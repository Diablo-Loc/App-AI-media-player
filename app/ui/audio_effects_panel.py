"""Minimalist audio controls popover with progressive disclosure and compact signal path."""
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
    QSizePolicy,
)

from core.audio_profile import AudioProfile, FLAT_EQ_BANDS, detect_preset, normalize_peq_filters, preset_profile
from ui.design_system import DIALOG_STYLE
from ui.icons import button_icon, ACCENT, MUTED, TEXT


class AudioEffectsPanel(QWidget):
    settings_changed = Signal(bool, str, str, str, str, bool)
    level_changed = Signal(int)
    prefetch_changed = Signal(bool)
    open_eq_requested = Signal()
    open_benchmark_requested = Signal()
    output_device_changed = Signal(str)
    per_device_changed = Signal(bool)
    dac_phase_changed = Signal(str)
    recommended_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName('audioEffectsPanel')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(356)
        self._anchor_button = None
        self._output_device = ''
        self._eq_state = {
            'eq_enabled': False,
            'eq_bands': FLAT_EQ_BANDS,
            'eq_peq_filters': (),
            'eq_preamp_db': 0.0,
            'eq_auto_preamp': True,
            'eq_bass_db': 0.0,
            'eq_treble_db': 0.0,
            'eq_crossfeed': 0,
        }
        self.setStyleSheet(DIALOG_STYLE + '''
            QWidget#audioEffectsPanel { background: #151C26; color: #EDF3FA;
                border: 1px solid #273445; border-radius: 12px;
                font-family: 'Segoe UI'; font-size: 13px; }
            QLabel, QCheckBox { color: #EDF3FA; background: transparent; border: none; }
            QLabel#panelTitle { font-size: 15px; font-weight: 600; color: #EDF3FA; }
            QLabel#panelStatus { font-size: 11px; color: #8FA2B7; }
            QLabel#formLabel { font-size: 12px; color: #9AAABC; }
            QCheckBox { spacing: 8px; font-size: 12px; color: #B8C7D6; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #526173;
                border-radius: 4px; background: #101722; }
            QCheckBox::indicator:checked { background: #77E0BE; border-color: #77E0BE; }
            QCheckBox:disabled { color: #657585; }
            QCheckBox::indicator:disabled { background: #273445; border-color: #354351; }
            QComboBox { padding: 4px 8px; }
            QProgressBar { border: none; background: #202B38; border-radius: 1px; }
            QProgressBar::chunk { background: #77E0BE; }
            QPushButton#headerIconBtn { background: transparent; border: none; border-radius: 7px; padding: 4px; }
            QPushButton#headerIconBtn:hover { background: #232F40; }
            QPushButton#openEqBtn { background: #1B2431; color: #EDF3FA; border: 1px solid #273445;
                border-radius: 8px; font-weight: 600; font-size: 12px; padding: 6px 10px; text-align: left; }
            QPushButton#openEqBtn:hover { background: #243142; border-color: #405267; }
            QPushButton#openEqBtn[eqActive="true"] { background: #162B26; color: #77E0BE; border-color: #2D5A4E; }
            QFrame#signalPathCard { background: #0F151E; border: 1px solid #1E2A3A; border-radius: 8px; }
            QLabel#signalDot { border-radius: 3px; background: #526173; }
            QLabel#signalDot[active="true"] { background: #77E0BE; }
            QLabel#signalPathText { color: #9AAABC; font-size: 11px; }
            QPushButton#advancedToggleBtn { background: transparent; border: none; color: #8FA2B7;
                font-size: 12px; font-weight: 500; text-align: left; padding: 2px 0; }
            QPushButton#advancedToggleBtn:hover { color: #EDF3FA; }
            QFrame#advancedDivider { background: #202B38; max-height: 1px; border: none; }
        ''')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Clean header: Title + subtle state + 2 icon buttons
        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        title = QLabel('Âm thanh')
        title.setObjectName('panelTitle')
        hdr.addWidget(title)

        self.status = QLabel('Nguyên bản')
        self.status.setObjectName('panelStatus')
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hdr.addWidget(self.status, stretch=1)

        self.btn_recommended = QPushButton()
        self.btn_recommended.setObjectName('headerIconBtn')
        self.btn_recommended.setFixedSize(28, 28)
        button_icon(self.btn_recommended, 'sparkles', 'Cấu hình khuyên dùng', color=ACCENT, size=15, icon_only=True)
        hdr.addWidget(self.btn_recommended)

        self.reset = QPushButton()
        self.reset.setObjectName('headerIconBtn')
        self.reset.setFixedSize(28, 28)
        button_icon(self.reset, 'rotate-ccw', 'Tắt xử lý (âm thanh gốc)', color=MUTED, size=15, icon_only=True)
        hdr.addWidget(self.reset)
        layout.addLayout(hdr)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setFixedHeight(2)
        self.busy.setTextVisible(False)
        self.busy.hide()
        layout.addWidget(self.busy)

        # Primary 3 clean horizontal rows
        self.preset_combo = QComboBox()
        for text, key in (
            ('Chuẩn Hi-Fi (Hợp nhất)', 'master_hifi'),
            ('Dawn Pro 2 · Aria 2', 'studio_dawn_aria2'),
            ('DAC Rời · Bit-Perfect', 'dac_bitperfect'),
            ('YouTube', 'youtube'),
            ('Nguyên bản', 'bit_pure'),
            ('Sống động', 'walkman_vivid'),
            ('Tắt', 'bypass'),
            ('Tùy chỉnh', 'custom'),
        ):
            self.preset_combo.addItem(text, key)
        self.preset_combo.setToolTip(
            'Chọn nhanh cấu hình nghe.\n'
            'Mẹo YouTube: ở trang Tải xuống chọn Original hoặc Opus để giữ nguyên luồng âm thanh.'
        )
        self._form_row(layout, 'Chế độ', self.preset_combo)

        self.device_combo = QComboBox()
        self.device_combo.addItem('Mặc định hệ thống', '')
        self.device_combo.view().setMinimumWidth(290)
        self.device_combo.setToolTip(
            'Chọn trực tiếp USB DAC (như Dawn Pro 2) để phát độc lập với âm thanh hệ thống.'
        )
        self._form_row(layout, 'Thiết bị', self.device_combo)

        self.tone = QComboBox()
        for text, key in (
            ('Tự nhiên', 'off'),
            ('Chuẩn Hi-Fi · Hợp nhất', 'master_hifi'),
            ('Aria 2 · Phòng thu', 'studio_aria2'),
            ('Loa kiểm âm 30°', 'studio_room'),
            ('Sống động', 'walkman_vivid'),
            ('Aria 2 · Cân bằng', 'aria2'),
            ('Rõ giọng hát', 'vocal_clear'),
            ('Ấm mượt', 'warm'),
            ('Tai nghe', 'headphones'),
            ('Dịu nhẹ', 'gentle'),
            ('Cân bằng', 'balanced'),
            ('Dễ nghe (Loa)', 'easy'),
            ('Dễ nghe (Tai nghe)', 'easy_headphones'),
        ):
            self.tone.addItem(text, key)
        self.tone.setItemData(
            self.tone.findData('studio_aria2'),
            'Tinh chỉnh tham chiếu cho Moondrop Aria 2 kèm không gian loa kiểm âm 30°.',
            Qt.ItemDataRole.ToolTipRole,
        )
        self.tone.setItemData(
            self.tone.findData('aria2'),
            'Tinh chỉnh cân bằng nhẹ cho Moondrop Aria 2.',
            Qt.ItemDataRole.ToolTipRole,
        )
        self._form_row(layout, 'Âm sắc', self.tone)

        # Clean Equalizer trigger button
        self.btn_open_eq = QPushButton('Equalizer')
        self.btn_open_eq.setObjectName('openEqBtn')
        self.btn_open_eq.setFixedHeight(34)
        self.btn_open_eq.setToolTip('Mở Equalizer 10 dải, Preamp và Crossfeed.')
        button_icon(self.btn_open_eq, 'sliders-horizontal', color=TEXT, size=15, icon_only=False)
        self.btn_open_eq.clicked.connect(self._request_open_eq)
        layout.addWidget(self.btn_open_eq)

        # Minimal single-strip signal path badge (full technical detail in tooltip)
        card = QFrame()
        card.setObjectName('signalPathCard')
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(10, 7, 10, 7)
        card_layout.setSpacing(8)
        self.signal_dot = QLabel()
        self.signal_dot.setObjectName('signalDot')
        self.signal_dot.setFixedSize(6, 6)
        self.signal_path = QLabel('Mặc định hệ thống')
        self.signal_path.setObjectName('signalPathText')
        self.signal_path.setWordWrap(True)
        self.signal_path.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.signal_path.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        card_layout.addWidget(self.signal_dot)
        card_layout.addWidget(self.signal_path, stretch=1)
        layout.addWidget(card)

        # Collapsible Advanced disclosure (collapsed by default)
        self.btn_advanced = QPushButton('Tùy chọn nâng cao  ▾')
        self.btn_advanced.setObjectName('advancedToggleBtn')
        self.btn_advanced.clicked.connect(self._toggle_advanced)
        layout.addWidget(self.btn_advanced)

        self.advanced_box = QWidget()
        adv_layout = QVBoxLayout(self.advanced_box)
        adv_layout.setContentsMargins(0, 2, 0, 0)
        adv_layout.setSpacing(8)

        div = QFrame()
        div.setObjectName('advancedDivider')
        div.setFrameShape(QFrame.Shape.HLine)
        adv_layout.addWidget(div)

        self.output_mode = QComboBox()
        self.output_mode.addItem('Chia sẻ (Shared)', 'shared')
        self.output_mode.addItem('Độc quyền (Exclusive)', 'exclusive')
        self.output_mode.setToolTip(
            'Shared: nghe chung với ứng dụng khác. Exclusive: đi thẳng vào USB DAC bỏ qua bộ trộn Windows.'
        )
        self._form_row(adv_layout, 'Đầu ra', self.output_mode)

        self.upsample = QComboBox()
        for text, key in (
            ('Tần số gốc', 'off'),
            ('176.4 / 192 kHz', 'hires_sync'),
            ('352.8 / 384 kHz', 'max_dac'),
        ):
            self.upsample.addItem(text, key)
        self.upsample.setToolTip('Nâng mẫu SoXR 33-bit đồng bộ khi dùng WASAPI Exclusive trên USB DAC.')
        self._form_row(adv_layout, 'Lấy mẫu', self.upsample)

        self.dac_phase = QComboBox()
        self.dac_phase.addItem('Tuyến tính (Linear)', 'linear')
        self.dac_phase.addItem('Tối thiểu (Minimum)', 'minimum')
        self.dac_phase.setToolTip(
            'Tuyến tính: SoXR 33-bit không xoay pha. Tối thiểu: lọc trễ pha cực tiểu loại bỏ hoàn toàn pre-ringing khi nâng mẫu.'
        )
        self._form_row(adv_layout, 'Pha DAC', self.dac_phase)

        norm_wrap = QWidget()
        norm_row = QHBoxLayout(norm_wrap)
        norm_row.setContentsMargins(0, 0, 0, 0)
        norm_row.setSpacing(8)
        self.normalize = QCheckBox('')
        self.normalize.setToolTip('Bật cân bằng âm lượng tự động theo chuẩn LUFS.')
        self.level = QComboBox()
        self.level.addItem('−16 LUFS (Chuẩn)', -16)
        self.level.addItem('−14 LUFS (To rõ)', -14)
        self.level.addItem('−18 LUFS (Tự nhiên)', -18)
        self.level.addItem('YouTube (−14 LUFS)', 'youtube')
        self.level.setFixedHeight(32)
        self.level.setEnabled(False)
        norm_row.addWidget(self.normalize)
        norm_row.addWidget(self.level, stretch=1)
        self._form_row(adv_layout, 'Âm lượng', norm_wrap)

        self.restorer = QComboBox()
        for text, key in (
            ('Tắt', 'off'),
            ('Tự động', 'auto'),
            ('Nhẹ', 'natural'),
            ('Rõ nét', 'vivid'),
        ):
            self.restorer.addItem(text, key)
        self.restorer.setToolTip('Bù dải cao dịu nhẹ cho nhạc MP3/AAC cũ; tự bỏ qua Opus và Lossless.')
        self._form_row(adv_layout, 'Nhạc nén', self.restorer)

        self.per_device_cb = QCheckBox('Nhớ riêng từng thiết bị')
        self.per_device_cb.setChecked(True)
        self.per_device_cb.setToolTip('Tự chuyển cấu hình & EQ khi cắm DAC hoặc đổi tai nghe/loa.')
        adv_layout.addWidget(self.per_device_cb)

        self.prefetch_next = QCheckBox('Đo trước bài kế tiếp')
        self.prefetch_next.setToolTip('Đo nhanh LUFS bài tiếp theo trong RAM để chuyển bài tức thì.')
        self.prefetch_next.setChecked(True)
        self.prefetch_next.setEnabled(False)
        self.prefetch_next.toggled.connect(self.prefetch_changed.emit)
        adv_layout.addWidget(self.prefetch_next)

        self.btn_open_benchmark = QPushButton('Đo kiểm chất âm…')
        self.btn_open_benchmark.setFixedHeight(30)
        self.btn_open_benchmark.setToolTip('Mở tab đo phổ tần số và so sánh file gốc với cấu hình hiện tại.')
        self.btn_open_benchmark.clicked.connect(self._request_open_benchmark)
        adv_layout.addWidget(self.btn_open_benchmark)

        self.advanced_box.hide()
        layout.addWidget(self.advanced_box)

        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        self.per_device_cb.toggled.connect(self.per_device_changed.emit)
        self.normalize.toggled.connect(self._emit_settings)
        self.level.currentIndexChanged.connect(self._on_level_changed)
        self.tone.currentIndexChanged.connect(self._emit_settings)
        self.restorer.currentIndexChanged.connect(self._emit_settings)
        self.output_mode.currentIndexChanged.connect(self._emit_settings)
        self.upsample.currentIndexChanged.connect(self._emit_settings)
        self.dac_phase.currentIndexChanged.connect(self._on_dac_phase_selected)
        self.btn_recommended.clicked.connect(self._apply_recommended)
        self.reset.clicked.connect(self._reset)

    def _on_dac_phase_selected(self, *_):
        self._sync_preset_combo()
        self.dac_phase_changed.emit(str(self.dac_phase.currentData() or 'linear'))

    def _form_row(self, parent_layout, label_text: str, widget: QWidget):
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel(label_text)
        lbl.setObjectName('formLabel')
        lbl.setFixedWidth(84)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if isinstance(widget, QComboBox):
            widget.setFixedHeight(32)
        row.addWidget(lbl)
        row.addWidget(widget, stretch=1)
        parent_layout.addLayout(row)

    def _toggle_advanced(self):
        from ui.i18n import translate_text
        opening = self.advanced_box.isHidden()
        self.advanced_box.setVisible(opening)
        self.btn_advanced.setText(translate_text('Tùy chọn nâng cao  ▴' if opening else 'Tùy chọn nâng cao  ▾'))
        self.adjustSize()
        if self.isVisible() and self._anchor_button is not None:
            self.open_at(self._anchor_button)

    def retranslate_ui(self, lang: str | None = None):
        from ui.i18n import translate_text, translate_widget_tree
        translate_widget_tree(self, lang)
        opening = not self.advanced_box.isHidden()
        self.btn_advanced.setText(translate_text('Tùy chọn nâng cao  ▴' if opening else 'Tùy chọn nâng cao  ▾', lang))
        self._refresh_eq_button()
        sig = getattr(self, '_last_signal_args', None)
        if sig is not None:
            self.set_signal_path(*sig)

    def _on_device_selected(self, *_):
        self._output_device = str(self.device_combo.currentData() or '')
        self._sync_preset_combo()
        self.output_device_changed.emit(self._output_device)

    def set_output_devices(self, devices: list[str], selected_device: str = ''):
        sel = (selected_device or '').strip()
        self._output_device = sel
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem('Mặc định hệ thống', '')
        seen = set()
        for dev in devices or ():
            clean = str(dev or '').strip()
            if clean and clean.lower() not in seen:
                seen.add(clean.lower())
                self.device_combo.addItem(clean, clean)
        if sel and sel.lower() not in seen:
            self.device_combo.addItem(f'{sel} (Chưa cắm)', sel)
        idx = self.device_combo.findData(sel)
        if idx < 0 and sel:
            for i in range(self.device_combo.count()):
                data = str(self.device_combo.itemData(i) or '')
                if data and data.lower() == sel.lower():
                    idx = i
                    break
        self.device_combo.setCurrentIndex(max(0, idx))
        self.device_combo.blockSignals(False)
        self._sync_preset_combo()

    def set_per_device_memory(self, enabled: bool):
        self.per_device_cb.blockSignals(True)
        self.per_device_cb.setChecked(bool(enabled))
        self.per_device_cb.blockSignals(False)

    def _request_open_eq(self):
        self.hide()
        self.open_eq_requested.emit()

    def _request_open_benchmark(self):
        self.hide()
        self.open_benchmark_requested.emit()

    def _refresh_eq_button(self):
        from ui.i18n import translate_text
        active = bool(self._eq_state.get('eq_enabled'))
        peq = normalize_peq_filters(self._eq_state.get('eq_peq_filters'))
        self.btn_open_eq.setProperty('eqActive', active)
        self.btn_open_eq.style().unpolish(self.btn_open_eq)
        self.btn_open_eq.style().polish(self.btn_open_eq)
        if active and peq:
            self.btn_open_eq.setText(translate_text(f'Equalizer  ·  PEQ {len(peq)} dải'))
            button_icon(self.btn_open_eq, 'sliders-horizontal', color=ACCENT, size=15, icon_only=False)
        elif active:
            self.btn_open_eq.setText(translate_text('Equalizer  ·  Đang bật'))
            button_icon(self.btn_open_eq, 'sliders-horizontal', color=ACCENT, size=15, icon_only=False)
        else:
            self.btn_open_eq.setText('Equalizer')
            button_icon(self.btn_open_eq, 'sliders-horizontal', color=TEXT, size=15, icon_only=False)

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
            output_device=self._output_device,
            dac_phase=str(self.dac_phase.currentData() or 'linear'),
            **self._eq_state,
        )
        key = detect_preset(prof, self._current_target_lufs())
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(key)))
        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, *_):
        key = self.preset_combo.currentData()
        if key == 'custom' or not key:
            return
        if key == 'master_hifi':
            self.recommended_requested.emit()
            return
        prof, lufs = preset_profile(key)
        eq_state = dict(self._eq_state)
        if key == 'bypass':
            eq_state['eq_enabled'] = False
        self.set_profile(
            prof.normalize,
            prof.tone,
            prof.restorer,
            prof.output_mode,
            prof.upsample,
            prof.youtube_loudness,
            target_lufs=lufs,
            eq_state=eq_state,
            dac_phase=prof.dac_phase,
        )
        # Emit settings FIRST so AudioEffectsController updates profile fields
        # before dac_phase_changed/level_changed sync panel widgets back.
        self._emit_settings()
        self.dac_phase_changed.emit(prof.dac_phase)
        if isinstance(lufs, int) and key != 'youtube':
            self.level_changed.emit(int(lufs))

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
            or bool(self._eq_state.get('eq_enabled')) or bool(self._output_device)
        )
        self.level.setEnabled(checked)
        self.prefetch_next.setEnabled(any_enabled)
        self._sync_preset_combo()
        self.settings_changed.emit(norm, tone_val, rest_val, out_val, up_val, yt_loud)

    def _apply_recommended(self):
        self.recommended_requested.emit()

    def _reset(self):
        eq_state = dict(self._eq_state)
        eq_state['eq_enabled'] = False
        self.set_profile(False, 'off', 'off', 'shared', 'off', False, eq_state=eq_state, output_device='', dac_phase='linear')
        # Emit settings FIRST so dac_phase_changed/output_device_changed do not
        # revert widgets to the old profile before _emit_settings reads them.
        self._emit_settings()
        self.output_device_changed.emit('')
        self.dac_phase_changed.emit('linear')

    def set_profile(
        self,
        normalize,
        tone,
        restorer='off',
        output_mode='shared',
        upsample='off',
        youtube_loudness=False,
        target_lufs=None,
        eq_state=None,
        output_device=None,
        dac_phase=None,
    ):
        widgets = (
            self.preset_combo, self.device_combo, self.normalize, self.level,
            self.tone, self.restorer, self.output_mode, self.upsample, self.dac_phase,
        )
        for w in widgets:
            w.blockSignals(True)
        if output_device is not None:
            self._output_device = str(output_device or '').strip()
            idx_d = self.device_combo.findData(self._output_device)
            if idx_d < 0 and self._output_device:
                self.device_combo.addItem(f'{self._output_device} (Chưa cắm)', self._output_device)
                idx_d = self.device_combo.findData(self._output_device)
            self.device_combo.setCurrentIndex(max(0, idx_d))
        if isinstance(eq_state, dict):
            for k in ('eq_enabled', 'eq_bands', 'eq_peq_filters', 'eq_preamp_db', 'eq_auto_preamp', 'eq_bass_db', 'eq_treble_db', 'eq_crossfeed'):
                if k in eq_state:
                    self._eq_state[k] = eq_state[k]
        if dac_phase is not None:
            phase_val = 'minimum' if dac_phase == 'minimum' else 'linear'
            self.dac_phase.setCurrentIndex(max(0, self.dac_phase.findData(phase_val)))
        yt_loud = bool(youtube_loudness)
        checked = bool(normalize or yt_loud)
        any_enabled = (
            checked or tone != 'off' or restorer != 'off'
            or output_mode == 'exclusive' or upsample != 'off'
            or bool(self._eq_state.get('eq_enabled')) or bool(self._output_device)
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
        self._refresh_eq_button()
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

    def set_signal_path(self, source_text: str, dsp_text: str, output_text: str, tooltip: str = ''):
        from ui.i18n import translate_text
        self._last_signal_args = (source_text, dsp_text, output_text, tooltip)
        raw_line = f'{source_text}  ›  {dsp_text}  ›  {output_text}'
        raw_tip = tooltip or f'Nguồn: {source_text}\nXử lý: {dsp_text}\nĐầu ra: {output_text}'
        self.signal_path.setText(translate_text(raw_line))
        self.signal_path.setToolTip(translate_text(raw_tip))
        is_active = dsp_text not in ('Nguyên gốc', 'Tắt', 'Bypass')
        self.signal_dot.setProperty('active', bool(is_active))
        self.signal_dot.style().unpolish(self.signal_dot)
        self.signal_dot.style().polish(self.signal_dot)

    def set_status(self, text, busy=False):
        from ui.i18n import translate_text
        self.status.setText(translate_text(text) if text else '')
        self.busy.setVisible(busy)

    def open_at(self, button):
        self._anchor_button = button
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
