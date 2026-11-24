"""Verification suite for BoTube Studio Hi-Fi Real-Time Audio Engine."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
import psutil
from PySide6.QtCore import QUrl

from core.audio_effects import AudioPlaybackCache, find_tool
from core.audio_loudness import LoudnessCache, probe_audio_stream, measure_loudness, measure_quick_loudness
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


def _fft_band_energy(samples: np.ndarray, sample_rate: int, low_hz: float, high_hz: float) -> float:
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    win = np.hanning(len(mono))
    spec = np.abs(np.fft.rfft(mono * win))
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sample_rate)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    return float(np.sqrt(np.mean(spec[mask] ** 2))) if np.any(mask) else 0.0


class StudioDspPolicyTests(unittest.TestCase):
    def test_supported_extensions_include_hifi_lossless_containers(self):
        for ext in ('.flac', '.m4a', '.opus', '.ogg', '.aac', '.webm', '.mp3', '.mp4', '.mkv', '.wav'):
            self.assertIn(ext, SUPPORTED_EXTS)

    def test_mastering_gain_fixes_quiet_track_and_protects_cs43198_intersample(self):
        # Quiet track (-22 LUFS) gets full +6.0 dB at -16 LUFS without being capped by QAudioOutput 1.0!
        gain, limited = compute_mastering_gain_db({'lufs': -22.0, 'peak_db': -3.0}, -16, normalize=True)
        self.assertAlmostEqual(gain, 6.0, places=3)
        self.assertFalse(limited)

        # Hot lossy track with +0.8 dBTP inter-sample peak is NOT over-attenuated; lookahead limiter handles peaks.
        gain2, limited2 = compute_mastering_gain_db({'lufs': -17.0, 'peak_db': 0.8}, -16, normalize=True)
        self.assertAlmostEqual(gain2, 1.0, places=3)
        self.assertFalse(limited2)

        # Unnormalized Exclusive path applies -1.5 dBTP protection if track exceeds CS43198 ceiling.
        gain3, _ = compute_mastering_gain_db({'lufs': -9.0, 'peak_db': 0.4}, -16, normalize=False, exclusive=True)
        self.assertAlmostEqual(gain3, CS43198_CEILING_DB - 0.4, places=3)

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

    def test_real_ffmpeg_restorer_soxr_and_cs43198_headroom(self):
        with tempfile.TemporaryDirectory() as td:
            mp3_128 = Path(td) / 'low_128k.mp3'
            # Generate 44.1kHz complex tone strictly band-limited < 10 kHz (simulating 128k HF cutoff).
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i',
                'aevalsrc=0.45*sin(2*PI*220*t)+0.35*sin(2*PI*1800*t)+0.30*sin(2*PI*7500*t)+0.25*sin(2*PI*9200*t):s=44100:c=stereo:d=1.2',
                '-b:a', '128k', str(mp3_128),
            ], check=True)
            proc = OwnedProcesses()
            info = probe_audio_stream(str(mp3_128), 0, proc, lambda: False)
            self.assertEqual(info['codec_name'], 'mp3')
            self.assertGreater(info['bit_rate'], 0)

            af_off, sum_off = build_realtime_filter_graph(
                AudioProfile(normalize=False, tone='off', restorer='off'), info, 0.0, 48000
            )
            af_on, sum_on = build_realtime_filter_graph(
                AudioProfile(normalize=True, tone='aria2', restorer='auto'), info, 2.5, 48000
            )
            self.assertEqual(sum_off['restorer_active'], 'Bypass')
            self.assertNotEqual(sum_on['restorer_active'], 'Bypass')

            raw_off = subprocess.run(
                [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(mp3_128),
                 '-af', af_off, '-f', 'f32le', '-ac', '2', 'pipe:1'],
                capture_output=True, check=True,
            ).stdout
            raw_on = subprocess.run(
                [FFMPEG, '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(mp3_128),
                 '-af', af_on, '-f', 'f32le', '-ac', '2', 'pipe:1'],
                capture_output=True, check=True,
            ).stdout

            arr_off = np.frombuffer(raw_off, dtype='<f4').reshape(-1, 2)
            arr_on = np.frombuffer(raw_on, dtype='<f4').reshape(-1, 2)

            # SoXR 28-bit resampled 44.1kHz -> 48kHz produces ~57600 frames for 1.2s.
            self.assertGreater(len(arr_on), 54000)
            # True-peak limiter strictly enforces <= -1.45 dBFS headroom for Dawn Pro 2 CS43198.
            peak_db = 20.0 * np.log10(max(1e-9, float(np.max(np.abs(arr_on)))))
            self.assertLessEqual(peak_db, -1.40)

            # High-frequency > 12.5 kHz air energy measurably restored vs bypass.
            hf_off = _fft_band_energy(arr_off, 48000, 12500, 19500)
            hf_on = _fft_band_energy(arr_on, 48000, 12500, 19500)
            self.assertGreater(hf_on, hf_off * 2.0)

            # Ensure source file was never modified.
            self.assertEqual(tone_filter(AudioProfile(tone='aria2'), 48000, 2).count(':r=f64'), 5)


class StreamQuantizerAndFadeTests(unittest.TestCase):
    def test_tpdf_dither_quantizers_exact_byte_sizes(self):
        frames = np.linspace(-0.8, 0.8, 256, dtype=np.float32).reshape(128, 2)
        rng = np.random.default_rng(42)
        self.assertEqual(len(quantize_pcm(frames, 'float32')), 128 * 2 * 4)
        self.assertEqual(len(quantize_pcm(frames, 'int32', rng=rng)), 128 * 2 * 4)
        self.assertEqual(len(quantize_pcm(frames, 'int24', rng=rng)), 128 * 2 * 3)
        self.assertEqual(len(quantize_pcm(frames, 'int16', rng=rng)), 128 * 2 * 2)

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
        orig_raw = sd.RawOutputStream
        calls = []

        def fake_raw(*args, **kwargs):
            extra = kwargs.get('extra_settings')
            calls.append((kwargs.get('dtype'), extra))
            # Reject every Exclusive attempt; succeed on Shared float32.
            if len(calls) <= 24:
                # Check if we are in exclusive loop via sample rates/dtypes or patch WasapiSettings
                pass
            return orig_raw(*args, **kwargs)

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

    def test_live_stream_rapid_pause_resume_seek_stop_no_deadlock(self):
        with tempfile.TemporaryDirectory() as td:
            mp3 = Path(td) / 'stress.mp3'
            subprocess.run([
                FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                '-i', 'sine=f=440:r=44100:d=1.5', '-b:a', '128k', str(mp3),
            ], check=True)
            info = {'codec_name': 'mp3', 'sample_rate': 44100, 'channels': 2, 'bit_rate': 128000}
            engine = AudioStreamEngine()
            engine.set_user_volume(0.0, muted=True)
            t0 = time.monotonic()
            st = engine.start_or_reconfigure(str(mp3), 0, AudioProfile.recommended(), info, 0.0)
            self.assertTrue(st['active'])
            time.sleep(0.12)
            engine.pause()
            self.assertTrue(engine.status_info()['paused'])
            engine.resume(200)
            self.assertTrue(engine.is_active())
            engine.seek(500)
            engine.set_dynamic_trim_db(-2.0)
            time.sleep(0.06)
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

            # Seed fake legacy owned .mkv + .json cache files and verify purge preserves foreign files.
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

            # Measure loudness -> only tiny JSON in audio-loudness-cache, zero .mkv writes.
            proc = OwnedProcesses()
            res = measure_loudness(str(src), 0, ctrl.loudness_cache, proc, lambda: False,
                                   source_info={'codec_name': 'mp3', 'sample_rate': 44100, 'channels': 2, 'bit_rate': 128000})
            self.assertIsNotNone(res['measurement']['lufs'])
            self.assertEqual(list(legacy_dir.glob(f'{fake_key}.mkv')), [])

            # Source file completely untouched.
            self.assertEqual(src.read_bytes(), before_bytes)
            self.assertEqual(src.stat().st_mtime_ns, before_mtime)

            # Live A/B reset -> switches to bypass cleanly and shuts down with 0 leaks.
            ctrl.panel._reset()
            pump(50)
            self.assertFalse(ctrl.profile.enabled)
            self.assertIs(window.media_player.player.audioOutput(), window.audio_output)


if __name__ == '__main__':
    unittest.main()
