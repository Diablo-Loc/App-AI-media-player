"""Tests for NVIDIA GPU (h264_nvenc) accelerated video subtitle export & CPU fallback."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.ui_preview import APPLICATION  # noqa: F401 - ensures QApplication exists
from core.audio_effects import find_tool
from ui.video_subtitle_export import (
    ExportCue,
    ExportSettings,
    ExportSnapshot,
    SubtitleBandRenderer,
    VideoExportSettingsDialog,
    VideoSubtitleExportWorker,
    build_export_ffmpeg_command,
    can_use_nvenc_for_canvas,
    probe_nvenc_support,
    resolve_video_encoder,
    subtitle_composition_filter,
    source_video_filter,
)


def _sample_snapshot(source_path: str = 'fixture.mp4', animated: bool = True) -> ExportSnapshot:
    effects = (
        {
            'enabled': True,
            'preset': 'karaoke_pro',
            'entrance': 'soft_rise',
            'color': 'fire_gold',
            'trail': 'karaoke_pro',
            'intensity': 'strong',
            'erase_passed': False,
        }
        if animated
        else {'enabled': False}
    )
    cue = ExportCue(
        index=0,
        start=100,
        end=900,
        text='yo ni kakeru\n夜に駆ける\nChạy vào màn đêm',
        sweep_row_groups=(0, 1, 2),
        phonetic_top_group=0,
        word_curves=(
            (0, ((100.0, 350.0, 0.0, 0.45), (350.0, 880.0, 0.45, 1.0))),
            (1, ((100.0, 350.0, 0.0, 0.45), (350.0, 880.0, 0.45, 1.0))),
            (2, ((100.0, 880.0, 0.0, 1.0),)),
        ),
    )
    return ExportSnapshot(
        source=source_path,
        cues=(cue,),
        style={
            'font_size': 32,
            'font_color': '#F8FAFC',
            'bg_color': '#000000',
            'bg_opacity': 0.5,
            'outline_enabled': True,
            'outline_width': 4,
            'outline_color': '#000000',
            'shadow_enabled': True,
            'shadow_alpha': 170,
            'bilingual_hierarchy': True,
        },
        effects=effects,
        fade_enabled=True,
        anchor_width=1280,
        anchor_height=720,
        user_moved=False,
        rel_x_offset=0,
        bottom_offset=40,
    )


def _create_synthetic_mp4(path: Path, duration_sec: float = 1.0, size: str = '1280x720', fps: int = 30) -> None:
    ffmpeg = find_tool('ffmpeg')
    subprocess.run(
        [
            ffmpeg, '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={fps}:duration={duration_sec}',
            '-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=44100:duration={duration_sec}',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k',
            str(path),
        ],
        check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


class NvencVideoExportTests(unittest.TestCase):
    def test_canvas_nvenc_dimension_limits(self):
        self.assertTrue(can_use_nvenc_for_canvas(256, 256))
        self.assertTrue(can_use_nvenc_for_canvas(1280, 720))
        self.assertTrue(can_use_nvenc_for_canvas(1920, 1080))
        self.assertTrue(can_use_nvenc_for_canvas(1080, 1920))
        self.assertTrue(can_use_nvenc_for_canvas(3840, 2160))
        self.assertTrue(can_use_nvenc_for_canvas(2160, 3840))
        self.assertTrue(can_use_nvenc_for_canvas(4096, 4096))

        # Below NVENC hardware minimum (256) or above H.264 NVENC max (4096)
        self.assertFalse(can_use_nvenc_for_canvas(128, 128))
        self.assertFalse(can_use_nvenc_for_canvas(254, 720))
        self.assertFalse(can_use_nvenc_for_canvas(4098, 2160))
        self.assertFalse(can_use_nvenc_for_canvas(7680, 4320))

    def test_resolve_video_encoder_honors_mode_gpu_and_canvas_bounds(self):
        self.assertEqual(
            resolve_video_encoder(ExportSettings(encoder='auto'), 1920, 1080, nvenc_available=True),
            'h264_nvenc',
        )
        self.assertEqual(
            resolve_video_encoder(ExportSettings(encoder='auto'), 1920, 1080, nvenc_available=False),
            'libx264',
        )
        self.assertEqual(
            resolve_video_encoder(ExportSettings(encoder='cpu'), 1920, 1080, nvenc_available=True),
            'libx264',
        )
        self.assertEqual(
            resolve_video_encoder(ExportSettings(encoder='nvenc'), 1920, 1080, nvenc_available=True),
            'h264_nvenc',
        )
        # Missing GPU or out-of-range 8K/tiny custom dimensions safely fall back to libx264
        self.assertEqual(
            resolve_video_encoder(ExportSettings(encoder='nvenc'), 1920, 1080, nvenc_available=False),
            'libx264',
        )
        self.assertEqual(
            resolve_video_encoder(ExportSettings(encoder='nvenc'), 7680, 4320, nvenc_available=True),
            'libx264',
        )
        self.assertEqual(
            resolve_video_encoder(ExportSettings(encoder='auto'), 160, 160, nvenc_available=True),
            'libx264',
        )

    def test_ffmpeg_command_builder_preserves_yuv444_filter_and_tunes_nvenc_vs_cpu(self):
        base = source_video_filter(1920, 1080, ExportSettings())
        graph = subtitle_composition_filter(base, 812)
        nvenc_cmd = build_export_ffmpeg_command(
            ffmpeg='ffmpeg',
            snapshot_source='input.mp4',
            canvas_width=1920,
            band_height=268,
            fps=60.0,
            filter_graph=graph,
            encoder_name='h264_nvenc',
            quality='high',
            threads=4,
            audio_args=['-c:a', 'copy'],
            output_path=Path('out.mp4'),
            partial_path=Path('out.botube-exporting-1.mp4'),
        )
        self.assertNotIn('-hwaccel', nvenc_cmd)
        self.assertIn('h264_nvenc', nvenc_cmd)
        self.assertEqual(nvenc_cmd[nvenc_cmd.index('-preset') + 1], 'p4')
        self.assertIn('-cq', nvenc_cmd)
        self.assertEqual(nvenc_cmd[nvenc_cmd.index('-cq') + 1], '21')
        self.assertIn('-spatial-aq', nvenc_cmd)
        self.assertIn('-temporal-aq', nvenc_cmd)
        self.assertNotIn('-crf', nvenc_cmd)
        self.assertIn('format=yuv444p[base444]', nvenc_cmd[nvenc_cmd.index('-filter_complex') + 1])
        self.assertIn('+faststart', nvenc_cmd)

        cpu_cmd = build_export_ffmpeg_command(
            ffmpeg='ffmpeg',
            snapshot_source='input.mp4',
            canvas_width=1920,
            band_height=268,
            fps=60.0,
            filter_graph=graph,
            encoder_name='libx264',
            quality='balanced',
            threads=6,
            audio_args=['-c:a', 'copy'],
            output_path=Path('out.mkv'),
            partial_path=Path('out.botube-exporting-1.mkv'),
        )
        self.assertNotIn('-hwaccel', cpu_cmd)
        self.assertIn('libx264', cpu_cmd)
        self.assertIn('-crf', cpu_cmd)
        self.assertEqual(cpu_cmd[cpu_cmd.index('-crf') + 1], '20')
        self.assertIn('-threads', cpu_cmd)
        self.assertEqual(cpu_cmd[cpu_cmd.index('-threads') + 1], '6')
        self.assertNotIn('+faststart', cpu_cmd)

    def test_frame_buffer_zero_copy_matches_frame_bytes_exactly(self):
        anim_renderer = SubtitleBandRenderer(_sample_snapshot(animated=True), 1280, 720)
        for pts in (0.0, 220.0, 520.0, 960.0, 1250.0):
            view_bytes = bytes(anim_renderer.frame_buffer(pts))
            exact_bytes = anim_renderer.frame(pts)
            self.assertEqual(view_bytes, exact_bytes)
            self.assertEqual(len(view_bytes), 1280 * anim_renderer.band_height * 4)

        # Animated active cue returns a non-bytes buffer view (zero-copy QImage constBits)
        active_buf = anim_renderer.frame_buffer(450.0)
        self.assertFalse(isinstance(active_buf, bytes))

        # Static cue caches and reuses exact bytes object
        static_renderer = SubtitleBandRenderer(_sample_snapshot(animated=False), 640, 360)
        first = static_renderer.frame_buffer(450.0)
        second = static_renderer.frame_buffer(550.0)
        self.assertIsInstance(first, bytes)
        self.assertIs(first, second)

    def test_dialog_exposes_encoder_selector_and_updates_summary(self):
        snap = _sample_snapshot(animated=True)
        with patch('ui.video_subtitle_export.probe_nvenc_support', return_value=True):
            dlg = VideoExportSettingsDialog(snapshot=snap)
            self.addCleanup(dlg.deleteLater)
            self.assertEqual(dlg.settings().encoder, 'auto')
            self.assertIn('GPU NVENC ⚡', dlg.output_summary.text())

            dlg.encoder.setCurrentIndex(dlg.encoder.findData('cpu'))
            self.assertEqual(dlg.settings().encoder, 'cpu')
            self.assertIn('CPU x264', dlg.output_summary.text())

            dlg._reset_recommended()
            self.assertEqual(dlg.settings().encoder, 'auto')
            self.assertIn('GPU NVENC ⚡', dlg.output_summary.text())

    def test_worker_automatically_falls_back_to_libx264_when_nvenc_runtime_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            src = tmp / 'src.mp4'
            out = tmp / 'out_fallback.mp4'
            _create_synthetic_mp4(src, duration_sec=0.6, size='640x360', fps=24)

            snap = _sample_snapshot(str(src), animated=True)
            worker = VideoSubtitleExportWorker(snap, str(out), ExportSettings(encoder='nvenc'))
            attempts: list[str] = []
            progress_messages: list[str] = []
            outcomes: list[tuple] = []
            errors: list[str] = []

            real_attempt = worker._encode_attempt

            def flaky_nvenc_attempt(**kwargs):
                attempts.append(kwargs['encoder_name'])
                if kwargs['encoder_name'] == 'h264_nvenc':
                    # Simulate concurrent NVENC session limit / driver failure leaving junk partial
                    Path(kwargs['partial']).write_bytes(b'')
                    Path(kwargs['log_path']).write_text('InitializeEncoder failed: out of memory', encoding='utf-8')
                    return 1
                return real_attempt(**kwargs)

            worker.progress.connect(lambda _pct, msg: progress_messages.append(msg))
            worker.succeeded.connect(lambda p, copied, has_a: outcomes.append((p, copied, has_a)))
            worker.failed.connect(errors.append)

            with patch('ui.video_subtitle_export.resolve_video_encoder', return_value='h264_nvenc'), \
                 patch.object(worker, '_encode_attempt', side_effect=flaky_nvenc_attempt):
                worker.run()

            self.assertEqual(errors, [])
            self.assertEqual(attempts, ['h264_nvenc', 'libx264'])
            self.assertTrue(any('tự động chuyển sang CPU' in m for m in progress_messages))
            self.assertEqual(len(outcomes), 1)
            self.assertTrue(out.is_file() and out.stat().st_size > 1024)
            # Zero leftover temp partial files
            self.assertEqual(list(tmp.glob('*.botube-exporting-*')), [])

    def test_real_end_to_end_nvenc_export_produces_valid_h264_mp4(self):
        if not probe_nvenc_support(use_cache=False):
            self.skipTest('NVIDIA h264_nvenc hardware not available on this host')
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            src = tmp / 'src_720p.mp4'
            out = tmp / 'exported_nvenc.mp4'
            _create_synthetic_mp4(src, duration_sec=1.0, size='1280x720', fps=30)

            snap = _sample_snapshot(str(src), animated=True)
            worker = VideoSubtitleExportWorker(
                snap, str(out), ExportSettings(encoder='nvenc', quality='high')
            )
            progress_messages: list[str] = []
            outcomes: list[tuple] = []
            errors: list[str] = []
            worker.progress.connect(lambda _pct, msg: progress_messages.append(msg))
            worker.succeeded.connect(lambda p, copied, has_a: outcomes.append((p, copied, has_a)))
            worker.failed.connect(errors.append)
            worker.run()

            self.assertEqual(errors, [])
            self.assertEqual(len(outcomes), 1)
            self.assertEqual(outcomes[0], (str(out), True, True))
            self.assertTrue(any('GPU NVENC ⚡' in m for m in progress_messages))
            self.assertFalse(any('tự động chuyển sang CPU' in m for m in progress_messages))
            self.assertTrue(out.is_file() and out.stat().st_size > 2048)

            ffprobe = find_tool('ffprobe')
            probe_raw = subprocess.check_output(
                [ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(out)],
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            streams = json.loads(probe_raw.decode('utf-8'))['streams']
            video_streams = [s for s in streams if s.get('codec_type') == 'video']
            audio_streams = [s for s in streams if s.get('codec_type') == 'audio']
            self.assertEqual(len(video_streams), 1)
            self.assertEqual(len(audio_streams), 1)
            self.assertEqual(video_streams[0]['codec_name'], 'h264')
            self.assertEqual(video_streams[0]['pix_fmt'], 'yuv420p')
            self.assertEqual((video_streams[0]['width'], video_streams[0]['height']), (1280, 720))


if __name__ == '__main__':
    unittest.main()
