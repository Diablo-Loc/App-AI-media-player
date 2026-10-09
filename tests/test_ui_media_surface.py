"""Mini surface ownership/first-frame refresh and truthful toggle colours."""
import ast
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.capture_ui_contracts import fingerprint
from tools.ui_preview import isolated_window, populate, pump, APPLICATION
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtTest import QTest, QSignalSpy

ROOT = Path(__file__).resolve().parents[1]


def solid_frame():
    image = QImage(64, 36, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#77E0BE"))
    return QVideoFrame(image)


class UiMediaSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = isolated_window()
        cls.window, cls.root = cls.context.__enter__()
        cls.items = populate(cls.window, cls.root)
        pump(250)

    @classmethod
    def tearDownClass(cls):
        from ui.media_card import MediaCard
        MediaCard.thread_pool.waitForDone(3000)
        cls.context.__exit__(None, None, None)

    def setUp(self):
        w = self.window
        w.content_stack.setCurrentIndex(0)
        w.showNormal()
        w.playback_bar.show()
        w.update_video_location("mini")
        w.sub_layer.hide()
        w.is_global_shuffle = False
        w.foryou_page.set_shuffle_visual(False)
        w.playback_bar.set_shuffle_visual(False)
        w.foryou_page.is_repeat = False
        pump(30)

    def assert_docked(self):
        w = self.window
        self.assertIs(w.video_display.parentWidget(), w.playback_bar.video_mini_placeholder)
        self.assertEqual(w.video_display.geometry(), w.playback_bar.video_mini_placeholder.rect())
        self.assertEqual(w.video_display.size().toTuple(), (140, 80))
        self.assertTrue(w.video_display.isVisible())

    def test_off_icons_keep_off_colour_even_in_active_hover_mode(self):
        from ui.icons import icon, TEXT, ACCENT
        for name in ("shuffle", "repeat", "volume-2", "maximize", "captions"):
            for color in (TEXT, ACCENT):
                with self.subTest(name=name, color=color):
                    normal = icon(name, color).pixmap(24, 24, QIcon.Mode.Normal).toImage()
                    hover = icon(name, color).pixmap(24, 24, QIcon.Mode.Active).toImage()
                    self.assertEqual(normal, hover)
        self.assertNotEqual(icon("shuffle", TEXT).pixmap(24, 24).toImage(),
                            icon("shuffle", ACCENT).pixmap(24, 24).toImage())

    def test_mouse_toggle_updates_both_shuffle_buttons_and_restores_order(self):
        from ui.icons import icon, TEXT, ACCENT
        w = self.window
        page = w.foryou_page
        original = list(page.original_data)
        # Keep For You inside the offscreen viewport, with its original widgets.
        w.content_stack.setCurrentIndex(1)
        # Its original showEvent maximizes. A maximized window cannot be moved
        # to expose a button on the tiny offscreen screen (400x400 at DPR 2).
        w.showNormal()
        w.resize(1000, 780)
        pump(60)
        for button in (page.btn_shuffle, w.playback_bar.btn_shuffle):
            for expected in (True, False):
                position = button.mapToGlobal(button.rect().center())
                center = APPLICATION.primaryScreen().availableGeometry().center()
                w.move(w.pos() + center - position)
                pump(15)
                position = button.mapToGlobal(button.rect().center())
                target = APPLICATION.widgetAt(position)
                self.assertIs(target, button)
                QTest.mouseMove(button, button.rect().center())
                QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFromGlobal(position))
                pump(20)
                self.assertEqual(w.is_global_shuffle, expected)
                self.assertEqual(page.is_shuffle, expected)
                expected_icon = icon("shuffle", ACCENT if expected else TEXT)
                for peer in (page.btn_shuffle, w.playback_bar.btn_shuffle):
                    self.assertEqual(peer.icon().pixmap(24, 24, QIcon.Mode.Active).toImage(),
                                     expected_icon.pixmap(24, 24, QIcon.Mode.Active).toImage())
                self.assertEqual(w.active_playlist, page.all_items_data)
                if not expected:
                    self.assertEqual(w.active_playlist, original)
                    self.assertTrue(all(a is b for a, b in zip(w.active_playlist, original)))

    def test_repeat_on_off_signal_and_hover_follow_original_boolean(self):
        from ui.icons import icon, TEXT, ACCENT
        page = self.window.foryou_page
        spy = QSignalSpy(page.repeat_toggled)
        before = list(page.all_items_data)
        for expected in (True, False):
            page.btn_repeat.click()
            self.assertEqual(page.is_repeat, expected)
            self.assertEqual(page.btn_repeat.icon().pixmap(24, 24, QIcon.Mode.Active).toImage(),
                             icon("repeat", ACCENT if expected else TEXT).pixmap(24, 24, QIcon.Mode.Active).toImage())
        self.assertEqual([spy.at(i)[0] for i in range(2)], [True, False])
        self.assertEqual(page.all_items_data, before)

    def test_delayed_for_you_layout_cannot_move_video_in_mini_or_large(self):
        w = self.window
        stage = w.foryou_page.video_container
        w.update_video_location("normal")
        stage.video_width, stage.video_height = 1280, 720
        stage.update_layout()
        self.assertTrue(stage._layout_timer.isActive())
        w.update_video_location("mini")
        pump(35)
        self.assert_docked()
        w.update_video_location("large")
        pump(30)
        before = w.video_display.geometry()
        margin = w.sub_layer._current_margin
        with patch.object(stage.video_widget, "setGeometry", wraps=stage.video_widget.setGeometry) as geometry:
            stage.update_layout_execution()
            self.assertEqual(geometry.call_count, 0)
        self.assertEqual(w.video_display.geometry(), before)
        self.assertEqual(w.sub_layer._current_margin, margin)
        w.update_video_location("mini")

    def test_live_for_you_stage_still_uses_original_aspect_layout(self):
        w = self.window
        w.update_video_location("normal")
        stage = w.foryou_page.video_container
        stage.video_width, stage.video_height = 1280, 720
        stage.update_layout_execution()
        scale = min(stage.width() / 1280, stage.height() / 720)
        # The layout can keep the original fixed limits until its next pass;
        # normal mode's existing implementation resets those limits first.
        self.assertEqual(w.video_display.width(), int(1280 * scale))
        self.assertEqual(w.video_display.height(), int(720 * scale))
        w.update_video_location("mini")

    def test_new_media_repairs_hidden_offset_surface_without_page_switch(self):
        w = self.window
        w.video_display.hide()
        w.video_display.move(25, 21)
        w.playback_bar.set_media_info("New track", "Artist", self.items[0])
        pump(25)
        self.assert_docked()
        self.assertEqual(w.content_stack.currentIndex(), 0)
        self.assertIs(w.playback_bar._current_item_data, self.items[0])

    def test_first_valid_frame_refreshes_once_and_never_steals_video(self):
        w = self.window
        dock = w.playback_bar.mini_video_dock
        sink = w.video_display.videoSink()
        dock.prepare_media()
        pump(20)
        with patch.object(dock, "refresh", wraps=dock.refresh) as refresh:
            sink.videoFrameChanged.emit(QVideoFrame())
            self.assertEqual(refresh.call_count, 0)
            frame = solid_frame()
            for _ in range(200):
                sink.videoFrameChanged.emit(frame)
            self.assertEqual(refresh.call_count, 1)
        self.assert_docked()
        w.update_video_location("large")
        pump(20)
        before = w.video_display.geometry()
        sink.videoFrameChanged.emit(solid_frame())
        self.assertIs(w.video_display.parentWidget(), w.video_container)
        self.assertEqual(w.video_display.geometry(), before)
        w.update_video_location("mini")

    def test_repeated_bind_does_not_duplicate_frame_listeners(self):
        w = self.window
        dock = w.playback_bar.mini_video_dock
        # Repeated binds must return before accessing/connecting to the sink.
        with patch.object(w.video_display, "videoSink", wraps=w.video_display.videoSink) as sink_access:
            for _ in range(100):
                dock.bind(w.video_display)
            self.assertEqual(sink_access.call_count, 0)
        self.assertEqual(len(dock.findChildren(QTimer)), 1)


class PresentationAdapterSourceGate(unittest.TestCase):
    def test_original_functions_remain_identical_after_removing_only_adapters(self):
        original = json.loads((ROOT / "docs/ui/original-contracts.json").read_text())
        cases = (
            ("app/ui/main_window.py", "MainWindow", "update_video_location", 2),
            ("app/ui/pages/for_you.py", "VideoStage", "update_layout_execution", 1),
            ("app/ui/playback_bar.py", "PlaybackBar", "set_media_info", 0),
        )
        for path, owner, name, prefix in cases:
            from tests.media_info_contracts import before_media_info_changes
            tree = ast.parse(before_media_info_changes(path))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
            method = copy.deepcopy(next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name))
            if prefix:
                method.body = method.body[prefix:]
            else:
                adapter = "self.mini_video_dock.prepare_media()"
                method.body = [node for node in method.body
                               if not (isinstance(node, ast.Expr) and ast.unparse(node.value) == adapter)]
            with self.subTest(path=path):
                self.assertEqual(fingerprint(method), original["files"][path]["methods"][f"{owner}.{name}"]["body"])


if __name__ == "__main__":
    unittest.main()
