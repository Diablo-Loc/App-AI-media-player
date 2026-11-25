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

from core.audio_profile import AudioProfile, detect_preset, preset_profile
from ui.design_system import DIALOG_STYLE


class AudioEffectsPanel(QWidget):
    settings_changed = Signal(bool, str, str, str, str, bool)
    level_changed = Signal(int)
    prefetch_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName('audioEffectsPanel')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(388)
        self.setStyleSheet(DIALOG_STYLE + '''
            QWidget#audioEffectsPanel { background: #151C26; color: #EDF3FA;
                border: 1px solid #273445; border-radius: 12px;
                font-family: 'Segoe UI'; font-size: 13px; }
            QLabel, QCheckBox { color: #EDF3FA; background: transparent; border: none; }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #526173;
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
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        title = QLabel('Âm thanh · Studio Engine')
        title.setStyleSheet('font-size: 16px; font-weight: 600;')
        layout.addWidget(title)

        layout.addWidget(QLabel('Chế độ nghe chuẩn (Quick Preset)'))
        self.preset_combo = QComboBox()
        for text, key in (
            ('★ Dawn Pro 2 + Aria 2 · Phòng thu Hi-Res', 'studio_dawn_aria2'),
            ('Chuẩn YouTube gốc (YouTube / YT Music)', 'youtube'),
            ('Nguyên bản Tuyệt đối (Bit-Pure · Khuyên dùng)', 'bit_pure'),
            ('Sống động Cuốn hút (Sony Walkman / Poweramp)', 'walkman_vivid'),
            ('Tắt xử lý — Âm thanh gốc mặc định', 'bypass'),
            ('Tùy chỉnh riêng (Custom)', 'custom'),
        ):
            self.preset_combo.addItem(text, key)
        self.preset_combo.setToolTip(
            'Chọn nhanh cấu hình nghe chuẩn phòng thu hoặc streaming phổ biến.\n'
            'Mẹo tải chuẩn YouTube: ở trang Tải xuống chọn "Original (Giữ nguồn)" hoặc "High (Opus)" '
            'để giữ luồng Opus 48 kHz gốc y hệt YouTube.'
        )
        self.preset_combo.setMinimumHeight(30)
        layout.addWidget(self.preset_combo)

        layout.addWidget(QLabel('Chế độ đầu ra (DAC / Tai nghe)'))
        self.output_mode = QComboBox()
        self.output_mode.addItem('Tiêu chuẩn — WASAPI Shared (Nghe chung mọi app)', 'shared')
        self.output_mode.addItem('Độc quyền DAC — WASAPI Exclusive (Tối đa chất âm)', 'exclusive')
        self.output_mode.setToolTip(
            'Shared: nghe chung cùng Chrome/Discord. Exclusive: khóa thẳng USB DAC (như Dawn Pro 2) '
            'để bỏ qua bộ trộn Windows; tự chuyển về Shared nếu thiết bị Bluetooth không hỗ trợ.'
        )
        self.output_mode.setMinimumHeight(30)
        layout.addWidget(self.output_mode)

        layout.addWidget(QLabel('Nâng tần số lấy mẫu (SoXR 33-bit Hi-Res)'))
        self.upsample = QComboBox()
        for text, key in (
            ('Tần số gốc (Bit-Pure Native)', 'off'),
            ('Hi-Res 4× Đồng bộ (176.4 / 192 kHz · SoXR 33-bit)', 'hires_sync'),
            ('Tối đa chip DAC (352.8 / 384 kHz · SoXR 33-bit)', 'max_dac'),
        ):
            self.upsample.addItem(text, key)
        self.upsample.setToolTip(
            'Hoạt động tối đa khi bật WASAPI Exclusive trên USB DAC như Dawn Pro 2: '
            'dùng bộ lọc SoXR 33-bit nâng tần số 4×/8× để bỏ qua lọc thô bên trong chip DAC. '
            'Chế độ Shared đi theo tần số Windows Mixer.'
        )
        self.upsample.setMinimumHeight(30)
        layout.addWidget(self.upsample)

        self.normalize = QCheckBox('Cân bằng âm lượng (EBU R128 / YouTube)')
        self.normalize.setToolTip(
            'Xử lý 64-bit Float trong RAM kèm bảo vệ đỉnh CS43198, '
            'giúp đồng đều âm lượng hoặc giữ đúng luật giảm âm −14 LUFS của YouTube.'
        )
        layout.addWidget(self.normalize)

        layout.addWidget(QLabel('Luật cân bằng âm lượng'))
        self.level = QComboBox()
        self.level.addItem('Chuẩn Audiophile (−16 LUFS · Khuyên dùng)', -16)
        self.level.addItem('Sôi động (−14 LUFS · Walkman / Streaming)', -14)
        self.level.addItem('Thuần khiết (−18 LUFS · Dải động tối đa)', -18)
        self.level.addItem('Chuẩn YouTube gốc (−14 LUFS · Chỉ giảm bài to)', 'youtube')
        self.level.setMinimumHeight(30)
        self.level.setEnabled(False)
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
        self.restorer.setMinimumHeight(30)
        layout.addWidget(self.restorer)

        layout.addWidget(QLabel('Chất âm (Sound Signature)'))
        self.tone = QComboBox()
        for text, key in (
            ('Nguyên bản Tuyệt đối (Bit-Pure · 0 dB)', 'off'),
            ('Phòng thu Hi-Res · Dawn Pro 2 + Aria 2', 'studio_aria2'),
            ('Không gian Loa Kiểm Âm 30° (Không EQ)', 'studio_room'),
            ('Sống động — Sony Walkman / Poweramp', 'walkman_vivid'),
            ('Moondrop Aria 2 Subtle Balance', 'aria2'),
            ('Giọng hát rõ nét (Vocal & Acoustic)', 'vocal_clear'),
            ('Ấm mượt — Nghe lâu (Musical Warm)', 'warm'),
            ('Không gian tai nghe nhẹ (IEM Crossfeed)', 'headphones'),
            ('Dịu — giảm chói (Legacy)', 'gentle'),
            ('Cân bằng nhẹ (Legacy)', 'balanced'),
            ('Dễ nghe — loa (Legacy)', 'easy'),
            ('Dễ nghe — tai nghe (Legacy)', 'easy_headphones'),
        ):
            self.tone.addItem(text, key)
        self.tone.setItemData(
            self.tone.findData('studio_aria2'),
            'Cân chỉnh Lab Reference 64-bit riêng cho Moondrop Aria 2 trên Dawn Pro 2 kết hợp Crossfeed '
            'loa kiểm âm 30° (giọng hát giữa 0.0 dB, mở rộng không gian sân khấu).',
            Qt.ItemDataRole.ToolTipRole,
        )
        self.tone.setItemData(
            self.tone.findData('aria2'),
            'Tinh chỉnh 64-bit tối ưu riêng cho Moondrop Aria 2: thêm độ sâu sub-bass, tách lớp vocal '
            'và làm êm đỉnh cộng hưởng 8 kHz.',
            Qt.ItemDataRole.ToolTipRole,
        )
        self.tone.setMinimumHeight(30)
        layout.addWidget(self.tone)

        self.prefetch_next = QCheckBox('Chuẩn bị sẵn bài kế tiếp trong RAM (0 MB ổ cứng)')
        self.prefetch_next.setToolTip('Chỉ đo nhanh thông số LUFS/Codec bài kế tiếp vào bộ nhớ; không tạo file âm thanh tạm.')
        self.prefetch_next.setChecked(True)
        self.prefetch_next.setEnabled(False)
        self.prefetch_next.toggled.connect(self.prefetch_changed.emit)
        layout.addWidget(self.prefetch_next)

        card = QFrame()
        card.setObjectName('signalPathCard')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 6, 10, 6)
        card_layout.setSpacing(2)
        card_title = QLabel('Signal Path (Thời gian thực trong RAM)')
        card_title.setStyleSheet('color: #77E0BE; font-size: 11px; font-weight: 600;')
        card_layout.addWidget(card_title)
        self.signal_path = QLabel('Nguồn: —\nDSP: Đang dùng âm thanh gốc (Bypass)\nĐầu ra: Hệ thống mặc định')
        self.signal_path.setWordWrap(True)
        self.signal_path.setStyleSheet('color: #B4C2D1; font-size: 11px; line-height: 1.3;')
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
        self.btn_recommended.setMinimumHeight(32)
        self.reset = QPushButton('Trở về âm thanh gốc')
        self.reset.setMinimumHeight(32)
        btn_row.addWidget(self.btn_recommended)
        btn_row.addWidget(self.reset)
        layout.addLayout(btn_row)

        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.normalize.toggled.connect(self._emit_settings)
        self.level.currentIndexChanged.connect(self._on_level_changed)
        self.tone.currentIndexChanged.connect(self._emit_settings)
        self.restorer.currentIndexChanged.connect(self._emit_settings)
        self.output_mode.currentIndexChanged.connect(self._emit_settings)
        self.upsample.currentIndexChanged.connect(self._emit_settings)
        self.btn_recommended.clicked.connect(self._apply_recommended)
        self.reset.clicked.connect(self._reset)

    def _current_target_lufs(self) -> int:
        val = self.level.currentData()
        return int(val) if isinstance(val, int) else -14

    def _sync_preset_combo(self):
        checked = self.normalize.isChecked()
        level_val = self.level.currentData()
        yt_loud = checked and (level_val == 'youtube')
        norm = checked and not yt_loud
        prof = AudioProfile(
            normalize=norm,
            tone=self.tone.currentData() or 'off',
            restorer=self.restorer.currentData() or 'off',
            output_mode=self.output_mode.currentData() or 'shared',
            upsample=self.upsample.currentData() or 'off',
            youtube_loudness=yt_loud,
        )
        key = detect_preset(prof, self._current_target_lufs())
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(key)))
        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, *_):
        key = self.preset_combo.currentData()
        if key == 'custom' or not key:
            return
        prof, lufs = preset_profile(key)
        self.set_profile(
            prof.normalize,
            prof.tone,
            prof.restorer,
            prof.output_mode,
            prof.upsample,
            prof.youtube_loudness,
            target_lufs=lufs,
        )
        if isinstance(lufs, int) and key != 'youtube':
            self.level_changed.emit(int(lufs))
        self._emit_settings()

    def _on_level_changed(self, *_):
        val = self.level.currentData()
        if isinstance(val, int):
            self.level_changed.emit(int(val))
        self._emit_settings()

    def _emit_settings(self, *_):
        checked = self.normalize.isChecked()
        level_val = self.level.currentData()
        yt_loud = checked and (level_val == 'youtube')
        norm = checked and not yt_loud
        tone_val = self.tone.currentData() or 'off'
        rest_val = self.restorer.currentData() or 'off'
        out_val = self.output_mode.currentData() or 'shared'
        up_val = self.upsample.currentData() or 'off'
        any_enabled = (
            norm or yt_loud or tone_val != 'off' or rest_val != 'off'
            or out_val == 'exclusive' or up_val != 'off'
        )
        self.level.setEnabled(checked)
        self.prefetch_next.setEnabled(any_enabled)
        self._sync_preset_combo()
        self.settings_changed.emit(norm, tone_val, rest_val, out_val, up_val, yt_loud)

    def _apply_recommended(self):
        self.set_profile(True, 'off', 'off', 'shared', 'off', False, target_lufs=-16)
        self.level_changed.emit(-16)
        self._emit_settings()

    def _reset(self):
        self.set_profile(False, 'off', 'off', 'shared', 'off', False)
        self._emit_settings()

    def set_profile(
        self,
        normalize,
        tone,
        restorer='off',
        output_mode='shared',
        upsample='off',
        youtube_loudness=False,
        target_lufs=None,
    ):
        widgets = (self.preset_combo, self.normalize, self.level, self.tone, self.restorer, self.output_mode, self.upsample)
        for w in widgets:
            w.blockSignals(True)
        yt_loud = bool(youtube_loudness)
        checked = bool(normalize or yt_loud)
        any_enabled = (
            checked or tone != 'off' or restorer != 'off'
            or output_mode == 'exclusive' or upsample != 'off'
        )
        self.normalize.setChecked(checked)
        self.level.setEnabled(checked)
        self.prefetch_next.setEnabled(any_enabled)
        if yt_loud:
            idx = self.level.findData('youtube')
            if idx >= 0:
                self.level.setCurrentIndex(idx)
        elif isinstance(target_lufs, int):
            idx = self.level.findData(int(target_lufs))
            if idx >= 0:
                self.level.setCurrentIndex(idx)
        elif self.level.currentData() == 'youtube':
            idx = self.level.findData(-16)
            if idx >= 0:
                self.level.setCurrentIndex(idx)
        self.tone.setCurrentIndex(max(0, self.tone.findData(tone)))
        self.restorer.setCurrentIndex(max(0, self.restorer.findData(restorer)))
        self.output_mode.setCurrentIndex(max(0, self.output_mode.findData(output_mode)))
        self.upsample.setCurrentIndex(max(0, self.upsample.findData(upsample)))
        for w in widgets:
            w.blockSignals(False)
        self._sync_preset_combo()

    def set_prefetch(self, enabled):
        self.prefetch_next.blockSignals(True)
        self.prefetch_next.setChecked(bool(enabled))
        self.prefetch_next.blockSignals(False)

    def set_target(self, target):
        self.level.blockSignals(True)
        if self.level.currentData() != 'youtube':
            self.level.setCurrentIndex(max(0, self.level.findData(target)))
        self.level.blockSignals(False)
        self._sync_preset_combo()

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
