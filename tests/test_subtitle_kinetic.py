"""Kinetic glyph rendering, cue/clock compatibility and bounded work."""
import ast
import hashlib
import json
import math
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from tools.ui_preview import APPLICATION, pump, isolated_window
from PySide6.QtCore import QRectF, QAbstractAnimation
from PySide6.QtTest import QSignalSpy
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QDialog
from ui.subtitle_effects import PRESETS, normalize_options
from ui.subtitle_effects_panel import SubtitleEffectsPanel
from ui.subtitle_kinetic import (KINETIC_MODES, KINETIC_ENTRANCES, MAX_TILES,
                                 _units, make_tiles, motion, Tile)
from tests import test_subtitle_particles as particle_tests
from tests.test_subtitle_particles import MediaClock
from tests.test_subtitle_effects import image_of
from tests.test_subtitle_sweep import bright_pixels
from tests.subtitle_kinetic_contracts import before_kinetic_changes

ROOT = Path(__file__).resolve().parents[1]


class KineticTests(unittest.TestCase):
    layer = particle_tests.ParticleTests.layer

    def test_grapheme_cursive_dense_and_multiline_plans_bounded(self):
        for text in ('a\u0301', '👩‍💻', '🇻🇳', 'कि'):
            self.assertEqual(_units(text, 'glyph'), [(0, len(text.encode('utf-16-le'))//2)])
        self.assertEqual(_units('hello world', 'word'), [(0, 5), (6, 11)])
        self.assertEqual(_units('مرحبا بالعالم', 'glyph'), _units('مرحبا بالعالم', 'word'))
        label = self.layer()
        for text in ('A', 'One gentle song', '日本語の歌\nOne two\nMột câu hát',
                     'שלום עולם', 'a\u0301 👩‍💻', '歌'*1000, 'w'*10000, 'abc\n'*500, ' '):
            label.setText(text)
            label.resize(700, 160)
            bounds = QRectF(-10, -10, 720, 180)
            for parts in ('auto', 'word', 'glyph'):
                for duration in (1, 80, 160, 480):
                    cells = make_tiles(label, bounds, parts, duration)
                    self.assertLessEqual(len(cells), MAX_TILES)
                    for cell in cells:
                        self.assertTrue(bounds.contains(cell.rect), (text[:20], cell))
                    self.assertFalse(cell.rect.isEmpty())

    def test_heavy_combinations_reduce_tiles_and_oversized_sprite_falls_back(self):
        label = self.layer('One gentle song beneath the stars')
        effect = label._subtitle_effects
        for extra in ({'color': 'shift'}, {'shimmer': True}, {'erase_passed': True}):
            effect.configure(dict(enabled=True, entrance='kinetic_drop', trail='sparkles',
                                  kinetic_parts='glyph', **extra))
            label.update_position(100)
            effect.animation.stop()
            effect.progress = .5
            image_of(label)
            self.assertLessEqual(len(effect.kinetic.tiles), 6)
        effect.kinetic.clear()
        self.assertFalse(effect.kinetic.paint(None, None, None, 'kinetic_drop', .5,
                                             'normal', 'auto', 480, lambda *a: None))
        self.assertEqual(effect.kinetic.last_draw_count, 0)

    def test_motion_strong_finite_deterministic_and_finishes_exactly(self):
        bounds, tile = QRectF(0, 0, 600, 120), Tile(QRectF(80, 0, 100, 60), 130, 30)
        for mode in KINETIC_MODES:
            for strength in ('gentle', 'normal', 'bold'):
                for count in (1, 16):
                    for phase in (0, .1, .5, .99, 1):
                        result = motion(mode, phase, count-1, count, tile, bounds, strength)
                        self.assertTrue(all(math.isfinite(v) for v in result))
                        self.assertEqual(result, motion(mode, phase, count-1, count, tile, bounds, strength))
                        self.assertGreater(result[2], 0)
                        self.assertGreater(result[3], 0)
                        self.assertTrue(0 <= result[-1] <= 1)
                        if phase == 1:
                            self.assertEqual(result, (0, 0, 1, 1, 0, 1))
        self.assertGreater(abs(motion('kinetic_drop', 0, 0, 1, tile, bounds, 'bold')[1]), 100)
        self.assertGreater(abs(motion('kinetic_drop', 0, 0, 1, tile, bounds, 'bold')[1]),
                           abs(motion('kinetic_drop', 0, 0, 1, tile, bounds, 'gentle')[1]))

    def test_render_matrix_text_geometry_limits_and_cache_reuse(self):
        label = self.layer()
        effect = label._subtitle_effects
        count = 0
        for text in ('A', 'word', 'a\u0301 👩‍💻 🇻🇳', '優しい歌', 'مرحبا بالعالم', 'Một câu hát '*8):
            for duration in (80, 500, 3000):
                label.load_subtitles([dict(start=0, end=duration, orig=text)])
                baseline = [dict(cue) for cue in label.subtitles]
                for mode in KINETIC_MODES:
                    for parts in ('word', 'glyph'):
                        effect.configure(dict(enabled=True, entrance=mode, color='mint', trail='none',
                            kinetic_strength='bold', kinetic_parts=parts, soft_fade=False))
                        label.update_position(0)
                        geometry = label.geometry()
                        for phase in (0, .25, .6, 1):
                            effect.animation.stop()
                            effect.progress = phase
                            image = image_of(label)
                            self.assertFalse(image.isNull())
                            self.assertEqual(label.geometry(), geometry)
                            self.assertEqual(label.subtitles, baseline)
                            self.assertEqual(label.text(), label.build_text(baseline[0]))
                            self.assertLessEqual(effect.kinetic.last_draw_count, MAX_TILES)
                            count += 1
                        if duration >= 160:
                            effect.progress = .5
                            image_of(label)
                            cells, sprite = effect.kinetic.tiles, effect._sprite
                            image_of(label)
                            self.assertIs(effect.kinetic.tiles, cells)
                            self.assertIs(effect._sprite, sprite)
        self.assertEqual(count, 1152)

    def test_settled_pixels_equal_static_glyphs_and_short_cues_stay_readable(self):
        label = self.layer('One gentle song')
        effect = label._subtitle_effects
        for mode in KINETIC_MODES:
            common = dict(enabled=True, trail='none', color='pastel', soft_fade=False, glow=True)
            effect.configure(dict(entrance=mode, **common))
            label.update_position(1000)
            kinetic = image_of(label)
            effect.configure(dict(entrance='none', **common))
            label.update_position(1000)
            self.assertEqual(kinetic, image_of(label), mode)
            for duration in (1, 80, 159):
                label.load_subtitles([dict(start=0, end=duration, orig='A')])
                effect.configure(dict(entrance=mode, **common))
                label.update_position(0)
                self.assertGreater(bright_pixels(image_of(label)), 0)
                self.assertEqual(effect.kinetic.last_draw_count, 0)
            label.load_subtitles([dict(start=0, end=3000, orig='One gentle song')])

    def test_sweep_combination_masks_end_and_off_restores(self):
        label = self.layer('One two three')
        effect = label._subtitle_effects
        for mode in KINETIC_MODES:
            effect.configure(dict(enabled=True, entrance=mode, trail='shuriken',
                erase_passed=True, glow=True, shimmer=True, soft_fade=False))
            label.update_position(3000)
            self.assertEqual(bright_pixels(image_of(label)), 0)
            self.assertFalse(label.isHidden())
            effect.configure(None)
            label.update_position(3000)
            self.assertGreater(bright_pixels(image_of(label)), 0)
        label.update_position(3001)
        self.assertTrue(label.isHidden())

    def test_cropped_source_preserves_glyph_pixels_at_identity_transform(self):
        label = self.layer('One gentle song')
        effect = label._subtitle_effects
        options = dict(enabled=True, color='mint', trail='none', soft_fade=False, glow=True)
        effect.configure(dict(entrance='none', **options))
        label.update_position(150)
        baseline = image_of(label)
        effect.configure(dict(entrance='kinetic_spring', kinetic_parts='word', **options))
        label.update_position(150)
        effect.animation.stop()
        effect.progress = .5
        with patch('ui.subtitle_kinetic.motion', return_value=(0, 0, 1, 1, 0, 1)):
            self.assertEqual(image_of(label), baseline)

    def test_entry_pause_rate_seek_repeat_hide_clear_uses_existing_owner(self):
        label = self.layer('word')
        label.load_subtitles([dict(start=0, end=3000, orig='word'),
                              dict(start=3001, end=6001, orig='word')])
        effect, clock = label._subtitle_effects, MediaClock()
        effect.bind_player(clock)
        effect.configure(dict(enabled=True, entrance='kinetic_drop', duration=480, trail='none'))
        label.update_position(50)
        image_of(label)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Running)
        clock.state = QMediaPlayer.PlaybackState.PausedState
        clock.playbackStateChanged.emit(clock.state)
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Paused)
        previous = effect.progress
        pump(30)
        self.assertEqual(effect.progress, previous)
        clock.rate = 2
        clock.playbackRateChanged.emit(2)
        self.assertEqual(effect.animation.duration(), 240)
        label.update_position(0)
        self.assertEqual(effect.progress, 0)
        label.update_position(3001)
        self.assertEqual(effect.cue[0], 1)
        self.assertEqual(effect.progress, 0)
        label.hide()
        self.assertEqual(effect.animation.state(), QAbstractAnimation.State.Stopped)
        effect.clear()
        self.assertEqual(effect.kinetic.tiles, [])
        self.assertIsNone(effect.cue)

    def test_old_effect_pixels_stay_equal_to_preceding_renderer(self):
        old = types.ModuleType('captured_kinetic_renderer')
        exec(before_kinetic_changes('app/ui/subtitle_effects.py'), old.__dict__)
        label = self.layer('One gentle song')
        current, previous = label._subtitle_effects, old.SubtitleEffects(label)
        for mode in ('none', 'drop', 'burst'):
            for erase in (False, True):
                images = []
                for effect in (current, previous):
                    label._subtitle_effects = effect
                    effect.configure(dict(enabled=True, entrance=mode, color='shift', trail='shuriken',
                                          erase_passed=erase, glow=True, shimmer=True))
                    label.update_position(1500)
                    effect.animation.stop()
                    effect.progress = .4
                    images.append(image_of(label))
                self.assertEqual(images[0], images[1], (mode, erase))
        label._subtitle_effects = current
        previous.clear()
        previous.deleteLater()

    def test_presets_options_roundtrip_emit_once_and_legacy_defaults(self):
        options = normalize_options({'enabled': True, 'entrance': 'drop'})
        self.assertEqual(options['kinetic_strength'], 'normal')
        self.assertEqual(options['kinetic_parts'], 'auto')
        self.assertFalse(normalize_options(None)['enabled'])
        panel = SubtitleEffectsPanel()
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.hide)
        panel.setChecked(True)
        spy = QSignalSpy(panel.changed)
        for index, (_, _, settings) in enumerate(PRESETS):
            if settings.get('entrance') not in KINETIC_MODES:
                continue
            previous = spy.count()
            panel.presets.setCurrentIndex(index)
            self.assertEqual(spy.count(), previous+1)
            for key, value in settings.items():
                self.assertEqual(panel.options()[key], value)
            self.assertFalse(panel.options()['erase_passed'])
            saved = panel.options()
            panel.sync_options(saved)
            self.assertEqual(panel.options(), saved)

    def test_real_settings_popup_editor_reset_preserve_subtitle_dispatch(self):
        with isolated_window() as (window, root):
            window.update_video_location('large')
            panel = window.subsettings_panel.effects_panel
            panel.setChecked(True)
            index = panel.presets.findData('rain')
            panel.presets.setCurrentIndex(index)
            config = json.loads(Path(window.settings_file).read_text())
            self.assertEqual(config['appearance']['subtitle_effects']['entrance'], 'kinetic_drop')
            layer = window.sub_layer
            layer.set_fade_enabled(False)
            layer.load_subtitles([dict(start=0, end=3000, orig='A gentle song')])
            layer.update_position(50)
            dialog = QDialog(window)
            dialog.show()
            pump(10)
            self.assertTrue(layer.isHidden())
            self.assertEqual(layer._subtitle_effects.animation.state(), QAbstractAnimation.State.Stopped)
            dialog.close()
            dialog.deleteLater()
            window._reset_defaults()
            self.assertFalse(panel.isChecked())
            self.assertEqual(layer._subtitle_effects.kinetic.tiles, [])


class KineticScopeTests(unittest.TestCase):
    def test_only_two_effect_helpers_change_and_prior_sources_owners_preserved(self):
        baseline = json.loads((ROOT/'docs/subtitle-kinetic/app-before-normalized.json').read_text())
        for relative, digest in baseline.items():
            current = before_kinetic_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(current.replace(b'\r\n', b'\n')).hexdigest(), digest, relative)
        after = ast.parse((ROOT/'app/ui/subtitle_effects.py').read_bytes())
        before = ast.parse(before_kinetic_changes('app/ui/subtitle_effects.py'))
        for name in ('bind_player', 'sync', '_sync_particles', '_arm_particles', '_tick_particles',
                     '_state_changed', '_rate_changed', '_source_changed', 'install_subtitle_effects',
                     '_draw_static', '_static_sprite'):
            a = next(n for n in ast.walk(before) if isinstance(n, ast.FunctionDef) and n.name == name)
            b = next(n for n in ast.walk(after) if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(ast.dump(a), ast.dump(b), name)
        hashes = json.loads((ROOT/'docs/subtitle-kinetic/helper-hash.json').read_text())
        for relative, digest in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(), digest, relative)


if __name__ == '__main__':
    unittest.main()
