"""Focused contracts for additive video + lyric burn-in export."""
from copy import deepcopy
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage

from subtitle.mode import SubtitleMode
from tools.ui_preview import APPLICATION
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.video_subtitle_export import (
    ExportCue, ExportPreviewWidget, ExportSettings, ExportSnapshot, SubtitleBandRenderer, audio_arguments,
    parse_probe, resolve_canvas, snapshot_from_window, source_transform, source_video_filter,
    subtitle_composition_filter,
)
from tests.video_export_contracts import before_video_export_changes


class ExportPolicyTests(unittest.TestCase):
    def test_exact_ui_adapter_restores_pre_export_dialog(self):
        relative = 'app/ui/subs_ui/lyric_settings_dialog.py'
        restored = before_video_export_changes(relative, raw=True)
        original = (Path(__file__).resolve().parents[1] / 'docs/video-subtitle-export/original' / relative).read_bytes()
        self.assertEqual(restored, original)

    def test_probe_rotation_fps_and_audio_policy(self):
        info = parse_probe({'streams': [
            {'codec_type': 'video', 'width': 600, 'height': 600,
             'disposition': {'attached_pic': 1}},
            {'codec_type': 'video', 'width': 1920, 'height': 1080, 'avg_frame_rate': '30000/1001',
             'side_data_list': [{'rotation': -90}]},
            {'codec_type': 'audio', 'codec_name': 'opus'},
        ], 'format': {'duration': '12.5'}})
        self.assertEqual((info['width'], info['height']), (1080, 1920))
        self.assertAlmostEqual(info['fps'], 30000/1001, places=4)
        self.assertEqual(info['duration'], 12.5)
        self.assertEqual(audio_arguments('x.mkv', info['audio_codecs']), (['-c:a', 'copy'], True))
        self.assertEqual(audio_arguments('x.mp4', info['audio_codecs']),
                         (['-c:a', 'aac', '-b:a', '320k'], False))
        self.assertEqual(audio_arguments('x.mp4', ('aac',)), (['-c:a', 'copy'], True))

    def test_probe_duration_fallbacks_do_not_depend_on_subtitle_tail(self):
        base = {'codec_type': 'video', 'width': 1280, 'height': 720,
                'avg_frame_rate': '25/1'}
        by_time_base = parse_probe({'streams': [{**base, 'duration_ts': 2500,
                                                 'time_base': '1/1000'}]})
        self.assertEqual(by_time_base['duration'], 2.5)
        by_frames = parse_probe({'streams': [{**base, 'nb_frames': '75'}]})
        self.assertEqual(by_frames['duration'], 3.0)

    def test_canvas_presets_and_fit_filters_are_deterministic(self):
        probe = {'width': 1080, 'height': 1080}
        self.assertEqual(resolve_canvas(probe, ExportSettings()), (1080, 1080))
        self.assertEqual(resolve_canvas(
            probe, ExportSettings(aspect='16:9', resolution='1080')), (1920, 1080))
        self.assertEqual(resolve_canvas(
            probe, ExportSettings(aspect='9:16', resolution='1080')), (1080, 1920))
        self.assertEqual(resolve_canvas(
            probe, ExportSettings(aspect='1:1', resolution='720')), (720, 720))
        self.assertEqual(resolve_canvas(
            probe, ExportSettings(resolution='custom', custom_width=1333, custom_height=777)),
            (1334, 778))
        contain = source_video_filter(1920, 1080, ExportSettings(fit_mode='contain'))
        cover = source_video_filter(1920, 1080, ExportSettings(fit_mode='cover'))
        stretch = source_video_filter(1920, 1080, ExportSettings(fit_mode='stretch'))
        self.assertIn('force_original_aspect_ratio=decrease', contain)
        self.assertIn('flags=lanczos+accurate_rnd+full_chroma_int', contain)
        self.assertIn('pad=1920:1080', contain)
        self.assertIn('force_original_aspect_ratio=increase', cover)
        self.assertIn('flags=lanczos+accurate_rnd+full_chroma_int', cover)
        self.assertIn('crop=1920:1080', cover)
        self.assertEqual(
            stretch,
            'scale=1920:1080:flags=lanczos+accurate_rnd+full_chroma_int',
        )
        graph = subtitle_composition_filter(contain, 812)
        self.assertIn('format=yuv444p[base444]', graph)
        self.assertIn('overlay=0:812:format=yuv444:alpha=straight', graph)
        self.assertIn('format=yuv420p,setsar=1[v]', graph)

    def test_live_screen_geometry_maps_to_export_source_coordinates(self):
        snap = self.snapshot(fade=False)
        snap = ExportSnapshot(
            source=snap.source, cues=snap.cues, style=snap.style, effects=snap.effects,
            fade_enabled=False, anchor_width=1200, anchor_height=700,
            user_moved=False, rel_x_offset=0, bottom_offset=40,
            anchor_x=0, anchor_y=0,
            video_x=100, video_y=50, video_width=900, video_height=600,
        )
        probe = {'width': 1080, 'height': 1080}
        renderer = SubtitleBandRenderer(
            snap, 1080, 1080, ExportSettings(safe_subtitles=False), probe=probe
        )
        # The 1080-square source is displayed as a 600-square image centered
        # inside the 900x600 live QVideoWidget, so export/live scale is 1.8.
        self.assertAlmostEqual(renderer.scale, 1.8, places=6)
        self.assertAlmostEqual(renderer.center_x, 630.0, places=6)
        self.assertAlmostEqual(renderer.bottom_y, 1098.0, places=6)

    def test_default_clip_guard_does_not_add_an_editor_safe_margin(self):
        snap = self.snapshot(fade=False)
        snap = ExportSnapshot(
            source=snap.source, cues=snap.cues, style=snap.style, effects=snap.effects,
            fade_enabled=False, anchor_width=600, anchor_height=600,
            user_moved=False, rel_x_offset=0, bottom_offset=40,
            anchor_x=100, anchor_y=50,
            video_x=100, video_y=50, video_width=600, video_height=600,
        )
        renderer = SubtitleBandRenderer(
            snap, 1080, 1080, ExportSettings(), probe={'width': 1080, 'height': 1080}
        )
        self.assertEqual((renderer.safe_x, renderer.safe_y), (0, 0))
        self.assertEqual(renderer.overlay_y + renderer.band_height, round(renderer.bottom_y))

    def test_export_only_subtitle_overrides_are_opt_in_and_do_not_mutate_snapshot(self):
        snap = self.snapshot(fade=False)
        style_before = dict(snap.style)
        base = SubtitleBandRenderer(
            snap, 1000, 500, ExportSettings(safe_subtitles=False)
        )
        custom = SubtitleBandRenderer(
            snap, 1000, 500,
            ExportSettings(
                safe_subtitles=False,
                override_font_size=True, font_size=17,
                subtitle_x_percent=10, subtitle_y_percent=8,
                override_bg_opacity=True, bg_opacity_percent=25,
            ),
        )
        self.assertEqual(base.font.pixelSize(), 24)
        self.assertEqual(custom.font.pixelSize(), 17)
        self.assertAlmostEqual(custom.style['bg_opacity'], .25, places=6)
        self.assertAlmostEqual(custom.center_x, base.center_x+100, places=6)
        self.assertAlmostEqual(custom.bottom_y, base.bottom_y-40, places=6)
        self.assertEqual(snap.style, style_before)

    def test_preview_overlay_renders_at_backing_store_dpr(self):
        snap = self.snapshot(fade=False)
        preview = ExportPreviewWidget(snapshot=snap)
        self.addCleanup(preview.deleteLater)
        source = QImage(1920, 1080, QImage.Format.Format_RGB32)
        source.fill(Qt.GlobalColor.black)
        preview.set_source_image(source)

        canvas = QRect(0, 0, 640, 360)
        preview._rebuild_overlay(canvas, 2.0)

        self.assertFalse(preview._overlay_image.isNull())
        self.assertEqual(preview._overlay_image.width(), 1280)
        self.assertEqual(preview._overlay_image.devicePixelRatio(), 2.0)
        self.assertGreaterEqual(preview._overlay_y, 0.0)

    def test_safe_area_is_based_on_visible_video_rect_not_letterbox_canvas(self):
        snap = self.snapshot(fade=False)
        probe = {'width': 1080, 'height': 1080}
        settings = ExportSettings(aspect='9:16', resolution='720', fit_mode='contain')
        transform = source_transform(720, 1280, 1080, 1080, settings)
        self.assertEqual(transform['x'], 0.0)
        self.assertEqual(transform['y'], 280.0)
        renderer = SubtitleBandRenderer(snap, 720, 1280, settings, probe=probe)
        self.assertGreaterEqual(renderer.safe_top, 280)
        self.assertLessEqual(renderer.safe_bottom, 1000)

    def snapshot(self, effects=None, fade=True):
        return ExportSnapshot(
            source='fixture.mp4', cues=(ExportCue(0, 1000, 2500, '星空へ fly\nDòng hai'),),
            style={'font_size': 24, 'font_color': '#FFFF00', 'bg_color': '#000000',
                   'bg_opacity': .5, 'outline_enabled': True, 'outline_width': 4,
                   'outline_color': '#000000', 'shadow_enabled': True, 'shadow_alpha': 160},
            effects=effects or {'enabled': False}, fade_enabled=fade,
            anchor_width=900, anchor_height=600, user_moved=False,
            rel_x_offset=0, bottom_offset=40)

    def test_renderer_is_timestamp_deterministic_and_bounded(self):
        renderer = SubtitleBandRenderer(self.snapshot({'enabled': True, 'entrance': 'kinetic_drop',
            'color': 'ocean', 'trail': 'sparkles', 'intensity': 'normal'}), 1280, 720)
        before = renderer.frame(1100)
        again = renderer.frame(1100)
        later = renderer.frame(1800)
        self.assertEqual(before, again)
        self.assertNotEqual(before, later)
        self.assertEqual(len(before), 1280*renderer.band_height*4)
        self.assertGreater(renderer.band_height, 0)
        self.assertLessEqual(renderer.band_height, 720)

    def test_fade_and_gap_do_not_extend_cue_forever(self):
        renderer = SubtitleBandRenderer(self.snapshot(fade=True), 640, 360)
        blank = bytes(len(renderer.frame(0)))
        self.assertEqual(renderer.frame(0), blank)
        self.assertNotEqual(renderer.frame(1050), blank)
        self.assertNotEqual(renderer.frame(2550), blank)
        self.assertEqual(renderer.frame(2800), blank)

    def test_erase_sweep_stays_finished_during_export_fade_out(self):
        renderer = SubtitleBandRenderer(self.snapshot({
            'enabled': True,
            'entrance': 'none',
            'soft_fade': False,
            'trail': 'shuriken',
            'erase_passed': True,
        }, fade=True), 640, 360)

        renderer.frame(2500)
        self.assertEqual(renderer.effects.scan_progress, 1.0)
        self.assertIsNotNone(renderer.effects.cue)

        # The cue is no longer active, but its completed erase mask must stay
        # attached while opacity fades so the old line cannot flash back.
        renderer.frame(2550)
        self.assertEqual(renderer.effects.scan_progress, 1.0)
        self.assertIsNotNone(renderer.effects.cue)
        self.assertEqual(renderer.effects.cue[0], 0)

        renderer.frame(2800)
        self.assertEqual(renderer.frame(2800), bytes(len(renderer.frame(2800))))

    def test_non_erasing_export_effect_keeps_existing_fade_behavior(self):
        renderer = SubtitleBandRenderer(self.snapshot({
            'enabled': True,
            'entrance': 'none',
            'soft_fade': False,
            'trail': 'shuriken',
            'erase_passed': False,
        }, fade=True), 640, 360)
        renderer.frame(2550)
        self.assertIsNone(renderer.effects.cue)
        self.assertEqual(renderer.effects.scan_progress, 1.0)

    def test_effect_off_keeps_text_pixels_and_source_data_immutable(self):
        snap = self.snapshot({'enabled': False}, fade=False)
        cue_before = snap.cues
        style_before = dict(snap.style)
        renderer = SubtitleBandRenderer(snap, 640, 360)
        frame = renderer.frame(1500)
        cached = renderer.frame(1600)
        self.assertNotEqual(frame, bytes(len(frame)))
        self.assertIs(frame, cached)
        self.assertEqual(snap.cues, cue_before)
        self.assertEqual(snap.style, style_before)

    def test_live_snapshot_is_read_only_and_uses_current_mode_and_position(self):
        layer = SubtitleLayer(SubtitleMode.JP)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.load_subtitles([
            {'start': 100, 'end': 900, 'orig': '原文', 'en': 'English', 'vi': 'Tiếng Việt'},
            {'start': 1000, 'end': 1600, 'orig': '二番'},
        ])
        layer._anchor_rect_global = QRect(10, 20, 900, 600)
        layer._user_moved = True
        layer._rel_x_offset = 37
        layer._rel_y_from_bottom = 88
        before = deepcopy(layer.subtitles)
        video = SimpleNamespace(
            width=lambda: 900,
            height=lambda: 600,
            mapToGlobal=lambda _point: QPoint(100, 200),
            aspectRatioMode=lambda: Qt.AspectRatioMode.KeepAspectRatio,
        )
        window = SimpleNamespace(
            sub_layer=layer,
            app_controller=SimpleNamespace(current_media_item=SimpleNamespace(path='D:/fixture.mp4')),
            video_display=video,
        )
        snap = snapshot_from_window(window)
        self.assertEqual([cue.text for cue in snap.cues], ['原文', '二番'])
        self.assertEqual((snap.anchor_width, snap.anchor_height), (900, 600))
        self.assertEqual((snap.rel_x_offset, snap.bottom_offset), (37, 88))
        self.assertEqual((snap.video_x, snap.video_y, snap.video_width, snap.video_height),
                         (100, 200, 900, 600))
        self.assertEqual(snap.video_aspect_mode, 'contain')
        self.assertGreater(snap.cues[0].box_width, 0)
        self.assertGreater(snap.cues[0].box_height, 0)
        self.assertGreater(snap.cues[0].contents_width, 0)
        self.assertGreater(snap.cues[0].contents_height, 0)
        self.assertEqual(snap.style['padding_left'], layer.contentsRect().x()-layer.rect().x())
        self.assertEqual(snap.style['padding_top'], layer.contentsRect().y()-layer.rect().y())
        self.assertEqual(layer.subtitles, before)

    def test_hidden_mode_cue_still_controls_live_fade_gap(self):
        layer = SubtitleLayer(SubtitleMode.VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.load_subtitles([
            {'start': 100, 'end': 900, 'orig': 'A', 'vi': 'Một'},
            {'start': 1200, 'end': 1900, 'orig': 'B', 'vi': ''},
            {'start': 1950, 'end': 2600, 'orig': 'C', 'vi': 'Ba'},
        ])
        layer._anchor_rect_global = QRect(0, 0, 900, 600)
        window = SimpleNamespace(
            sub_layer=layer,
            app_controller=SimpleNamespace(current_media_item=SimpleNamespace(path='D:/fixture.mp4')),
            video_display=SimpleNamespace(width=lambda: 900, height=lambda: 600),
        )
        snap = snapshot_from_window(window)
        self.assertEqual([cue.text for cue in snap.cues], ['Một', 'Ba'])
        self.assertEqual(snap.cues[1].previous_source_end, 1900)
        renderer = SubtitleBandRenderer(snap, 900, 600)
        cue, opacity, active = renderer._cue_at(1950)
        self.assertTrue(active)
        self.assertEqual(cue.text, 'Ba')
        self.assertEqual(opacity, 1.0)

    def test_dragged_vertical_offset_is_not_clamped(self):
        snap = self.snapshot(fade=False)
        snap = ExportSnapshot(
            source=snap.source, cues=snap.cues, style=snap.style, effects=snap.effects,
            fade_enabled=snap.fade_enabled, anchor_width=snap.anchor_width,
            anchor_height=snap.anchor_height, user_moved=True, rel_x_offset=0,
            bottom_offset=-24,
        )
        renderer = SubtitleBandRenderer(
            snap, 640, 360, ExportSettings(safe_subtitles=False)
        )
        self.assertGreater(renderer.overlay_y, 360-renderer.band_height)

    def test_safe_area_keeps_dragged_and_long_subtitle_inside_canvas(self):
        snap = self.snapshot(fade=False)
        long_text = 'Một câu lyric rất dài ' * 18
        snap = ExportSnapshot(
            source=snap.source,
            cues=(ExportCue(0, 1000, 2500, long_text),),
            style=snap.style, effects=snap.effects, fade_enabled=False,
            anchor_width=900, anchor_height=600, user_moved=True,
            rel_x_offset=-5000, bottom_offset=-5000,
        )
        settings = ExportSettings(
            safe_subtitles=True, safe_horizontal_percent=5, safe_vertical_percent=4
        )
        renderer = SubtitleBandRenderer(snap, 1920, 1080, settings)
        display = renderer._display_text(long_text)
        size, _contents = renderer._geometry(display)
        target_width = int(math.ceil(size.width()*renderer.scale))
        self.assertGreater(display.count('\n'), 0)
        self.assertLessEqual(target_width, 1920-2*renderer.safe_x)
        self.assertGreaterEqual(renderer.overlay_y, renderer.safe_y)
        self.assertLessEqual(
            renderer.overlay_y+renderer.band_height, 1080-renderer.safe_y
        )


if __name__ == '__main__':
    unittest.main()
