from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                               QSlider, QPushButton, QFrame, QComboBox, 
                               QColorDialog, QCheckBox)
from PySide6.QtCore import Qt, Signal
from subtitle.mode import SubtitleMode

class SettingsPanel(QWidget):
    # --- Tín hiệu (Signals) ---
    font_size_changed = Signal(int)
    font_color_changed = Signal(str)
    
    # Tín hiệu cho Background (Mới)
    bg_color_changed = Signal(str)
    bg_opacity_changed = Signal(float)
    
    playback_speed_changed = Signal(float)
    subtitle_mode_changed = Signal(object)
    lock_position_changed = Signal(bool)
    
    # Tín hiệu Reset
    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(320) # Mở rộng chút để chứa đủ nút
        self.speed_btns = []

        # --- Style (CSS) ---
        self.setStyleSheet("""
            QWidget { background-color: #282828; color: white; border: 1px solid #404040; border-radius: 8px; }
            QLabel { border: none; font-weight: bold; font-size: 13px; margin-top: 5px; }
            QComboBox { background-color: #444; border: 1px solid #555; padding: 4px; border-radius: 4px; color: white; }
            QComboBox::drop-down { border: none; }
            QPushButton { background-color: #3E3E3E; border: none; border-radius: 4px; padding: 6px; }
            QPushButton:hover { background-color: #505050; }
            /* Slider */
            QSlider::handle:horizontal { background: #1DB954; width: 16px; margin: -5px 0; border-radius: 8px; }
            /* Nút Reset màu đỏ */
            QPushButton#btn_reset { background-color: #8B0000; color: white; font-weight: bold; }
            QPushButton#btn_reset:hover { background-color: #FF4500; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # --- 1. CHẾ ĐỘ HIỂN THỊ (MODE) ---
        layout.addWidget(QLabel("Chế độ hiển thị"))
        self.combo_mode = QComboBox()
        
        # Thêm Data: (Text hiển thị, Giá trị Enum)
        self.combo_mode.addItem("Tắt phụ đề", SubtitleMode.OFF)
        self.combo_mode.addItem("Chỉ Tiếng Nhật (JP)", SubtitleMode.JP)
        self.combo_mode.addItem("Chỉ Tiếng Anh (EN)", SubtitleMode.EN)
        self.combo_mode.addItem("Chỉ Tiếng Việt (VI)", SubtitleMode.VI)
        self.combo_mode.addItem("Nhật - Anh", SubtitleMode.JP_EN)
        self.combo_mode.addItem("Nhật - Việt", SubtitleMode.JP_VI)
        self.combo_mode.addItem("Anh - Việt", SubtitleMode.EN_VI)
        self.combo_mode.addItem("Full (Nhật - Anh - Việt)", SubtitleMode.JP_EN_VI)
        
        # Mặc định chọn EN_VI
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
        
        # Nút chọn màu chữ
        self.btn_font_color = QPushButton("A")
        self.btn_font_color.setFixedSize(30, 24)
        self.btn_font_color.setToolTip("Chọn màu chữ")
        self.btn_font_color.clicked.connect(lambda: self._open_color_dialog(is_bg=False))
        self._set_btn_color(self.btn_font_color, "#FFFF00") # Màu mặc định
        
        font_layout.addWidget(self.slider_size)
        font_layout.addWidget(self.btn_font_color)
        layout.addLayout(font_layout)

        layout.addWidget(self._sep())

        # --- 3. GIAO DIỆN NỀN (Opacity + Color) ---
        layout.addWidget(QLabel("Độ mờ nền & Màu nền"))
        bg_layout = QHBoxLayout()
        
        # ComboBox chọn độ mờ
        self.combo_opacity = QComboBox()
        # (Text, Giá trị float)
        self.combo_opacity.addItem("0% (Trong suốt)", 0.0)
        self.combo_opacity.addItem("25%", 0.25)
        self.combo_opacity.addItem("50% (Mặc định)", 0.5)
        self.combo_opacity.addItem("75%", 0.75)
        self.combo_opacity.addItem("100% (Đặc)", 1.0)
        
        self.combo_opacity.setCurrentIndex(2) # Chọn 50%
        self.combo_opacity.currentIndexChanged.connect(self._on_opacity_changed)
        
        # Nút chọn màu nền
        self.btn_bg_color = QPushButton("Bg")
        self.btn_bg_color.setFixedSize(30, 24)
        self.btn_bg_color.setToolTip("Chọn màu nền")
        self.btn_bg_color.clicked.connect(lambda: self._open_color_dialog(is_bg=True))
        self._set_btn_color(self.btn_bg_color, "#000000", is_bg_btn=True) # Màu mặc định đen
        
        bg_layout.addWidget(self.combo_opacity)
        bg_layout.addWidget(self.btn_bg_color)
        layout.addLayout(bg_layout)

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

        # --- 5. CHỨC NĂNG KHÁC (Lock + Reset) ---
        bottom_layout = QHBoxLayout()
        
        self.chk_lock = QCheckBox("Khóa vị trí")
        self.chk_lock.toggled.connect(self.lock_position_changed.emit)
        bottom_layout.addWidget(self.chk_lock)
        
        bottom_layout.addStretch()
        
        self.btn_reset = QPushButton("Đặt lại")
        self.btn_reset.setObjectName("btn_reset")
        self.btn_reset.setFixedSize(60, 28)
        self.btn_reset.setToolTip("Khôi phục cài đặt gốc")
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        bottom_layout.addWidget(self.btn_reset)
        
        layout.addLayout(bottom_layout)
        layout.addStretch()

    # --- LOGIC XỬ LÝ ---

    def _sep(self):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #444; max-height: 1px;")
        return line
    
    def _set_btn_color(self, btn, hex_color, is_bg_btn=False):
        """Helper đổi màu nút hiển thị"""
        text_color = "black" if not is_bg_btn else "white"
        if is_bg_btn and hex_color.upper() == "#FFFFFF": text_color = "black"
        
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

    def _open_color_dialog(self, is_bg=False):
        """
        Sửa lỗi dialog bị chìm: 
        1. Gán parent là self.
        2. Dùng DontUseNativeDialog để ép nó vẽ trong luồng Qt (nổi cùng layer với SettingsPanel).
        """
        # Tạo đối tượng dialog thay vì gọi hàm tĩnh
        dialog = QColorDialog(self)
        dialog.setWindowTitle("Chọn màu nền" if is_bg else "Chọn màu chữ")
        
        # QUAN TRỌNG: Tắt Native Dialog để tránh bị Video đè lên
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        
        # Thiết lập màu hiện tại (nếu muốn, tùy chọn)
        # dialog.setCurrentColor(QColor(...)) 

        # Hiển thị và chờ người dùng chọn
        if dialog.exec():
            color = dialog.selectedColor()
            if color.isValid():
                hex_c = color.name() # Lấy mã Hex (ví dụ #FF0000)
                
                if is_bg:
                    # Gửi tín hiệu thay đổi màu nền
                    self.bg_color_changed.emit(hex_c)
                    # Cập nhật màu nút
                    self._set_btn_color(self.btn_bg_color, hex_c, is_bg_btn=True)
                else:
                    # Gửi tín hiệu thay đổi màu chữ
                    self.font_color_changed.emit(hex_c)
                    # Cập nhật màu nút
                    self._set_btn_color(self.btn_font_color, hex_c)

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
        """Khôi phục mặc định trên UI và gửi tín hiệu"""
        # 1. Reset UI controls
        idx_en_vi = self.combo_mode.findData(SubtitleMode.EN_VI)
        self.combo_mode.setCurrentIndex(idx_en_vi)
        
        self.slider_size.setValue(24)
        self._set_btn_color(self.btn_font_color, "#FFFF00")
        
        self.combo_opacity.setCurrentIndex(2) # 50%
        self._set_btn_color(self.btn_bg_color, "#000000", is_bg_btn=True)
        
        self.chk_lock.setChecked(False)
        self.speed_btns[2].click() # Click vào nút 1.0x
        
        # 2. Gửi tín hiệu để App reset logic bên dưới
        self.reset_requested.emit()

    def sync_ui(self, config):
        """Đồng bộ UI khi load file JSON"""
        if not config: return
        
        # Sync Mode
        saved_mode_raw = config.get("mode")
        # Logic tìm Mode chuẩn trong ComboBox
        found_mode = False
        if saved_mode_raw:
            for i in range(self.combo_mode.count()):
                data = self.combo_mode.itemData(i)
                # So sánh nếu config lưu là Enum, hoặc String, hoặc Value
                if data == saved_mode_raw or str(data) == str(saved_mode_raw) or data.value == saved_mode_raw:
                    self.combo_mode.setCurrentIndex(i)
                    found_mode = True
                    break
        
        # Nếu không tìm thấy trong config, set mặc định là Full
        if not found_mode:
            idx = self.combo_mode.findData(SubtitleMode.EN_VI)
            if idx != -1: self.combo_mode.setCurrentIndex(idx)
        
        # --- 2. SYNC FONT ---
        self.slider_size.setValue(config.get("font_size", 24))
        self._set_btn_color(self.btn_font_color, config.get("font_color", "#FFFF00"))
        
        # Sync Background
        saved_op = config.get("bg_opacity", 0.5)
        # Tìm index có giá trị gần đúng nhất
        for i in range(self.combo_opacity.count()):
            if abs(self.combo_opacity.itemData(i) - saved_op) < 0.01:
                self.combo_opacity.setCurrentIndex(i)
                break
        self._set_btn_color(self.btn_bg_color, config.get("bg_color", "#000000"), is_bg_btn=True)

    def get_current_mode(self):
        """Trả về Enum SubtitleMode đang được chọn"""
        return self.combo_mode.currentData()
    
    def set_mode_visual(self, mode_enum):
        """Chỉnh ComboBox về đúng mode (dùng khi Load Settings)"""
        idx = self.combo_mode.findData(mode_enum)
        if idx != -1:
            self.combo_mode.setCurrentIndex(idx)