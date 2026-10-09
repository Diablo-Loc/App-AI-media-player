"""Unicode/cue/clock/limits and compatibility for decorative subtitle sweeps."""
import ast
import hashlib
import json
from pathlib import Path
import unittest

from tools.ui_preview import APPLICATION, isolated_window, pump
from ui.main_window import MainWindow
from ui.subs_ui.subtitle_layer import SubtitleLayer, DraggableSubtitle
from ui.subtitle_effects import normalize_options, DEFAULTS, PRESETS, ENTRANCES
from ui.subtitle_effects_panel import SubtitleEffectsPanel
from ui.subtitle_particles import word_units, build_regions, TRAILS, MAX_PARTICLES, MAX_REGIONS
from subtitle.mode import SubtitleMode
from PySide6.QtCore import QObject, Signal, Qt, QAbstractAnimation
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QDialog
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QSignalSpy
from tests.subtitle_particles_contracts import before_particle_changes
from tests.test_subtitle_effects import image_of
from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]


class MediaClock(QObject):
    playbackStateChanged = Signal(object)
    playbackRateChanged = Signal(float)
    mediaStatusChanged = Signal(object)
    sourceChanged = Signal(object)

    def __init__(self):
        super().__init__()
        self.position_ms = 0
        self.state = QMediaPlayer.PlaybackState.PlayingState
        self.status = QMediaPlayer.MediaStatus.BufferedMedia
        self.rate = 1.0

    def position(self):
        return self.position_ms

    def playbackState(self):
        return self.state

    def mediaStatus(self):
        return self.status

    def playbackRate(self):
        return self.rate


class ParticleTests(unittest.TestCase):
    def layer(self, text='A gentle song', duration=3000, options=None):
        label = SubtitleLayer(SubtitleMode.JP)
        label.set_fade_enabled(False)
        label.load_subtitles([dict(start=0, end=duration, orig=text)])
        label._subtitle_effects.configure(dict(enabled=True, trail='shuriken',
                                             **(options or {})))
        label.update_position(0)
        self.addCleanup(label.deleteLater)
        self.addCleanup(label.hide)
        return label

    def test_grapheme_units_preserve_accents_emoji_and_utf16_indices(self):
        samples = ('a\u0301', '👩‍💻', '👨‍👩‍👧‍👦', '🇻🇳', '👍🏽', 'कि', '日', '𝄞')
        for text in samples:
            with self.subTest(text=text):
                encoded = text.encode('utf-16-le')
                self.assertEqual(word_units(text), [(0, len(encoded)//2)])
        self.assertEqual(word_units('hello world'), [(0, 5), (6, 11)])
        self.assertEqual(len(word_units('日本語')), 3)
        self.assertEqual(word_units('  \t\n '), [])

    def test_layout_regions_bidi_and_multilingual_are_bounded(self):
        label = DraggableSubtitle()
        self.addCleanup(label.deleteLater)
        for text in ('Một câu hát\n日本語の歌\nA gentle song', 'مرحبا بالعالم', 'שלום עולם',
                     'a\u0301 👩‍💻 🇻🇳', 'หนึ่งเพลง', '한 곡의 노래'):
            label.setText(text)
            label.adjustSize()
            rows = build_regions(label, 3000)
            self.assertTrue(rows, text)
            for row in rows:
                for region in row:
                    self.assertTrue(label.contentsRect().contains(region.rect.toRect()), text)
                    self.assertGreater(region.end, region.start)

    def test_long_dense_short_and_pathological_cues_have_bounded_plans(self):
        label = DraggableSubtitle()
        self.addCleanup(label.deleteLater)
        label.resize(800, 90)
        for text in ('word '*1000, '歌'*2000, 'w'*10000, ('abc\n'*1000), ' '):
            label.setText(text)
            for duration in (0, 1, 80, 1000, 600000):
                rows = build_regions(label, duration)
                count = sum(len(row) for row in rows)
                self.assertLessEqual(count, MAX_REGIONS)
                if duration <= 80:
                    self.assertTrue(all(len(row) <= 1 for row in rows))

    def test_all_styles_lengths_fonts_and_frames_keep_text_and_geometry(self):
        cases = ('A', 'word', '!', 'a\u0301', '👩‍💻', '優しい歌',
                 'One long lyric line with repeated words '*6, '歌'*90,
                 'مرحبا بالعالم', 'Một câu hát dịu dàng')
        label = self.layer()
        effect = label._subtitle_effects
        checked = 0
        for text in cases:
            for duration in (1, 80, 500, 3000):
                label.load_subtitles([dict(start=0, end=duration, orig=text)])
                for font in (18, 36, 72):
                    label.apply_style(font_size=font)
                    for style, _ in TRAILS:
                        effect.configure(dict(enabled=True, trail=style, intensity='rich', entrance='burst'))
                        label.update_position(0)
                        geometry = label.geometry()
                        for phase in (0, .15, .5, .9, 1):
                            label.update_position(int(duration*phase))
                            image = image_of(label)
                            self.assertFalse(image.isNull())
                            self.assertEqual(label.text(), label.build_text(label.subtitles[0]))
                            self.assertEqual(label.geometry(), geometry)
                            self.assertLessEqual(effect.particles.last_draw_count, MAX_PARTICLES)
                            self.assertLessEqual(sum(len(row) for row in effect.particles.rows), MAX_REGIONS)
                            checked += 1
        self.assertEqual(checked, 6000)

    def test_word_morph_restores_text_and_never_makes_it_invisible(self):
        label = self.layer('word', options={'intensity': 'rich'})
        effect = label._subtitle_effects
        label.update_position(1500)
        image_of(label)
        regions = effect.particles.morph_regions(.5, 'shuriken', 'rich')
        self.assertEqual(len(regions), 1)
        self.assertGreaterEqual(regions[0][1], .35)
        self.assertEqual(effect.particles.morph_regions(1, 'shuriken', 'rich'), [])
        label.update_position(3000)
        image_of(label)
        self.assertEqual(effect.particles.last_draw_count, 0)
        self.assertFalse(label.isHidden())  # inclusive endpoint stays intact
        label.update_position(3001)
        self.assertTrue(label.isHidden())
        self.assertFalse(effect._particle_timer.isActive())

    def test_same_cue_reuses_layout_and_sprite_repeated_cue_still_sweeps(self):
        label = self.layer()
        effect = label._subtitle_effects
        label.load_subtitles([dict(start=0, end=2000, orig='word'),
                              dict(start=2001, end=4001, orig='word')])
        label.update_position(500)
        image_of(label)
        rows, sprite = effect.particles.rows, effect._sprite
        for position in range(550, 1800, 50):
            label.update_position(position)
            image_of(label)
            self.assertIs(effect.particles.rows, rows)
            self.assertIs(effect._sprite, sprite)
        label.update_position(2001)
        self.assertEqual(effect.scan_progress, 0)
        self.assertEqual(effect.cue[0], 1)
        label.update_position(3001)
        self.assertEqual(effect.scan_progress, .5)
        label.update_position(1000)  # reverse seek same text different cue
        self.assertEqual(effect.cue[0], 0)
        self.assertEqual(effect.scan_progress, .5)

    def test_timer_uses_media_clock_holds_stalls_and_handles_pause_rate_seek(self):
        label = self.layer()
        effect = label._subtitle_effects
        clock = MediaClock()
        self.addCleanup(clock.deleteLater)
        effect.bind_player(clock)
        label.update_position(0)
        self.assertTrue(effect._particle_timer.isActive())
        clock.position_ms = 1000
        effect._tick_particles()
        self.assertAlmostEqual(effect.scan_progress, 1/3, places=2)
        clock.state = QMediaPlayer.PlaybackState.PausedState
        clock.playbackStateChanged.emit(clock.state)
        self.assertFalse(effect._particle_timer.isActive())
        frozen = effect.scan_progress
        pump(50)
        self.assertEqual(effect.scan_progress, frozen)
        clock.state = QMediaPlayer.PlaybackState.PlayingState
        clock.playbackStateChanged.emit(clock.state)
        self.assertTrue(effect._particle_timer.isActive())
        clock.status = QMediaPlayer.MediaStatus.StalledMedia
        clock.mediaStatusChanged.emit(clock.status)
        self.assertFalse(effect._particle_timer.isActive())
        clock.status = QMediaPlayer.MediaStatus.BufferedMedia
        clock.mediaStatusChanged.emit(clock.status)
        self.assertTrue(effect._particle_timer.isActive())
        clock.rate = 2
        clock.playbackRateChanged.emit(clock.rate)
        clock.position_ms = 2300
        label.update_position(2300)
        self.assertAlmostEqual(effect.scan_progress, 2300/3000)
        clock.position_ms = 300
        label.update_position(300)
        self.assertAlmostEqual(effect.scan_progress, .1)
        clock.sourceChanged.emit('another source')
        self.assertFalse(effect._particle_timer.isActive())
        self.assertIsNone(effect.cue)
        self.assertEqual(effect.particles.rows, [])

    def test_preview_is_finite_and_hidden_off_empty_cancel_immediately(self):
        label = self.layer(duration=200)
        effect = label._subtitle_effects
        pump(250)
        self.assertFalse(effect._particle_timer.isActive())
        self.assertEqual(effect.scan_progress, 1)
        for action in (label.hide, lambda: effect.configure(None),
                       lambda: label.load_subtitles([]), lambda: label.set_mode(SubtitleMode.OFF)):
            label.set_mode(SubtitleMode.JP)
            label.load_subtitles([dict(start=0, end=3000, orig='word')])
            effect.configure(dict(enabled=True, trail='sparkles'))
            label.update_position(10)
            self.assertTrue(effect._particle_timer.isActive())
            action()
            self.assertFalse(effect._particle_timer.isActive())

    def test_very_short_cues_keep_full_text_without_particle_flash(self):
        for duration in (0, 1, 80, 159):
            label = self.layer('A', duration, options={'entrance': 'burst', 'intensity': 'rich'})
            effect = label._subtitle_effects
            label.update_position(duration // 2)
            image_of(label)
            self.assertFalse(effect._particle_timer.isActive())
            self.assertEqual(effect.particles.last_draw_count, 0)
            self.assertEqual(effect.particles.rows, [])
            self.assertFalse(label.isHidden())

    def test_empty_whitespace_and_one_pixel_widget_safe(self):
        label = self.layer()
        for text in ('', ' ', '\t', '\n', 'A'):
            label.setText(text)
            label.resize(1, 1)
            self.assertLessEqual(sum(len(row) for row in build_regions(label, 1)), 1)

    def test_new_options_validate_and_missing_keys_preserve_old_styles(self):
        for bad in ({}, None, [], 'particles'):
            self.assertEqual(normalize_options(bad)['trail'], 'none')
        options = normalize_options(dict(enabled=True, trail={}, intensity=100, duration=-10))
        self.assertEqual(options['trail'], 'none')
        self.assertEqual(options['intensity'], 'gentle')
        self.assertEqual(options['duration'], 160)


class ParticlePanelTests(unittest.TestCase):
    def test_presets_change_once_keep_master_and_round_trip_all_controls(self):
        panel = SubtitleEffectsPanel()
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.hide)
        panel.setChecked(True)
        spy = QSignalSpy(panel.changed)
        for index in range(1, len(PRESETS)):
            before = spy.count()
            panel.presets.setCurrentIndex(index)
            self.assertEqual(spy.count(), before+1)
            options = panel.options()
            self.assertTrue(options['enabled'])
            for key, value in PRESETS[index][2].items():
                self.assertEqual(options[key], value)
            panel.sync_options(options)
            self.assertEqual(panel.options(), options)
        panel.trail.setCurrentIndex(panel.trail.findData('none'))
        self.assertEqual(panel.presets.currentData(), 'custom')

    def test_saved_data_keys_and_popup_editor_guard_remain_original(self):
        with isolated_window() as (window, root):
            window.update_video_location('large')
            panel = window.subsettings_panel.effects_panel
            panel.setChecked(True)
            panel.presets.setCurrentIndex(1)
            saved = json.loads(Path(window.settings_file).read_text())
            self.assertEqual(saved['appearance']['subtitle_effects']['trail'], 'shuriken')
            layer = window.sub_layer
            layer.set_mode(SubtitleMode.JP)
            layer.set_fade_enabled(False)
            layer.load_subtitles([dict(start=0, end=3000, orig='one two')])
            effect = layer._subtitle_effects
            layer.update_position(500)
            dialog = QDialog(window)
            dialog.show()
            pump(10)
            self.assertTrue(layer.isHidden())
            self.assertFalse(effect._particle_timer.isActive())
            layer.update_position(1500)
            self.assertTrue(layer.isHidden())
            dialog.close()
            dialog.deleteLater()
            window._reset_defaults()
            self.assertFalse(panel.isChecked())
            self.assertFalse(effect._particle_timer.isActive())


class ParticleScopeTests(unittest.TestCase):
    def test_all_old_app_sources_and_previous_manifests_are_preserved(self):
        baseline = json.loads((ROOT/'docs/subtitle-particles/app-before-normalized.json').read_text())
        for relative, digest in baseline.items():
            current = before_particle_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(current.replace(b'\r\n', b'\n')).hexdigest(), digest, relative)
        helpers = json.loads((ROOT/'docs/subtitle-particles/helper-hash.json').read_text())
        for relative, digest in helpers.items():
            from tests.subtitle_sweep_contracts import before_sweep_changes
            self.assertEqual(hashlib.sha256(before_sweep_changes(relative, raw=True)).hexdigest(), digest)
        before = ast.parse(before_particle_changes('app/ui/subtitle_effects.py'))
        from tests.subtitle_sweep_contracts import before_sweep_changes
        after = ast.parse(before_sweep_changes('app/ui/subtitle_effects.py', raw=True))
        a, b = functions(before), functions(after)
        for name in ('install_subtitle_effects', 'SubtitleEffects._brush',
                     'SubtitleEffects._draw_static', 'SubtitleEffects._static_sprite',
                     'SubtitleEffects._frame', 'SubtitleEffects.settle'):
            self.assertEqual(a[name], b[name], name)


if __name__ == '__main__':
    unittest.main()
