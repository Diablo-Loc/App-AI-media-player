"""Studio Hi-Fi audio controls, A/B switch, and real-time Signal Path card."""
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QComboBox,
    QPushButton,
    QProgressBar,
    QFrame,
)

from ui.design_system import DIALOG_STYLE


class AudioEffectsPanel(QWidget):
    settings_changed = Signal(bool, str, str, str)
    level_changed = Signal(int)
    prefetch_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName('audioEffectsPanel')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(372)
        self.setStyleSheet(DIALOG_STYLE + '''
            QWidget#audioEffectsPanel { background: #151C26; color: #EDF3FA;
                border: 1px solid #273445; border-radius: 12px;
                font-family: 'Segoe UI'; font-size: 13px; }
            QLabel, QCheckBox { color: #EDF3FA; background: transparent; border: none; }
            QCheckBox { spacing: 9px; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #526173;
                border-radius: 4px; background: #101722; }
            QCheckBox::indicator:checked { background: #77E0BE; border-color: #77E0BE; }
            QCheckBox:disabled { color: #657585; }
            QCheckBox::indicator:disabled { background: #273445; border-color: #354351; }
            QProgressBar { border: none; background: #273445; }
            QProgressBar::chunk { background: #77E0BE; }
            QFrame#signalPathCard { background: #0E141D; border: 1px solid #223042; border-radius: 8px; }
            QPushButton#recommendedBtn { background: #1D3530; color: #77E0BE; border: 1px solid #2D5A4E;
                border-radius: 8px; font-weight: 600; padding: 6px 10px; }
            QPushButton#recommendedBtn:hover { background: #24433D; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel('Âm thanh · Studio Engine')
        title.setStyleSheet('font-size: 17px; font-weight: 600;')
        layout.addWidget(title)

        layout.addWidget(QLabel('Chế độ đầu ra (DAC / Tai nghe)'))
        self.output_mode = QComboBox()
        self.output_mode.addItem('Tiêu chuẩn — WASAPI Shared (Nghe chung mọi app)', 'shared')
        self.output_mode.addItem('Độc quyền DAC — WASAPI Exclusive (Tối đa chất âm)', 'exclusive')
        self.output_mode.setToolTip(
            'Shared: nghe chung cùng Chrome/Discord. Exclusive: khóa thẳng USB DAC (như Dawn Pro 2) '
            'để bỏ qua bộ trộn Windows; tự chuyển về Shared nếu thiết bị Bluetooth không hỗ trợ.'
        )
        self.output_mode.setMinimumHeight(34)
        layout.addWidget(self.output_mode)

        self.normalize = QCheckBox('Cân bằng âm lượng Mastering (EBU R128)')
        self.normalize.setToolTip(
            'Xử lý 64-bit Float trong RAM kèm bộ giữ đỉnh -1.5 dBTP bảo vệ chip CS43198, '
            'giúp mọi bài đều âm lượng mà không bóp độ động.'
        )
        layout.addWidget(self.normalize)

        layout.addWidget(QLabel('Mức cân bằng'))
        self.level = QComboBox()
        self.level.addItem('Chuẩn Audiophile (−16 LUFS · Khuyên dùng)', -16)
        self.level.addItem('Sôi động (−14 LUFS · Pop / EDM)', -14)
        self.level.addItem('Thuần khiết (−18 LUFS · Dải động tối đa)', -18)
        self.level.setMinimumHeight(34)
        self.level.setEnabled(False)
        self.level.currentIndexChanged.connect(lambda _: self.level_changed.emit(self.level.currentData()))
        layout.addWidget(self.level)

        layout.addWidget(QLabel('Khôi phục chi tiết nhạc nén (128kbps Restorer)'))
        self.restorer = QComboBox()
        for text, key in (
            ('Tắt — Giữ 100% âm sắc gốc (Khuyên dùng)', 'off'),
            ('Tự động nhẹ (Chỉ lọc MP3/AAC cũ ≤192kbps)', 'auto'),
            ('Tự nhiên (Làm nét & bù dải cao dịu)', 'natural'),
            ('Chi tiết cao (Tối đa độ thoáng 128kbps)', 'vivid'),
        ):
            self.restorer.addItem(text, key)
        self.restorer.setToolTip(
            'Mặc định Tắt để bảo toàn tuyệt đối chất âm gốc. Bật Tự động nhẹ nếu nghe các file MP3/AAC cũ '
            'bị tù bí; tự bỏ qua Opus và FLAC/Lossless.'
        )
        self.restorer.setMinimumHeight(34)
        layout.addWidget(self.restorer)

        layout.addWidget(QLabel('Chất âm (Sound Signature)'))
        self.tone = QComboBox()
        for text, key in (
            ('Nguyên bản Tuyệt đối (Bit-Pure · Khuyên dùng)', 'off'),
            ('Moondrop Aria 2 Subtle Balance', 'aria2'),
            ('Ấm mượt — Nghe lâu (Musical Warm)', 'warm'),
            ('Không gian loa tự nhiên (IEM Crossfeed)', 'headphones'),
            ('Giọng hát rõ nét (Vocal & Acoustic)', 'vocal_clear'),
            ('Dịu — giảm chói (Legacy)', 'gentle'),
            ('Cân bằng nhẹ (Legacy)', 'balanced'),
            ('Dễ nghe — loa (Legacy)', 'easy'),
            ('Dễ nghe — tai nghe (Legacy)', 'easy_headphones'),
        ):
            self.tone.addItem(text, key)
        self.tone.setItemData(
            self.tone.findData('aria2'),
            'Tinh chỉnh 64-bit tối ưu riêng cho Moondrop Aria 2: thêm độ sâu sub-bass, tách lớp vocal '
            'và làm êm đỉnh cộng hưởng 8 kHz.',
            Qt.ItemDataRole.ToolTipRole,
        )
        self.tone.setMinimumHeight(34)
        layout.addWidget(self.tone)

        self.prefetch_next = QCheckBox('Đo sẵn độ lớn bài kế tiếp (0 MB rác ổ cứng)')
        self.prefetch_next.setToolTip('Chỉ đo nhanh thông số LUFS bài kế tiếp vào mục lục JSON; không tạo file âm thanh tạm.')
        self.prefetch_next.setChecked(True)
        self.prefetch_next.setEnabled(False)
        self.prefetch_next.toggled.connect(self.prefetch_changed.emit)
        layout.addWidget(self.prefetch_next)

        card = QFrame()
        card.setObjectName('signalPathCard')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(2)
        card_title = QLabel('Signal Path (Thời gian thực trong RAM)')
        card_title.setStyleSheet('color: #77E0BE; font-size: 11px; font-weight: 600;')
        card_layout.addWidget(card_title)
        self.signal_path = QLabel('Nguồn: —\nDSP: Đang dùng âm thanh gốc (Bypass)\nĐầu ra: Hệ thống mặc định')
        self.signal_path.setWordWrap(True)
        self.signal_path.setStyleSheet('color: #B4C2D1; font-size: 11px; line-height: 1.35;')
        card_layout.addWidget(self.signal_path)
        layout.addWidget(card)

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

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_recommended = QPushButton('Chuẩn khuyên dùng')
        self.btn_recommended.setObjectName('recommendedBtn')
        self.btn_recommended.setMinimumHeight(34)
        self.reset = QPushButton('Trở về âm thanh gốc')
        self.reset.setMinimumHeight(34)
        btn_row.addWidget(self.btn_recommended)
        btn_row.addWidget(self.reset)
        layout.addLayout(btn_row)

        self.normalize.toggled.connect(self._emit_settings)
        self.tone.currentIndexChanged.connect(self._emit_settings)
        self.restorer.currentIndexChanged.connect(self._emit_settings)
        self.output_mode.currentIndexChanged.connect(self._emit_settings)
        self.btn_recommended.clicked.connect(self._apply_recommended)
        self.reset.clicked.connect(self._reset)

    def _emit_settings(self, *_):
        self.level.setEnabled(self.normalize.isChecked())
        self.prefetch_next.setEnabled(self.normalize.isChecked())
        self.settings_changed.emit(
            self.normalize.isChecked(),
            self.tone.currentData(),
            self.restorer.currentData(),
            self.output_mode.currentData(),
        )

    def _apply_recommended(self):
        self.set_profile(True, 'off', 'off', 'shared')
        idx = self.level.findData(-16)
        if idx >= 0:
            self.level.setCurrentIndex(idx)
        self._emit_settings()

    def _reset(self):
        self.set_profile(False, 'off', 'off', 'shared')
        self._emit_settings()

    def set_profile(self, normalize, tone, restorer='off', output_mode='shared'):
        widgets = (self.normalize, self.tone, self.restorer, self.output_mode)
        for w in widgets:
            w.blockSignals(True)
        self.normalize.setChecked(bool(normalize))
        self.level.setEnabled(bool(normalize))
        self.prefetch_next.setEnabled(bool(normalize))
        self.tone.setCurrentIndex(max(0, self.tone.findData(tone)))
        self.restorer.setCurrentIndex(max(0, self.restorer.findData(restorer)))
        self.output_mode.setCurrentIndex(max(0, self.output_mode.findData(output_mode)))
        for w in widgets:
            w.blockSignals(False)

    def set_prefetch(self, enabled):
        self.prefetch_next.blockSignals(True)
        self.prefetch_next.setChecked(bool(enabled))
        self.prefetch_next.blockSignals(False)

    def set_target(self, target):
        self.level.blockSignals(True)
        self.level.setCurrentIndex(max(0, self.level.findData(target)))
        self.level.blockSignals(False)

    def set_signal_path(self, source_text: str, dsp_text: str, output_text: str):
        self.signal_path.setText(f'Nguồn: {source_text}\nDSP: {dsp_text}\nĐầu ra: {output_text}')

    def set_status(self, text, busy=False):
        self.status.setText(text)
        self.busy.setVisible(busy)

    def open_at(self, button):
        self.adjustSize()
        height = self.layout().totalHeightForWidth(self.width())
        if height >= 0:
            self.resize(self.width(), height)
        point = button.mapToGlobal(QPoint(button.width() // 2, 0))
        screen = button.screen().availableGeometry()
        x = max(screen.left() + 8, min(point.x() - self.width() // 2, screen.right() - self.width() - 8))
        y = max(screen.top() + 8, point.y() - self.height() - 10)
        self.move(x, y)
        self.show()
