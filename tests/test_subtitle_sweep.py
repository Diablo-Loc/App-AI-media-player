"""Disappearing-word pixels, cache bounds and old cue/clock preservation."""
import ast
import hashlib
import json
from pathlib import Path
import types
import unittest

from tools.ui_preview import APPLICATION
from PySide6.QtCore import QPoint
from PySide6.QtGui import QRegion
from PySide6.QtTest import QSignalSpy
from PySide6.QtMultimedia import QMediaPlayer
from subtitle.mode import SubtitleMode
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subtitle_effects import PRESETS, normalize_options
from ui.subtitle_effects_panel import SubtitleEffectsPanel
from ui.subtitle_particles import TRAILS, MAX_REGIONS, subtitle_row_groups
from tests.test_subtitle_particles import MediaClock
from tests import test_subtitle_particles as particle_tests
from tests.test_subtitle_effects import image_of
from tests.subtitle_sweep_contracts import before_sweep_changes

ROOT = Path(__file__).resolve().parents[1]


def bright_pixels(image, region=None):
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if region is not None and not region.contains(QPoint(x, y)):
                continue
            color = image.pixelColor(x, y)
            if color.alpha() > 10 and max(color.red(), color.green(), color.blue()) > 100:
                count += 1
    return count


class SweepTests(unittest.TestCase):
    layer = particle_tests.ParticleTests.layer

    def test_wrapped_language_phrases_use_one_sequential_sweep_each(self):
        orig = ' '.join(f'orig{i}' for i in range(14))
        english = ' '.join(f'english{i}' for i in range(12))
        label = SubtitleLayer(SubtitleMode.JP_EN)
        self.addCleanup(label.deleteLater)
        self.addCleanup(label.hide)
        label.set_fade_enabled(False)
        cue = dict(start=0, end=4000, orig=orig, en=english, vi='')
        label.load_subtitles([cue])
        label._subtitle_effects.configure(dict(
            enabled=True, trail='shuriken', erase_passed=True,
            soft_fade=False, entrance='none',
        ))
        label.update_position(0)

        lines = label.text().split('\n')
        self.assertEqual(len(lines), 4)
        self.assertEqual(label.sweep_row_groups, (0, 0, 1, 1))
        self.assertEqual(subtitle_row_groups(label.text(), label.mode, cue), (0, 0, 1, 1))
        particles = label._subtitle_effects.particles
        particles.prepare(4000)
        self.assertEqual(particles._row_group_ids, (0, 0, 1, 1))
        self.assertEqual(len(particles.tracks), 2)

        early = particles.targets(.10)
        late = particles.targets(.90)
        self.assertEqual(len(early), 2)
        self.assertEqual(len(late), 2)
        self.assertLess(early[0][0].rect.center().y(), late[0][0].rect.center().y())
        self.assertLess(early[1][0].rect.center().y(), late[1][0].rect.center().y())
        _, active = particles.sweep_masks(.5)
        self.assertEqual(len(active), 2)

    def test_three_languages_and_future_language_count_keep_one_track_per_phrase(self):
        orig = ' '.join(f'orig{i}' for i in range(14))
        english = ' '.join(f'english{i}' for i in range(12))
        vietnamese = ' '.join(f'vietnamese{i}' for i in range(12))
        label = SubtitleLayer(SubtitleMode.JP_EN_VI)
        self.addCleanup(label.deleteLater)
        self.addCleanup(label.hide)
        label.set_fade_enabled(False)
        cue = dict(start=0, end=6000, orig=orig, en=english, vi=vietnamese)
        label.load_subtitles([cue])
        label._subtitle_effects.configure(dict(
            enabled=True, trail='comet', erase_passed=True,
            soft_fade=False, entrance='none',
        ))
        label.update_position(0)

        groups = label.sweep_row_groups
        self.assertEqual(set(groups), {0, 1, 2})
        self.assertEqual(len(groups), len(label.text().split('\n')))
        particles = label._subtitle_effects.particles
        particles.prepare(6000)
        self.assertEqual(len(particles.tracks), 3)
        self.assertEqual(len(particles.targets(.5)), 3)
        _, active = particles.sweep_masks(.5)
        self.assertEqual(len(active), 3)

        label.mode = types.SimpleNamespace(
            display_language_keys=('jp', 'en', 'vi', 'fr', 'de', 'es')
        )
        future_cue = dict(
            orig='jp phrase', en='en phrase', vi='vi phrase',
            fr='fr phrase', de='de phrase', es='es phrase',
        )
        text, future_groups = label.build_text_plan(future_cue)
        self.assertEqual(text.split('\n'), [
            'jp phrase', 'en phrase', 'vi phrase',
            'fr phrase', 'de phrase', 'es phrase',
        ])
        self.assertEqual(future_groups, (0, 1, 2, 3, 4, 5))
        self.assertEqual(subtitle_row_groups(text, label.mode, future_cue), future_groups)

        label.setText(text)
        label.sweep_row_groups = future_groups
        label.adjustSize()
        particles.clear()
        particles.prepare(6000)
        self.assertEqual(len(particles.tracks), 6)

    def test_single_wrapped_language_is_one_sweep_and_ambiguous_text_falls_back(self):
        orig = ' '.join(f'word{i}' for i in range(16))
        label = SubtitleLayer(SubtitleMode.JP)
        self.addCleanup(label.deleteLater)
        self.addCleanup(label.hide)
        label.set_fade_enabled(False)
        cue = dict(start=0, end=4000, orig=orig, en='', vi='')
        label.load_subtitles([cue])
        label._subtitle_effects.configure(dict(
            enabled=True, trail='petals', erase_passed=True,
            soft_fade=False, entrance='none',
        ))
        label.update_position(0)
        self.assertEqual(len(label.text().split('\n')), 2)
        particles = label._subtitle_effects.particles
        particles.prepare(4000)
        self.assertEqual(len(particles.tracks), 1)
        self.assertEqual(len(particles.targets(.5)), 1)
        self.assertEqual(subtitle_row_groups('custom\npreview'), (0, 1))

    def test_passed_word_pixels_hide_and_final_cell_survives_until_layer_hide(self):
        label = self.layer('FIRST SECOND THIRD', options={
            'erase_passed': True, 'entrance': 'none', 'soft_fade': False,
            'color': 'original', 'shimmer': True, 'glow': True})
        effect = label._subtitle_effects
        # Isolate glyph pixels, retaining the actual mask/render path.
        effect.particles.paint = lambda *a, **k: None
        label.update_position(0)
        full = image_of(label)
        hidden, active = effect.particles.sweep_masks(1/3)
        self.assertFalse(hidden.isEmpty())
        self.assertGreater(bright_pixels(full, hidden), 0)
        label.update_position(1000)
        middle = image_of(label)
        self.assertEqual(bright_pixels(middle, hidden), 0)
        self.assertGreater(bright_pixels(middle, QRegion(label.rect()).subtracted(hidden)), 0)
        label.update_position(3000)
        self.assertGreater(bright_pixels(image_of(label)), 0)
        self.assertFalse(label.isHidden())  # Old inclusive endpoint is unchanged.
        label.update_position(3001)
        self.assertTrue(label.isHidden())

    def test_seek_back_repeated_next_cue_and_toggle_off_restore_glyphs(self):
        label = self.layer('word', options={'erase_passed': True, 'soft_fade': False})
        label.load_subtitles([dict(start=0, end=3000, orig='word'),
                              dict(start=3001, end=6001, orig='word')])
        effect = label._subtitle_effects
        effect.particles.paint = lambda *a, **k: None
        label.update_position(3000)
        self.assertGreater(bright_pixels(image_of(label)), 0)
        label.update_position(0)
        self.assertGreater(bright_pixels(image_of(label)), 0)
        label.update_position(3000)
        label.update_position(3001)
        self.assertGreater(bright_pixels(image_of(label)), 0)
        label.update_position(6001)
        effect.configure(None)
        label.update_position(6001)
        self.assertGreater(bright_pixels(image_of(label)), 0)
        self.assertFalse(effect._particle_timer.isActive())

    def test_masks_are_monotonic_disjoint_bounded_and_reused(self):
        for text in ('one two three', 'مرحبا بالعالم', 'שלום עולם', 'a\u0301 👩‍💻 🇻🇳',
                     '日本語の歌\nOne two three\nMột câu hát', '歌'*1000):
            label = self.layer(text, options={'erase_passed': True})
            label.update_position(500)
            image_of(label)
            particles = label._subtitle_effects.particles
            previous = QRegion()
            for phase in (0, .1, .25, .5, .75, .99, 1):
                hidden, active = particles.sweep_masks(phase)
                self.assertTrue(previous.subtracted(hidden).isEmpty(), text)
                for mask, alpha in active:
                    self.assertTrue(mask.intersected(hidden).isEmpty(), text)
                    self.assertGreaterEqual(alpha, 0)
                    self.assertLessEqual(alpha, 1)
                self.assertTrue(hidden.subtracted(QRegion(label.contentsRect())).isEmpty(), text)
                previous = hidden
            cells = particles._sweep_cells
            particles.sweep_masks(.4)
            self.assertIs(particles._sweep_cells, cells)
            self.assertLessEqual(sum(map(len, cells)), MAX_REGIONS)

    def test_single_word_short_cues_and_all_trails_preserve_cue_data(self):
        label = self.layer()
        for text in ('A', 'word', '!', 'a\u0301', '👩‍💻', '日本語', 'Một câu dài '*25):
            for duration in (1, 80, 159, 500, 3000):
                cue = dict(start=0, end=duration, orig=text, en='', vi='')
                label.load_subtitles([cue])
                saved_cues = [dict(item) for item in label.subtitles]
                for trail, _ in TRAILS:
                    label._subtitle_effects.configure(dict(enabled=True, trail=trail,
                        erase_passed=True, soft_fade=False, entrance='none'))
                    for phase in (0, .5, 1):
                        label.update_position(round(duration*phase))
                        image = image_of(label)
                        self.assertEqual(label.subtitles, saved_cues)
                        self.assertEqual(label.text(), label.build_text(saved_cues[0]))
                        if text == 'A' and (duration < 160 or trail == 'none'):
                            self.assertGreater(bright_pixels(image), 0)
                label.update_position(duration+1)
                self.assertTrue(label.isHidden())

    def test_native_clock_pause_seek_source_and_no_extra_timer(self):
        label = self.layer(options={'erase_passed': True})
        effect = label._subtitle_effects
        clock = MediaClock()
        effect.bind_player(clock)
        clock.position_ms = 1500
        label.update_position(1500)
        image_of(label)
        before = effect.scan_progress
        clock.state = QMediaPlayer.PlaybackState.PausedState
        clock.playbackStateChanged.emit(clock.state)
        effect._tick_particles()
        self.assertEqual(effect.scan_progress, before)
        self.assertFalse(effect._particle_timer.isActive())
        clock.position_ms = 0
        label.update_position(0)
        hidden, _ = effect.particles.sweep_masks(effect.scan_progress)
        self.assertTrue(hidden.isEmpty())
        clock.sourceChanged.emit(None)
        self.assertIsNone(effect.cue)
        self.assertEqual(effect.particles._sweep_cells, [])

    def test_presets_checkbox_and_legacy_settings_do_not_migrate(self):
        panel = SubtitleEffectsPanel()
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.hide)
        self.assertFalse(normalize_options({'enabled': True, 'trail': 'shuriken'})['erase_passed'])
        self.assertFalse(normalize_options({'erase_passed': 'yes'})['erase_passed'])
        panel.setChecked(True)
        spy = QSignalSpy(panel.changed)
        for index, (name, title, options) in enumerate(PRESETS[1:], 1):
            before = spy.count()
            panel.presets.setCurrentIndex(index)
            self.assertEqual(spy.count(), before+1)
            self.assertEqual(panel.erase_passed.isChecked(),
                             name in ('ninja', 'stars', 'comet', 'crystal'))
            saved = panel.options()
            panel.sync_options(saved)
            self.assertEqual(panel.options(), saved)
        panel.sync_options({'enabled': True, 'trail': 'shuriken'})
        self.assertFalse(panel.erase_passed.isChecked())
        panel.erase_passed.setChecked(True)
        self.assertTrue(panel.options()['erase_passed'])
        panel.presets.setCurrentIndex(4)  # Non-erasing fireflies preset.
        panel.erase_passed.setChecked(True)
        self.assertEqual(panel.presets.currentData(), 'custom')

    def test_legacy_effect_pixels_equal_preceding_renderer_when_erase_off(self):
        old = types.ModuleType('captured_sweep_renderer')
        exec(before_sweep_changes('app/ui/subtitle_effects.py'), old.__dict__)
        label = self.layer('One gentle song')
        current = label._subtitle_effects
        previous = old.SubtitleEffects(label)
        for trail in ('none', 'shuriken', 'comet', 'sparkles'):
            for phase in (0, .5, 1):
                options = dict(enabled=True, trail=trail, glow=True, shimmer=True,
                               entrance='burst', color='shift')
                images = []
                for effect in (current, previous):
                    label._subtitle_effects = effect
                    effect.configure(options)
                    label.update_position(round(3000*phase))
                    effect.animation.stop()
                    effect.progress = .4
                    images.append(image_of(label))
                self.assertEqual(images[0], images[1], (trail, phase))
        label._subtitle_effects = current
        previous.clear()
        previous.deleteLater()


class SweepScopeTests(unittest.TestCase):
    def test_exact_three_helper_scope_and_all_prior_app_sources_preserved(self):
        baseline = json.loads((ROOT/'docs/subtitle-sweep/app-before-normalized.json').read_text())
        for relative, digest in baseline.items():
            source = before_sweep_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(source.replace(b'\r\n', b'\n')).hexdigest(), digest, relative)
        allowed = {'app/ui/subtitle_particles.py', 'app/ui/subtitle_effects.py',
                   'app/ui/subtitle_effects_panel.py'}
        manifest = json.loads((ROOT/'docs/subtitle-sweep/reviewed-sources.json').read_text())
        self.assertEqual({p for p in manifest if p.startswith('app/')}, allowed)
        before = ast.parse(before_sweep_changes('app/ui/subtitle_effects.py'))
        from tests.subtitle_kinetic_contracts import before_kinetic_changes
        after = ast.parse(before_kinetic_changes('app/ui/subtitle_effects.py', raw=True))
        methods = ('bind_player', 'clear', 'sync', '_sync_particles', '_arm_particles',
                   '_tick_particles', '_state_changed', '_source_changed', '_media_status_changed')
        for name in methods:
            a = next(n for n in ast.walk(before) if isinstance(n, ast.FunctionDef) and n.name == name)
            b = next(n for n in ast.walk(after) if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(ast.dump(a), ast.dump(b), name)


if __name__ == '__main__':
    unittest.main()
