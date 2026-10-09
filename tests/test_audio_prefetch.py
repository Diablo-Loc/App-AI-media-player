"""One next track, same worker, current audio untouched, foreground wins."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import QThread, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from tools.ui_preview import isolated_window, pump
from core.audio_profile import AudioProfile
from control.audio_prefetch import next_audio_source
from tests import test_audio_start as selection_fixtures
from tests.test_audio_effects import wait_until, FFMPEG, FFPROBE
from tests.audio_prefetch_contracts import before_prefetch_changes

ROOT = Path(__file__).resolve().parents[1]


class NextSourceTests(unittest.TestCase):
    def test_equality_full_queue_wrap_missing_current_and_duplicates_match_old_navigation(self):
        a = SimpleNamespace(id=1, path='A.mp4', title='A')
        b = SimpleNamespace(id=1, path='B.mp4', title='B')
        c = SimpleNamespace(id=2, path='C.mp4', title='C')
        queue = [a, b, c]
        prior = queue.copy()
        self.assertEqual(next_audio_source(queue, a, 'A.mp4'), 'B.mp4')
        self.assertEqual(next_audio_source(queue, c, 'C.mp4'), 'A.mp4')
        self.assertEqual(next_audio_source([c, a, b], a, 'A.mp4'), 'B.mp4')
        self.assertEqual(next_audio_source(queue, SimpleNamespace(id=7), 'X.mp4'), 'A.mp4')
        self.assertIsNone(next_audio_source([], a, 'A.mp4'))
        self.assertIsNone(next_audio_source([a], a, 'A.mp4'))
        self.assertIsNone(next_audio_source(queue, None, 'A.mp4'))
        self.assertEqual(queue, prior)


class PrefetchPlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Share fixture builder, not its tests; sources/derived cache are temporary.
        selection_fixtures.AudioSelectionTests.setUpClass()
        fixture = selection_fixtures.AudioSelectionTests
        cls.source, cls.next, cls.result = fixture.source, fixture.next, fixture.result

    @classmethod
    def tearDownClass(cls):
        selection_fixtures.AudioSelectionTests.tearDownClass()

    def ready(self, window):
        player, c = window.media_player.player, window.audio_effects
        window.audio_output.setMuted(True)
        player.setSource(QUrl.fromLocalFile(str(self.source)))
        player.play()
        wait_until(lambda: player.position() > 100)
        c._request_timer.stop()
        c._pending = False
        c.profile = AudioProfile(False, 'gentle')
        c._measurement = dict(lufs=-10, peak_db=-1, silent=False)
        a = SimpleNamespace(id='A', path=self.source, title='A')
        b = SimpleNamespace(id='B', path=self.next, title='B')
        window.current_media_item = a
        window.active_playlist = [a, b]
        return c, player, a, b

    def start(self, c):
        c.prefetch.timer.stop()
        c.prefetch._start()
        self.assertIsNotNone(c.worker)
        self.assertTrue(c.worker.prefetch)

    def test_prefetch_completes_without_source_state_or_gain_changes_and_only_once(self):
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            original = player.source()
            volume = window.audio_output.volume()
            output, video, device, rate = player.audioOutput(), player.videoOutput(), window.audio_output.device(), player.playbackRate()
            changes = []
            player.sourceChanged.connect(changes.append)
            states = []
            player.playbackStateChanged.connect(states.append)
            with patch('control.audio_effects.prepare_audio', return_value=self.result) as prepare:
                self.start(c)
                wait_until(lambda: c.worker is None)
                c.prefetch._start()
                self.assertEqual(prepare.call_count, 1)
            self.assertEqual(player.source(), original)
            self.assertEqual(changes, [])
            self.assertEqual(states, [])
            self.assertEqual(window.audio_output.volume(), volume)
            self.assertIs(player.audioOutput(), output)
            self.assertIs(player.videoOutput(), video)
            self.assertEqual(window.audio_output.device(), device)
            self.assertEqual(player.playbackRate(), rate)
            self.assertFalse(c.prefetch.budget.isActive())

    def test_same_next_selection_promotes_inflight_job_without_second_worker(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow) as prepare:
                self.start(c)
                worker = c.worker
                try:
                    c.play_source(QUrl.fromLocalFile(str(self.next)))
                    self.assertIs(c.worker, worker)
                    self.assertFalse(worker.prefetch)
                    self.assertFalse(worker.isInterruptionRequested())
                    self.assertNotEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
                finally:
                    release.set()
                wait_until(lambda: c.worker is None and not c.switching and player.position() > 100)
                pump(220)
                self.assertEqual(prepare.call_count, 1)
            self.assertEqual(c._original, QUrl.fromLocalFile(str(self.next)))

    def test_other_selection_cancels_prefetch_without_gui_wait_and_latest_wins(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            sources = []
            def slow(source, *args):
                sources.append(source)
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                self.start(c)
                old = c.worker
                try:
                    with patch.object(old, 'wait', side_effect=AssertionError('GUI must not wait')):
                        c.play_source(QUrl.fromLocalFile(str(self.source)))
                    self.assertTrue(old.isInterruptionRequested())
                finally:
                    release.set()
                wait_until(lambda: not c.switching and player.position() > 100 and c.worker is None)
            self.assertEqual([Path(path) for path in sources], [self.next, self.source])
            self.assertEqual(c._original, QUrl.fromLocalFile(str(self.source)))

    def test_disable_pause_slider_stall_and_budget_cancel_only_prefetch(self):
        for action in ('disable', 'pause', 'slider', 'stall', 'budget', 'seek'):
            release = threading.Event()
            with self.subTest(action=action), isolated_window() as (window, root):
                c, player, a, b = self.ready(window)
                def slow(*args):
                    release.wait(5)
                    return self.result
                with patch('control.audio_effects.prepare_audio', side_effect=slow):
                    self.start(c)
                    worker = c.worker
                    try:
                        with patch.object(worker, 'wait', side_effect=AssertionError('GUI must not wait')):
                            if action == 'disable':
                                c.set_prefetch(False)
                            elif action == 'pause':
                                player.pause()
                            elif action == 'slider':
                                window.playback_bar.time_slider.sliderPressed.emit()
                            elif action == 'stall':
                                c.prefetch._status_changed(QMediaPlayer.MediaStatus.StalledMedia)
                            elif action == 'seek':
                                c.prefetch._position_changed(100)
                                c.prefetch._position_changed(4000)
                            else:
                                c.prefetch._expired()
                        self.assertTrue(worker.isInterruptionRequested())
                    finally:
                        release.set()
                    wait_until(lambda: c.worker is None)
                self.assertEqual(player.source(), QUrl.fromLocalFile(str(self.source)))

    def test_ai_busy_defers_then_retries_without_starting_a_model(self):
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            ai_worker = QThread()
            window.job_manager = SimpleNamespace(_worker=ai_worker)
            with patch.object(ai_worker, 'isRunning', return_value=True):
                c.prefetch._start()
                self.assertIsNone(c.worker)
                self.assertTrue(c.prefetch.timer.isActive())
            with patch('control.audio_effects.prepare_audio', return_value=self.result):
                self.start(c)
                wait_until(lambda: c.worker is None)

    def test_error_does_not_touch_current_status_or_retry_until_context_changes(self):
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            c.panel.set_status('Current audio ready')
            with patch('control.audio_effects.prepare_audio', side_effect=RuntimeError('bad next file')) as prepare:
                self.start(c)
                wait_until(lambda: c.worker is None)
                c.prefetch._start()
                self.assertEqual(prepare.call_count, 1)
                self.assertEqual(c.panel.status.text(), 'Current audio ready')
            self.assertIsNone(c._failed_request)
            self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)

    def test_shuffle_refresh_preserves_master_and_cancels_old_next(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            other = SimpleNamespace(id='C', path=Path('C:/other.mp4'), title='C')
            queue = [a, b, other]
            window.active_playlist = queue
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                self.start(c)
                worker = c.worker
                try:
                    window.active_playlist = [a, other, b]
                    c.playback_queue_changed()
                    self.assertTrue(worker.isInterruptionRequested())
                    self.assertEqual(Path(next_audio_source(window.active_playlist, a, str(self.source))), Path('C:/other.mp4'))
                    self.assertEqual(queue, [a, b, other])
                finally:
                    release.set()
                wait_until(lambda: c.worker is None)

    def test_user_toggle_persists_only_audio_setting_and_off_never_prefetches(self):
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            c.panel.set_profile(False, 'gentle')
            c.panel.open_at(window.playback_bar.btn_audio)
            pump(30)
            from PySide6.QtWidgets import QLabel
            for label in c.panel.findChildren(QLabel):
                if label.wordWrap():
                    self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
            c.panel.prefetch_next.setChecked(False)
            self.assertFalse(c.prefetch_enabled)
            saved = json.loads(c.settings_path.read_text())
            self.assertFalse(saved['prefetch_next'])
            self.assertEqual(saved['tone'], 'gentle')
            c.prefetch._start()
            self.assertIsNone(c.worker)
            c.profile = AudioProfile(True, 'off')
            c.prefetch_enabled = True
            c.prefetch._start()
            self.assertIsNone(c.worker)
            c.panel.set_profile(True, 'off')
            self.assertFalse(c.panel.prefetch_next.isEnabled())

    def test_shutdown_reaps_active_prefetch_and_stops_owned_timers(self):
        release = threading.Event()
        with isolated_window() as (window, root):
            c, player, a, b = self.ready(window)
            def slow(*args):
                release.wait(5)
                return self.result
            with patch('control.audio_effects.prepare_audio', side_effect=slow):
                self.start(c)
                release.set()
                c.shutdown()
            self.assertIsNone(c.worker)
            self.assertFalse(c.prefetch.timer.isActive())
            self.assertFalse(c.prefetch.budget.isActive())


class ScopeTests(unittest.TestCase):
    def test_exact_reviewed_adapters_preserve_old_gates_and_processor(self):
        manifest = json.loads((ROOT / 'docs/audio-prefetch/reviewed-sources.json').read_text())
        self.assertEqual(set(manifest['app/ui/main_window.py']['changed_functions']), {'MainWindow.toggle_global_shuffle'})
        for relative in manifest:
            before_prefetch_changes(relative)
        hashes = json.loads((ROOT / 'docs/audio-prefetch/new-source-hashes.json').read_text())
        for relative, digest in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
