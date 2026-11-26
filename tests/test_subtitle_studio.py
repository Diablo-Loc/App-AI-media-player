"""Studio subtitle performance, pre-warming, uniform typography, zero-flicker fade & MV editor effects tests."""
import time
import unittest
from unittest.mock import patch

import PySide6.QtMultimedia  # keep resident across ui_preview module resets
from PySide6.QtCore import Qt, QPoint, QRect, QAbstractAnimation
from PySide6.QtGui import QImage, QPainter
from PySide6.QtMultimedia import QMediaPlayer

from tools.ui_preview import APPLICATION, isolated_window, pump
from subtitle.mode import SubtitleMode
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subs_ui.sub_panel import SettingsPanel
from ui.subtitle_effects import COLORS, ENTRANCES, PRESETS, normalize_options
from ui.subtitle_studio import (
    MAX_CACHE_ENTRIES,
    MAX_SPRITE_PIXELS,
    STUDIO_PROFILES,
    STUDIO_PROFILE_ORDER,
)
from ui.video_subtitle_export import (
    ExportSettings,
    SubtitleBandRenderer,
    snapshot_from_window,
)
from tests.test_subtitle_particles import MediaClock


def _snap(widget) -> QImage:
    img = QImage(max(1, widget.width()), max(1, widget.height()), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    widget.render(p, QPoint(0, 0))
    p.end()
    return img


class SubtitleStudioEngineTests(unittest.TestCase):
    def _cues(self):
        return [
            {
                'start': 0,
                'end': 3000,
                'orig': '夜に駆ける',
                'en': 'Racing into the starlit night',
                'vi': 'Lao vào màn đêm rực ánh sao',
            },
            {
                'start': 3100,
                'end': 6200,
                'orig': '二人だけの空',
                'en': 'Where a sky just for two unfolds',
                'vi': 'Nơi bầu trời riêng đôi ta mở rộng',
            },
            {
                'start': 6300,
                'end': 9500,
                'orig': '消えない光',
                'en': 'An unfading beam across the dark',
                'vi': 'Tia sáng dịu dàng không bao giờ tắt',
            },
        ]

    def test_uniform_typography_keeps_equal_font_size_across_all_lines(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(False)
        layer.apply_style(font_size=28, subtitle_hierarchy=True)
        layer.load_subtitles(self._cues())
        layer.update_position(100)
        _snap(layer)

        plan = layer._cached_plan
        self.assertIsNotNone(plan)
        self.assertFalse(plan.hierarchical)
        self.assertEqual(len(plan.lines), 2)
        self.assertFalse(plan.lines[0].is_secondary)
        self.assertFalse(plan.lines[1].is_secondary)
        self.assertEqual(plan.lines[0].font.pixelSize(), plan.lines[1].font.pixelSize())

    def test_cue_end_fade_holds_settled_state_without_flicker(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(True)
        layer.apply_style(font_size=28, color='#FFFFFF', outline_width=3, shadow_alpha=195)
        layer._subtitle_effects.configure(STUDIO_PROFILES['capcut_karaoke']['subtitle_effects'])
        layer.load_subtitles(self._cues())

        layer.update_position(1500)
        layer.fade_anim.stop()
        layer.set_opacity(1.0)
        layer._subtitle_effects.progress = 1.0
        layer._subtitle_effects.scan_progress = 0.5

        # Move past cue end -> enters smooth fade-out without wiping row groups or sprite
        layer.update_position(3020)
        self.assertFalse(layer.isHidden())
        self.assertEqual(layer.fade_anim.state(), QAbstractAnimation.State.Running)
        self.assertEqual(layer.fade_anim.endValue(), 0.0)
        self.assertEqual(layer.sweep_row_groups, (0, 1))
        self.assertIsNotNone(layer._subtitle_effects.cue)
        self.assertEqual(layer._subtitle_effects.scan_progress, 1.0)
        self.assertFalse(_snap(layer).isNull())

        # When fade finishes to 0.0, _finish_fade cleans up and hides
        layer.set_opacity(0.0)
        layer._finish_fade()
        self.assertTrue(layer.isHidden())
        self.assertIsNone(layer._subtitle_effects.cue)
        self.assertEqual(layer.sweep_row_groups, ())

    def test_lookahead_prewarm_eliminates_cue_transition_cold_stall(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(False)
        layer.apply_style(
            font_size=28,
            color='#FFFFFF',
            bg_opacity=0.0,
            outline_width=3,
            shadow_alpha=195,
        )
        layer._subtitle_effects.configure(STUDIO_PROFILES['ae_focus']['subtitle_effects'])
        layer.load_subtitles(self._cues())

        layer.update_position(60)
        _snap(layer)
        layer._prewarm_next_cue()
        self.assertEqual(layer._prewarmed_idx, 1)
        self.assertLessEqual(len(layer._render_cache), MAX_CACHE_ENTRIES)

        t0 = time.perf_counter()
        layer.update_position(3160)
        _snap(layer)
        prewarmed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertLess(prewarmed_ms, 8.0)

        sprite = layer._subtitle_effects._sprite
        self.assertIsNotNone(sprite)
        self.assertLessEqual(sprite.width() * sprite.height(), MAX_SPRITE_PIXELS)

    def test_all_pro_editor_entrances_and_60fps_trails_render_cleanly(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(False)
        layer.apply_style(font_size=26)
        layer.load_subtitles(self._cues())
        effect = layer._subtitle_effects
        self.assertEqual(effect._particle_timer.interval(), 16)

        clock = MediaClock()
        self.addCleanup(clock.deleteLater)
        effect.bind_player(clock)

        editor_entrances = ('editor_pop', 'editor_blur_in', 'editor_whip',
                            'editor_wave', 'editor_glitch', 'editor_slam')
        for entrance in editor_entrances:
            for trail in ('karaoke_pro', 'neon_pulse', 'spotlight', 'none'):
                with self.subTest(entrance=entrance, trail=trail):
                    effect.configure(dict(
                        enabled=True,
                        entrance=entrance,
                        color='cyber_neon',
                        trail=trail,
                        glow=True,
                        shimmer=False,
                    ))
                    layer.update_position(100)
                    for phase in (0.12, 0.38, 0.72, 1.0):
                        effect.animation.stop()
                        effect.progress = phase
                        effect.scan_progress = 0.45 if trail != 'none' else 1.0
                        img = _snap(layer)
                        self.assertFalse(img.isNull())
                    if trail != 'none':
                        self.assertTrue(effect._particle_timer.isActive())
                        self.assertLessEqual(effect.particles.last_draw_count, 24)

        clock.state = QMediaPlayer.PlaybackState.PausedState
        clock.playbackStateChanged.emit(clock.state)
        self.assertFalse(effect._particle_timer.isActive())

    def test_blackhole_exit_precise_timer_and_monotonic_clock(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(True)
        layer.apply_style(font_size=26, color='#FFFFFF', bg_opacity=0.0, outline_width=3, shadow_alpha=200)
        eff = layer._subtitle_effects
        self.assertEqual(eff._particle_timer.timerType(), Qt.TimerType.PreciseTimer)
        eff.configure(STUDIO_PROFILES['blackhole_warp']['subtitle_effects'])
        layer.load_subtitles(self._cues())

        clock = MediaClock()
        self.addCleanup(clock.deleteLater)
        eff.bind_player(clock)
        clock.position_ms = 1200
        layer.show()
        layer.update_position(1200)
        eff.animation.stop()
        eff.progress = 1.0
        _ = _snap(layer)

        # Coarse backward player tick inside same cue must not snap scan_progress backward
        first_scan = eff.scan_progress
        eff._smooth_pts_ms = 1260.0
        clock.position_ms = 1210
        eff._tick_particles()
        self.assertGreaterEqual(eff.scan_progress, first_scan)

        # Fade-out uses gentle 380ms InOutQuad and renders smooth blackhole collapse without double-dimming
        layer.update_position(3050)
        self.assertEqual(layer.fade_anim.duration(), 380)
        for op in (0.92, 0.72, 0.45, 0.22, 0.08):
            layer.set_opacity(op)
            img = _snap(layer)
            self.assertFalse(img.isNull())

    def test_video_subtitle_export_supports_mv_editor_effects(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.apply_style(font_size=26, color='#FFFFFF', bg_opacity=0.0)
        layer._subtitle_effects.configure(STUDIO_PROFILES['capcut_karaoke']['subtitle_effects'])
        layer.load_subtitles(self._cues())
        layer._anchor_rect_global = QRect(0, 0, 1100, 750)

        win = type('W', (), {
            'sub_layer': layer,
            'app_controller': type('C', (), {'current_media_item': type('M', (), {'path': 'x.mp4'})()})(),
            'video_display': None,
        })()
        snap = snapshot_from_window(win)
        self.assertFalse(snap.style['subtitle_hierarchy'])
        renderer = SubtitleBandRenderer(snap, 1280, 720, ExportSettings())
        frame = renderer.frame(150)
        self.assertNotEqual(frame, bytes(len(frame)))

    def test_per_character_beat_kinetic_typography_slicing_diacritics_and_beat_sync(self):
        import numpy as np
        from PySide6.QtCore import QRectF
        from ui.subtitle_kinetic import PER_CHAR_MODES, make_char_tiles

        layer = SubtitleLayer(SubtitleMode.VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(True)
        layer.apply_style(font_size=26, color='#FFFFFF', bg_opacity=0.0, outline_width=3, shadow_alpha=210)
        layer.load_subtitles([
            {'start': 0, 'end': 3000, 'orig': '', 'en': '', 'vi': 'Anh vẫn đứng đây chờ em'},
            {'start': 3010, 'end': 6200, 'orig': '', 'en': '', 'vi': 'Từng ký tự bay theo nhịp'},
        ])
        layer.show()
        fx = layer._subtitle_effects
        fx.configure(STUDIO_PROFILES['beat_char_pop']['subtitle_effects'])
        layer.update_position(100)
        fx.animation.stop()
        fx._particle_timer.stop()
        fx.progress = 1.0
        _ = _snap(layer)

        sp = fx._sprite
        self.assertIsNotNone(sp)
        bounds = QRectF(
            fx._sprite_origin.x(),
            fx._sprite_origin.y(),
            sp.width() / sp.devicePixelRatio(),
            sp.height() / sp.devicePixelRatio(),
        )
        tiles = make_char_tiles(layer, bounds)
        # 'Anh vẫn đứng đây chờ em' has exactly 18 non-space grapheme clusters (Vietnamese diacritics intact!)
        self.assertEqual(len(tiles), 18)
        self.assertEqual([t.col_index for t in tiles], list(range(18)))

        # Passive read-only beat pulse detector reacts cleanly to loud audio spike and tolerates empty/None
        self.assertTrue(fx.wants_audio_beat())
        fx.feed_audio_samples(None)
        fx.feed_audio_samples(np.zeros((0, 2), dtype=np.float32))
        fx.feed_audio_samples(np.full((256, 2), 0.04, dtype=np.float32))
        fx.feed_audio_samples(np.full((256, 2), 0.65, dtype=np.float32))
        pulse, _phase = fx.current_beat_pulse()
        self.assertGreater(pulse, 0.25)

        for key in ('beat_char_pop', 'char_orbit_snap', 'char_cascade_drop'):
            with self.subTest(profile=key):
                fx.configure(STUDIO_PROFILES[key]['subtitle_effects'])
                self.assertIn(fx.options['entrance'], PER_CHAR_MODES)
                layer.update_position(150)
                for p in (0.15, 0.45, 0.85, 1.0):
                    fx.animation.stop()
                    fx.progress = p
                    fx.scan_progress = 0.35
                    img = _snap(layer)
                    self.assertFalse(img.isNull())
                # Advance smoothly to end of Cue 1 then transition continuously into Cue 2 (not a seek jump)
                layer.update_position(2980)
                layer.update_position(3015)
                self.assertIsNotNone(fx._exit_ghost)
                self.assertEqual(len(fx._exit_ghost['tiles']), 18)
                for p in (0.20, 0.55):
                    fx.animation.stop()
                    fx.progress = p
                    img = _snap(layer)
                    self.assertFalse(img.isNull())


class SubtitleStudioWindowTests(unittest.TestCase):
    def test_studio_profiles_window_geometry_and_guard_fast_path(self):
        with isolated_window() as (window, root):
            window.resize(1100, 750)
            self.assertEqual((window.width(), window.height()), (1100, 750))
            self.assertLessEqual(window.minimumSizeHint().height(), 665)
            panel = window.subsettings_panel
            self.assertIsInstance(panel, SettingsPanel)

            # Test all 18 Studio VFX 1-click profiles round-trip cleanly with 2-row scrollable preset strip
            self.assertEqual(len(STUDIO_PROFILE_ORDER), 18)
            window.toggle_subsettings_panel()
            pump(20)
            available = panel.screen().availableGeometry()
            self.assertTrue(available.contains(panel.geometry()))
            self.assertGreaterEqual(panel.width(), 520)
            win_right = window.mapToGlobal(QPoint(0, 0)).x() + window.width()
            if win_right <= available.right():
                # Panel stays docked flush to the right edge of the app window
                self.assertLessEqual(abs((panel.geometry().right() + 1) - (win_right - 4)), 6)
            if available.height() >= 584:
                self.assertEqual(panel.settings_scroll.verticalScrollBar().maximum(), 0)
            if available.width() >= 948:
                self.assertEqual(panel.settings_scroll.horizontalScrollBar().maximum(), 0)
            # Preset strip shows at most 2 rows at once and scrolls smoothly for row 3+
            self.assertLessEqual(panel.profile_scroll.height(), 66)
            self.assertGreater(panel.profile_scroll.verticalScrollBar().maximum(), 0)
            self.assertTrue(panel.effects_panel.preview_button.isVisible())
            self.assertTrue(panel.btn_reset.isVisible())
            panel.hide()

            for key in STUDIO_PROFILE_ORDER:
                with self.subTest(profile=key):
                    panel.profile_btns[key].click()
                    spec = STUDIO_PROFILES[key]
                    self.assertEqual(window.config['font_color'], spec['font_color'])
                    self.assertEqual(window.config['bg_opacity'], spec['bg_opacity'])
                    self.assertNotIn('subtitle_hierarchy', window.config)
                    self.assertFalse(window.sub_layer.bilingual_hierarchy)
                    self.assertEqual(
                        window.sub_layer._subtitle_effects.options['enabled'],
                        spec['subtitle_effects']['enabled'],
                    )
                    self.assertTrue(panel.profile_btns[key].property('active'))
                    self.assertIn(spec['label'], panel.lbl_active_badge.text())
                    self.assertGreater(panel.effects_panel.presets.currentIndex(), 0)

            # Simulate app restart with a row-3 preset: fresh panel restores highlight, badge, and scrolls into view
            panel.profile_btns['glass_shatter'].click()
            fresh_panel = SettingsPanel()
            self.addCleanup(fresh_panel.deleteLater)
            fresh_panel.sync_ui(dict(window.config))
            self.assertEqual(fresh_panel._active_profile_key, 'glass_shatter')
            self.assertTrue(fresh_panel.profile_btns['glass_shatter'].property('active'))
            self.assertEqual(fresh_panel.lbl_active_badge.text(), 'Đang chọn: Gương Vỡ 3D')
            self.assertEqual(fresh_panel.lbl_active_badge.property('tone'), 'active')
            fresh_panel._on_reset_clicked()
            self.assertIsNone(fresh_panel._active_profile_key)
            self.assertEqual(fresh_panel.lbl_active_badge.text(), 'Hiệu ứng: Tắt')

            # MainWindow.moveEvent while _user_moved=True must not raise and stays bounded
            window.sub_layer.set_locked(False)
            window.sub_layer._user_moved = True
            window.sub_layer.setText('Line 1\nDòng hai')
            window.sub_layer.adjustSize()
            window.sub_layer.show()
            window.move(window.x() + 12, window.y() + 8)
            pump(20)

            # Large mode keeps compact SubtitleLayer box instead of fullscreen 1100x750
            window.update_video_location('large')
            pump(20)
            self.assertLess(window.sub_layer.width(), window.width())

            # For You VideoStage.update_layout_execution must anchor subtitle cleanly inside video_rect with no NameError
            window.foryou_page.video_container.resize(640, 360)
            window.foryou_page.video_container.set_components(window.video_display, window.sub_layer)
            window.foryou_page.video_container.update_layout_execution()
            self.assertIsNotNone(window.sub_layer._anchor_rect_global)
            self.assertEqual(window.sub_layer._anchor_rect_global.width(), 640)
            self.assertEqual(window.sub_layer._anchor_rect_global.height(), 360)
            window.update_video_location('large')
            pump(20)

            # OverlayInputGuard clears mask quickly when subtitle does not intersect controls
            window.sub_layer.move(window.x() + 120, window.y() + 120)
            window._overlay_input_guard.refresh()
            self.assertTrue(window.sub_layer.mask().isEmpty())

            # Stage size lock keeps HWND size constant across short & long cues (0 DWM reallocations)
            # and anchors shorter cues near bottom of stage rather than floating upward
            with (
                patch.object(window.sub_layer._presentation_guard, 'context_allows', return_value=True),
                patch.object(window.sub_layer._presentation_guard, 'allows', return_value=True),
            ):
                window.sub_layer.set_mode(SubtitleMode.EN)
                window.sub_layer.load_subtitles([
                    {'start': 0, 'end': 2500, 'orig': 'Hi', 'en': 'Short cue', 'vi': 'Ngắn'},
                    {
                        'start': 2600,
                        'end': 6000,
                        'orig': 'Longer Japanese verse',
                        'en': 'Dancing quietly through neon lights at midnight together under stars',
                        'vi': 'Cùng nhảy dưới ánh đèn neon lấp lánh lúc nửa đêm',
                    },
                ])
                window.sub_layer.update_position(200)
                window.sub_layer.fade_anim.stop()
                window.sub_layer.set_opacity(1.0)
                _snap(window.sub_layer)
                stage_after_short = window.sub_layer.size()
                short_plan = window.sub_layer._cached_plan
                self.assertIsNotNone(short_plan)
                self.assertGreater(short_plan.lines[-1].baseline, window.sub_layer.height() * 0.50)

                # Verify 0.0px vertical alignment between TypographyPlan, ParticlePainter rows & KineticPainter tiles
                eff = window.sub_layer._subtitle_effects
                eff.configure(STUDIO_PROFILES['bass_drop_3d']['subtitle_effects'])
                eff.particles.prepare(2500)
                self.assertEqual(len(eff.particles.rows), len(short_plan.lines))
                self.assertLess(abs(eff.particles.rows[0][0].rect.top() - short_plan.lines[0].y_top), 1.5)
                window.sub_layer.update_position(2800)
                stage_after_long = window.sub_layer.size()
                self.assertEqual(stage_after_short, stage_after_long)

                # Dynamic font size increase must expand locked stage immediately without clipping
                window.sub_layer.apply_style(font_size=18)
                h_18 = window.sub_layer.height()
                window.sub_layer.apply_style(font_size=44)
                self.assertGreater(window.sub_layer.height(), h_18)
                window.sub_layer.apply_style(font_size=24)
                window.sub_layer.set_mode(SubtitleMode.EN_VI)

            # Reset restores defaults safely
            panel._on_reset_clicked()
            self.assertEqual(window.config['font_color'], '#FFFF00')
            self.assertFalse(window.sub_layer._subtitle_effects.options['enabled'])
            self.assertFalse(window.sub_layer.bilingual_hierarchy)

    def test_dual_cue_shatter_rebirth_and_new_choreography_modes_render(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(False)
        layer.apply_style(font_size=28, color='#FFFFFF', outline_width=3, outline_color='#090D16', shadow_alpha=200)
        eff = layer._subtitle_effects
        eff.configure(STUDIO_PROFILES['shatter_rebirth']['subtitle_effects'])
        layer.load_subtitles([
            {'start': 0, 'end': 2500, 'orig': '', 'en': 'First lyric line explodes away', 'vi': 'Câu đầu tiên bung tỏa sáng'},
            {'start': 2550, 'end': 5200, 'orig': '', 'en': 'Second lyric leaps back together', 'vi': 'Câu mới bật nhảy ghép lại ngay'},
        ])
        layer.show()
        layer.update_position(2400)
        eff.animation.stop()
        eff.progress = 1.0
        _snap(layer)
        self.assertIsNotNone(eff._sprite)

        # Continuous playback across cue boundary (delta <= 500ms) captures outgoing explosion ghost
        layer.update_position(2620)
        self.assertIsNotNone(eff._exit_ghost)
        eff.animation.stop()
        eff.progress = 0.25
        eff.scan_progress = 0.25
        mid_img = _snap(layer)
        self.assertFalse(mid_img.isNull())

        eff.progress = 1.0
        _snap(layer)
        self.assertIsNone(eff._exit_ghost)

        # Exercise all 10 high-impact VFX entrances and 8 VFX trails
        clock = MediaClock()
        self.addCleanup(clock.deleteLater)
        eff.bind_player(clock)
        for entrance in (
            'vfx_supernova_shatter',
            'vfx_saber_slash',
            'vfx_bass_drop_3d',
            'vfx_cyber_glitch_pro',
            'vfx_blackhole_warp',
            'vfx_amll_silk_pro',
            'vfx_elastic_bounce_pro',
            'vfx_liquid_fire',
            'vfx_3d_domino_flip',
            'vfx_cinema_clean',
        ):
            for trail in (
                'supernova_embers',
                'thunder_chain',
                'bass_visualizer',
                'cyber_laser',
                'nebula_orbit',
                'star_confetti',
                'phoenix_embers',
                'prism_flare',
                'karaoke_pro',
            ):
                with self.subTest(entrance=entrance, trail=trail):
                    eff.configure(dict(enabled=True, entrance=entrance, color='fire_gold', trail=trail, glow=True))
                    layer.update_position(100)
                    eff.animation.stop()
                    eff.progress = 0.35
                    eff.scan_progress = 0.45
                    self.assertFalse(_snap(layer).isNull())

    def test_cold_directwrite_simd_rasterization_and_gaussian_blur_speed(self):
        layer = SubtitleLayer(SubtitleMode.EN_VI)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(False)
        layer.apply_style(font_size=29, color='#FFFDF7', outline_width=2, shadow_alpha=195)
        layer._subtitle_effects.configure(STUDIO_PROFILES['amll_live']['subtitle_effects'])
        layer.load_subtitles([
            {
                'start': 0,
                'end': 3500,
                'orig': '夜に駆ける',
                'en': 'Racing into the starlit midnight sky together',
                'vi': 'Lao vào bầu trời đêm đầy sao rực rỡ cùng nhau',
            }
        ])
        layer.update_position(120)
        # Warm font/metrics once, then clear sprite caches and measure cold SIMD + blur rasterization
        _snap(layer)
        eff = layer._subtitle_effects
        eff._sprite_key = None
        eff._sprite = None
        eff._blur_sprite_key = None
        eff._blur_sprite = None
        eff._unlit_sprite_key = None
        eff._unlit_sprite = None

        t0 = time.perf_counter()
        eff.progress = 0.25
        eff.scan_progress = 0.48
        img = _snap(layer)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertFalse(img.isNull())
        self.assertLess(elapsed_ms, 20.0)
        self.assertIsNotNone(eff._sprite)
        self.assertIsNotNone(eff._blur_sprite)
        self.assertIsNotNone(eff._unlit_sprite)
        # Gaussian blur sprite uses half-resolution smoothing
        self.assertLessEqual(eff._blur_sprite.width(), max(2, eff._sprite.width() // 2))


if __name__ == '__main__':
    unittest.main()
