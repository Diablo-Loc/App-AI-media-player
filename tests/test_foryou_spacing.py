"""Measured Qt gutters and unchanged native window mechanics."""
import ast
import ctypes
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.ui_preview import isolated_window, populate, pump
from PySide6.QtCore import QPoint, Qt
from ui.design_system import apply_shell
from ui.native_frame_style import apply_caption_colors, colorref

ROOT = Path(__file__).resolve().parents[1]


class ForYouSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = isolated_window()
        cls.window, cls.root = cls.context.__enter__()
        populate(cls.window, cls.root)
        cls.window.showMaximized = lambda: None

    def setUp(self):
        self.window.showNormal()
        self.window.resize(1280, 820)
        self.page = self.window.foryou_page
        self.window.sidebar.setCurrentRow(1)
        self.window.handle_sidebar_click(self.window.sidebar.item(1))
        pump(120)

    @classmethod
    def tearDownClass(cls):
        from ui.media_card import MediaCard
        from ui.playlist_thumbnail_queue import thumbnail_queue
        MediaCard.thread_pool.waitForDone(3000)
        thumbnail_queue().pool.waitForDone(3000)
        cls.context.__exit__(None, None, None)

    def test_search_top_bottom_and_horizontal_center_are_balanced(self):
        for width in (1920, 1280, 900):
            self.window.resize(width, 820)
            pump(70)
            search = self.page.search_input
            header = self.page.header_container
            origin = search.mapTo(header, QPoint(0, 0))
            self.assertEqual(origin.y(), 12)
            self.assertEqual(header.height() - origin.y() - search.height(), 12)
            self.assertLessEqual(abs(origin.x() + search.width() / 2 - header.width() / 2), 1)

    def test_outer_gutters_and_column_gap_are_twelve_at_multiple_sizes(self):
        for width, height in ((1920, 1080), (1280, 820), (900, 620)):
            self.window.resize(width, height)
            pump(70)
            p = self.page
            body = p.body_container
            left, playlist = p.left_scroll_area.geometry(), p.playlist_container.geometry()
            self.assertEqual((left.x(), left.y()), (12, 12))
            self.assertEqual(body.width() - playlist.right() - 1, 12)
            self.assertEqual(body.height() - playlist.bottom() - 1, 12)
            self.assertEqual(body.height() - left.bottom() - 1, 12)
            self.assertEqual(playlist.x() - left.right() - 1, 12)
            self.assertEqual(p.video_container.mapTo(p, QPoint(0, 0)).x(), 12)
            wrapper = self.window.grid_main_page.layout().contentsMargins()
            self.assertEqual((wrapper.left(), wrapper.top(), wrapper.right(), wrapper.bottom()), (0, 0, 0, 0))
            self.assertEqual(self.window.browser_layout.spacing(), 0)

    def test_other_page_margins_are_restored_and_reapplying_theme_is_idempotent(self):
        w = self.window
        owner = w._for_you_spacing
        frame = w._native_frame_style
        for index in (0, 2, 3, 4, 1, 0, 1):
            w.content_stack.setCurrentIndex(index)
            pump(20)
            margins = w.grid_main_page.layout().contentsMargins()
            actual = (margins.left(), margins.top(), margins.right(), margins.bottom())
            self.assertEqual(actual, (0, 0, 0, 0) if index == 1 else (20, 18, 20, 16))
        apply_shell(w)
        self.assertIs(w._for_you_spacing, owner)
        self.assertIs(w._native_frame_style, frame)

    def test_style_observer_never_changes_flags_geometry_or_native_video_owners(self):
        w = self.window
        flags, geometry = w.windowFlags(), w.geometry()
        video_parent, subtitle_parent = w.video_display.parentWidget(), w.sub_layer.parentWidget()
        with patch('ui.native_frame_style.QGuiApplication.platformName', return_value='windows'), \
                patch('ui.native_frame_style.apply_caption_colors', return_value={35: 0}) as setter:
            w._native_frame_style.apply()
            setter.assert_called_once()
            self.assertEqual(w.windowFlags(), flags)
            self.assertEqual(w.geometry(), geometry)
            self.assertIs(w.video_display.parentWidget(), video_parent)
            self.assertIs(w.sub_layer.parentWidget(), subtitle_parent)
            w.showFullScreen()
            pump(20)
            setter.reset_mock()
            w._native_frame_style.apply()
            setter.assert_not_called()
            w.showNormal()
            pump(20)
            w._native_frame_style.timer.stop()
            setter.reset_mock()
            w._native_frame_style.apply()
            setter.assert_called_once()


class FrameColorTests(unittest.TestCase):
    def test_native_attribute_values_are_correct_and_hwnd_is_pointer_sized(self):
        calls = []
        def setter(hwnd, attribute, pointer, size):
            calls.append((hwnd.value, attribute, ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value, size))
            return 0
        hwnd = 0x123456789
        with patch('ui.native_frame_style._dwm_setter', return_value=setter):
            result = apply_caption_colors(hwnd, '#0D1118', '#EDF3FA', '#273445')
        self.assertEqual(result, {20: 0, 35: 0, 36: 0, 34: 0})
        self.assertEqual(calls, [(hwnd, 20, 1, 4), (hwnd, 35, 0x18110D, 4),
                                 (hwnd, 36, 0xFAF3ED, 4), (hwnd, 34, 0x453427, 4)])
        self.assertEqual(colorref('#FFFFFF'), 0xFFFFFF)

    def test_unavailable_or_unsupported_dwm_does_not_break_startup(self):
        with patch('ui.native_frame_style._dwm_setter', return_value=None):
            self.assertEqual(apply_caption_colors(1, '#0D1118', '#EDF3FA', '#273445'), {})
        with patch('ui.native_frame_style._dwm_setter', return_value=lambda *args: -2147024809):
            self.assertTrue(all(value < 0 for value in apply_caption_colors(1, '#0D1118', '#EDF3FA', '#273445').values()))
        with patch('ui.native_frame_style._dwm_setter', side_effect=None, return_value=lambda *args: (_ for _ in ()).throw(OSError('unavailable'))):
            self.assertEqual(apply_caption_colors(1, '#0D1118', '#EDF3FA', '#273445'), {20: -1, 35: -1, 36: -1, 34: -1})

    def test_only_for_you_presentation_and_shell_installs_change_captured_sources(self):
        def tree(path):
            return ast.parse(path.read_text(encoding='utf-8-sig'))
        old = tree(ROOT / 'docs/foryou-spacing/original/for_you.py')
        new = tree(ROOT / 'app/ui/pages/for_you.py')
        helpers = [node for node in new.body if isinstance(node, ast.ImportFrom) and node.module == 'foryou_spacing']
        self.assertEqual(len(helpers), 1)
        self.assertEqual(ast.dump(helpers[0]), ast.dump(ast.parse('from ..foryou_spacing import PAGE_GUTTER').body[0]))
        new.body.remove(helpers[0])
        old_class = next(node for node in old.body if isinstance(node, ast.ClassDef) and node.name == 'ForYouPage')
        new_class = next(node for node in new.body if isinstance(node, ast.ClassDef) and node.name == 'ForYouPage')
        old_init = next(node for node in old_class.body if isinstance(node, ast.FunctionDef) and node.name == 'init_ui')
        for i, node in enumerate(new_class.body):
            if isinstance(node, ast.FunctionDef) and node.name == 'init_ui':
                new_class.body[i] = old_init
        self.assertEqual(ast.dump(new), ast.dump(old))
        old = tree(ROOT / 'docs/foryou-spacing/original/design_system.py')
        new = tree(ROOT / 'app/ui/design_system.py')
        body = next(node for node in new.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_shell').body
        adapter = ast.parse('from .foryou_spacing import install_for_you_spacing\nfrom .native_frame_style import install_native_frame\ninstall_for_you_spacing(window)\ninstall_native_frame(window, BACKGROUND, TEXT, BORDER)').body
        self.assertEqual([ast.dump(node) for node in body[-4:]], [ast.dump(node) for node in adapter])
        del body[-4:]
        self.assertEqual(ast.dump(new), ast.dump(old))
        from tests.reliability_contracts import before_reliability_changes
        self.assertEqual(hashlib.sha256(before_reliability_changes('app/ui/main_window.py', raw=True)).hexdigest(),
                         '89b6a2fe45e9ed825e84e815799e4dea4ecf42ca9e085c4db054bd3e599f0d6b')
