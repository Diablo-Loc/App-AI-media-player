"""Real Qt geometry/text and original playlist/download behavior regression."""
import json
import unittest
from unittest.mock import patch

from tools.ui_preview import isolated_window, populate, pump
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QStyleOptionComboBox


class UiLayoutPolishTests(unittest.TestCase):
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

    def test_playlist_balances_index_thumbnail_and_metadata(self):
        from ui.elided_label import ElidedLabel
        from ui.pages.for_you import LazyThumb
        page = self.window.foryou_page
        self.window.content_stack.setCurrentIndex(1)
        pump()
        card = page.cards_map[self.items[0].id]
        index = next(label for label in card.findChildren(QLabel)
                     if not isinstance(label, (ElidedLabel, LazyThumb)))
        thumb = card.findChild(LazyThumb)
        labels = card.findChildren(ElidedLabel)
        self.assertLessEqual(index.width(), 18)
        self.assertEqual(thumb.size().toTuple(), (140, 78))
        self.assertEqual(thumb.cache_key,
                         f"lazy_rounded_{self.items[0].thumbnail}_140x78_{self.items[0].mtime}")
        for label in labels:
            self.assertGreaterEqual(label.width(), 170)
            self.assertTrue(card.rect().contains(label.mapTo(card, label.rect().bottomRight())))
        self.assertEqual(labels[0].text(), self.items[0].title)
        self.assertEqual(labels[1].text(), self.items[0].artist)

    def test_long_text_elides_without_losing_full_unicode_metadata(self):
        from ui.elided_label import ElidedLabel
        text = "🌟 Một bài hát rất dài của nghệ sĩ — 世界 " * 15
        for count in (1, 2):
            label = ElidedLabel(text, max_lines=count)
            try:
                label.setStyleSheet("font-size:13px; color:#A9F1D9;")
                label.resize(180, label.sizeHint().height())
                label.show()
                pump(20)
                lines = label.visible_lines()
                self.assertEqual(len(lines), count)
                self.assertTrue(lines[-1].endswith("…"))
                self.assertEqual(label.text(), text)
                self.assertEqual(label.toolTip(), text)
                for line in lines:
                    self.assertLessEqual(label.fontMetrics().horizontalAdvance(line), label.width())
                # A wider widget recomputes the layout rather than reusing old text.
                label.resize(240, label.height())
                self.assertNotEqual(label.visible_lines(), lines)
            finally:
                label.close()
                label.deleteLater()

    def test_playlist_click_order_and_highlight_remain_original(self):
        from ui.elided_label import ElidedLabel
        page = self.window.foryou_page
        self.window.content_stack.setCurrentIndex(1)
        self.assertEqual(page.all_items_data, self.items)
        spy = QSignalSpy(page.playlist_item_clicked)
        card = page.cards_map[self.items[1].id]
        with patch.object(self.window, "on_media_clicked") as playback:
            QTest.mouseClick(card, Qt.LeftButton, pos=QPoint(card.width() - 10, card.height() // 2))
            playback.assert_called_once_with(self.items[1])
        self.assertEqual(spy.count(), 1)
        self.assertIs(spy.at(0)[0], self.items[1])
        page.mark_playing_item(self.items[1].id)
        pump(20)
        title = next(label for label in card.findChildren(ElidedLabel) if label.property("is_title"))
        self.assertEqual(title.palette().color(QPalette.WindowText).name(), "#a9f1d9")
        page.mark_playing_item(self.items[0].id)
        pump(20)
        self.assertEqual(title.palette().color(QPalette.WindowText).name(), "#efefef")

    def test_download_combo_text_and_buttons_fit_in_popup(self):
        window = self.window
        window.content_stack.setCurrentIndex(3)
        menu = window.download_page.setting_menu
        menu.show()
        pump()
        self.assertGreaterEqual(menu.height(), menu.minimumSizeHint().height())
        for combo in (menu.format_combo, menu.quality_combo, menu.res_combo):
            option = QStyleOptionComboBox()
            combo.initStyleOption(option)
            text_rect = combo.style().subControlRect(QStyle.CC_ComboBox, option,
                                                     QStyle.SC_ComboBoxEditField, combo)
            self.assertGreaterEqual(text_rect.height(), combo.fontMetrics().height() + 4)
            for index in range(combo.count()):
                self.assertGreaterEqual(text_rect.width(),
                                        combo.fontMetrics().horizontalAdvance(combo.itemText(index)))
            self.assertTrue(menu.rect().contains(combo.mapTo(menu, combo.rect().bottomRight())))
        for button in menu.findChildren(QPushButton):
            self.assertTrue(menu.rect().contains(button.mapTo(menu, button.rect().bottomRight())))
        menu.hide()

    def test_download_options_and_saved_schema_stay_original(self):
        menu = self.window.download_page.setting_menu
        self.assertEqual([menu.format_combo.itemText(i) for i in range(menu.format_combo.count())],
                         ["Video MP4", "Video MKV", "Audio MP3"])
        self.assertEqual([menu.res_combo.itemText(i) for i in range(menu.res_combo.count())],
                         ["4K", "2K", "1080p", "720p"])
        for format_name in ("Video MKV", "Audio MP3", "Video MP4"):
            menu.format_combo.setCurrentText(format_name)
            self.assertEqual([menu.quality_combo.itemText(i) for i in range(menu.quality_combo.count())],
                             ["Original (Giữ nguồn)", "High (Opus)"] if format_name == "Video MKV" else menu.all_qualities)
        self.assertTrue(menu.auto_update_cb.isChecked())
        self.assertFalse(menu.auto_update_cb.isEnabled())
        menu.quality_combo.setCurrentText("Standard (M4A-ACC)")
        menu.res_combo.setCurrentText("2K")
        path = self.root / "layout-test-settings.json"
        page = self.window.download_page
        previous = page.settings_file
        page.settings_file = str(path)
        original = json.loads(json.dumps(menu.settings))
        try:
            spy = QSignalSpy(menu.settings_saved)
            menu.save_settings()
            self.assertEqual(spy.count(), 1)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["download"], dict(original.get("download", {}),
                quality="Standard (M4A-ACC)", format="Video MP4", resolution="2K", auto_update=True))
            self.assertEqual({k: v for k, v in saved.items() if k != "download"},
                             {k: v for k, v in original.items() if k != "download"})
        finally:
            page.settings_file = previous

    def test_hamburger_center_matches_rail_in_both_modes(self):
        window = self.window
        for expanded in (True, False, True):
            if getattr(window, "_nav_expanded", True) != expanded:
                window.toggle_nav_animation()
                pump(250)
            center = window.btn_menu.geometry().center().x()
            self.assertLessEqual(abs(center - window.sidebar_container.rect().center().x()), 1)
            image = window.btn_menu.grab().toImage()
            scale = image.devicePixelRatio()
            bright = [(x, y) for y in range(image.height()) for x in range(image.width())
                      if image.pixelColor(x, y).green() > 130]
            self.assertGreater(len(bright), 15)
            painted_center = (min(x for x, _ in bright) + max(x for x, _ in bright)) / (2 * scale)
            self.assertLessEqual(abs(painted_center - window.btn_menu.width() / 2), 1)


if __name__ == "__main__":
    unittest.main()
