"""Regression tests for hardware media keys (SMTC), WASAPI stop responsiveness, and History skip filtering."""
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from tools.ui_preview import isolated_window, pump
from PySide6.QtMultimedia import QMediaPlayer

from ui.system_media_manager import SystemMediaManager
from core.audio_stream_engine import AudioStreamEngine
from core.audio_profile import AudioProfile
from core.media_library import MediaMetadata


class _FakeNativeLib:
    """Stub native AudioEngineNative.dll tracking exact lifecycle calls."""

    def __init__(self):
        self.calls = []
        self.restart_called = 0
        self.start_called = 0
        self.stop_called = 0
        self.status_calls = []

    def StopEngine(self, _engine):
        self.stop_called += 1
        self.calls.append("StopEngine")

    def StartEngine(self, _engine):
        self.start_called += 1
        self.calls.append("StartEngine")
        return True

    def RestartEngine(self, _engine):
        self.restart_called += 1
        self.calls.append("RestartEngine")
        return True

    def SetPlaybackStatus(self, _engine, playing):
        self.status_calls.append(bool(playing))
        self.calls.append(("SetPlaybackStatus", bool(playing)))

    def UpdateMetadata(self, _engine, title, artist):
        self.calls.append(("UpdateMetadata", title, artist))

    def ReleaseEngine(self, _engine):
        self.calls.append("ReleaseEngine")


def _make_stub_smtc_manager() -> tuple[SystemMediaManager, _FakeNativeLib]:
    """Build a SystemMediaManager without touching real AudioEngineNative.dll."""
    with patch("sys.platform", "linux"):
        mgr = SystemMediaManager(None)
    fake_lib = _FakeNativeLib()
    mgr.lib = fake_lib
    mgr.engine = 0x1234
    mgr.enabled = True
    return mgr, fake_lib


class HardwareMediaControlsTests(unittest.TestCase):
    def test_smtc_callback_queues_off_winrt_thread_debounces_and_never_calls_native_restart(self):
        mgr, fake_lib = _make_stub_smtc_manager()
        main_tid = threading.get_ident()
        delivered = []

        mgr.media_play.connect(lambda: delivered.append(("play", threading.get_ident() == main_tid)))
        mgr.media_pause.connect(lambda: delivered.append(("pause", threading.get_ident() == main_tid)))
        mgr.media_next.connect(lambda: delivered.append(("next", threading.get_ident() == main_tid)))
        mgr.media_prev.connect(lambda: delivered.append(("prev", threading.get_ident() == main_tid)))

        # Simulate a burst of 6 duplicate Next events arriving from a WinRT RPC thread.
        callback_elapsed = []

        def winrt_burst():
            t0 = time.perf_counter()
            for _ in range(6):
                mgr._native_media_callback(3)
            callback_elapsed.append(time.perf_counter() - t0)

        t = threading.Thread(target=winrt_burst)
        t.start()
        t.join(timeout=2.0)

        # WinRT callback must return immediately without executing GUI slots inline.
        self.assertEqual(len(callback_elapsed), 1)
        self.assertLess(callback_elapsed[0], 0.05)
        self.assertEqual(delivered, [])

        pump(40)
        # All 6 rapid duplicate Next events must collapse into exactly ONE GUI-thread delivery.
        self.assertEqual(delivered, [("next", True)])

        # Pending Play followed immediately by Pause coalesces to the latest intent (Pause).
        delivered.clear()
        mgr._native_media_callback(1)
        mgr._native_media_callback(2)
        pump(40)
        self.assertEqual(delivered, [("pause", True)])

        # restart() MUST NEVER call native RestartEngine() (which leaks SMTC ButtonPressed delegates).
        mgr.restart()
        self.assertEqual(fake_lib.restart_called, 0)
        self.assertEqual(fake_lib.start_called, 0)

        # Even when audio capture is opted in, restart() cycles StopEngine+StartEngine, never RestartEngine.
        mgr._numpy = MagicMock()
        mgr.set_audio_capture_enabled(True)
        self.assertEqual(fake_lib.start_called, 1)
        mgr.restart()
        self.assertEqual(fake_lib.restart_called, 0)
        self.assertGreaterEqual(fake_lib.stop_called, 1)
        self.assertEqual(fake_lib.start_called, 2)

        # Redundant set_playing(True) calls are deduplicated before hitting WinRT COM.
        mgr.set_playing(True)
        mgr.set_playing(True)
        mgr.set_playing(False)
        mgr.set_playing(False)
        self.assertEqual(fake_lib.status_calls, [True, False])

        mgr.close()

    def test_wasapi_stop_aborts_blocking_writer_immediately_and_caches_exclusive_format(self):
        engine = AudioStreamEngine()
        aborted = threading.Event()
        entered_write = threading.Event()

        class _BlockingStream:
            def abort(self):
                aborted.set()

            def close(self):
                pass

        # 1. Normal writer thread exits cleanly as soon as cancel_event fires (no concurrent abort race).
        cancel_fast = threading.Event()
        fast_entered = threading.Event()

        def _healthy_writer():
            fast_entered.set()
            cancel_fast.wait(timeout=1.0)

        w_fast = threading.Thread(target=_healthy_writer, daemon=True)
        w_fast.start()
        self.assertTrue(fast_entered.wait(timeout=1.0))
        engine._writer_thread = w_fast
        engine._active_stream = _BlockingStream()
        engine._active_stream_lock = threading.Lock()
        engine._active_stream_closed = [False]
        engine._cancel_event = cancel_fast
        engine._playing = True

        t_fast = time.perf_counter()
        engine.stop()
        self.assertLess(time.perf_counter() - t_fast, 0.12)
        self.assertFalse(aborted.is_set(), "Healthy writer must exit cleanly without racing Pa_AbortStream")

        # 2. Stalled DAC writer that ignores cancel_event still gets safely aborted after short grace window.
        def _stalled_writer():
            entered_write.set()
            aborted.wait(timeout=3.0)

        writer = threading.Thread(target=_stalled_writer, daemon=True)
        writer.start()
        self.assertTrue(entered_write.wait(timeout=1.0))

        engine._writer_thread = writer
        engine._active_stream = _BlockingStream()
        engine._active_stream_lock = threading.Lock()
        engine._active_stream_closed = [False]
        engine._cancel_event = threading.Event()
        engine._playing = True

        t0 = time.perf_counter()
        engine.stop()
        elapsed = time.perf_counter() - t0

        self.assertTrue(aborted.is_set(), "Stalled writer must be unblocked via stream.abort() fallback")
        self.assertFalse(writer.is_alive())
        # Old code waited 0.35 + 0.65 = 1.0s; bounded grace + abort finishes well under 0.45s.
        self.assertLess(elapsed, 0.45)

        # Verify Exclusive format cache avoids re-probing failing dtypes on consecutive tracks.
        open_attempts = []

        class _FakeWasapiSettings:
            def __init__(self, exclusive=False):
                self.exclusive = exclusive

        class _FakeSoundDevice:
            WasapiSettings = _FakeWasapiSettings

            @staticmethod
            def query_hostapis():
                return [{"name": "Windows WASAPI", "devices": [0], "default_output_device": 0}]

            @staticmethod
            def query_devices(_idx):
                return {"name": "Headphones (DAWN PRO2)", "max_output_channels": 2, "default_samplerate": 48000.0}

            @staticmethod
            def RawOutputStream(**kwargs):
                open_attempts.append((kwargs["samplerate"], kwargs["dtype"]))
                # Fail first 2 attempts (192000 int32 & int24), succeed on 192000 float32.
                if kwargs["samplerate"] == 192000 and kwargs["dtype"] == "float32":
                    return MagicMock()
                raise RuntimeError("format not supported")

        prof = AudioProfile(normalize=True, output_mode="exclusive", upsample="hires_sync")
        src_info = {"sample_rate": 48000, "channels": 2, "codec_name": "flac"}
        with patch.dict(sys.modules, {"sounddevice": _FakeSoundDevice}):
            _, _, sr1, dt1, mode1, _ = engine._open_wasapi_stream(prof, src_info, "")
            first_count = len(open_attempts)
            _, _, sr2, dt2, mode2, _ = engine._open_wasapi_stream(prof, src_info, "")
            second_count = len(open_attempts) - first_count

        self.assertEqual((sr1, dt1, mode1), (192000, "float32", "exclusive"))
        self.assertEqual((sr2, dt2, mode2), (192000, "float32", "exclusive"))
        self.assertEqual(first_count, 3)
        self.assertEqual(second_count, 1, "Second track in Exclusive mode must open on attempt #1 from cache")

    def test_mainwindow_hardware_keys_idempotent_mini_restore_endofmedia_and_history_skip_filter(self):
        with isolated_window() as (w, root):
            # Create 4 real dummy files on disk so on_media_clicked accepts them cleanly.
            items = []
            for idx in range(4):
                fp = root / f"track_{idx}.mp3"
                fp.write_bytes(b"ID3" + bytes([idx]) * 64)
                items.append(
                    MediaMetadata(
                        id=f"id_{idx}",
                        path=str(fp),
                        title=f"Track {idx}",
                        artist=f"Artist {idx}",
                        duration=180.0,
                    )
                )
            w.active_playlist = list(items)
            w.all_media_items = list(items)
            w.user_collections.clear_history()

            # Attach stub SMTC manager with enabled=True and rewire through the unified helper.
            stub_mgr, fake_lib = _make_stub_smtc_manager()
            old_mgr = getattr(w, "media_manager", None)
            w.media_manager = stub_mgr
            try:
                w._connect_hardware_media_signals(reconnect=True)

                # 1. _resume_smtc_after_exclusive() must NOT call restart() when _capture_audio is False.
                w.audio_effects._resume_smtc_after_exclusive()
                self.assertEqual(fake_lib.restart_called, 0)
                self.assertEqual(fake_lib.start_called, 0)

                # 2. Idempotent hardware Play / Pause (even after Mini -> Normal roundtrip!).
                w.switch_to_mini_mode()
                pump(20)
                w.switch_to_normal_mode()
                pump(20)

                player = w.media_player.player
                state_box = [QMediaPlayer.PlaybackState.PlayingState]
                play_calls = []
                pause_calls = []

                def _fake_play():
                    play_calls.append(1)
                    state_box[0] = QMediaPlayer.PlaybackState.PlayingState

                def _fake_pause():
                    pause_calls.append(1)
                    state_box[0] = QMediaPlayer.PlaybackState.PausedState

                with patch.object(player, "playbackState", side_effect=lambda: state_box[0]), \
                     patch.object(player, "play", side_effect=_fake_play), \
                     patch.object(player, "pause", side_effect=_fake_pause), \
                     patch.object(w, "_try_startup_resume", return_value=False):
                    # Pressing Pause twice must pause ONCE and NEVER accidentally unpause!
                    w._hardware_pause()
                    w._hardware_pause()
                    self.assertEqual(len(pause_calls), 1)
                    self.assertEqual(len(play_calls), 0)
                    self.assertEqual(state_box[0], QMediaPlayer.PlaybackState.PausedState)

                    # Pressing Play twice must play ONCE and NEVER accidentally pause!
                    w._hardware_play()
                    w._hardware_play()
                    self.assertEqual(len(play_calls), 1)
                    self.assertEqual(len(pause_calls), 1)
                    self.assertEqual(state_box[0], QMediaPlayer.PlaybackState.PlayingState)

                    # Verify Mini -> Normal kept signals wired to _hardware_pause (not raw btn_play.click toggle).
                    stub_mgr.media_pause.emit()
                    stub_mgr.media_pause.emit()
                    pump(40)
                    self.assertEqual(len(pause_calls), 2)
                    self.assertEqual(len(play_calls), 1)
                    self.assertEqual(state_box[0], QMediaPlayer.PlaybackState.PausedState)

                # 3. Direct click on Track 0 records Track 0 in History immediately.
                with patch.object(w.audio_effects, "play_source"), \
                     patch.object(player, "playbackState", return_value=QMediaPlayer.PlaybackState.PlayingState):
                    w.on_media_clicked(items[0])
                    w.active_playlist = list(items)
                    pump(30)
                    self.assertEqual([m.id for m in w.user_collections.get_history_items()], ["id_0"])

                    # Spurious EndOfMedia right after track switch (within 650ms guard) MUST NOT skip!
                    w.handle_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
                    self.assertEqual(w.current_media_item.id, "id_0")

                    # 4. Rapidly skipping Track 0 -> Track 1 -> Track 2 -> Track 3 via play_next()
                    # MUST NOT dump unlistened skipped tracks 1 and 2 into Watch History!
                    w.play_next()  # -> Track 1 (skipped past!)
                    w.play_next()  # -> Track 2 (skipped past!)
                    w.play_next()  # -> Track 3 (final settled track)
                    self.assertEqual(w.current_media_item.id, "id_3")
                    self.assertEqual([m.id for m in w.user_collections.get_history_items()], ["id_0"])
                    self.assertIs(w._pending_history_item, items[3])
                    self.assertTrue(w._pending_history_timer.isActive())

                    # Simulating 2.5s listen dwell commits ONLY Track 3 (never 1 or 2!).
                    w._pending_history_timer.stop()
                    w._commit_pending_history()
                    self.assertEqual(
                        [m.id for m in w.user_collections.get_history_items()],
                        ["id_3", "id_0"],
                    )

                    # 5. Hardware Next burst within 280ms only advances ONCE.
                    w._hw_last_skip_mono = 0.0
                    w._hardware_next()  # Track 3 -> Track 0 (wrap)
                    w._hardware_next()  # dropped (<280ms)
                    w._hardware_next()  # dropped (<280ms)
                    self.assertEqual(w.current_media_item.id, "id_0")

                    # 6. EndOfMedia while Paused MUST NOT skip to next track.
                    w._track_switch_guard_until = 0.0
                    with patch.object(player, "playbackState", return_value=QMediaPlayer.PlaybackState.PausedState):
                        w.handle_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
                    self.assertEqual(w.current_media_item.id, "id_0")

                    # 7. Skip while Paused does NOT record into History until actually resumed!
                    w.user_collections.clear_history()
                    w.play_next()  # -> Track 1 while paused
                    with patch.object(player, "playbackState", return_value=QMediaPlayer.PlaybackState.PausedState):
                        w._pending_history_timer.stop()
                        w._commit_pending_history()
                    self.assertEqual(w.user_collections.history_count(), 0)
                    self.assertIs(w._pending_history_item, items[1])

                    # Resuming playback restarts the pending history timer and commits after dwell.
                    w.update_ui_state(QMediaPlayer.PlaybackState.PlayingState)
                    self.assertTrue(w._pending_history_timer.isActive())
                    w._pending_history_timer.stop()
                    w._commit_pending_history()
                    self.assertEqual([m.id for m in w.user_collections.get_history_items()], ["id_1"])
            finally:
                stub_mgr.close()
                if old_mgr is not None:
                    w.media_manager = old_mgr


if __name__ == "__main__":
    unittest.main()
