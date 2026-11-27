from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QSlider,
    QPushButton,
    QFrame,
    QComboBox,
    QColorDialog,
    QCheckBox,
    QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from subtitle.mode import SubtitleMode
from ui.icons import ACCENT, MUTED, button_icon, label_icon
from ui.subtitle_effects import ENTRANCES
from ui.subtitle_effects_panel import SubtitleEffectsPanel
from ui.subtitle_studio import (
    KARAOKE_RECOMMENDED_PROFILES,
    STUDIO_PROFILES,
    STUDIO_PROFILE_ORDER,
    detect_studio_profile,
)

QUICK_FONT_COLORS = (
    ('#FFFFFF', 'Trắng chuẩn điện ảnh'),
    ('#FEF08A', 'Vàng dịu rạp hát'),
    ('#7DD3FC', 'Xanh băng Studio'),
    ('#A7F3D0', 'Ngọc lam dịu'),
    ('#F9A8D4', 'Hồng Neon nổi bật'),
)


class SettingsPanel(QWidget):
    # --- Tín hiệu (Signals) ---
    font_size_changed = Signal(int)
    font_color_changed = Signal(str)

    outline_changed = Signal(bool, int, str)  # (bật/tắt, độ dày, màu)
    shadow_changed = Signal(bool, int)        # (bật/tắt, độ đậm)

    bg_color_changed = Signal(str)
    bg_opacity_changed = Signal(float)

    playback_speed_changed = Signal(float)
    subtitle_mode_changed = Signal(object)
    lock_position_changed = Signal(bool)
    fade_effect_changed = Signal(bool)        # Bật/Tắt Hiệu ứng Fade In/Out
    phonetic_changed = Signal(bool)           # Bật/Tắt dòng Phiên âm trên cùng (Romaji / Pinyin / Hangul)
    word_karaoke_changed = Signal(bool)       # Bật/Tắt Karaoke chuẩn từng chữ thật
    studio_profile_requested = Signal(str)    # Áp nhanh bộ phong cách Studio Editor

    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(920)
        self.speed_btns = []
        self.profile_btns = {}
        self._active_profile_key = None
        self._current_outline_color = "#090D16"
        self._current_font_color = "#FFFF00"

        # --- BoTube Fluent Dark Dashboard (unified with ui.design_system Obsidian Slate + Mint) ---
        self.setStyleSheet("""
            QWidget {
                background-color: #0D1118;
                color: #EDF3FA;
                border: 1px solid #233042;
                border-radius: 12px;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                border: none;
                background: transparent;
                font-weight: 600;
                font-size: 12px;
                color: #C7D4E3;
                margin-top: 0px;
            }
            QLabel#studioTitle {
                font-size: 14px;
                font-weight: 700;
                color: #EDF3FA;
            }
            QLabel#activeStatusBadge {
                font-size: 11px;
                font-weight: 600;
                color: #9AAABC;
                background-color: #161F2B;
                border: 1px solid #263447;
                border-radius: 6px;
                padding: 2px 9px;
            }
            QLabel#activeStatusBadge[tone="active"] {
                color: #A9F1D9;
                background-color: #16332B;
                border-color: #367865;
            }
            QLabel#activeStatusBadge[tone="custom"] {
                color: #C7E8F9;
                background-color: #162636;
                border-color: #2E5270;
            }
            QLabel#activeStatusBadge[tone="karaoke"] {
                color: #FEF08A;
                background-color: #38270E;
                border-color: #F59E0B;
            }
            QLabel#sectionCaption {
                font-size: 11px;
                font-weight: 700;
                color: #77E0BE;
            }
            QLabel#valueBadge {
                font-size: 11px;
                font-weight: 600;
                color: #77E0BE;
                background-color: #162B26;
                border: 1px solid #2A5448;
                border-radius: 5px;
                padding: 1px 6px;
            }
            QFrame#subCoreCard {
                background-color: #131A24;
                border: 1px solid #233042;
                border-radius: 10px;
            }
            QComboBox {
                background-color: #18212E;
                border: 1px solid #2A384B;
                padding: 4px 8px;
                border-radius: 7px;
                color: #EDF3FA;
                font-size: 12px;
            }
            QComboBox:hover { border-color: #77E0BE; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background-color: #18212E;
                color: #EDF3FA;
                selection-background-color: #19372F;
                selection-color: #A9F1D9;
                border: 1px solid #2A384B;
            }
            QPushButton {
                background-color: #1A2330;
                border: 1px solid #2A384B;
                border-radius: 7px;
                padding: 5px 8px;
                color: #EDF3FA;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #233042;
                border-color: #3E526A;
            }
            QPushButton#studioProfileBtn {
                background-color: #151D28;
                border: 1px solid #233042;
                border-radius: 7px;
                padding: 5px 6px;
                color: #C7D4E3;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton#studioProfileBtn:hover {
                background-color: #1E2A3A;
                border-color: #3D5068;
                color: #EDF3FA;
            }
            QPushButton#studioProfileBtn[active="true"] {
                background-color: #19372F;
                border: 1px solid #77E0BE;
                border-left: 3px solid #77E0BE;
                color: #A9F1D9;
                font-weight: 700;
            }
            QPushButton#studioProfileBtn[karaoke_rec="true"] {
                background-color: #2A1F0D;
                border: 1px solid #F59E0B;
                border-left: 3px solid #FBBF24;
                color: #FDE68A;
                font-weight: 700;
            }
            QPushButton#studioProfileBtn[karaoke_rec="true"]:hover {
                background-color: #382811;
                border-color: #FBBF24;
                color: #FEF9C3;
            }
            QPushButton#studioProfileBtn[karaoke_rec="true"][active="true"] {
                background-color: #422E0E;
                border: 1px solid #FDE047;
                border-left: 3px solid #FEF08A;
                color: #FEF9C3;
                font-weight: 700;
            }
            QPushButton#speedPill {
                background-color: #18212E;
                border: 1px solid #273445;
                border-radius: 6px;
                color: #9AAABC;
                font-size: 11px;
                font-weight: 600;
                padding: 2px;
            }
            QPushButton#speedPill:hover {
                background-color: #222F40;
                color: #EDF3FA;
            }
            QPushButton#speedPill:checked {
                background-color: #19372F;
                border: 1px solid #77E0BE;
                color: #A9F1D9;
                font-weight: 700;
            }
            QPushButton#btn_reset {
                background-color: #1A2330;
                border: 1px solid #2C3B4F;
                color: #C7D4E3;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 10px;
            }
            QPushButton#btn_reset:hover {
                background-color: #262028;
                border-color: #884455;
                color: #FCA5A5;
            }
            QSlider {
                border: none;
                background: transparent;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #273445;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #77E0BE;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #EDF3FA;
                border: 2px solid #77E0BE;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QWidget#subtitleSettingsContent { border: none; background-color: #0D1118; }
            QCheckBox {
                border: none;
                background: transparent;
                color: #D7E2EE;
                font-size: 12px;
                padding: 2px 0;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 13px;
                height: 13px;
                border-radius: 4px;
                border: 1px solid #3A4B61;
                background-color: #18212E;
            }
            QCheckBox::indicator:hover {
                border-color: #77E0BE;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #77E0BE;
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.46, fx:0.5, fy:0.5,
                    stop:0 #77E0BE, stop:0.72 #77E0BE, stop:0.76 #131A24, stop:1 #131A24);
            }
            QCheckBox#chkKaraokeMode:checked {
                color: #FDE68A;
                font-weight: 700;
            }
            QCheckBox#chkKaraokeMode::indicator:checked {
                border: 2px solid #FBBF24;
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.46, fx:0.5, fy:0.5,
                    stop:0 #FBBF24, stop:0.72 #FBBF24, stop:0.76 #131A24, stop:1 #131A24);
            }
            QScrollArea { border: none; background-color: #0D1118; }
            QScrollArea#profileStripScroll { border: none; background: transparent; }
            QWidget#profileStripContent { border: none; background: transparent; }
            QScrollArea#profileStripScroll QScrollBar:vertical {
                background: #111822; width: 5px; margin: 1px 0; border: none; border-radius: 2px;
            }
            QScrollArea#profileStripScroll QScrollBar::handle:vertical {
                background: #3B4E66; min-height: 20px; border-radius: 2px;
            }
            QScrollArea#profileStripScroll QScrollBar::handle:vertical:hover { background: #77E0BE; }
            QScrollBar:vertical { background: #0D1118; width: 6px; margin: 6px 0; border: none; }
            QScrollBar::handle:vertical { background: #344254; min-height: 28px; border-radius: 3px; }
            QScrollBar::handle:vertical:hover { background: #53667D; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.settings_scroll = QScrollArea(self)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName('subtitleSettingsContent')
        self.settings_scroll.setWidget(content)
        outer.addWidget(self.settings_scroll)
        self.setFixedHeight(556)

        root = QVBoxLayout(content)
        root.setSpacing(7)
        root.setContentsMargins(14, 10, 14, 10)

        # --- TOP BAR: CLEAN HEADER + PERSISTENT ACTIVE BADGE + RESET + 2-ROW SCROLLABLE VFX PROFILES ---
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        title_icon = QLabel()
        title_icon.setFixedSize(18, 18)
        label_icon(title_icon, "captions", size=16, color=ACCENT)
        header = QLabel("Phụ đề & Hiệu ứng")
        header.setObjectName("studioTitle")
        self.lbl_active_badge = QLabel("Hiệu ứng: Tắt")
        self.lbl_active_badge.setObjectName("activeStatusBadge")
        self.lbl_active_badge.setProperty("tone", "off")
        top_row.addWidget(title_icon)
        top_row.addWidget(header)
        top_row.addWidget(self.lbl_active_badge)
        top_row.addStretch(1)

        self.btn_reset = QPushButton(" Đặt lại mặc định")
        self.btn_reset.setObjectName("btn_reset")
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_reset, "rotate-ccw", "Đặt lại mặc định", color=MUTED, size=13, icon_only=False)
        self.btn_reset.setToolTip("Khôi phục toàn bộ cài đặt phụ đề về mặc định")
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        top_row.addWidget(self.btn_reset, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top_row)

        self.profile_scroll = QScrollArea(content)
        self.profile_scroll.setObjectName("profileStripScroll")
        self.profile_scroll.setWidgetResizable(True)
        self.profile_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.profile_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.profile_scroll.setFrameShape(QFrame.Shape.NoFrame)
        profile_holder = QWidget()
        profile_holder.setObjectName("profileStripContent")
        profile_grid = QGridLayout(profile_holder)
        profile_grid.setContentsMargins(0, 0, 4, 0)
        profile_grid.setHorizontalSpacing(6)
        profile_grid.setVerticalSpacing(6)
        cols = 5
        btn_h = 28
        for idx, key in enumerate(STUDIO_PROFILE_ORDER):
            spec = STUDIO_PROFILES[key]
            btn = QPushButton(spec['label'])
            btn.setObjectName("studioProfileBtn")
            btn.setProperty("active", False)
            btn.setFixedHeight(btn_h)
            btn.setMinimumWidth(0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(spec['tooltip'])
            btn.clicked.connect(lambda _=False, k=key: self._on_studio_profile_clicked(k))
            self.profile_btns[key] = btn
            profile_grid.addWidget(btn, idx // cols, idx % cols)
        for c in range(cols):
            profile_grid.setColumnStretch(c, 1)
        self.profile_scroll.setWidget(profile_holder)
        # Hiển thị gọn tối đa 2 hàng preset (2 * 28px + 6px khoảng cách = 62px), các hàng sau cuộn mượt
        self.profile_scroll.setFixedHeight(btn_h * 2 + 6)
        root.addWidget(self.profile_scroll)

        # --- MAIN 2-COLUMN BODY (LEFT: CORE SUBTITLE CONTROLS | RIGHT: VFX STUDIO + PREVIEW) ---
        body = QHBoxLayout()
        body.setSpacing(12)

        # LEFT CARD: Core Subtitle Display Controls
        left_card = QFrame(content)
        left_card.setObjectName("subCoreCard")
        left_card.setFixedWidth(342)
        left = QVBoxLayout(left_card)
        left.setSpacing(5)
        left.setContentsMargins(12, 6, 12, 6)

        sec_left = QLabel("Hiển thị & Kiểu chữ")
        sec_left.setObjectName("sectionCaption")
        left.addWidget(sec_left)

        # 1. Mode
        mode_lbl = QLabel("Chế độ ngôn ngữ")
        left.addWidget(mode_lbl)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Chỉ Lời Gốc (Original)", SubtitleMode.JP)
        self.combo_mode.addItem("Chỉ Tiếng Anh (EN)", SubtitleMode.EN)
        self.combo_mode.addItem("Chỉ Tiếng Việt (VI)", SubtitleMode.VI)
        self.combo_mode.addItem("Lời Gốc + Anh", SubtitleMode.JP_EN)
        self.combo_mode.addItem("Lời Gốc + Việt", SubtitleMode.JP_VI)
        self.combo_mode.addItem("Anh + Việt", SubtitleMode.EN_VI)
        self.combo_mode.addItem("Tất cả (Gốc + Anh + Việt)", SubtitleMode.JP_EN_VI)
        self.combo_mode.addItem("Tắt phụ đề", SubtitleMode.OFF)
        idx = self.combo_mode.findData(SubtitleMode.EN_VI)
        self.combo_mode.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        left.addWidget(self.combo_mode)

        left.addWidget(self._sep())

        # 2. Font Size + Color + Swatches
        size_hdr = QHBoxLayout()
        size_hdr.addWidget(QLabel("Cỡ chữ & Màu chữ"))
        size_hdr.addStretch()
        self.lbl_size_val = QLabel("24 px")
        self.lbl_size_val.setObjectName("valueBadge")
        size_hdr.addWidget(self.lbl_size_val)
        left.addLayout(size_hdr)

        font_layout = QHBoxLayout()
        font_layout.setSpacing(6)
        self.slider_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_size.setRange(18, 72)
        self.slider_size.setValue(24)
        self.slider_size.setToolTip("Kéo để chỉnh cỡ chữ")
        self.slider_size.valueChanged.connect(self._on_size_changed)

        self.btn_font_color = QPushButton("Màu")
        self.btn_font_color.setFixedSize(46, 24)
        self.btn_font_color.setToolTip("Chọn màu chữ tùy ý")
        self.btn_font_color.clicked.connect(lambda: self._open_color_dialog("font"))
        self._set_btn_color(self.btn_font_color, "#FFFF00")

        font_layout.addWidget(self.slider_size, 1)
        font_layout.addWidget(self.btn_font_color)
        left.addLayout(font_layout)

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        swatch_lbl = QLabel("Màu nhanh:")
        swatch_lbl.setStyleSheet("font-size: 11px; font-weight: normal; color: #94A3B8; border: none;")
        swatch_row.addWidget(swatch_lbl)
        for hex_col, tip in QUICK_FONT_COLORS:
            sw = QPushButton()
            sw.setFixedSize(22, 18)
            sw.setCursor(Qt.CursorShape.PointingHandCursor)
            sw.setToolTip(tip)
            sw.setStyleSheet(
                f"background-color: {hex_col}; border: 1px solid #475569; border-radius: 4px; padding: 0;"
            )
            sw.clicked.connect(lambda _=False, hc=hex_col: self._apply_quick_font_color(hc))
            swatch_row.addWidget(sw)
        swatch_row.addStretch()
        left.addLayout(swatch_row)

        left.addWidget(self._sep())

        # 3. Background Glass Pill
        left.addWidget(QLabel("Hộp nền & Độ mờ"))
        bg_layout = QHBoxLayout()
        bg_layout.setSpacing(6)
        self.combo_opacity = QComboBox()
        self.combo_opacity.addItem("0% (Trong suốt)", 0.0)
        self.combo_opacity.addItem("15% (Kính rất nhẹ)", 0.15)
        self.combo_opacity.addItem("25% (Nhẹ)", 0.25)
        self.combo_opacity.addItem("35% (Kính dịu)", 0.35)
        self.combo_opacity.addItem("50% (Chuẩn)", 0.5)
        self.combo_opacity.addItem("65% (Rạp tối)", 0.65)
        self.combo_opacity.addItem("75% (Đậm)", 0.75)
        self.combo_opacity.addItem("100% (Đặc)", 1.0)
        self.combo_opacity.setCurrentIndex(4)
        self.combo_opacity.currentIndexChanged.connect(self._on_opacity_changed)

        self.btn_bg_color = QPushButton("Nền")
        self.btn_bg_color.setFixedSize(46, 24)
        self.btn_bg_color.setToolTip("Chọn màu nền")
        self.btn_bg_color.clicked.connect(lambda: self._open_color_dialog("bg"))
        self._set_btn_color(self.btn_bg_color, "#000000", is_dark_bg=True)

        bg_layout.addWidget(self.combo_opacity, 1)
        bg_layout.addWidget(self.btn_bg_color)
        left.addLayout(bg_layout)

        left.addWidget(self._sep())

        # 4. Outline & Shadow
        left.addWidget(QLabel("Viền & Bóng quang học"))

        out_layout = QHBoxLayout()
        out_layout.setSpacing(6)
        self.chk_outline = QCheckBox("Viền")
        self.chk_outline.setChecked(True)
        self.chk_outline.stateChanged.connect(self._emit_style_update)

        self.slider_out_width = QSlider(Qt.Orientation.Horizontal)
        self.slider_out_width.setMinimumWidth(80)
        self.slider_out_width.setRange(0, 10)
        self.slider_out_width.setValue(4)
        self.slider_out_width.valueChanged.connect(self._emit_style_update)

        self.lbl_outline_val = QLabel("4")
        self.lbl_outline_val.setObjectName("valueBadge")

        self.btn_out_color = QPushButton("Viền")
        self.btn_out_color.setFixedSize(42, 22)
        self.btn_out_color.clicked.connect(lambda: self._open_color_dialog("outline"))
        self._set_btn_color(self.btn_out_color, self._current_outline_color, is_dark_bg=True)

        out_layout.addWidget(self.chk_outline)
        out_layout.addWidget(self.slider_out_width, 1)
        out_layout.addWidget(self.lbl_outline_val)
        out_layout.addWidget(self.btn_out_color)
        left.addLayout(out_layout)

        sha_layout = QHBoxLayout()
        sha_layout.setSpacing(6)
        self.chk_shadow = QCheckBox("Bóng")
        self.chk_shadow.setChecked(True)
        self.chk_shadow.stateChanged.connect(self._emit_style_update)

        self.slider_sha_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_sha_alpha.setMinimumWidth(80)
        self.slider_sha_alpha.setRange(0, 255)
        self.slider_sha_alpha.setValue(160)
        self.slider_sha_alpha.valueChanged.connect(self._emit_style_update)

        self.lbl_shadow_val = QLabel("160")
        self.lbl_shadow_val.setObjectName("valueBadge")

        sha_layout.addWidget(self.chk_shadow)
        sha_layout.addWidget(self.slider_sha_alpha, 1)
        sha_layout.addWidget(self.lbl_shadow_val)
        left.addLayout(sha_layout)

        left.addWidget(self._sep())

        # 5. Playback Speed
        left.addWidget(QLabel("Tốc độ phát"))
        speed_layout = QHBoxLayout()
        speed_layout.setSpacing(4)
        for speed in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            btn = QPushButton(f"{speed}x")
            btn.setObjectName("speedPill")
            btn.setCheckable(True)
            btn.setMinimumWidth(0)
            btn.setFixedHeight(25)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if speed == 1.0:
                btn.setChecked(True)
            self.speed_btns.append(btn)
            btn.clicked.connect(lambda checked, s=speed, b=btn: self._on_speed_click(s, b))
            speed_layout.addWidget(btn, 1)
        left.addLayout(speed_layout)

        # 6. Lock & Fade toggles side-by-side + Karaoke / Phonetics options
        other_row = QHBoxLayout()
        other_row.setSpacing(10)
        self.chk_lock = QCheckBox("Khóa vị trí sub")
        self.chk_lock.toggled.connect(self.lock_position_changed.emit)
        self.chk_fade = QCheckBox("Mờ dần (Fade)")
        self.chk_fade.setChecked(True)
        self.chk_fade.toggled.connect(self.fade_effect_changed.emit)
        other_row.addWidget(self.chk_lock)
        other_row.addWidget(self.chk_fade)
        other_row.addStretch()
        left.addLayout(other_row)

        karaoke_row = QHBoxLayout()
        karaoke_row.setSpacing(10)
        self.chk_word_karaoke = QCheckBox("🎤 Chế độ Karaoke")
        self.chk_word_karaoke.setObjectName("chkKaraokeMode")
        self.chk_word_karaoke.setChecked(False)
        self.chk_word_karaoke.setToolTip(
            "Bật chế độ Karaoke sân khấu: phóng to phụ đề, đổi màu sáng chữ theo từng từ thật (Anh/Việt/Nhật/Trung/Hàn + Romaji) và tô vàng ★ các hiệu ứng khuyên dùng"
        )
        self.chk_word_karaoke.toggled.connect(self._on_karaoke_toggled)

        self.chk_phonetic = QCheckBox("Phiên âm (R)")
        self.chk_phonetic.setChecked(False)
        self.chk_phonetic.setToolTip(
            "Hiện dòng phiên âm Latinh (Romaji Nhật / Pinyin Trung / Hangul Hàn) màu xanh băng ở trên cùng (Phím tắt khi xem video: R)"
        )
        self.chk_phonetic.toggled.connect(self.phonetic_changed.emit)

        karaoke_row.addWidget(self.chk_word_karaoke)
        karaoke_row.addWidget(self.chk_phonetic)
        karaoke_row.addStretch()
        left.addLayout(karaoke_row)
        left.addStretch()

        body.addWidget(left_card, 0)

        # RIGHT COLUMN: Wide 2-column VFX Controls + Large Live Preview Stage
        self.effects_panel = SubtitleEffectsPanel(content)
        self.effects_panel.changed.connect(self._sync_active_indicator)
        body.addWidget(self.effects_panel, 1)

        root.addLayout(body, 1)

    # --- HÀM BỔ TRỢ ---

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #202C3C; max-height: 1px; border: none;")
        return line

    def _set_btn_color(self, btn, hex_color, is_dark_bg=False):
        qcol = QColor(hex_color)
        luminance = (0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()) / 255
        text_color = "#0D1118" if luminance > 0.55 else "#EDF3FA"

        btn.setStyleSheet(f"""
            background-color: {hex_color};
            color: {text_color};
            border: 1px solid #3A4B61;
            border-radius: 6px;
            font-weight: 600;
            font-size: 11px;
            padding: 2px 6px;
        """)

    def _set_active_profile_btn(self, active_key: str | None):
        self._active_profile_key = active_key
        for key, btn in self.profile_btns.items():
            is_act = (key == active_key)
            if btn.property("active") != is_act:
                btn.setProperty("active", is_act)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        if active_key and active_key in self.profile_btns and hasattr(self, "profile_scroll"):
            self.profile_scroll.ensureWidgetVisible(self.profile_btns[active_key], 0, 2)

    def _on_karaoke_toggled(self, checked: bool):
        self.set_karaoke_recommendations(bool(checked))
        self.word_karaoke_changed.emit(bool(checked))

    def set_karaoke_recommendations(self, enabled: bool):
        """Highlight recommended Karaoke presets & dropdown options in Gold ★ when Karaoke Mode is ON."""
        rec_set = set(KARAOKE_RECOMMENDED_PROFILES)
        for key, btn in self.profile_btns.items():
            spec = STUDIO_PROFILES[key]
            is_rec = bool(enabled and key in rec_set)
            base_lbl = spec['label']
            target_lbl = f"★ {base_lbl}" if is_rec else base_lbl
            if btn.text() != target_lbl:
                btn.setText(target_lbl)
            target_tip = (
                f"★ Đề xuất chuẩn cho Karaoke từng chữ · {spec['tooltip']}"
                if key in rec_set
                else spec['tooltip']
            )
            btn.setToolTip(target_tip)
            if btn.property("karaoke_rec") != is_rec:
                btn.setProperty("karaoke_rec", is_rec)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        if hasattr(self, "effects_panel") and hasattr(self.effects_panel, "set_karaoke_recommendations"):
            self.effects_panel.set_karaoke_recommendations(bool(enabled))
        self._sync_active_indicator()

    def _sync_active_indicator(self, subtitle_effects: dict | None = None):
        """Keep active quick-profile button & header badge synced across startup, edits, and resets."""
        opts = subtitle_effects if isinstance(subtitle_effects, dict) else self.effects_panel.options()
        matched = detect_studio_profile(opts)
        self._set_active_profile_btn(matched)
        badge = getattr(self, "lbl_active_badge", None)
        if badge is None:
            return
        karaoke_on = bool(hasattr(self, "chk_word_karaoke") and self.chk_word_karaoke.isChecked())
        if matched is not None:
            prefix = "🎤 Karaoke · " if karaoke_on else "Đang chọn: "
            badge.setText(f"{prefix}{STUDIO_PROFILES[matched]['label']}")
            tone = "karaoke" if karaoke_on else "active"
        elif opts.get("enabled"):
            ent_key = opts.get("entrance", "none")
            ent_label = next((t.split(" · ")[0] for k, t in ENTRANCES if k == ent_key), ent_key)
            prefix = "🎤 Karaoke · " if karaoke_on else "Tùy chỉnh · "
            badge.setText(f"{prefix}{ent_label}")
            tone = "karaoke" if karaoke_on else "custom"
        else:
            badge.setText("Hiệu ứng: Tắt")
            tone = "off"
        if badge.property("tone") != tone:
            badge.setProperty("tone", tone)
            badge.style().unpolish(badge)
            badge.style().polish(badge)

    def set_active_studio_profile(self, key: str | None):
        self._set_active_profile_btn(key)
        if key and key in STUDIO_PROFILES:
            self._sync_active_indicator(STUDIO_PROFILES[key]["subtitle_effects"])
        else:
            self._sync_active_indicator(None)

    def _on_studio_profile_clicked(self, key: str):
        self._set_active_profile_btn(key)
        self.studio_profile_requested.emit(key)

    def _on_size_changed(self, value: int):
        self.lbl_size_val.setText(f"{value} px")
        self.font_size_changed.emit(value)

    def _apply_quick_font_color(self, hex_color: str):
        self._current_font_color = hex_color
        self._set_btn_color(self.btn_font_color, hex_color)
        self.font_color_changed.emit(hex_color)

    def _on_mode_changed(self, index):
        mode = self.combo_mode.currentData()
        self.subtitle_mode_changed.emit(mode)

    def _on_opacity_changed(self, index):
        val = self.combo_opacity.currentData()
        self.bg_opacity_changed.emit(val)

    def _open_color_dialog(self, target_type):
        """Gộp chung hàm chọn màu an toàn, không bị chìm bên dưới video"""
        dialog = QColorDialog(self)
        title_map = {"font": "Chọn màu chữ", "bg": "Chọn màu nền", "outline": "Chọn màu viền"}
        dialog.setWindowTitle(title_map.get(target_type, "Chọn màu"))
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)

        if dialog.exec():
            color = dialog.selectedColor()
            if color.isValid():
                hex_c = color.name()
                if target_type == "font":
                    self._current_font_color = hex_c
                    self.font_color_changed.emit(hex_c)
                    self._set_btn_color(self.btn_font_color, hex_c)
                elif target_type == "bg":
                    self.bg_color_changed.emit(hex_c)
                    self._set_btn_color(self.btn_bg_color, hex_c, is_dark_bg=True)
                elif target_type == "outline":
                    self._current_outline_color = hex_c
                    self._set_btn_color(self.btn_out_color, hex_c, is_dark_bg=True)
                    self._emit_style_update()

    def _emit_style_update(self):
        self.lbl_outline_val.setText(str(self.slider_out_width.value()))
        self.lbl_shadow_val.setText(str(self.slider_sha_alpha.value()))
        self.outline_changed.emit(
            self.chk_outline.isChecked(),
            self.slider_out_width.value(),
            self._current_outline_color
        )
        self.shadow_changed.emit(
            self.chk_shadow.isChecked(),
            self.slider_sha_alpha.value()
        )

    def _on_speed_click(self, speed, clicked_btn):
        self.playback_speed_changed.emit(speed)
        for btn in self.speed_btns:
            btn.setChecked(btn == clicked_btn)

    def _on_reset_clicked(self):
        self.effects_panel.sync_options(None)
        self._sync_active_indicator(None)
        self.blockSignals(True)

        idx_en_vi = self.combo_mode.findData(SubtitleMode.EN_VI)
        if idx_en_vi != -1:
            self.combo_mode.setCurrentIndex(idx_en_vi)

        self.slider_size.setValue(24)
        self.lbl_size_val.setText("24 px")
        self._set_btn_color(self.btn_font_color, "#FFFF00")

        idx_half = self.combo_opacity.findData(0.5)
        self.combo_opacity.setCurrentIndex(idx_half if idx_half != -1 else 4)
        self._set_btn_color(self.btn_bg_color, "#000000", is_dark_bg=True)

        self.chk_lock.setChecked(False)
        self.chk_fade.setChecked(True)
        self.chk_phonetic.setChecked(False)
        self.chk_word_karaoke.setChecked(False)
        self.speed_btns[2].setChecked(True)

        self.chk_outline.setChecked(True)
        self.slider_out_width.setValue(4)
        self.lbl_outline_val.setText("4")
        self._current_outline_color = "#000000"
        self._set_btn_color(self.btn_out_color, "#000000", is_dark_bg=True)

        self.chk_shadow.setChecked(True)
        self.slider_sha_alpha.setValue(160)
        self.lbl_shadow_val.setText("160")

        self.blockSignals(False)
        self.set_karaoke_recommendations(False)

        self.reset_requested.emit()

    def sync_ui(self, config):
        saved_fx = config.get('subtitle_effects') if config else None
        self.effects_panel.sync_options(saved_fx)
        self._sync_active_indicator(saved_fx)
        if not config:
            return

        self.blockSignals(True)

        saved_mode_raw = config.get("mode")
        found_mode = False
        if saved_mode_raw is not None:
            for i in range(self.combo_mode.count()):
                data = self.combo_mode.itemData(i)
                if data == saved_mode_raw or str(data) == str(saved_mode_raw) or (hasattr(data, 'value') and data.value == saved_mode_raw):
                    self.combo_mode.setCurrentIndex(i)
                    found_mode = True
                    break

        if not found_mode:
            idx = self.combo_mode.findData(SubtitleMode.EN_VI)
            if idx != -1:
                self.combo_mode.setCurrentIndex(idx)

        size_val = config.get("font_size", 24)
        self.slider_size.setValue(size_val)
        self.lbl_size_val.setText(f"{size_val} px")
        self._set_btn_color(self.btn_font_color, config.get("font_color", "#FFFF00"))

        saved_op = config.get("bg_opacity", 0.5)
        for i in range(self.combo_opacity.count()):
            if abs(self.combo_opacity.itemData(i) - saved_op) < 0.01:
                self.combo_opacity.setCurrentIndex(i)
                break
        self._set_btn_color(self.btn_bg_color, config.get("bg_color", "#000000"), is_dark_bg=True)

        self.chk_outline.setChecked(config.get("outline_enabled", True))
        out_w = config.get("outline_width", 4)
        self.slider_out_width.setValue(out_w)
        self.lbl_outline_val.setText(str(out_w))
        self._current_outline_color = config.get("outline_color", "#000000")
        self._set_btn_color(self.btn_out_color, self._current_outline_color, is_dark_bg=True)

        self.chk_shadow.setChecked(config.get("shadow_enabled", True))
        sha_a = config.get("shadow_alpha", 160)
        self.slider_sha_alpha.setValue(sha_a)
        self.lbl_shadow_val.setText(str(sha_a))

        self.chk_lock.setChecked(config.get("lock_position", False))
        self.chk_fade.setChecked(config.get("fade_enabled", True))
        self.chk_phonetic.setChecked(bool(config.get("phonetic_enabled", False)))
        karaoke_flag = bool(config.get("word_karaoke_enabled", False))
        self.chk_word_karaoke.setChecked(karaoke_flag)

        self.blockSignals(False)
        self.set_karaoke_recommendations(karaoke_flag)
        self._sync_active_indicator(saved_fx)

        self._emit_style_update()

    def get_current_mode(self):
        return self.combo_mode.currentData()

    def set_mode_visual(self, mode_enum):
        idx = self.combo_mode.findData(mode_enum)
        if idx != -1:
            self.combo_mode.setCurrentIndex(idx)

    def showEvent(self, event):
        screen = self.screen().availableGeometry()
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, '_position_subsettings_panel'):
            parent._position_subsettings_panel()
        else:
            target_w = min(920, max(520, screen.width() - 24))
            target_h = min(556, max(240, screen.height() - 24))
            self.setFixedWidth(target_w)
            self.setFixedHeight(target_h)
            self.move(
                max(screen.left() + 8, min(self.x(), screen.right() - self.width() - 4)),
                max(screen.top() + 8, min(self.y(), screen.bottom() - self.height() - 8)),
            )
        super().showEvent(event)
        if self._active_profile_key and self._active_profile_key in self.profile_btns and hasattr(self, "profile_scroll"):
            self.profile_scroll.ensureWidgetVisible(self.profile_btns[self._active_profile_key], 0, 2)
