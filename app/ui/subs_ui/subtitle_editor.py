from PySide6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QSlider, 
                             QPushButton, QLabel, QColorDialog, QHBoxLayout)
from PySide6.QtCore import Qt
from subtitle.mode import SubtitleMode

class SubtitleEditor(QWidget):
    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.layer = layer # Giữ tham chiếu đến SubtitleLayer để điều khiển
        self._current_color = "#ffff00" # Màu mặc định
        
        # Mapping từ index của ComboBox sang SubtitleMode Enum
        self.mode_map = {
            0: SubtitleMode.JP,
            1: SubtitleMode.EN,         
            2: SubtitleMode.VI,         
            3: SubtitleMode.JP_EN,      
            4: SubtitleMode.JP_VI,
            5: SubtitleMode.EN_VI,
            6: SubtitleMode.JP_EN_VI,
            7: SubtitleMode.OFF
        }
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # --- 1. CHỌN CHẾ ĐỘ HIỂN THỊ (MODE) ---
        layout.addWidget(QLabel("<b>Chế độ hiển thị:</b>"))
        self.mode_box = QComboBox()
        self.mode_box.addItems([
            "Chỉ Tiếng Nhật (JP)", 
            "Chỉ Tiếng Anh (EN)", 
            "Chỉ Tiếng Việt (VI)", 
            "Nhật + Anh", 
            "Nhật + Việt", 
            "Anh + Việt", 
            "Tất cả (Nhật + Anh + Việt)", 
            "Tắt phụ đề"
        ])
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_box)

        # --- 2. CHỈNH CỠ CHỮ (FONT SIZE) ---
        layout.addWidget(QLabel("<b>Cỡ chữ:</b>"))
        size_layout = QHBoxLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(14, 80)
        self.size_slider.setValue(24)
        self.size_slider.valueChanged.connect(self._update_style)
        
        self.size_label = QLabel("24px")
        size_layout.addWidget(self.size_slider)
        size_layout.addWidget(self.size_label)
        layout.addLayout(size_layout)

        # --- 3. CHỌN MÀU SẮC (COLOR PICKER) ---
        layout.addWidget(QLabel("<b>Màu sắc:</b>"))
        self.color_btn = QPushButton("Chọn màu chữ")
        self.color_btn.setStyleSheet(f"background-color: {self._current_color}; color: black; font-weight: bold; border: 1px solid gray;")
        self.color_btn.clicked.connect(self._pick_color)
        layout.addWidget(self.color_btn)

        layout.addStretch()

    # --- LOGIC XỬ LÝ ---

    def _on_mode_changed(self, index):
        if self.layer:
            self.layer.set_mode(self.mode_map.get(index))
            
    def _pick_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self._current_color = color.name()
            self.color_btn.setStyleSheet(f"background-color: {self._current_color}; color: black; font-weight: bold; border: 1px solid gray;")
            self._update_style()

    def _update_style(self):
        size = self.size_slider.value()
        self.size_label.setText(f"{size}px")
        if self.layer:
            # Gọi hàm apply_style bên Layer
            self.layer.apply_style(font_size=size, color=self._current_color)
        
    def sync_ui(self, profile_data):
        """
        Cập nhật giao diện Editor khi nạp Profile từ file JSON.
        profile_data là dictionary: {"mode": "jp_vi", "font_size": 26, "color": "#ffffff"}
        """
        if not profile_data:
            return

        # 1. Update Mode ComboBox
        target_mode = profile_data.get("mode")
        for index, mode_enum in self.mode_map.items():
            if mode_enum.value == target_mode:
                self.mode_box.blockSignals(True) # Tránh gọi ngược lại layer khi đang sync
                self.mode_box.setCurrentIndex(index)
                self.mode_box.blockSignals(False)
                break

        # 2. Update Slider
        new_size = profile_data.get("font_size", 24)
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(new_size)
        self.size_label.setText(f"{new_size}px")
        self.size_slider.blockSignals(False)

        # 3. Update Color Button
        self._current_color = profile_data.get("color", "#ffff00")
        self.color_btn.setStyleSheet(f"background-color: {self._current_color}; color: black; font-weight: bold; border: 1px solid gray;")
        if self.layer:
            self.layer.apply_style(
                font_size=new_size,
                color=self._current_color
            )
