"""Width-aware playlist text; retain full QLabel text and tooltip for callers."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    def __init__(self, text, max_lines=1, parent=None):
        super().__init__(text, parent)
        self.max_lines = max_lines
        self._line_cache = None
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(0, self.fontMetrics().lineSpacing() * self.max_lines)

    def minimumSizeHint(self):
        return self.sizeHint()

    def visible_lines(self):
        width = max(0, self.contentsRect().width())
        text = " ".join(self.text().splitlines())
        key = (text, self.font().toString(), width, self.max_lines)
        if self._line_cache and self._line_cache[0] == key:
            return self._line_cache[1]
        metrics = QFontMetrics(self.font())
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        # Qt offsets use UTF-16 code units, including surrogate pairs for emoji.
        encoded = text.encode("utf-16-le")
        lines = []
        layout.beginLayout()
        for index in range(self.max_lines):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start = line.textStart() * 2
            if index == self.max_lines - 1:
                remaining = encoded[start:].decode("utf-16-le")
                lines.append(metrics.elidedText(remaining, Qt.ElideRight, width))
            else:
                end = start + line.textLength() * 2
                lines.append(encoded[start:end].decode("utf-16-le").rstrip())
        layout.endLayout()
        self._line_cache = (key, lines)
        return lines

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.WindowText))
        rect = self.contentsRect()
        painter.setClipRect(rect)
        lines = self.visible_lines()
        height = self.fontMetrics().lineSpacing()
        top = rect.y() + max(0, (rect.height() - height * len(lines)) // 2)
        for index, text in enumerate(lines):
            painter.drawText(QRect(rect.x(), top + index * height, rect.width(), height),
                             Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, text)
