"""Optional audio feature: policies, real FFmpeg media, Qt lifecycle/parity."""
import ast
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

from tools.ui_preview import APPLICATION, isolated_window, pump
from ui.main_window import MainWindow
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer

from core.audio_profile import AudioProfile, choose_gain, render_filter
from core.audio_effects import AudioPlaybackCache, OWNER_MARKER, cache_key, source_signature, prepare_audio
from control.audio_effects import AudioEffectsController
from control.worker_lifecycle import OwnedProcesses
from tests.audio_effects_contracts import before_audio_changes
from tests.audio_realtime_contracts import before_realtime_changes
from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = str(ROOT / 'bin/ffmpeg.exe')
FFPROBE = str(ROOT / 'bin/ffprobe.exe')


def command(args):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=subprocess.CREATE_NO_WINDOW, check=True).stdout


def wait_until(predicate, timeout=6):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise AssertionError('Timed out waiting for audio worker/player')
        pump(5)


class PolicyTests(unittest.TestCase):
    def test_defaults_and_invalid_settings_preserve_original(self):
        for data in ({}, None, {'normalize': 'yes', 'tone': 'untrusted-filter'}, {'tone': []}):
            self.assertFalse(AudioProfile.from_dict(data).enabled)

    def test_loud_quiet_targets_and_peak_cap_preserve_dynamic_range(self):
        profile = AudioProfile(True)
        self.assertEqual(choose_gain({'input_i': -10, 'input_tp': -1}, profile).gain_db, -8)
        self.assertEqual(choose_gain({'input_i': -30, 'input_tp': -20}, profile).gain_db, 12)
        peak = choose_gain({'input_i': -30, 'input_tp': -2}, profile)
        self.assertAlmostEqual(peak.gain_db, 0.3)
        self.assertTrue(peak.peak_limited)
        self.assertAlmostEqual(peak.input_peak_db + peak.gain_db, -1.7)
        self.assertNotIn('loudnorm', render_filter(profile, peak))
        self.assertNotIn('compand', render_filter(profile, peak))

    def test_silence_and_invalid_measurement_do_not_create_gain_or_fake_success(self):
        silent = choose_gain({'input_i': '-inf', 'input_tp': '-inf'}, AudioProfile(True))
        self.assertEqual(silent.gain_db, 0)
        with self.assertRaises(ValueError):
            choose_gain({'input_i': -18}, AudioProfile(True))
        for malformed in ({}, {'input_i': 'nan', 'input_tp': 'nan'}):
            with self.assertRaises(ValueError):
                choose_gain(malformed, AudioProfile(True))

    def test_tone_only_has_no_boost_and_canonical_profiles_are_bounded(self):
        for tone in ('gentle', 'balanced'):
            profile = AudioProfile(False, tone)
            decision = choose_gain({'input_i': -25, 'input_tp': -8}, profile)
            self.assertEqual(decision.gain_db, 0)
            self.assertIn('equalizer=', render_filter(profile, decision))
            self.assertEqual(AudioProfile.from_dict(profile.as_dict()), profile)

    def test_cache_key_invalidates_file_profile_track_and_algorithm_context(self):
        signature = {'path': 'fixture', 'size': 123, 'mtime_ns': 44}
        keys = {cache_key(signature, AudioProfile(True), 0),
                cache_key({**signature, 'mtime_ns': 45}, AudioProfile(True), 0),
                cache_key(signature, AudioProfile(True, 'gentle'), 0),
                cache_key(signature, AudioProfile(True), 1)}
        self.assertEqual(len(keys), 4)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = AudioPlaybackCache(self.root / 'cache', limit=200)
        self.cache.root.mkdir()

    def entry(self, key, size=100):
        path = self.cache.root / (key * 64 + '.mkv')
        path.write_bytes(b'x' * size)
        path.with_suffix('.json').write_text(json.dumps({'owner': OWNER_MARKER, 'key': key * 64,
                                                       'output_bytes': size, 'version': 1,
                                                       'gain': {'gain_db': 0.0, 'peak_limited': False}}))
        return path

    def test_eviction_is_bounded_and_protects_current_and_foreign_media(self):
        first, second = self.entry('a'), self.entry('b')
        foreign = self.cache.root / ('c' * 64 + '.mkv')
        foreign.write_bytes(b'foreign-media')
        foreign.with_suffix('.json').write_text('{}')
        self.cache.prune(protected=[first], reserve=100)
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())
        self.assertEqual(foreign.read_bytes(), b'foreign-media')

    def test_outside_paths_corrupt_entries_and_full_protected_cache_are_safe(self):
        with self.assertRaises(ValueError):
            self.cache._owned(self.root / 'user-video.mkv')
        first, second = self.entry('a'), self.entry('b')
        self.assertIsNotNone(self.cache.lookup('a' * 64))
        first.write_bytes(b'truncated')
        self.assertIsNone(self.cache.lookup('a' * 64))
        with self.assertRaises(RuntimeError):
            self.cache.prune(protected=[first, second], reserve=200)

    def test_malformed_metadata_is_a_miss_and_never_deletes_foreign_files(self):
        path = self.entry('a')
        path.with_suffix('.json').write_text('[]')
        self.assertIsNone(self.cache.lookup('a' * 64))
        self.cache.prune(reserve=150)
        self.assertTrue(path.exists())
        path.with_suffix('.json').write_text(json.dumps({'owner': OWNER_MARKER, 'key': 'a' * 64,
                                                       'output_bytes': path.stat().st_size, 'version': 1, 'gain': []}))
        self.assertIsNone(self.cache.lookup('a' * 64))

    def test_crash_recovery_only_removes_owned_dead_job_and_keeps_live_and_foreign(self):
        import os
        import psutil
        live = psutil.Process()
        for letter, created, owned in (('a', live.create_time(), True), ('b', -1, True), ('c', -1, False)):
            partial = self.cache.root / (letter * 64 + '-' + 'd' * 32 + '.part.mkv')
            partial.write_bytes(b'partial')
            partial.with_suffix('.json').write_text(json.dumps({
                'owner': OWNER_MARKER if owned else 'foreign', 'partial': partial.name,
                'pid': os.getpid(), 'created': created}))
        self.cache.recover_partials()
        self.assertEqual(sorted(p.name[0] for p in self.cache.root.glob('*.part.mkv')), ['a', 'c'])
        self.assertEqual(sorted(p.name[0] for p in self.cache.root.glob('*.part.json')), ['a', 'c'])


class RealMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.sources = {}
        for label, level in (('quiet', 0.5), ('loud', 1.0)):
            path = cls.root / (label + '.mp4')
            command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:r=25',
                     '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000', '-t', '4',
                     '-filter:a', f'volume={level}', '-c:v', 'mpeg4', '-c:a', 'aac', '-b:a', '128k', str(path)])
            cls.sources[label] = path
        cls.silence = cls.root / 'silence.wav'
        command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                 '-t', '2', '-c:a', 'pcm_s16le', str(cls.silence)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def render(self, source, profile, directory):
        processes = OwnedProcesses()
        with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
            return prepare_audio(str(source), profile, 0, AudioPlaybackCache(directory), processes, lambda: False)

    def test_real_128k_sources_normalize_without_video_change_and_cache_hit_has_no_process(self):
        import av
        def video_hash(path):
            digest = hashlib.sha256()
            with av.open(str(path)) as container:
                for packet in container.demux(video=0):
                    digest.update(bytes(packet))
            return digest.hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            levels = []
            for label, source in self.sources.items():
                before = hashlib.sha256(source.read_bytes()).hexdigest()
                result = self.render(source, AudioProfile(True), directory)
                self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(video_hash(source), video_hash(result['path']))
                info = json.loads(command([FFPROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', result['path']]))
                audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
                self.assertEqual(audio['codec_name'], 'flac')
                self.assertEqual(audio['sample_rate'], '48000')
                self.assertAlmostEqual(float(info['format']['duration']), 4, delta=0.05)
                levels.append(result['record']['gain']['input_lufs'] + result['record']['gain']['gain_db'])
                measurement = subprocess.run([FFMPEG, '-nostdin', '-hide_banner', '-i', result['path'],
                    '-map', '0:a:0', '-af', 'loudnorm=I=-18:TP=-1.5:LRA=50:print_format=json',
                    '-f', 'null', '-'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
                import re
                measured = json.loads(re.findall(rb'\{\s*"input_i".*?\}', measurement.stderr, re.DOTALL)[-1])
                self.assertAlmostEqual(float(measured['input_i']), -18, delta=0.2)
                self.assertLessEqual(float(measured['input_tp']), -1.5)
                with patch('core.audio_effects.run_tool', side_effect=AssertionError('cache hit must not spawn')):
                    hit = self.render(source, AudioProfile(True), directory)
                self.assertTrue(hit['cache_hit'])
            self.assertLess(abs(levels[0] - levels[1]), 0.2)
            self.assertTrue(all(abs(level + 18) < 0.2 for level in levels))

    def test_real_silence_and_tone_file_are_valid_and_source_bytes_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.render(self.silence, AudioProfile(True, 'gentle'), directory)
            pcm = command([FFMPEG, '-nostdin', '-v', 'error', '-i', result['path'], '-f', 'f32le', '-'])
            import numpy as np
            self.assertEqual(float(np.abs(np.frombuffer(pcm, dtype='<f4')).max()), 0)
            self.assertEqual(result['record']['gain']['gain_db'], 0)

    def test_real_bad_file_fails_without_partial_or_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad.mp4'
            source.write_bytes(b'original-bad-data')
            cache = Path(directory) / 'cache'
            with self.assertRaises(RuntimeError):
                self.render(source, AudioProfile(True), cache)
            self.assertEqual(source.read_bytes(), b'original-bad-data')
            self.assertFalse(list(cache.glob('*.part.mkv')))

    def test_low_sample_rate_tone_and_cancellation_keep_source_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'voice8k.wav'
            command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                     'sine=frequency=800:sample_rate=8000:duration=2', '-c:a', 'pcm_s16le', str(source)])
            original = source.read_bytes()
            result = self.render(source, AudioProfile(True, 'gentle'), Path(directory) / 'cache')
            info = json.loads(command([FFPROBE, '-v', 'error', '-show_streams', '-of', 'json', result['path']]))
            self.assertEqual(info['streams'][0]['sample_rate'], '8000')
            self.assertEqual(source.read_bytes(), original)
            from core.audio_effects import AudioPreparationCancelled
            with self.assertRaises(AudioPreparationCancelled):
                prepare_audio(str(source), AudioProfile(True, 'balanced'), 0,
                              AudioPlaybackCache(Path(directory) / 'cancelled'), OwnedProcesses(), lambda: True)
            self.assertEqual(source.read_bytes(), original)

    def test_gentle_tone_reduces_harsh_band_without_changing_rate_or_duration(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'two-tone.wav'
            command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                     'aevalsrc=0.05*sin(2*PI*1000*t)+0.05*sin(2*PI*3200*t):s=48000:d=4',
                     '-c:a', 'pcm_s24le', str(source)])
            result = self.render(source, AudioProfile(False, 'gentle'), Path(directory) / 'cache')
            spectra = []
            counts = []
            for path in (source, result['path']):
                pcm = command([FFMPEG, '-nostdin', '-v', 'error', '-i', str(path), '-f', 'f32le', '-'])
                samples = np.frombuffer(pcm, dtype='<f4')
                counts.append(len(samples))
                spectrum = np.abs(np.fft.rfft(samples[48000:144000]))
                spectra.append(spectrum[6400] / spectrum[2000])
            change_db = 20 * np.log10(spectra[1] / spectra[0])
            self.assertLess(change_db, -2)
            self.assertGreater(change_db, -3.5)
            self.assertEqual(counts[0], counts[1])


class FakePlayer(QObject):
    sourceChanged = Signal(QUrl)
    mediaStatusChanged = Signal(object)
    activeTracksChanged = Signal()
    playbackStateChanged = Signal(object)
    errorOccurred = Signal(object, str)
    playbackRateChanged = Signal(float)
    positionChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self.url = QUrl.fromLocalFile('C:/original.mp4')
        self.pos = 12345
        self.rate = 1.5
        self.state = QMediaPlayer.PlaybackState.PlayingState
        self.track = 0
        self.video, self.subtitle, self.loop_count = 0, -1, 1

    def source(self): return self.url
    def position(self): return self.pos
    def playbackRate(self): return self.rate
    def playbackState(self): return self.state
    def activeAudioTrack(self): return self.track
    def activeVideoTrack(self): return self.video
    def activeSubtitleTrack(self): return self.subtitle
    def loops(self): return self.loop_count
    def setPosition(self, value): self.pos = value
    def setPlaybackRate(self, value): self.rate = value
    def setActiveAudioTrack(self, value): self.track = value
    def setActiveVideoTrack(self, value): self.video = value
    def setActiveSubtitleTrack(self, value): self.subtitle = value
    def setLoops(self, value): self.loop_count = value
    def play(self): self.state = QMediaPlayer.PlaybackState.PlayingState
    def pause(self): self.state = QMediaPlayer.PlaybackState.PausedState

    def setSource(self, value):
        self.url = value
        self.pos = 0
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.sourceChanged.emit(value)
        self.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadingMedia)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.context = isolated_window()
        self.window, self.root = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.window.audio_effects.shutdown()
        self.player = FakePlayer()
        with patch.object(self.window.media_player, 'player', self.player):
            self.controller = AudioEffectsController(self.window, self.root / 'audio-fixture')
        self.window.audio_effects = self.controller
        self.addCleanup(self.controller.shutdown)

    def test_default_off_does_not_prepare_and_button_is_adjacent_to_volume(self):
        controller = self.controller
        self.assertFalse(controller.profile.enabled)
        with patch('control.audio_effects.prepare_audio', side_effect=AssertionError('off must not prepare')):
            controller._prepare()
        self.assertIsNone(controller.worker)
        buttons = self.window.playback_bar.btn_vol.parentWidget().layout()
        self.assertEqual(buttons.indexOf(self.window.playback_bar.btn_audio), buttons.indexOf(self.window.playback_bar.btn_vol) + 1)

    def test_transition_preserves_position_rate_pause_and_original_identity(self):
        controller = self.controller
        original = self.player.source()
        for state in (QMediaPlayer.PlaybackState.PlayingState, QMediaPlayer.PlaybackState.PausedState):
            self.player.state, self.player.pos = state, 12345
            controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
            self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
            self.assertEqual(self.player.position(), 12345)
            self.assertEqual(self.player.playbackState(), state)
            self.assertEqual(self.player.playbackRate(), 1.5)
            self.assertEqual(controller._original, original)
            controller._switch(original)
            self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)

    def test_off_cancels_preparation_restores_original_and_persists_only_new_settings(self):
        controller = self.controller
        old_config = Path(self.window.settings_file)
        prior = old_config.read_bytes() if old_config.exists() else None
        controller.set_profile(True, 'gentle')
        controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
        self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        controller.set_profile(False, 'off')
        self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(self.player.source(), controller._original)
        self.assertEqual(self.player.position(), 12345)
        self.assertFalse(controller._request_timer.isActive())
        settings = json.loads(controller.settings_path.read_text())
        self.assertEqual((settings['normalize'], settings['tone']), (False, 'off'))
        self.assertEqual(old_config.read_bytes() if old_config.exists() else None, prior)

    def test_transition_keeps_tracks_loops_and_latest_seek_speed_intent(self):
        self.player.video, self.player.subtitle, self.player.loop_count = -1, 2, 3
        self.controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
        self.player.video, self.player.subtitle, self.player.loop_count = 0, -1, 1
        self.player.positionChanged.emit(0)
        self.assertEqual(self.controller._transition['position'], 12345)
        self.player.playbackRateChanged.emit(0.75)
        self.controller._seek_requested(0)
        self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual((self.player.video, self.player.subtitle, self.player.loop_count), (-1, 2, 3))
        self.assertEqual(self.player.playbackRate(), 0.75)
        self.assertEqual(self.player.position(), 0)

    def test_new_track_supersedes_transition_and_failed_cache_falls_back(self):
        controller = self.controller
        controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
        self.player.errorOccurred.emit(QMediaPlayer.Error.FormatError, 'fixture')
        self.assertEqual(self.player.source(), controller._original)
        self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(self.player.position(), 12345)
        controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
        latest = QUrl.fromLocalFile('C:/next.mp4')
        self.player.setSource(latest)
        self.assertEqual(controller._original, latest)
        self.assertIsNone(controller._transition)
        self.assertFalse(controller._transition_timer.isActive())

    def test_new_track_from_reentrant_end_callback_wins_during_restore(self):
        controller = self.controller
        latest = QUrl.fromLocalFile('C:/next.mp4')
        controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
        with patch.object(self.player, 'play', side_effect=lambda: self.player.setSource(latest)):
            self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(controller._original, latest)
        self.assertIsNone(controller._transition)
        self.assertEqual(self.player.source(), latest)

    def test_decoder_failure_during_restore_keeps_fallback_transition_owned(self):
        controller = self.controller
        controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
        with patch.object(self.player, 'setPlaybackRate', side_effect=lambda value:
                          self.player.errorOccurred.emit(QMediaPlayer.Error.FormatError, 'fixture')):
            self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(self.player.source(), controller._original)
        self.assertIsNotNone(controller._transition)
        self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
        self.assertEqual(self.player.position(), 12345)
        self.assertIsNone(controller._transition)

    def test_latest_worker_only_no_gui_wait_and_shutdown_reaps_owned_thread(self):
        controller = self.controller
        sources = []
        def slow(source, profile, track, cache, processes, cancelled, protected, progress):
            sources.append(profile)
            end = time.monotonic() + 0.2
            while time.monotonic() < end:
                time.sleep(0.005)
            return None
        def slow_measure(source, track, cache, processes, cancelled, progress):
            return slow(source, AudioProfile(True, 'off'), track, cache, processes, cancelled, (), progress)
        with patch('control.audio_effects.prepare_audio', side_effect=slow), \
                patch('control.audio_effects.measure_loudness', side_effect=slow_measure):
            controller.set_profile(True, 'gentle')
            controller._request_timer.stop()
            controller._prepare()
            worker = controller.worker
            wait_until(lambda: len(sources) == 1)
            with patch.object(worker, 'wait', side_effect=AssertionError('normal interaction must not wait')):
                controller.set_profile(True, 'balanced')
                controller.set_profile(True, 'off')
            controller._request_timer.stop()
            wait_until(lambda: controller.worker is None)
            controller._request_timer.stop()
            controller._prepare()
            wait_until(lambda: len(sources) == 2)
            self.assertEqual(sources[-1], AudioProfile(True, 'off'))
            controller.shutdown()
            self.assertIsNone(controller.worker)
            self.assertFalse(controller._request_timer.isActive())

    def test_popup_controls_own_status_and_prevent_bar_auto_hide(self):
        self.controller.toggle_panel()
        self.window.audio_effects = self.controller
        pump(10)
        self.assertTrue(self.controller.panel.isVisible())
        with patch.object(self.window.playback_bar, 'underMouse', return_value=False):
            self.window.hide_controls()
        self.assertTrue(self.window.playback_bar.isVisible())
        self.controller.panel.normalize.setChecked(True)
        self.assertTrue(self.controller.profile.normalize)
        self.controller.panel.reset.click()
        self.assertFalse(self.controller.profile.enabled)

    def test_audio_popup_and_source_reload_do_not_flash_first_lyric(self):
        from subtitle.mode import SubtitleMode
        window, controller = self.window, self.controller
        window.update_video_location('large')
        sub = window.sub_layer
        sub.mode = SubtitleMode.JP
        sub.set_fade_enabled(False)
        sub.load_subtitles([dict(start=0, end=1000, orig='First line'),
                            dict(start=12000, end=16000, orig='Current line')])
        with patch.object(window, 'isActiveWindow', return_value=True):
            pump(30)
            sub.update_position(12345)
            self.assertFalse(sub.isHidden())
            controller.toggle_panel()
            pump(20)
            self.assertTrue(sub.isHidden())
            controller.panel.hide()
            pump(20)
            self.assertFalse(sub.isHidden())
            controller._switch(QUrl.fromLocalFile('C:/processed.mkv'))
            sub.update_position(0)
            sub.show()
            self.assertTrue(sub.isHidden())
            self.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
            pump(20)
            self.assertFalse(sub.isHidden())
            self.assertEqual(sub.text(), 'Current line')


class SourceScopeTests(unittest.TestCase):
    def test_exact_reviewed_audio_adapters_and_unchanged_all_other_sources(self):
        manifest = json.loads((ROOT / 'docs/audio-effects/reviewed-sources.json').read_text())
        expected = {
            'app/ui/main_window.py': {'MainWindow.__init__', 'MainWindow.closeEvent', 'MainWindow.hide_controls'},
            'app/ui/playback_bar.py': {'PlaybackBar.__init__', 'PlaybackBar.init_ui', 'PlaybackBar._arrange_controls'},
            'app/ui/subtitle_presentation.py': {'SubtitlePresentationGuard.eventFilter', 'SubtitlePresentationGuard.context_allows'},
            'app/ui/subs_ui/subtitle_layer.py': set(),
        }
        for relative, allowed in expected.items():
            old = (ROOT / 'docs/audio-effects/original' / relative).read_text(encoding='utf-8-sig')
            current = before_realtime_changes(relative)
            before, after = functions(old), functions(current)
            self.assertEqual({name for name in before if before[name] != after.get(name)}, allowed)
            self.assertEqual(set(before), set(after))
            before_audio_changes(relative)
        sources = json.loads((ROOT / 'docs/audio-effects/sources-before.json').read_text(encoding='utf-8-sig'))
        from tests.audio_easy_contracts import before_easy_changes
        for entry in sources:
            if entry['Path'] not in expected:
                self.assertEqual(hashlib.sha256(before_easy_changes(entry['Path'], raw=True)).hexdigest().upper(), entry['Hash'])
        helpers = json.loads((ROOT / 'docs/audio-effects/new-source-hashes.json').read_text())
        for relative, digest in helpers.items():
            self.assertEqual(hashlib.sha256(before_realtime_changes(relative, raw=True)).hexdigest(), digest)
        original_icons = json.loads((ROOT / 'docs/audio-effects/original/app/ui/assets/icons/manifest.json').read_text())
        icons = json.loads((ROOT / 'app/ui/assets/icons/manifest.json').read_text())
        self.assertEqual({k: icons['sha256'][k] for k in original_icons['sha256']}, original_icons['sha256'])


class NativeDecoderTests(unittest.TestCase):
    def test_muted_actual_qt_decoder_switches_cache_and_original_with_same_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'native-fixture.mp4'
            command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:r=25',
                     '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000', '-t', '12',
                     '-c:v', 'mpeg4', '-c:a', 'aac', '-b:a', '128k', str(source)])
            with isolated_window() as (window, root):
                player = window.media_player.player
                output, video = player.audioOutput(), player.videoOutput()
                output.setMuted(True)
                output.setVolume(0.37)
                device = output.device()
                original = QUrl.fromLocalFile(str(source))
                player.setSource(original)
                player.play()
                wait_until(lambda: player.position() > 100, timeout=8)
                player.pause()
                player.setPosition(3500)
                player.setPlaybackRate(1.5)
                pump(100)
                before = player.position()
                controller = window.audio_effects
                with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
                    controller.set_profile(True, 'gentle')
                    wait_until(lambda: controller.worker is None and player.source() != original
                               and controller._transition is None, timeout=10)
                self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
                self.assertAlmostEqual(player.position(), before, delta=35)
                self.assertEqual(player.playbackRate(), 1.5)
                self.assertIs(player.audioOutput(), output)
                self.assertIs(player.videoOutput(), video)
                self.assertTrue(output.isMuted())
                self.assertAlmostEqual(controller.volume(), 0.37, places=5)
                self.assertEqual(output.device(), device)
                player.play()
                wait_until(lambda: player.position() > before + 100)
                before = player.position()
                controller.set_profile(False, 'off')
                wait_until(lambda: player.source() == original and controller._transition is None)
                self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
                self.assertAlmostEqual(player.position(), before, delta=100)
                self.assertEqual(player.playbackRate(), 1.5)
                self.assertIs(player.videoOutput(), video)
                self.assertTrue(output.isMuted())
                player.stop()
                player.setSource(QUrl())
                pump(30)


if __name__ == '__main__':
    unittest.main()
