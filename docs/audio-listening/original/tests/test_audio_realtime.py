"""Native gain normalization: no source reload, no processed media, no new clock."""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.ui_preview import APPLICATION, isolated_window, pump
from ui.main_window import MainWindow
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from core.audio_loudness import LoudnessCache, native_gain, measure_loudness, valid_measurement, MEASUREMENT_OWNER
from core.audio_profile import AudioProfile
from core.audio_effects import source_signature, cache_key, OWNER_MARKER
from control.audio_volume import AudioVolumeControl
from control.worker_lifecycle import OwnedProcesses
from tests.test_audio_effects import command, wait_until, FFMPEG, FFPROBE
from tests.audio_realtime_contracts import before_realtime_changes

ROOT = Path(__file__).resolve().parents[1]


class NativeGainTests(unittest.TestCase):
    def test_default_target_keeps_four_db_more_level_than_previous_eighteen(self):
        new = native_gain(-10, -1, -14, 0.5)
        previous = native_gain(-10, -1, -18, 0.5)
        self.assertAlmostEqual(new.gain_db - previous.gain_db, 4)
        self.assertAlmostEqual(new.gain_db, -4)
        self.assertFalse(new.limited)

    def test_peak_limit_accounts_for_user_volume_without_unnecessary_source_attenuation(self):
        half = native_gain(-13.8, 0.54, -14, 0.5)
        self.assertAlmostEqual(half.gain_db, -0.2)
        full = native_gain(-13.8, 0.54, -14, 1)
        self.assertAlmostEqual(full.gain_db, -2.24)
        self.assertTrue(full.limited)

    def test_native_volume_ceiling_is_explicit_and_silence_zero_remain_valid(self):
        limited = native_gain(-30, -20, -14, 0.5)
        self.assertEqual(limited.effective_volume, 1)
        self.assertAlmostEqual(limited.gain_db, 20 * math.log10(2))
        self.assertTrue(limited.limited)
        self.assertEqual(native_gain(None, None, -14, 0.5).gain_db, 0)
        self.assertEqual(native_gain(-30, -20, -14, 0).effective_volume, 0)
        self.assertFalse(valid_measurement({'lufs': None, 'peak_db': None}))
        self.assertFalse(valid_measurement({'lufs': float('nan'), 'peak_db': 0}))
        self.assertFalse(valid_measurement({'lufs': True, 'peak_db': False}))
        self.assertFalse(valid_measurement({'lufs': 1e300, 'peak_db': 1e300}))
        boost_limited = native_gain(-40, -40, -14, 0.01)
        self.assertAlmostEqual(boost_limited.gain_db, 12)
        self.assertTrue(boost_limited.limited)


class LoudnessCacheTests(unittest.TestCase):
    def test_cache_hit_keeps_hot_measurement_in_owned_lru(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = LoudnessCache(root / 'cache', root / 'old', limit=2)
            measurement = dict(lufs=-10, peak_db=-1, silent=False)
            signatures = [dict(path=f'fixture{i}', size=100, mtime_ns=i) for i in range(3)]
            cache.save(signatures[0], 0, measurement)
            cache.save(signatures[1], 0, measurement)
            for i, signature in enumerate(signatures[:2]):
                os.utime(cache.root / (cache.key(signature, 0) + '.json'), ns=(100 + i, 100 + i))
            self.assertEqual(cache.lookup(signatures[0], 0), measurement)
            cache.save(signatures[2], 0, measurement)
            self.assertIsNotNone(cache.lookup(signatures[0], 0))
            self.assertIsNone(cache.lookup(signatures[1], 0))

    def test_foreign_symlinks_malformed_context_and_owned_bound_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = LoudnessCache(root / 'cache', root / 'old', limit=2)
            measurement = dict(lufs=-10, peak_db=-1, silent=False)
            for i in range(3):
                cache.save(dict(path=f'fixture{i}', size=100, mtime_ns=i), 0, measurement)
            self.assertEqual(len(list(cache.root.glob('*.json'))), 2)
            signature = dict(path='foreign', size=100, mtime_ns=7)
            target = cache.root / (cache.key(signature, 0) + '.json')
            target.write_text('[]')
            self.assertIsNone(cache.lookup(signature, 0))
            with self.assertRaises(ValueError):
                cache.save(signature, 0, measurement)
            self.assertEqual(target.read_text(), '[]')
            self.assertIsNone(cache.lookup(dict(path='fixture2', size=101, mtime_ns=2), 0))

    def test_legacy_analysis_reuse_does_not_require_or_touch_media_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = LoudnessCache(root / 'new', root / 'old')
            cache.legacy_root.mkdir()
            signature = dict(path='fixture', size=100, mtime_ns=1)
            key = cache_key(signature, AudioProfile(True), 0)
            path = cache.legacy_root / (key + '.json')
            original = json.dumps(dict(owner=OWNER_MARKER, key=key, source=signature, version=1, track=0,
                profile=AudioProfile(True).as_dict(), gain=dict(input_lufs=-10, input_peak_db=-1))).encode()
            path.write_bytes(original)
            before = path.stat().st_mtime_ns
            self.assertEqual(cache.lookup(signature, 0), dict(lufs=-10, peak_db=-1, silent=False))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(path.stat().st_mtime_ns, before)


class RealMeasurementTests(unittest.TestCase):
    def test_measurement_uses_one_null_pass_no_encoder_and_hit_uses_no_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'audio.wav'
            command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                     'sine=frequency=1000:sample_rate=48000:duration=3', '-c:a', 'pcm_s24le', str(source)])
            original = source.read_bytes()
            cache = LoudnessCache(root / 'cache', root / 'legacy')
            from core.audio_loudness import run_tool
            calls = []
            def observe(args, *rest, **kwargs):
                calls.append(args)
                return run_tool(args, *rest, **kwargs)
            with patch('core.audio_loudness.find_tool', return_value=FFMPEG), \
                    patch('core.audio_loudness.run_tool', side_effect=observe):
                result = measure_loudness(str(source), 0, cache, OwnedProcesses(), lambda: False)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][-3:], ['-f', 'null', '-'])
            self.assertNotIn('flac', calls[0])
            self.assertTrue(valid_measurement(result['measurement']))
            self.assertFalse(result['cache_hit'])
            with patch('core.audio_loudness.run_tool', side_effect=AssertionError('cache hit must not spawn')):
                hit = measure_loudness(str(source), 0, cache, OwnedProcesses(), lambda: False)
            self.assertTrue(hit['cache_hit'])
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(list(root.rglob('*.mkv')))

    def test_silence_cancel_and_invalid_source_are_distinct(self):
        from core.audio_effects import AudioPreparationCancelled
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'silent.wav'
            command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                     'anullsrc=r=48000:cl=stereo', '-t', '2', str(source)])
            cache = LoudnessCache(root / 'cache', root / 'legacy')
            with patch('core.audio_loudness.find_tool', return_value=FFMPEG):
                result = measure_loudness(str(source), 0, cache, OwnedProcesses(), lambda: False)
                self.assertTrue(result['measurement']['silent'])
                source.write_bytes(b'bad-file')
                with self.assertRaises(AudioPreparationCancelled):
                    measure_loudness(str(source), 0, cache, OwnedProcesses(), lambda: True)
                with self.assertRaises(RuntimeError):
                    measure_loudness(str(source), 0, cache, OwnedProcesses(), lambda: False)

    def test_cache_write_failure_keeps_valid_measurement_and_foreign_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'audio.wav'
            command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                     'sine=frequency=1000:duration=2', str(source)])
            cache = LoudnessCache(root / 'cache', root / 'old')
            cache.root.mkdir()
            foreign = cache.root / (cache.key(source_signature(source), 0) + '.json')
            foreign.write_bytes(b'[]')
            with patch('core.audio_loudness.find_tool', return_value=FFMPEG):
                result = measure_loudness(str(source), 0, cache, OwnedProcesses(), lambda: False)
            self.assertTrue(valid_measurement(result['measurement']))
            self.assertFalse(result['cache_saved'])
            self.assertEqual(foreign.read_bytes(), b'[]')


class ActualNativePlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.source = Path(cls.temp.name) / 'native.mp4'
        command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:r=25',
                 '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000', '-t', '15',
                 '-c:v', 'mpeg4', '-c:a', 'aac', '-b:a', '128k', str(cls.source)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def ready(self, window):
        player, output = window.media_player.player, window.audio_output
        output.setMuted(True)
        player.setSource(QUrl.fromLocalFile(str(self.source)))
        player.play()
        wait_until(lambda: player.position() > 100)
        return player, output, window.audio_effects

    def prepare(self, controller):
        with patch('core.audio_loudness.find_tool', return_value=FFMPEG):
            controller.set_profile(True, 'off')
            wait_until(lambda: controller._measurement is not None and controller.worker is None)
        pump(170)

    def test_toggle_target_and_next_have_only_requested_source_changes_without_pause_or_seek(self):
        with isolated_window() as (window, root):
            player, output, controller = self.ready(window)
            source, video, device = player.source(), player.videoOutput(), output.device()
            source_changes, state_changes, mute_changes = [], [], []
            player.sourceChanged.connect(source_changes.append)
            player.playbackStateChanged.connect(state_changes.append)
            output.mutedChanged.connect(mute_changes.append)
            player.setPosition(3500)
            player.setPlaybackRate(1.5)
            before = player.position()
            self.prepare(controller)
            self.assertEqual(player.source(), source)
            self.assertEqual(source_changes, [])
            self.assertEqual(state_changes, [])
            self.assertEqual(mute_changes, [])
            self.assertGreater(player.position(), before)
            self.assertEqual(player.playbackRate(), 1.5)
            self.assertIs(player.videoOutput(), video)
            self.assertIs(player.audioOutput(), output)
            self.assertEqual(output.device(), device)
            with patch('control.audio_effects.measure_loudness', side_effect=AssertionError('level edits reuse measurement')):
                controller.set_target(-18)
                controller.set_profile(False, 'off')
                controller.set_profile(True, 'off')
                controller.set_target(-14)
                pump(170)
            self.assertEqual(source_changes, [])
            self.assertEqual(state_changes, [])
            self.assertIsNone(controller._transition)
            self.assertFalse(list(root.rglob('*.mkv')))
            # One ordinary source change for a user choosing another song.
            player.setSource(QUrl.fromLocalFile(str(self.source) + '?fixture-next'))
            self.assertEqual(len(source_changes), 1)
            player.stop()
            player.setSource(QUrl())

    def test_volume_ui_shortcuts_mute_device_and_off_preserve_user_level(self):
        with isolated_window() as (window, root):
            player, output, controller = self.ready(window)
            self.prepare(controller)
            window.update_volume_from_popup(60)
            self.assertAlmostEqual(controller.volume(), 0.6)
            window.adjust_volume(-0.1)
            self.assertAlmostEqual(controller.volume(), 0.5)
            window.show_volume_popup()
            self.assertEqual(window.vol_popup.slider.value(), 50)
            window.vol_popup.hide()
            output.setDevice(output.device())
            self.assertAlmostEqual(controller.volume(), 0.5)
            controller.set_profile(False, 'off')
            pump(180)
            self.assertAlmostEqual(output.volume(), 0.5)
            self.assertTrue(output.isMuted())
            settings = json.loads(controller.settings_path.read_text())
            self.assertIs(settings.pop('prefetch_next'), True)
            self.assertEqual(settings, dict(normalize=False, tone='off', target_lufs=-14))
            player.stop()
            player.setSource(QUrl())

    def test_actual_decoded_pcm_bytes_are_identical_with_normalization_on(self):
        try:
            from PySide6.QtMultimedia import QAudioBufferOutput
        except ImportError:
            self.skipTest('Optional diagnostic requires Qt 6.8; native gain itself supports 6.7')
        blocks = {'off': {}, 'on': {}}
        # Use identical fresh decoder initialization. stop/replay has its own
        # AAC priming/pitch-compensation history, unrelated to the gain path.
        for phase in ('off', 'on'):
            with isolated_window() as (window, root):
                player, output, controller = window.media_player.player, window.audio_output, window.audio_effects
                output.setMuted(True)
                buffer_output = QAudioBufferOutput(player)
                player.setAudioBufferOutput(buffer_output)
                def receive(buffer):
                    if buffer.isValid():
                        key = (buffer.startTime(), buffer.byteCount())
                        blocks[phase][key] = hashlib.sha256(bytes(buffer.constData())).hexdigest()
                buffer_output.audioBufferReceived.connect(receive)
                player.setSource(QUrl.fromLocalFile(str(self.source)))
                wait_until(lambda: player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia)
                if phase == 'on':
                    self.prepare(controller)
                player.play()
                wait_until(lambda: len(blocks[phase]) >= 10)
                if phase == 'on':
                    self.assertNotAlmostEqual(output.volume(), controller.volume())
                player.stop()
                player.setSource(QUrl())
        common = set(blocks['off']) & set(blocks['on'])
        self.assertGreaterEqual(len(common), 8)
        self.assertTrue(all(blocks['off'][key] == blocks['on'][key] for key in common))

    def test_device_refresh_during_gain_ramp_does_not_rewrite_user_volume(self):
        with isolated_window() as (window, root):
            player, output, controller = self.ready(window)
            controller._measurement = dict(lufs=-10, peak_db=-1, silent=False)
            controller.set_profile(True, 'off')
            self.assertTrue(controller.volume_control._timer.isActive())
            with patch.object(output, 'setDevice', side_effect=lambda device: output.deviceChanged.emit()):
                window.media_player.refresh_audio_output()
            self.assertAlmostEqual(controller.volume(), 0.5)
            pump(180)
            self.assertAlmostEqual(controller.volume(), 0.5)
            player.stop()
            player.setSource(QUrl())

    def test_paused_toggle_and_measurement_failure_do_not_reload_or_move_position(self):
        with isolated_window() as (window, root):
            player, output, controller = self.ready(window)
            player.pause()
            player.setPosition(4500)
            pump(50)
            before, source = player.position(), player.source()
            with patch('control.audio_effects.measure_loudness', side_effect=RuntimeError('fixture')):
                controller.set_profile(True, 'off')
                wait_until(lambda: controller._failed_request is not None)
            self.assertEqual(player.position(), before)
            self.assertEqual(player.source(), source)
            self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
            controller.set_profile(False, 'off')
            self.prepare(controller)
            self.assertEqual(player.position(), before)
            self.assertEqual(player.source(), source)
            player.stop()
            player.setSource(QUrl())

    def test_malformed_eq_cache_measurement_never_reaches_source_switch_or_gui_math(self):
        with isolated_window() as (window, root):
            player, output, controller = self.ready(window)
            source = player.source()
            invalid = dict(path='C:/invalid.mkv', record=dict(key='bad',
                           gain=dict(gain_db=0, input_lufs=-10, input_peak_db=None, peak_limited=False)))
            with patch('control.audio_effects.prepare_audio', return_value=invalid):
                controller.set_profile(True, 'gentle')
                wait_until(lambda: controller.worker is None and controller._failed_request is not None)
            self.assertEqual(player.source(), source)
            self.assertIsNone(controller._transition)
            self.assertTrue(output.isMuted())
            player.stop()
            player.setSource(QUrl())

    def test_gain_ramp_monotonic_and_stale_timeout_is_safe_after_reset_or_shutdown(self):
        with isolated_window() as (window, root):
            volume = window.audio_effects.volume_control
            volume.set_volume(0.5)
            volume.set_gain(-6)
            samples = [volume.output.volume()]
            for _ in range(5):
                pump(35)
                samples.append(volume.output.volume())
            self.assertTrue(all(a >= b for a, b in zip(samples, samples[1:])))
            self.assertAlmostEqual(samples[-1], 0.5 * 10 ** (-6 / 20), places=5)
            volume.set_gain(0, ramp=False)
            volume._tick()
            self.assertAlmostEqual(volume.output.volume(), 0.5)
            volume.shutdown()
            volume._tick()
            self.assertFalse(volume._timer.isActive())

    def test_real_playlist_files_change_source_only_once_per_selection_with_normalization_on(self):
        files = sorted((ROOT / 'video').glob('*.mp4'))
        self.assertGreaterEqual(len(files), 2)
        with isolated_window() as (window, root):
            player, output, controller = window.media_player.player, window.audio_output, window.audio_effects
            output.setMuted(True)
            source_changes = []
            player.sourceChanged.connect(source_changes.append)
            with patch('core.audio_loudness.find_tool', return_value=FFMPEG):
                controller.set_profile(True, 'off')
                for source in files[:2]:
                    player.setSource(QUrl.fromLocalFile(str(source)))
                    player.play()
                    wait_until(lambda: controller._measurement is not None and controller.worker is None, timeout=10)
                    pump(180)
                    self.assertEqual(player.source(), QUrl.fromLocalFile(str(source)))
                    self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
                    self.assertIsNone(controller._transition)
                self.assertEqual(len(source_changes), 2)
                self.assertFalse(list(root.rglob('*.mkv')))
                self.assertTrue(output.isMuted())
            player.stop()
            player.setSource(QUrl())


class SourceScopeTests(unittest.TestCase):
    def test_prior_gates_remain_frozen_and_only_reviewed_scope_changed(self):
        manifest = json.loads((ROOT / 'docs/audio-realtime/reviewed-sources.json').read_text())
        expected_main = {'MainWindow.show_volume_popup', 'MainWindow.update_volume_from_popup', 'MainWindow.adjust_volume'}
        self.assertEqual(set(manifest['app/ui/main_window.py']['changed_functions']), expected_main)
        self.assertEqual(manifest['app/ui/playback_bar.py']['changed_functions'], [])
        self.assertEqual(manifest['app/ui/subtitle_presentation.py']['changed_functions'], [])
        original = json.loads((ROOT / 'docs/audio-realtime/sources-before.json').read_text())
        changed = {'app/control/audio_effects.py', 'app/ui/audio_effects_panel.py', 'app/ui/main_window.py'}
        for path, digest in original.items():
            if path not in changed:
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest, path)
            before_realtime_changes(path)
        for path, digest in json.loads((ROOT / 'docs/audio-realtime/new-source-hashes.json').read_text()).items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
