"""Actual Qt selections stay stopped until EQ is ready; stale requests never play."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace

from tools.ui_preview import isolated_window, pump
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from core.audio_profile import AudioProfile
from core.audio_effects import AudioPlaybackCache, prepare_audio
from control.worker_lifecycle import OwnedProcesses
from tests.test_audio_effects import command, wait_until, FFMPEG, FFPROBE
from tests.audio_start_contracts import before_start_changes
from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]


class AudioSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'original.mp4'
        cls.next = cls.root / 'next.mp4'
        command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:r=25',
                 '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000', '-t', '8',
                 '-c:v', 'mpeg4', '-c:a', 'aac', '-b:a', '128k', str(cls.source)])
        cls.next.write_bytes(cls.source.read_bytes())
        cls.hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (cls.source, cls.next)}
        with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
            cls.result = prepare_audio(str(cls.source), AudioProfile(False, 'gentle'), 0,
                                       AudioPlaybackCache(cls.root / 'cache'), OwnedProcesses(), lambda: False)
            cls.balanced = prepare_audio(str(cls.source), AudioProfile(False, 'balanced'), 0,
                                       AudioPlaybackCache(cls.root / 'cache'), OwnedProcesses(), lambda: False)

    @classmethod
    def tearDownClass(cls):
        for path, digest in cls.hashes.items():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        cls.temp.cleanup()

    def setup_gate(self, window):
        controller, player = window.audio_effects, window.media_player.player
        window.audio_output.setMuted(True)
        controller.profile = AudioProfile(True, 'gentle')
        return controller, player

    def assert_waiting(self, controller, player):
        wait_until(lambda: controller.worker is not None)
        wait_until(lambda: player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia)
        pump(80)
        self.assertNotEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.assertEqual(player.position(), 0)
        self.assertTrue(controller.switching)
        self.assertFalse(controller._start_indicator.isHidden())

    def test_cold_selection_starts_processed_source_once_without_original_playback(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            output, video, device = player.audioOutput(), player.videoOutput(), window.audio_output.device()
            controller.set_volume(0.37)
            played = []
            player.playbackStateChanged.connect(lambda state: played.append(player.source())
                if state == QMediaPlayer.PlaybackState.PlayingState else None)
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                try:
                    self.assert_waiting(controller, player)
                    self.assertEqual(played, [])
                finally:
                    release.set()
                wait_until(lambda: not controller.switching and player.position() > 100)
            self.assertEqual(played, [QUrl.fromLocalFile(self.result['path'])])
            self.assertTrue(window.audio_output.isMuted())
            self.assertIs(player.audioOutput(), output)
            self.assertIs(player.videoOutput(), video)
            self.assertEqual(window.audio_output.device(), device)
            self.assertAlmostEqual(controller.volume(), 0.37)
            self.assertTrue(controller._start_indicator.isHidden())
            self.assertFalse(controller._start_timer.isActive())

    def test_pending_pause_seek_rate_and_hardware_intent_are_preserved(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                try:
                    self.assert_waiting(controller, player)
                    window._hardware_pause()
                    window._hardware_pause()  # Explicit pause stays paused.
                    self.assertFalse(controller.pending_playback())
                    window._hardware_play()
                    window._hardware_play()  # Explicit play does not toggle off.
                    self.assertTrue(controller.pending_playback())
                    window.mini_player.play_req.emit()
                    self.assertFalse(controller.pending_playback())
                    window.on_seek_move(2000)
                    controller._seek_requested(2000)
                    window.change_playback_speed(1.5)
                finally:
                    release.set()
                wait_until(lambda: not controller.switching and controller.worker is None)
            self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
            self.assertAlmostEqual(player.position(), 2000, delta=35)
            self.assertEqual(player.playbackRate(), 1.5)
            window.toggle_play_pause()
            wait_until(lambda: player.position() > 2100)

    def test_off_while_waiting_resumes_original_and_discards_late_eq(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                try:
                    self.assert_waiting(controller, player)
                    controller.set_profile(False, 'off')
                    wait_until(lambda: player.position() > 100)
                finally:
                    release.set()
                wait_until(lambda: controller.worker is None)
                pump(220)
            self.assertEqual(player.source(), QUrl.fromLocalFile(str(self.source)))
            self.assertFalse(controller.switching)

    def test_error_and_timeout_fall_back_to_original_without_automatic_retry(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout), isolated_window() as (window, root):
                controller, player = self.setup_gate(window)
                def failed(*args):
                    raise RuntimeError('fixture preparation failed')
                with patch('control.audio_effects.prepare_audio', side_effect=failed):
                    controller.play_source(QUrl.fromLocalFile(str(self.source)))
                    if timeout:
                        controller._start_failed()
                    wait_until(lambda: not controller.switching and player.position() > 100)
                self.assertEqual(player.source(), QUrl.fromLocalFile(str(self.source)))
                self.assertFalse(controller._start_timer.isActive())
                self.assertIsNotNone(controller._failed_request)

    def test_rapid_selection_cancels_old_result_and_shutdown_reaps_worker(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            played = []
            player.playbackStateChanged.connect(lambda state: played.append(player.source())
                if state == QMediaPlayer.PlaybackState.PlayingState else None)
            def slow(source, *args):
                release.wait(5)
                if Path(source) == self.next:
                    raise RuntimeError('latest fixture falls back')
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                try:
                    self.assert_waiting(controller, player)
                    controller.play_source(QUrl.fromLocalFile(str(self.next)))
                    self.assertEqual(played, [])
                finally:
                    release.set()
                wait_until(lambda: player.position() > 100 and controller.worker is None)
            self.assertEqual(played, [QUrl.fromLocalFile(str(self.next))])
            controller.profile = AudioProfile(False, 'gentle')
            controller.play_source(QUrl.fromLocalFile(str(self.source)))
            controller.shutdown()
            self.assertIsNone(controller.worker)
            self.assertFalse(controller._start_timer.isActive())
            self.assertTrue(controller._start_indicator.isHidden())

    def test_changing_eq_during_wait_only_starts_the_latest_profile(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            played = []
            player.playbackStateChanged.connect(lambda state: played.append(player.source())
                if state == QMediaPlayer.PlaybackState.PlayingState else None)
            def slow(source, profile, *args):
                release.wait(5)
                return self.balanced if profile.tone == 'balanced' else self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                try:
                    self.assert_waiting(controller, player)
                    controller.set_profile(True, 'balanced')
                finally:
                    release.set()
                wait_until(lambda: not controller.switching and player.position() > 100)
            self.assertEqual(played, [QUrl.fromLocalFile(self.balanced['path'])])

    def test_bad_prepared_decoder_returns_to_original_without_stuck_wait(self):
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            trace = []
            player.mediaStatusChanged.connect(lambda status: trace.append((str(status), player.source().toLocalFile(),
                str(player.playbackState()), str(controller._transition), str(controller._starting))))
            invalid = dict(self.result, path=str(root / 'missing.mkv'))
            with patch('control.audio_effects.prepare_audio', return_value=invalid):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                try:
                    wait_until(lambda: not controller.switching and player.position() > 100)
                except AssertionError:
                    self.fail(str(trace))
            self.assertEqual(player.source(), QUrl.fromLocalFile(str(self.source)))
            self.assertTrue(controller._start_indicator.isHidden())

    def test_cached_selection_has_no_artificial_delay_and_repeat_selection_starts_at_zero(self):
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            with patch('control.audio_effects.prepare_audio', return_value=self.result):
                for _ in range(2):
                    controller.play_source(QUrl.fromLocalFile(str(self.source)))
                    wait_until(lambda: not controller.switching and player.position() > 100)
                    self.assertEqual(player.source(), QUrl.fromLocalFile(self.result['path']))
                    self.assertEqual(player.activeVideoTrack(), 0)
                    self.assertFalse(controller._start_timer.isActive())
                    self.assertLess(player.position(), 1000)

    def test_normalization_only_still_plays_original_immediately(self):
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            controller.profile = AudioProfile(True, 'off')
            with patch('control.audio_effects.measure_loudness', return_value={
                    'measurement': dict(lufs=-10, peak_db=-1, silent=False)}):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                wait_until(lambda: player.position() > 100)
            self.assertIsNone(controller._starting)
            self.assertEqual(player.source(), QUrl.fromLocalFile(str(self.source)))
            self.assertTrue(controller._start_indicator.isHidden())

    def test_main_selection_keeps_playlist_subtitle_dispatch_and_wait_controls(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            item = SimpleNamespace(id='start-fixture', title='Selected song', artist='Artist',
                                   path=self.source, thumbnail=None)
            window.app_controller = Mock()
            window.active_playlist = [item]
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                window.on_media_clicked(item, update_playlist=False)
                window.audio_output.setMuted(True)
                try:
                    self.assert_waiting(controller, player)
                    self.assertEqual(window.current_media_item, item)
                    self.assertEqual(window.active_playlist, [item])
                    window.app_controller.on_media_item_clicked.assert_called_once_with(item, force_gen=False)
                    window.playback_bar.btn_play.click()
                finally:
                    release.set()
                wait_until(lambda: not controller.switching)
            self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)

    def test_selection_from_reentrant_seek_wins_over_old_fallback_resume(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            controller, player = self.setup_gate(window)
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                controller.play_source(QUrl.fromLocalFile(str(self.source)))
                try:
                    self.assert_waiting(controller, player)
                    controller._starting['ready'] = True
                    with patch.object(player, 'setPosition', side_effect=lambda position:
                                      controller.play_source(QUrl.fromLocalFile(str(self.next)))):
                        controller._finish_start()
                    self.assertEqual(controller._starting['source'], QUrl.fromLocalFile(str(self.next)))
                    self.assertNotEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
                finally:
                    release.set()
                    controller.shutdown()


class SourceScopeTests(unittest.TestCase):
    def test_only_selection_controls_and_owned_audio_orchestration_changed(self):
        manifest = json.loads((ROOT / 'docs/audio-start/reviewed-sources.json').read_text())
        self.assertEqual(set(manifest), {'app/ui/main_window.py', 'app/control/audio_effects.py',
                                       'app/ui/audio_effects_panel.py'})
        self.assertEqual(set(manifest['app/ui/main_window.py']['changed_functions']), {
            'MainWindow.on_media_clicked', 'MainWindow.toggle_play_pause',
            'MainWindow._hardware_play', 'MainWindow._hardware_pause', 'MainWindow.sync_mini_player_state'})
        for relative in manifest:
            before_start_changes(relative)
        original = before_start_changes('app/ui/main_window.py')
        current = (ROOT / 'app/ui/main_window.py').read_text(encoding='utf-8')
        old_functions, new_functions = functions(original), functions(current)
        for name in old_functions:
            if name not in manifest['app/ui/main_window.py']['changed_functions']:
                self.assertEqual(old_functions[name], new_functions[name], name)


if __name__ == '__main__':
    unittest.main()
