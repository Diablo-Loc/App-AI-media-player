"""Rendered icons, real mouse dispatch, compact layouts and animation ownership."""
import unittest
from unittest.mock import patch

from tools.ui_preview import isolated_window, populate, pump, APPLICATION
from PySide6.QtCore import QPoint, QRect, Qt, QParallelAnimationGroup
from PySide6.QtTest import QTest, QSignalSpy


BUTTONS = ("btn_shuffle", "btn_prev", "btn_play", "btn_next", "btn_repeat",
           "btn_info", "btn_subseting", "btn_sub", "btn_reload", "btn_vol",
           "btn_dynamic_island", "btn_fs")


class UiStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = isolated_window()
        cls.window, cls.root = cls.context.__enter__()
        cls.items = populate(cls.window, cls.root)
        pump(300)

    @classmethod
    def tearDownClass(cls):
        from ui.media_card import MediaCard
        MediaCard.thread_pool.waitForDone(3000)
        cls.context.__exit__(None, None, None)

    def setUp(self):
        w = self.window
        w.vol_popup.hide()
        w.subsettings_panel.hide()
        w.playback_bar.info_popup.hide()
        w.sub_layer.hide()
        w.showNormal()
        w.playback_bar.show()
        w.content_stack.setCurrentIndex(0)
        w.update_video_location("mini")
        w.move(0, 0)
        w.resize(1280, 820)
        if not getattr(w, "_nav_expanded", True):
            w.toggle_nav_animation()
        pump(250)

    def place_volume_on_screen(self):
        w = self.window
        button = w.playback_bar.btn_vol
        position = button.mapToGlobal(button.rect().center())
        # The offscreen screen is 800x800. Real mouse lookup must be on-screen.
        w.move(w.pos() + QPoint(350, 350) - position)
        pump(20)
        return button.mapToGlobal(button.rect().center())

    def test_collapsed_sidebar_paints_every_icon(self):
        w = self.window
        w.toggle_nav_animation()
        pump(250)
        self.assertEqual(w.sidebar_container.width(), 70)
        image = w.sidebar.viewport().grab().toImage()
        scale = image.devicePixelRatio()
        for index in range(w.sidebar.count()):
            with self.subTest(index=index):
                center = w.sidebar.visualItemRect(w.sidebar.item(index)).center()
                area = QRect(center.x() - 11, center.y() - 11, 22, 22)
                bright = sum(
                    image.pixelColor(int(x * scale), int(y * scale)).green() > 130
                    for x in range(area.left(), area.right() + 1)
                    for y in range(area.top(), area.bottom() + 1)
                )
                self.assertGreater(bright, 15, "non-null QIcon alone does not prove it is painted")

    def test_rapid_sidebar_reversals_use_one_owned_group(self):
        w = self.window
        w.toggle_nav_animation()
        pump(35)
        group = w.anim_group
        for i in range(49):
            w.toggle_nav_animation()
            if i % 7 == 0:
                pump(8)
            self.assertIs(w.anim_group, group)
            self.assertEqual(w.anim_menu.easingCurve(), w.anim_menu_max.easingCurve())
        pump(250)
        self.assertEqual(w.sidebar_container.width(), 160)
        self.assertEqual(w.sidebar_container.minimumWidth(), 160)
        self.assertEqual(w.sidebar_container.maximumWidth(), 160)
        self.assertEqual(len(w.findChildren(QParallelAnimationGroup)), 1)
        self.assertEqual(group.animationCount(), 2)

    def test_resizing_preserves_all_control_targets_and_video_parent(self):
        w = self.window
        bar = w.playback_bar
        w.toggle_nav_animation()
        pump(250)
        parent = w.video_display.parent()
        for width in (1280, 1000, 990, 900, 820, 760, 990, 1280):
            w.resize(width, 820)
            pump(230)
            with self.subTest(width=width):
                self.assertEqual(w.width(), width)
                self.assertEqual(bar.height(), 110)
                self.assertEqual(bar._compact_layout, width < 1000)
                if width >= 1280:
                    self.assertGreaterEqual(bar.info_area.width(), 280)
                rectangles = []
                for name in BUTTONS:
                    button = getattr(bar, name)
                    rect = QRect(button.mapTo(bar, QPoint()), button.size())
                    self.assertTrue(button.isVisible(), name)
                    self.assertTrue(bar.rect().contains(rect), name)
                    self.assertIs(bar.childAt(rect.center()), button, name)
                    for other in rectangles:
                        self.assertFalse(rect.intersects(other), name)
                    rectangles.append(rect)
                self.assertGreaterEqual(bar.time_slider.width(), 80)
                self.assertEqual(bar.video_mini_placeholder.size().toTuple(), (140, 80))
                self.assertIs(w.video_display.parent(), parent)

    def test_volume_receives_real_mouse_click_in_each_layout(self):
        w = self.window
        for width in (1280, 900, 780):
            w.toggle_nav_animation() if getattr(w, "_nav_expanded", True) else None
            w.resize(width, 820)
            pump(250)
            point = self.place_volume_on_screen()
            target = APPLICATION.widgetAt(point)
            with self.subTest(width=width):
                self.assertIs(target, w.playback_bar.btn_vol)
                spy = QSignalSpy(w.playback_bar.btn_vol.clicked)
                QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFromGlobal(point))
                pump(20)
                self.assertEqual(spy.count(), 1)
                self.assertTrue(w.vol_popup.isVisible())
                self.assertEqual(w.vol_popup.slider.value(), int(w.audio_output.volume() * 100))
            w.vol_popup.hide()

    def test_floating_subtitle_cannot_swallow_volume_click(self):
        w = self.window
        w.update_video_location("large")
        pump(30)
        point = self.place_volume_on_screen()
        sub = w.sub_layer
        sub.set_locked(False)
        # Preserve production focus handling. Only emulate an active main window
        # in offscreen, which otherwise deactivates it when a Tool window opens.
        with patch.object(w, "isActiveWindow", return_value=True):
            sub.setGeometry(QRect(point.x() - 60, point.y() - 30, 120, 60))
            sub.show()
            sub.raise_()
            pump(30)
            self.assertFalse(sub.mask().contains(sub.mapFromGlobal(point)))
            target = APPLICATION.widgetAt(point)
            self.assertIsNotNone(target)
            spy = QSignalSpy(w.playback_bar.btn_vol.clicked)
            QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFromGlobal(point))
            pump(20)
            self.assertEqual(spy.count(), 1)
            self.assertTrue(w.vol_popup.isVisible())
            self.assertFalse(sub.is_locked)
            self.assertFalse(sub.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_guard_preserves_subtitle_drag_outside_controls(self):
        w = self.window
        w.update_video_location("large")
        pump(30)
        self.place_volume_on_screen()
        sub = w.sub_layer
        sub.set_locked(False)
        with patch.object(w, "isActiveWindow", return_value=True):
            video_point = w.video_display.mapToGlobal(QPoint(150, 150))
            sub.setGeometry(QRect(video_point, sub.size()))
            sub.show()
            pump(20)
            self.assertTrue(sub.mask().isEmpty())
            QTest.mousePress(sub, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
            self.assertIsNotNone(sub._drag_offset)
            self.assertIsNone(w._overlay_input_guard._mouse_target)
            QTest.mouseRelease(sub, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))

    def test_controls_remain_visible_during_popup_seek_and_button_press(self):
        w = self.window
        with patch.object(w.playback_bar, "underMouse", return_value=False):
            for popup in (w.vol_popup, w.subsettings_panel, w.playback_bar.info_popup):
                popup.show()
                pump(10)
                w.hide_controls()
                self.assertTrue(w.playback_bar.isVisible())
                popup.hide()
            w.playback_bar.time_slider.setSliderDown(True)
            w.hide_controls()
            self.assertTrue(w.playback_bar.isVisible())
            w.playback_bar.time_slider.setSliderDown(False)
            w.playback_bar.btn_play.setDown(True)
            w.hide_controls()
            self.assertTrue(w.playback_bar.isVisible())
            w.playback_bar.btn_play.setDown(False)
            w.hide_controls()
            self.assertTrue(w.playback_bar.isHidden())
            w.show_controls()
            self.assertTrue(w.playback_bar.isVisible())

    def test_guard_does_not_reapply_identical_native_masks(self):
        guard = self.window._overlay_input_guard
        guard.refresh()
        with patch.object(guard.overlay, "setMask", wraps=guard.overlay.setMask) as set_mask:
            for _ in range(200):
                guard.refresh()
            self.assertEqual(set_mask.call_count, 0)

    def test_download_compact_controls_remain_within_page(self):
        w = self.window
        w.toggle_nav_animation()
        pump(250)
        w.content_stack.setCurrentIndex(3)
        page = w.download_page
        for width in (1280, 820, 760):
            w.resize(width, 820)
            pump(250)
            for name in ("btn_settings", "btn_toggle_path", "combo_path", "btn_browse",
                         "btn_get_name", "btn_start", "btn_stop", "btn_clear", "btn_refresh_all",
                         "txt_links", "txt_names", "progress_bar", "fail_bar"):
                with self.subTest(width=width, name=name):
                    widget = getattr(page, name)
                    rect = QRect(widget.mapTo(page, QPoint()), widget.size())
                    self.assertTrue(widget.isVisible())
                    self.assertTrue(page.rect().contains(rect))
            self.assertEqual(page.progress_bar.format(), "--/--")
            self.assertEqual(page.fail_bar.format(), "--/--")

    def test_metadata_elision_retains_original_html_and_full_tooltip(self):
        title = "A very long title " * 10
        artist = "A very long artist name"
        bar = self.window.playback_bar
        bar.set_media_info(title, artist)
        self.assertIn(title[:37] + "...", bar.lbl_song_info.text())
        self.assertEqual(bar.lbl_song_info._lines, [title[:37] + "...", artist])
        self.assertIn(title, bar.lbl_song_info.toolTip())
        self.assertEqual(bar.lbl_song_info._lines[1], artist)


if __name__ == "__main__":
    unittest.main()
