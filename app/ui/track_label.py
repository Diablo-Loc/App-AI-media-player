"""Elide the two visual metadata lines while retaining QLabel's HTML API."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QTextDocument
from PySide6.QtWidgets import QLabel


class TrackLabel(QLabel):
    def setText(self, text):
        super().setText(text)
        document = QTextDocument()
        document.setHtml(text)
        self._lines = document.toPlainText().strip().splitlines()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.contentsRect()
        top = rect.y() + max(0, (rect.height() - 36) // 2)
        for i, (size, weight, color) in enumerate((
            (14, QFont.Weight.Bold, "#FFFFFF"),
            (11, QFont.Weight.Normal, "#B3B3B3"),
        )):
            font = QFont(self.font())
            font.setPixelSize(size)
            font.setWeight(weight)
            painter.setFont(font)
            painter.setPen(QColor(color))
            text = self._lines[i] if i < len(getattr(self, "_lines", ())) else ""
            text = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(QRect(rect.x(), top + i * 18, rect.width(), 18),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
