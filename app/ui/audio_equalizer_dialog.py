"""Minimalist 10-band studio Equalizer dialog with live biquad curve, shelves, A/B compare & APO menu."""
from dataclasses import replace
import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.audio_profile import (
    AudioProfile,
    EQ_CURVES,
    EQ_FREQS,
    EQ_LABELS,
    FLAT_EQ_BANDS,
    MAX_PEQ_FILTERS,
    PEQ_CURVES,
    detect_eq_curve,
    effective_eq_preamp_db,
    evaluate_eq_response_db,
    export_apo_text,
    normalize_eq_bands,
    normalize_peq_filters,
    parse_apo_text,
)
from core.subtitle_persistence import atomic_bytes
from ui.design_system import DIALOG_STYLE
from ui.icons import button_icon, MUTED, TEXT


class EqResponseCanvas(QWidget):
    """Real-time analytical biquad frequency response curve (20 Hz - 20 kHz, +/- 12 dB)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(118)
        self._profile = AudioProfile()
        log_min = math.log10(20.0)
        log_max = math.log10(20000.0)
        self._freqs = [10.0 ** (log_min + (log_max - log_min) * (i / 255.0)) for i in range(256)]

    def set_profile(self, profile: AudioProfile):
        self._profile = profile
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        fnt = self.font()
        fnt.setPointSizeF(8.0)
        p.setFont(fnt)
        fm = p.fontMetrics()

        pad_l = max(36.0, float(fm.horizontalAdvance('+12') + 10))
        pad_r = 14.0
        pad_t = 10.0
        pad_b = max(22.0, float(fm.height() + 8))
        gw = max(20.0, w - pad_l - pad_r)
        gh = max(20.0, h - pad_t - pad_b)

        p.fillRect(self.rect(), QColor('#0B1017'))
        p.setPen(QPen(QColor('#1D2938'), 1.0))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

        log_min = math.log10(20.0)
        log_max = math.log10(20000.0)

        def _x(freq: float) -> float:
            return pad_l + ((math.log10(max(20.0, freq)) - log_min) / (log_max - log_min)) * gw

        def _y(db: float) -> float:
            clamped = max(-14.0, min(14.0, float(db)))
            return pad_t + (1.0 - (clamped + 14.0) / 28.0) * gh

        # Horizontal dB grid
        for db in (12, 6, 0, -6, -12):
            yy = _y(db)
            p.setPen(QPen(QColor('#2A3B4E' if db == 0 else '#16202C'), 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            if db in (12, 0, -12):
                lbl = f'{db:+d}' if db != 0 else '0'
                tw = fm.horizontalAdvance(lbl)
                p.setPen(QColor('#64778B'))
                p.drawText(int(pad_l - tw - 6), int(yy + fm.ascent() / 2 - 1), lbl)

        # Vertical frequency grid
        for freq, lbl in zip(EQ_FREQS, EQ_LABELS):
            xx = _x(float(freq))
            p.setPen(QPen(QColor('#16202C'), 1.0))
            p.drawLine(QPointF(xx, pad_t), QPointF(xx, pad_t + gh))
            tw = fm.horizontalAdvance(lbl)
            p.setPen(QColor('#64778B'))
            p.drawText(int(xx - tw / 2.0), int(h - 6), lbl)

        vals = evaluate_eq_response_db(self._profile, self._freqs, 48000.0, include_preamp=False, force_preview=True)
        pts = [QPointF(_x(f), _y(v)) for f, v in zip(self._freqs, vals)]
        if pts:
            zero_y = _y(0.0)
            fill_path = QPainterPath()
            fill_path.moveTo(pts[0].x(), zero_y)
            for pt in pts:
                fill_path.lineTo(pt)
            fill_path.lineTo(pts[-1].x(), zero_y)
            fill_path.closeSubpath()

            active = bool(self._profile.eq_enabled)
            stroke_color = QColor('#77E0BE' if active else '#56697D')
            grad = QLinearGradient(0.0, pad_t, 0.0, pad_t + gh)
            if active:
                grad.setColorAt(0.0, QColor(119, 224, 190, 52))
                grad.setColorAt(0.5, QColor(119, 224, 190, 14))
                grad.setColorAt(1.0, QColor(119, 224, 190, 32))
            else:
                grad.setColorAt(0.0, QColor(86, 105, 125, 28))
                grad.setColorAt(1.0, QColor(86, 105, 125, 6))
            p.fillPath(fill_path, QBrush(grad))

            curve_path = QPainterPath()
            curve_path.moveTo(pts[0])
            for pt in pts[1:]:
                curve_path.lineTo(pt)
            p.setPen(QPen(stroke_color, 2.0))
            p.drawPath(curve_path)

            peq = normalize_peq_filters(getattr(self._profile, 'eq_peq_filters', ()))
            p.setBrush(QBrush(stroke_color))
            p.setPen(QPen(QColor('#0B1017'), 1.0))
            if peq:
                peq_freqs = [f[1] for f in peq]
                peq_vals = evaluate_eq_response_db(
                    self._profile, peq_freqs, 48000.0, include_preamp=False, force_preview=True
                )
                for (_, freq_hz, g_val, _), pv in zip(peq, peq_vals):
                    radius = 3.2 if abs(g_val) >= 0.05 else 2.0
                    p.drawEllipse(QPointF(_x(float(freq_hz)), _y(pv)), radius, radius)
            else:
                band_vals = evaluate_eq_response_db(
                    self._profile, list(EQ_FREQS), 48000.0, include_preamp=False, force_preview=True
                )
                bands = normalize_eq_bands(self._profile.eq_bands)
                for freq, bv, g in zip(EQ_FREQS, band_vals, bands):
                    radius = 3.0 if abs(g) >= 0.05 else 2.0
                    p.drawEllipse(QPointF(_x(float(freq)), _y(bv)), radius, radius)


class _ResettableSlider(QSlider):
    """QSlider where double-click or right-click resets smoothly to zero."""

    def __init__(self, orientation, default_val: int = 0, parent=None):
        super().__init__(orientation, parent)
        self._default_val = int(default_val)
        self.setToolTip('Nhấp đúp hoặc chuột phải để về 0')

    def mouseDoubleClickEvent(self, event):
        self.setValue(self._default_val)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.setValue(self._default_val)
            event.accept()
            return
        super().mousePressEvent(event)


class StudioEqualizerDialog(QDialog):
    """Minimalist 10-band & Parametric (PEQ) Equalizer with live biquad curve, shelves & APO I/O."""

    eq_changed = Signal(dict)
    user_presets_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle('Equalizer')
        self.setMinimumSize(700, 486)
        self.resize(760, 516)
        self.setStyleSheet(DIALOG_STYLE + '''
            QDialog { background: #0F151E; color: #EDF3FA; font-family: 'Segoe UI'; }
            QCheckBox { color: #EDF3FA; spacing: 8px; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #526173;
                border-radius: 4px; background: #101722; }
            QCheckBox::indicator:checked { background: #77E0BE; border-color: #77E0BE; }
            QComboBox { padding: 4px 10px; background: #151C26; border: 1px solid #253344; border-radius: 8px; }
            QDoubleSpinBox { padding: 3px 6px; background: #101722; color: #EDF3FA;
                border: 1px solid #253344; border-radius: 6px; font-family: Consolas; font-size: 12px; }
            QDoubleSpinBox:focus { border-color: #77E0BE; }
            QPushButton#toolIconBtn { background: #151C26; border: 1px solid #253344; border-radius: 8px; padding: 4px; }
            QPushButton#toolIconBtn:hover { background: #1E2836; border-color: #3A4D64; }
            QPushButton#toolIconBtn:disabled { background: #121821; border-color: #1C2532; }
            QPushButton#toolIconBtn::menu-indicator { image: none; width: 0px; }
            QPushButton#eqModeBtn { background: #151C26; color: #8FA2B7; border: 1px solid #253344;
                border-radius: 7px; font-size: 11px; font-weight: 600; padding: 0 10px; }
            QPushButton#eqModeBtn:hover { background: #1E2836; color: #EDF3FA; }
            QPushButton#eqModeBtn[peqModeActive="true"] { background: #162B26; color: #77E0BE; border-color: #2D5A4E; }
            QPushButton#peqSmallBtn { background: #1A232E; color: #D7E2EE; border: 1px solid #2C3B4E;
                border-radius: 6px; font-size: 11px; font-weight: 600; padding: 3px 10px; }
            QPushButton#peqSmallBtn:hover { background: #24303F; border-color: #77E0BE; color: #77E0BE; }
            QPushButton#peqDelBtn { background: transparent; color: #7A8CA0; border: 1px solid #253344;
                border-radius: 6px; font-size: 13px; font-weight: 700; }
            QPushButton#peqDelBtn:hover { background: #361C22; color: #F28B82; border-color: #6B343E; }
            QPushButton#abCompareBtn { background: #1A232E; color: #D7E2EE; border: 1px solid #2C3B4E;
                border-radius: 8px; font-weight: 600; font-size: 12px; padding: 0 12px; }
            QPushButton#abCompareBtn:hover { background: #24303F; border-color: #465B75; }
            QPushButton#abCompareBtn[abActive="true"] { background: #F2C96B; color: #0D1118; border-color: #F2C96B; }
            QMenu { background: #18212E; color: #EDF3FA; border: 1px solid #2A394C; border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 6px 14px; border-radius: 5px; font-size: 12px; }
            QMenu::item:selected { background: #26384B; color: #77E0BE; }
            QMenu::separator { height: 1px; background: #253344; margin: 4px 8px; }
            QSlider::groove:vertical { width: 4px; background: #233040; border-radius: 2px; }
            QSlider::sub-page:vertical { background: #233040; border-radius: 2px; }
            QSlider::add-page:vertical { background: #77E0BE; border-radius: 2px; }
            QSlider::handle:vertical { background: #EDF3FA; border: 2px solid #77E0BE;
                height: 11px; width: 11px; margin: 0 -4px; border-radius: 6px; }
            QSlider::groove:horizontal { height: 4px; background: #233040; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #77E0BE; border-radius: 2px; }
            QSlider::handle:horizontal { background: #EDF3FA; border: 2px solid #77E0BE;
                width: 11px; height: 11px; margin: -4px 0; border-radius: 6px; }
            QFrame#eqStripFrame { background: #141B25; border: 1px solid #202C3C; border-radius: 10px; }
            QScrollArea#peqScroll { background: transparent; border: none; }
            QWidget#peqScrollBody { background: transparent; }
        ''')

        self._user_presets: dict[str, dict] = {}
        self._syncing = False
        self._ab_holding = False
        self._eq_mode = 'geq'
        self._peq_rows: list[dict] = []
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(140)
        self._emit_timer.timeout.connect(self._emit_now)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(2600)
        self._toast_timer.timeout.connect(self._clear_toast)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Single clean top toolbar
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        self.enable_cb = QCheckBox('Bật')
        self.enable_cb.setStyleSheet('font-weight: 600; font-size: 13px;')
        hdr.addWidget(self.enable_cb)

        self.btn_mode_geq = QPushButton('10 dải')
        self.btn_mode_geq.setObjectName('eqModeBtn')
        self.btn_mode_geq.setFixedHeight(30)
        self.btn_mode_geq.setProperty('peqModeActive', True)
        hdr.addWidget(self.btn_mode_geq)

        self.btn_mode_peq = QPushButton('PEQ')
        self.btn_mode_peq.setObjectName('eqModeBtn')
        self.btn_mode_peq.setFixedHeight(30)
        self.btn_mode_peq.setProperty('peqModeActive', False)
        self.btn_mode_peq.setToolTip('Parametric EQ chuẩn Squiglink / Oratory1990 (Fc + Q + PK/LS/HS)')
        hdr.addWidget(self.btn_mode_peq)

        self.curve_combo = QComboBox()
        self.curve_combo.setMinimumWidth(182)
        self.curve_combo.setFixedHeight(32)
        hdr.addWidget(self.curve_combo)

        self.btn_save_preset = QPushButton()
        self.btn_save_preset.setObjectName('toolIconBtn')
        self.btn_save_preset.setFixedSize(32, 32)
        button_icon(self.btn_save_preset, 'plus', 'Lưu mẫu mới', color=TEXT, size=15, icon_only=True)
        hdr.addWidget(self.btn_save_preset)

        self.btn_delete_preset = QPushButton()
        self.btn_delete_preset.setObjectName('toolIconBtn')
        self.btn_delete_preset.setFixedSize(32, 32)
        button_icon(self.btn_delete_preset, 'trash', 'Xóa mẫu đang chọn', color=MUTED, size=15, icon_only=True)
        hdr.addWidget(self.btn_delete_preset)

        hdr.addStretch()

        self.lbl_info = QLabel('')
        self.lbl_info.setStyleSheet('color: #77E0BE; font-size: 11px;')
        self.lbl_info.hide()
        hdr.addWidget(self.lbl_info)

        self.btn_ab = QPushButton('A/B')
        self.btn_ab.setObjectName('abCompareBtn')
        self.btn_ab.setFixedHeight(32)
        self.btn_ab.setMinimumWidth(52)
        self.btn_ab.setToolTip('Nhấn giữ để so sánh với âm gốc')
        hdr.addWidget(self.btn_ab)

        self.btn_reset = QPushButton()
        self.btn_reset.setObjectName('toolIconBtn')
        self.btn_reset.setFixedSize(32, 32)
        button_icon(self.btn_reset, 'rotate-ccw', 'Đặt lại 0 dB', color=MUTED, size=15, icon_only=True)
        hdr.addWidget(self.btn_reset)

        self.btn_apo_menu = QPushButton()
        self.btn_apo_menu.setObjectName('toolIconBtn')
        self.btn_apo_menu.setFixedSize(32, 32)
        button_icon(self.btn_apo_menu, 'menu', 'Nhập / Xuất Equalizer APO', color=MUTED, size=15, icon_only=True)
        apo_menu = QMenu(self.btn_apo_menu)
        self.act_open_txt = apo_menu.addAction('Mở file .txt…')
        self.act_save_txt = apo_menu.addAction('Lưu file .txt…')
        apo_menu.addSeparator()
        self.act_paste_apo = apo_menu.addAction('Dán từ Clipboard')
        self.act_copy_apo = apo_menu.addAction('Chép vào Clipboard')
        self.btn_apo_menu.setMenu(apo_menu)
        hdr.addWidget(self.btn_apo_menu)
        root.addLayout(hdr)

        # Compatibility attributes for headless tests/callers (hidden from visual chrome)
        self.btn_open_txt = QPushButton('Mở .txt…', self)
        self.btn_save_txt = QPushButton('Lưu .txt…', self)
        self.btn_paste_apo = QPushButton('Dán APO', self)
        self.btn_copy_apo = QPushButton('Chép APO', self)
        for compat_btn in (self.btn_open_txt, self.btn_save_txt, self.btn_paste_apo, self.btn_copy_apo):
            compat_btn.hide()

        # Live response graph
        self.canvas = EqResponseCanvas(self)
        root.addWidget(self.canvas)

        # Center stack: Index 0 = 10-band Graphic Faders, Index 1 = Parametric PEQ Editor
        self.mode_stack = QStackedWidget()

        strip = QFrame()
        strip.setObjectName('eqStripFrame')
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(14, 14, 14, 14)
        strip_layout.setSpacing(6)

        self.preamp_slider, self.preamp_val = self._make_vertical_fader(strip_layout, 'Pre', -120, 120, 0)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet('background: #202C3C; border: none;')
        strip_layout.addWidget(sep)

        self.band_sliders: list[_ResettableSlider] = []
        self.band_labels: list[QLabel] = []
        for lbl in EQ_LABELS:
            sld, val_lbl = self._make_vertical_fader(strip_layout, lbl, -120, 120, 0)
            self.band_sliders.append(sld)
            self.band_labels.append(val_lbl)
        self.mode_stack.addWidget(strip)

        peq_frame = QFrame()
        peq_frame.setObjectName('eqStripFrame')
        peq_v = QVBoxLayout(peq_frame)
        peq_v.setContentsMargins(12, 10, 12, 10)
        peq_v.setSpacing(8)

        peq_bar = QHBoxLayout()
        peq_bar.setSpacing(8)
        lbl_pre_t = QLabel('Preamp:')
        lbl_pre_t.setStyleSheet('font-size: 11px; color: #9AAABC;')
        peq_bar.addWidget(lbl_pre_t)
        self.peq_preamp_spin = QDoubleSpinBox()
        self.peq_preamp_spin.setRange(-12.0, 12.0)
        self.peq_preamp_spin.setSingleStep(0.5)
        self.peq_preamp_spin.setDecimals(1)
        self.peq_preamp_spin.setSuffix(' dB')
        self.peq_preamp_spin.setFixedWidth(84)
        self.peq_preamp_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        peq_bar.addWidget(self.peq_preamp_spin)

        self.lbl_peq_count = QLabel('0/16 dải PEQ')
        self.lbl_peq_count.setStyleSheet('font-size: 11px; color: #64778B;')
        peq_bar.addWidget(self.lbl_peq_count)
        peq_bar.addStretch()

        self.btn_add_peq = QPushButton('+ Thêm dải')
        self.btn_add_peq.setObjectName('peqSmallBtn')
        self.btn_add_peq.setFixedHeight(26)
        peq_bar.addWidget(self.btn_add_peq)

        self.btn_clear_peq = QPushButton('Xóa PEQ')
        self.btn_clear_peq.setObjectName('peqSmallBtn')
        self.btn_clear_peq.setFixedHeight(26)
        peq_bar.addWidget(self.btn_clear_peq)
        peq_v.addLayout(peq_bar)

        self.peq_scroll = QScrollArea()
        self.peq_scroll.setObjectName('peqScroll')
        self.peq_scroll.setWidgetResizable(True)
        self.peq_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        peq_body = QWidget()
        peq_body.setObjectName('peqScrollBody')
        self.peq_rows_layout = QVBoxLayout(peq_body)
        self.peq_rows_layout.setContentsMargins(0, 0, 2, 0)
        self.peq_rows_layout.setSpacing(6)
        self.peq_rows_layout.addStretch()
        self.peq_scroll.setWidget(peq_body)
        peq_v.addWidget(self.peq_scroll, stretch=1)

        self.mode_stack.addWidget(peq_frame)
        root.addWidget(self.mode_stack, stretch=1)

        # Bottom shelf & headroom bar
        bot = QFrame()
        bot.setObjectName('eqStripFrame')
        bot_layout = QHBoxLayout(bot)
        bot_layout.setContentsMargins(14, 9, 14, 9)
        bot_layout.setSpacing(18)

        pre_col = QHBoxLayout()
        pre_col.setSpacing(8)
        self.auto_preamp_cb = QCheckBox('Tự giảm Preamp')
        self.auto_preamp_cb.setChecked(True)
        self.auto_preamp_cb.setToolTip('Tự giảm mức đầu vào theo đỉnh cộng hưởng để không vỡ tiếng.')
        self.lbl_auto_pad = QLabel('0 dB')
        self.lbl_auto_pad.setStyleSheet('color: #64778B; font-size: 11px; font-family: Consolas;')
        pre_col.addWidget(self.auto_preamp_cb)
        pre_col.addWidget(self.lbl_auto_pad)
        bot_layout.addLayout(pre_col)

        self.bass_slider, self.bass_lbl = self._make_horiz_knob(
            bot_layout, 'Trầm', -60, 80, ' dB', scale=0.1, tip='Bass Shelf 55 Hz'
        )
        self.treble_slider, self.treble_lbl = self._make_horiz_knob(
            bot_layout, 'Cao', -60, 80, ' dB', scale=0.1, tip='Treble Shelf 12.5 kHz'
        )
        self.crossfeed_slider, self.crossfeed_lbl = self._make_horiz_knob(
            bot_layout, 'Âm trường', 0, 100, '%', scale=1.0, tip='Crossfeed loa kiểm âm 30°'
        )
        root.addWidget(bot)

        self._rebuild_curve_combo()
        self._connect_signals()

    def _make_vertical_fader(self, parent_layout, title: str, lo: int, hi: int, default: int):
        col = QVBoxLayout()
        col.setSpacing(6)
        val_lbl = QLabel('0')
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_lbl.setFixedHeight(18)
        val_lbl.setStyleSheet('font-size: 11px; color: #5E7185; font-family: Consolas;')
        sld = _ResettableSlider(Qt.Orientation.Vertical, default_val=default)
        sld.setRange(lo, hi)
        sld.setValue(default)
        sld.setMinimumHeight(104)
        name_lbl = QLabel(title)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setFixedHeight(18)
        name_lbl.setStyleSheet('font-size: 11px; color: #8498AD;')
        col.addWidget(val_lbl)
        col.addWidget(sld, stretch=1, alignment=Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(name_lbl)
        parent_layout.addLayout(col, stretch=1)
        return sld, val_lbl

    def _make_horiz_knob(self, parent_layout, title: str, lo: int, hi: int, suffix: str, scale: float, tip: str = ''):
        col = QVBoxLayout()
        col.setSpacing(3)
        top = QHBoxLayout()
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet('font-size: 11px; color: #9AAABC;')
        if tip:
            lbl_t.setToolTip(tip)
        lbl_v = QLabel(f'0{suffix}')
        lbl_v.setStyleSheet('font-size: 11px; color: #64778B; font-family: Consolas;')
        top.addWidget(lbl_t)
        top.addStretch()
        top.addWidget(lbl_v)
        sld = _ResettableSlider(Qt.Orientation.Horizontal, default_val=0)
        sld.setRange(lo, hi)
        sld.setValue(0)
        sld.setMinimumWidth(104)
        if tip:
            sld.setToolTip(f'{tip} · Nhấp đúp hoặc chuột phải để về 0')
        col.addLayout(top)
        col.addWidget(sld)
        parent_layout.addLayout(col, stretch=1)
        return sld, lbl_v

    def _connect_signals(self):
        self.enable_cb.toggled.connect(lambda _v: self._on_ui_edited(immediate=True))
        self.btn_mode_geq.clicked.connect(lambda: self.set_eq_mode('geq', emit_change=True))
        self.btn_mode_peq.clicked.connect(lambda: self.set_eq_mode('peq', emit_change=True))
        self.auto_preamp_cb.toggled.connect(lambda _v: self._on_ui_edited(immediate=True))
        self.preamp_slider.valueChanged.connect(self._on_preamp_slider_changed)
        self.peq_preamp_spin.valueChanged.connect(self._on_peq_preamp_spin_changed)
        self.btn_add_peq.clicked.connect(lambda: self.add_peq_band(('PK', 1000.0, 0.0, 1.414), emit_change=True))
        self.btn_clear_peq.clicked.connect(self._clear_peq_bands)
        for sld in self.band_sliders:
            sld.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        self.bass_slider.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        self.treble_slider.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        self.crossfeed_slider.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))

        self.curve_combo.currentIndexChanged.connect(self._on_curve_selected)
        self.btn_save_preset.clicked.connect(self.save_user_preset_prompt)
        self.btn_delete_preset.clicked.connect(self.delete_selected_user_preset)
        self.btn_ab.pressed.connect(self.start_ab_compare)
        self.btn_ab.released.connect(self.stop_ab_compare)
        self.btn_reset.clicked.connect(self.reset_flat)

        self.act_open_txt.triggered.connect(self.open_apo_file_dialog)
        self.act_save_txt.triggered.connect(self.save_apo_file_dialog)
        self.act_paste_apo.triggered.connect(self.paste_apo_from_clipboard)
        self.act_copy_apo.triggered.connect(self.copy_apo_to_clipboard)

        self.btn_open_txt.clicked.connect(self.open_apo_file_dialog)
        self.btn_save_txt.clicked.connect(self.save_apo_file_dialog)
        self.btn_paste_apo.clicked.connect(self.paste_apo_from_clipboard)
        self.btn_copy_apo.clicked.connect(self.copy_apo_to_clipboard)

    def _on_preamp_slider_changed(self, val: int):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.peq_preamp_spin.setValue(round(val / 10.0, 1))
        finally:
            self._syncing = False
        self._on_ui_edited(immediate=False)

    def _on_peq_preamp_spin_changed(self, val: float):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.preamp_slider.setValue(int(round(val * 10.0)))
        finally:
            self._syncing = False
        self._on_ui_edited(immediate=False)

    def set_eq_mode(self, mode: str, emit_change: bool = False):
        target = 'peq' if mode == 'peq' else 'geq'
        if target == 'peq' and not self._peq_rows:
            self._add_peq_row_widget(('PK', 1000.0, 0.0, 1.414))
        self._eq_mode = target
        self.mode_stack.setCurrentIndex(1 if target == 'peq' else 0)
        self.btn_mode_geq.setProperty('peqModeActive', target == 'geq')
        self.btn_mode_peq.setProperty('peqModeActive', target == 'peq')
        for b in (self.btn_mode_geq, self.btn_mode_peq):
            b.style().unpolish(b)
            b.style().polish(b)
        self._update_peq_header()
        if emit_change:
            self._refresh_readouts()
            self._emit_timer.stop()
            self._emit_now()

    def _update_peq_header(self):
        n = len(self._peq_rows)
        self.lbl_peq_count.setText(f'{n}/{MAX_PEQ_FILTERS} dải PEQ')
        self.btn_add_peq.setEnabled(n < MAX_PEQ_FILTERS)
        self.btn_clear_peq.setEnabled(n > 0)

    def _add_peq_row_widget(self, item: tuple[str, float, float, float]):
        if len(self._peq_rows) >= MAX_PEQ_FILTERS:
            return
        kind, freq_hz, gain_db, q_val = item
        row_w = QWidget()
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(6)

        cb_kind = QComboBox()
        cb_kind.addItem('PK', 'PK')
        cb_kind.addItem('LS', 'LS')
        cb_kind.addItem('HS', 'HS')
        cb_kind.setFixedWidth(64)
        cb_kind.setFixedHeight(28)
        cb_kind.setCurrentIndex(max(0, cb_kind.findData(kind)))

        sp_freq = QDoubleSpinBox()
        sp_freq.setRange(10.0, 24000.0)
        sp_freq.setDecimals(1)
        sp_freq.setSingleStep(10.0)
        sp_freq.setSuffix(' Hz')
        sp_freq.setValue(float(freq_hz))
        sp_freq.setFixedHeight(28)

        sp_gain = QDoubleSpinBox()
        sp_gain.setRange(-15.0, 15.0)
        sp_gain.setDecimals(2)
        sp_gain.setSingleStep(0.2)
        sp_gain.setSuffix(' dB')
        sp_gain.setValue(float(gain_db))
        sp_gain.setFixedHeight(28)

        sp_q = QDoubleSpinBox()
        sp_q.setRange(0.10, 18.00)
        sp_q.setDecimals(2)
        sp_q.setSingleStep(0.1)
        sp_q.setPrefix('Q ')
        sp_q.setValue(float(q_val))
        sp_q.setFixedHeight(28)

        btn_del = QPushButton('×')
        btn_del.setObjectName('peqDelBtn')
        btn_del.setFixedSize(26, 26)

        row_l.addWidget(cb_kind)
        row_l.addWidget(sp_freq, stretch=1)
        row_l.addWidget(sp_gain, stretch=1)
        row_l.addWidget(sp_q, stretch=1)
        row_l.addWidget(btn_del)

        entry = {'widget': row_w, 'kind': cb_kind, 'freq': sp_freq, 'gain': sp_gain, 'q': sp_q}
        cb_kind.currentIndexChanged.connect(lambda _i: self._on_ui_edited(immediate=True))
        sp_freq.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        sp_gain.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        sp_q.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        btn_del.clicked.connect(lambda: self._remove_peq_row(entry))

        insert_at = max(0, self.peq_rows_layout.count() - 1)
        self.peq_rows_layout.insertWidget(insert_at, row_w)
        self._peq_rows.append(entry)
        self._update_peq_header()

    def add_peq_band(self, item: tuple[str, float, float, float], emit_change: bool = True):
        self._add_peq_row_widget(item)
        if emit_change:
            self._on_ui_edited(immediate=True)

    def _remove_peq_row(self, entry: dict):
        if entry in self._peq_rows:
            self._peq_rows.remove(entry)
            w = entry['widget']
            self.peq_rows_layout.removeWidget(w)
            w.deleteLater()
            self._update_peq_header()
            self._on_ui_edited(immediate=True)

    def _set_peq_rows(self, peq_filters):
        for entry in list(self._peq_rows):
            w = entry['widget']
            self.peq_rows_layout.removeWidget(w)
            w.deleteLater()
        self._peq_rows.clear()
        for item in normalize_peq_filters(peq_filters):
            self._add_peq_row_widget(item)
        self._update_peq_header()

    def _clear_peq_bands(self):
        self._set_peq_rows(())
        self._on_ui_edited(immediate=True)

    def _current_peq_tuple(self) -> tuple[tuple[str, float, float, float], ...]:
        if self._eq_mode != 'peq' or not self._peq_rows:
            return ()
        raw = [
            (str(e['kind'].currentData() or 'PK'), e['freq'].value(), e['gain'].value(), e['q'].value())
            for e in self._peq_rows
        ]
        return normalize_peq_filters(raw)

    def _show_toast(self, text: str, persistent: bool = False):
        self._toast_timer.stop()
        self.lbl_info.setText(text)
        self.lbl_info.setVisible(bool(text))
        if text and not persistent:
            self._toast_timer.start()

    def _clear_toast(self):
        self.lbl_info.setText('')
        self.lbl_info.hide()

    def _rebuild_curve_combo(self):
        cur = self.curve_combo.currentData()
        self.curve_combo.blockSignals(True)
        self.curve_combo.clear()
        for key, (label, _) in EQ_CURVES.items():
            self.curve_combo.addItem(label, key)
        for key, (label, _pre, _filts) in PEQ_CURVES.items():
            self.curve_combo.addItem(label, f'peq:{key}')
        for name in sorted(self._user_presets):
            self.curve_combo.addItem(name, f'user:{name}')
        self.curve_combo.addItem('Tùy chỉnh', 'custom')
        if cur is not None:
            idx = self.curve_combo.findData(cur)
            if idx >= 0:
                self.curve_combo.setCurrentIndex(idx)
        self.curve_combo.blockSignals(False)

    def current_eq_dict(self) -> dict:
        return {
            'eq_enabled': bool(self.enable_cb.isChecked()),
            'eq_bands': tuple(round(s.value() / 10.0, 2) for s in self.band_sliders),
            'eq_peq_filters': self._current_peq_tuple(),
            'eq_preamp_db': round(self.preamp_slider.value() / 10.0, 2),
            'eq_auto_preamp': bool(self.auto_preamp_cb.isChecked()),
            'eq_bass_db': round(self.bass_slider.value() / 10.0, 2),
            'eq_treble_db': round(self.treble_slider.value() / 10.0, 2),
            'eq_crossfeed': int(self.crossfeed_slider.value()),
        }

    @staticmethod
    def _set_fader_readout(label: QLabel, val: float, active_color: str = '#77E0BE'):
        if abs(val) < 0.05:
            label.setText('0')
            label.setStyleSheet('font-size: 11px; color: #5E7185; font-family: Consolas;')
        else:
            label.setText(f'{val:+.1f}')
            label.setStyleSheet(f'font-size: 11px; color: {active_color}; font-family: Consolas;')

    def _refresh_readouts(self):
        eq_data = self.current_eq_dict()
        prof = AudioProfile.from_dict(eq_data)
        self._set_fader_readout(self.preamp_val, eq_data['eq_preamp_db'], active_color='#EDF3FA')
        for sld, lbl in zip(self.band_sliders, self.band_labels):
            self._set_fader_readout(lbl, sld.value() / 10.0)

        for lbl_w, val, suffix, is_pct in (
            (self.bass_lbl, eq_data['eq_bass_db'], ' dB', False),
            (self.treble_lbl, eq_data['eq_treble_db'], ' dB', False),
            (self.crossfeed_lbl, eq_data['eq_crossfeed'], '%', True),
        ):
            if is_pct:
                if val <= 0:
                    lbl_w.setText('0%')
                    lbl_w.setStyleSheet('font-size: 11px; color: #64778B; font-family: Consolas;')
                else:
                    lbl_w.setText(f'{val}%')
                    lbl_w.setStyleSheet('font-size: 11px; color: #77E0BE; font-family: Consolas;')
            else:
                if abs(val) < 0.05:
                    lbl_w.setText(f'0{suffix}')
                    lbl_w.setStyleSheet('font-size: 11px; color: #64778B; font-family: Consolas;')
                else:
                    lbl_w.setText(f'{val:+.1f}{suffix}')
                    lbl_w.setStyleSheet('font-size: 11px; color: #77E0BE; font-family: Consolas;')

        eff_pre = effective_eq_preamp_db(prof, force_preview=True)
        if abs(eff_pre) < 0.05:
            self.lbl_auto_pad.setText('0 dB')
            self.lbl_auto_pad.setStyleSheet('color: #64778B; font-size: 11px; font-family: Consolas;')
        else:
            self.lbl_auto_pad.setText(f'{eff_pre:+.1f} dB')
            self.lbl_auto_pad.setStyleSheet('color: #77E0BE; font-size: 11px; font-family: Consolas;')

        self.canvas.set_profile(prof)

        matched = None
        for name, entry in self._user_presets.items():
            target_b = normalize_eq_bands(entry.get('eq_bands'))
            target_peq = normalize_peq_filters(entry.get('eq_peq_filters'))
            if (
                eq_data['eq_peq_filters'] == target_peq
                and all(abs(a - b) < 0.05 for a, b in zip(eq_data['eq_bands'], target_b))
                and abs(eq_data['eq_preamp_db'] - float(entry.get('eq_preamp_db', 0.0))) < 0.05
                and abs(eq_data['eq_bass_db'] - float(entry.get('eq_bass_db', 0.0))) < 0.05
                and abs(eq_data['eq_treble_db'] - float(entry.get('eq_treble_db', 0.0))) < 0.05
                and eq_data['eq_crossfeed'] == int(entry.get('eq_crossfeed', 0))
            ):
                matched = f'user:{name}'
                break
        if matched is None and eq_data['eq_peq_filters']:
            for key, (_, pre_val, filts) in PEQ_CURVES.items():
                if (
                    eq_data['eq_peq_filters'] == normalize_peq_filters(filts)
                    and abs(eq_data['eq_preamp_db'] - pre_val) < 0.05
                    and abs(eq_data['eq_bass_db']) < 0.05
                    and abs(eq_data['eq_treble_db']) < 0.05
                    and eq_data['eq_crossfeed'] == 0
                ):
                    matched = f'peq:{key}'
                    break
        if matched is None and not eq_data['eq_peq_filters']:
            matched = detect_eq_curve(eq_data['eq_bands'])
            if matched != 'custom' and (
                abs(eq_data['eq_bass_db']) >= 0.05
                or abs(eq_data['eq_treble_db']) >= 0.05
                or eq_data['eq_crossfeed'] > 0
                or abs(eq_data['eq_preamp_db']) >= 0.05
            ):
                matched = 'custom'
        if matched is None:
            matched = 'custom'
        self.curve_combo.blockSignals(True)
        idx = self.curve_combo.findData(matched)
        self.curve_combo.setCurrentIndex(idx if idx >= 0 else max(0, self.curve_combo.findData('custom')))
        self.curve_combo.blockSignals(False)
        self.btn_delete_preset.setEnabled(str(self.curve_combo.currentData() or '').startswith('user:'))

    def _on_ui_edited(self, immediate: bool = False):
        if self._syncing:
            return
        self._refresh_readouts()
        if immediate:
            self._emit_timer.stop()
            self._emit_now()
        else:
            self._emit_timer.start()

    def _emit_now(self):
        if not self._syncing:
            self.eq_changed.emit(self.current_eq_dict())

    def flush_pending(self):
        if self._emit_timer.isActive():
            self._emit_timer.stop()
            self._emit_now()

    def _on_curve_selected(self, *_):
        if self._syncing:
            return
        key = self.curve_combo.currentData()
        if key == 'custom' or not key:
            self.btn_delete_preset.setEnabled(False)
            return
        self._syncing = True
        try:
            self.enable_cb.setChecked(True)
            if isinstance(key, str) and key.startswith('peq:'):
                peq_key = key[4:]
                _, pre_val, filts = PEQ_CURVES.get(peq_key, ('', 0.0, ()))
                self.preamp_slider.setValue(int(round(pre_val * 10)))
                self.peq_preamp_spin.setValue(float(pre_val))
                self._set_peq_rows(filts)
                self.set_eq_mode('peq', emit_change=False)
            elif isinstance(key, str) and key.startswith('user:'):
                name = key[5:]
                entry = self._user_presets.get(name, {})
                bands = normalize_eq_bands(entry.get('eq_bands'))
                peq = normalize_peq_filters(entry.get('eq_peq_filters'))
                pre_val = float(entry.get('eq_preamp_db', 0.0))
                self.preamp_slider.setValue(int(round(pre_val * 10)))
                self.peq_preamp_spin.setValue(pre_val)
                self.bass_slider.setValue(int(round(float(entry.get('eq_bass_db', 0.0)) * 10)))
                self.treble_slider.setValue(int(round(float(entry.get('eq_treble_db', 0.0)) * 10)))
                self.crossfeed_slider.setValue(int(entry.get('eq_crossfeed', 0)))
                for sld, g in zip(self.band_sliders, bands):
                    sld.setValue(int(round(g * 10)))
                self._set_peq_rows(peq)
                self.set_eq_mode('peq' if peq else 'geq', emit_change=False)
            else:
                bands = EQ_CURVES.get(key, EQ_CURVES['flat'])[1]
                for sld, g in zip(self.band_sliders, bands):
                    sld.setValue(int(round(g * 10)))
                self.set_eq_mode('geq', emit_change=False)
        finally:
            self._syncing = False
        self._refresh_readouts()
        self._emit_timer.stop()
        self._emit_now()

    def set_state(self, profile: AudioProfile, user_presets: dict | None = None):
        if isinstance(user_presets, dict):
            self._user_presets = dict(user_presets)
            self._rebuild_curve_combo()
        peq = normalize_peq_filters(getattr(profile, 'eq_peq_filters', ()))
        self._syncing = True
        try:
            self.enable_cb.setChecked(True if self._ab_holding else bool(profile.eq_enabled))
            self.auto_preamp_cb.setChecked(bool(profile.eq_auto_preamp))
            pre_val = float(profile.eq_preamp_db)
            self.preamp_slider.setValue(int(round(pre_val * 10)))
            self.peq_preamp_spin.setValue(pre_val)
            for sld, g in zip(self.band_sliders, normalize_eq_bands(profile.eq_bands)):
                sld.setValue(int(round(g * 10)))
            if peq:
                self._set_peq_rows(peq)
                self.set_eq_mode('peq', emit_change=False)
            elif self._eq_mode != 'peq':
                self.set_eq_mode('geq', emit_change=False)
            self.bass_slider.setValue(int(round(float(profile.eq_bass_db) * 10)))
            self.treble_slider.setValue(int(round(float(profile.eq_treble_db) * 10)))
            self.crossfeed_slider.setValue(int(profile.eq_crossfeed))
        finally:
            self._syncing = False
        self._refresh_readouts()

    def save_user_preset(self, name: str):
        clean = (name or '').strip()[:48]
        if not clean:
            return False
        data = self.current_eq_dict()
        self._user_presets[clean] = {
            'eq_bands': list(data['eq_bands']),
            'eq_peq_filters': [list(f) for f in data['eq_peq_filters']],
            'eq_preamp_db': data['eq_preamp_db'],
            'eq_bass_db': data['eq_bass_db'],
            'eq_treble_db': data['eq_treble_db'],
            'eq_crossfeed': data['eq_crossfeed'],
        }
        self._rebuild_curve_combo()
        self.user_presets_changed.emit(dict(self._user_presets))
        self._refresh_readouts()
        return True

    def save_user_preset_prompt(self):
        name, ok = QInputDialog.getText(self, 'Lưu mẫu EQ', 'Tên mẫu:')
        if ok and name.strip():
            self.save_user_preset(name)

    def delete_selected_user_preset(self):
        key = str(self.curve_combo.currentData() or '')
        if key.startswith('user:'):
            name = key[5:]
            if name in self._user_presets:
                del self._user_presets[name]
                self._rebuild_curve_combo()
                self.user_presets_changed.emit(dict(self._user_presets))
                self._refresh_readouts()

    def copy_apo_to_clipboard(self):
        prof = AudioProfile.from_dict(self.current_eq_dict())
        txt = export_apo_text(prof)
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(txt)
        self._show_toast('Đã chép APO')

    def apply_apo_text(self, text: str) -> bool:
        parsed = parse_apo_text(text)
        if parsed is None:
            self._show_toast('Không đọc được định dạng APO')
            return False
        peq = normalize_peq_filters(parsed.get('eq_peq_filters'))
        self._syncing = True
        try:
            self.enable_cb.setChecked(True)
            pre_val = float(parsed['eq_preamp_db'])
            self.preamp_slider.setValue(int(round(pre_val * 10)))
            self.peq_preamp_spin.setValue(pre_val)
            for sld, g in zip(self.band_sliders, parsed['eq_bands']):
                sld.setValue(int(round(g * 10)))
            self._set_peq_rows(peq)
            self.set_eq_mode('peq' if peq else 'geq', emit_change=False)
        finally:
            self._syncing = False
        self._refresh_readouts()
        self._emit_timer.stop()
        self._emit_now()
        self._show_toast(f'Đã nhập PEQ ({len(peq)} dải)' if peq else 'Đã nhập APO')
        return True

    def paste_apo_from_clipboard(self):
        cb = QApplication.clipboard()
        self.apply_apo_text(cb.text() if cb is not None else '')

    def start_ab_compare(self):
        if self._ab_holding or not self.enable_cb.isChecked():
            return
        self._ab_holding = True
        self.btn_ab.setProperty('abActive', True)
        self.btn_ab.style().unpolish(self.btn_ab)
        self.btn_ab.style().polish(self.btn_ab)
        self.btn_ab.setText('Gốc')
        self._show_toast('Đang nghe âm gốc', persistent=True)
        self._emit_timer.stop()
        cur = self.current_eq_dict()
        self.canvas.set_profile(replace(AudioProfile.from_dict(cur), eq_enabled=False))
        cur['eq_enabled'] = False
        self.eq_changed.emit(cur)

    def stop_ab_compare(self):
        if not self._ab_holding:
            return
        self._ab_holding = False
        self._syncing = True
        try:
            self.enable_cb.setChecked(True)
        finally:
            self._syncing = False
        self.btn_ab.setProperty('abActive', False)
        self.btn_ab.style().unpolish(self.btn_ab)
        self.btn_ab.style().polish(self.btn_ab)
        self.btn_ab.setText('A/B')
        self._clear_toast()
        self._refresh_readouts()
        self._emit_timer.stop()
        self.eq_changed.emit(self.current_eq_dict())

    def import_apo_file(self, path) -> bool:
        try:
            text = Path(path).read_text(encoding='utf-8-sig')
        except OSError:
            self._show_toast('Không mở được file .txt')
            return False
        ok = self.apply_apo_text(text)
        if ok:
            self._show_toast(f'Đã nạp {Path(path).name}')
        return ok

    def export_apo_file(self, path) -> bool:
        try:
            prof = AudioProfile.from_dict(self.current_eq_dict())
            target = Path(path)
            atomic_bytes(target, (export_apo_text(prof) + '\n').encode('utf-8'))
            self._show_toast(f'Đã lưu {target.name}')
            return True
        except OSError:
            self._show_toast('Không lưu được file .txt')
            return False

    def open_apo_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Mở cấu hình Equalizer APO (.txt)', '', 'Equalizer APO (*.txt);;All Files (*)'
        )
        if path:
            self.import_apo_file(path)

    def save_apo_file_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Lưu cấu hình Equalizer APO (.txt)', 'botube-eq.txt', 'Equalizer APO (*.txt);;All Files (*)'
        )
        if path:
            self.export_apo_file(path)

    def reset_flat(self):
        self._syncing = True
        try:
            self.preamp_slider.setValue(0)
            self.peq_preamp_spin.setValue(0.0)
            for sld, g in zip(self.band_sliders, FLAT_EQ_BANDS):
                sld.setValue(int(round(g * 10)))
            self._set_peq_rows(())
            self.bass_slider.setValue(0)
            self.treble_slider.setValue(0)
            self.crossfeed_slider.setValue(0)
        finally:
            self._syncing = False
        self._refresh_readouts()
        self._emit_timer.stop()
        self._emit_now()
        self._show_toast('Đã đặt lại 0 dB')

    def hideEvent(self, event):
        self.stop_ab_compare()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.stop_ab_compare()
        self.flush_pending()
        super().closeEvent(event)
