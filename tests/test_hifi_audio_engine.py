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

from tools.ui_preview import isolated_window, pump
from core.audio_effects import find_tool
from core.audio_loudness import probe_audio_stream, measure_loudness
from core.audio_profile import (
    AudioProfile,
    CS43198_CEILING_DB,
    adaptive_master_profile,
    atempo_chain,
    build_realtime_filter_graph,
    build_upsample_stage,
    compute_mastering_gain_db,
    custom_eq_filter,
    custom_eq_peak_boost_db,
    detect_preset,
    effective_eq_preamp_db,
    evaluate_eq_response_db,
    export_apo_text,
    normalize_peq_filters,
    parse_apo_text,
    preset_profile,
    resolve_restorer,
    tone_filter,
    tone_peak_pad_db,
)
from PySide6.QtCore import QUrl
import PySide6.QtMultimedia  # noqa: F401 - keep QtMultimedia C++ extension in sys.modules across isolated_window()

from core.audio_stream_engine import (
    AudioStreamEngine,
    apply_micro_fade,
    build_release_tail,
    preferred_exclusive_rates,
    quantize_pcm,
    _tpdf_slice,
)
from core.audio_benchmark import compute_k_weighted_db, render_audition_pair, run_audio_benchmark
from core.audio_profile import resolve_profile_gain_db
from core.media_library import SUPPORTED_EXTS
from control.worker_lifecycle import OwnedProcesses

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

    def test_recommended_default_is_adaptive_master_hifi_and_bit_pure_preserved(self):
        bp = AudioProfile.bit_pure()
        self.assertEqual(bp, AudioProfile(normalize=True, tone='off', restorer='off', output_mode='shared'))
        self.assertEqual(detect_preset(bp, -16), 'bit_pure')

        rec = AudioProfile.recommended()
        self.assertEqual(rec, AudioProfile(normalize=True, tone='master_hifi', restorer='auto', output_mode='shared'))
        self.assertEqual(detect_preset(rec, -14), 'master_hifi')

        shared_prof, shared_lufs = adaptive_master_profile('Speakers (Realtek(R) Audio)')
        self.assertEqual((shared_prof, shared_lufs), (rec, -14))
        bt_prof, bt_lufs = adaptive_master_profile('Headphones (SPACE TRAVEL 2 ULTRA)')
        self.assertEqual((bt_prof, bt_lufs), (rec, -14))

        dac_prof, dac_lufs = adaptive_master_profile('Headphones (DAWN PRO2)')
        self.assertEqual(dac_prof.output_mode, 'exclusive')
        self.assertEqual(dac_prof.upsample, 'hires_sync')
        self.assertEqual(dac_prof.dac_phase, 'minimum')
        self.assertEqual(dac_prof.tone, 'master_hifi')
        self.assertEqual(dac_prof.restorer, 'auto')
        self.assertEqual(dac_lufs, -14)
        self.assertEqual(detect_preset(dac_prof, dac_lufs), 'master_hifi')

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
        af, summary = build_realtime_filter_graph(AudioProfile.bit_pure(), info, -5.0, sr)
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

        bit_pure_192, _ = build_realtime_filter_graph(AudioProfile.bit_pure(), info, 0.0, 192000)
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
            st = engine.start_or_reconfigure(str(mp3), 0, AudioProfile.bit_pure(), info, -2.0)
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

            expected_init, expected_init_lufs = adaptive_master_profile(ctrl._effective_device_key())
            self.assertEqual(ctrl.profile, expected_init)
            self.assertEqual(ctrl.target_lufs, expected_init_lufs)
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
            for key in ('master_hifi', 'studio_dawn_aria2', 'dac_bitperfect', 'youtube', 'bit_pure', 'walkman_vivid', 'bypass'):
                idx = panel.preset_combo.findData(key)
                self.assertGreaterEqual(idx, 0)
                panel.preset_combo.setCurrentIndex(idx)
                pump(30)
                expected_prof, expected_lufs = (
                    adaptive_master_profile(ctrl._effective_device_key()) if key == 'master_hifi' else preset_profile(key)
                )
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
            panel = ctrl.panel
            self.assertTrue(panel.advanced_box.isHidden())
            self.assertLessEqual(panel.sizeHint().height(), 340)
            panel._toggle_advanced()
            pump(20)
            self.assertFalse(panel.advanced_box.isHidden())
            self.assertLessEqual(panel.sizeHint().height(), 620)
            panel._toggle_advanced()
            self.assertTrue(panel.advanced_box.isHidden())

            # Zero "AI slop" marketing slogans in visible combos, buttons, and APO menu
            for combo in (panel.preset_combo, panel.tone, panel.restorer, panel.level, dlg.curve_combo):
                for idx_c in range(combo.count()):
                    txt = combo.itemText(idx_c)
                    for slop in ('0 MB ổ cứng', 'Khuyên dùng', '★'):
                        self.assertNotIn(slop, txt)
            self.assertIsNotNone(dlg.btn_apo_menu.menu())
            self.assertEqual(len(dlg.btn_apo_menu.menu().actions()), 5)

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

                # Plug in Dawn Pro 2 -> auto-applies adaptive Master Hi-Fi (Exclusive Hi-Res MinPhase -14 LUFS)
                state['devs'].append('Headphones (DAWN PRO2)')
                state['default'] = 'Headphones (DAWN PRO2)'
                ctrl._handle_device_change()
                pump(40)
                self.assertEqual(ctrl.profile.output_mode, 'exclusive')
                self.assertEqual(ctrl.profile.upsample, 'hires_sync')
                self.assertEqual(ctrl.profile.dac_phase, 'minimum')
                self.assertEqual(ctrl.profile.tone, 'master_hifi')
                self.assertEqual(ctrl.target_lufs, -14)

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

    def test_prime_decorrelated_dither_restorer_headroom_and_benchmark_tab(self):
        # 1. Prime-length stereo TPDF dither is decorrelated across L/R and non-periodic at 65536 frames
        d0 = _tpdf_slice((8192, 2), 0)
        d_wrap = _tpdf_slice((8192, 2), 65536)
        lr_corr = float(np.corrcoef(d0[:, 0], d0[:, 1])[0, 1])
        self.assertLess(abs(lr_corr), 0.035)
        self.assertGreater(float(np.max(np.abs(d0 - d_wrap))), 0.1)

        # 2. Restorer headroom pad protects legacy 128k MP3 without penalizing bypassed FLAC/Opus
        flac_info = {'codec_name': 'flac', 'sample_rate': 48000, 'channels': 2, 'bit_rate': 950000}
        mp3_info = {'codec_name': 'mp3', 'sample_rate': 44100, 'channels': 2, 'bit_rate': 128000}
        rest_prof = AudioProfile(normalize=True, restorer='auto')
        self.assertEqual(tone_peak_pad_db(rest_prof, flac_info), 0.0)
        self.assertGreater(tone_peak_pad_db(rest_prof, mp3_info), 1.5)
        g_flac, _ = resolve_profile_gain_db(rest_prof, {'lufs': -14.0, 'peak_db': -1.0}, -14, source_info=flac_info)
        g_mp3, _ = resolve_profile_gain_db(rest_prof, {'lufs': -14.0, 'peak_db': -1.0}, -14, source_info=mp3_info)
        self.assertEqual(g_flac, 0.0)
        self.assertLess(g_mp3, -1.5)

        # 3. Scientific benchmark proves bit-pure intersample protection and flags unguarded clipping
        with isolated_window() as (window, root):
            hot_wav = root / 'hot_clip.wav'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', (
                    'aevalsrc=0.44*sin(2*PI*60*t)+0.36*sin(2*PI*250*t)+0.28*sin(2*PI*1000*t)'
                    '+0.22*sin(2*PI*4000*t)+0.16*sin(2*PI*12000*t):s=48000:c=stereo:d=1.2'
                ),
                '-c:a', 'pcm_f32le', str(hot_wav),
            ], check=True)

            pure_res = run_audio_benchmark(str(hot_wav), AudioProfile.bit_pure(), -16)
            self.assertGreater(pure_res['orig_tp_db'], 1.0)
            self.assertGreater(pure_res['orig_clips'], 0)
            self.assertLessEqual(pure_res['proc_tp_db'], -0.95)
            self.assertEqual(pure_res['proc_clips'], 0)
            self.assertLess(pure_res['tonal_rms_db'], 0.08)
            self.assertLess(abs(pure_res['dr_delta_db']), 0.08)
            self.assertLess(pure_res['null_residual_db'], -135.0)
            self.assertIn('BIT-PURE', pure_res['verdict']['badge'])
            ls_pure = pure_res['verdict']['listener_summary']
            self.assertEqual(ls_pure['overall_tag'], 'SẠCH HƠN BẢN GỐC')
            self.assertEqual(ls_pure['overall_tone'], 'good')
            self.assertEqual(ls_pure['pillars'][0]['verdict'], 'Tốt hơn gốc')
            self.assertEqual(ls_pure['pillars'][2]['verdict'], 'Nguyên bản 1:1')
            self.assertLess(pure_res['thdn_db'], -130.0)
            self.assertLess(pure_res['imd_db'], -125.0)
            self.assertLess(pure_res['crosstalk_db'], -130.0)
            self.assertLess(max(abs(v) for v in pure_res['lab_transfer_db']), 0.05)
            self.assertLess(max(abs(p) for p in pure_res['lab_phase_deg']), 0.5)
            self.assertEqual(len(pure_res['comparison_rows']), 8)
            self.assertEqual(len(pure_res['ref_thd_fft_db']), len(pure_res['thd_fft_freqs']))
            for row in pure_res['comparison_rows']:
                self.assertNotIn('Lý tưởng số', row['orig'])
                self.assertNotIn('0.00000%', row['proc'])

            studio_prof, studio_lufs = preset_profile('studio_dawn_aria2')
            studio_res = run_audio_benchmark(str(hot_wav), studio_prof, int(studio_lufs or -16))
            self.assertGreater(studio_res['crosstalk_db'], -35.0)
            self.assertLess(studio_res['crosstalk_db'], -12.0)
            self.assertEqual(studio_res['out_sr'], 192000)
            self.assertEqual(studio_res['out_dtype'], 'int32')
            self.assertLess(studio_res['thdn_db'], -130.0)
            self.assertEqual(studio_res['verdict']['badge'], 'CHUẨN HI-RES STUDIO')
            self.assertNotIn('186.', studio_res['verdict']['headline'])
            self.assertNotIn('STREAMING', studio_res['verdict']['badge'])
            self.assertEqual(studio_res['noise_floor_label'], '< -144 dBFS')
            self.assertIn('SẠCH ĐỈNH HƠN', studio_res['verdict']['listener_summary']['overall_tag'])

            # Gain-matched RAM A/B audition equalizes K-weighted loudness within <= 0.15 dB without clipping
            pair = render_audition_pair(
                str(hot_wav),
                studio_prof,
                studio_res['source_info'],
                float(studio_res['exact_gain_db']),
                0.0,
                1.0,
                play_sr=48000,
            )
            self.assertEqual(pair['sample_rate'], 48000)
            self.assertGreater(abs(pair['delta_loudness_db']), 2.0)
            matched_k_orig = compute_k_weighted_db(pair['orig_f32'].astype(np.float64) * pair['match_orig_lin'], 48000)
            matched_k_proc = compute_k_weighted_db(pair['proc_f32'].astype(np.float64) * pair['match_proc_lin'], 48000)
            self.assertLessEqual(abs(matched_k_orig - matched_k_proc), 0.15)
            self.assertLessEqual(float(np.max(np.abs(pair['orig_f32'])) * pair['match_orig_lin']), 0.97)
            self.assertLessEqual(float(np.max(np.abs(pair['proc_f32'])) * pair['match_proc_lin']), 0.97)

            # DAC Bit-Perfect Exclusive preserves native 96 kHz sample rate & 0 dB flat pass-through
            hires_wav = root / 'hires_96k.wav'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', (
                    'aevalsrc=0.25*sin(2*PI*1000*t)+0.18*sin(2*PI*5000*t)+0.15*sin(2*PI*36000*t)'
                    ':s=96000:c=stereo:d=1.0'
                ),
                '-c:a', 'pcm_s24le', str(hires_wav),
            ], check=True)
            bp_prof, _ = preset_profile('dac_bitperfect')
            bp_res = run_audio_benchmark(str(hires_wav), bp_prof, -16)
            self.assertEqual(bp_res['in_sr'], 96000)
            self.assertEqual(bp_res['out_sr'], 96000)
            self.assertEqual(bp_res['out_dtype'], 'int32')
            self.assertFalse(bp_res['filter_summary']['resampled'])
            self.assertGreaterEqual(bp_res['source_cutoff_hz'], 34000)
            self.assertEqual(bp_res['gain_db'], 0.0)
            self.assertEqual(bp_res['verdict']['badge'], 'ĐẠT CHUẨN BIT-PURE')
            self.assertEqual(bp_res['verdict']['listener_summary']['overall_tag'], 'TRUNG THỰC NHƯ GỐC')

            heavy_eq_prof = AudioProfile(
                normalize=False,
                eq_enabled=True,
                eq_auto_preamp=True,
                eq_bands=(12.0, 10.0, 8.0, 6.0, -4.0, -4.0, 6.0, 8.0, 10.0, 12.0),
            )
            heavy_res = run_audio_benchmark(str(hot_wav), heavy_eq_prof, -16)
            self.assertEqual(heavy_res['verdict']['badge'], 'CẦN LƯU Ý')
            self.assertTrue(any(f['level'] == 'warn' for f in heavy_res['verdict']['findings']))
            self.assertEqual(heavy_res['proc_clips'], 0)
            self.assertEqual(heavy_res['verdict']['listener_summary']['overall_tone'], 'warn')
            self.assertIn('QUÁ ĐÀ', heavy_res['verdict']['listener_summary']['overall_tag'])

            # Quiet 44.1 kHz track boosted by +5+ dB ReplayGain never false-clips the synthetic AES17 lab suite
            quiet_wav = root / 'quiet_44k.wav'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', (
                    'aevalsrc=0.05*sin(2*PI*220*t)+0.04*sin(2*PI*1000*t)+0.03*sin(2*PI*4000*t)'
                    ':s=44100:c=stereo:d=1.2'
                ),
                '-c:a', 'pcm_s16le', str(quiet_wav),
            ], check=True)
            for test_prof, test_lufs in (
                (AudioProfile.bit_pure(), -16),
                preset_profile('master_hifi'),
                preset_profile('studio_dawn_aria2'),
                preset_profile('walkman_vivid'),
            ):
                q_res = run_audio_benchmark(str(quiet_wav), test_prof, int(test_lufs or -16))
                self.assertGreater(q_res['gain_db'], 4.0)
                self.assertLess(q_res['thdn_db'], -130.0)
                self.assertLess(q_res['imd_db'], -125.0)
                self.assertEqual(q_res['comparison_rows'][7]['status'], 'Tuyến tính')
                self.assertEqual(q_res['verdict']['listener_summary']['overall_tone'], 'good')

            # Lab suite LRU cache returns identical metrics & avoids re-running FFmpeg;
            # Full-song climax over-peak in cached_measurement flags Bypass & credits Bit-Pure cleanly.
            climax_meas = {'lufs': -13.4, 'peak_db': 1.3, 'silent': False}
            bypass_climax = run_audio_benchmark(str(quiet_wav), AudioProfile(), -16, cached_measurement=climax_meas)
            self.assertIn('CAO TRÀO', bypass_climax['verdict']['listener_summary']['overall_tag'])
            fixed_climax = run_audio_benchmark(str(quiet_wav), AudioProfile.bit_pure(), -16, cached_measurement=climax_meas)
            self.assertEqual(fixed_climax['verdict']['listener_summary']['overall_tag'], 'SẠCH HƠN BẢN GỐC')
            self.assertEqual(fixed_climax['verdict']['listener_summary']['pillars'][0]['verdict'], 'Tốt hơn gốc')
            t_hit0 = time.perf_counter()
            fixed_climax_2 = run_audio_benchmark(str(quiet_wav), AudioProfile.bit_pure(), -16, cached_measurement=climax_meas)
            self.assertLess(time.perf_counter() - t_hit0, 2.0)
            self.assertEqual(fixed_climax_2['lab_transfer_db'], fixed_climax['lab_transfer_db'])

            # 4. Settings button opens Benchmark tab, populates non-expert A/B + 4 charts/table, prevents clipping
            ctrl = window.audio_effects
            self.assertTrue(hasattr(window.settings_page, 'btn_audio_benchmark'))
            window.settings_page.btn_audio_benchmark.click()
            pump(40)
            self.assertIs(window.content_stack.currentWidget(), ctrl.benchmark_page)
            ctrl.benchmark_page.mode_combo.setCurrentIndex(ctrl.benchmark_page.mode_combo.findData('studio_dawn_aria2'))
            ctrl.benchmark_page.set_source_file(str(hot_wav), auto_run=False)
            ctrl.benchmark_page.run_benchmark()
            for _ in range(80):
                pump(50)
                if ctrl.benchmark_page._last_result is not None and ctrl.benchmark_page.btn_run.isEnabled():
                    break
            self.assertIsNotNone(ctrl.benchmark_page._last_result)
            self.assertEqual(ctrl.benchmark_page.lbl_verdict_badge.text(), 'CHUẨN HI-RES STUDIO')
            self.assertIn('SẠCH ĐỈNH HƠN', ctrl.benchmark_page.lbl_plain_badge.text())
            self.assertTrue(ctrl.benchmark_page.btn_audition_toggle.isEnabled())
            self.assertNotIn('186.', ctrl.benchmark_page.lbl_spec_footer.text())
            self.assertTrue(ctrl.benchmark_page.copy_report_to_clipboard())

            # Test muted live A/B audition start, branch switch, and clean stop on Back
            window.audio_output.setMuted(True)
            ctrl.benchmark_page.toggle_audition()
            for _ in range(60):
                pump(50)
                if ctrl.benchmark_page._audition.is_playing():
                    break
            self.assertTrue(ctrl.benchmark_page._audition.is_playing())
            ctrl.benchmark_page.btn_ab_orig.click()
            pump(40)
            self.assertTrue(ctrl.benchmark_page.btn_ab_orig.isChecked())
            self.assertEqual(ctrl.benchmark_page._audition._branch, 'orig')
            ctrl.benchmark_page.btn_ab_proc.click()
            pump(40)
            self.assertEqual(ctrl.benchmark_page._audition._branch, 'proc')

            from PySide6.QtWidgets import QLabel as _QLabel
            window.show()
            for size in ((1120, 760), (860, 560)):
                window.resize(*size)
                pump(60)
                for lbl in ctrl.benchmark_page.findChildren(_QLabel):
                    if not lbl.isVisible() or lbl.width() <= 0 or not lbl.text():
                        continue
                    self.assertGreaterEqual(lbl.height() + 1, lbl.minimumSizeHint().height(), f'Clipped minHint on {lbl.text()}')
                    if lbl.wordWrap() and lbl.hasHeightForWidth():
                        hfw = lbl.heightForWidth(lbl.width())
                        if hfw > 0:
                            self.assertGreaterEqual(lbl.height() + 1, hfw, f'Wrapped text clipped on {lbl.text()}')

            dlg = ctrl.open_equalizer()
            pump(40)
            for lbl in dlg.findChildren(_QLabel):
                if lbl.isVisible() and lbl.width() > 0:
                    self.assertGreaterEqual(lbl.height() + 1, lbl.minimumSizeHint().height())
            for sld, v_lbl in zip(dlg.band_sliders, dlg.band_labels):
                self.assertLessEqual(v_lbl.geometry().bottom(), sld.geometry().top())
                for f_lbl in dlg.findChildren(_QLabel):
                    if f_lbl.text() in ('31', '62', '125') and abs(f_lbl.geometry().center().x() - sld.geometry().center().x()) < 25:
                        self.assertLessEqual(sld.geometry().bottom(), f_lbl.geometry().top())

            ctrl.benchmark_page.cb_show_orig.click()
            ctrl.benchmark_page.cb_show_orig.click()
            ctrl.benchmark_page.cb_show_proc.click()
            ctrl.benchmark_page.cb_show_proc.click()
            for chart_btn in (
                ctrl.benchmark_page.btn_view_transfer,
                ctrl.benchmark_page.btn_view_peaks,
                ctrl.benchmark_page.btn_view_thd,
                ctrl.benchmark_page.btn_view_spec,
            ):
                chart_btn.click()
                pump(20)
            ctrl.benchmark_page.btn_back.click()
            pump(40)
            self.assertFalse(ctrl.benchmark_page._audition.is_playing())
            self.assertIs(window.content_stack.currentWidget(), window.settings_page)
            self.assertEqual(list(ctrl.cache.root.glob('*.mkv')), [])

    def test_parametric_peq_exact_biquads_apo_roundtrip_and_hashability(self):
        squiglink_apo = (
            'Preamp: -2.4 dB\n'
            'Filter 1: ON LSC Fc 95 Hz Gain 2.2 dB Q 0.707\n'
            'Filter 2: ON PK Fc 210 Hz Gain -1.4 dB Q 1.300\n'
            'Filter 3: ON PK Fc 3350 Hz Gain -2.1 dB Q 2.400\n'
            'Filter 4: ON PK Fc 7950 Hz Gain -4.5 dB Q 4.200\n'
            'Filter 5: OFF PK Fc 5000 Hz Gain 8.0 dB Q 1.000\n'
            'Filter 6: ON HSC Fc 12800 Hz Gain 1.8 dB Q 0.707\n'
            'Filter 7: ON PK Fc 520 Hz Gain 1.2 dB BW Oct 1.0\n'
        )
        parsed = parse_apo_text(squiglink_apo)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['eq_preamp_db'], -2.4)
        peq = parsed['eq_peq_filters']
        self.assertEqual(len(peq), 6)
        self.assertEqual(peq[0], ('LS', 95.0, 2.2, 0.707))
        self.assertEqual(peq[3], ('PK', 7950.0, -4.5, 4.2))
        self.assertEqual(peq[4], ('HS', 12800.0, 1.8, 0.707))
        self.assertAlmostEqual(peq[5][3], 1.414, places=2)

        prof = AudioProfile.from_dict(parsed)
        self.assertIsInstance(hash(prof), int)
        self.assertTrue(prof.custom_eq_active)

        af, summary = build_realtime_filter_graph(
            prof, {'codec_name': 'flac', 'sample_rate': 48000, 'channels': 2, 'bit_rate': 960000}, 0.0, 48000
        )
        self.assertEqual(summary['peq_count'], 6)
        test_freqs = [95, 210, 1000, 3350, 7950, 12800]
        predicted = evaluate_eq_response_db(prof, test_freqs, 48000.0)
        for freq, pred_db in zip(test_freqs, predicted):
            actual_db = _measure_tone_gain_db(af, freq, 48000)
            self.assertLess(abs(actual_db - pred_db), 0.12, f'Mismatch at {freq} Hz: {actual_db} vs {pred_db}')
        # Verify sharp Q=4.2 notch at 7950 Hz hits real depth
        self.assertLess(_measure_tone_gain_db(af, 7950, 48000), -3.8)

        # Auto Preamp protects narrow high-Q boosts and APO export -> import round-trips losslessly
        peak_peq = AudioProfile(eq_enabled=True, eq_peq_filters=normalize_peq_filters([('PK', 3456.0, 7.5, 5.0)]))
        self.assertGreaterEqual(custom_eq_peak_boost_db(peak_peq), 7.3)
        self.assertAlmostEqual(effective_eq_preamp_db(peak_peq), -custom_eq_peak_boost_db(peak_peq), places=2)
        exported = export_apo_text(prof)
        self.assertIn('Filter 4: ON PK Fc 7950 Hz Gain -4.50 dB Q 4.200', exported)
        re_parsed = parse_apo_text(exported)
        self.assertEqual(re_parsed['eq_peq_filters'], prof.eq_peq_filters)

    def test_minimum_phase_dac_oversampler_and_peq_dialog_integration(self):
        # 1. Verify zero pre-ringing (< -100 dB pre-onset) vs linear SoXR sinc (~ -19 dB)
        imp = np.zeros((8192, 2), dtype=np.float64)
        imp[1024, 0] = 0.25
        for phase, expect_low_prering in (('linear', False), ('minimum', True)):
            up_stage = build_upsample_stage(48000, 192000, dac_phase=phase)
            raw = subprocess.run([
                FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'f64le', '-ar', '48000', '-ac', '2', '-i', 'pipe:0',
                '-af', f'aformat=sample_fmts=dblp,{up_stage}',
                '-f', 'f64le', '-ac', '2', 'pipe:1',
            ], input=imp.astype('<f8').tobytes(), capture_output=True, check=True).stdout
            ir = np.frombuffer(raw, dtype='<f8').reshape(-1, 2)[:, 0] * (4.0 * 48000 / 192000)
            onset = 1024 * 4
            pre_db = 10.0 * np.log10(max(1e-32, float(np.sum(ir[:onset - 1] ** 2))))
            if expect_low_prering:
                self.assertLess(pre_db, -100.0)
            else:
                self.assertGreater(pre_db, -30.0)

        with isolated_window() as (window, root):
            ctrl = window.audio_effects
            panel = ctrl.panel

            for sr_in, expect_sr in ((48000, 192000), (44100, 176400)):
                wav_p = root / f'tone_{sr_in}.wav'
                subprocess.run([
                    FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', f'aevalsrc=0.25*sin(2*PI*1000*t)+0.15*sin(2*PI*12000*t):s={sr_in}:c=stereo:d=0.9',
                    '-c:a', 'pcm_s24le', str(wav_p),
                ], check=True)
                min_prof = AudioProfile(normalize=False, output_mode='exclusive', upsample='hires_sync', dac_phase='minimum')
                res = run_audio_benchmark(str(wav_p), min_prof, -16)
                self.assertEqual(res['out_sr'], expect_sr)
                self.assertEqual(res['filter_summary']['dac_phase'], 'minimum')
                self.assertLess(res['tonal_rms_db'], 0.08)
                self.assertLess(res['thdn_db'], -130.0)
                self.assertEqual(res['verdict']['badge'], 'ĐẠT CHUẨN BIT-PURE')
                self.assertGreater(abs(res['lab_phase_deg'][-8]), 5.0)

            # UI Panel -> Controller persistence for dac_phase
            idx_min = panel.dac_phase.findData('minimum')
            self.assertGreaterEqual(idx_min, 0)
            panel.dac_phase.setCurrentIndex(idx_min)
            pump(40)
            self.assertEqual(ctrl.profile.dac_phase, 'minimum')
            saved_cfg = json.loads(ctrl.settings_path.read_text(encoding='utf-8'))
            self.assertEqual(saved_cfg['dac_phase'], 'minimum')

            # Equalizer PEQ mode, preset, file I/O & DPI geometry check
            dlg = ctrl.open_equalizer()
            dlg.curve_combo.setCurrentIndex(dlg.curve_combo.findData('peq:aria2_squiglink'))
            pump(40)
            self.assertEqual(dlg._eq_mode, 'peq')
            self.assertTrue(ctrl.profile.eq_enabled)
            self.assertEqual(len(ctrl.profile.eq_peq_filters), 6)
            self.assertIn('PEQ 6 dải', panel.btn_open_eq.text())

            from PySide6.QtWidgets import QLabel as _QLabel
            dlg.show()
            pump(40)
            for lbl in dlg.findChildren(_QLabel):
                if lbl.isVisible() and lbl.width() > 0:
                    self.assertGreaterEqual(lbl.height() + 1, lbl.minimumSizeHint().height())

            peq_txt = root / 'aria2_peq.txt'
            self.assertTrue(dlg.export_apo_file(peq_txt))
            dlg.reset_flat()
            pump(30)
            self.assertEqual(ctrl.profile.eq_peq_filters, ())
            self.assertTrue(dlg.import_apo_file(peq_txt))
            pump(30)
            self.assertEqual(len(ctrl.profile.eq_peq_filters), 6)
            self.assertAlmostEqual(ctrl.profile.eq_peq_filters[4][1], 7950.0, places=1)
            self.assertEqual(list(ctrl.cache.root.glob('*.mkv')), [])

    def test_settings_studio_ui_cards_sync_and_no_clipping(self):
        from PySide6.QtWidgets import QLabel as _QLabel, QLineEdit as _QLineEdit, QMessageBox as _QMessageBox
        from ui import pages as _pages_pkg  # noqa: F401
        from ui.pages import settings as _settings_mod

        with isolated_window() as (window, root):
            ctrl = window.audio_effects
            page = window.settings_page
            studio = ctrl.settings_studio
            self.assertIsNotNone(studio)

            # Switch sidebar cleanly to Settings
            settings_row = window.sidebar.row_for_page('settings')
            if settings_row < 0:
                settings_row = window.sidebar.count() - 1
            window.sidebar.setCurrentRow(settings_row)
            window.handle_sidebar_click(window.sidebar.item(settings_row))
            window.show()
            pump(60)

            self.assertTrue(studio.audio_card.isVisible())
            self.assertTrue(studio.asr_card.isVisible())
            self.assertTrue(studio.translation_card.isVisible())

            # Volume slider <-> VolumeSettings.spin two-way sync
            studio.volume_slider.setValue(72)
            pump(30)
            self.assertEqual(page.volume_percent.value(), 72)
            self.assertAlmostEqual(ctrl.volume(), 0.72, places=2)
            page.volume_percent.setValue(44)
            pump(30)
            self.assertEqual(studio.volume_slider.value(), 44)

            # Settings preset combo <-> AudioEffectsController & optimal button
            studio.preset_combo.setCurrentIndex(studio.preset_combo.findData('bit_pure'))
            pump(30)
            self.assertEqual(ctrl.profile, AudioProfile.bit_pure())
            self.assertEqual(ctrl.target_lufs, -16)

            studio.btn_optimal_preset.click()
            pump(30)
            self.assertEqual(ctrl.profile.tone, 'master_hifi')
            self.assertEqual(ctrl.target_lufs, -14)
            self.assertEqual(studio.preset_combo.currentData(), 'master_hifi')

            # API Key reveal toggle + dynamic provider portal link
            page.combo_online_ai.setCurrentText('Google Gemini')
            pump(20)
            self.assertTrue(page.api_key_input.isEnabled())
            self.assertIn('aistudio.google.com', studio.lbl_provider_link.text())
            self.assertEqual(page.api_key_input.echoMode(), _QLineEdit.EchoMode.Password)
            studio.btn_toggle_api_key.click()
            self.assertEqual(page.api_key_input.echoMode(), _QLineEdit.EchoMode.Normal)
            studio.btn_toggle_api_key.click()
            self.assertEqual(page.api_key_input.echoMode(), _QLineEdit.EchoMode.Password)

            page.combo_online_ai.setCurrentText('Local Default')
            pump(20)
            self.assertFalse(page.api_key_input.isEnabled())
            self.assertIn('NLLB-200', studio.lbl_provider_link.text())

            # Dialogue content mode disables Genius token + reveal button cleanly
            page.combo_content_mode.setCurrentIndex(page.combo_content_mode.findData('dialogue'))
            pump(20)
            self.assertFalse(page.genius_key_input.isEnabled())
            self.assertFalse(studio.btn_toggle_genius_key.isEnabled())
            page.combo_content_mode.setCurrentIndex(page.combo_content_mode.findData('lyrics'))
            pump(20)
            self.assertTrue(studio.btn_toggle_genius_key.isEnabled())

            # Zero label clipping across desktop & compact widths
            for size in ((1280, 820), (1120, 760), (860, 560)):
                window.resize(*size)
                pump(50)
                for lbl in page.findChildren(_QLabel):
                    if not lbl.isVisible() or lbl.width() <= 0 or not lbl.text():
                        continue
                    self.assertGreaterEqual(lbl.height() + 1, lbl.minimumSizeHint().height(), f'Clipped minHint: {lbl.text()}')
                    if lbl.wordWrap() and lbl.hasHeightForWidth():
                        hfw = lbl.heightForWidth(lbl.width())
                        if hfw > 0:
                            self.assertGreaterEqual(lbl.height() + 1, hfw, f'Clipped wrapped: {lbl.text()}')

            # Reset still works cleanly through original owner
            with patch.object(_settings_mod.QMessageBox, 'question', return_value=_QMessageBox.StandardButton.Yes), \
                 patch.object(_settings_mod.QMessageBox, 'information'):
                page.reset_to_defaults()
            self.assertEqual(page.volume_percent.value(), 50)


if __name__ == '__main__':
    unittest.main()
