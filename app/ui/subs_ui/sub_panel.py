from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QSlider, QPushButton, QFrame, QComboBox, 
                               QColorDialog, QCheckBox)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from subtitle.mode import SubtitleMode

class SettingsPanel(QWidget):
    # --- Tín hiệu (Signals) ---
    font_size_changed = Signal(int)
    font_color_changed = Signal(str)
    
    outline_changed = Signal(bool, int, str)  # (bật/tắt, độ dày, màu)
    shadow_changed = Signal(bool, int)       # (bật/tắt, độ đậm)
    
    bg_color_changed = Signal(str)
    bg_opacity_changed = Signal(float)
    
    playback_speed_changed = Signal(float)
    subtitle_mode_changed = Signal(object)
    lock_position_changed = Signal(bool)
    fade_effect_changed = Signal(bool)       # Tín hiệu Bật/Tắt Hiệu ứng Fade In/Out
    
    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(320)
        self.speed_btns = []
        self._current_outline_color = "#000000"

        # --- Style (CSS) ---
        self.setStyleSheet("""
            QWidget { background-color: #151C26; color: #EDF3FA; border: 1px solid #273445; border-radius: 8px; }
            QLabel { border: none; font-weight: bold; font-size: 13px; margin-top: 5px; }
            QComboBox { background-color: #1B2431; border: 1px solid #405267; padding: 4px; border-radius: 6px; color: white; }
            QComboBox::drop-down { border: none; }
            QPushButton { background-color: #1B2431; border: none; border-radius: 6px; padding: 6px; }
            QPushButton:hover { background-color: #505050; }
            QSlider::handle:horizontal { background: #1DB954; width: 16px; margin: -5px 0; border-radius: 8px; }
            QPushButton#btn_reset { background-color: #8B0000; color: white; font-weight: bold; }
            QPushButton#btn_reset:hover { background-color: #FF4500; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # --- 1. CHẾ ĐỘ HIỂN THỊ (MODE) ---
        layout.addWidget(QLabel("Chế độ hiển thị"))
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
        layout.addWidget(self.combo_mode)

        layout.addWidget(self._sep())

        # --- 2. GIAO DIỆN CHỮ (Size + Color) ---
        layout.addWidget(QLabel("Cỡ chữ & Màu chữ"))
        font_layout = QHBoxLayout()
        
        self.slider_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_size.setRange(18, 72)
        self.slider_size.setValue(24)
        self.slider_size.setToolTip("Kéo để chỉnh cỡ chữ")
        self.slider_size.valueChanged.connect(self.font_size_changed.emit)
        
        self.btn_font_color = QPushButton("A")
        self.btn_font_color.setFixedSize(30, 24)
        self.btn_font_color.setToolTip("Chọn màu chữ")
        self.btn_font_color.clicked.connect(lambda: self._open_color_dialog("font"))
        self._set_btn_color(self.btn_font_color, "#FFFF00")
        
        font_layout.addWidget(self.slider_size)
        font_layout.addWidget(self.btn_font_color)
        layout.addLayout(font_layout)

        layout.addWidget(self._sep())

        # --- 3. GIAO DIỆN NỀN (Opacity + Color) ---
        layout.addWidget(QLabel("Độ mờ nền & Màu nền"))
        bg_layout = QHBoxLayout()
        
        self.combo_opacity = QComboBox()
        self.combo_opacity.addItem("0% (Trong suốt)", 0.0)
        self.combo_opacity.addItem("25%", 0.25)
        self.combo_opacity.addItem("50% (Mặc định)", 0.5)
        self.combo_opacity.addItem("75%", 0.75)
        self.combo_opacity.addItem("100% (Đặc)", 1.0)
        
        self.combo_opacity.setCurrentIndex(2)
        self.combo_opacity.currentIndexChanged.connect(self._on_opacity_changed)
        
        self.btn_bg_color = QPushButton("Bg")
        self.btn_bg_color.setFixedSize(30, 24)
        self.btn_bg_color.setToolTip("Chọn màu nền")
        self.btn_bg_color.clicked.connect(lambda: self._open_color_dialog("bg"))
        self._set_btn_color(self.btn_bg_color, "#000000", is_dark_bg=True)
        
        bg_layout.addWidget(self.combo_opacity)
        bg_layout.addWidget(self.btn_bg_color)
        layout.addLayout(bg_layout)

        layout.addWidget(self._sep())

        # --- 3.5 TÙY CHỈNH VIỀN & BÓNG ---
        layout.addWidget(QLabel("Viền & Bóng đổ"))
        
        out_layout = QHBoxLayout()
        self.chk_outline = QCheckBox("Viền")
        self.chk_outline.setChecked(True)
        self.chk_outline.stateChanged.connect(self._emit_style_update)
        
        self.slider_out_width = QSlider(Qt.Orientation.Horizontal)
        self.slider_out_width.setRange(0, 10)
        self.slider_out_width.setValue(4)
        self.slider_out_width.valueChanged.connect(self._emit_style_update)
        
        self.btn_out_color = QPushButton("C")
        self.btn_out_color.setFixedSize(25, 20)
        self.btn_out_color.clicked.connect(lambda: self._open_color_dialog("outline"))
        self._set_btn_color(self.btn_out_color, self._current_outline_color, is_dark_bg=True)
        
        out_layout.addWidget(self.chk_outline)
        out_layout.addWidget(self.slider_out_width)
        out_layout.addWidget(self.btn_out_color)
        layout.addLayout(out_layout)

        sha_layout = QHBoxLayout()
        self.chk_shadow = QCheckBox("Bóng")
        self.chk_shadow.setChecked(True)
        self.chk_shadow.stateChanged.connect(self._emit_style_update)
        
        self.slider_sha_alpha = QSlider(Qt.Orientation.Horizontal)
        self.slider_sha_alpha.setRange(0, 255)
        self.slider_sha_alpha.setValue(160)
        self.slider_sha_alpha.valueChanged.connect(self._emit_style_update)
        
        sha_layout.addWidget(self.chk_shadow)
        sha_layout.addWidget(self.slider_sha_alpha)
        layout.addLayout(sha_layout)

        layout.addWidget(self._sep())
        
        # --- 4. TỐC ĐỘ PHÁT ---
        layout.addWidget(QLabel("Tốc độ phát"))
        speed_layout = QHBoxLayout()
        speeds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
        
        for speed in speeds:
            btn = QPushButton(f"{speed}x")
            btn.setCheckable(True)
            btn.setFixedSize(40, 25)
            btn.setStyleSheet("font-size: 11px;")
            if speed == 1.0:
                btn.setChecked(True)
                btn.setStyleSheet("background-color: #1DB954; color: white; border: none;")
            
            self.speed_btns.append(btn)
            btn.clicked.connect(lambda checked, s=speed, b=btn: self._on_speed_click(s, b))
            speed_layout.addWidget(btn)
            
        layout.addLayout(speed_layout)
        
        layout.addWidget(self._sep())

        # --- 5. CHỨC NĂNG KHÁC (Lock + Fade + Reset) ---
        layout.addWidget(QLabel("Tùy chọn khác"))
        other_options_layout = QVBoxLayout()
        other_options_layout.setSpacing(6)
        
        # Checkbox Khóa vị trí
        self.chk_lock = QCheckBox("Khóa vị trí phụ đề")
        self.chk_lock.toggled.connect(self.lock_position_changed.emit)
        other_options_layout.addWidget(self.chk_lock)
        
        # Checkbox Mờ dần (Fade effect)
        self.chk_fade = QCheckBox("Hiệu ứng Mờ dần (Fade)")
        self.chk_fade.setChecked(True)  # Mặc định bật
        self.chk_fade.toggled.connect(self.fade_effect_changed.emit)
        other_options_layout.addWidget(self.chk_fade)
        
        layout.addLayout(other_options_layout)
        
        # Nút Đặt lại (Reset)
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        self.btn_reset = QPushButton("Đặt lại")
        self.btn_reset.setObjectName("btn_reset")
        self.btn_reset.setFixedSize(60, 28)
        self.btn_reset.setToolTip("Khôi phục cài đặt gốc")
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        bottom_layout.addWidget(self.btn_reset)
        
        layout.addLayout(bottom_layout)
        layout.addStretch()

    # --- HÀM BỔ TRỢ ---

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #444; max-height: 1px;")
        return line
    
    def _set_btn_color(self, btn, hex_color, is_dark_bg=False):
        qcol = QColor(hex_color)
        luminance = (0.299 * qcol.red() + 0.587 * qcol.green() + 0.114 * qcol.blue()) / 255
        text_color = "black" if luminance > 0.5 else "white"
        
        btn.setStyleSheet(f"""
            background-color: {hex_color}; 
            color: {text_color}; 
            border: 1px solid #777; 
            font-weight: bold;
        """)

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
            if btn == clicked_btn:
                btn.setChecked(True)
                btn.setStyleSheet("background-color: #1DB954; color: white; border: none;")
            else:
                btn.setChecked(False)
                btn.setStyleSheet("background-color: transparent; border: 1px solid #555;")

    def _on_reset_clicked(self):
        self.blockSignals(True)
        
        idx_en_vi = self.combo_mode.findData(SubtitleMode.EN_VI)
        if idx_en_vi != -1: self.combo_mode.setCurrentIndex(idx_en_vi)
        
        self.slider_size.setValue(24)
        self._set_btn_color(self.btn_font_color, "#FFFF00")
        
        self.combo_opacity.setCurrentIndex(2)
        self._set_btn_color(self.btn_bg_color, "#000000", is_dark_bg=True)
        
        self.chk_lock.setChecked(False)
        self.chk_fade.setChecked(True)
        self.speed_btns[2].setChecked(True)
        
        self.chk_outline.setChecked(True)
        self.slider_out_width.setValue(4)
        self._current_outline_color = "#000000"
        self._set_btn_color(self.btn_out_color, "#000000", is_dark_bg=True)
        
        self.chk_shadow.setChecked(True)
        self.slider_sha_alpha.setValue(160)
        
        self.blockSignals(False)
        
        self.reset_requested.emit()

    def sync_ui(self, config):
        if not config: return
        
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
            if idx != -1: self.combo_mode.setCurrentIndex(idx)
        
        self.slider_size.setValue(config.get("font_size", 24))
        self._set_btn_color(self.btn_font_color, config.get("font_color", "#FFFF00"))
        
        saved_op = config.get("bg_opacity", 0.5)
        for i in range(self.combo_opacity.count()):
            if abs(self.combo_opacity.itemData(i) - saved_op) < 0.01:
                self.combo_opacity.setCurrentIndex(i)
                break
        self._set_btn_color(self.btn_bg_color, config.get("bg_color", "#000000"), is_dark_bg=True)

        self.chk_outline.setChecked(config.get("outline_enabled", True))
        self.slider_out_width.setValue(config.get("outline_width", 4))
        self._current_outline_color = config.get("outline_color", "#000000")
        self._set_btn_color(self.btn_out_color, self._current_outline_color, is_dark_bg=True)

        self.chk_shadow.setChecked(config.get("shadow_enabled", True))
        self.slider_sha_alpha.setValue(config.get("shadow_alpha", 160))

        self.chk_lock.setChecked(config.get("lock_position", False))
        self.chk_fade.setChecked(config.get("fade_enabled", True))
        
        self.blockSignals(False)
        
        self._emit_style_update()
        
    def get_current_mode(self):
        return self.combo_mode.currentData()
    
    def set_mode_visual(self, mode_enum):
        idx = self.combo_mode.findData(mode_enum)
        if idx != -1:
            self.combo_mode.setCurrentIndex(idx)
