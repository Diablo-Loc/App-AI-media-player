"""Optional voicing/crossfeed: real signals, 128k media and owned Qt decoder."""
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QMediaPlayer
from tools.ui_preview import isolated_window, pump
from core.audio_profile import AudioProfile, choose_gain, tone_filter, render_filter, TONES
from core.audio_effects import AudioPlaybackCache, prepare_audio, cache_key
from control.worker_lifecycle import OwnedProcesses
from tools.probe_audio_effects import video_contract, audio_bounds
from tests.test_audio_effects import command, wait_until, FFMPEG, FFPROBE
from tests.audio_listening_contracts import before_listening_changes

ROOT = Path(__file__).resolve().parents[1]


def signal_filter(pcm, profile, rate=48000):
    import subprocess
    result = subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-f', 'f32le', '-ar', str(rate),
        '-ac', str(pcm.shape[1]), '-i', 'pipe:0', '-af', tone_filter(profile, rate, pcm.shape[1]),
        '-f', 'f32le', 'pipe:1'], input=pcm.astype('<f4').tobytes(), capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype='<f4').reshape(-1, pcm.shape[1])


class ListeningPolicyTests(unittest.TestCase):
    def test_original_profiles_filters_gain_and_cache_keys_are_exactly_unchanged(self):
        spec = importlib.util.spec_from_file_location('_old_audio_profile',
            ROOT / 'docs/audio-listening/original/app/core/audio_profile.py')
        old = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'_old_audio_profile': old}):
            spec.loader.exec_module(old)
            signature = {'path': 'same', 'size': 128, 'mtime_ns': 42}
            for tone in ('off', 'gentle', 'balanced'):
                for normalize in (False, True):
                    current, prior = AudioProfile(normalize, tone), old.AudioProfile(normalize, tone)
                    self.assertEqual(current.as_dict(), prior.as_dict())
                    self.assertEqual(cache_key(signature, current, 0), cache_key(signature, prior, 0))
                    for measurement in ({'input_i': -30, 'input_tp': -2}, {'input_i': -10, 'input_tp': -1},
                                        {'input_i': '-inf', 'input_tp': '-inf'}):
                        gain, prior_gain = choose_gain(measurement, current), old.choose_gain(measurement, prior)
                        self.assertEqual(dataclasses.asdict(gain), dataclasses.asdict(prior_gain))
                        for rate in (8000, 44100, 48000):
                            for channels in (1, 2, 6):
                                self.assertEqual(render_filter(current, gain, rate, channels),
                                                 old.render_filter(prior, prior_gain, rate))

    def test_new_presets_are_optional_bounded_and_do_not_replace_defaults_or_old_keys(self):
        self.assertEqual(AudioProfile.from_dict({}), AudioProfile(False, 'off'))
        for tone in ('warm', 'headphones'):
            profile = AudioProfile.from_dict({'tone': tone})
            self.assertEqual(profile.tone, tone)
            self.assertFalse(profile.normalize)
            self.assertEqual(AudioProfile.from_dict(profile.as_dict()), profile)
            filters = tone_filter(profile)
            for forbidden in ('loudnorm', 'compand', 'alimiter', 'aecho', 'afftdn', 'aresample', 'stereowiden'):
                self.assertNotIn(forbidden, filters)
        self.assertNotIn('crossfeed', tone_filter(AudioProfile(False, 'headphones'), channels=1))
        self.assertNotIn('crossfeed', tone_filter(AudioProfile(False, 'headphones'), channels=6))
        self.assertNotIn('crossfeed', tone_filter(AudioProfile(False, 'headphones'), 4000))
        self.assertEqual(set(TONES), {'off', 'gentle', 'balanced', 'warm', 'headphones'})

    def test_warm_is_a_small_linear_cut_not_bass_boost_or_dynamic_compression(self):
        rate = 48000
        t = np.arange(rate) / rate
        for frequency in (60, 280, 1000, 3200, 8500):
            signal = (0.2 * np.sin(2*np.pi*frequency*t))[:, None]
            out = signal_filter(signal, AudioProfile(False, 'warm'))
            quiet = signal_filter(signal * 0.1, AudioProfile(False, 'warm'))
            np.testing.assert_allclose(quiet, out * 0.1, atol=3e-8)
            ratio = np.sqrt(np.mean(out[rate//4:]**2) / np.mean(signal[rate//4:]**2))
            self.assertLessEqual(ratio, 1.0001)
            self.assertGreater(ratio, 0.65)
            if frequency == 60:
                self.assertGreater(ratio, 0.97)
            if frequency == 3200:
                self.assertLess(ratio, 0.88)

    def test_crossfeed_preserves_center_sample_count_and_has_modest_low_frequency_blend(self):
        rate = 48000
        t = np.arange(rate) / rate
        left = 0.2 * np.sin(2*np.pi*120*t)
        centered = np.column_stack((left, left))
        warm = signal_filter(centered, AudioProfile(False, 'warm'))
        headphones = signal_filter(centered, AudioProfile(False, 'headphones'))
        self.assertEqual(headphones.shape, centered.shape)
        np.testing.assert_allclose(headphones, warm, atol=5e-8)
        isolated = np.column_stack((left, np.zeros_like(left)))
        out = signal_filter(isolated, AudioProfile(False, 'headphones'))
        self.assertEqual(out.shape, isolated.shape)
        right_ratio = np.sqrt(np.mean(out[12000:, 1]**2) / np.mean(out[12000:, 0]**2))
        self.assertGreater(right_ratio, 0.03)
        self.assertLess(right_ratio, 0.2)
        self.assertEqual(float(out[0].max()), 0)
        # No invented signal on silence; channel layouts never become stereo by force.
        for channels in (1, 2, 6):
            silent = np.zeros((8000, channels), dtype='<f4')
            filtered = signal_filter(silent, AudioProfile(False, 'headphones'), 8000)
            self.assertEqual(filtered.shape, silent.shape)
            self.assertEqual(float(np.abs(filtered).max()), 0)


class ListeningMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='botube-listening-test-')
        cls.source = Path(cls.temp.name) / '128k.mp4'
        command([FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x48:r=25',
            '-f', 'lavfi', '-i', 'aevalsrc=0.5*sin(2*PI*120*t)+0.2*sin(2*PI*3200*t)|'
            '0.5*sin(2*PI*170*t)+0.2*sin(2*PI*3500*t):s=48000', '-t', '12',
            '-c:v', 'mpeg4', '-c:a', 'aac', '-b:a', '128k', str(cls.source)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_128k_media_preserves_video_timestamps_source_and_peak_after_full_chain(self):
        import re
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        prior_video, prior_pts = video_contract(self.source)
        prior_bounds = audio_bounds(self.source)
        with tempfile.TemporaryDirectory() as directory:
            cache = AudioPlaybackCache(directory)
            for tone in ('warm', 'headphones'):
                for normalize in (False, True):
                    profile = AudioProfile(normalize, tone)
                    owned = OwnedProcesses()
                    with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
                        result = prepare_audio(str(self.source), profile, 0, cache, owned, lambda: False)
                        with patch('core.audio_effects.run_tool', side_effect=AssertionError('cache hit spawned')):
                            self.assertTrue(prepare_audio(str(self.source), profile, 0, cache, owned, lambda: False)['cache_hit'])
                    current_video, pts = video_contract(result['path'])
                    self.assertEqual(prior_video, current_video)
                    self.assertEqual(len(prior_pts), len(pts))
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(prior_pts, pts)), 0.00051)
                    self.assertAlmostEqual(audio_bounds(result['path'])[1], prior_bounds[1], delta=0.002)
                    import subprocess
                    measured = subprocess.run([FFMPEG, '-nostdin', '-hide_banner', '-i', result['path'],
                        '-af', 'loudnorm=I=-18:TP=-1.5:LRA=50:print_format=json', '-f', 'null', '-'],
                        capture_output=True, check=True)
                    stats = json.loads(re.findall(rb'\{\s*"input_i".*?\}', measured.stderr, re.DOTALL)[-1])
                    self.assertLessEqual(float(stats['input_tp']), -1.5)
                    if normalize:
                        self.assertAlmostEqual(float(stats['input_i']), -18, delta=0.2)
            self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_actual_qt_new_presets_return_to_original_preserving_paused_seek_owners_and_volume(self):
        with isolated_window() as (window, root):
            c, player = window.audio_effects, window.media_player.player
            c.set_prefetch(False)
            original = QUrl.fromLocalFile(str(self.source))
            output, video = player.audioOutput(), player.videoOutput()
            output.setMuted(True)
            c.set_volume(0.37)
            player.setSource(original)
            player.play()
            wait_until(lambda: player.position() > 100)
            player.pause()
            player.setPosition(3500)
            player.setPlaybackRate(1.25)
            pump(50)
            for tone in ('warm', 'headphones'):
                with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
                    c.set_profile(False, tone)
                    wait_until(lambda: c.worker is None and not c.switching and player.source() != original, timeout=12)
                self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
                self.assertAlmostEqual(player.position(), 3500, delta=40)
                self.assertIs(player.audioOutput(), output)
                self.assertIs(player.videoOutput(), video)
                self.assertEqual(player.activeAudioTrack(), 0)
                self.assertEqual(player.activeVideoTrack(), 0)
                self.assertTrue(output.isMuted())
                self.assertAlmostEqual(c.volume(), 0.37, places=5)
                self.assertEqual(player.playbackRate(), 1.25)
                c.set_profile(False, 'off')
                wait_until(lambda: not c.switching and player.source() == original)
                self.assertAlmostEqual(player.position(), 3500, delta=40)
            for tone in ('warm', 'headphones'):
                index = c.panel.tone.findData(tone)
                self.assertGreater(index, -1)
                self.assertTrue(c.panel.tone.itemData(index, Qt.ItemDataRole.ToolTipRole))


class ListeningScopeTests(unittest.TestCase):
    def test_exact_three_module_scope_and_frozen_pipeline_owners(self):
        manifest = json.loads((ROOT / 'docs/audio-listening/reviewed-sources.json').read_text())
        self.assertEqual(set(manifest), {'app/core/audio_profile.py', 'app/core/audio_effects.py',
                                       'app/ui/audio_effects_panel.py', 'tests/test_audio_realtime.py'})
        self.assertEqual(manifest['app/core/audio_effects.py']['changed_functions'], ['prepare_audio'])
        self.assertEqual(set(manifest['app/core/audio_profile.py']['changed_functions']), {'tone_filter', 'render_filter'})
        for relative in manifest:
            before_listening_changes(relative)


if __name__ == '__main__':
    unittest.main()
