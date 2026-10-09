"""Focused regression tests for readable inline subtitle-table editing."""
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QStyleOptionViewItem, QWidget

from ui.subs_ui.lyric_settings_dialog import SubtitleCellEditDelegate
from ui.subs_ui.subtitle_model import SubtitleTableModel
from tests.subtitle_editor_visibility_contracts import before_subtitle_editor_visibility_changes


ROOT = Path(__file__).resolve().parents[1]


class SubtitleCellEditDelegateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.model = SubtitleTableModel([{
            'start': 1.25,
            'end': 4.5,
            'text': '君の声が聞こえる',
            'en': 'I can hear your voice',
            'vi': 'Mình nghe thấy giọng của bạn',
        }])
        self.parent = QWidget()
        self.delegate = SubtitleCellEditDelegate(self.parent)

    def tearDown(self):
        self.parent.deleteLater()
        self.app.processEvents()

    def test_editor_keeps_full_unicode_text_visible_and_selected(self):
        index = self.model.index(0, 2)
        editor = self.delegate.createEditor(self.parent, QStyleOptionViewItem(), index)
        self.assertIsInstance(editor, QLineEdit)
        self.delegate.setEditorData(editor, index)

        self.assertEqual(editor.text(), '君の声が聞こえる')
        self.assertEqual(editor.selectedText(), '君の声が聞こえる')
        style = editor.styleSheet()
        self.assertIn('color: #EDF3FA', style)
        self.assertIn('background: #0D1118', style)
        self.assertIn('selection-color: #0D1118', style)
        self.assertIn('selection-background-color: #77E0BE', style)

    def test_editor_fits_inside_existing_compact_row(self):
        index = self.model.index(0, 3)
        option = QStyleOptionViewItem()
        option.rect = QRect(10, 20, 300, 36)
        editor = self.delegate.createEditor(self.parent, option, index)
        self.delegate.updateEditorGeometry(editor, option, index)
        self.assertEqual(editor.geometry(), QRect(11, 21, 298, 34))

    def test_commit_uses_existing_model_path(self):
        index = self.model.index(0, 4)
        editor = self.delegate.createEditor(self.parent, QStyleOptionViewItem(), index)
        editor.setText('Bản dịch đã sửa')
        self.delegate.setModelData(editor, self.model, index)
        self.assertEqual(self.model.data(index, Qt.DisplayRole), 'Bản dịch đã sửa')

    def test_time_columns_keep_center_alignment(self):
        index = self.model.index(0, 0)
        editor = self.delegate.createEditor(self.parent, QStyleOptionViewItem(), index)
        self.assertEqual(editor.alignment(), Qt.AlignCenter)


class SubtitleEditorVisibilityContractTests(unittest.TestCase):
    def test_exact_adapter_restores_pre_fix_dialog(self):
        relative = 'app/ui/subs_ui/lyric_settings_dialog.py'
        restored = before_subtitle_editor_visibility_changes(relative, raw=True)
        original = (ROOT / 'docs/subtitle-editor-visibility/original' / relative).read_bytes()
        self.assertEqual(restored, original)


if __name__ == '__main__':
    unittest.main()
