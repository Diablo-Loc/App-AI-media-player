"""Fault recovery, saved-data compatibility, translation completeness and ownership."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.ui_preview import APPLICATION, isolated_window, pump
from tools.current_flow_audit import isolated_function
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QSignalSpy
from core.subtitle_manager import SubtitleManager, SubtitleStatus
from core import subtitle_persistence as persistence
from subtitle.model import Subtitle, SubtitleLine
from translate import pipeline
from translate import online_logic
from translate.cache import TranslationCache
from control.ai_controller import AIController
from control.library_scan import LibraryScanQueue
from control.worker_lifecycle import OwnedProcesses, WorkerOwner, editor_worker_owner
from worker import AIWorker
# Keep Qt wrapper modules resident across patch.dict(sys.modules) UI fixtures.
from ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parents[1]


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        pump(5)
    if not predicate():
        raise AssertionError('Timed out waiting for owned worker completion')


class TemporaryStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='botube-reliability-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)


class SubtitleSaveTests(TemporaryStore):
    def setUp(self):
        super().setUp()
        self.manager = SubtitleManager(str(self.root / 'storage'))
        self.media = self.root / 'song.mp4'
        self.media.write_bytes(b'ID fixture')
        self.media_id = self.manager.get_reliable_id(self.media)
        self.old = Subtitle(1.25, 2.5, SubtitleLine('Original lyric', 'en', 'EN'))
        self.new = Subtitle(3.25, 4.5, SubtitleLine('New lyric', 'en', 'EN'))
        self.assertTrue(self.manager.save_segments(self.media_id, [self.old], str(self.media)))
        self.paths = [self.manager.get_path(self.media_id, ext) for ext in ('json', 'ass')] + [self.manager.index_file]
        self.before = [path.read_bytes() for path in self.paths]

    def assert_original(self):
        self.assertEqual([path.read_bytes() for path in self.paths], self.before)

    def test_render_false_or_exception_keeps_all_old_files_and_index(self):
        for failure in (False, OSError('synthetic renderer error')):
            with self.subTest(failure=failure), patch('core.subtitle_renderer.ASSRenderer.generate') as render:
                if isinstance(failure, Exception):
                    render.side_effect = failure
                else:
                    render.return_value = failure
                self.assertIsNone(self.manager.save_segments(self.media_id, [self.new], str(self.root / 'rename.mp4')))
                self.assert_original()
                self.assertEqual(self.manager.index_cache[self.media_id], 'song')

    def test_json_encoding_failure_does_not_truncate_saved_file(self):
        self.assertFalse(self.manager._save_json_file(self.paths[0], {'bad': object()}))
        self.assert_original()

    def test_second_replace_failure_rolls_back_json_ass_and_index(self):
        real_replace = persistence.os.replace
        failed = False
        def replacing(source, target):
            nonlocal failed
            if Path(target) == self.paths[1].resolve() and not failed:
                failed = True
                raise PermissionError('synthetic ASS publish failure')
            return real_replace(source, target)
        with patch.object(persistence.os, 'replace', side_effect=replacing):
            self.assertIsNone(self.manager.save_segments(self.media_id, [self.new], str(self.root / 'renamed.mp4')))
        self.assertTrue(failed)
        self.assert_original()
        self.assertEqual(self.manager.request_subtitle(self.media).status, SubtitleStatus.READY)

    def test_interrupted_publication_recovers_only_owned_transaction_on_reopen(self):
        unrelated = self.manager.base_dir / 'user-reference.srt'
        unrelated.write_bytes(b'user file untouched')
        real_replace = persistence.os.replace
        def replacing(source, target):
            if Path(target) == self.paths[1].resolve():
                raise SystemExit('synthetic process interruption between publications')
            return real_replace(source, target)
        with patch.object(persistence.os, 'replace', side_effect=replacing), self.assertRaises(SystemExit):
            self.manager.save_segments(self.media_id, [self.new], str(self.media))
        self.assertNotEqual(self.paths[0].read_bytes(), self.before[0])
        reopened = SubtitleManager(str(self.root / 'storage'))
        self.assert_original()
        self.assertEqual(reopened.request_subtitle(self.media).status, SubtitleStatus.READY)
        self.assertEqual(unrelated.read_bytes(), b'user file untouched')

    def test_success_keeps_old_schema_and_final_marker_timing(self):
        self.new._botube_final_timing = True
        result = self.manager.save_segments(self.media_id, [self.new], str(self.media))
        self.assertTrue(result)
        saved = self.manager.get_raw_data(self.media_id)
        self.assertEqual(set(saved), {'media_id', 'original_name', 'segments'})
        self.assertEqual(saved['segments'], [dict(start=3.25, end=4.5, jp='New lyric', en='', vi='')])
        self.assertIn('0:00:03.25,0:00:04.50', Path(result).read_text(encoding='utf-8-sig'))

    def test_old_load_is_read_only_and_never_realigns_or_migrates(self):
        reopened = SubtitleManager(str(self.root / 'storage'))
        with patch.object(reopened, 'render_ass_from_json', side_effect=AssertionError('Unexpected regeneration')):
            self.assertEqual(reopened.request_subtitle(self.media).status, SubtitleStatus.READY)
            self.assertTrue(reopened.get_segments_for_ui(self.media_id))
        self.assert_original()

    def test_editor_failure_does_not_report_success_or_close(self):
        dialogs = Mock()
        from ui.subs_ui.subtitle_dialog_logic import SubtitleToolsDialogLogic
        fixture = SimpleNamespace(sync_context_from_parent=Mock(), _resolve_subtitle_path=lambda: str(self.paths[0]),
            tabs=SimpleNamespace(currentIndex=lambda: 0), _parse_tab_orig=lambda: [dict(start=1, end=2, text='Edited')],
            parent=lambda: SimpleNamespace(app_controller=SimpleNamespace(subtitle_mgr=self.manager)),
            media_id=self.media_id, detected_lang='en', accept=Mock())
        with patch('ui.subs_ui.subtitle_dialog_logic.QMessageBox', dialogs), \
                patch.object(self.manager, '_save_bundle', return_value=False):
            SubtitleToolsDialogLogic.save_subtitle_content(fixture)
        dialogs.warning.assert_called_once()
        dialogs.information.assert_not_called()
        fixture.accept.assert_not_called()
        self.assert_original()

    def test_external_editor_write_failure_does_not_truncate_imported_file(self):
        from ui.subs_ui.subtitle_dialog_logic import SubtitleToolsDialogLogic
        path = self.root / 'imported.srt'
        path.write_bytes(b'old imported subtitle')
        dialogs = Mock()
        fixture = SimpleNamespace(sync_context_from_parent=Mock(), _resolve_subtitle_path=lambda: str(path),
            tabs=SimpleNamespace(currentIndex=lambda: 0), _parse_tab_orig=lambda: [dict(start=1, end=2, text='Edited')],
            parent=lambda: None, media_id=None, detected_lang='en', accept=Mock(),
            editor_orig=SimpleNamespace(toPlainText=lambda: 'new subtitle'))
        with patch('ui.subs_ui.subtitle_dialog_logic.QMessageBox', dialogs), \
                patch.object(persistence.os, 'replace', side_effect=PermissionError('synthetic file locked')):
            SubtitleToolsDialogLogic.save_subtitle_content(fixture)
        self.assertEqual(path.read_bytes(), b'old imported subtitle')
        dialogs.critical.assert_called_once()
        dialogs.information.assert_not_called()
        fixture.accept.assert_not_called()


class TranslationTests(TemporaryStore):
    def setUp(self):
        super().setUp()
        self.cache_path = self.root / 'translation.json'
        self.cache_patch = patch.object(pipeline, 'TranslationCache', side_effect=lambda: TranslationCache(self.cache_path))
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.torch_patch = patch.dict(sys.modules, {'torch': SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))})
        self.torch_patch.start()
        self.addCleanup(self.torch_patch.stop)

    def rows(self, texts=('First sentence', 'Second sentence')):
        return [Subtitle(i, i+1, SubtitleLine(text, 'en', 'EN')) for i, text in enumerate(texts)]

    def test_failed_translation_is_not_cached_and_next_attempt_can_succeed(self):
        broken = Mock()
        broken.translate_batch.side_effect = OSError('synthetic model failure')
        with patch.object(pipeline, 'get_translator', return_value=broken), self.assertRaises(RuntimeError):
            pipeline.translate_pipeline(self.rows(), src_lang='en')
        self.assertFalse(self.cache_path.exists())
        healthy = Mock()
        healthy.translate_batch.return_value = ['Câu thứ nhất', 'Câu thứ hai']
        with patch.object(pipeline, 'get_translator', return_value=healthy):
            result = pipeline.translate_pipeline(self.rows(), src_lang='en')
        self.assertEqual([row.bottom.text for row in result], ['Câu thứ nhất', 'Câu thứ hai'])

    def test_old_blank_cache_is_ignored_without_migrating_it_on_read(self):
        cache = TranslationCache(self.cache_path)
        cache.data[cache._key('First sentence')] = {'vi': '', 'en': 'First sentence'}
        self.cache_path.write_text(json.dumps(cache.data), encoding='utf-8')
        before = self.cache_path.read_bytes()
        reopened = TranslationCache(self.cache_path)
        self.assertIsNone(reopened.get('First sentence'))
        reopened.save()
        self.assertEqual(self.cache_path.read_bytes(), before)

    def test_all_valid_cache_hits_skip_model_initialization_and_file_write(self):
        cache = TranslationCache(self.cache_path)
        for text in ('First sentence', 'Second sentence'):
            cache.set(text, {'vi': 'Lời dịch cũ', 'en': text})
        cache.save()
        before = self.cache_path.read_bytes()
        with patch.object(pipeline, 'get_translator', side_effect=AssertionError('Unexpected model load')):
            result = pipeline.translate_pipeline(self.rows(), src_lang='en')
        self.assertEqual([s.bottom.text for s in result], ['Lời dịch cũ', 'Lời dịch cũ'])
        self.assertEqual(self.cache_path.read_bytes(), before)

    def test_malformed_legacy_cache_entries_are_ignored_without_rewriting_file(self):
        key = TranslationCache(self.cache_path)._key('First sentence')
        for data in ([1, 2], {key: 'broken'}, {key: {'vi': 7}}, {key: {'vi': 'Dịch cũ', 'en': 9}}):
            self.cache_path.write_text(json.dumps(data), encoding='utf-8')
            before = self.cache_path.read_bytes()
            cache = TranslationCache(self.cache_path)
            self.assertIsNone(cache.get('First sentence'))
            cache.save()
            self.assertEqual(self.cache_path.read_bytes(), before)

    def test_short_response_retries_individual_rows_without_shift_into_next_batch(self):
        translator = Mock()
        translator.translate_batch.side_effect = lambda texts, **kw: [f'vi:{texts[0]}'] if len(texts) > 1 else [f'vi:{texts[0]}']
        source = ['A', 'B', 'C', 'D']
        result = pipeline.run_safe_batch(translator, source, 'en', 'vi', batch_size=2)
        self.assertEqual(result, ['vi:A', 'vi:B', 'vi:C', 'vi:D'])
        self.assertEqual(translator.translate_batch.call_count, 6)

    def test_source_repeats_and_long_lyrics_are_passed_in_full(self):
        repeated = 'Stay with me ' * 4
        long_text = 'This is a valid lyric with many different words. ' * 30
        translator = Mock()
        translator.translate_batch.return_value = ['Hãy ở bên tôi', 'Một bản dịch']
        pipeline.run_safe_batch(translator, [repeated, long_text], 'en', 'vi')
        self.assertEqual(translator.translate_batch.call_args.args[0], [repeated.strip(), long_text.strip()])
        for count in (2, 3, 4):
            self.assertEqual(pipeline.clean_repetitive_text(('Stay with me ' * count).strip()), ('Stay with me ' * count).strip())
        self.assertLess(len(pipeline.clean_repetitive_text('ha ' * 100).split()), 10)
        cache = TranslationCache(self.cache_path)
        for count in (2, 3, 4):
            refrain = ('Never say never ' * count).strip()
            cache.set(refrain, {'vi': ('Đừng bao giờ ' * count).strip(), 'en': refrain})
            self.assertIsNotNone(cache.get(refrain))
        self.assertFalse(cache._is_spam('This translation is long but contains meaningful words. ' * 5))

    def online(self, response, rows):
        settings = Mock()
        settings.value.side_effect = lambda key, default=None: default
        request = Mock()
        request.post.return_value.json.return_value = {'choices': [{'message': {'content': response}}]}
        namespace = dict(
            QSettings=Mock(return_value=settings),
            requests=request,
            re=__import__('re'),
            SubtitleLine=SubtitleLine,
            _semantic_review_ids=online_logic._semantic_review_ids,
            _post_provider_once_with_retry=lambda url, label, **kwargs: request.post(url, **kwargs),
        )
        translate = isolated_function('app/translate/online_logic.py', 'translate_online_pipeline', namespace)
        return translate(rows, 'OpenAI (GPT-4o)', 'synthetic-key', 'Synthetic song')

    def test_online_invalid_partial_duplicate_or_empty_rows_do_not_mutate_source(self):
        for response in ('wrong format', '0===First===Một', '0===First===Một\n0===Again===Hai',
                         '0===First===Một\n1===Second===', '-1===Bad===Sai\n0===First===Một'):
            with self.subTest(response=response):
                rows = self.rows()
                self.assertIsNone(self.online(response, rows))
                self.assertTrue(all(s.middle is None and s.bottom is None for s in rows))
                self.assertEqual([s.top.text for s in rows], ['First sentence', 'Second sentence'])

    def test_online_complete_out_of_order_ids_map_to_original_times(self):
        rows = self.rows()
        result = self.online('1===Second===Hai\n0===First===Một', rows)
        self.assertIs(result, rows)
        self.assertEqual([s.bottom.text for s in result], ['Một', 'Hai'])
        self.assertEqual([(s.start, s.end) for s in result], [(0, 1), (1, 2)])


class AsyncJobTests(TemporaryStore):
    def controller(self):
        state = patch('control.ai_controller._RESOURCE_CHECK_CACHE', {'checked': True, 'ready': True})
        state.start()
        self.addCleanup(state.stop)
        installer = SimpleNamespace(check_resource_status=Mock(), _set_resource_ready_flag=Mock(), _get_resource_ready_flag=Mock())
        imports = patch.dict(sys.modules, {'download_core.download_source_app': installer})
        imports.start()
        self.addCleanup(imports.stop)
        controller = AIController(str(self.root))
        self.addCleanup(controller.abort_all_jobs)
        return controller

    def test_restart_is_nonblocking_latest_request_wins_and_stale_results_ignored(self):
        entered = threading.Event()
        launched = []
        class Old(AIWorker):
            def run(self):
                entered.set()
                while not self._cancelled:
                    self.msleep(1)
                self.msleep(150)
                self.data_ready.emit(self.media_id, ['stale'])
        class New(AIWorker):
            def run(self):
                launched.append(self.media_id)
                self.data_ready.emit(self.media_id, ['fresh'])
        controller = self.controller()
        old = Old('old', 'unused', str(self.root))
        controller._worker, controller._current_media_id = old, 'old'
        old.finished.connect(controller._on_thread_stopped)
        old.finished.connect(old.deleteLater)
        old.data_ready.connect(controller._on_data_ready)
        old.start()
        self.assertTrue(entered.wait(2))
        spy = QSignalSpy(controller.job_finished)
        with patch('control.ai_controller.AIWorker', New):
            controller.start('discard', 'unused')
            self.assertTrue(old.isRunning())
            controller.start('latest', 'unused')
            ticks = []
            timer = QTimer()
            timer.setInterval(5)
            timer.timeout.connect(lambda: ticks.append(1))
            timer.start()
            wait_until(lambda: spy.count() == 1)
            timer.stop()
            self.assertGreater(len(ticks), 2)
            self.assertEqual(launched, ['latest'])
            self.assertEqual(spy.at(0), ['latest', ['fresh']])
            wait_until(lambda: controller._worker is None)

    def test_cancel_or_shutdown_prevents_queued_restart(self):
        class Delayed(AIWorker):
            def run(self):
                while not self._cancelled:
                    self.msleep(1)
                self.msleep(30)
        for shutdown in (False, True):
            controller = self.controller()
            with patch('control.ai_controller.AIWorker', Delayed):
                controller.start('old', 'unused')
                wait_until(lambda: controller._worker.isRunning())
                controller.start('pending', 'unused')
                if shutdown:
                    controller.abort_all_jobs()
                else:
                    controller.cancel()
                pump(100)
                self.assertIsNone(controller._pending_start)
                self.assertIsNone(controller._worker)

    def test_scan_is_background_latest_folder_and_concurrent_edits_are_preserved(self):
        from core.media_library import MediaLibrary, MediaMetadata
        with patch('core.media_library.SubtitleManager', return_value=SubtitleManager(str(self.root / 'ids'))):
            library = MediaLibrary(str(self.root / 'cache.json'))
        first, second = self.root / 'first', self.root / 'second'
        first.mkdir(); second.mkdir()
        (first / 'a.mp4').write_bytes(b'first')
        (second / 'b.mp4').write_bytes(b'second')
        entered = threading.Event()
        thread_checks = []
        def metadata(path):
            thread_checks.append(QThread.currentThread() != APPLICATION.thread())
            entered.set()
            time.sleep(0.08)
            return Path(path).stem, 'Artist', 5
        queue = LibraryScanQueue(library)
        self.addCleanup(queue.shutdown)
        spy = QSignalSpy(queue.completed)
        with patch('core.media_library.get_raw_metadata', side_effect=metadata):
            queue.request(str(first))
            wait_until(entered.is_set)
            queue.request(str(second))
            wait_until(lambda: spy.count() == 1)
        self.assertTrue(all(thread_checks))
        result = spy.at(0)[0]
        self.assertEqual([Path(s.path).name for s in result], ['b.mp4'])
        self.assertNotIn(library.subtitle_mgr.get_reliable_id(first / 'a.mp4'), library.items)
        wait_until(lambda: queue.writer is None)
        current = result[0]
        current.duration = 0
        entered.clear()
        with patch('core.media_library.get_raw_metadata', side_effect=metadata):
            queue.request(str(second))
            wait_until(entered.is_set)
            current.title, current.thumbnail = 'User edited title', 'new-thumbnail.jpg'
            wait_until(lambda: spy.count() == 2)
        self.assertIs(spy.at(1)[0][0], current)
        self.assertEqual((current.title, current.thumbnail, current.duration), ('User edited title', 'new-thumbnail.jpg', 5))


    def test_background_cache_io_does_not_hold_metadata_lock(self):
        from core.media_library import MediaLibrary, MediaMetadata
        from control.library_scan import CacheWriter
        with patch('core.media_library.SubtitleManager', return_value=SubtitleManager(str(self.root / 'ids'))):
            library = MediaLibrary(str(self.root / 'cache.json'))
        library.items['one'] = MediaMetadata('one', 'one.mp4', 'Old title')
        entered, release = threading.Event(), threading.Event()
        real_dump = json.dump
        def slow_dump(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError('Probe did not release owned cache writer')
            return real_dump(*args, **kwargs)
        writer = CacheWriter(library)
        try:
            with patch('core.media_library.json.dump', side_effect=slow_dump):
                writer.start()
                self.assertTrue(entered.wait(2))
                acquired = library.lock.acquire(blocking=False)
                try:
                    self.assertTrue(acquired, 'Disk I/O must not block GUI metadata access')
                    library.items['one'].title = 'User edit during cache I/O'
                finally:
                    if acquired:
                        library.lock.release()
                    release.set()
                self.assertTrue(writer.wait(2000))
        finally:
            release.set()
            writer.wait()
        library.save()
        self.assertEqual(json.loads(library.db_path.read_text(encoding='utf-8'))['one']['title'], 'User edit during cache I/O')

    def test_main_window_async_scan_commits_full_playlist_and_empty_folder_clears_view(self):
        with isolated_window() as (window, root):
            folder = root / 'media-fixture'
            folder.mkdir()
            for name in ('a.mp4', 'b.mp4'):
                (folder / name).write_bytes(b'ID fixture')
            entered = threading.Event()
            def metadata(path):
                entered.set()
                time.sleep(0.03)
                return Path(path).stem, 'Artist', 5
            with patch('core.media_library.get_raw_metadata', side_effect=metadata), \
                    patch.object(window.content_ctrl, 'set_new_data') as publish:
                window.load_folder_content(str(folder))
                self.assertTrue(hasattr(window, '_folder_scan_queue'))
                wait_until(lambda: publish.call_count == 1)
                self.assertEqual(len(window.all_media_items), 2)
                self.assertEqual({s.id for s in window.foryou_page.get_playback_playlist()}, {s.id for s in window.all_media_items})
                empty = root / 'empty-fixture'
                empty.mkdir()
                window.load_folder_content(str(empty))
                wait_until(lambda: window._folder_scan_queue.worker is None and not window._folder_scan_queue.pending and not window._folder_scan_queue.timer.isActive())
                self.assertEqual(window.all_media_items, [])
                self.assertEqual(window.foryou_page.get_playback_playlist(), [])


class WorkerShutdownTests(TemporaryStore):
    def test_cancel_registration_race_terminates_newly_owned_process(self):
        owner = OwnedProcesses()
        owner.stop()
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        owner.track(process)
        owner.wait()
        self.assertIsNotNone(process.poll())
        self.assertFalse(owner.processes)

    def test_download_and_title_shutdown_kill_actual_owned_update_process(self):
        from download_core.download_worker import DownloadWorker
        from download_core.get_title_worker import GetTitleWorker
        for cls in (DownloadWorker, GetTitleWorker):
            with self.subTest(worker=cls.__name__):
                processes = []
                real_popen = subprocess.Popen
                def spawn(*args, **kwargs):
                    process = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
                    processes.append(process)
                    return process
                worker = cls([], [], str(self.root)) if cls is DownloadWorker else cls([])
                owner = WorkerOwner()
                owner.own(worker)
                module = 'download_core.download_worker' if cls is DownloadWorker else 'download_core.get_title_worker'
                with patch(module + '.ensure_ytdlp_exists', return_value=True), patch(module + '.subprocess.Popen', side_effect=spawn):
                    worker.start()
                    wait_until(lambda: bool(processes))
                    owner.shutdown()
                self.assertFalse(worker.isRunning())
                self.assertTrue(all(p.poll() is not None for p in processes))
                pump(20)
                self.assertFalse(owner.workers)

    def test_dialog_owner_retains_cancelled_translation_until_thread_finishes(self):
        class Slow(QThread):
            def run(self):
                while not self.isInterruptionRequested():
                    self.msleep(1)
                self.msleep(40)
        owner = editor_worker_owner()
        worker = Slow()
        owner.own(worker)
        worker.start()
        wait_until(worker.isRunning)
        worker.requestInterruption()
        self.assertIn(worker, owner.workers)
        wait_until(lambda: not owner.workers)

    def test_close_main_window_waits_for_download_and_editor_workers(self):
        from download_core.download_worker import DownloadWorker
        class DelayedTranslation(QThread):
            def run(self):
                while not self.isInterruptionRequested():
                    self.msleep(1)
                self.msleep(40)
        with isolated_window() as (window, root):
            processes = []
            real_popen = subprocess.Popen
            def spawn(*args, **kwargs):
                process = real_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
                processes.append(process)
                return process
            download = DownloadWorker([], [], str(root))
            window.download_page._worker_owner.own(download)
            translation = DelayedTranslation()
            owner = editor_worker_owner()
            owner.own(translation)
            with patch('download_core.download_worker.ensure_ytdlp_exists', return_value=True), \
                    patch('download_core.download_worker.subprocess.Popen', side_effect=spawn):
                download.start()
                translation.start()
                wait_until(lambda: bool(processes) and translation.isRunning())
                window.close()
                self.assertFalse(download.isRunning())
                self.assertFalse(translation.isRunning())
                self.assertTrue(all(process.poll() is not None for process in processes))
            pump(30)
            self.assertFalse(owner.workers)
            self.assertFalse(window.download_page._worker_owner.workers)

    def test_stop_during_actual_download_stage_reaps_owned_process(self):
        from download_core.download_worker import DownloadWorker
        processes = []
        real_popen = subprocess.Popen
        def spawn(command, **kwargs):
            delay = 0 if command[1] == '-U' else 30
            process = real_popen([sys.executable, '-c', f'import time; time.sleep({delay})'], **kwargs)
            processes.append(process)
            return process
        worker = DownloadWorker(['synthetic-link'], ['Synthetic title'], str(self.root))
        owner = WorkerOwner()
        owner.own(worker)
        with patch('download_core.download_worker.ensure_ytdlp_exists', return_value=True), \
                patch('download_core.download_worker.subprocess.Popen', side_effect=spawn):
            worker.start()
            wait_until(lambda: len(processes) == 2)
            owner.shutdown()
            self.assertFalse(worker.isRunning())
        self.assertTrue(all(process.poll() is not None for process in processes))
        pump(20)

    def test_no_late_editor_callbacks_after_close(self):
        from ui.subs_ui.subtitle_dialog_logic import SubtitleToolsDialogLogic
        fixture = SimpleNamespace(_workers_closed=True)
        for name, args in (('_on_translation_finished', ([],)), ('_on_translation_error', ('error',)),
                           ('_on_align_finished', ([], 0)), ('_on_align_error', ('error',))):
            getattr(SubtitleToolsDialogLogic, name)(fixture, *args)


class ReviewedScopeTests(unittest.TestCase):
    def test_exact_reviewed_snapshots_restore_previous_phase_and_asr_timing_hook_stay_unchanged(self):
        from tests.reliability_contracts import before_reliability_changes
        manifest = json.loads((ROOT / 'docs/reliability/reviewed-sources.json').read_text(encoding='utf-8'))
        for relative, entry in manifest.items():
            original = ROOT / 'docs/reliability/original' / relative
            self.assertEqual(before_reliability_changes(relative, raw=True), original.read_bytes())
            self.assertNotIn('app/run_app.py', manifest)
        inventory = json.loads((ROOT / 'docs/current-flow-audit/probe-results.json').read_text(encoding='utf-8'))['inventory']['files']
        from tests.subtitle_presentation_contracts import before_presentation_changes
        for relative in ('app/run_app.py', 'app/worker.py', 'app/ai/pipeline.py', 'app/pipeline/asr_coverage.py',
                         'app/pipeline/lyric_refinement.py', 'app/pipeline/lyric_phrases.py', 'app/ui/subs_ui/subtitle_layer.py'):
            self.assertEqual(hashlib.sha256(before_presentation_changes(relative, raw=True)).hexdigest(), inventory[relative]['sha256'], relative)
        helpers = json.loads((ROOT / 'docs/reliability/new-source-hashes.json').read_text(encoding='utf-8'))
        for relative, expected in helpers.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
