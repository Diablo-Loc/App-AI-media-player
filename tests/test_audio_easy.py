"""Optional easy voicing: frozen old profiles, measured audio and Qt owners."""
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from tools.ui_preview import isolated_window, pump
from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QMediaPlayer
from core.audio_profile import AudioProfile, choose_gain, tone_filter, render_filter, TONES
from core.audio_effects import AudioPlaybackCache, cache_key, prepare_audio
from control.worker_lifecycle import OwnedProcesses
from tools.probe_audio_effects import video_contract, audio_bounds
from tests import test_audio_listening as fixtures
from tests.test_audio_effects import wait_until, FFMPEG, FFPROBE
from tests.audio_easy_contracts import before_easy_changes

ROOT = Path(__file__).resolve().parents[1]


class EasyPolicyTests(unittest.TestCase):
    def test_all_five_existing_profiles_gain_filters_and_cache_keys_stay_exact(self):
        spec = importlib.util.spec_from_file_location('_pre_easy_profile',
            ROOT / 'docs/audio-easy/original/app/core/audio_profile.py')
        old = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'_pre_easy_profile': old}):
            spec.loader.exec_module(old)
            for tone in ('off', 'gentle', 'balanced', 'warm', 'headphones'):
                for normalize in (False, True):
                    profile, prior = AudioProfile(normalize, tone), old.AudioProfile(normalize, tone)
                    self.assertEqual(cache_key({'path': 'same', 'size': 128, 'mtime_ns': 42}, profile, 0),
                                     cache_key({'path': 'same', 'size': 128, 'mtime_ns': 42}, prior, 0))
                    for measurement in ({'input_i': -30, 'input_tp': -2}, {'input_i': -10, 'input_tp': -1},
                                        {'input_i': '-inf', 'input_tp': '-inf'}):
                        gain, prior_gain = choose_gain(measurement, profile), old.choose_gain(measurement, prior)
                        self.assertEqual(dataclasses.asdict(gain), dataclasses.asdict(prior_gain))
                        for rate in (4000, 8000, 44100, 48000):
                            for channels in (1, 2, 6):
                                self.assertEqual(render_filter(profile, gain, rate, channels),
                                                 old.render_filter(prior, prior_gain, rate, channels))

    def test_optional_meier_has_preamp_before_crossfeed_and_eq_without_dynamics(self):
        self.assertEqual(AudioProfile.from_dict({}), AudioProfile(False, 'off'))
        signature = {'path': 'same', 'size': 128, 'mtime_ns': 42}
        keys = set()
        for tone in TONES:
            profile = AudioProfile.from_dict({'tone': tone})
            self.assertFalse(profile.normalize)
            self.assertEqual(AudioProfile.from_dict(profile.as_dict()), profile)
            keys.add(cache_key(signature, profile, 0))
        self.assertEqual(len(keys), len(TONES))
        for tone in ('easy', 'easy_headphones'):
            for channels in (1, 2, 6):
                for rate in (4000, 8000, 48000):
                    filters = tone_filter(AudioProfile(False, tone), rate, channels)
                    self.assertTrue(filters.startswith('volume=-1.5dB,'))
                    self.assertEqual('bs2b' in filters, tone == 'easy_headphones' and channels == 2 and rate >= 8000)
                    if 'bs2b' in filters:
                        self.assertTrue(filters.startswith('volume=-1.5dB,bs2b=profile=jmeier,bass='))
                    self.assertEqual(filters.count('r=f64'), 4)
                    for forbidden in ('loudnorm', 'alimiter', 'compand', 'acompressor', 'aecho', 'afftdn', 'aresample'):
                        self.assertNotIn(forbidden, filters)

    def test_eq_frequency_response_and_linearity_do_not_add_dynamic_compression(self):
        rate = 48000
        t = np.arange(rate) / rate
        ratios = {}
        for frequency in (40, 1000, 3500, 7000, 14000):
            signal = (0.2 * np.sin(2*np.pi*frequency*t))[:, None]
            out = fixtures.signal_filter(signal, AudioProfile(False, 'easy'))
            quiet = fixtures.signal_filter(signal * 0.1, AudioProfile(False, 'easy'))
            np.testing.assert_allclose(quiet, out * 0.1, atol=3e-8)
            self.assertEqual(out.shape, signal.shape)
            ratios[frequency] = np.sqrt(np.mean(out[rate//4:]**2) / np.mean(signal[rate//4:]**2))
        self.assertGreater(ratios[40], 0.96)  # Preamp offsets the small bass shelf.
        self.assertLess(ratios[40], 1.03)  # Shelf transition is not an exact gain ceiling.
        self.assertGreater(ratios[1000], 0.78)
        self.assertLess(ratios[1000], 0.87)
        self.assertLess(ratios[3500], ratios[1000])
        self.assertLess(ratios[7000], ratios[1000])
        self.assertLess(ratios[14000], ratios[1000])

    def test_meier_blend_silence_sample_count_and_layout_fallback(self):
        rate = 48000
        left = 0.2*np.sin(2*np.pi*120*np.arange(rate)/rate)
        out = fixtures.signal_filter(np.column_stack((left, np.zeros_like(left))), AudioProfile(False, 'easy_headphones'))
        self.assertEqual(out.shape, (rate, 2))
        blend = np.sqrt(np.mean(out[12000:, 1]**2)/np.mean(out[12000:, 0]**2))
        self.assertGreater(blend, 0.1)
        self.assertLess(blend, 0.4)
        centered = fixtures.signal_filter(np.column_stack((left, left)), AudioProfile(False, 'easy_headphones'))
        np.testing.assert_allclose(centered[:, 0], centered[:, 1], atol=1e-7)
        for channels in (1, 2, 6):
            silent = np.zeros((8000, channels), dtype='<f4')
            filtered = fixtures.signal_filter(silent, AudioProfile(False, 'easy_headphones'), 8000)
            self.assertEqual(filtered.shape, silent.shape)
            self.assertEqual(float(np.abs(filtered).max()), 0)
            if channels != 2:
                self.assertEqual(tone_filter(AudioProfile(False, 'easy_headphones'), 8000, channels),
                                 tone_filter(AudioProfile(False, 'easy'), 8000, channels))


class EasyMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ListeningMediaTests.setUpClass()
        cls.source = fixtures.ListeningMediaTests.source

    @classmethod
    def tearDownClass(cls):
        fixtures.ListeningMediaTests.tearDownClass()

    def test_real_128k_full_chain_preserves_source_video_bounds_and_peak_with_cache_hits(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        video, points = video_contract(self.source)
        bounds = audio_bounds(self.source)
        with tempfile.TemporaryDirectory() as directory:
            cache = AudioPlaybackCache(directory)
            for tone in ('easy', 'easy_headphones'):
                for normalize in (False, True):
                    profile, processes = AudioProfile(normalize, tone), OwnedProcesses()
                    with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
                        result = prepare_audio(str(self.source), profile, 0, cache, processes, lambda: False)
                        with patch('core.audio_effects.run_tool', side_effect=AssertionError('cache hit spawned')):
                            self.assertTrue(prepare_audio(str(self.source), profile, 0, cache, processes, lambda: False)['cache_hit'])
                    new_video, new_points = video_contract(result['path'])
                    self.assertEqual(video, new_video)
                    self.assertEqual(len(points), len(new_points))
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(points, new_points)), 0.00051)
                    new_bounds = audio_bounds(result['path'])
                    for old, new in zip(bounds, new_bounds):
                        self.assertAlmostEqual(old, new, delta=.002)
                    measured = subprocess.run([FFMPEG, '-nostdin', '-hide_banner', '-i', result['path'],
                        '-af', 'loudnorm=I=-18:TP=-1.5:LRA=50:print_format=json', '-f', 'null', '-'],
                        capture_output=True, check=True)
                    stats = json.loads(re.findall(rb'\{\s*"input_i".*?\}', measured.stderr, re.DOTALL)[-1])
                    self.assertLessEqual(float(stats['input_tp']), -1.5)
                    if normalize:
                        self.assertAlmostEqual(float(stats['input_i']), -18, delta=.2)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_qt_apply_off_preserves_paused_seek_rate_tracks_volume_and_decoder_owners(self):
        with isolated_window() as (window, root):
            c, player = window.audio_effects, window.media_player.player
            c.set_prefetch(False)
            original = QUrl.fromLocalFile(str(self.source))
            output, video = player.audioOutput(), player.videoOutput()
            output.setMuted(True)
            c.set_volume(.37)
            player.setSource(original)
            player.play()
            wait_until(lambda: player.position() > 100)
            player.pause()
            player.setPosition(3500)
            player.setPlaybackRate(1.25)
            pump(50)
            for tone in ('easy', 'easy_headphones'):
                with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
                    c.set_profile(False, tone)
                    wait_until(lambda: c.worker is None and not c.switching and player.source() != original, timeout=12)
                self.assertEqual(player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
                self.assertAlmostEqual(player.position(), 3500, delta=40)
                self.assertEqual(player.playbackRate(), 1.25)
                self.assertIs(player.audioOutput(), output)
                self.assertIs(player.videoOutput(), video)
                self.assertEqual(player.activeAudioTrack(), 0)
                self.assertEqual(player.activeVideoTrack(), 0)
                self.assertTrue(output.isMuted())
                self.assertAlmostEqual(c.volume(), .37, places=5)
                self.assertFalse(c.profile.normalize)
                self.assertTrue(c.panel.tone.itemData(c.panel.tone.findData(tone), Qt.ItemDataRole.ToolTipRole))
                c.set_profile(False, 'off')
                wait_until(lambda: not c.switching and player.source() == original)
                self.assertAlmostEqual(player.position(), 3500, delta=40)


class EasyScopeTests(unittest.TestCase):
    def test_only_profile_panel_and_explicit_prior_whitelist_adapter_changed(self):
        manifest = json.loads((ROOT / 'docs/audio-easy/reviewed-sources.json').read_text())
        self.assertEqual(set(manifest), {'app/core/audio_profile.py', 'app/ui/audio_effects_panel.py',
                                       'tests/test_audio_listening.py', 'tests/test_audio_effects.py'})
        self.assertEqual(manifest['app/core/audio_profile.py']['changed_functions'], ['tone_filter'])
        self.assertEqual(manifest['app/core/audio_profile.py']['added_functions'], [])
        self.assertEqual(manifest['app/ui/audio_effects_panel.py']['changed_functions'], ['AudioEffectsPanel.__init__'])
        for relative in manifest:
            before_easy_changes(relative)
        checkout = json.loads((ROOT / 'docs/audio-easy/checkout-sources.json').read_text())
        self.assertEqual(set(checkout), set(json.loads((ROOT / 'docs/audio-easy/checkout-paths.json').read_text())))
        self.assertEqual(len(checkout), 52)
        for relative in checkout:
            before_easy_changes(relative)


if __name__ == '__main__':
    unittest.main()
