"""Commercial Hi-Fi Studio Settings view adapter (composes SettingsPage & VolumeSettings without altering frozen contracts)."""
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.audio_profile import detect_preset, normalize_peq_filters
from ui.design_system import FORM_STYLE
from ui.icons import ACCENT, INK, MUTED, TEXT, button_icon

_PORTAL_LINKS = {
    'Google Gemini': ('Google AI Studio', 'https://aistudio.google.com/apikey'),
    'OpenAI (GPT-4o)': ('OpenAI Platform', 'https://platform.openai.com/api-keys'),
    'Claude 3.5': ('Anthropic Console', 'https://console.anthropic.com/settings/keys'),
}

_STUDIO_STYLE = FORM_STYLE + '''
    QWidget#settingsPageHost { background: #0D1118; font-family: 'Segoe UI'; }
    QLabel { color: #EDF3FA; background: transparent; border: none; }
    QLabel#studioTitle { font-size: 22px; font-weight: 700; color: #EDF3FA; }
    QLabel#studioSubtitle { font-size: 12px; color: #8FA2B7; }
    QFrame#studioCard { background: #131A24; border: 1px solid #202C3C; border-radius: 12px; }
    QLabel#studioCardTitle { font-size: 14px; font-weight: 700; color: #EDF3FA; }
    QLabel#studioRowTitle { font-size: 13px; font-weight: 600; color: #EDF3FA; }
    QLabel#studioRowDesc { font-size: 11px; color: #8FA2B7; }
    QLabel#studioBadge { background: #16332B; color: #77E0BE; border: 1px solid #2D5A4E;
        border-radius: 6px; padding: 3px 10px; font-size: 11px; font-weight: 600; }
    QLabel#studioBadge[tone="neutral"] { background: #1A232E; color: #9AAABC; border-color: #2B394B; }
    QLabel#studioLink { font-size: 11px; color: #8FA2B7; }
    QFrame#studioDivider { background: #1C2635; max-height: 1px; min-height: 1px; border: none; }
    QPushButton#studioSubBtn { background: #1A232E; color: #EDF3FA; border: 1px solid #283648;
        border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; }
    QPushButton#studioSubBtn:hover { background: #233040; border-color: #3E526A; }
    QPushButton#studioOptBtn { background: #162B26; color: #77E0BE; border: 1px solid #2D5A4E;
        border-radius: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; }
    QPushButton#studioOptBtn:hover { background: #1E3A33; border-color: #77E0BE; }
    QPushButton#studioEyeBtn { background: #18212D; color: #9AAABC; border: 1px solid #273445;
        border-radius: 8px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
    QPushButton#studioEyeBtn:hover { background: #222F40; color: #EDF3FA; }
    QPushButton#studioEyeBtn:disabled { color: #526173; border-color: #1D2734; }
    QScrollArea#studioScroll { background: transparent; border: none; }
    QWidget#studioScrollBody { background: transparent; border: none; }
    QSlider::groove:horizontal { height: 4px; background: #243242; border-radius: 2px; }
    QSlider::sub-page:horizontal { background: #77E0BE; border-radius: 2px; }
    QSlider::handle:horizontal { background: #EDF3FA; border: 2px solid #77E0BE;
        width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
    QScrollBar:vertical { background: #0D1118; width: 8px; border-radius: 4px; }
    QScrollBar::handle:vertical { background: #263447; border-radius: 4px; min-height: 28px; }
    QScrollBar::handle:vertical:hover { background: #364A64; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
'''


class SettingsStudioView(QObject):
    """Commercial single-column card layout around the frozen SettingsPage & VolumeSettings owners."""

    def __init__(self, controller):
        self.controller = controller
        self.page = controller.window.settings_page
        super().__init__(self.page)
        self._volume_adopted = False
        self._syncing_volume = False
        self._build_ui()
        self.page.installEventFilter(self)
        QTimer.singleShot(0, self._adopt_volume_controls)
        self.sync_from_controller()

    def _build_ui(self):
        page = self.page
        page.setObjectName('settingsPageHost')
        page.setMinimumSize(0, 0)
        page.setStyleSheet(_STUDIO_STYLE)

        root = page.layout()
        # Preserve legacy widgets/content_layout inside a hidden owner bin so VolumeSettings & contracts stay intact.
        self._legacy_bin = QWidget(page)
        self._legacy_bin.hide()
        self._legacy_bin.setFixedSize(0, 0)
        if root is not None:
            while root.count():
                item = root.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(self._legacy_bin)
                    w.hide()
        else:
            root = QVBoxLayout(page)

        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(12)

        # Clean header bar + Reset / Save actions
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        self.lbl_title = QLabel('Cài đặt')
        self.lbl_title.setObjectName('studioTitle')
        self.lbl_subtitle = QLabel('Âm thanh phòng thu, mô hình AI nhận diện lời và dịch vụ dịch thuật.')
        self.lbl_subtitle.setObjectName('studioSubtitle')
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        title_col.addWidget(self.lbl_title)
        title_col.addWidget(self.lbl_subtitle)
        hdr.addLayout(title_col, stretch=1)

        page.btn_reset.setText('Đặt lại mặc định')
        page.btn_reset.setMinimumSize(132, 36)
        page.btn_reset.setMaximumWidth(175)
        page.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(page.btn_reset, 'rotate-ccw', 'Đặt lại tất cả về mặc định', color=MUTED, size=14, icon_only=False)
        hdr.addWidget(page.btn_reset)

        page.btn_save.setText('Lưu cài đặt')
        page.btn_save.setProperty('role', 'primary')
        page.btn_save.setMinimumSize(124, 36)
        page.btn_save.setMaximumWidth(165)
        page.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(page.btn_save, 'save', 'Lưu cài đặt', color=INK, size=14, icon_only=False)
        hdr.addWidget(page.btn_save)
        root.addLayout(hdr)

        # Centered commercial scroll area
        self.scroll = QScrollArea(page)
        self.scroll.setObjectName('studioScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_host = QWidget()
        scroll_host.setObjectName('studioScrollBody')
        outer_h = QHBoxLayout(scroll_host)
        outer_h.setContentsMargins(0, 2, 4, 16)
        outer_h.setSpacing(0)

        col_wrap = QWidget()
        col_wrap.setObjectName('studioScrollBody')
        col_wrap.setMaximumWidth(880)
        col_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.cards_layout = QVBoxLayout(col_wrap)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)

        self._build_audio_card()
        self._build_asr_card()
        self._build_translation_card()
        self.cards_layout.addStretch()

        outer_h.addStretch(1)
        outer_h.addWidget(col_wrap, stretch=100)
        outer_h.addStretch(1)
        self.scroll.setWidget(scroll_host)
        root.addWidget(self.scroll, stretch=1)

    def _make_card(self, title_text: str, right_widget: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName('studioCard')
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        lbl = QLabel(title_text)
        lbl.setObjectName('studioCardTitle')
        top.addWidget(lbl)
        top.addStretch()
        if right_widget is not None:
            top.addWidget(right_widget)
        lay.addLayout(top)

        div = QFrame()
        div.setObjectName('studioDivider')
        div.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(div)
        return card, lay

    def _add_card_row(
        self,
        parent_lay: QVBoxLayout,
        title_text: str,
        desc_text: str,
        control: QWidget,
        footer_widget: QWidget | None = None,
    ) -> QLabel:
        div = None
        if parent_lay.count() > 2:
            div = QFrame()
            div.setObjectName('studioDivider')
            div.setFrameShape(QFrame.Shape.HLine)
            parent_lay.addWidget(div)

        row_wrap = QVBoxLayout()
        row_wrap.setContentsMargins(0, 2, 0, 2)
        row_wrap.setSpacing(4)

        h = QHBoxLayout()
        h.setSpacing(14)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(2)
        lbl_t = QLabel(title_text)
        lbl_t.setObjectName('studioRowTitle')
        lbl_t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        left.addWidget(lbl_t)
        if desc_text:
            lbl_d = QLabel(desc_text)
            lbl_d.setObjectName('studioRowDesc')
            lbl_d.setWordWrap(True)
            lbl_d.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            lbl_d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            left.addWidget(lbl_d)
        else:
            lbl_d = lbl_t

        control.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        h.addLayout(left, stretch=1)
        h.addWidget(control, alignment=Qt.AlignmentFlag.AlignVCenter)
        row_wrap.addLayout(h)

        if footer_widget is not None:
            row_wrap.addWidget(footer_widget)
        parent_lay.addLayout(row_wrap)
        return lbl_d

    def _build_audio_card(self):
        self.lbl_audio_badge = QLabel('Chuẩn Hi-Fi · −14 LUFS')
        self.lbl_audio_badge.setObjectName('studioBadge')
        self.audio_card, lay = self._make_card('Âm thanh & Thiết bị', self.lbl_audio_badge)

        # Row 1: Preset + One-click optimal master restore
        preset_ctrl = QWidget()
        preset_ctrl.setFixedWidth(340)
        ph = QHBoxLayout(preset_ctrl)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(8)
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedHeight(34)
        for text, key in (
            ('Chuẩn Hi-Fi (Hợp nhất)', 'master_hifi'),
            ('Dawn Pro 2 · Aria 2', 'studio_dawn_aria2'),
            ('DAC Rời · Bit-Perfect', 'dac_bitperfect'),
            ('Nguyên bản', 'bit_pure'),
            ('YouTube', 'youtube'),
            ('Sống động', 'walkman_vivid'),
            ('Tắt (Bypass)', 'bypass'),
            ('Tùy chỉnh', 'custom'),
        ):
            self.preset_combo.addItem(text, key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        self.btn_optimal_preset = QPushButton('Tối ưu')
        self.btn_optimal_preset.setObjectName('studioOptBtn')
        self.btn_optimal_preset.setFixedHeight(34)
        self.btn_optimal_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(
            self.btn_optimal_preset,
            'sparkles',
            'Tự động chọn cấu hình nghe tối ưu nhất theo thiết bị đang phát',
            color=ACCENT,
            size=14,
            icon_only=False,
        )
        self.btn_optimal_preset.clicked.connect(self.controller.apply_unified_master_preset)
        ph.addWidget(self.preset_combo, stretch=1)
        ph.addWidget(self.btn_optimal_preset)
        self._add_card_row(
            lay,
            'Chế độ nghe',
            'Tự chuẩn hóa −14 LUFS chống vỡ đỉnh 0 dBTP, giữ 100% chi tiết gốc và tự thích ứng DAC rời.',
            preset_ctrl,
        )

        # Row 2: Output device selector
        self.device_combo = QComboBox()
        self.device_combo.setFixedWidth(340)
        self.device_combo.setFixedHeight(34)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self._add_card_row(
            lay,
            'Thiết bị phát',
            'Gắn trực tiếp USB DAC (như Moondrop Dawn Pro 2) để chạy WASAPI Exclusive bỏ qua bộ trộn Windows.',
            self.device_combo,
        )

        # Row 3: Volume slider + VolumeSettings spinbox slot
        vol_ctrl = QWidget()
        vol_ctrl.setFixedWidth(340)
        vh = QHBoxLayout(vol_ctrl)
        vh.setContentsMargins(0, 0, 0, 0)
        vh.setSpacing(10)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(round(self.controller.volume() * 100)))
        self.volume_slider.valueChanged.connect(self._on_volume_slider_changed)
        vh.addWidget(self.volume_slider, stretch=1)
        self._volume_spin_slot = vh

        self._volume_hint_slot = QVBoxLayout()
        self._volume_hint_slot.setContentsMargins(0, 0, 0, 0)
        self._volume_hint_slot.setSpacing(0)
        hint_wrap = QWidget()
        hint_wrap.setLayout(self._volume_hint_slot)
        self._add_card_row(
            lay,
            'Âm lượng phát',
            '',
            vol_ctrl,
            footer_widget=hint_wrap,
        )

        # Row 4: Equalizer + Audio Benchmark tools
        tools_ctrl = QWidget()
        tools_ctrl.setFixedWidth(340)
        th = QHBoxLayout(tools_ctrl)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(8)
        self.btn_open_eq = QPushButton('Equalizer (10 dải / PEQ)')
        self.btn_open_eq.setObjectName('studioSubBtn')
        self.btn_open_eq.setFixedHeight(34)
        self.btn_open_eq.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_open_eq, 'sliders-horizontal', 'Mở Equalizer phòng thu 64-bit', color=TEXT, size=14, icon_only=False)
        self.btn_open_eq.clicked.connect(self.controller.open_equalizer)

        self.btn_benchmark = QPushButton('Đo kiểm âm')
        self.btn_benchmark.setObjectName('studioSubBtn')
        self.btn_benchmark.setFixedHeight(34)
        self.btn_benchmark.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(
            self.btn_benchmark,
            'sliders-horizontal',
            'Mở tab Đo kiểm phổ tần số & Nghe đối chiếu A/B',
            color=ACCENT,
            size=14,
            icon_only=False,
        )
        self.btn_benchmark.clicked.connect(lambda: self.controller.open_benchmark_tab(auto_run=True))
        self.page.btn_audio_benchmark = self.btn_benchmark

        th.addWidget(self.btn_open_eq, stretch=1)
        th.addWidget(self.btn_benchmark)
        self._add_card_row(
            lay,
            'Công cụ phòng thu',
            'Tinh chỉnh PEQ Squiglink/APO chính xác từng dải hoặc mở phòng đo phổ tần số & nghe thử A/B.',
            tools_ctrl,
        )

        self.cards_layout.addWidget(self.audio_card)

    def _build_asr_card(self):
        page = self.page
        self.asr_card, lay = self._make_card('Nhận diện giọng nói · Whisper AI')

        for widget, title_t, desc_t in (
            (page.combo_model, 'Mô hình Whisper', 'Chọn độ chính xác (Base chạy nhanh, Large-v3 chuẩn lời nhạc).'),
            (page.combo_content_mode, 'Loại nội dung', 'Áp dụng khi tạo hoặc dịch phụ đề mới; phụ đề đã lưu giữ nguyên.'),
            (page.combo_device, 'Thiết bị tính toán', 'Ưu tiên CUDA (GPU NVIDIA) nếu máy có card rời để nhận diện nhanh hơn.'),
        ):
            widget.setStyleSheet('')
            widget.setFixedWidth(340)
            widget.setFixedHeight(34)
            self._add_card_row(lay, title_t, desc_t, widget)

        page.btn_download_resource.setStyleSheet('')
        page.btn_download_resource.setText('Tải / Cập nhật mô hình & thư viện AI')
        page.btn_download_resource.setObjectName('studioSubBtn')
        page.btn_download_resource.setFixedHeight(36)
        page.btn_download_resource.setFixedWidth(340)
        page.btn_download_resource.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(page.btn_download_resource, 'download', 'Mở trình tải tài nguyên AI', color=TEXT, size=14, icon_only=False)
        self._add_card_row(
            lay,
            'Tài nguyên ngoại tuyến',
            'Kiểm tra trạng thái cài đặt và tải xuống các gói mô hình Whisper / dịch nội bộ.',
            page.btn_download_resource,
        )
        self.cards_layout.addWidget(self.asr_card)

    def _build_translation_card(self):
        page = self.page
        self.translation_card, lay = self._make_card('Dịch thuật AI & Đối soát Genius')

        page.combo_online_ai.setStyleSheet('')
        page.combo_online_ai.setFixedWidth(340)
        page.combo_online_ai.setFixedHeight(34)
        self._add_card_row(
            lay,
            'Dịch vụ dịch thuật',
            'Chọn mô hình chạy cục bộ hoặc dịch trực tuyến qua API đám mây.',
            page.combo_online_ai,
        )

        page.combo_translation_model.setStyleSheet('')
        page.combo_translation_model.setFixedWidth(340)
        page.combo_translation_model.setFixedHeight(34)
        self._add_card_row(
            lay,
            'Model dịch',
            'Model nhẹ tiết kiệm chi phí; model cao cấp ưu tiên văn phong và ngữ cảnh lời bài hát.',
            page.combo_translation_model,
        )

        # API Key + reveal toggle + provider link
        api_ctrl = QWidget()
        api_ctrl.setFixedWidth(340)
        ah = QHBoxLayout(api_ctrl)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(6)
        page.api_key_input.setStyleSheet('')
        page.api_key_input.setFixedHeight(34)
        self.btn_toggle_api_key = QPushButton('Hiện')
        self.btn_toggle_api_key.setObjectName('studioEyeBtn')
        self.btn_toggle_api_key.setFixedSize(56, 34)
        self.btn_toggle_api_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_api_key.clicked.connect(lambda: self._toggle_echo(page.api_key_input, self.btn_toggle_api_key))
        ah.addWidget(page.api_key_input, stretch=1)
        ah.addWidget(self.btn_toggle_api_key)

        self.lbl_provider_link = QLabel('')
        self.lbl_provider_link.setObjectName('studioLink')
        self.lbl_provider_link.setOpenExternalLinks(True)
        self._add_card_row(
            lay,
            'API Key dịch thuật',
            'Mã xác thực lưu cục bộ trên máy khi dùng dịch vụ AI trực tuyến.',
            api_ctrl,
            footer_widget=self.lbl_provider_link,
        )

        page.combo_genius_mode.setStyleSheet('')
        page.combo_genius_mode.setFixedWidth(340)
        page.combo_genius_mode.setFixedHeight(34)
        self._add_card_row(
            lay,
            'Đối soát lời Genius',
            'Tự đối chiếu lời gốc đáng tin cậy từ Genius để sửa lỗi nghe nhầm của Whisper.',
            page.combo_genius_mode,
        )

        gen_ctrl = QWidget()
        gen_ctrl.setFixedWidth(340)
        gh = QHBoxLayout(gen_ctrl)
        gh.setContentsMargins(0, 0, 0, 0)
        gh.setSpacing(6)
        page.genius_key_input.setStyleSheet('')
        page.genius_key_input.setFixedHeight(34)
        self.btn_toggle_genius_key = QPushButton('Hiện')
        self.btn_toggle_genius_key.setObjectName('studioEyeBtn')
        self.btn_toggle_genius_key.setFixedSize(56, 34)
        self.btn_toggle_genius_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_genius_key.clicked.connect(
            lambda: self._toggle_echo(page.genius_key_input, self.btn_toggle_genius_key)
        )
        gh.addWidget(page.genius_key_input, stretch=1)
        gh.addWidget(self.btn_toggle_genius_key)

        self.lbl_genius_link = QLabel(
            'Lấy Genius Access Token tại: '
            '<a href="https://genius.com/api-clients" style="color: #77E0BE; text-decoration: none;">Genius API Clients</a>'
        )
        self.lbl_genius_link.setObjectName('studioLink')
        self.lbl_genius_link.setOpenExternalLinks(True)
        self._add_card_row(
            lay,
            'Genius Access Token',
            'Bắt buộc khi bật chế độ đối soát lời gốc Genius cho nhạc có lời.',
            gen_ctrl,
            footer_widget=self.lbl_genius_link,
        )

        page.combo_online_ai.currentTextChanged.connect(self._refresh_provider_link)
        page.combo_content_mode.currentIndexChanged.connect(self._refresh_genius_state)
        self._refresh_provider_link()
        self._refresh_genius_state()
        self.cards_layout.addWidget(self.translation_card)

    def _adopt_volume_controls(self):
        if self._volume_adopted:
            return
        spin = getattr(self.page, 'volume_percent', None)
        if spin is None:
            return
        self._volume_adopted = True
        old_panel = spin.parentWidget()
        hint_lbl = None
        if old_panel is not None:
            for lbl in old_panel.findChildren(QLabel):
                if '50%' in lbl.text() or 'storage' in lbl.text().lower():
                    hint_lbl = lbl
                    break

        spin.setStyleSheet(
            'QSpinBox { background: #151C26; color: #EDF3FA; border: 1px solid #273445; '
            'border-radius: 8px; padding: 4px 8px; font-weight: 600; } '
            'QSpinBox:focus { border-color: #77E0BE; }'
        )
        spin.setFixedSize(78, 34)
        self._volume_spin_slot.addWidget(spin)
        spin.show()
        spin.valueChanged.connect(self._on_volume_spin_changed)
        self._on_volume_spin_changed(spin.value())

        if hint_lbl is not None:
            hint_lbl.setStyleSheet('color: #8FA2B7; font-size: 11px; margin-left: 0px;')
            hint_lbl.setWordWrap(True)
            hint_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            hint_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            self._volume_hint_slot.addWidget(hint_lbl)
            hint_lbl.show()
        if old_panel is not None and old_panel is not self.page:
            old_panel.hide()

    def _on_volume_slider_changed(self, value: int):
        if self._syncing_volume:
            return
        self._syncing_volume = True
        try:
            spin = getattr(self.page, 'volume_percent', None)
            if spin is not None and spin.value() != value:
                spin.setValue(int(value))
            else:
                self.controller.set_volume(value / 100.0)
        finally:
            self._syncing_volume = False

    def _on_volume_spin_changed(self, value: int):
        if self._syncing_volume:
            return
        self._syncing_volume = True
        try:
            if self.volume_slider.value() != value:
                self.volume_slider.setValue(int(value))
        finally:
            self._syncing_volume = False

    @staticmethod
    def _toggle_echo(line_edit: QLineEdit, btn: QPushButton):
        showing = line_edit.echoMode() == QLineEdit.EchoMode.Normal
        line_edit.setEchoMode(QLineEdit.EchoMode.Password if showing else QLineEdit.EchoMode.Normal)
        btn.setText('Hiện' if showing else 'Ẩn')

    def _refresh_provider_link(self, *_):
        provider = self.page.combo_online_ai.currentText()
        if provider == 'Local Default':
            self.page.api_key_input.setEnabled(False)
            self.btn_toggle_api_key.setEnabled(False)
            self.lbl_provider_link.setText('Đang dùng dịch cục bộ NLLB-200 ngoại tuyến (không cần API Key).')
            return
        self.page.api_key_input.setEnabled(True)
        self.btn_toggle_api_key.setEnabled(True)
        name, url = _PORTAL_LINKS.get(provider, ('OpenAI Platform', 'https://platform.openai.com/api-keys'))
        self.lbl_provider_link.setText(
            f'Lấy key tại: <a href="{url}" style="color: #77E0BE; text-decoration: none;">{name}</a>'
        )

    def _refresh_genius_state(self, *_):
        enabled = bool(self.page.genius_key_input.isEnabled())
        self.btn_toggle_genius_key.setEnabled(enabled)

    def _on_preset_changed(self, *_):
        key = self.preset_combo.currentData()
        if not key or key == 'custom':
            return
        if key == 'master_hifi':
            self.controller.apply_unified_master_preset()
            return
        panel = self.controller.panel
        idx = panel.preset_combo.findData(key)
        if idx >= 0:
            panel.preset_combo.setCurrentIndex(idx)

    def _on_device_changed(self, *_):
        dev = str(self.device_combo.currentData() or '')
        self.controller.set_output_device(dev)

    def sync_from_controller(self):
        self._adopt_volume_controls()
        ctrl = self.controller
        panel = ctrl.panel

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for i in range(panel.device_combo.count()):
            self.device_combo.addItem(panel.device_combo.itemText(i), panel.device_combo.itemData(i))
        self.device_combo.setCurrentIndex(max(0, panel.device_combo.currentIndex()))
        self.device_combo.blockSignals(False)

        preset_key = detect_preset(ctrl.profile, ctrl.target_lufs)
        self.preset_combo.blockSignals(True)
        idx = self.preset_combo.findData(preset_key)
        self.preset_combo.setCurrentIndex(idx if idx >= 0 else max(0, self.preset_combo.findData('custom')))
        self.preset_combo.blockSignals(False)

        peq = normalize_peq_filters(getattr(ctrl.profile, 'eq_peq_filters', ()))
        if ctrl.profile.eq_enabled and peq:
            self.btn_open_eq.setText(f'Equalizer · PEQ {len(peq)} dải')
        elif ctrl.profile.eq_enabled:
            self.btn_open_eq.setText('Equalizer · Đang bật')
        else:
            self.btn_open_eq.setText('Equalizer (10 dải / PEQ)')

        if not ctrl.profile.enabled:
            self.lbl_audio_badge.setText('Nguyên gốc (Bypass)')
            self.lbl_audio_badge.setProperty('tone', 'neutral')
        else:
            preset_lbl = self.preset_combo.currentText()
            st = ctrl.stream.status_info()
            sr = int(st.get('sample_rate') or 0) if st.get('active') else 0
            if st.get('active') and st.get('output_mode') == 'exclusive' and sr > 0:
                self.lbl_audio_badge.setText(f'{preset_lbl} · Exclusive {sr / 1000.0:g} kHz')
            elif ctrl.profile.output_mode == 'exclusive':
                self.lbl_audio_badge.setText(f'{preset_lbl} · DAC Exclusive')
            elif ctrl.profile.youtube_loudness:
                self.lbl_audio_badge.setText(f'{preset_lbl} · −14 LUFS')
            elif ctrl.profile.normalize:
                self.lbl_audio_badge.setText(f'{preset_lbl} · {ctrl.target_lufs} LUFS')
            else:
                self.lbl_audio_badge.setText(preset_lbl)
            self.lbl_audio_badge.setProperty('tone', 'good')
        self.lbl_audio_badge.style().unpolish(self.lbl_audio_badge)
        self.lbl_audio_badge.style().polish(self.lbl_audio_badge)

        spin = getattr(self.page, 'volume_percent', None)
        if spin is not None and self.volume_slider.value() != spin.value():
            self._on_volume_spin_changed(spin.value())
        self._refresh_provider_link()
        self._refresh_genius_state()

    def eventFilter(self, watched, event):
        if watched is self.page and event.type() == QEvent.Type.Show:
            self._adopt_volume_controls()
            self.sync_from_controller()
        return super().eventFilter(watched, event)


def install_settings_studio_view(controller) -> SettingsStudioView | None:
    """Install the commercial Settings Studio UI around an existing MainWindow.settings_page."""
    settings_page = getattr(getattr(controller, 'window', None), 'settings_page', None)
    if settings_page is None:
        return None
    return SettingsStudioView(controller)
