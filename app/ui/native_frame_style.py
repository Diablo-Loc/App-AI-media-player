"""Color the existing Windows caption. Never replace its frame or controls."""
import ctypes
from functools import lru_cache
import sys

from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtGui import QGuiApplication


def colorref(color):
    value = int(color.lstrip('#'), 16)
    return (value >> 16) | (value & 0x00FF00) | ((value & 0xFF) << 16)


@lru_cache(maxsize=1)
def _dwm_setter():
    if sys.platform != 'win32':
        return None
    try:
        setter = ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
        setter.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        setter.restype = ctypes.c_long
        return setter
    except (AttributeError, OSError):
        return None


def apply_caption_colors(hwnd, background, text, border):
    """Return HRESULTs; unsupported OS attributes leave native defaults intact."""
    setter = _dwm_setter()
    if not hwnd or setter is None:
        return {}
    results = {}
    for attribute, value in ((20, 1), (35, colorref(background)),
                             (36, colorref(text)), (34, colorref(border))):
        data = ctypes.c_uint32(value)
        try:
            results[attribute] = setter(ctypes.c_void_p(hwnd), attribute,
                                        ctypes.byref(data), ctypes.sizeof(data))
        except (OSError, ValueError):
            # Styling must never prevent startup, restore or normal controls.
            results[attribute] = -1
    return results


class NativeFrameStyle(QObject):
    def __init__(self, window, background, text, border):
        super().__init__(window)
        self.window = window
        self.colors = (background, text, border)
        self.last_results = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.apply)
        window.installEventFilter(self)
        self.timer.start(0)

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() in (QEvent.Show, QEvent.WinIdChange, QEvent.WindowStateChange,
                                QEvent.PaletteChange):
                self.timer.start(0)
            elif event.type() == QEvent.Close:
                self.timer.stop()
        return False

    def apply(self):
        window = self.window
        if (sys.platform != 'win32' or QGuiApplication.platformName() != 'windows'
                or not window.isVisible() or not window.windowHandle()
                or window.isFullScreen() or window.windowFlags() & Qt.FramelessWindowHint):
            return
        self.last_results = apply_caption_colors(int(window.winId()), *self.colors)


def install_native_frame(window, background, text, border):
    if not hasattr(window, '_native_frame_style'):
        window._native_frame_style = NativeFrameStyle(window, background, text, border)
