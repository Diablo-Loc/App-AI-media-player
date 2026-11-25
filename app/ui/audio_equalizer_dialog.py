"""Studio 64-bit 10-band Parametric/Graphic Equalizer with live curve, shelves & APO import/export."""
import math

from PySide6.QtCore import Qt, QTimer, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.audio_profile import (
    AudioProfile,
    EQ_CURVES,
    EQ_FREQS,
    EQ_LABELS,
    FLAT_EQ_BANDS,
    custom_eq_peak_boost_db,
    detect_eq_curve,
    effective_eq_preamp_db,
    evaluate_eq_response_db,
    export_apo_text,
    normalize_eq_bands,
    parse_apo_text,
)
from ui.design_system import DIALOG_STYLE


class EqResponseCanvas(QWidget):
    """Real-time analytical biquad frequency response curve (20 Hz - 20 kHz, +/- 12 dB)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(132)
        self._profile = AudioProfile()
        log_min = math.log10(20.0)
        log_max = math.log10(20000.0)
        self._freqs = [10.0 ** (log_min + (log_max - log_min) * (i / 95.0)) for i in range(96)]

    def set_profile(self, profile: AudioProfile):
        self._profile = profile
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        pad_l, pad_r, pad_t, pad_b = 34.0, 12.0, 10.0, 20.0
        gw = max(20.0, w - pad_l - pad_r)
        gh = max(20.0, h - pad_t - pad_b)

        p.fillRect(self.rect(), QColor('#0E141D'))
        p.setPen(QPen(QColor('#223042'), 1.0))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)

        log_min = math.log10(20.0)
        log_max = math.log10(20000.0)

        def _x(freq: float) -> float:
            return pad_l + ((math.log10(max(20.0, freq)) - log_min) / (log_max - log_min)) * gw

        def _y(db: float) -> float:
            clamped = max(-14.0, min(14.0, float(db)))
            return pad_t + (1.0 - (clamped + 14.0) / 28.0) * gh

        # Horizontal dB grid
        p.setFont(self.font())
        for db in (12, 6, 0, -6, -12):
            yy = _y(db)
            p.setPen(QPen(QColor('#36495E' if db == 0 else '#1C2634'), 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            p.setPen(QColor('#6C8096'))
            p.drawText(2, int(yy) + 4, f'{db:+d}' if db != 0 else ' 0')

        # Vertical frequency grid
        for freq, lbl in zip(EQ_FREQS, EQ_LABELS):
            xx = _x(float(freq))
            p.setPen(QPen(QColor('#1C2634'), 1.0))
            p.drawLine(QPointF(xx, pad_t), QPointF(xx, pad_t + gh))
            p.setPen(QColor('#6C8096'))
            p.drawText(int(xx) - 10, int(h - 4), lbl)

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
            stroke_color = QColor('#77E0BE' if active else '#5C7085')
            fill_color = QColor(119, 224, 190, 46 if active else 20)
            p.fillPath(fill_path, QBrush(fill_color))

            curve_path = QPainterPath()
            curve_path.moveTo(pts[0])
            for pt in pts[1:]:
                curve_path.lineTo(pt)
            p.setPen(QPen(stroke_color, 2.0))
            p.drawPath(curve_path)

            band_vals = evaluate_eq_response_db(
                self._profile, list(EQ_FREQS), 48000.0, include_preamp=False, force_preview=True
            )
            p.setBrush(QBrush(stroke_color))
            p.setPen(QPen(QColor('#0D1118'), 1.0))
            for freq, bv in zip(EQ_FREQS, band_vals):
                p.drawEllipse(QPointF(_x(float(freq)), _y(bv)), 3.2, 3.2)


class _ResettableSlider(QSlider):
    """QSlider where double-click or right-click resets smoothly to zero."""

    def __init__(self, orientation, default_val: int = 0, parent=None):
        super().__init__(orientation, parent)
        self._default_val = int(default_val)

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
    """Real-time 64-bit 10-band EQ, preamp protection, shelf enhancers & Equalizer APO import/export."""

    eq_changed = Signal(dict)
    user_presets_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle('BoTube Studio Equalizer · 64-bit Float')
        self.resize(728, 492)
        self.setStyleSheet(DIALOG_STYLE + '''
            QDialog { background: #101722; color: #EDF3FA; font-family: 'Segoe UI'; }
            QSlider::groove:vertical { width: 5px; background: #263344; border-radius: 2px; }
            QSlider::sub-page:vertical { background: #263344; border-radius: 2px; }
            QSlider::add-page:vertical { background: #77E0BE; border-radius: 2px; }
            QSlider::handle:vertical { background: #EDF3FA; border: 2px solid #77E0BE;
                height: 12px; width: 12px; margin: 0 -4px; border-radius: 7px; }
            QSlider::groove:horizontal { height: 5px; background: #263344; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #77E0BE; border-radius: 2px; }
            QSlider::handle:horizontal { background: #EDF3FA; border: 2px solid #77E0BE;
                width: 12px; height: 12px; margin: -4px 0; border-radius: 7px; }
            QFrame#eqStripFrame { background: #151C26; border: 1px solid #223042; border-radius: 10px; }
        ''')

        self._user_presets: dict[str, dict] = {}
        self._syncing = False
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(140)
        self._emit_timer.timeout.connect(self._emit_now)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header row
        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        self.enable_cb = QCheckBox('Bật Equalizer 10 dải (64-bit Float)')
        self.enable_cb.setStyleSheet('font-weight: 600; font-size: 13px;')
        hdr.addWidget(self.enable_cb)
        hdr.addStretch()

        self.curve_combo = QComboBox()
        self.curve_combo.setMinimumWidth(230)
        self.curve_combo.setMinimumHeight(30)
        hdr.addWidget(self.curve_combo)

        self.btn_save_preset = QPushButton('Lưu mẫu…')
        self.btn_delete_preset = QPushButton('Xóa')
        self.btn_paste_apo = QPushButton('Dán APO')
        self.btn_copy_apo = QPushButton('Chép APO')
        self.btn_reset = QPushButton('0 dB')
        for btn in (self.btn_save_preset, self.btn_delete_preset, self.btn_paste_apo, self.btn_copy_apo, self.btn_reset):
            btn.setMinimumHeight(30)
            hdr.addWidget(btn)
        root.addLayout(hdr)

        # Live response graph
        self.canvas = EqResponseCanvas(self)
        root.addWidget(self.canvas)

        # Faders strip (Preamp + 10 EQ bands)
        strip = QFrame()
        strip.setObjectName('eqStripFrame')
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(12, 10, 12, 10)
        strip_layout.setSpacing(6)

        self.preamp_slider, self.preamp_val = self._make_vertical_fader(strip_layout, 'Preamp', -120, 120, 0)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet('background: #273445; max-width: 1px;')
        strip_layout.addWidget(sep)

        self.band_sliders: list[_ResettableSlider] = []
        self.band_labels: list[QLabel] = []
        for lbl in EQ_LABELS:
            sld, val_lbl = self._make_vertical_fader(strip_layout, f'{lbl}Hz', -120, 120, 0)
            self.band_sliders.append(sld)
            self.band_labels.append(val_lbl)
        root.addWidget(strip, stretch=1)

        # Bottom shelf & protection bar
        bot = QFrame()
        bot.setObjectName('eqStripFrame')
        bot_layout = QHBoxLayout(bot)
        bot_layout.setContentsMargins(12, 8, 12, 8)
        bot_layout.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.setSpacing(2)
        self.auto_preamp_cb = QCheckBox('Auto Preamp chống vỡ tiếng DAC')
        self.auto_preamp_cb.setChecked(True)
        self.lbl_auto_pad = QLabel('Đệm bảo vệ: 0.0 dB · Chuột phải/đúp vào thanh kéo để về 0 dB')
        self.lbl_auto_pad.setStyleSheet('color: #8CA0B5; font-size: 11px;')
        left_col.addWidget(self.auto_preamp_cb)
        left_col.addWidget(self.lbl_auto_pad)
        bot_layout.addLayout(left_col, stretch=2)

        self.bass_slider, self.bass_lbl = self._make_horiz_knob(bot_layout, 'Bass (55Hz)', -60, 80, ' dB', scale=0.1)
        self.treble_slider, self.treble_lbl = self._make_horiz_knob(bot_layout, 'Treble (12.5k)', -60, 80, ' dB', scale=0.1)
        self.crossfeed_slider, self.crossfeed_lbl = self._make_horiz_knob(bot_layout, 'Loa 30°', 0, 100, '%', scale=1.0)
        root.addWidget(bot)

        self.lbl_info = QLabel('Xử lý tức thì trong RAM (64-bit Float) · Không chạm file nhạc gốc · Không ghi ổ cứng')
        self.lbl_info.setStyleSheet('color: #77E0BE; font-size: 11px;')
        root.addWidget(self.lbl_info)

        self._rebuild_curve_combo()
        self._connect_signals()

    def _make_vertical_fader(self, parent_layout, title: str, lo: int, hi: int, default: int):
        col = QVBoxLayout()
        col.setSpacing(4)
        val_lbl = QLabel('+0.0')
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_lbl.setStyleSheet('font-size: 11px; color: #BFD0E0; font-family: Consolas;')
        sld = _ResettableSlider(Qt.Orientation.Vertical, default_val=default)
        sld.setRange(lo, hi)
        sld.setValue(default)
        sld.setMinimumHeight(138)
        name_lbl = QLabel(title)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet('font-size: 11px; color: #8CA0B5;')
        col.addWidget(val_lbl)
        col.addWidget(sld, alignment=Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(name_lbl)
        parent_layout.addLayout(col, stretch=1)
        return sld, val_lbl

    def _make_horiz_knob(self, parent_layout, title: str, lo: int, hi: int, suffix: str, scale: float):
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet('font-size: 11px; color: #8CA0B5;')
        lbl_v = QLabel(f'0{suffix}' if scale == 1.0 else f'+0.0{suffix}')
        lbl_v.setStyleSheet('font-size: 11px; color: #77E0BE; font-family: Consolas;')
        top.addWidget(lbl_t)
        top.addStretch()
        top.addWidget(lbl_v)
        sld = _ResettableSlider(Qt.Orientation.Horizontal, default_val=0)
        sld.setRange(lo, hi)
        sld.setValue(0)
        sld.setMinimumWidth(112)
        col.addLayout(top)
        col.addWidget(sld)
        parent_layout.addLayout(col, stretch=1)
        return sld, lbl_v

    def _connect_signals(self):
        self.enable_cb.toggled.connect(lambda _v: self._on_ui_edited(immediate=True))
        self.auto_preamp_cb.toggled.connect(lambda _v: self._on_ui_edited(immediate=True))
        self.preamp_slider.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        for sld in self.band_sliders:
            sld.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        self.bass_slider.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        self.treble_slider.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))
        self.crossfeed_slider.valueChanged.connect(lambda _v: self._on_ui_edited(immediate=False))

        self.curve_combo.currentIndexChanged.connect(self._on_curve_selected)
        self.btn_save_preset.clicked.connect(self.save_user_preset_prompt)
        self.btn_delete_preset.clicked.connect(self.delete_selected_user_preset)
        self.btn_paste_apo.clicked.connect(self.paste_apo_from_clipboard)
        self.btn_copy_apo.clicked.connect(self.copy_apo_to_clipboard)
        self.btn_reset.clicked.connect(self.reset_flat)

    def _rebuild_curve_combo(self):
        cur = self.curve_combo.currentData()
        self.curve_combo.blockSignals(True)
        self.curve_combo.clear()
        for key, (label, _) in EQ_CURVES.items():
            self.curve_combo.addItem(label, key)
        for name in sorted(self._user_presets):
            self.curve_combo.addItem(f'★ {name}', f'user:{name}')
        self.curve_combo.addItem('Tùy chỉnh riêng (Custom)', 'custom')
        if cur is not None:
            idx = self.curve_combo.findData(cur)
            if idx >= 0:
                self.curve_combo.setCurrentIndex(idx)
        self.curve_combo.blockSignals(False)

    def current_eq_dict(self) -> dict:
        return {
            'eq_enabled': bool(self.enable_cb.isChecked()),
            'eq_bands': tuple(round(s.value() / 10.0, 2) for s in self.band_sliders),
            'eq_preamp_db': round(self.preamp_slider.value() / 10.0, 2),
            'eq_auto_preamp': bool(self.auto_preamp_cb.isChecked()),
            'eq_bass_db': round(self.bass_slider.value() / 10.0, 2),
            'eq_treble_db': round(self.treble_slider.value() / 10.0, 2),
            'eq_crossfeed': int(self.crossfeed_slider.value()),
        }

    def _refresh_readouts(self):
        eq_data = self.current_eq_dict()
        prof = AudioProfile.from_dict(eq_data)
        self.preamp_val.setText(f'{eq_data["eq_preamp_db"]:+.1f}')
        for sld, lbl in zip(self.band_sliders, self.band_labels):
            lbl.setText(f'{sld.value() / 10.0:+.1f}')
        self.bass_lbl.setText(f'{eq_data["eq_bass_db"]:+.1f} dB')
        self.treble_lbl.setText(f'{eq_data["eq_treble_db"]:+.1f} dB')
        self.crossfeed_lbl.setText(f'{eq_data["eq_crossfeed"]}%')
        pad_boost = custom_eq_peak_boost_db(prof, force_preview=True)
        eff_pre = effective_eq_preamp_db(prof, force_preview=True)
        self.lbl_auto_pad.setText(f'Đỉnh cộng thêm: +{pad_boost:.1f} dB · Preamp tổng: {eff_pre:+.1f} dB')
        self.canvas.set_profile(prof)

        # Match built-in or user preset cleanly
        matched = None
        for name, entry in self._user_presets.items():
            target_b = normalize_eq_bands(entry.get('eq_bands'))
            if (
                all(abs(a - b) < 0.05 for a, b in zip(eq_data['eq_bands'], target_b))
                and abs(eq_data['eq_preamp_db'] - float(entry.get('eq_preamp_db', 0.0))) < 0.05
                and abs(eq_data['eq_bass_db'] - float(entry.get('eq_bass_db', 0.0))) < 0.05
                and abs(eq_data['eq_treble_db'] - float(entry.get('eq_treble_db', 0.0))) < 0.05
                and eq_data['eq_crossfeed'] == int(entry.get('eq_crossfeed', 0))
            ):
                matched = f'user:{name}'
                break
        if matched is None:
            matched = detect_eq_curve(eq_data['eq_bands'])
            if matched != 'custom' and (
                abs(eq_data['eq_bass_db']) >= 0.05
                or abs(eq_data['eq_treble_db']) >= 0.05
                or eq_data['eq_crossfeed'] > 0
                or abs(eq_data['eq_preamp_db']) >= 0.05
            ):
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
            if isinstance(key, str) and key.startswith('user:'):
                name = key[5:]
                entry = self._user_presets.get(name, {})
                bands = normalize_eq_bands(entry.get('eq_bands'))
                self.preamp_slider.setValue(int(round(float(entry.get('eq_preamp_db', 0.0)) * 10)))
                self.bass_slider.setValue(int(round(float(entry.get('eq_bass_db', 0.0)) * 10)))
                self.treble_slider.setValue(int(round(float(entry.get('eq_treble_db', 0.0)) * 10)))
                self.crossfeed_slider.setValue(int(entry.get('eq_crossfeed', 0)))
            else:
                bands = EQ_CURVES.get(key, EQ_CURVES['flat'])[1]
            for sld, g in zip(self.band_sliders, bands):
                sld.setValue(int(round(g * 10)))
        finally:
            self._syncing = False
        self._refresh_readouts()
        self._emit_timer.stop()
        self._emit_now()

    def set_state(self, profile: AudioProfile, user_presets: dict | None = None):
        if isinstance(user_presets, dict):
            self._user_presets = dict(user_presets)
            self._rebuild_curve_combo()
        self._syncing = True
        try:
            self.enable_cb.setChecked(bool(profile.eq_enabled))
            self.auto_preamp_cb.setChecked(bool(profile.eq_auto_preamp))
            self.preamp_slider.setValue(int(round(float(profile.eq_preamp_db) * 10)))
            for sld, g in zip(self.band_sliders, normalize_eq_bands(profile.eq_bands)):
                sld.setValue(int(round(g * 10)))
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
        name, ok = QInputDialog.getText(self, 'Lưu mẫu EQ cá nhân', 'Đặt tên cho cấu hình EQ này:')
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
        self.lbl_info.setText('Đã chép cấu hình Equalizer APO vào Clipboard!')

    def apply_apo_text(self, text: str) -> bool:
        parsed = parse_apo_text(text)
        if parsed is None:
            self.lbl_info.setText('Không nhận diện được cú pháp Equalizer APO (cần Preamp / GraphicEQ / Filter).')
            return False
        self._syncing = True
        try:
            self.enable_cb.setChecked(True)
            self.preamp_slider.setValue(int(round(parsed['eq_preamp_db'] * 10)))
            for sld, g in zip(self.band_sliders, parsed['eq_bands']):
                sld.setValue(int(round(g * 10)))
        finally:
            self._syncing = False
        self._refresh_readouts()
        self._emit_timer.stop()
        self._emit_now()
        self.lbl_info.setText('Đã nhập thành công cấu hình Equalizer APO (64-bit Float)!')
        return True

    def paste_apo_from_clipboard(self):
        cb = QApplication.clipboard()
        self.apply_apo_text(cb.text() if cb is not None else '')

    def reset_flat(self):
        self._syncing = True
        try:
            self.preamp_slider.setValue(0)
            for sld, g in zip(self.band_sliders, FLAT_EQ_BANDS):
                sld.setValue(int(round(g * 10)))
            self.bass_slider.setValue(0)
            self.treble_slider.setValue(0)
            self.crossfeed_slider.setValue(0)
        finally:
            self._syncing = False
        self._refresh_readouts()
        self._emit_timer.stop()
        self._emit_now()
        self.lbl_info.setText('Đã đưa toàn bộ 10 dải EQ & hiệu ứng về 0.0 dB.')

    def closeEvent(self, event):
        self.flush_pending()
        super().closeEvent(event)
