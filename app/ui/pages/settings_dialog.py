from PySide6.QtWidgets import (QVBoxLayout, QFormLayout, QComboBox, 
                             QCheckBox, QPushButton, QHBoxLayout, QLabel, QFrame)
from PySide6.QtCore import Qt, Signal # Thêm Signal ở đây

class SettingMenu(QFrame):
    # Tạo tín hiệu để báo ra ngoài khi lưu xong
    settings_saved = Signal(str) 

    def __init__(self, parent, full_settings):
        super().__init__(parent)
        # Check kỹ: full_settings phải là dict chứa cả ['appearance'] và ['download']
        self.settings = full_settings
        self.all_qualities = ["Extreme (320k)", "High (Opus)", "Standard (M4A-ACC)", "Low (128k)"]
        self.init_ui()
        self.hide()

    def init_ui(self):
        # Giữ nguyên Style xịn của bác
        self.setStyleSheet("""
            QFrame {
                background-color: #1E1E1E;
                border: 2px solid #333333;
                border-radius: 15px;
            }
            QLabel { color: #B3B3B3; font-size: 13px; font-weight: bold; border: none; background: none; }
            QComboBox {
                background-color: #282828;
                color: white;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 5px;
                min-width: 150px;
            }
            QCheckBox { color: white; background: none; }
            QPushButton#btn_save {
                background-color: #1DB954;
                color: white;
                font-weight: bold;
                border-radius: 12px;
                padding: 8px 15px;
            }
            QPushButton#btn_save:hover { background-color: #1ed760; }
            QPushButton#btn_cancel {
                background-color: #333333;
                color: white;
                border-radius: 12px;
                padding: 8px 15px;
            }
            QPushButton#btn_cancel:hover { background-color: #444444; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(20)

        lbl_title = QLabel("CÀI ĐẶT TẢI XUỐNG")
        lbl_title.setStyleSheet("font-size: 18px; color: white; margin-bottom: 5px;")
        layout.addWidget(lbl_title, alignment=Qt.AlignmentFlag.AlignCenter)

        form = QFormLayout()
        form.setSpacing(15)

        # Truy cập an toàn vào nhánh ['download']
        dl_data = self.settings.get("download", {})

        # 1. combobox Định dạng TRƯỚC
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Video MP4",  "Video MKV", "Audio MP3"])
        self.format_combo.setCurrentText(dl_data.get("format", "Video MP4"))
        form.addRow("Định dạng:", self.format_combo)
        
        # 2.combobox Chất lượng
        self.quality_combo = QComboBox()
        form.addRow("Chất lượng:", self.quality_combo)
        
        self.format_combo.currentTextChanged.connect(self.on_format_changed)
        
        # 3. Kích hoạt hàm lần đầu tiên để load danh sách chất lượng dựa trên định dạng đang lưu
        self.on_format_changed(self.format_combo.currentText())
        
        # Ép lại lựa chọn chất lượng đã lưu trong file JSON
        saved_quality = dl_data.get("quality", "Extreme (320k)")
        if self.quality_combo.findText(saved_quality) != -1:
            self.quality_combo.setCurrentText(saved_quality)
            
        self.res_combo = QComboBox()
        self.res_combo.addItems(["4K", "2K", "1080p", "720p"])
        self.res_combo.setCurrentText(dl_data.get("resolution", "1080p"))
        form.addRow("Độ phân giải:", self.res_combo)
        
        layout.addLayout(form)

        self.label_note = QLabel("Lưu ý: Chất lượng 'Standard (M4A-ACC)' sẽ giữ nguyên chất âm gốc-ổn định nhất cho MP4")
        self.label_note.setWordWrap(True)
        self.label_note.setStyleSheet("font-size: 11px; color: #888888; font-style: italic;")
        layout.addWidget(self.label_note)
        # 4. Checkbox (Khóa cứng luôn Bật)
        self.auto_update_cb = QCheckBox("Tự động cập nhật bộ máy (Luôn bật)")
        self.auto_update_cb.setChecked(True)       # Ép luôn tích xanh
        self.auto_update_cb.setEnabled(False)      # Vô hiệu hóa chuột (Khóa cứng không cho bấm)
        
        # (Tùy chọn) Chỉnh thêm 1 chút CSS riêng cho nó mờ đi 1 xíu để người dùng biết là bị khóa
        self.auto_update_cb.setStyleSheet("QCheckBox { color: #888888; }")
        
        layout.addWidget(self.auto_update_cb)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Đóng")
        btn_cancel.setObjectName("btn_cancel")
        btn_cancel.clicked.connect(self.hide)
        
        btn_save = QPushButton("Lưu cài đặt")
        btn_save.setObjectName("btn_save")
        btn_save.clicked.connect(self.save_settings)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def on_format_changed(self, selected_format):
        current_quality = self.quality_combo.currentText()
        
        self.quality_combo.clear()

        if selected_format == "Video MKV":
            # Nếu là MKV -> Chỉ cho phép Opus
            self.quality_combo.addItems(["High (Opus)"])
        else:
            # Nếu là MP4, MP3 -> Thêm full 4 tùy chọn
            self.quality_combo.addItems(self.all_qualities)

        if self.quality_combo.findText(current_quality) != -1:
            self.quality_combo.setCurrentText(current_quality)
            
    def save_settings(self):
        try:
            if "download" not in self.settings:
                self.settings["download"] = {}

            self.settings["download"].update({
                "quality": self.quality_combo.currentText(),
                "format": self.format_combo.currentText(),
                "resolution": self.res_combo.currentText(),
                "auto_update": self.auto_update_cb.isChecked()
            })
            
            # SỬA Ở ĐÂY: Dùng đường dẫn từ lúc khởi tạo (nếu có) hoặc biến class
            filename = getattr(self.parent(), 'settings_file', "settings.json")
            import json
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
            
            self.settings_saved.emit("✅ Đã lưu cấu hình thành công!")
            self.hide()

        except Exception as e:
            self.settings_saved.emit(f"❌ Lỗi lưu file: {str(e)}")
