"""Small painted progress ring; animates only while its viewport is visible."""
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .icons import ACCENT


class PlaylistLoadingOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.message = ''
        self.started = 0
        self.setAccessibleName('Đang tải danh sách phát')
        self.setCursor(Qt.WaitCursor)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)
        self.hide()

    def begin(self, message):
        self.message = message
        if self.isHidden():
            self.started = time.monotonic()
        self.setAccessibleName(message)
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#151C26'))
        painter.setRenderHint(QPainter.Antialiasing)
        x, y = self.width() / 2, self.height() / 2
        ring = QRectF(x - 15, y - 31, 30, 30)
        painter.setPen(QPen(QColor('#273445'), 3))
        painter.drawEllipse(ring)
        pen = QPen(QColor(ACCENT), 3)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        angle = (time.monotonic() - self.started) * 300
        painter.drawArc(ring, int(-angle * 16), 250 * 16)
        painter.setPen(QColor('#A3AFBF'))
        painter.drawText(QRectF(12, y + 12, self.width() - 24, 28), Qt.AlignCenter, self.message)
        painter.end()
