"""Read actual Windows caption attributes on an isolated app; no user media."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

os.environ['QT_QPA_PLATFORM'] = 'windows'
from tools.ui_preview import isolated_window, populate, pump
from ui.native_frame_style import colorref
from ui.design_system import BACKGROUND, TEXT, BORDER
from PySide6.QtCore import QPoint, Qt


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    output = Path('docs/foryou-spacing')
    output.mkdir(parents=True, exist_ok=True)
    dwm = ctypes.WinDLL('dwmapi').DwmGetWindowAttribute
    dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwm.restype = ctypes.c_long
    user32 = ctypes.WinDLL('user32')
    style = user32.GetWindowLongW
    style.argtypes = [wintypes.HWND, ctypes.c_int]
    style.restype = ctypes.c_long

    def caption(window):
        hwnd = int(window.winId())
        values = {}
        for attr in (20, 34, 35, 36):
            value = ctypes.c_uint32()
            hr = dwm(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
            values[attr] = dict(hresult=hr, value=value.value)
        return values

    report = dict(windows_version=list(sys.getwindowsversion()), stages=[])
    with isolated_window() as (window, root):
        populate(window, root)
        window.showMaximized = lambda: None
        window.sidebar.setCurrentRow(1)
        window.handle_sidebar_click(window.sidebar.item(1))
        window.resize(1280, 820)
        pump(150)
        flags, geometry = window.windowFlags(), window.geometry()
        before_style = style(int(window.winId()), -16)
        window._native_frame_style.apply()
        after_style = style(int(window.winId()), -16)
        assert before_style == after_style
        assert flags == window.windowFlags() and geometry == window.geometry()
        # WS_CAPTION, WS_THICKFRAME, WS_MINIMIZEBOX, WS_MAXIMIZEBOX remain set.
        mask = 0x00C00000 | 0x00040000 | 0x00020000 | 0x00010000
        assert after_style & mask == mask
        report['native_style_unchanged'] = True
        report['native_frame_buttons_and_resize_bits'] = hex(after_style & mask)
        for name, action in [('normal', window.showNormal), ('maximized', window.showMaximized),
                             ('minimized', window.showMinimized), ('restore', window.showNormal),
                             ('fullscreen', window.showFullScreen), ('exit_fullscreen', window.showNormal)]:
            # The For You handler's maximize override is solely for preview size.
            if name == 'maximized':
                from PySide6.QtWidgets import QMainWindow
                action = lambda: QMainWindow.showMaximized(window)
            action()
            pump(120)
            window._native_frame_style.apply()
            values = caption(window)
            if not window.isFullScreen() and sys.getwindowsversion().build >= 22000:
                assert all(window._native_frame_style.last_results.get(attr) == 0
                           for attr in (20, 34, 35, 36)), window._native_frame_style.last_results
                # Caption COLORREFs are documented for Set, not necessarily Get.
                # Record unsupported readback instead of mistaking it for a Set failure.
                for attr, expected in ((35, BACKGROUND), (36, TEXT), (34, BORDER)):
                    if values[attr]['hresult'] == 0:
                        assert values[attr]['value'] == colorref(expected), values
            report['stages'].append(dict(stage=name, is_fullscreen=window.isFullScreen(),
                is_minimized=window.isMinimized(), flags=int(window.windowFlags()), attributes=values,
                set_results=dict(window._native_frame_style.last_results)))
        # Exercise the same native frame flags used by the app's mini restore.
        window.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint |
                              Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        window.show()
        pump(100)
        report['restore_flags_caption'] = caption(window)
        report['restore_flags_set_results'] = dict(window._native_frame_style.last_results)
        if sys.getwindowsversion().build >= 22000:
            assert report['restore_flags_set_results'][35] == 0
        window.grab().save(str(output / 'native-client.png'))
        window.raise_()
        window.activateWindow()
        pump(150)
        foreground = user32.GetForegroundWindow
        foreground.restype = wintypes.HWND
        report['caption_capture_owned_foreground'] = foreground() == int(window.winId())
        if report['caption_capture_owned_foreground']:
            # Capture only this owned window's caption, never the desktop around it.
            client = window.mapToGlobal(QPoint(0, 0))
            top = window.frameGeometry().top() + 1
            height = client.y() - top
            if height > 0:
                window.screen().grabWindow(0, client.x(), top, window.width(), height).save(
                    str(output / 'native-caption.png'))
        from ui.media_card import MediaCard
        from ui.playlist_thumbnail_queue import thumbnail_queue
        MediaCard.thread_pool.waitForDone(3000)
        thumbnail_queue().pool.waitForDone(3000)
        pump(30)
    (output / 'native-frame.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Actual HWND/DWM Set results and native style bits verified:', report['windows_version'])


if __name__ == '__main__':
    main()
