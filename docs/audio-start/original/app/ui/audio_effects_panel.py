"""Playback audio controls, using the app's existing Widgets/icon system."""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QCheckBox, QComboBox, QPushButton, QProgressBar

from ui.design_system import DIALOG_STYLE


class AudioEffectsPanel(QWidget):
    settings_changed = Signal(bool, str)
    level_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName('audioEffectsPanel')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(330)
        self.setStyleSheet(DIALOG_STYLE + '''
            QWidget#audioEffectsPanel { background: #151C26; color: #EDF3FA;
                border: 1px solid #273445; border-radius: 12px;
                font-family: 'Segoe UI'; font-size: 13px; }
            QLabel, QCheckBox { color: #EDF3FA; background: transparent; border: none; }
            QCheckBox { spacing: 9px; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #526173;
                border-radius: 4px; background: #101722; }
            QCheckBox::indicator:checked { background: #77E0BE; border-color: #77E0BE; }
            QProgressBar { border: none; background: #273445; }
            QProgressBar::chunk { background: #77E0BE; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title = QLabel('Âm thanh')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        layout.addWidget(title)
        self.normalize = QCheckBox('Cân bằng âm lượng giữa các bài')
        self.normalize.setToolTip('Điều chỉnh độ lớn toàn bài, giữ độ động; giới hạn gain để tránh quá tải.')
        layout.addWidget(self.normalize)
        layout.addWidget(QLabel('Mức cân bằng'))
        self.level = QComboBox()
        self.level.addItem('Thông thường (−14 LUFS)', -14)
        self.level.addItem('Nhỏ hơn (−18 LUFS)', -18)
        self.level.setMinimumHeight(36)
        self.level.setEnabled(False)
        self.level.currentIndexChanged.connect(lambda _: self.level_changed.emit(self.level.currentData()))
        layout.addWidget(self.level)
        layout.addWidget(QLabel('EQ tùy chọn'))
        self.tone = QComboBox()
        for text, key in (('Nguyên bản', 'off'), ('Dịu — giảm chói', 'gentle'), ('Cân bằng nhẹ', 'balanced')):
            self.tone.addItem(text, key)
        self.tone.setMinimumHeight(36)
        layout.addWidget(self.tone)
        note = QLabel('Cân bằng trực tiếp giữ phổ âm và độ động, không nạp lại video. '
                      'EQ riêng cần chuẩn bị và nạp lại nguồn; chọn Nguyên bản để phát liền mạch.')
        note.setWordWrap(True)
        note.setStyleSheet('color: #9AAABC; font-size: 12px;')
        layout.addWidget(note)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setFixedHeight(4)
        self.busy.setTextVisible(False)
        self.busy.hide()
        layout.addWidget(self.busy)
        self.status = QLabel('Đang dùng âm thanh gốc')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('font-size: 12px; color: #9AAABC;')
        layout.addWidget(self.status)
        self.reset = QPushButton('Trở về âm thanh gốc')
        self.reset.setMinimumHeight(36)
        layout.addWidget(self.reset)
        self.normalize.toggled.connect(self._emit_settings)
        self.tone.currentIndexChanged.connect(self._emit_settings)
        self.reset.clicked.connect(self._reset)

    def _emit_settings(self, *_):
        self.level.setEnabled(self.normalize.isChecked())
        self.settings_changed.emit(self.normalize.isChecked(), self.tone.currentData())

    def _reset(self):
        self.set_profile(False, 'off')
        self._emit_settings()

    def set_profile(self, normalize, tone):
        self.normalize.blockSignals(True)
        self.tone.blockSignals(True)
        self.normalize.setChecked(normalize)
        self.level.setEnabled(normalize)
        self.tone.setCurrentIndex(max(0, self.tone.findData(tone)))
        self.normalize.blockSignals(False)
        self.tone.blockSignals(False)

    def set_target(self, target):
        self.level.blockSignals(True)
        self.level.setCurrentIndex(max(0, self.level.findData(target)))
        self.level.blockSignals(False)

    def set_status(self, text, busy=False):
        self.status.setText(text)
        self.busy.setVisible(busy)

    def open_at(self, button):
        self.adjustSize()
        point = button.mapToGlobal(QPoint(button.width() // 2, 0))
        screen = button.screen().availableGeometry()
        x = max(screen.left() + 8, min(point.x() - self.width() // 2, screen.right() - self.width() - 8))
        y = max(screen.top() + 8, point.y() - self.height() - 10)
        self.move(x, y)
        self.show()
