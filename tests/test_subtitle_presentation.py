"""Qt regressions for dialog visibility and interrupted lyric fades."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.ui_preview import APPLICATION, isolated_window, pump
# Keep Qt modules resident across isolated_window's sys.modules fixtures.
from ui.main_window import MainWindow
from ui.subs_ui.subtitle_layer import SubtitleLayer
from subtitle.mode import SubtitleMode
from PySide6.QtCore import QAbstractAnimation, QPoint, QTimer
from PySide6.QtWidgets import QDialog, QWidget, QVBoxLayout

from tests.subtitle_presentation_contracts import before_presentation_changes
from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]
CUES = [dict(start=0, end=500, orig='First line'),
        dict(start=800, end=2000, orig='Second line')]


class FadeTests(unittest.TestCase):
    def make_layer(self, cls=SubtitleLayer):
        layer = cls(initial_mode=SubtitleMode.JP)
        layer.load_subtitles(CUES)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        return layer

    def test_repeated_gap_updates_do_not_restart_fade_out(self):
        layer = self.make_layer()
        layer.update_position(100)
        layer.fade_anim.setCurrentTime(220)
        layer.update_position(550)
        layer.fade_anim.setCurrentTime(100)
        opacity = layer.get_opacity()
        for position in range(551, 600):
            layer.update_position(position)
            self.assertEqual(layer.fade_anim.currentTime(), 100)
            self.assertEqual(layer.get_opacity(), opacity)
        layer.fade_anim.setCurrentTime(220)
        self.assertTrue(layer.isHidden())

    def test_canceled_hide_callback_never_hides_next_fade_in(self):
        layer = self.make_layer()
        layer.load_subtitles([CUES[0], dict(start=1000, end=2000, orig='Second line')])
        layer.update_position(100)
        layer.fade_anim.setCurrentTime(220)
        for _ in range(20):
            layer.update_position(550)
            layer.fade_anim.setCurrentTime(50)
            layer.hide()  # A dialog/window transition interrupts the old fade.
            layer.update_position(1200)
            layer.fade_anim.setCurrentTime(220)
            pump(5)
            self.assertFalse(layer.isHidden())
            self.assertEqual(layer.get_opacity(), 1.0)
            self.assertEqual(layer.text(), 'Second line')

    def test_old_snapshot_reproduces_restart_and_stale_callback(self):
        namespace = {'__name__': 'captured_subtitle_layer'}
        source = before_presentation_changes('app/ui/subs_ui/subtitle_layer.py')
        exec(compile(source, 'captured_subtitle_layer.py', 'exec'), namespace)
        old = self.make_layer(namespace['SubtitleLayer'])
        old.load_subtitles([CUES[0], dict(start=1000, end=2000, orig='Second line')])
        old.update_position(100)
        old.fade_anim.setCurrentTime(220)
        old.update_position(550)
        old.fade_anim.setCurrentTime(100)
        old.update_position(600)
        self.assertEqual(old.fade_anim.currentTime(), 0)
        old.hide()
        old.update_position(1200)
        old.fade_anim.setCurrentTime(220)
        pump(5)
        self.assertTrue(old.isHidden(), 'Old hide callback fires at new fade-in completion')

    def test_seek_back_into_same_cue_reverses_fade_without_opacity_reset(self):
        layer = self.make_layer()
        layer.update_position(900)
        layer.fade_anim.setCurrentTime(220)
        layer.update_position(2100)
        layer.fade_anim.setCurrentTime(100)
        opacity = layer.get_opacity()
        layer.update_position(1500)
        self.assertEqual(layer.get_opacity(), opacity)
        self.assertEqual(layer.fade_anim.endValue(), 1.0)
        layer.fade_anim.setCurrentTime(220)
        self.assertFalse(layer.isHidden())

    def test_fade_in_opacity_is_monotonic_and_geometry_stays_stable(self):
        layer = self.make_layer()
        layer.update_position(0)
        geometry = layer.geometry()
        samples = []
        for offset in range(0, 221, 20):
            layer.fade_anim.setCurrentTime(offset)
            layer.update_position(offset)
            samples.append(layer.get_opacity())
            self.assertEqual(layer.geometry(), geometry)
            self.assertFalse(layer.isHidden())
        self.assertEqual(samples, sorted(samples))
        self.assertEqual(samples[0], 0.0)
        self.assertEqual(samples[-1], 1.0)

    def test_inclusive_endpoints_gaps_fade_setting_and_source_timing_stay_intact(self):
        layer = self.make_layer()
        layer.set_fade_enabled(False)
        self.assertEqual(layer.fade_anim.duration(), 220)
        for position, text in ((0, 'First line'), (500, 'First line'), (501, None),
                               (799, None), (800, 'Second line'), (2000, 'Second line'), (2001, None)):
            layer.update_position(position)
            self.assertEqual(layer.isHidden(), text is None)
            if text is not None:
                self.assertEqual(layer.text(), text)
                self.assertEqual(layer.get_opacity(), 1.0)
        self.assertEqual([(cue['start'], cue['end']) for cue in layer.subtitles], [(0, 500), (800, 2000)])


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.owner.video_mode = 'normal'
        self.owner.is_mini_mode = False
        self.owner.video_display = QWidget(self.owner)
        QVBoxLayout(self.owner).addWidget(self.owner.video_display)
        self.layer = SubtitleLayer(initial_mode=SubtitleMode.JP, parent=self.owner)
        self.layer.set_fade_enabled(False)
        self.layer.load_subtitles(CUES)
        self.owner.show()
        self.active = patch.object(self.owner, 'isActiveWindow', return_value=True)
        self.active.start()
        self.addCleanup(self.active.stop)
        self.addCleanup(self.owner.deleteLater)
        self.addCleanup(self.owner.close)
        self.layer.update_position(100)
        pump(20)
        self.assertFalse(self.layer.isHidden())

    def make_dialog(self, modal):
        dialog = QDialog(self.owner)
        dialog.setModal(modal)
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.close)
        return dialog

    def test_modal_editor_blocks_ticks_direct_show_and_setvisible(self):
        dialog = self.make_dialog(True)
        dialog.show()
        pump(20)
        for position in (100, 500, 900, 1000):
            self.layer.update_position(position)
            self.layer.show()
            self.layer.setVisible(True)
            self.assertTrue(self.layer.isHidden())
        self.assertEqual(self.layer._current_ms_cache, 1000)
        dialog.close()
        pump(30)
        self.assertFalse(self.layer.isHidden())
        self.assertEqual(self.layer.text(), 'Second line')

    def test_video_cue_end_keeps_220ms_fade_while_dialog_suppression_is_instant(self):
        self.layer.set_fade_enabled(True)
        self.layer.update_position(900)
        self.layer.update_position(2100)
        self.assertEqual(self.layer.fade_anim.state(), QAbstractAnimation.State.Running)
        self.assertEqual(self.layer.fade_anim.endValue(), 0.0)
        self.layer.fade_anim.setCurrentTime(100)
        self.layer.update_position(2200)
        self.assertFalse(self.layer.isHidden())
        self.assertEqual(self.layer.fade_anim.currentTime(), 100)
        self.layer.fade_anim.setCurrentTime(220)
        self.assertTrue(self.layer.isHidden())
        self.layer.update_position(100)
        dialog = self.make_dialog(True)
        dialog.show()
        self.assertTrue(self.layer.isHidden())
        self.assertEqual(self.layer.fade_anim.state(), QAbstractAnimation.State.Stopped)

    def test_modeless_editor_also_blocks_and_paused_cue_restores(self):
        dialog = self.make_dialog(False)
        dialog.show()
        pump(20)
        self.assertTrue(self.layer.isHidden())
        dialog.close()
        pump(30)
        self.assertFalse(self.layer.isHidden())
        self.assertEqual(self.layer.text(), 'First line')

    def test_closing_editor_in_gap_never_resurrects_old_text(self):
        dialog = self.make_dialog(True)
        dialog.show()
        pump(20)
        self.layer.update_position(650)
        dialog.close()
        pump(30)
        self.layer.show()
        self.assertTrue(self.layer.isHidden())

    def test_video_hidden_or_detached_blocks_and_restores_latest_cue(self):
        video = self.owner.video_display
        video.hide()
        pump(20)
        self.layer.update_position(900)
        self.assertTrue(self.layer.isHidden())
        video.show()
        pump(20)
        self.assertFalse(self.layer.isHidden())
        self.assertEqual(self.layer.text(), 'Second line')
        video.setParent(None)
        video.show()
        self.layer.update_position(1000)
        self.assertTrue(self.layer.isHidden())
        video.setParent(self.owner)
        self.owner.layout().addWidget(video)
        video.show()
        pump(20)
        self.assertFalse(self.layer.isHidden())

    def test_mini_minimized_inactive_and_mode_off_never_show(self):
        guard = self.layer._presentation_guard
        self.owner.video_mode = 'mini'
        self.layer.show()
        self.assertTrue(self.layer.isHidden())
        self.owner.video_mode = 'normal'
        self.owner.is_mini_mode = True
        self.layer.update_position(900)
        self.assertTrue(self.layer.isHidden())
        self.owner.is_mini_mode = False
        self.owner.showMinimized()
        pump(20)
        self.layer.show()
        self.assertTrue(self.layer.isHidden())
        self.owner.showNormal()
        pump(20)
        self.layer.set_mode(SubtitleMode.OFF)
        self.layer.update_position(900)
        self.layer.show()
        self.assertTrue(self.layer.isHidden())
        self.layer.mode = SubtitleMode.JP
        self.active.stop()
        with patch.object(self.owner, 'isActiveWindow', return_value=False), \
                patch.object(APPLICATION, 'activeWindow', return_value=None):
            guard.refresh()
            self.assertTrue(self.layer.isHidden())

    def test_nested_dialog_hidden_owner_empty_cues_and_shutdown(self):
        first = self.make_dialog(True)
        second = QDialog(first)
        self.addCleanup(second.deleteLater)
        self.addCleanup(second.close)
        first.show()
        second.show()
        pump(20)
        second.close()
        pump(20)
        self.assertTrue(self.layer.isHidden())
        first.close()
        pump(20)
        self.assertFalse(self.layer.isHidden())
        self.owner.hide()
        pump(20)
        self.layer.show()
        self.assertTrue(self.layer.isHidden())
        self.owner.show()
        self.layer.load_subtitles([])
        self.layer.update_position(100)
        self.layer.show()
        self.assertTrue(self.layer.isHidden())
        guard = self.layer._presentation_guard
        guard.schedule_refresh()
        guard.shutdown()
        self.assertFalse(guard._refresh_timer.isActive())


class ShellIntegrationTests(unittest.TestCase):
    def test_detached_foryou_cue_is_placed_before_fade_and_does_not_jump(self):
        with isolated_window() as (window, root):
            window.content_stack.setCurrentIndex(1)
            window.update_video_location('normal')
            sub = window.sub_layer
            sub.mode = SubtitleMode.JP
            sub.load_subtitles([dict(start=0, end=5000, orig='A balanced line in the video')])
            with patch.object(window, 'isActiveWindow', return_value=True):
                pump(60)
                sub.update_position(100)
                geometry = sub.geometry()
                video = window.video_display
                origin = video.mapToGlobal(QPoint())
                self.assertIsNone(sub.parentWidget())
                self.assertEqual(geometry.left(), origin.x())
                self.assertEqual(geometry.width(), video.width())
                self.assertEqual(geometry.y() + geometry.height(), origin.y() + video.height() - 10)
                for offset in range(20, 221, 20):
                    sub.fade_anim.setCurrentTime(offset)
                    sub.update_position(100 + offset)
                    window.foryou_page.video_container.update_layout_execution()
                    self.assertEqual(sub.geometry(), geometry)
                    self.assertFalse(sub.isHidden())

    def test_existing_editor_exec_suppresses_overlay_and_keeps_video_owner(self):
        with isolated_window() as (window, root):
            window.update_video_location('large')
            window.app_controller = SimpleNamespace(current_media_item=SimpleNamespace(id='fixture'),
                                                    stop_thumbnail_scan=lambda: None)
            sub = window.sub_layer
            sub.mode = SubtitleMode.JP
            sub.set_fade_enabled(False)
            sub.load_subtitles(CUES)
            sub.update_position(100)
            video_parent, flags = window.video_display.parent(), sub.windowFlags()
            checked = []

            def factory(parent):
                dialog = QDialog(parent)
                dialog.load_from_media_file = lambda media_id: True

                def while_open():
                    sub.update_position(900)
                    sub.show()
                    checked.append(sub.isHidden())
                    dialog.accept()

                QTimer.singleShot(20, while_open)
                return dialog

            with patch.object(window, 'isActiveWindow', return_value=True), \
                    patch('ui.main_window.SubtitleToolsDialog', side_effect=factory):
                window.open_subtitle_tools_dialog()
                pump(30)
                self.assertEqual(checked, [True])
                self.assertFalse(sub.isHidden())
                self.assertEqual(sub.text(), 'Second line')
                self.assertIs(window.video_display.parent(), video_parent)
                self.assertEqual(sub.windowFlags(), flags)


class SourceScopeTests(unittest.TestCase):
    def test_only_reviewed_rendering_methods_change_and_old_gates_keep_snapshots(self):
        manifest = json.loads((ROOT / 'docs/subtitle-presentation/reviewed-sources.json').read_text())
        expected = {
            'app/ui/main_window.py': {'MainWindow.changeEvent'},
            'app/ui/subs_ui/subtitle_layer.py': {'SubtitleLayer.__init__', 'SubtitleLayer.update_position',
                                               'SubtitleLayer._smart_show', 'SubtitleLayer._smart_hide'},
        }
        self.assertEqual(set(manifest), set(expected))
        for relative, names in expected.items():
            old = before_presentation_changes(relative)
            from tests.audio_effects_contracts import before_audio_changes
            new = before_audio_changes(relative)
            before, after = functions(old), functions(new)
            self.assertEqual({name for name in before if before[name] != after.get(name)}, names)
            self.assertEqual(manifest[relative]['changed_functions'], [name for name in before if name in names])
            before_tree, after_tree = ast.parse(old), ast.parse(new)
            for tree in (before_tree, after_tree):
                tree.body = [node for node in tree.body if not (isinstance(node, ast.ImportFrom)
                             and node.module == 'app.ui.subtitle_presentation')]
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        node.body = [item for item in node.body if not isinstance(item, ast.FunctionDef)
                                     or (node.name + '.' + item.name not in names
                                         and node.name + '.' + item.name in before)]
            self.assertEqual(ast.dump(before_tree), ast.dump(after_tree))
        helpers = json.loads((ROOT / 'docs/subtitle-presentation/helper-hash.json').read_text())
        for relative, expected_hash in helpers.items():
            self.assertEqual(hashlib.sha256(before_audio_changes(relative, raw=True)).hexdigest(), expected_hash)


if __name__ == '__main__':
    unittest.main()
