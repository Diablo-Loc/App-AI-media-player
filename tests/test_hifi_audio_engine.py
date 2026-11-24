"""Verification suite for BoTube Studio Hi-Fi Real-Time Audio Engine."""
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
    resolve_restorer,
    tone_filter,
)
from core.audio_stream_engine import AudioStreamEngine, apply_micro_fade, quantize_pcm
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

    def test_mastering_gain_fixes_quiet_track_and_protects_cs43198_intersample(self):
        # Quiet dynamic track (-22 LUFS, peak -8 dBTP) gets full +6.0 dB at -16 LUFS without QAudioOutput 1.0 ceiling!
        gain, limited = compute_mastering_gain_db({'lufs': -22.0, 'peak_db': -8.0}, -16, normalize=True)
        self.assertAlmostEqual(gain, 6.0, places=3)
        self.assertFalse(limited)

        # Quiet track with a hot -3 dBTP transient stops cleanly at -1.0 dBTP (+2.0 dB) so transients never clip.
        gain_p, limited_p = compute_mastering_gain_db({'lufs': -22.0, 'peak_db': -3.0}, -16, normalize=True)
        self.assertAlmostEqual(gain_p, 2.0, places=3)
        self.assertTrue(limited_p)

        # Hot track with +0.8 dBTP peak is attenuated safely to -1.0 dBTP ceiling without squashing dynamics.
        gain2, limited2 = compute_mastering_gain_db({'lufs': -17.0, 'peak_db': 0.8}, -16, normalize=True)
        self.assertAlmostEqual(gain2, CS43198_CEILING_DB - 0.8, places=3)
        self.assertTrue(limited2)

        # Unnormalized Exclusive path applies -1.2 dBTP protection if track exceeds ceiling.
        gain3, _ = compute_mastering_gain_db({'lufs': -9.0, 'peak_db': 0.4}, -16, normalize=False, exclusive=True)
        self.assertAlmostEqual(gain3, -1.2 - 0.4, places=3)

        # Silence guard never amplifies digital noise floor.
        gain4, limited4 = compute_mastering_gain_db({'lufs': None, 'peak_db': None, 'silent': True}, -16, normalize=True)
        self.assertEqual((gain4, limited4), (0.0, False))

    def test_auto_restorer_targets_low_bitrate_and_bypasses_lossless(self):
        prof = AudioProfile.recommended()
        self.assertEqual(prof, AudioProfile(normalize=True, tone='aria2', restorer='auto', output_mode='shared'))
        r128 = resolve_restorer(prof, {'codec_name': 'mp3', 'bit_rate': 128000, 'sample_rate': 44100})
        self.assertIsNotNone(r128)
        self.assertIn('128k', r128['mode'])

        r160 = resolve_restorer(prof, {'codec_name': 'aac', 'bit_rate': 160000, 'sample_rate': 44100})
        self.assertIsNotNone(r160)

        # Strictly bypass FLAC, PCM, and high-bitrate Opus/AAC.
        self.assertIsNone(resolve_restorer(prof, {'codec_name': 'flac', 'bit_rate': 950000, 'sample_rate': 96000}))
        self.assertIsNone(resolve_restorer(prof, {'codec_name': 'pcm_s24le', 'bit_rate': 2304000, 'sample_rate': 48000}))
        self.assertIsNone(resolve_restorer(prof, {'codec_name': 'opus', 'bit_rate': 256000, 'sample_rate': 48000}))

    def test_atempo_chain_handles_arbitrary_speeds(self):
        self.assertEqual(atempo_chain(1.0), '')
        self.assertEqual(atempo_chain(1.5), 'atempo=1.5000')
        self.assertEqual(atempo_chain(0.25), 'atempo=0.5,atempo=0.5000')
        self.assertEqual(atempo_chain(3.0), 'atempo=2.0,atempo=1.5000')

    def test_clean_frequency_response_no_crystalizer_and_cs43198_ceiling(self):
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

            af, summary = build_realtime_filter_graph(AudioProfile.recommended(), info, 0.0, 48000)
            self.assertNotIn('crystalizer', af)
            self.assertNotIn('asoftclip', af)
            self.assertNotIn('asplit', af)
            self.assertNotEqual(summary['restorer_active'], 'Bypass')

            # Acoustic flatness guard: 1 kHz must be within +/- 1.0 dB of 0 dB; 14 kHz musical (+0.5..+3.8 dB).
            g60 = _measure_tone_gain_db(af, 60)
            g220 = _measure_tone_gain_db(af, 220)
            g1k = _measure_tone_gain_db(af, 1000)
            g8k = _measure_tone_gain_db(af, 8000)
            g14k = _measure_tone_gain_db(af, 14000)
            self.assertGreaterEqual(g1k, -1.0)
            self.assertLessEqual(g1k, 1.0)
            self.assertGreaterEqual(g60, 0.5)
            self.assertLessEqual(g220, -0.3)
            self.assertLessEqual(g8k, -0.3)
            self.assertGreaterEqual(g14k, 0.5)
            self.assertLessEqual(g14k, 3.8)

            # Safety limiter ceiling strictly <= -0.95 dBFS even with hot drive.
            af_hot, _ = build_realtime_filter_graph(AudioProfile.recommended(), info, 6.0, 48000)
            raw_hot = subprocess.run(
                [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(mp3_128),
                 '-af', af_hot, '-f', 'f32le', '-ac', '2', 'pipe:1'],
                capture_output=True, check=True,
            ).stdout
            arr_hot = np.frombuffer(raw_hot, dtype='<f4').reshape(-1, 2)
            peak_db = 20.0 * np.log10(max(1e-9, float(np.max(np.abs(arr_hot)))))
            self.assertLessEqual(peak_db, -0.95)
            self.assertEqual(tone_filter(AudioProfile(tone='aria2'), 48000, 2).count(':r=f64'), 5)


class StreamQuantizerAndFadeTests(unittest.TestCase):
    def test_tpdf_dither_quantizers_exact_byte_sizes(self):
        frames = np.linspace(-0.8, 0.8, 256, dtype=np.float32).reshape(128, 2)
        rng = np.random.default_rng(42)
        self.assertEqual(len(quantize_pcm(frames, 'float32')), 128 * 2 * 4)
        self.assertEqual(len(quantize_pcm(frames, 'int32', rng=rng)), 128 * 2 * 4)
        self.assertEqual(len(quantize_pcm(frames, 'int24', rng=rng)), 128 * 2 * 3)
        self.assertEqual(len(quantize_pcm(frames, 'int16', rng=rng)), 128 * 2 * 2)
        # Also verify static TPDF table path (rng=None)
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
            st = engine.start_or_reconfigure(str(mp3), 0, AudioProfile.recommended(), info, 0.0)
            self.assertTrue(st['active'])
            time.sleep(0.45)
            st_mid = engine.status_info()
            self.assertEqual(st_mid['underflows'], 0)
            engine.pause()
            self.assertTrue(engine.status_info()['paused'])
            engine.resume(200)
            self.assertTrue(engine.is_active())
            engine.seek(500)
            engine.set_dynamic_trim_db(-2.0)
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


if __name__ == '__main__':
    unittest.main()
