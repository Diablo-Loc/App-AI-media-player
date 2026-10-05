"""Real Qt painter, cue/lifecycle and isolated appearance persistence checks."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.ui_preview import APPLICATION, isolated_window, pump
# Keep Qt wrapper classes resident across preview's sys.modules isolation.
from ui.main_window import MainWindow
from ui.subs_ui.subtitle_layer import SubtitleLayer, DraggableSubtitle
from ui.subtitle_effects import SubtitleEffects, normalize_options, DEFAULTS, ENTRANCES, COLORS
from ui.subtitle_effects_panel import SubtitleEffectsPanel
from subtitle.mode import SubtitleMode
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QDialog
from PySide6.QtTest import QSignalSpy
from PySide6.QtMultimedia import QMediaPlayer
from tests.subtitle_effects_contracts import before_effect_changes
from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]
CUES = [dict(start=1000, end=2000, orig='優しい歌 · Dịu dàng'),
        dict(start=2001, end=3000, orig='優しい歌 · Dịu dàng')]


def image_of(label):
    image = QImage(label.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    label.render(painter, label.rect().topLeft())
    painter.end()
    return image


class EffectTests(unittest.TestCase):
    def layer(self):
        layer = SubtitleLayer(SubtitleMode.JP)
        layer.load_subtitles(CUES)
        layer.set_fade_enabled(False)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        return layer

    def test_options_off_by_default_and_validate_corrupt_input(self):
        self.assertEqual(normalize_options(None), DEFAULTS)
        self.assertFalse(normalize_options({'enabled': 'true'})['enabled'])
        options = normalize_options({'enabled': True, 'entrance': 'invalid',
                                     'color': {}, 'duration': 999999, 'glow': 1})
        self.assertEqual(options['duration'], 600)
        self.assertFalse(options['glow'])
        self.assertEqual(options['entrance'], DEFAULTS['entrance'])
        self.assertEqual(normalize_options({'duration': True})['duration'], 320)

    def test_off_pixels_and_cues_equal_captured_renderer(self):
        source = before_effect_changes('app/ui/subs_ui/subtitle_layer.py')
        namespace = {'__name__': 'baseline_effect_layer'}
        exec(compile(source, 'baseline_effect_layer', 'exec'), namespace)
        before = namespace['SubtitleLayer'](SubtitleMode.JP)
        self.addCleanup(before.deleteLater)
        self.addCleanup(before.hide)
        before.load_subtitles(CUES)
        before.set_fade_enabled(False)
        after = self.layer()
        for pts in (1000, 1300, 2000, 2001, 3000, 3001, 1200):
            before.update_position(pts)
            after.update_position(pts)
            self.assertEqual(after.text(), before.text())
            self.assertEqual(after.isHidden(), before.isHidden())
            self.assertEqual(after.get_opacity(), before.get_opacity())
            self.assertEqual(image_of(after), image_of(before))
        self.assertEqual(after.subtitles, before.subtitles)
        self.assertEqual(after._start_times, before._start_times)

    def test_all_modes_render_unicode_and_stable_geometry(self):
        layer = self.layer()
        layer.update_position(1000)
        baseline = layer.geometry()
        for entrance, _ in ENTRANCES:
            for color, _ in COLORS:
                with self.subTest(entrance=entrance, color=color):
                    layer._subtitle_effects.configure(dict(enabled=True, entrance=entrance,
                        color=color, glow=True, shimmer=True))
                    layer.update_position(1000)
                    for time in (0, 80, 180, 320):
                        layer._subtitle_effects.animation.setCurrentTime(time)
                        self.assertFalse(image_of(layer).isNull())
                        self.assertEqual(layer.geometry(), baseline)
                        self.assertEqual(layer.text(), CUES[0]['orig'])
                        self.assertIsNotNone(layer._cached_path)

    def test_same_cue_does_not_restart_and_identical_next_cue_does(self):
        layer = self.layer()
        effect = layer._subtitle_effects
        effect.configure(dict(enabled=True))
        layer.update_position(1000)
        effect.animation.setCurrentTime(90)
        for _ in range(100):
            layer.update_position(1050)
        self.assertEqual(effect.animation.currentTime(), 90)
        layer.update_position(2001)
        self.assertEqual(effect.cue[0], 1)
        self.assertEqual(effect.animation.currentTime(), 0)

    def test_seek_midcue_is_complete_and_seek_back_uses_media_offset(self):
        layer = self.layer()
        effect = layer._subtitle_effects
        effect.configure(dict(enabled=True))
        layer.update_position(1700)
        self.assertEqual(effect.progress, 1)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
        layer.update_position(1080)
        self.assertAlmostEqual(effect.progress, .25)
        self.assertEqual(effect.animation.currentTime(), 80)

    def test_short_cues_never_extend_timing_or_consume_whole_cue(self):
        layer = self.layer()
        layer.load_subtitles([dict(start=0, end=100, orig='短い')])
        effect = layer._subtitle_effects
        effect.configure(dict(enabled=True, duration=600))
        layer.update_position(0)
        self.assertEqual(effect.animation.duration(), 50)
        layer.update_position(100)
        self.assertFalse(layer.isHidden())
        self.assertEqual(effect.progress, 1)
        layer.update_position(101)
        self.assertTrue(layer.isHidden())
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)

    def test_erased_sentence_stays_hidden_during_live_fade_out(self):
        layer = self.layer()
        layer.load_subtitles([dict(start=1000, end=2000, orig='A sentence swept away')])
        layer.set_fade_enabled(True)
        effect = layer._subtitle_effects
        effect.configure(dict(enabled=True, trail='shuriken', erase_passed=True))
        layer.update_position(1000)
        effect.scan_progress = .99

        layer.update_position(2001)

        self.assertFalse(layer.isHidden())
        self.assertEqual(layer.text(), 'A sentence swept away')
        self.assertEqual(effect.scan_progress, 1.0)
        self.assertIsNotNone(effect.cue)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(layer.fade_anim.endValue(), 0.0)

        erased_frame = image_of(layer)
        effect.clear()
        restored_frame = image_of(layer)
        self.assertNotEqual(erased_frame, restored_frame)

    def test_hidden_off_empty_and_load_cancel_animation(self):
        layer = self.layer()
        effect = layer._subtitle_effects
        effect.configure(dict(enabled=True))
        for stop in (lambda: layer.hide(), lambda: layer.load_subtitles([]),
                     lambda: layer.set_mode(SubtitleMode.OFF),
                     lambda: effect.configure(dict(enabled=False))):
            layer.set_mode(SubtitleMode.JP)
            layer.load_subtitles(CUES)
            effect.configure(dict(enabled=True))
            layer.update_position(1000)
            stop()
            self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
            self.assertEqual(effect.progress, 1)

    def test_static_gradient_has_no_animation_and_path_reused(self):
        layer = self.layer()
        effect = layer._subtitle_effects
        effect.configure(dict(enabled=True, entrance='none', color='mint', soft_fade=False))
        layer.update_position(1000)
        image_of(layer)
        path = layer._cached_path
        sprite = effect._sprite
        self.assertIsNotNone(sprite)
        self.assertLessEqual(sprite.width() * sprite.height(), 2_000_000)
        for _ in range(50):
            layer.update_position(1150)
            image_of(layer)
            self.assertIs(layer._cached_path, path)
            self.assertIs(effect._sprite, sprite)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
        layer.apply_style(font_size=30)
        image_of(layer)
        self.assertIsNot(effect._sprite, sprite)
        effect.configure(None)
        self.assertIsNone(effect._sprite)

    def test_complete_animation_is_finite_and_reset_restores_original_pixels(self):
        layer = self.layer()
        layer.update_position(1300)
        before = image_of(layer)
        effect = layer._subtitle_effects
        effect.configure(dict(enabled=True, color='sunset', glow=True, shimmer=True))
        layer.update_position(1000)
        effect.animation.setCurrentTime(effect.animation.duration())
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(effect.progress, 1)
        self.assertNotEqual(image_of(layer), before)
        effect.configure(None)
        self.assertEqual(image_of(layer), before)

    def test_player_pause_resume_stop_and_rate(self):
        layer = self.layer()
        effect = layer._subtitle_effects
        player = QMediaPlayer()
        self.addCleanup(player.deleteLater)
        effect.bind_player(player)
        effect.configure(dict(enabled=True))
        layer.update_position(1080)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Paused)
        effect._state_changed(QMediaPlayer.PlaybackState.PlayingState)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Running)
        effect._state_changed(QMediaPlayer.PlaybackState.PausedState)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Paused)
        player.setPlaybackRate(2)
        self.assertEqual(effect.animation.duration(), 160)
        self.assertEqual(effect.animation.currentTime(), 40)
        effect._state_changed(QMediaPlayer.PlaybackState.StoppedState)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
        self.assertIsNone(effect.cue)


class PanelTests(unittest.TestCase):
    def test_sync_does_not_emit_and_options_can_combine(self):
        panel = SubtitleEffectsPanel()
        self.addCleanup(panel.deleteLater)
        spy = QSignalSpy(panel.changed)
        panel.sync_options(dict(enabled=True, entrance='rise', color='pastel', glow=True,
                                duration=275, shimmer=True))
        self.assertEqual(spy.count(), 0)
        self.assertEqual(panel.options()['duration'], 275)
        self.assertTrue(panel.options()['glow'])
        panel.setChecked(False)
        self.assertEqual(spy.count(), 1)
        self.assertFalse(spy.at(0)[0]['enabled'])
        self.assertTrue(panel.options()['shimmer'])

    def test_preview_uses_production_painter_and_stops_on_hide(self):
        panel = SubtitleEffectsPanel()
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.hide)
        panel.sync_options(dict(enabled=True, entrance='drop', color='ocean'))
        panel.show()
        panel.play_preview()
        effect = panel.preview._subtitle_effects
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Running)
        self.assertFalse(image_of(panel.preview).isNull())
        panel.hide()
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)

    def test_shell_persists_only_appearance_and_reset_off(self):
        with isolated_window() as (window, root):
            player = window.media_player.player
            panel = window.subsettings_panel.effects_panel
            old_fade = window.sub_layer.use_fade_effect
            old_data = [dict(cue) for cue in window.sub_layer.subtitles]
            with patch.object(player, 'setSource') as source, patch.object(player, 'setPosition') as seek:
                panel.setChecked(True)
                panel.color.setCurrentIndex(panel.color.findData('mint'))
                panel.glow.setChecked(True)
                saved = json.loads(Path(window.settings_file).read_text())
                self.assertTrue(saved['appearance']['subtitle_effects']['enabled'])
                self.assertEqual(saved['appearance']['subtitle_effects']['color'], 'mint')
                self.assertTrue(saved['appearance']['subtitle_effects']['glow'])
                source.assert_not_called()
                seek.assert_not_called()
            self.assertEqual(window.sub_layer.subtitles, old_data)
            self.assertEqual(window.sub_layer.use_fade_effect, old_fade)
            options = dict(saved['appearance']['subtitle_effects'])
            window.subsettings_panel.sync_ui(saved['appearance'])
            self.assertEqual(panel.options(), options)
            window.subsettings_panel._on_reset_clicked()
            self.assertFalse(panel.isChecked())
            self.assertFalse(window.sub_layer._subtitle_effects.options['enabled'])
            self.assertNotIn('subtitle_effects', window.config)

    def test_popup_scroll_all_controls_reachable_and_inside_screen(self):
        with isolated_window() as (window, root):
            panel = window.subsettings_panel
            window.toggle_subsettings_panel()
            pump(20)
            available = panel.screen().availableGeometry()
            self.assertTrue(available.contains(panel.geometry()))
            bar = panel.settings_scroll.verticalScrollBar()
            self.assertGreater(bar.maximum(), 0)
            panel.settings_scroll.ensureWidgetVisible(panel.effects_panel.preview_button)
            pump(10)
            self.assertGreater(bar.value(), 0)
            self.assertTrue(panel.effects_panel.preview_button.isVisible())
            panel.settings_scroll.ensureWidgetVisible(panel.btn_reset)
            pump(10)
            self.assertTrue(panel.btn_reset.isVisible())
            panel.hide()

    def test_saved_effects_loaded_at_startup_without_rewriting_preferences(self):
        options = normalize_options(dict(enabled=True, entrance='bounce', color='sunset',
                                         glow=True, shimmer=True, duration=480))
        saved = json.dumps({'appearance': {'subtitle_effects': options},
                            'download': {'quality': 'Original (Giữ nguồn)'}}).encode('utf-8')
        original_load = MainWindow.load_config

        def seed_settings(window):
            Path(window.settings_file).write_bytes(saved)
            return original_load(window)

        # A real Python method keeps QObject slot introspection intact. Do not
        # replace a QObject class method with a MagicMock (native Qt crash).
        with patch.object(MainWindow, 'load_config', new=seed_settings):
            with isolated_window() as (window, root):
                self.assertEqual(window.sub_layer._subtitle_effects.options, options)
                self.assertEqual(window.subsettings_panel.effects_panel.options(), options)
                self.assertEqual(Path(window.settings_file).read_bytes(), saved)

    def test_editor_with_effects_on_suppresses_and_resumes_current_cue_without_replay(self):
        with isolated_window() as (window, root):
            layer = window.sub_layer
            window.update_video_location('large')
            window.activateWindow()
            layer.set_mode(SubtitleMode.JP)
            layer.set_fade_enabled(False)
            layer.load_subtitles(CUES)
            effect = layer._subtitle_effects
            effect.configure(dict(enabled=True, color='pastel', shimmer=True))
            self.assertTrue(layer.enable_render)
            with patch.object(layer._presentation_guard, 'context_allows', return_value=True):
                layer.update_position(1000)
                effect.animation.setCurrentTime(80)
            dialog = QDialog(window)
            dialog.show()
            pump(10)
            self.assertTrue(layer.isHidden())
            self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
            layer.update_position(1600)
            self.assertTrue(layer.isHidden())
            dialog.hide()
            dialog.deleteLater()
            with patch.object(layer._presentation_guard, 'context_allows', return_value=True):
                layer._presentation_guard.refresh()
                self.assertFalse(layer.isHidden())
                self.assertEqual(layer.text(), CUES[0]['orig'])
                self.assertEqual(effect.progress, 1)
                self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)


class EffectScopeTests(unittest.TestCase):
    def test_only_painter_and_settings_adapters_change_old_production(self):
        allowed = {
            'app/ui/main_window.py': {'MainWindow.__init__'},
            'app/ui/subs_ui/subtitle_layer.py': {'DraggableSubtitle.paintEvent',
                'SubtitleLayer.__init__', 'SubtitleLayer.load_subtitles',
                'SubtitleLayer.update_position', 'SubtitleLayer._smart_hide'},
            'app/ui/subs_ui/sub_panel.py': {'SettingsPanel.__init__',
                'SettingsPanel._on_reset_clicked', 'SettingsPanel.sync_ui'},
        }
        for relative, methods in allowed.items():
            before = before_effect_changes(relative)
            from tests.resource_performance_contracts import before_resource_changes
            after = before_resource_changes(relative)
            a, b = functions(ast.parse(before)), functions(ast.parse(after))
            for name in a:
                if name not in methods:
                    self.assertEqual(a[name], b[name], (relative, name))
            if relative.endswith('main_window.py'):
                self.assertEqual(after.replace('from ui.subtitle_effects import install_subtitle_effects\n', '')
                    .replace('        install_subtitle_effects(self)\n', ''), before)
            elif relative.endswith('subtitle_layer.py'):
                restored = after.replace('from ui.subtitle_effects import SubtitleEffects\n', '')
                restored = restored.replace(
                    "        keep_erased_sweep = (\n"
                    "            not self.isHidden() and not instant and self.use_fade_effect\n"
                    "            and self._subtitle_effects.finish_erase_sweep_for_fade()\n"
                    "        )\n"
                    "        if not keep_erased_sweep:\n"
                    "            self._subtitle_effects.clear()\n",
                    "        self._subtitle_effects.clear()\n",
                )
                restored = restored.replace("        effects = getattr(self, '_subtitle_effects', None)\n"
                    '        if effects is not None and effects.paint(painter, path):\n'
                    '            painter.end()\n            return\n\n', '')
                restored = restored.replace('        self._subtitle_effects = SubtitleEffects(self)\n', '')
                restored = restored.replace('        self._subtitle_effects.clear()\n', '')
                restored = restored.replace("        self._subtitle_effects.sync((idx, active_sub['start'], "
                    "active_sub['end'], new_text), pts_ms)\n\n", '')
                self.assertEqual(restored, before)

    def test_all_prior_app_sources_unchanged_outside_three_ui_adapters(self):
        baseline = json.loads((ROOT/'docs/subtitle-effects/app-before-normalized.json').read_text())
        for relative, digest in baseline.items():
            current = before_effect_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(current.replace(b'\r\n', b'\n')).hexdigest(), digest, relative)
        helpers = json.loads((ROOT/'docs/subtitle-effects/helper-hash.json').read_text())
        for relative, digest in helpers.items():
            from tests.subtitle_particles_contracts import before_particle_changes
            self.assertEqual(hashlib.sha256(before_particle_changes(relative, raw=True)).hexdigest(), digest, relative)


if __name__ == '__main__':
    unittest.main()
