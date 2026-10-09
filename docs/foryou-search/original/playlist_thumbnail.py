"""Bounded supersampling for playlist covers; decode QImage on a worker."""
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, Signal
from PySide6.QtGui import QImage, QImageReader


class ThumbnailSignals(QObject):
    finished = Signal(str, QImage)


class PlaylistThumbnailLoader(QRunnable):
    def __init__(self, cache_key, path, target_w, target_h, dpr):
        super().__init__()
        self.cache_key = cache_key
        self.path = path
        self.target = QSize(target_w, target_h)
        self.dpr = dpr
        self.signals = ThumbnailSignals()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            original = reader.size()
            if original.isValid():
                requested = original.scaled(self.target * 2, Qt.KeepAspectRatioByExpanding)
                # Do not manufacture extra source pixels for a small cover.
                if requested.width() <= original.width() and requested.height() <= original.height():
                    reader.setScaledSize(requested)
            if self._is_cancelled:
                return
            image = reader.read()
            if self._is_cancelled or image.isNull():
                return
            image = image.scaled(self.target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            image.setDevicePixelRatio(self.dpr)
            if not self._is_cancelled:
                self.signals.finished.emit(self.cache_key, image)
        except (RuntimeError, OSError, ValueError):
            return
