"""Regression tests for app-wide startup, RAM/VRAM, CPU timer, and bundle size optimizations."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaPlayer

import build_app
from core import audio_stream_engine
from subtitle.mode import SubtitleMode
from tools.ui_preview import isolated_window
from ui.subs_ui.subtitle_workers import TranslationWorker

ROOT = Path(__file__).resolve().parents[1]


class AppOptimizationTests(unittest.TestCase):
    def test_dead_unreferenced_modules_are_removed(self):
        removed = (
            'app/control/ai_process_manager.py',
            'app/core/media_control.py',
            'app/pipeline/asr_engine.py',
            'app/pipeline/forced_aligner.py',
            'app/pipeline/vocal_separator.py',
            'app/subtitle/ass/ass_parser.py',
            'app/test/test_ai_controller.py',
            'app/test/test_aligner_optimizations.py',
        )
        for rel in removed:
            self.assertFalse((ROOT / rel).exists(), f'Dead module still exists: {rel}')

    def test_cold_startup_import_skips_heavy_network_phonetic_and_ai_packages(self):
        code = """
import sys
import ui.main_window  # noqa: F401
import subtitle.phonetics as phonetics
import core.audio_stream_engine as ase

forbidden = (
    'yt_dlp', 'requests', 'urllib3', 'pykakasi', 'pypinyin',
    'tracemalloc', 'torch', 'transformers', 'faster_whisper', 'lyricsgenius',
)
leaked = [m for m in forbidden if m in sys.modules]
assert not leaked, f'Eagerly imported heavy modules at startup: {leaked}'
assert ase._TPDF_TABLE is None, 'TPDF dither table allocated eagerly before integer PCM quantization'
assert phonetics._KAKASI_INSTANCE is None
assert phonetics._PYPINYIN_BUNDLE is None
print('LAZY_STARTUP_OK')
"""
        env = dict(
            os.environ,
            PYTHONPATH=f"{ROOT}{os.pathsep}{ROOT / 'app'}",
            QT_QPA_PLATFORM='offscreen',
            PYTHONIOENCODING='utf-8',
            KMP_DUPLICATE_LIB_OK='TRUE',
        )
        res = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=env,
            timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self.assertEqual(res.returncode, 0, res.stdout + '\n' + res.stderr)
        self.assertIn('LAZY_STARTUP_OK', res.stdout)

    def test_tpdf_table_stays_lazy_for_float32_and_initializes_on_int24(self):
        samples = np.zeros((64, 2), dtype=np.float32)
        saved = audio_stream_engine._TPDF_TABLE
        try:
            audio_stream_engine._TPDF_TABLE = None
            pcm_f32 = audio_stream_engine.quantize_pcm(samples, 'float32')
            self.assertEqual(len(pcm_f32), 64 * 2 * 4)
            self.assertIsNone(audio_stream_engine._TPDF_TABLE)

            pcm_i24 = audio_stream_engine.quantize_pcm(samples, 'int24')
            self.assertEqual(len(pcm_i24), 64 * 2 * 3)
            self.assertIsNotNone(audio_stream_engine._TPDF_TABLE)
        finally:
            audio_stream_engine._TPDF_TABLE = saved

    def test_window_timers_do_not_leak_and_subtitle_clock_sleeps_when_empty_or_off(self):
        with isolated_window() as (window, _root):
            self.assertIs(window.resize_timer.parent(), window)
            self.assertIs(window.mouse_hide_timer.parent(), window)
            self.assertIs(window.mini_player.click_timer.parent(), window.mini_player)

            # Repeated resize events must reuse the single parented resize_timer
            window.grid_widgets = [object()]
            timers_before = len(window.findChildren(QTimer))
            for _ in range(5):
                window.resize(1080, 720)
                window.resize(1100, 750)
            timers_after = len(window.findChildren(QTimer))
            self.assertEqual(timers_before, timers_after)

            # Subtitle clock (25ms / 40Hz) must not tick when subtitles are empty or OFF
            window.sub_layer.subtitles = []
            window._sync_subtitle_clock_state(QMediaPlayer.PlaybackState.PlayingState)
            self.assertFalse(window._sub_clock_timer.isActive())

            window.sub_layer.load_subtitles([{'start': 0, 'end': 1000, 'orig': 'Hello', 'en': 'Hello', 'vi': 'Xin chào'}])
            window.sub_layer.set_mode(SubtitleMode.OFF)
            window._sync_subtitle_clock_state(QMediaPlayer.PlaybackState.PlayingState)
            self.assertFalse(window._sub_clock_timer.isActive())

            window.sub_layer.set_mode(SubtitleMode.EN_VI)
            window._sync_subtitle_clock_state(QMediaPlayer.PlaybackState.PlayingState)
            self.assertTrue(window._sub_clock_timer.isActive())
            window._sub_clock_timer.stop()

    def test_translation_worker_releases_nllb_ram_even_when_pipeline_raises(self):
        worker = TranslationWorker(
            [{'start': 0.0, 'end': 1.0, 'text': 'Hello world'}],
            {'detected_lang': 'en', 'use_online_translation': False},
        )
        cleared = []
        errors = []
        worker.error_signal.connect(errors.append)
        with patch('translate.pipeline.translate_pipeline', side_effect=RuntimeError('OOM simulation')), \
             patch('translate.pipeline.clear_translator', side_effect=lambda: cleared.append(True)):
            worker.run()
        self.assertEqual(len(errors), 1)
        self.assertEqual(cleared, [True])

    def test_portable_packaging_excludes_ffplay_and_prunes_duplicate_ytdlp_and_pycache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for rel in (
                'icon/app_icon.ico',
                'bin/ffmpeg.exe',
                'bin/ffprobe.exe',
                'bin/ffplay.exe',
                'app/download_core/yt-dlp.exe',
            ):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'fixture')

            plan = build_app.build_plan(root, stamp='slim')
            self.assertIn('--exclude-module=PySide6.QtWebEngineCore', plan['params'])
            self.assertIn('--exclude-module=torch', plan['params'])
            for stdlib_mod in ('timeit', 'filecmp', 'pipes', 'trace', 'unittest', 'wave'):
                self.assertIn(f'--hidden-import={stdlib_mod}', plan['params'])

            out = Path(plan['output'])
            (out / '_internal/app/download_core/__pycache__').mkdir(parents=True, exist_ok=True)
            (out / '_internal/app/test').mkdir(parents=True, exist_ok=True)
            (out / '_internal/app/download_core/yt-dlp.exe').write_bytes(b'duplicate-22mb')
            (out / '_internal/app/download_core/__pycache__/mod.cpython-311.pyc').write_bytes(b'pyc')
            (out / '_internal/app/test/test_sub.py').write_bytes(b'test')
            (out / 'BoTube.exe').write_bytes(b'exe')

            build_app.copy_portable_resources(plan)

            self.assertTrue((out / 'bin/ffmpeg.exe').is_file())
            self.assertTrue((out / 'bin/ffprobe.exe').is_file())
            self.assertFalse((out / 'bin/ffplay.exe').exists())
            self.assertTrue((out / 'yt-dlp.exe').is_file())
            self.assertFalse((out / '_internal/app/download_core/yt-dlp.exe').exists())
            self.assertFalse((out / '_internal/app/download_core/__pycache__').exists())
            self.assertFalse((out / '_internal/app/test').exists())

    def test_ai_resource_pip_command_drops_unused_vision_audio_and_supports_lean_cpu_mode(self):
        from download_core.download_source_app import build_ai_pip_command

        gpu_cmd = build_ai_pip_command('python', 'libs', 'gpu')
        cpu_cmd = build_ai_pip_command('python', 'libs', 'cpu')

        for cmd in (gpu_cmd, cpu_cmd):
            joined = ' '.join(cmd)
            self.assertIn('--no-cache-dir', cmd)
            self.assertIn('torch==2.4.0', cmd)
            self.assertIn('faster-whisper==1.0.2', cmd)
            self.assertIn('soundfile>=0.12.1', cmd)
            self.assertNotIn('torchvision', joined)
            self.assertNotIn('torchaudio', joined)

        self.assertIn('https://download.pytorch.org/whl/cu121', gpu_cmd)
        self.assertIn('https://download.pytorch.org/whl/cpu', cpu_cmd)


if __name__ == '__main__':
    unittest.main()
