"""Empty ASR is a saved result; technical failures and old subtitles stay distinct."""
import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.ui_preview import APPLICATION, pump
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QPlainTextEdit
from PySide6.QtTest import QSignalSpy
from core.subtitle_manager import SubtitleManager, SubtitleStatus
from core.subtitle_renderer import ASSRenderer
from control.app_controller import AppController
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subs_ui.subtitle_dialog_logic import SubtitleToolsDialogLogic
from ui.subs_ui.subtitle_model import SubtitleTableModel
from subtitle.mode import SubtitleMode
from subtitle.converter import refined_to_subtitles
from worker import AIWorker
from tests import test_asr_coverage as asr_tests
from tests.empty_subtitle_contracts import before_empty_changes, EDITS
from tests.empty_subtitle_process_fixture import finish_empty_in_spawn

ROOT = Path(__file__).resolve().parents[1]


class EmptyPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='botube-empty-asr-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.probe = asr_tests.ProductionOrchestrationTests()

    def test_completed_empty_asr_and_recovery_export_empty_files_without_translation(self):
        result, _, constructor, repair = self.probe.run_pipeline(
            ROOT / 'app/ai/pipeline.py', self.root, primary=[], recovery=[])
        self.assertEqual(result, dict(media_id='same-media-id', segments=[]))
        self.assertEqual(repair.call_args.args[3], [])
        constructor.assert_called_once()
        self.probe.pipeline_translation.translate_pipeline.assert_not_called()
        self.probe.pipeline_translation.clear_translator.assert_not_called()
        self.probe.pipeline_online.translate_online_pipeline.assert_not_called()
        self.assertEqual(self.probe.pipeline_progress[-1][0], 100)
        for suffix in ('srt', 'lrc'):
            self.assertEqual((self.root / f'subtitles/source/{suffix}/song.{suffix}').read_bytes(), b'')

    def test_all_filtered_credit_text_is_saved_empty_not_reinserted_as_lyrics(self):
        raw = [asr_tests.segment(1, 9, '作詞・作曲・編曲 初音ミク')]
        result, _, _, repair = self.probe.run_pipeline(ROOT / 'app/ai/pipeline.py', self.root, primary=raw)
        self.assertEqual(repair.call_args.args[3], [])
        self.assertEqual(result['segments'], [])

    def test_optional_coverage_failure_with_empty_primary_does_not_fail_job(self):
        def configure(namespace, model):
            namespace['repair_missing_subtitles'].side_effect = RuntimeError('VAD unavailable')
        result, _, _, _ = self.probe.run_pipeline(ROOT / 'app/ai/pipeline.py', self.root,
                                                 primary=[], configure=configure)
        self.assertEqual(result['segments'], [])

    def test_real_asr_error_export_failure_and_cancel_are_not_saved_as_no_lyrics(self):
        def asr_error(namespace, model):
            model.transcribe.side_effect = RuntimeError('decoder failed')
        def export_error(namespace, model):
            namespace['export_srt'] = Mock(side_effect=OSError('disk full'))
        for configure, cancel, error in ((asr_error, None, RuntimeError),
                                         (export_error, None, OSError),
                                         (None, lambda: True, RuntimeError)):
            with self.subTest(configure=configure, cancelled=bool(cancel)):
                with self.assertRaises(error):
                    self.probe.run_pipeline(ROOT / 'app/ai/pipeline.py', self.root,
                        primary=[], configure=configure, cancel_cb=cancel)
                self.probe.pipeline_translation.translate_pipeline.assert_not_called()


class TemporaryStorageFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='botube-empty-save-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = SubtitleManager(str(self.root / 'storage'))
        self.media = self.root / 'instrumental.mp4'
        self.media.write_bytes(b'test media fingerprint')
        self.media_id = self.manager.get_reliable_id(self.media)


class EmptyStorageTests(TemporaryStorageFixture, unittest.TestCase):

    def test_empty_result_saves_original_schema_and_header_only_ass_and_reopens_without_rerender(self):
        path = self.manager.save_segments(self.media_id, [], str(self.media))
        self.assertTrue(path)
        source = self.manager.get_raw_data(self.media_id)
        self.assertEqual(source, dict(media_id=self.media_id, original_name='instrumental', segments=[]))
        self.assertEqual(self.manager.get_segments_for_ui(self.media_id), [])
        self.assertIn('[Events]', Path(path).read_text(encoding='utf-8-sig'))
        self.assertNotIn('Dialogue:', Path(path).read_text(encoding='utf-8-sig'))
        before = {p: p.read_bytes() for p in self.manager.base_dir.rglob('*') if p.is_file()}
        reopened = SubtitleManager(str(self.root / 'storage'))
        with patch.object(reopened, 'render_ass_from_json', side_effect=AssertionError('No repeat rendering')):
            self.assertEqual(reopened.request_subtitle(self.media).status, SubtitleStatus.READY)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_empty_json_recovers_missing_ass_and_mode_render_keeps_zero_dialogue(self):
        self.manager.save_segments(self.media_id, [], str(self.media))
        self.manager.get_path(self.media_id, 'ass').unlink()
        self.assertEqual(self.manager.request_subtitle(self.media).status, SubtitleStatus.READY)
        for mode in SubtitleMode:
            with self.subTest(mode=mode):
                self.manager.set_mode(mode)
                self.assertTrue(self.manager.render_ass_from_json(self.media_id))
                self.assertTrue(self.manager._is_valid_ass(self.manager.get_path(self.media_id, 'ass')))
                self.assertNotIn('Dialogue:', self.manager.get_path(self.media_id, 'ass').read_text(encoding='utf-8-sig'))

    def test_invalid_json_or_ass_alone_is_not_cached_as_instrumental(self):
        ass = self.manager.get_path(self.media_id, 'ass')
        ASSRenderer.generate([], ass)
        source = self.manager.get_path(self.media_id, 'json')
        for data in (None, {}, {'segments': None}, {'segments': ''}, ['wrong root'], 'broken json'):
            with self.subTest(data=data):
                if data is None:
                    if source.exists():
                        source.unlink()
                else:
                    source.write_text(data if isinstance(data, str) else json.dumps(data), encoding='utf-8')
                self.assertFalse(self.manager._is_valid_ass(ass))
                self.assertEqual(self.manager.request_subtitle(self.media).status, SubtitleStatus.NEED_AI)

    def test_none_and_write_failure_are_not_completed_empty_results(self):
        self.assertIsNone(self.manager.save_segments(self.media_id, None))
        with patch('builtins.open', side_effect=PermissionError('read only')):
            with self.assertLogs('core.subtitle_manager', level='ERROR'):
                self.assertIsNone(self.manager.save_segments(self.media_id, [], str(self.media)))
        self.assertFalse(self.manager.get_path(self.media_id, 'json').exists())
        self.assertFalse(self.manager.get_path(self.media_id, 'ass').exists())
        self.assertEqual(self.manager.request_subtitle(self.media).status, SubtitleStatus.NEED_AI)

    def test_saving_empty_song_does_not_touch_existing_nonempty_song_bytes(self):
        old = refined_to_subtitles([dict(start=1, end=3, text='Old lyrics')], 'ja')
        self.manager.save_segments('old', old)
        paths = [self.manager.get_path('old', extension) for extension in ('json', 'ass')]
        before = [p.read_bytes() for p in paths]
        self.manager.save_segments(self.media_id, [], str(self.media))
        self.assertEqual([p.read_bytes() for p in paths], before)


class FakeAI(QObject):
    job_finished = Signal(str, list)
    job_failed = Signal(str, str)
    status_changed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.start = Mock()
        self.cancel = Mock()


class EmptyControllerTests(TemporaryStorageFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.layer = SubtitleLayer(initial_mode=SubtitleMode.JP)
        self.addCleanup(self.layer.deleteLater)
        self.ai = FakeAI()
        self.messages = []
        statusbar = SimpleNamespace(showMessage=lambda message, timeout: self.messages.append(message))
        self.window = SimpleNamespace(sub_layer=self.layer, statusBar=lambda: statusbar,
                                     media_player=SimpleNamespace(player=Mock()))
        self.controller = AppController(self.window, None, self.ai, self.manager)
        self.controller.current_media_id = self.media_id
        self.controller.current_media_item = SimpleNamespace(path=self.media)
        self.layer.load_subtitles([dict(start=0, end=10000, jp='Old lyrics')])
        self.layer.update_position(500)

    def test_worker_empty_callback_saves_hides_and_cached_reopen_does_not_start_ai(self):
        self.ai.job_finished.emit(self.media_id, [])
        self.assertEqual(self.manager.get_raw_data(self.media_id)['segments'], [])
        self.assertEqual(self.layer.subtitles, [])
        self.assertEqual(self.layer.text(), '')
        self.assertTrue(self.layer.isHidden())
        self.layer.update_position(1500)
        self.assertTrue(self.layer.isHidden())
        item = SimpleNamespace(id=self.media_id, path=self.media, title='Instrumental')
        self.controller.on_media_item_clicked(item)
        self.ai.start.assert_not_called()
        self.assertIn('Chưa nhận diện được lời', self.messages[-1])
        self.controller.on_media_item_clicked(item, force_gen=True)
        self.ai.start.assert_called_once_with(media_id=self.media_id, input_path=str(self.media))

    def test_switch_before_ai_finishes_clears_old_cues_and_stale_empty_result_is_ignored(self):
        item = SimpleNamespace(id=self.media_id, path=self.media, title='New song')
        self.controller.on_media_item_clicked(item, force_gen=True)
        self.assertEqual(self.layer.subtitles, [])
        self.layer.update_position(500)
        self.assertTrue(self.layer.isHidden())
        self.ai.job_finished.emit('old-media-id', [])
        self.assertIsNone(self.manager.get_raw_data('old-media-id'))
        self.assertIsNone(self.manager.get_raw_data(self.media_id))

    def test_failed_save_reports_failure_without_claiming_subtitle_ready(self):
        with patch.object(self.manager, 'save_segments', return_value=None):
            self.ai.job_finished.emit(self.media_id, [])
        self.assertIn('Không lưu được phụ đề', self.messages[-1])
        self.assertIsNone(self.manager.get_raw_data(self.media_id))

    def test_editor_loads_empty_source_as_zero_rows_instead_of_showing_raw_json(self):
        self.manager.save_segments(self.media_id, [], str(self.media))
        table = SubtitleTableModel([dict(start=0, end=1, text='Old text')])
        editor = QPlainTextEdit()
        label = QLabel()
        self.addCleanup(editor.deleteLater)
        self.addCleanup(label.deleteLater)
        parent = SimpleNamespace(app_controller=self.controller)
        fixture = SimpleNamespace(parent=lambda: parent, raw_data=None, sub_path=None,
            editor_orig=editor, lbl_info=label,
            _update_combined_table_ui=lambda segments: table.set_segments(segments))
        self.assertTrue(SubtitleToolsDialogLogic.load_from_media_file(fixture, self.media_id))
        self.assertEqual(table.rowCount(), 0)
        self.assertEqual(editor.toPlainText(), '')


class EmptyWorkerTests(unittest.TestCase):
    def test_real_qthread_spawn_queue_returns_empty_list_as_data_ready_without_failure(self):
        with tempfile.TemporaryDirectory(prefix='botube-empty-spawn-') as directory:
            worker = AIWorker('empty', 'synthetic.wav', directory)
            ready, failed = QSignalSpy(worker.data_ready), QSignalSpy(worker.failed)
            context = multiprocessing.get_context('spawn')
            def make_process(*, target, kwargs):
                from worker import _ai_process_wrapper
                self.assertIs(target, _ai_process_wrapper)
                return context.Process(target=finish_empty_in_spawn, kwargs=kwargs)
            proxy = SimpleNamespace(Process=make_process)
            try:
                with patch('worker.multiprocessing.get_context', return_value=proxy):
                    worker.start()
                    deadline = time.monotonic() + 15
                    while worker.isRunning() and time.monotonic() < deadline:
                        pump(20)
                    self.assertFalse(worker.isRunning())
                    worker.wait(1000)
                    APPLICATION.processEvents()
                self.assertEqual(ready.count(), 1)
                self.assertEqual(ready.at(0), ['empty', []])
                self.assertEqual(failed.count(), 0)
                self.assertIsNone(worker._process)
                self.assertIsNone(worker._queue)
                self.assertFalse((Path(directory) / 'error_log.txt').exists())
            finally:
                worker.stop()
                worker.deleteLater()


class EmptySourceGates(unittest.TestCase):
    def test_only_explicit_empty_result_edits_change_the_four_captured_sources(self):
        for relative in EDITS:
            with self.subTest(source=relative):
                before_empty_changes(relative)

    def test_timing_refinement_except_reviewed_phrase_edits_and_worker_are_unchanged(self):
        baseline = json.loads((ROOT / 'docs/restored-app-baseline.json').read_text(encoding='utf-8'))
        worker_hash = next(row['sha256'] for row in baseline['sources'] if row['path'] == 'app/worker.py')
        self.assertEqual(hashlib.sha256((ROOT / 'app/worker.py').read_bytes()).hexdigest(), worker_hash)
        from tests.lyric_phrase_contracts import before_phrase_changes
        self.assertEqual(before_phrase_changes(),
                         (ROOT / 'docs/subtitle-timing/original/lyric_refinement.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
