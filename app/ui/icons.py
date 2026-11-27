"""Offline, scalable Lucide icons shared by the existing Qt Widgets UI.

Source revision, hashes and ISC/MIT notices live in assets/icons/. QIcon paints
on the GUI thread; this cache does not interact with media thumbnail caches.
"""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

TEXT = "#EDF3FA"
MUTED = "#9AAABC"
ACCENT = "#77E0BE"
HEART_COLOR = "#FF6B8B"
INK = "#0D1118"
ASSETS = Path(__file__).resolve().parent / "assets" / "icons"
if not ASSETS.is_dir():
    # Original entry point uses the short `ui.*` namespace. PyInstaller may put
    # its module at _internal/ui while --add-data keeps assets at _internal/app.
    from paths import asset_dir
    ASSETS = asset_dir("app/ui/assets/icons")

_INLINE_SVGS = {
    "heart": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2'
        '-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>'
    ),
    "heart-filled": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2'
        '-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>'
    ),
    "history": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
        '<path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>'
    ),
    "list-music": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M21 15V6"/><path d="M18.5 18a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"/>'
        '<path d="M12 12H3"/><path d="M16 6H3"/><path d="M12 18H3"/></svg>'
    ),
    "folder-plus": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 10v6"/><path d="M9 13h6"/>'
        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>'
    ),
    "edit-3": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>'
    ),
    "flame": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 '
        '.5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>'
    ),
    "trophy": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>'
        '<path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>'
        '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>'
        '<path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/></svg>'
    ),
}


@lru_cache(maxsize=64)
def _svg(name):
    # Names come from the fixed subset, never from media/user file paths.
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name):
        raise ValueError(f"Invalid icon name: {name!r}")
    if name in _INLINE_SVGS:
        return _INLINE_SVGS[name]
    return (ASSETS / f"{name}.svg").read_text(encoding="utf-8")


class _VectorEngine(QIconEngine):
    def __init__(self, name, color):
        super().__init__()
        self.name, self.color = name, color
        source = _svg(name)
        self.renderers = {
            mode: QSvgRenderer(QByteArray(source.replace("currentColor", value).encode("utf-8")))
            # Qt requests Active while the pointer is over a button, including
            # after switching a toggle OFF. Hover must not impersonate ON.
            for mode, value in ((QIcon.Mode.Normal, color), (QIcon.Mode.Active, color),
                                (QIcon.Mode.Selected, ACCENT), (QIcon.Mode.Disabled, "#526173"))
        }

    def clone(self):
        return _VectorEngine(self.name, self.color)

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(rect.width(), rect.height())
        target = QRectF(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2, side, side)
        self.renderers.get(mode, self.renderers[QIcon.Mode.Normal]).render(painter, target)
        painter.restore()

    def pixmap(self, size, mode, state):
        result = QPixmap(size)
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        self.paint(painter, result.rect(), mode, state)
        painter.end()
        return result


@lru_cache(maxsize=128)
def icon(name, color=TEXT):
    return QIcon(_VectorEngine(name, color))


def button_icon(button, name, label=None, *, color=TEXT, size=20, icon_only=True):
    """Set presentation only; keep enabled/checkable/signal semantics untouched."""
    if label is not None:
        button.setAccessibleName(label)
        if not button.toolTip():
            button.setToolTip(label)
    button.setIcon(icon(name, color))
    button.setIconSize(QSize(size, size))
    button.setProperty("iconName", name)
    if icon_only:
        button.setText("")


def label_icon(label, name, *, size=32, color=MUTED):
    label.clear()
    label.setPixmap(icon(name, color).pixmap(QSize(size, size), label.devicePixelRatioF()))
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
