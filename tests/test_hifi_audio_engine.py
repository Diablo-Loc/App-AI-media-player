"""Verification suite for BoTube Studio Hi-Fi Real-Time Audio Engine (Bit-Pure & Null-Test Proven)."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import psutil

from core.audio_effects import find_tool
from core.audio_loudness import probe_audio_stream, measure_loudness
from core.audio_profile import (
    AudioProfile,
    CS43198_CEILING_DB,
    atempo_chain,
    build_realtime_filter_graph,
    compute_mastering_gain_db,
    custom_eq_filter,
    custom_eq_peak_boost_db,
    detect_preset,
    effective_eq_preamp_db,
    evaluate_eq_response_db,
    export_apo_text,
    parse_apo_text,
    preset_profile,
    resolve_restorer,
    tone_filter,
    tone_peak_pad_db,
)
from PySide6.QtCore import QUrl

from core.audio_stream_engine import (
    AudioStreamEngine,
    apply_micro_fade,
    build_release_tail,
    preferred_exclusive_rates,
    quantize_pcm,
)
from core.media_library import SUPPORTED_EXTS
from control.worker_lifecycle import OwnedProcesses
from tools.ui_preview import isolated_window, pump

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = find_tool('ffmpeg')


def _measure_tone_gain_db(filter_graph: str, freq_hz: int, sample_rate: int = 44100) -> float:
    expr = f'0.125*sin(2*PI*{freq_hz}*t)|0.125*sin(2*PI*{freq_hz}*t)'
    raw = subprocess.run(
        [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
         '-i', f'aevalsrc={expr}:s={sample_rate}:d=0.3', '-af', filter_graph,
         '-f', 'f32le', '-ac', '2', 'pipe:1'],
        capture_output=True, check=True,
    ).stdout
    arr = np.frombuffer(raw, dtype='<f4').reshape(-1, 2)[2000:-2000, 0]
    return float(20.0 * np.log10(np.sqrt(np.mean(arr ** 2)) / (0.125 / np.sqrt(2.0))))


class StudioDspPolicyTests(unittest.TestCase):
    def test_supported_extensions_include_hifi_lossless_containers(self):
        for ext in ('.flac', '.m4a', '.opus', '.ogg', '.aac', '.webm', '.mp3', '.mp4', '.mkv', '.wav'):
            self.assertIn(ext, SUPPORTED_EXTS)

    def test_recommended_default_is_bit_pure_uncolored_with_loudness(self):
        prof = AudioProfile.recommended()
        self.assertEqual(prof, AudioProfile(normalize=True, tone='off', restorer='off', output_mode='shared'))

    def test_bit_pure_null_test_proves_zero_coloration_and_unclips_intersample_overs(self):
        # Multi-tone signal peaking at +1.9 dBTP (~1.245 float amplitude) simulating hot lossy peaks.
        sr = 48000
        t = np.arange(int(sr * 0.25), dtype=np.float64) / sr
        sig = (
            0.35 * np.sin(2 * np.pi * 60.0 * t)
            + 0.30 * np.sin(2 * np.pi * 250.0 * t)
            + 0.25 * np.sin(2 * np.pi * 1000.0 * t)
            + 0.20 * np.sin(2 * np.pi * 4000.0 * t)
            + 0.145 * np.sin(2 * np.pi * 14000.0 * t)
        )
        sig = sig * (1.245 / float(np.max(np.abs(sig))))  # Exact +1.9 dBTP peak
        self.assertGreater(float(np.max(np.abs(sig))), 1.24)
        stereo_f64 = np.column_stack([sig, sig]).astype('<f8')

        info = {'codec_name': 'opus', 'sample_rate': sr, 'channels': 2, 'bit_rate': 128000}
        af, summary = build_realtime_filter_graph(AudioProfile.recommended(), info, -5.0, sr)
        self.assertFalse(summary['resampled'])
        self.assertEqual(summary['restorer_active'], 'Bypass')

        raw_out = subprocess.run(
            [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error',
             '-f', 'f64le', '-ar', str(sr), '-ac', '2', '-i', 'pipe:0',
             '-af', af, '-f', 'f32le', '-ac', '2', 'pipe:1'],
            input=stereo_f64.tobytes(),
            capture_output=True,
            check=True,
        ).stdout
        out_f32 = np.frombuffer(raw_out, dtype='<f4').reshape(-1, 2)
        gain_lin = 10.0 ** (-5.0 / 20.0)
        gained = out_f32.astype(np.float64) * gain_lin
        expected = stereo_f64 * gain_lin

        # Null-test residual must be strictly < -135 dBFS (0.0000 dB coloration, 0 deg phase shift).
        residual = np.max(np.abs(gained - expected))
        residual_db = 20.0 * np.log10(max(1e-18, float(residual)))
        self.assertLess(residual_db, -135.0)
        # Intersample +1.9 dBTP peak was recovered cleanly below 0 dBFS without clipping!
        self.assertLess(float(np.max(np.abs(gained))), 0.80)

    def test_mastering_gain_fixes_quiet_track_and_protects_cs43198_intersample(self):
        gain, limited = compute_mastering_gain_db({'lufs': -22.0, 'peak_db': -8.0}, -16, normalize=True)
        self.assertAlmostEqual(gain, 6.0, places=3)
        self.assertFalse(limited)

        gain_p, limited_p = compute_mastering_gain_db({'lufs': -22.0, 'peak_db': -3.0}, -16, normalize=True)
        self.assertAlmostEqual(gain_p, 2.0, places=3)
        self.assertTrue(limited_p)

        gain2, limited2 = compute_mastering_gain_db({'lufs': -17.0, 'peak_db': 0.8}, -16, normalize=True)
        self.assertAlmostEqual(gain2, CS43198_CEILING_DB - 0.8, places=3)
        self.assertTrue(limited2)

        gain3, _ = compute_mastering_gain_db({'lufs': -9.0, 'peak_db': 0.4}, -16, normalize=False, exclusive=True)
        self.assertAlmostEqual(gain3, -1.2 - 0.4, places=3)

        gain4, limited4 = compute_mastering_gain_db({'lufs': None, 'peak_db': None, 'silent': True}, -16, normalize=True)
        self.assertEqual((gain4, limited4), (0.0, False))

    def test_opt_in_auto_restorer_targets_legacy_mp3_aac_and_bypasses_opus_and_lossless(self):
        opt_in = AudioProfile(normalize=True, tone='off', restorer='auto', output_mode='shared')
        r128 = resolve_restorer(opt_in, {'codec_name': 'mp3', 'bit_rate': 128000, 'sample_rate': 44100})
        self.assertIsNotNone(r128)
        self.assertIn('128k', r128['mode'])

        r160 = resolve_restorer(opt_in, {'codec_name': 'aac', 'bit_rate': 160000, 'sample_rate': 44100})
        self.assertIsNotNone(r160)

        # Strictly bypass Opus >=96k, FLAC, PCM, and high-bitrate AAC.
        self.assertIsNone(resolve_restorer(opt_in, {'codec_name': 'opus', 'bit_rate': 122000, 'sample_rate': 48000}))
        self.assertIsNone(resolve_restorer(opt_in, {'codec_name': 'flac', 'bit_rate': 950000, 'sample_rate': 96000}))
        self.assertIsNone(resolve_restorer(opt_in, {'codec_name': 'pcm_s24le', 'bit_rate': 2304000, 'sample_rate': 48000}))
        self.assertIsNone(resolve_restorer(opt_in, {'codec_name': 'aac', 'bit_rate': 256000, 'sample_rate': 48000}))

    def test_atempo_chain_handles_arbitrary_speeds(self):
        self.assertEqual(atempo_chain(1.0), '')
        self.assertEqual(atempo_chain(1.5), 'atempo=1.5000')
        self.assertEqual(atempo_chain(0.25), 'atempo=0.5,atempo=0.5000')
        self.assertEqual(atempo_chain(3.0), 'atempo=2.0,atempo=1.5000')

    def test_optional_aria2_voicing_flatness_and_no_crystalizer(self):
        with tempfile.TemporaryDirectory() as td:
            mp3_128 = Path(td) / 'low_128k.mp3'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i',
                'aevalsrc=0.45*sin(2*PI*220*t)+0.35*sin(2*PI*1800*t)+0.30*sin(2*PI*7500*t):s=44100:c=stereo:d=0.8',
                '-b:a', '128k', str(mp3_128),
            ], check=True)
            proc = OwnedProcesses()
            info = probe_audio_stream(str(mp3_128), 0, proc, lambda: False)

            af, summary = build_realtime_filter_graph(
                AudioProfile(normalize=True, tone='aria2', restorer='auto'), info, 0.0, 48000
            )
            self.assertNotIn('crystalizer', af)
            self.assertNotIn('asoftclip', af)
            self.assertNotIn('asplit', af)
            self.assertTrue(summary['resampled'])

            g60 = _measure_tone_gain_db(af, 60)
            g220 = _measure_tone_gain_db(af, 220)
            g1k = _measure_tone_gain_db(af, 1000)
            g8k = _measure_tone_gain_db(af, 8000)
            g14k = _measure_tone_gain_db(af, 14000)
            self.assertGreaterEqual(g1k, -0.8)
            self.assertLessEqual(g1k, 0.8)
            self.assertGreaterEqual(g60, 0.5)
            self.assertLessEqual(g220, -0.2)
            self.assertLessEqual(g8k, -0.2)
            self.assertGreaterEqual(g14k, 0.5)
            self.assertLessEqual(g14k, 3.2)
            self.assertEqual(tone_filter(AudioProfile(tone='aria2'), 48000, 2).count(':r=f64'), 5)

    def test_youtube_loudness_law_and_null_coloration(self):
        # Loud track (> -14 LUFS): attenuated to -14 LUFS without altering quiet/dynamic tracks.
        g_loud, lim_loud = compute_mastering_gain_db(
            {'lufs': -8.0, 'peak_db': 1.5}, -16, normalize=False, youtube_loudness=True
        )
        self.assertAlmostEqual(g_loud, -6.0, places=3)
        self.assertFalse(lim_loud)

        # Quiet dynamic track (<= -14 LUFS): untouched at 0.0 dB.
        g_quiet, lim_quiet = compute_mastering_gain_db(
            {'lufs': -19.0, 'peak_db': -4.0}, -16, normalize=False, youtube_loudness=True
        )
        self.assertEqual(g_quiet, 0.0)
        self.assertFalse(lim_quiet)

        # Quiet track with hot intersample transient (+0.8 dBTP): padded cleanly below -1.0 dBTP.
        g_hot, lim_hot = compute_mastering_gain_db(
            {'lufs': -15.0, 'peak_db': 0.8}, -16, normalize=False, youtube_loudness=True
        )
        self.assertAlmostEqual(g_hot, CS43198_CEILING_DB - 0.8, places=3)
        self.assertTrue(lim_hot)

        # Null test on exact YouTube preset with 48 kHz Opus proves 0.0000 dB tonal coloration.
        yt_prof, _ = preset_profile('youtube')
        sr = 48000
        t = np.arange(int(sr * 0.2), dtype=np.float64) / sr
        sig = 0.25 * np.sin(2 * np.pi * 440.0 * t) + 0.15 * np.sin(2 * np.pi * 6000.0 * t)
        stereo_f64 = np.column_stack([sig, sig]).astype('<f8')
        info = {'codec_name': 'opus', 'sample_rate': sr, 'channels': 2, 'bit_rate': 128000}
        af, summary = build_realtime_filter_graph(yt_prof, info, -2.5, sr)
        self.assertFalse(summary['resampled'])
        raw_out = subprocess.run(
            [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error',
             '-f', 'f64le', '-ar', str(sr), '-ac', '2', '-i', 'pipe:0',
             '-af', af, '-f', 'f32le', '-ac', '2', 'pipe:1'],
            input=stereo_f64.tobytes(),
            capture_output=True,
            check=True,
        ).stdout
        residual = np.max(np.abs(np.frombuffer(raw_out, dtype='<f4').reshape(-1, 2).astype(np.float64) - stereo_f64))
        self.assertLess(20.0 * np.log10(max(1e-18, float(residual))), -135.0)

    def test_soxr_33bit_synchronous_oversampling_and_chunk_scaling(self):
        self.assertEqual(preferred_exclusive_rates(44100, 48000, 'hires_sync')[0], 176400)
        self.assertEqual(preferred_exclusive_rates(48000, 48000, 'hires_sync')[0], 192000)
        self.assertEqual(preferred_exclusive_rates(44100, 48000, 'max_dac')[0], 352800)
        self.assertEqual(preferred_exclusive_rates(48000, 48000, 'max_dac')[0], 384000)
        self.assertEqual(AudioStreamEngine._chunk_frames_for_rate(48000), 2048)
        self.assertEqual(AudioStreamEngine._chunk_frames_for_rate(192000), 8192)
        self.assertEqual(AudioStreamEngine._chunk_frames_for_rate(384000), 16384)

        studio_prof, _ = preset_profile('studio_dawn_aria2')
        info = {'codec_name': 'flac', 'sample_rate': 48000, 'channels': 2, 'bit_rate': 960000}
        af, summary = build_realtime_filter_graph(studio_prof, info, -2.0, 192000)
        self.assertTrue(summary['resampled'])
        self.assertEqual(summary['soxr_precision'], 33)
        self.assertLess(af.index('aresample=192000:resampler=soxr:precision=33'), af.index('crossfeed='))

        bit_pure_192, _ = build_realtime_filter_graph(AudioProfile.recommended(), info, 0.0, 192000)
        for freq in (40, 1000, 14000):
            expr = f'0.125*sin(2*PI*{freq}*t)|0.125*sin(2*PI*{freq}*t)'
            raw = subprocess.run(
                [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                 '-i', f'aevalsrc={expr}:s=48000:d=0.35', '-af', bit_pure_192,
                 '-f', 'f32le', '-ac', '2', 'pipe:1'],
                capture_output=True, check=True,
            ).stdout
            arr = np.frombuffer(raw, dtype='<f4').reshape(-1, 2)[9600:-9600, 0]
            gain_db = 20.0 * np.log10(np.sqrt(np.mean(arr ** 2)) / (0.125 / np.sqrt(2.0)))
            self.assertLess(abs(gain_db), 0.05)

    def test_studio_aria2_and_walkman_vivid_signatures(self):
        studio_af, _ = build_realtime_filter_graph(
            AudioProfile(normalize=True, tone='studio_aria2', output_mode='exclusive', upsample='hires_sync'),
            {'codec_name': 'flac', 'sample_rate': 48000, 'channels': 2, 'bit_rate': 1000000},
            0.0,
            48000,
        )
        self.assertNotIn('crystalizer', studio_af)
        self.assertNotIn('asoftclip', studio_af)
        self.assertIn('crossfeed=', studio_af)
        self.assertGreater(_measure_tone_gain_db(studio_af, 40, 48000), 0.8)
        self.assertLess(abs(_measure_tone_gain_db(studio_af, 1000, 48000)), 0.4)
        self.assertLess(_measure_tone_gain_db(studio_af, 3350, 48000), -0.5)
        self.assertGreater(_measure_tone_gain_db(studio_af, 14000, 48000), 0.4)

        room_af = tone_filter(AudioProfile(tone='studio_room'), 48000, 2)
        self.assertLess(abs(_measure_tone_gain_db(room_af, 1000, 48000)), 0.05)

        walkman_af, _ = build_realtime_filter_graph(
            AudioProfile(normalize=True, tone='walkman_vivid'),
            {'codec_name': 'flac', 'sample_rate': 48000, 'channels': 2, 'bit_rate': 1000000},
            0.0,
            48000,
        )
        self.assertGreater(_measure_tone_gain_db(walkman_af, 55, 48000), 1.0)
        self.assertLess(_measure_tone_gain_db(walkman_af, 230, 48000), -0.5)
        self.assertLess(abs(_measure_tone_gain_db(walkman_af, 1000, 48000)), 0.4)
        self.assertGreater(_measure_tone_gain_db(walkman_af, 2750, 48000), 0.3)
        self.assertLess(_measure_tone_gain_db(walkman_af, 7600, 48000), -0.4)
        self.assertGreater(_measure_tone_gain_db(walkman_af, 14000, 48000), 0.9)

        pad = tone_peak_pad_db(AudioProfile(tone='walkman_vivid'))
        g_hot, lim = compute_mastering_gain_db(
            {'lufs': -15.0, 'peak_db': 0.5}, -14, normalize=True, tone_pad_db=pad
        )
        self.assertAlmostEqual(g_hot, CS43198_CEILING_DB - pad - 0.5, places=3)
        self.assertTrue(lim)


class StreamQuantizerAndFadeTests(unittest.TestCase):
    def test_tpdf_dither_quantizers_exact_byte_sizes(self):
        frames = np.linspace(-0.8, 0.8, 256, dtype=np.float32).reshape(128, 2)
        rng = np.random.default_rng(42)
        self.assertEqual(len(quantize_pcm(frames, 'float32')), 128 * 2 * 4)
        self.assertEqual(len(quantize_pcm(frames, 'int32', rng=rng)), 128 * 2 * 4)
        self.assertEqual(len(quantize_pcm(frames, 'int24', rng=rng)), 128 * 2 * 3)
        self.assertEqual(len(quantize_pcm(frames, 'int16', rng=rng)), 128 * 2 * 2)
        self.assertEqual(len(quantize_pcm(frames, 'int32')), 128 * 2 * 4)
        self.assertEqual(len(quantize_pcm(frames, 'int24')), 128 * 2 * 3)

    def test_micro_fade_smoothly_ramps_without_step_clicks(self):
        block = np.ones((600, 2), dtype=np.float32)
        faded, end_amp = apply_micro_fade(block, current_amp=0.0, target_amp=0.8, fade_samples=576)
        self.assertAlmostEqual(float(faded[0, 0]), 0.0, places=5)
        self.assertAlmostEqual(end_amp, 0.8, places=5)
        self.assertAlmostEqual(float(faded[-1, 0]), 0.8, places=5)
        diffs = np.abs(np.diff(faded[:, 0]))
        self.assertLess(float(np.max(diffs)), 0.01)

    def test_exclusive_rejection_falls_back_gracefully_to_shared(self):
        import sounddevice as sd
        engine = AudioStreamEngine()

        class FakeWasapi:
            def __init__(self, exclusive=False):
                self.exclusive = exclusive

        with patch('sounddevice.WasapiSettings', FakeWasapi), \
             patch('sounddevice.RawOutputStream') as mock_stream:
            def side_effect(**kwargs):
                if kwargs['extra_settings'].exclusive:
                    raise sd.PortAudioError('Invalid device', -9996)
                return mock_stream.return_value
            mock_stream.side_effect = side_effect
            with tempfile.TemporaryDirectory() as td:
                wav = Path(td) / 's.wav'
                subprocess.run([FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                                '-i', 'sine=f=440:r=44100:d=0.4', str(wav)], check=True)
                info = engine.start_or_reconfigure(
                    str(wav), 0, AudioProfile(output_mode='exclusive'),
                    {'codec_name': 'pcm_s16le', 'sample_rate': 44100, 'channels': 2, 'bit_rate': 1411200},
                    0.0,
                )
                self.assertEqual(info['output_mode'], 'shared_fallback')
                self.assertIn('Hi-Fi Shared', info['fallback_reason'])
                engine.shutdown()

    def test_live_stream_continuous_zero_underflows_and_rapid_controls(self):
        with tempfile.TemporaryDirectory() as td:
            mp3 = Path(td) / 'stress.mp3'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'sine=f=440:r=44100:d=2.0', '-b:a', '128k', str(mp3),
            ], check=True)
            info = {'codec_name': 'mp3', 'sample_rate': 44100, 'channels': 2, 'bit_rate': 128000}
            engine = AudioStreamEngine()
            engine.set_user_volume(0.0, muted=True)
            t0 = time.monotonic()
            st = engine.start_or_reconfigure(str(mp3), 0, AudioProfile.recommended(), info, -2.0)
            self.assertTrue(st['active'])
            time.sleep(0.45)
            st_mid = engine.status_info()
            self.assertEqual(st_mid['underflows'], 0)
            engine.pause()
            self.assertTrue(engine.status_info()['paused'])
            engine.resume(200)
            self.assertTrue(engine.is_active())
            engine.seek(500)
            engine.set_gain_db(-4.0)
            time.sleep(0.10)
            engine.stop()
            engine.shutdown()
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 4.0)
            children = [c.name() for c in psutil.Process(os.getpid()).children(recursive=True)
                        if 'ffmpeg' in c.name().lower()]
            self.assertEqual(children, [])


class ZeroDiskIntegrationTests(unittest.TestCase):
    def test_zero_mkv_writes_legacy_purge_and_source_readonly(self):
        with isolated_window() as (window, root):
            src = root / 'track.mp3'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'sine=f=520:r=44100:d=0.6', '-b:a', '128k', str(src),
            ], check=True)
            before_bytes = src.read_bytes()
            before_mtime = src.stat().st_mtime_ns

            legacy_dir = window.audio_effects.cache.root
            legacy_dir.mkdir(parents=True, exist_ok=True)
            fake_key = 'a' * 64
            (legacy_dir / f'{fake_key}.mkv').write_bytes(b'old_mkv_waste')
            (legacy_dir / f'{fake_key}.json').write_text(
                f'{{"owner": "botube-audio-effects", "key": "{fake_key}"}}', encoding='utf-8'
            )
            foreign = legacy_dir / 'foreign.mkv'
            foreign.write_bytes(b'keep_foreign')

            ctrl = window.audio_effects
            ctrl._purge_legacy_disk_cache()
            self.assertFalse((legacy_dir / f'{fake_key}.mkv').exists())
            self.assertTrue(foreign.exists())

            self.assertEqual(ctrl.profile, AudioProfile.recommended())
            self.assertIs(window.media_player.player.audioOutput(), window.audio_output)

            proc = OwnedProcesses()
            res = measure_loudness(str(src), 0, ctrl.loudness_cache, proc, lambda: False,
                                   source_info={'codec_name': 'mp3', 'sample_rate': 44100, 'channels': 2, 'bit_rate': 128000})
            self.assertIsNotNone(res['measurement']['lufs'])
            self.assertEqual(list(legacy_dir.glob(f'{fake_key}.mkv')), [])

            self.assertEqual(src.read_bytes(), before_bytes)
            self.assertEqual(src.stat().st_mtime_ns, before_mtime)

            ctrl.panel._reset()
            pump(50)
            self.assertFalse(ctrl.profile.enabled)
            self.assertIs(window.media_player.player.audioOutput(), window.audio_output)

            # Quick presets & screen-fit geometry check
            panel = ctrl.panel
            self.assertLessEqual(panel.sizeHint().height(), 860)
            for key in ('studio_dawn_aria2', 'youtube', 'bit_pure', 'walkman_vivid', 'bypass'):
                idx = panel.preset_combo.findData(key)
                self.assertGreaterEqual(idx, 0)
                panel.preset_combo.setCurrentIndex(idx)
                pump(30)
                expected_prof, expected_lufs = preset_profile(key)
                self.assertEqual(ctrl.profile, expected_prof)
                self.assertEqual(detect_preset(ctrl.profile, ctrl.target_lufs), key)
                if isinstance(expected_lufs, int) and key != 'youtube':
                    self.assertEqual(ctrl.target_lufs, expected_lufs)

            # Changing any single knob flips Quick Preset cleanly to Custom
            panel.upsample.setCurrentIndex(panel.upsample.findData('max_dac'))
            pump(30)
            self.assertEqual(ctrl.profile.upsample, 'max_dac')
            self.assertEqual(panel.preset_combo.currentData(), 'custom')

    def test_64bit_f64le_to_int32_preserves_sub_24bit_lsb_precision(self):
        # A -156 dBFS sine (~1.585e-8) riding on +0.75 is < 0.5 float32 ULP (~2.98e-8)
        # so float32 collapses 100% of it to flat 0.75, whereas float64 -> int32 preserves ~34 int32 LSB steps!
        t = np.linspace(0.0, 2.0 * np.pi, 1024, endpoint=False, dtype=np.float64)
        amp = 10.0 ** (-156.0 / 20.0)
        delta = amp * np.sin(t)
        base_f64 = np.column_stack([0.75 + delta, -0.75 - delta]).astype(np.float64)
        base_f32 = base_f64.astype(np.float32)
        self.assertEqual(float(np.max(np.abs(base_f32[:, 0] - np.float32(0.75)))), 0.0)

        pcm_i32 = np.frombuffer(quantize_pcm(base_f64, 'int32', rng=None), dtype='<i4').reshape(-1, 2)
        span = int(np.max(pcm_i32[:, 0]) - np.min(pcm_i32[:, 0]))
        expected_span = int(round(2.0 * amp * 2147483647.0))
        self.assertGreater(span, expected_span - 8)
        self.assertLess(span, expected_span + 8)

        tail = build_release_tail(np.array([0.8, -0.6], dtype=np.float64), 288)
        self.assertEqual(tail.shape, (288, 2))
        self.assertEqual(tail.dtype, np.float64)
        self.assertGreater(float(tail[0, 0]), 0.79)
        self.assertLess(float(tail[0, 1]), -0.59)
        self.assertEqual(float(tail[-1, 0]), 0.0)
        self.assertEqual(float(tail[-1, 1]), 0.0)
        self.assertTrue(np.all(np.diff(tail[:, 0]) <= 0.0))

    def test_instant_ram_cache_fast_path_spawns_zero_worker_threads_on_replay_or_prefetch(self):
        with isolated_window() as (window, root):
            src = root / 'fast_path.mp3'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'sine=frequency=440:sample_rate=44100:duration=0.6', '-b:a', '128k', str(src),
            ], check=True)
            ctrl = window.audio_effects
            ctrl.set_profile(True, 'off', 'off', 'shared', 'off', True)
            window.audio_output.setMuted(True)
            proc = OwnedProcesses()
            info = probe_audio_stream(str(src), 0, proc, lambda: False)
            measure_loudness(str(src), 0, ctrl.loudness_cache, proc, lambda: False, source_info=info)

            # 1st play hits disk loudness cache & populates RAM cache -> 0 workers spawned.
            with patch('control.audio_effects.AudioAnalysisWorker', side_effect=AssertionError('Must use fast-path')):
                ctrl.play_source(QUrl.fromLocalFile(str(src)))
                pump(120)
                self.assertEqual(ctrl._source_info['sample_rate'], 44100)
                self.assertGreater(ctrl.stream.status_info()['latency_ms'], 0.0)

                # 2nd play hits pure in-RAM LRU cache -> 0 disk lookups and 0 workers spawned.
                with patch.object(ctrl.loudness_cache, 'lookup_full', side_effect=AssertionError('Must hit RAM cache')):
                    ctrl.play_source(QUrl.fromLocalFile(str(src)))
                    pump(120)
                    self.assertEqual(ctrl._source_info['codec_name'], 'mp3')

    def test_10band_custom_eq_biquad_accuracy_auto_preamp_and_apo_roundtrip(self):
        # Flat 10-band EQ emits empty filter string (bit-pure path).
        self.assertEqual(custom_eq_filter(AudioProfile(eq_enabled=True)), '')

        prof = AudioProfile(
            eq_enabled=True,
            eq_bands=(0.0, 4.5, 0.0, 0.0, 0.0, -3.0, 0.0, 0.0, 0.0, 3.5),
            eq_bass_db=2.0,
            eq_treble_db=0.0,
            eq_preamp_db=0.0,
            eq_auto_preamp=True,
        )
        af, summary = build_realtime_filter_graph(
            prof, {'codec_name': 'flac', 'sample_rate': 48000, 'channels': 2, 'bit_rate': 960000}, 0.0, 48000
        )
        self.assertTrue(summary['custom_eq_active'])
        test_freqs = [62, 250, 1000, 4000, 14000]
        predicted = evaluate_eq_response_db(prof, test_freqs, 48000.0)
        for freq, pred_db in zip(test_freqs, predicted):
            actual_db = _measure_tone_gain_db(af, freq, 48000)
            self.assertLess(abs(actual_db - pred_db), 0.12)

        # Auto Preamp prevents +8 dB bass boost from clipping DAC on hot +0.5 dBTP tracks.
        hot_eq = AudioProfile(
            eq_enabled=True,
            eq_bands=(8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            eq_auto_preamp=True,
        )
        boost = custom_eq_peak_boost_db(hot_eq)
        self.assertGreaterEqual(boost, 7.8)
        self.assertAlmostEqual(effective_eq_preamp_db(hot_eq), -boost, places=2)
        gain_hot, _ = compute_mastering_gain_db(
            {'lufs': -15.0, 'peak_db': 0.5}, -14, normalize=True, tone_pad_db=tone_peak_pad_db(hot_eq)
        )
        self.assertLessEqual(gain_hot + boost + 0.5, CS43198_CEILING_DB + 0.02)

        # Equalizer APO round-trip + arbitrary AutoEQ GraphicEQ interpolation.
        apo = export_apo_text(prof)
        parsed = parse_apo_text(apo)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['eq_bands'], prof.eq_bands)
        autoeq = 'Preamp: -4.2 dB\nGraphicEQ: 20 3.0; 100 1.5; 1000 0.0; 4000 -2.0; 16000 2.0'
        parsed_auto = parse_apo_text(autoeq)
        self.assertEqual(parsed_auto['eq_preamp_db'], -4.2)
        self.assertAlmostEqual(parsed_auto['eq_bands'][5], 0.0, places=2)
        self.assertAlmostEqual(parsed_auto['eq_bands'][7], -2.0, places=2)
        self.assertAlmostEqual(parsed_auto['eq_bands'][9], 2.0, places=2)

    def test_equalizer_dialog_presets_user_save_bypass_preservation_and_zero_disk(self):
        with isolated_window() as (window, root):
            ctrl = window.audio_effects
            dlg = ctrl.open_equalizer()
            self.assertIsNotNone(dlg)
            self.assertLessEqual(ctrl.panel.sizeHint().height(), 860)

            idx = dlg.curve_combo.findData('v_shape')
            dlg.curve_combo.setCurrentIndex(idx)
            pump(40)
            self.assertTrue(ctrl.profile.eq_enabled)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 4.2, places=1)
            self.assertEqual(ctrl.panel.preset_combo.currentData(), 'custom')

            dlg.band_sliders[0].setValue(62)
            dlg.flush_pending()
            pump(40)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 6.2, places=1)
            self.assertTrue(dlg.save_user_preset('Tai nghe của tôi'))
            self.assertIn('Tai nghe của tôi', ctrl.user_eq_presets)

            saved_cfg = json.loads(ctrl.settings_path.read_text(encoding='utf-8'))
            self.assertIn('Tai nghe của tôi', saved_cfg['user_eq_presets'])
            self.assertAlmostEqual(saved_cfg['eq_bands'][0], 6.2, places=1)
            self.assertEqual(list(ctrl.cache.root.glob('*.mkv')), [])

            # Bypass turns eq_enabled OFF while preserving user's 6.2 dB band setting!
            ctrl.panel._reset()
            pump(40)
            self.assertFalse(ctrl.profile.eq_enabled)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 6.2, places=1)
            dlg.enable_cb.setChecked(True)
            pump(40)
            self.assertTrue(ctrl.profile.eq_enabled)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 6.2, places=1)

    def test_output_device_pinning_unplugged_fallback_and_per_device_hotplug_memory(self):
        import sounddevice as sd
        studio_prof, lufs = preset_profile('studio_dawn_aria2')
        pinned = replace(studio_prof, output_device='Headphones (DAWN PRO2)')
        self.assertTrue(pinned.enabled)
        self.assertEqual(detect_preset(pinned, lufs), 'studio_dawn_aria2')
        self.assertEqual(detect_preset(AudioProfile(output_device='Headphones (DAWN PRO2)')), 'custom')

        class FakeWasapi:
            def __init__(self, exclusive=False):
                self.exclusive = exclusive

        with patch('sounddevice.WasapiSettings', FakeWasapi), \
             patch('sounddevice.query_hostapis', return_value=[{'name': 'Windows WASAPI', 'devices': [0], 'default_output_device': 0}]), \
             patch('sounddevice.query_devices', return_value={'name': 'Speakers (Realtek(R) Audio)', 'max_output_channels': 2, 'default_samplerate': 48000.0}), \
             patch('sounddevice.RawOutputStream') as mock_stream:
            def _open(**kwargs):
                if kwargs['extra_settings'].exclusive:
                    raise sd.PortAudioError('Exclusive rejected', -9996)
                return mock_stream.return_value
            mock_stream.side_effect = _open
            engine = AudioStreamEngine()
            with tempfile.TemporaryDirectory() as td:
                wav = Path(td) / 'pin.wav'
                subprocess.run([FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                                '-i', 'sine=f=440:r=48000:d=0.4', str(wav)], check=True)
                info = engine.start_or_reconfigure(
                    str(wav), 0, replace(pinned, output_mode='shared'),
                    {'codec_name': 'pcm_s16le', 'sample_rate': 48000, 'channels': 2, 'bit_rate': 1536000},
                    0.0,
                )
                self.assertIn('Chưa cắm "Headphones (DAWN PRO2)"', info['fallback_reason'])
                engine.shutdown()

        # Per-device memory auto-switches on hotplug between Space Travel 2 Ultra & Dawn Pro 2
        with isolated_window() as (window, root):
            ctrl = window.audio_effects
            state = {
                'devs': ['Speakers (Realtek(R) Audio)', 'Headphones (SPACE TRAVEL 2 ULTRA)'],
                'default': 'Headphones (SPACE TRAVEL 2 ULTRA)',
            }
            ctrl._last_device_key = state['default']
            with patch.object(ctrl, '_available_device_names', side_effect=lambda: list(state['devs'])), \
                 patch.object(ctrl, '_system_default_device_name', side_effect=lambda: state['default']), \
                 patch.object(ctrl.stream, 'refresh_devices', side_effect=lambda: list(state['devs'])), \
                 patch('control.audio_effects.QMediaDevices.audioOutputs', return_value=[]):
                idx = ctrl.panel.preset_combo.findData('walkman_vivid')
                ctrl.panel.preset_combo.setCurrentIndex(idx)
                pump(40)
                self.assertIn('Headphones (SPACE TRAVEL 2 ULTRA)', ctrl.device_profiles)
                self.assertEqual(ctrl.target_lufs, -14)

                # Plug in Dawn Pro 2 -> auto-applies studio_dawn_aria2 (-16 LUFS Exclusive Hi-Res)
                state['devs'].append('Headphones (DAWN PRO2)')
                state['default'] = 'Headphones (DAWN PRO2)'
                ctrl._handle_device_change()
                pump(40)
                self.assertEqual(ctrl.profile.output_mode, 'exclusive')
                self.assertEqual(ctrl.profile.upsample, 'hires_sync')
                self.assertEqual(ctrl.profile.tone, 'studio_aria2')
                self.assertEqual(ctrl.target_lufs, -16)

                # Customize 10-band EQ on Dawn Pro 2
                ctrl.set_custom_eq({'eq_enabled': True, 'eq_bands': (4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0)})
                pump(30)

                # Unplug Dawn Pro 2 -> restores Space Travel 2 Ultra profile cleanly
                state['devs'].remove('Headphones (DAWN PRO2)')
                state['default'] = 'Headphones (SPACE TRAVEL 2 ULTRA)'
                ctrl._handle_device_change()
                pump(40)
                self.assertEqual(ctrl.profile.tone, 'walkman_vivid')
                self.assertFalse(ctrl.profile.eq_enabled)
                self.assertEqual(ctrl.target_lufs, -14)

                # Plug Dawn Pro 2 back in -> restores custom 10-band EQ + Exclusive Hi-Res
                state['devs'].append('Headphones (DAWN PRO2)')
                state['default'] = 'Headphones (DAWN PRO2)'
                ctrl._handle_device_change()
                pump(40)
                self.assertTrue(ctrl.profile.eq_enabled)
                self.assertAlmostEqual(ctrl.profile.eq_bands[0], 4.0, places=1)
                self.assertEqual(ctrl.profile.output_mode, 'exclusive')

    def test_equalizer_ab_hold_compare_and_apo_txt_file_import_export(self):
        with isolated_window() as (window, root):
            ctrl = window.audio_effects
            dlg = ctrl.open_equalizer()
            dlg.curve_combo.setCurrentIndex(dlg.curve_combo.findData('aria2_harman'))
            pump(40)
            self.assertTrue(ctrl.profile.eq_enabled)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 2.5, places=1)

            # Hold A/B compare bypasses EQ cleanly without losing slider positions
            dlg.start_ab_compare()
            pump(30)
            self.assertFalse(ctrl.profile.eq_enabled)
            self.assertEqual(dlg.band_sliders[0].value(), 25)

            # Release A/B restores active 10-band EQ
            dlg.stop_ab_compare()
            pump(30)
            self.assertTrue(ctrl.profile.eq_enabled)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 2.5, places=1)

            # Export and import .txt APO preset file (zero .mkv audio files written)
            txt_path = root / 'aria2_harman.txt'
            self.assertTrue(dlg.export_apo_file(txt_path))
            self.assertTrue(txt_path.is_file())
            dlg.reset_flat()
            pump(30)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 0.0, places=1)
            self.assertTrue(dlg.import_apo_file(txt_path))
            pump(30)
            self.assertTrue(ctrl.profile.eq_enabled)
            self.assertAlmostEqual(ctrl.profile.eq_bands[0], 2.5, places=1)
            self.assertEqual(list(ctrl.cache.root.glob('*.mkv')), [])


if __name__ == '__main__':
    unittest.main()
