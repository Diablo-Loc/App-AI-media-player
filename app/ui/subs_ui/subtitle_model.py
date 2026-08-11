from typing import List
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QUndoCommand, QColor, QFont, QBrush

from ui.subs_ui.subtitle_utils import _format_time, _parse_time_str


class SubtitleTableModel(QAbstractTableModel):
    HEADERS = ["Bắt đầu (s)", "Kết thúc (s)", "Lời Gốc", "Tiếng Anh (EN)", "Tiếng Việt (VI)"]

    def __init__(self, segments=None, parent=None):
        super().__init__(parent)
        self._segments = []
        self.active_row = -1
        self._font_time = QFont("Consolas", 10, QFont.Bold)
        self._font_orig = QFont("Segoe UI", 10, QFont.Bold)
        self._font_trans = QFont("Segoe UI", 10)
        self._color_time = QColor("#8e8e93")
        self._color_orig = QColor("#ffffff")
        self._color_en = QColor("#64b5f6")
        self._color_vi = QColor("#ffe082")
        if segments:
            self.set_segments(segments)

    def rowCount(self, parent=QModelIndex()):
        return len(self._segments)

    def columnCount(self, parent=QModelIndex()):
        return 5

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = index.row()
        c = index.column()
        seg = self._segments[r]

        if role == Qt.DisplayRole or role == Qt.EditRole:
            if c == 0:
                return _format_time(seg.get('start', 0.0))
            if c == 1:
                return _format_time(seg.get('end', 0.0))
            if c == 2:
                return seg.get('text', '') or seg.get('orig', '') or seg.get('jp', '')
            if c == 3:
                return seg.get('en', '')
            if c == 4:
                return seg.get('vi', '')

        if role == Qt.ForegroundRole:
            if c in (0, 1):
                return self._color_time
            if c == 2:
                return self._color_orig
            if c == 3:
                return self._color_en
            if c == 4:
                return self._color_vi

        if role == Qt.FontRole:
            if c in (0, 1):
                return self._font_time
            if c == 2:
                return self._font_orig
            return self._font_trans

        if role == Qt.TextAlignmentRole:
            if c in (0, 1):
                return Qt.AlignCenter

        if role == Qt.BackgroundRole:
            if self.active_row == r:
                return QBrush(QColor(255, 213, 79, 64))
            # Non-blocking validation visual: soft red if end < start
            try:
                if float(seg.get('end', 0.0)) < float(seg.get('start', 0.0)):
                    return QBrush(QColor(255, 92, 92, 80))
            except Exception:
                pass
            return QBrush(QColor(0, 0, 0, 0))

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        r = index.row()
        c = index.column()
        text = str(value).strip()
        if c == 0:
            self._segments[r]['start'] = float(_parse_time_str(text))
        elif c == 1:
            self._segments[r]['end'] = float(_parse_time_str(text))
        elif c == 2:
            self._segments[r]['text'] = text
            self._segments[r]['orig'] = text
        elif c == 3:
            self._segments[r]['en'] = text
        elif c == 4:
            self._segments[r]['vi'] = text
        else:
            return False

        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        return True

    def insertRows(self, row, count, parent=QModelIndex()):
        self.beginInsertRows(QModelIndex(), row, row + count - 1)
        for i in range(count):
            self._segments.insert(row, {"start": 0.0, "end": 3.0, "text": "", "orig": "", "en": "", "vi": ""})
        self.endInsertRows()
        return True

    def removeRows(self, row, count, parent=QModelIndex()):
        self.beginRemoveRows(QModelIndex(), row, row + count - 1)
        for i in range(count):
            if row < len(self._segments):
                self._segments.pop(row)
        self.endRemoveRows()
        return True

    def get_segments(self):
        return [dict(s) for s in self._segments]

    def set_segments(self, segments: List[dict]):
        self.beginResetModel()
        self._segments = []
        for seg in segments:
            self._segments.append({
                'start': float(seg.get('start', 0.0)),
                'end': float(seg.get('end', 0.0)),
                'text': seg.get('text', '') or seg.get('orig', '') or seg.get('jp', ''),
                'orig': seg.get('orig', '') or seg.get('text', '') or seg.get('jp', ''),
                'en': seg.get('en', ''),
                'vi': seg.get('vi', '')
            })
        self.endResetModel()

    def set_active_row(self, row: int):
        old = self.active_row
        self.active_row = row
        if old >= 0 and old < len(self._segments):
            left = self.index(old, 0)
            right = self.index(old, self.columnCount()-1)
            self.dataChanged.emit(left, right, [Qt.BackgroundRole])
        if row >= 0 and row < len(self._segments):
            left = self.index(row, 0)
            right = self.index(row, self.columnCount()-1)
            self.dataChanged.emit(left, right, [Qt.BackgroundRole])

    def snapshot(self):
        return [dict(s) for s in self._segments]


class SnapshotCommand(QUndoCommand):
    def __init__(self, model: SubtitleTableModel, before: List[dict], after: List[dict], text: str = "change"):
        super().__init__(text)
        self.model = model
        self.before = before
        self.after = after

    def undo(self):
        self.model.set_segments(self.before)

    def redo(self):
        self.model.set_segments(self.after)
