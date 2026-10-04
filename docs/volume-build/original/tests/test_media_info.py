"""Actual source metadata, responsive Qt requests, cancellation and old contracts."""
import ast
from collections import OrderedDict
import copy
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
from unittest.mock import patch

from tools.ui_preview import APPLICATION, isolated_window, pump
from PySide6.QtCore import QTimer, QUrl
from control.worker_lifecycle import OwnedProcesses
from ui import media_info_probe as probe
from ui.video_info_popup import VideoInfoPopup
from tests.media_info_contracts import before_media_info_changes

ROOT = Path(__file__).resolve().parents[1]
INFO = {'streams': [
    {'codec_type': 'video', 'codec_name': 'av1', 'width': 1080, 'height': 1080,
     'avg_frame_rate': '25/1', 'display_aspect_ratio': '1:1'},
    {'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '44100',
     'channels': 2, 'channel_layout': 'stereo', 'bit_rate': '128000'}],
    'format': {'duration': '12.5', 'tags': {'DESCRIPTION': 'tag\r\ntext'}}}


def wait_for(predicate, timeout=6):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        pump(5)
    if not predicate():
        raise AssertionError('Metadata request did not finish')


def run_read(path, cache=None, description=''):
    return probe.read_media_info(probe.item_snapshot({'path': str(path), 'description': description}),
                                 OrderedDict() if cache is None else cache, OwnedProcesses(), lambda: False)


class MetadataParsingTests(unittest.TestCase):
    def test_actual_av1_square_fps_aac_values_not_extension_guesses(self):
        fields = probe.stream_fields(INFO)
        self.assertEqual(fields['v_codec'], 'av1')
        self.assertEqual(fields['resolution'], '1080 × 1080')
        self.assertEqual(fields['aspect'], '1:1')
        self.assertEqual(fields['fps'], '25 FPS (trung bình)')
        self.assertEqual(fields['a_codec'], 'aac')
        self.assertEqual(fields['sample_rate'], '44100 Hz')
        self.assertEqual(fields['channels'], '2 kênh (stereo)')
        self.assertEqual(fields['bitrate'], '128.0 kbps')

    def test_cover_art_unknown_vbr_and_default_audio_selection(self):
        info = {'streams': [
            {'codec_type': 'video', 'codec_name': 'mjpeg', 'disposition': {'attached_pic': 1}},
            {'codec_type': 'audio', 'codec_name': 'aac', 'bit_rate': '96000'},
            {'codec_type': 'audio', 'codec_name': 'flac', 'channels': 6, 'sample_rate': '96000',
             'disposition': {'default': 1}}], 'format': {'bit_rate': '900000'}}
        fields = probe.stream_fields(info)
        self.assertEqual(fields['v_codec'], 'Không có')
        self.assertEqual(fields['resolution'], 'N/A')
        self.assertEqual(fields['a_codec'], 'flac')
        self.assertEqual(fields['bitrate'], probe.UNKNOWN)  # Container bitrate is not audio bitrate.
        self.assertEqual(fields['channels'], '6 kênh')

    def test_missing_streams_invalid_rational_and_pixel_aspect(self):
        self.assertEqual(probe.stream_fields({})['a_codec'], 'Không có')
        info = {'streams': [{'codec_type': 'video', 'width': 720, 'height': 576,
                            'avg_frame_rate': '0/0', 'r_frame_rate': '30000/1001',
                            'display_aspect_ratio': '0:0', 'sample_aspect_ratio': '16:15'}]}
        self.assertEqual(probe.stream_fields(info)['aspect'], '4:3')
        self.assertEqual(probe.stream_fields(info)['fps'], '29.97 FPS (danh định)')
        for value in ('NaN', 'inf', '0/0', '-1', None):
            self.assertIsNone(probe.positive(value))

    def test_description_precedence_dict_object_sidecars_tags_plain_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '日本.mp4'
            path.write_bytes(b'fixture')
            for index, sidecar in enumerate(probe.sidecars(path)):
                sidecar.write_text(json.dumps({'description': f'sidecar {index}\r\n日本 <b>'}), encoding='utf-8')
            with patch.object(probe, 'probe_file', return_value=INFO):
                self.assertEqual(run_read(path, description='item\r\ntext')['description'], 'item\ntext')
                self.assertEqual(run_read(path)['description'], 'sidecar 0\n日本 <b>')
                probe.sidecars(path)[0].write_text('invalid JSON', encoding='utf-8')
                self.assertEqual(run_read(path)['description'], 'sidecar 1\n日本 <b>')
                for sidecar in probe.sidecars(path):
                    sidecar.unlink()
                self.assertEqual(run_read(path)['description'], 'tag\ntext')
            item = SimpleNamespace(file_path=str(path), description='old', title='日本')
            self.assertEqual(probe.item_snapshot(item)['path'], str(path))
            self.assertEqual(item.description, 'old')

    def test_cache_hit_invalidation_source_sidecar_and_lru_bound(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'probe_file', return_value=INFO) as ffprobe:
            path = Path(directory) / 'source.mp4'
            path.write_bytes(b'one')
            cache = OrderedDict()
            run_read(path, cache)
            run_read(path, cache)
            self.assertEqual(ffprobe.call_count, 1)
            path.write_bytes(b'source changed')
            run_read(path, cache)
            self.assertEqual(ffprobe.call_count, 2)
            sidecar = probe.sidecars(path)[0]
            sidecar.write_text('{"description":"new"}', encoding='utf-8')
            self.assertEqual(run_read(path, cache)['description'], 'new')
            self.assertEqual(ffprobe.call_count, 3)
            for index in range(probe.CACHE_LIMIT + 4):
                run_read(path, cache, description=str(index))
            self.assertEqual(len(cache), probe.CACHE_LIMIT)

    def test_errors_keep_description_retry_and_changed_source_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.mp4'
            path.write_bytes(b'one')
            cache = OrderedDict()
            with patch.object(probe, 'probe_file', side_effect=TimeoutError('timeout')):
                result = run_read(path, cache, 'existing description')
            self.assertEqual(result['description'], 'existing description')
            self.assertEqual(set(result['stream'].values()), {probe.UNKNOWN})
            self.assertIn('timeout', result['error'])
            self.assertEqual(len(cache), 0)
            def mutate(*args):
                path.write_bytes(b'changed during probe')
                return INFO
            with patch.object(probe, 'probe_file', side_effect=mutate):
                self.assertTrue(run_read(path, cache)['error'])
            self.assertEqual(len(cache), 0)
            self.assertTrue(run_read(Path(directory) / 'missing')['error'])

    def test_missing_format_duration_retains_existing_metadata_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.mkv'
            path.write_bytes(b'fixture')
            item = probe.item_snapshot({'path': str(path), 'duration': 125})
            cache = OrderedDict()
            with patch.object(probe, 'probe_file', return_value={'streams': [], 'format': {}}):
                result = probe.read_media_info(item, cache, OwnedProcesses(), lambda: False)
                item['duration'] = 126
                updated = probe.read_media_info(item, cache, OwnedProcesses(), lambda: False)
            self.assertEqual(result['general']['duration'], '02:05 (125.00 giây)')
            self.assertEqual(updated['general']['duration'], '02:06 (126.00 giây)')


class MetadataQtTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'original.mp4'
        self.path.write_bytes(b'fixture')
        self.popup = VideoInfoPopup()

    def tearDown(self):
        self.popup.reject()
        probe.media_info_owner().shutdown()
        self.popup.deleteLater()
        pump(20)
        self.temp.cleanup()

    def test_slow_probe_keeps_gui_responsive_and_cached_reopen_does_not_probe(self):
        entered, release = threading.Event(), threading.Event()
        calls, threads, ticks = [], [], []
        def slow(path, processes, cancelled):
            calls.append(str(path))
            threads.append(threading.get_ident())
            entered.set()
            while not release.wait(.01):
                if cancelled():
                    raise InterruptedError()
            return INFO
        timer = QTimer()
        timer.setInterval(5)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            with patch.object(probe, 'probe_file', side_effect=slow):
                self.popup.update_info({'path': str(self.path), 'title': 'actual'})
                self.popup.show()
                wait_for(entered.is_set)
                pump(60)
                self.assertGreater(len(ticks), 3)
                self.assertNotEqual(threads[0], threading.get_ident())
                self.assertEqual(self.popup.fields_stream['v_codec'].text(), 'Đang đọc…')
                release.set()
                wait_for(lambda: self.popup._info_requests.worker is None)
                self.assertEqual(self.popup.fields_stream['resolution'].text(), '1080 × 1080')
                self.popup.update_info({'path': str(self.path)})
                wait_for(lambda: self.popup._info_requests.worker is None)
                self.assertEqual(len(calls), 1)
        finally:
            release.set()
            timer.stop()

    def test_latest_selection_single_worker_pending_coalescing_and_close(self):
        entered, release = threading.Event(), threading.Event()
        active, maximum, calls = 0, 0, []
        other = Path(self.temp.name) / 'next.wav'
        other.write_bytes(b'next')
        def slow(path, processes, cancelled):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            calls.append(path.name)
            try:
                if len(calls) == 1:
                    entered.set()
                    release.wait(2)  # Deliberately emits a stale result after cancellation.
                return INFO
            finally:
                active -= 1
        with patch.object(probe, 'probe_file', side_effect=slow):
            self.popup.update_info({'path': str(self.path)})
            self.popup.show()
            wait_for(entered.is_set)
            self.popup.update_info({'path': str(other), 'description': 'intermediate'})
            self.popup.update_info({'path': str(other), 'description': 'latest'})
            release.set()
            wait_for(lambda: self.popup._info_requests.worker is None)
            self.assertEqual(calls, ['original.mp4', 'next.wav'])
            self.assertEqual(maximum, 1)
            self.assertEqual(self.popup.description_edit.toPlainText(), 'latest')
            self.assertEqual(self.popup.fields_gen['filename'].text(), 'next.wav')
            self.popup.update_info({'path': str(other), 'description': 'cancelled'})
            self.popup.reject()
            wait_for(lambda: self.popup._info_requests.worker is None)
            self.assertNotEqual(self.popup.description_edit.toPlainText(), 'cancelled tag')
            self.assertIsNone(self.popup._info_requests.pending)

    def test_modal_exec_close_cancels_and_empty_selection_clears_old_rows(self):
        def slow(path, processes, cancelled):
            while not cancelled():
                time.sleep(.005)
            raise InterruptedError()
        with patch.object(probe, 'probe_file', side_effect=slow):
            self.popup.update_info({'path': str(self.path)})
            QTimer.singleShot(40, self.popup.reject)
            self.popup.show_above_widget()
            wait_for(lambda: self.popup._info_requests.worker is None)
        self.popup.update_info(None)
        self.assertEqual(self.popup.fields_stream['a_codec'].text(), probe.UNKNOWN)
        self.assertEqual(self.popup.description_edit.toPlainText(), 'Không có mô tả')

    def test_shell_visible_switch_original_path_player_owners_and_shutdown(self):
        with isolated_window() as (window, root):
            player = window.media_player.player
            audio, video, source = player.audioOutput(), player.videoOutput(), player.source()
            bar = window.playback_bar
            other = Path(self.temp.name) / 'second.wav'
            other.write_bytes(b'next')
            with patch.object(probe, 'probe_file', return_value=INFO) as tool:
                bar.set_media_info('original', item_data=SimpleNamespace(path=str(self.path)))
                bar.info_popup.update_info(bar._current_item_data)
                bar.info_popup.show()
                wait_for(lambda: bar.info_popup._info_requests.worker is None)
                bar.set_media_info('second', item_data=SimpleNamespace(path=str(other)))
                wait_for(lambda: bar.info_popup._info_requests.worker is None)
                self.assertEqual(bar.info_popup.fields_gen['path'].text(), str(other))
                self.assertEqual(tool.call_args[0][0], other.resolve())
            self.assertEqual(player.source(), source)
            self.assertIs(player.audioOutput(), audio)
            self.assertIs(player.videoOutput(), video)
            entered = threading.Event()
            def stalled(path, processes, cancelled):
                entered.set()
                while not cancelled():
                    time.sleep(.005)
                raise InterruptedError()
            owner = bar.info_popup._info_requests.owner
            with patch.object(probe, 'probe_file', side_effect=stalled):
                bar.info_popup.update_info({'path': str(other), 'description': 'uncached'})
                wait_for(entered.is_set)
                workers = tuple(owner.workers)
                window.close()
                self.assertTrue(owner.closed)
                self.assertTrue(all(not worker.isRunning() for worker in workers))


class MetadataProcessTests(unittest.TestCase):
    def test_real_timeout_and_cancellation_reap_owned_process_without_gui_wait(self):
        # A sleeping child replaces ffprobe; the production poll/reap code stays real.
        original_popen = subprocess.Popen
        children = []
        def sleeping(*args, **kwargs):
            child = original_popen([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
            children.append(child)
            return child
        with patch.object(probe.subprocess, 'Popen', side_effect=sleeping):
            processes = OwnedProcesses()
            with self.assertRaises(TimeoutError):
                probe.probe_file(ROOT / 'unused.mp4', processes, lambda: False, timeout=.1)
            self.assertIsNotNone(children[-1].poll())
            self.assertEqual(processes.processes, set())
            started = time.monotonic()
            processes = OwnedProcesses()
            with self.assertRaises(InterruptedError):
                probe.probe_file(ROOT / 'unused.mp4', processes, lambda: time.monotonic() - started > .1)
            self.assertIsNotNone(children[-1].poll())
            self.assertEqual(processes.processes, set())

    def test_real_mp4_wav_flac_probe_and_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            for ext, options, codec in (
                ('mp4', ['-c:a', 'aac', '-b:a', '128k'], 'AAC'),
                ('wav', ['-c:a', 'pcm_s16le'], 'PCM'),
                ('flac', ['-c:a', 'flac'], 'FLAC')):
                path = Path(directory) / ('actual.' + ext)
                cmd = [str(ROOT / 'bin/ffmpeg.exe'), '-v', 'error', '-f', 'lavfi', '-i',
                       'sine=frequency=440:sample_rate=44100:duration=1', '-ac', '2', *options, str(path)]
                subprocess.run(cmd, capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                result = run_read(path)
                self.assertEqual(result['error'], '')
                self.assertIn(codec.lower(), result['stream']['a_codec'].lower())
                self.assertEqual(result['stream']['v_codec'], 'Không có')
                self.assertEqual(result['stream']['sample_rate'], '44100 Hz')
                self.assertTrue(result['stream']['channels'].startswith('2 kênh'))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


class MetadataScopeTests(unittest.TestCase):
    def test_exact_three_source_adapters_and_no_other_ast_changes(self):
        manifest = json.loads((ROOT / 'docs/media-info/reviewed-sources.json').read_text())
        expected = {
            'app/ui/main_window.py': (['MainWindow.closeEvent'], []),
            'app/ui/playback_bar.py': (['PlaybackBar.set_media_info'], []),
            'app/ui/video_info_popup.py': (['VideoInfoPopup.__init__', 'VideoInfoPopup.update_info',
                                          'VideoInfoPopup.get_description_for_item'], ['VideoInfoPopup._apply_info']),
            'tests/test_ui_media_surface.py':
                (['PresentationAdapterSourceGate.test_original_functions_remain_identical_after_removing_only_adapters'], [])}
        self.assertEqual(set(manifest), set(expected))
        for relative, (changed, added) in expected.items():
            self.assertEqual(manifest[relative]['changed_functions'], changed)
            self.assertEqual(manifest[relative]['added_functions'], added)
            before = ast.parse(before_media_info_changes(relative))
            after = ast.parse((ROOT / relative).read_bytes())
            old_classes = {n.name: n for n in before.body if isinstance(n, ast.ClassDef)}
            for cls in [n for n in after.body if isinstance(n, ast.ClassDef)]:
                old_methods = {n.name: n for n in old_classes[cls.name].body if isinstance(n, ast.FunctionDef)}
                cls.body = [old_methods[n.name] if isinstance(n, ast.FunctionDef) and f'{cls.name}.{n.name}' in changed else n
                            for n in cls.body if not (isinstance(n, ast.FunctionDef) and f'{cls.name}.{n.name}' in added)]
            if relative.endswith('video_info_popup.py'):
                # The only module-level change is the new helper import / four unused imports removed.
                new_imports = [ast.dump(n) for n in after.body if isinstance(n, (ast.Import, ast.ImportFrom))]
                old_imports = [ast.dump(n) for n in before.body if isinstance(n, (ast.Import, ast.ImportFrom))
                               and not (isinstance(n, ast.Import) and n.names[0].name in ('os', 'sys', 'json', 'subprocess'))]
                helper = ast.parse('from .media_info_probe import MediaInfoRequests, item_snapshot, read_media_info, UNKNOWN').body[0]
                self.assertEqual(new_imports, old_imports + [ast.dump(helper)])
                after.body = [n for n in after.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
                before.body = [n for n in before.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
            self.assertEqual(ast.dump(before), ast.dump(after), relative)
        helper = json.loads((ROOT / 'docs/media-info/helper-hash.json').read_text())
        for relative, sha in helper.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), sha)


if __name__ == '__main__':
    unittest.main()
