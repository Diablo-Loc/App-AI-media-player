from PySide6.QtWidgets import (QWidget, QVBoxLayout, QComboBox, QSlider, 
                               QPushButton, QLabel, QColorDialog, QHBoxLayout, QCheckBox)
from PySide6.QtCore import Qt
from subtitle.mode import SubtitleMode

class SubtitleEditor(QWidget):
    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.layer = layer # Giữ tham chiếu đến SubtitleLayer để điều khiển
        self._current_color = "#ffff00" # Màu mặc định
        self._outline_color = "#000000"
        
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
        layout.setSpacing(12)

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
        
        # --- 4. TÙY CHỈNH VIỀN (OUTLINE) ---
        layout.addWidget(QLabel("<b>Tùy chỉnh Viền (Outline):</b>"))
        out_layout = QHBoxLayout()
        self.out_check = QCheckBox("Bật")
        self.out_check.setChecked(True)
        self.out_check.stateChanged.connect(self._update_style)
        
        self.out_width_slider = QSlider(Qt.Orientation.Horizontal)
        self.out_width_slider.setRange(0, 15)
        self.out_width_slider.setValue(4)
        self.out_width_slider.valueChanged.connect(self._update_style)
        
        self.out_color_btn = QPushButton("Màu viền")
        self.out_color_btn.setFixedWidth(80)
        self._update_button_style(self.out_color_btn, self._outline_color)
        self.out_color_btn.clicked.connect(self._pick_outline_color)
        
        out_layout.addWidget(self.out_check)
        out_layout.addWidget(QLabel("Dày:"))
        out_layout.addWidget(self.out_width_slider)
        out_layout.addWidget(self.out_color_btn)
        layout.addLayout(out_layout)

        # --- 5. TÙY CHỈNH BÓNG (SHADOW) ---
        layout.addWidget(QLabel("<b>Tùy chỉnh Bóng (Shadow):</b>"))
        sha_layout = QHBoxLayout()
        self.sha_check = QCheckBox("Bật")
        self.sha_check.setChecked(True)
        self.sha_check.stateChanged.connect(self._update_style)
        
        self.sha_blur_slider = QSlider(Qt.Orientation.Horizontal)
        self.sha_blur_slider.setRange(0, 255)
        self.sha_blur_slider.setValue(160)
        self.sha_blur_slider.valueChanged.connect(self._update_style)
        
        sha_layout.addWidget(self.sha_check)
        sha_layout.addWidget(QLabel("Độ đậm:"))
        sha_layout.addWidget(self.sha_blur_slider)
        layout.addLayout(sha_layout)
        
        layout.addStretch()

    # --- HÀM TIỆN ÍCH ---
    def _update_button_style(self, btn, color):
        # Tự động chọn màu chữ trắng hoặc đen dựa trên màu nền để dễ đọc
        btn.setStyleSheet(f"background-color: {color}; border: 1px solid #555; padding: 4px; border-radius: 4px;")
        
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
    
    def _pick_main_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self._current_color = color.name()
            self._update_style()

    def _pick_outline_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self._outline_color = color.name()
            self._update_style()

    def _on_mode_changed(self, index):
        if self.layer: self.layer.set_mode(self.mode_map.get(index))

    def _update_style(self):
        size = self.size_slider.value()
        self.size_label.setText(f"{size}px")
        if self.layer:
            self.layer.apply_style(
                font_size=size,
                color=self._current_color,
                outline_enabled=self.out_check.isChecked(),
                outline_width=self.out_width_slider.value(),
                outline_color=self._outline_color,
                shadow_enabled=self.sha_check.isChecked(),
                shadow_alpha=self.sha_blur_slider.value()
            )
       
    def sync_ui(self, profile_data):
        if not profile_data or not self.layer: return
        
        # Chặn tín hiệu toàn bộ widget trong lúc nạp để tránh lag/vòng lặp
        self.blockSignals(True) 

        # --- LOGIC CŨ (GIỮ NGUYÊN) ---
        # 1. Update Mode
        target_mode = profile_data.get("mode")
        for index, mode_enum in self.mode_map.items():
            if mode_enum.value == target_mode:
                self.mode_box.setCurrentIndex(index)
                break

        # 2. Update Font Size
        new_size = profile_data.get("font_size", 24)
        self.size_slider.setValue(new_size)
        self.size_label.setText(f"{new_size}px")

        # 3. Update Màu chính
        self._current_color = profile_data.get("color", "#ffff00")
        self._update_button_style(self.color_btn, self._current_color)

        # --- PHẦN THÊM MỚI (CHỈ LÀ MỞ RỘNG) ---
        # 4. Update Outline (Viền)
        self.out_check.setChecked(profile_data.get("outline_enabled", True))
        self.out_width_slider.setValue(profile_data.get("outline_width", 4))
        self._outline_color = profile_data.get("outline_color", "#000000")
        self._update_button_style(self.out_color_btn, self._outline_color)

        # 5. Update Shadow (Bóng)
        self.sha_check.setChecked(profile_data.get("shadow_enabled", True))
        self.sha_blur_slider.setValue(profile_data.get("shadow_alpha", 160))

        # Mở chặn tín hiệu
        self.blockSignals(False)

        # --- CUỐI CÙNG: ÁP DỤNG TẤT CẢ (Sử dụng hàm update_style mới của bạn) ---
        self._update_style()