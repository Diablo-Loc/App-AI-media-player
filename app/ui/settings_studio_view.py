"""Commercial Hi-Fi Studio Settings view adapter (unified cards, auto-save & safe VI/EN i18n)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
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
from pipeline.content_mode import DIALOGUE
from ui.design_system import FORM_STYLE
from ui.i18n import (
    SUPPORTED_LANGUAGES,
    get_language,
    install_app_language_manager,
    normalize_language,
    reload_language_from_settings,
    set_language,
    tr_pair,
    translate_widget_tree,
)
from ui.icons import ACCENT, INK, MUTED, TEXT, button_icon

_PORTAL_LINKS = {
    'Google Gemini': ('Google AI Studio', 'https://aistudio.google.com/apikey'),
    'OpenAI (GPT-4o)': ('OpenAI Platform', 'https://platform.openai.com/api-keys'),
    'Claude 3.5': ('Anthropic Console', 'https://console.anthropic.com/settings/keys'),
}

# Canonical internal values preserved 100% on SettingsPage combos -> Clean VI / EN display labels
_CONTENT_MODE_ITEMS = (
    ('lyrics', 'Lời bài hát (Nhạc / MV)', 'Song Lyrics (Music / MV)'),
    ('dialogue', 'Hội thoại / Phim / Podcast', 'Dialogue / Video / Podcast'),
)
_FAST_LYRICS_ITEMS = (
    ('Bật (Siêu tốc)', 'Bật — Ưu tiên lời chuẩn & căn nhịp siêu tốc (< 1s)', 'On — Instant synced lyrics & vocal sync (< 1s)'),
    ('Tắt (Luôn dùng AI)', 'Tắt — Luôn chạy nhận diện giọng nói Whisper AI', 'Off — Always run Whisper AI transcription'),
)
_COMPUTE_DEVICE_ITEMS = (
    ('cuda', 'GPU NVIDIA (CUDA ⚡)', 'NVIDIA GPU (CUDA ⚡)'),
    ('cpu', 'CPU (Bộ vi xử lý)', 'CPU (Software)'),
)
_ONLINE_PROVIDER_ITEMS = (
    ('Local Default', 'Dịch nội bộ · NLLB-200 (Ngoại tuyến)', 'Local Offline · NLLB-200 (Free)'),
    ('Google Gemini', 'Google Gemini (Khuyên dùng cho nhạc)', 'Google Gemini (Recommended for lyrics)'),
    ('OpenAI (GPT-4o)', 'OpenAI · GPT-4o / GPT-5', 'OpenAI · GPT-4o / GPT-5'),
    ('Claude 3.5', 'Anthropic Claude · Sonnet / Haiku', 'Anthropic Claude · Sonnet / Haiku'),
)
_GENIUS_MODE_ITEMS = (
    ('Tắt (Nhanh)', 'Tắt — Dịch trực tiếp tốc độ cao', 'Off — Direct fast translation'),
    ('Bật (Chính xác cao)', 'Bật — Đối chiếu lời gốc chuẩn trên Genius', 'On — Verify with official Genius lyrics'),
)
_AUDIO_PRESET_ITEMS = (
    ('master_hifi', 'Chuẩn Hi-Fi (Hợp nhất)', 'Hi-Fi Master (Unified)'),
    ('studio_dawn_aria2', 'Dawn Pro 2 · Aria 2', 'Dawn Pro 2 · Aria 2'),
    ('dac_bitperfect', 'DAC Rời · Bit-Perfect', 'External DAC · Bit-Perfect'),
    ('bit_pure', 'Nguyên bản', 'Bit-Pure Original'),
    ('youtube', 'YouTube (−14 LUFS)', 'YouTube (−14 LUFS)'),
    ('walkman_vivid', 'Sống động', 'Walkman Vivid'),
    ('bypass', 'Tắt (Bypass)', 'Bypass (Raw)'),
    ('custom', 'Tùy chỉnh', 'Custom'),
)

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
    QLabel#studioSavePill { background: #142B24; color: #77E0BE; border: 1px solid #2A5649;
        border-radius: 12px; padding: 3px 10px; font-size: 11px; font-weight: 600; }
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
        self._syncing_proxies = False
        self._in_scroll_sync = False
        self._row_i18n_pairs: list[tuple[QLabel, str, str]] = []
        self._save_pill_timer = QTimer(self)
        self._save_pill_timer.setSingleShot(True)
        self._save_pill_timer.setInterval(2600)
        self._save_pill_timer.timeout.connect(self._hide_save_pill)

        initial_lang = normalize_language(self.page.settings.value('app_language', 'vi'))
        set_language(initial_lang, persist=False)
        self._build_ui()
        self._wire_proxy_sync()
        self.page.installEventFilter(self)
        self.scroll.viewport().installEventFilter(self)
        install_app_language_manager(controller.window, settings=self.page.settings)
        QTimer.singleShot(0, self._adopt_volume_controls)
        self.sync_from_controller()
        if get_language() == 'en':
            self.retranslate_ui('en')
        QTimer.singleShot(0, self._sync_scroll_geometry)

    def _register_label_i18n(self, lbl: QLabel, vi_text: str, en_text: str) -> QLabel:
        self._row_i18n_pairs.append((lbl, vi_text, en_text))
        lbl.setText(tr_pair(vi_text, en_text))
        return lbl

    def _build_ui(self):
        page = self.page
        page.setObjectName('settingsPageHost')
        page.setMinimumSize(0, 0)
        page.setStyleSheet(_STUDIO_STYLE)

        root = page.layout()
        # Preserve legacy widgets/content_layout inside a hidden owner bin so VolumeSettings & contracts stay intact.
        self._legacy_bin = QWidget(page)
        self._legacy_bin.setObjectName('legacySettingsOwnerBin')
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

        # Clean header bar + non-blocking auto-save pill + Reset / Save actions
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName('studioTitle')
        self._register_label_i18n(self.lbl_title, 'Cài đặt', 'Settings')

        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setObjectName('studioSubtitle')
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_subtitle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._register_label_i18n(
            self.lbl_subtitle,
            'Ngôn ngữ giao diện, âm thanh phòng thu, mô hình nhận diện lời và dịch vụ dịch thuật.',
            'App language, studio audio output, speech recognition models, and lyric translation.',
        )
        title_col.addWidget(self.lbl_title)
        title_col.addWidget(self.lbl_subtitle)
        hdr.addLayout(title_col, stretch=1)

        self.lbl_save_status = QLabel('')
        self.lbl_save_status.setObjectName('studioSavePill')
        self.lbl_save_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.lbl_save_status.hide()
        hdr.addWidget(self.lbl_save_status, alignment=Qt.AlignmentFlag.AlignVCenter)

        page.btn_reset.setMinimumSize(132, 36)
        page.btn_reset.setMaximumWidth(180)
        page.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(page.btn_reset, 'rotate-ccw', 'Đặt lại tất cả về mặc định', color=MUTED, size=14, icon_only=False)
        page.btn_reset.setText(tr_pair('Đặt lại mặc định', 'Reset Defaults'))
        hdr.addWidget(page.btn_reset)

        # Replace blocking modal save popup on studio header button with smooth silent save + inline pill
        try:
            page.btn_save.clicked.disconnect(page.save_settings)
        except (TypeError, RuntimeError):
            pass
        page.btn_save.clicked.connect(self._on_save_button_clicked)
        page.btn_save.setProperty('role', 'primary')
        page.btn_save.setMinimumSize(124, 36)
        page.btn_save.setMaximumWidth(168)
        page.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(page.btn_save, 'save', 'Lưu cài đặt', color=INK, size=14, icon_only=False)
        page.btn_save.setText(tr_pair('Lưu cài đặt', 'Save Settings'))
        hdr.addWidget(page.btn_save)
        root.addLayout(hdr)

        # Centered commercial scroll area with exact width-for-height sizing (zero phantom bottom void)
        self.scroll = QScrollArea(page)
        self.scroll.setObjectName('studioScroll')
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.scroll_host = QWidget()
        self.scroll_host.setObjectName('studioScrollBody')

        self.col_wrap = QWidget(self.scroll_host)
        self.col_wrap.setObjectName('studioScrollBody')
        self.cards_layout = QVBoxLayout(self.col_wrap)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)

        self._build_appearance_card()
        self._build_audio_card()
        self._build_asr_card()
        self._build_translation_card()

        self.scroll.setWidget(self.scroll_host)
        root.addWidget(self.scroll, stretch=1)
        self._sync_scroll_geometry()

    def _sync_scroll_geometry(self) -> None:
        """Compute exact per-card width-for-height geometry so maximized scroll has 0px void & 0 stretched cards."""
        if self._in_scroll_sync or not hasattr(self, 'scroll') or not hasattr(self, 'col_wrap'):
            return
        self._in_scroll_sync = True
        try:
            vp = self.scroll.viewport()
            cards = [
                c
                for c in (
                    getattr(self, 'appearance_card', None),
                    getattr(self, 'audio_card', None),
                    getattr(self, 'asr_card', None),
                    getattr(self, 'translation_card', None),
                )
                if c is not None
            ]

            def _layout_at(target_vp_w: int, target_vp_h: int) -> None:
                col_w = min(880, max(340, target_vp_w - 8))
                self.col_wrap.setFixedWidth(col_w)
                total_h = 0
                spacing = self.cards_layout.spacing()
                for idx, card in enumerate(cards):
                    card.setMinimumHeight(0)
                    card.setMaximumHeight(16777215)
                    card.setFixedWidth(col_w)
                    lay = card.layout()
                    if lay is not None:
                        lay.invalidate()
                        lay.activate()
                        card_h = (
                            lay.totalHeightForWidth(col_w)
                            if lay.hasHeightForWidth()
                            else lay.sizeHint().height()
                        )
                    else:
                        card_h = card.sizeHint().height()
                    card_h = max(48, int(card_h))
                    card.setFixedHeight(card_h)
                    total_h += card_h
                    if idx > 0:
                        total_h += spacing

                self.cards_layout.invalidate()
                self.cards_layout.activate()
                col_x = max(0, (target_vp_w - col_w) // 2)
                top_pad = 2
                bottom_pad = 16
                self.col_wrap.setGeometry(col_x, top_pad, col_w, total_h)
                self.scroll_host.resize(target_vp_w, max(target_vp_h, top_pad + total_h + bottom_pad))

            vp_w = max(360, vp.width())
            vp_h = max(120, vp.height())
            _layout_at(vp_w, vp_h)

            # Re-run once if vertical scrollbar toggled and narrowed viewport width
            vp_w2 = max(360, vp.width())
            vp_h2 = max(120, vp.height())
            if vp_w2 != vp_w or vp_h2 != vp_h:
                _layout_at(vp_w2, vp_h2)
        finally:
            self._in_scroll_sync = False

    def _make_card(
        self,
        vi_title: str,
        en_title: str,
        right_widget: QWidget | None = None,
    ) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName('studioCard')
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        lbl = QLabel()
        lbl.setObjectName('studioCardTitle')
        lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._register_label_i18n(lbl, vi_title, en_title)
        top.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        top.addStretch()
        if right_widget is not None:
            right_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            top.addWidget(right_widget, alignment=Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(top)

        div = QFrame()
        div.setObjectName('studioDivider')
        div.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(div)
        return card, lay

    def _add_card_row(
        self,
        parent_lay: QVBoxLayout,
        vi_title: str,
        en_title: str,
        vi_desc: str,
        en_desc: str,
        control: QWidget,
        footer_widget: QWidget | None = None,
    ) -> QLabel:
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
        lbl_t = QLabel()
        lbl_t.setObjectName('studioRowTitle')
        lbl_t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._register_label_i18n(lbl_t, vi_title, en_title)
        left.addWidget(lbl_t)
        if vi_desc or en_desc:
            lbl_d = QLabel()
            lbl_d.setObjectName('studioRowDesc')
            lbl_d.setWordWrap(True)
            lbl_d.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            lbl_d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._register_label_i18n(lbl_d, vi_desc, en_desc)
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

    @staticmethod
    def _make_proxy_combo(items: tuple[tuple[str, str, str], ...]) -> QComboBox:
        combo = QComboBox()
        combo.setFixedWidth(340)
        combo.setFixedHeight(34)
        is_en = get_language() == 'en'
        for canonical_key, vi_lbl, en_lbl in items:
            combo.addItem(en_lbl if is_en else vi_lbl, canonical_key)
        return combo

    @staticmethod
    def _retranslate_proxy_combo(combo: QComboBox, items: tuple[tuple[str, str, str], ...], lang: str) -> None:
        is_en = normalize_language(lang) == 'en'
        combo.blockSignals(True)
        try:
            for i, (_key, vi_lbl, en_lbl) in enumerate(items):
                if i < combo.count():
                    combo.setItemText(i, en_lbl if is_en else vi_lbl)
        finally:
            combo.blockSignals(False)

    def _build_appearance_card(self):
        self.lbl_lang_badge = QLabel()
        self.lbl_lang_badge.setObjectName('studioBadge')
        self.lbl_lang_badge.setProperty('tone', 'neutral')
        self.appearance_card, lay = self._make_card(
            'Giao diện & Ngôn ngữ',
            'Appearance & Language',
            self.lbl_lang_badge,
        )

        self.language_combo = QComboBox()
        self.language_combo.setFixedWidth(340)
        self.language_combo.setFixedHeight(34)
        for code, label in SUPPORTED_LANGUAGES:
            self.language_combo.addItem(label, code)
        cur_lang = get_language()
        idx = self.language_combo.findData(cur_lang)
        self.language_combo.setCurrentIndex(max(0, idx))
        self.language_combo.currentIndexChanged.connect(self._on_language_combo_changed)

        self._add_card_row(
            lay,
            'Ngôn ngữ hiển thị',
            'App Language',
            'Chuyển đổi tức thì ngôn ngữ toàn bộ giao diện ứng dụng (không làm thay đổi phụ đề hay dữ liệu đã lưu).',
            'Switch the entire application interface language instantly (does not alter saved subtitles or user data).',
            self.language_combo,
        )
        self._update_language_badge(cur_lang)
        self.cards_layout.addWidget(self.appearance_card)

    def _build_audio_card(self):
        self.lbl_audio_badge = QLabel('Chuẩn Hi-Fi · −14 LUFS')
        self.lbl_audio_badge.setObjectName('studioBadge')
        self.audio_card, lay = self._make_card(
            'Âm thanh & Thiết bị',
            'Audio & Output Device',
            self.lbl_audio_badge,
        )

        # Row 1: Preset + One-click optimal master restore
        preset_ctrl = QWidget()
        preset_ctrl.setFixedWidth(340)
        ph = QHBoxLayout(preset_ctrl)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(8)
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedHeight(34)
        is_en = get_language() == 'en'
        for key, vi_lbl, en_lbl in _AUDIO_PRESET_ITEMS:
            self.preset_combo.addItem(en_lbl if is_en else vi_lbl, key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        self.btn_optimal_preset = QPushButton(tr_pair('Tối ưu', 'Optimal'))
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
            'Listening Mode',
            'Tự chuẩn hóa −14 LUFS chống vỡ đỉnh 0 dBTP, giữ 100% chi tiết gốc và tự thích ứng DAC rời.',
            'Normalizes loudness to −14 LUFS with 0 dBTP true-peak protection while preserving 100% source detail.',
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
            'Output Device',
            'Gắn trực tiếp USB DAC (như Moondrop Dawn Pro 2) để chạy WASAPI Exclusive bỏ qua bộ trộn Windows.',
            'Select a USB DAC directly (e.g. Moondrop Dawn Pro 2) for bit-exact WASAPI Exclusive playback.',
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
            'Playback Volume',
            '',
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
        self.btn_open_eq = QPushButton(tr_pair('Equalizer (10 dải / PEQ)', 'Equalizer (10-Band / PEQ)'))
        self.btn_open_eq.setObjectName('studioSubBtn')
        self.btn_open_eq.setFixedHeight(34)
        self.btn_open_eq.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_open_eq, 'sliders-horizontal', 'Mở Equalizer phòng thu 64-bit', color=TEXT, size=14, icon_only=False)
        self.btn_open_eq.clicked.connect(self.controller.open_equalizer)

        self.btn_benchmark = QPushButton(tr_pair('Đo kiểm âm', 'Audio Lab'))
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
            'Studio Tools',
            'Tinh chỉnh PEQ Squiglink/APO chính xác từng dải hoặc mở phòng đo phổ tần số & nghe thử A/B.',
            'Fine-tune 64-bit Parametric / 10-Band EQ or open the spectrum & live A/B audition lab.',
            tools_ctrl,
        )

        self.cards_layout.addWidget(self.audio_card)

    def _build_asr_card(self):
        page = self.page
        self.asr_card, lay = self._make_card(
            'Nhận diện giọng nói · Whisper AI',
            'Speech Recognition · Whisper AI',
        )

        page.combo_model.setStyleSheet('')
        page.combo_model.setFixedWidth(340)
        page.combo_model.setFixedHeight(34)
        self._add_card_row(
            lay,
            'Mô hình Whisper',
            'Whisper Model',
            'Chọn độ chính xác (Base chạy nhanh, Large-v3 tối ưu nhất cho lời bài hát đa ngôn ngữ).',
            'Choose transcription accuracy (Base is fast; Large-v3 is best for multilingual lyrics).',
            page.combo_model,
        )

        self.content_mode_combo = self._make_proxy_combo(_CONTENT_MODE_ITEMS)
        self._add_card_row(
            lay,
            'Loại nội dung',
            'Content Type',
            'Áp dụng khi tạo hoặc dịch phụ đề mới; các tệp phụ đề đã lưu giữ nguyên.',
            'Applies when generating or translating new subtitles; existing saved subtitles remain untouched.',
            self.content_mode_combo,
        )

        # Restored Fast Lyrics setting (previously hidden in _legacy_bin!)
        self.fast_lyrics_combo = self._make_proxy_combo(_FAST_LYRICS_ITEMS)
        self._add_card_row(
            lay,
            'Lấy lời nhanh (Fast Lyrics)',
            'Fast Synced Lyrics',
            'Ưu tiên sub có sẵn (.lrc/.srt/.ass) hoặc lời chuẩn LRCLIB căn nhịp giọng hát (< 1s); tự chuyển sang Whisper nếu không khớp.',
            'Prioritize sidecar subtitles or verified LRCLIB lyrics with vocal forced-alignment (< 1s); falls back to Whisper automatically.',
            self.fast_lyrics_combo,
        )

        self.compute_device_combo = self._make_proxy_combo(_COMPUTE_DEVICE_ITEMS)
        self._add_card_row(
            lay,
            'Thiết bị tính toán',
            'Compute Device',
            'Ưu tiên GPU NVIDIA (CUDA) nếu máy có card rời để nhận diện và căn chữ từng âm tiết nhanh gấp nhiều lần.',
            'Prefer NVIDIA GPU (CUDA) when available for dramatically faster transcription and word-level alignment.',
            self.compute_device_combo,
        )

        page.btn_download_resource.setStyleSheet('')
        page.btn_download_resource.setObjectName('studioSubBtn')
        page.btn_download_resource.setFixedHeight(36)
        page.btn_download_resource.setFixedWidth(340)
        page.btn_download_resource.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(page.btn_download_resource, 'download', 'Mở trình tải tài nguyên AI', color=TEXT, size=14, icon_only=False)
        page.btn_download_resource.setText(
            tr_pair('Tải / Cập nhật mô hình && thư viện AI', 'Download / Manage Offline AI Models')
        )
        self._add_card_row(
            lay,
            'Tài nguyên ngoại tuyến',
            'Offline AI Packages',
            'Kiểm tra trạng thái cài đặt và tải xuống các gói mô hình Whisper / NLLB-200 chạy nội bộ.',
            'Check installation status and download offline Whisper / NLLB-200 model packages.',
            page.btn_download_resource,
        )
        self.cards_layout.addWidget(self.asr_card)

    def _build_translation_card(self):
        page = self.page
        self.translation_card, lay = self._make_card(
            'Dịch thuật AI & Đối soát Genius',
            'AI Translation & Genius Verification',
        )

        self.online_ai_combo = self._make_proxy_combo(_ONLINE_PROVIDER_ITEMS)
        self._add_card_row(
            lay,
            'Dịch vụ dịch thuật',
            'Translation Service',
            'Chọn mô hình NLLB-200 chạy cục bộ miễn phí hoặc dịch trực tuyến qua API đám mây.',
            'Choose free offline NLLB-200 translation or cloud AI providers for natural poetic lyrics.',
            self.online_ai_combo,
        )

        page.combo_translation_model.setStyleSheet('')
        page.combo_translation_model.setFixedWidth(340)
        page.combo_translation_model.setFixedHeight(34)
        self._add_card_row(
            lay,
            'Model dịch',
            'Translation Model',
            'Model nhẹ tiết kiệm chi phí; model cao cấp ưu tiên văn phong và ngữ cảnh lời bài hát.',
            'Flash/Mini models optimize speed & cost; flagship models prioritize lyric nuance.',
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
        page.api_key_input.setPlaceholderText(tr_pair('Nhập API Key tại đây...', 'Enter provider API key...'))
        self.btn_toggle_api_key = QPushButton(tr_pair('Hiện', 'Show'))
        self.btn_toggle_api_key.setObjectName('studioEyeBtn')
        self.btn_toggle_api_key.setFixedSize(58, 34)
        self.btn_toggle_api_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_api_key.clicked.connect(lambda: self._toggle_echo(page.api_key_input, self.btn_toggle_api_key))
        ah.addWidget(page.api_key_input, stretch=1)
        ah.addWidget(self.btn_toggle_api_key)

        self.lbl_provider_link = QLabel('')
        self.lbl_provider_link.setObjectName('studioLink')
        self.lbl_provider_link.setWordWrap(True)
        self.lbl_provider_link.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.lbl_provider_link.setOpenExternalLinks(True)
        self._add_card_row(
            lay,
            'API Key dịch thuật',
            'Provider API Key',
            'Mã xác thực chỉ lưu cục bộ trên máy của bạn khi sử dụng dịch vụ AI trực tuyến.',
            'Stored locally on your device only; used when a cloud translation provider is selected.',
            api_ctrl,
            footer_widget=self.lbl_provider_link,
        )

        self.genius_mode_combo = self._make_proxy_combo(_GENIUS_MODE_ITEMS)
        self._add_card_row(
            lay,
            'Đối soát lời Genius',
            'Genius Lyric Verification',
            'Tự đối chiếu lời gốc đáng tin cậy từ Genius để sửa lỗi nghe nhầm của Whisper trước khi dịch.',
            'Cross-check against verified Genius lyrics to repair ASR mishearings before translation.',
            self.genius_mode_combo,
        )

        gen_ctrl = QWidget()
        gen_ctrl.setFixedWidth(340)
        gh = QHBoxLayout(gen_ctrl)
        gh.setContentsMargins(0, 0, 0, 0)
        gh.setSpacing(6)
        page.genius_key_input.setStyleSheet('')
        page.genius_key_input.setFixedHeight(34)
        page.genius_key_input.setPlaceholderText(tr_pair('Nhập Genius Access Token...', 'Enter Genius Client Access Token...'))
        self.btn_toggle_genius_key = QPushButton(tr_pair('Hiện', 'Show'))
        self.btn_toggle_genius_key.setObjectName('studioEyeBtn')
        self.btn_toggle_genius_key.setFixedSize(58, 34)
        self.btn_toggle_genius_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_genius_key.clicked.connect(
            lambda: self._toggle_echo(page.genius_key_input, self.btn_toggle_genius_key)
        )
        gh.addWidget(page.genius_key_input, stretch=1)
        gh.addWidget(self.btn_toggle_genius_key)

        self.lbl_genius_link = QLabel()
        self.lbl_genius_link.setObjectName('studioLink')
        self.lbl_genius_link.setWordWrap(True)
        self.lbl_genius_link.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.lbl_genius_link.setOpenExternalLinks(True)
        self._add_card_row(
            lay,
            'Genius Access Token',
            'Genius Access Token',
            'Bắt buộc khi bật chế độ đối soát lời gốc Genius cho nhạc có lời.',
            'Required when Genius Lyric Verification is enabled for music tracks.',
            gen_ctrl,
            footer_widget=self.lbl_genius_link,
        )
        self._update_genius_portal_label()
        self.cards_layout.addWidget(self.translation_card)

    def _wire_proxy_sync(self) -> None:
        page = self.page
        # Initial sync from underlying SettingsPage combos -> Studio proxies
        self._sync_proxies_from_page()

        # Studio proxy -> SettingsPage + silent auto-save
        self.content_mode_combo.currentIndexChanged.connect(self._on_proxy_content_mode_changed)
        self.fast_lyrics_combo.currentIndexChanged.connect(self._on_proxy_fast_lyrics_changed)
        self.compute_device_combo.currentIndexChanged.connect(self._on_proxy_device_changed)
        self.online_ai_combo.currentIndexChanged.connect(self._on_proxy_online_ai_changed)
        self.genius_mode_combo.currentIndexChanged.connect(self._on_proxy_genius_changed)

        page.combo_model.currentIndexChanged.connect(self._on_direct_ai_widget_edited)
        page.combo_translation_model.currentIndexChanged.connect(self._on_direct_ai_widget_edited)
        page.api_key_input.editingFinished.connect(self._on_direct_ai_widget_edited)
        page.genius_key_input.editingFinished.connect(self._on_direct_ai_widget_edited)

        # SettingsPage -> Studio proxy (keeps programmatic/test calls & Reset 100% synced!)
        page.combo_content_mode.currentIndexChanged.connect(self._sync_proxies_from_page)
        page.combo_fast_lyrics.currentIndexChanged.connect(self._sync_proxies_from_page)
        page.combo_device.currentIndexChanged.connect(self._sync_proxies_from_page)
        page.combo_online_ai.currentTextChanged.connect(self._on_page_online_ai_changed)
        page.combo_genius_mode.currentIndexChanged.connect(self._sync_proxies_from_page)

        self._refresh_provider_link()
        self._refresh_genius_state()

    def _sync_proxies_from_page(self, *_args) -> None:
        if self._syncing_proxies:
            return
        self._syncing_proxies = True
        try:
            page = self.page
            cm_val = page.combo_content_mode.currentData() or 'lyrics'
            idx = self.content_mode_combo.findData(cm_val)
            if idx >= 0 and self.content_mode_combo.currentIndex() != idx:
                self.content_mode_combo.setCurrentIndex(idx)

            fl_val = page.combo_fast_lyrics.currentText()
            idx = self.fast_lyrics_combo.findData(fl_val)
            if idx >= 0 and self.fast_lyrics_combo.currentIndex() != idx:
                self.fast_lyrics_combo.setCurrentIndex(idx)

            dev_val = page.combo_device.currentText()
            idx = self.compute_device_combo.findData(dev_val)
            if idx >= 0 and self.compute_device_combo.currentIndex() != idx:
                self.compute_device_combo.setCurrentIndex(idx)

            prov_val = page.combo_online_ai.currentText()
            idx = self.online_ai_combo.findData(prov_val)
            if idx >= 0 and self.online_ai_combo.currentIndex() != idx:
                self.online_ai_combo.setCurrentIndex(idx)

            gen_val = page.combo_genius_mode.currentText()
            idx = self.genius_mode_combo.findData(gen_val)
            if idx >= 0 and self.genius_mode_combo.currentIndex() != idx:
                self.genius_mode_combo.setCurrentIndex(idx)

            self._refresh_genius_state()
        finally:
            self._syncing_proxies = False

    def _on_page_online_ai_changed(self, *_args) -> None:
        self._sync_proxies_from_page()
        self._refresh_provider_link()

    def _on_proxy_content_mode_changed(self, *_args) -> None:
        if self._syncing_proxies:
            return
        val = self.content_mode_combo.currentData()
        idx = self.page.combo_content_mode.findData(val)
        if idx >= 0:
            self.page.combo_content_mode.setCurrentIndex(idx)
        self._refresh_genius_state()
        self._auto_save_ai_settings()

    def _on_proxy_fast_lyrics_changed(self, *_args) -> None:
        if self._syncing_proxies:
            return
        val = str(self.fast_lyrics_combo.currentData() or 'Bật (Siêu tốc)')
        self.page.combo_fast_lyrics.setCurrentText(val)
        self._auto_save_ai_settings()

    def _on_proxy_device_changed(self, *_args) -> None:
        if self._syncing_proxies:
            return
        val = str(self.compute_device_combo.currentData() or 'cpu')
        self.page.combo_device.setCurrentText(val)
        self._auto_save_ai_settings()

    def _on_proxy_online_ai_changed(self, *_args) -> None:
        if self._syncing_proxies:
            return
        val = str(self.online_ai_combo.currentData() or 'Local Default')
        self.page.combo_online_ai.setCurrentText(val)
        self._refresh_provider_link()
        self._auto_save_ai_settings()

    def _on_proxy_genius_changed(self, *_args) -> None:
        if self._syncing_proxies:
            return
        val = str(self.genius_mode_combo.currentData() or 'Tắt (Nhanh)')
        self.page.combo_genius_mode.setCurrentText(val)
        self._auto_save_ai_settings()

    def _on_direct_ai_widget_edited(self, *_args) -> None:
        if self._syncing_proxies:
            return
        self._auto_save_ai_settings()

    def _show_save_pill(self, vi_msg: str, en_msg: str) -> None:
        self.lbl_save_status.setText(tr_pair(vi_msg, en_msg))
        self.lbl_save_status.show()
        self._save_pill_timer.start()

    def _hide_save_pill(self) -> None:
        self.lbl_save_status.hide()

    def _auto_save_ai_settings(self) -> None:
        self.page.save_settings_silent()
        if self.page.isVisible():
            self._show_save_pill('✓ Đã tự động lưu', '✓ Auto-saved')

    def _on_save_button_clicked(self) -> None:
        self.page.save_settings_silent()
        self._show_save_pill('✓ Đã lưu cài đặt', '✓ Settings saved')
        win = self.controller.window
        if hasattr(win, '_show_status'):
            win._show_status(tr_pair('✅ Đã lưu cài đặt thành công', '✅ Settings saved'))

    def _on_language_combo_changed(self, *_args) -> None:
        code = normalize_language(str(self.language_combo.currentData() or 'vi'))
        self.page.settings.setValue('app_language', code)
        set_language(code, persist=False)
        self._show_save_pill('✓ Đã đổi ngôn ngữ', '✓ Language updated')

    def _update_language_badge(self, lang: str) -> None:
        is_en = normalize_language(lang) == 'en'
        self.lbl_lang_badge.setText('English · Active' if is_en else 'Tiếng Việt · Mặc định')

    def _update_genius_portal_label(self) -> None:
        prefix = tr_pair('Lấy Genius Access Token tại:', 'Get your Genius Access Token at:')
        self.lbl_genius_link.setText(
            f'{prefix} <a href="https://genius.com/api-clients" style="color: #77E0BE; text-decoration: none;">Genius API Clients</a>'
        )

    def _adopt_volume_controls(self):
        if self._volume_adopted:
            return
        spin = getattr(self.page, 'volume_percent', None)
        if spin is None:
            return
        self._volume_adopted = True
        self._volume_hint_label = None
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
            self._volume_hint_label = hint_lbl
            hint_lbl.setStyleSheet('color: #8FA2B7; font-size: 11px; margin-left: 0px;')
            hint_lbl.setWordWrap(True)
            hint_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            hint_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            self._volume_hint_slot.addWidget(hint_lbl)
            hint_lbl.show()
            translate_widget_tree(hint_lbl, get_language())
        if old_panel is not None and old_panel is not self.page:
            old_panel.hide()
        self._sync_scroll_geometry()

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
        if showing:
            btn.setText(tr_pair('Hiện', 'Show'))
        else:
            btn.setText(tr_pair('Ẩn', 'Hide'))

    def _refresh_provider_link(self, *_):
        provider = self.page.combo_online_ai.currentText()
        if provider == 'Local Default':
            self.page.api_key_input.setEnabled(False)
            self.btn_toggle_api_key.setEnabled(False)
            self.lbl_provider_link.setText(
                tr_pair(
                    'Đang dùng dịch cục bộ NLLB-200 ngoại tuyến (không cần API Key).',
                    'Using offline NLLB-200 local translation (no API key required).',
                )
            )
            return
        self.page.api_key_input.setEnabled(True)
        self.btn_toggle_api_key.setEnabled(True)
        name, url = _PORTAL_LINKS.get(provider, ('OpenAI Platform', 'https://platform.openai.com/api-keys'))
        prefix = tr_pair('Lấy key tại:', 'Get API key at:')
        self.lbl_provider_link.setText(
            f'{prefix} <a href="{url}" style="color: #77E0BE; text-decoration: none;">{name}</a>'
        )

    def _refresh_genius_state(self, *_):
        is_dialogue = self.page.combo_content_mode.currentData() == DIALOGUE
        enabled = not is_dialogue and bool(self.page.genius_key_input.isEnabled())
        self.genius_mode_combo.setEnabled(not is_dialogue)
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

    def retranslate_ui(self, lang: str | None = None) -> None:
        target = get_language() if lang is None else normalize_language(lang)
        is_en = target == 'en'

        self.language_combo.blockSignals(True)
        try:
            idx = self.language_combo.findData(target)
            if idx >= 0:
                self.language_combo.setCurrentIndex(idx)
        finally:
            self.language_combo.blockSignals(False)
        self._update_language_badge(target)

        for lbl, vi_t, en_t in self._row_i18n_pairs:
            lbl.setText(en_t if is_en else vi_t)

        self._retranslate_proxy_combo(self.preset_combo, _AUDIO_PRESET_ITEMS, target)
        self._retranslate_proxy_combo(self.content_mode_combo, _CONTENT_MODE_ITEMS, target)
        self._retranslate_proxy_combo(self.fast_lyrics_combo, _FAST_LYRICS_ITEMS, target)
        self._retranslate_proxy_combo(self.compute_device_combo, _COMPUTE_DEVICE_ITEMS, target)
        self._retranslate_proxy_combo(self.online_ai_combo, _ONLINE_PROVIDER_ITEMS, target)
        self._retranslate_proxy_combo(self.genius_mode_combo, _GENIUS_MODE_ITEMS, target)

        self.page.btn_reset.setText('Reset Defaults' if is_en else 'Đặt lại mặc định')
        self.page.btn_save.setText('Save Settings' if is_en else 'Lưu cài đặt')
        self.btn_optimal_preset.setText('Optimal' if is_en else 'Tối ưu')
        self.btn_benchmark.setText('Audio Lab' if is_en else 'Đo kiểm âm')
        self.page.btn_download_resource.setText(
            'Download / Manage Offline AI Models' if is_en else 'Tải / Cập nhật mô hình && thư viện AI'
        )
        self.page.api_key_input.setPlaceholderText(
            'Enter provider API key...' if is_en else 'Nhập API Key tại đây...'
        )
        self.page.genius_key_input.setPlaceholderText(
            'Enter Genius Client Access Token...' if is_en else 'Nhập Genius Access Token...'
        )

        for inp, btn in (
            (self.page.api_key_input, self.btn_toggle_api_key),
            (self.page.genius_key_input, self.btn_toggle_genius_key),
        ):
            showing = inp.echoMode() == QLineEdit.EchoMode.Normal
            btn.setText(('Hide' if is_en else 'Ẩn') if showing else ('Show' if is_en else 'Hiện'))

        if self.page.combo_translation_model.count() == 1 and not self.page.combo_translation_model.isEnabled():
            self.page.combo_translation_model.setItemText(
                0, 'Local NLLB · Automatic' if is_en else 'Local NLLB · Tự động'
            )

        self._update_genius_portal_label()
        self.sync_from_controller()
        self._sync_scroll_geometry()

    def sync_from_controller(self):
        self._adopt_volume_controls()
        self._sync_proxies_from_page()
        ctrl = self.controller
        panel = ctrl.panel
        is_en = get_language() == 'en'

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for i in range(panel.device_combo.count()):
            txt = panel.device_combo.itemText(i)
            data = panel.device_combo.itemData(i)
            if is_en and txt == 'Mặc định hệ thống':
                txt = 'System Default Output'
            self.device_combo.addItem(txt, data)
        self.device_combo.setCurrentIndex(max(0, panel.device_combo.currentIndex()))
        self.device_combo.blockSignals(False)

        preset_key = detect_preset(ctrl.profile, ctrl.target_lufs)
        self.preset_combo.blockSignals(True)
        idx = self.preset_combo.findData(preset_key)
        self.preset_combo.setCurrentIndex(idx if idx >= 0 else max(0, self.preset_combo.findData('custom')))
        self.preset_combo.blockSignals(False)

        peq = normalize_peq_filters(getattr(ctrl.profile, 'eq_peq_filters', ()))
        if ctrl.profile.eq_enabled and peq:
            self.btn_open_eq.setText(
                f'Equalizer · PEQ ({len(peq)} bands)' if is_en else f'Equalizer · PEQ {len(peq)} dải'
            )
        elif ctrl.profile.eq_enabled:
            self.btn_open_eq.setText('Equalizer · Active' if is_en else 'Equalizer · Đang bật')
        else:
            self.btn_open_eq.setText('Equalizer (10-Band / PEQ)' if is_en else 'Equalizer (10 dải / PEQ)')

        if not ctrl.profile.enabled:
            self.lbl_audio_badge.setText('Raw Bypass' if is_en else 'Nguyên gốc (Bypass)')
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
                self.lbl_audio_badge.setText(preset_lbl if 'LUFS' in preset_lbl else f'{preset_lbl} · −14 LUFS')
            elif ctrl.profile.normalize:
                self.lbl_audio_badge.setText(
                    preset_lbl if 'LUFS' in preset_lbl else f'{preset_lbl} · {ctrl.target_lufs} LUFS'
                )
            else:
                self.lbl_audio_badge.setText(preset_lbl)
            self.lbl_audio_badge.setProperty('tone', 'good')
        self.lbl_audio_badge.style().unpolish(self.lbl_audio_badge)
        self.lbl_audio_badge.style().polish(self.lbl_audio_badge)

        spin = getattr(self.page, 'volume_percent', None)
        if spin is not None and self.volume_slider.value() != spin.value():
            self._on_volume_spin_changed(spin.value())
        translate_widget_tree(self.page.combo_model, get_language())
        if getattr(self, '_volume_hint_label', None) is not None:
            translate_widget_tree(self._volume_hint_label, get_language())
        self._refresh_provider_link()
        self._refresh_genius_state()
        self._sync_scroll_geometry()

    def eventFilter(self, watched, event):
        if watched is self.page and event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            self._adopt_volume_controls()
            if event.type() == QEvent.Type.Show:
                self.sync_from_controller()
            self._sync_scroll_geometry()
        elif hasattr(self, 'scroll') and watched is self.scroll.viewport() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Show,
        ):
            self._sync_scroll_geometry()
        return super().eventFilter(watched, event)


def install_settings_studio_view(controller) -> SettingsStudioView | None:
    """Install the commercial Settings Studio UI around an existing MainWindow.settings_page."""
    settings_page = getattr(getattr(controller, 'window', None), 'settings_page', None)
    if settings_page is None:
        return None
    return SettingsStudioView(controller)
