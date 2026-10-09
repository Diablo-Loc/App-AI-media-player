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
INK = "#0D1118"
ASSETS = Path(__file__).resolve().parent / "assets" / "icons"
if not ASSETS.is_dir():
    # Original entry point uses the short `ui.*` namespace. PyInstaller may put
    # its module at _internal/ui while --add-data keeps assets at _internal/app.
    from paths import asset_dir
    ASSETS = asset_dir("app/ui/assets/icons")


@lru_cache(maxsize=64)
def _svg(name):
    # Names come from the fixed subset, never from media/user file paths.
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name):
        raise ValueError(f"Invalid icon name: {name!r}")
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
