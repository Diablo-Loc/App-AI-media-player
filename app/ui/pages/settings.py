from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QLineEdit, QPushButton, QScrollArea, QMessageBox)
from PySide6.QtCore import Qt, QSettings,Signal
from PySide6.QtGui import QFont

class SettingsPage(QWidget):
    settings_changed = Signal(dict)  # Tín hiệu phát ra khi cài đặt thay đổi, gửi dict mới
    def __init__(self):
        super().__init__()
        self.settings = QSettings("MyStudio", "AI_Music_Player")
        self.init_ui()
        self.load_settings()
        
    def init_ui(self):
        # Layout chính có ScrollArea vì setting có thể dài
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        container = QWidget()
        self.content_layout = QVBoxLayout(container)
        self.content_layout.setSpacing(25)
        
        # --- PHẦN 1: AI LOCAL (WHISPER) ---
        self.add_section_title("🤖 Local AI Model (Speech-to-Text)")
        
        self.combo_model = QComboBox()
        self.combo_model.addItems(["tiny", "base", "small", "medium", "large-v2", "large-v3"])
        self.add_setting_row("Whisper Model:", self.combo_model, "Chọn độ chính xác (Càng lớn càng chậm nhưng chuẩn)")

        self.combo_device = QComboBox()
        self.combo_device.addItems(["cuda", "cpu"])
        self.add_setting_row("Compute Device:", self.combo_device, "Sử dụng GPU (NVIDIA) để dịch nhanh hơn")
        
        # --- PHẦN 2: ONLINE AI (TRANSLATION & API) ---
        self.add_section_title("🌐 Cloud AI Services (Translation)")
        
        self.combo_online_ai = QComboBox()
        self.combo_online_ai.addItems(["Local Default", "OpenAI (GPT-4o)", "Google Gemini", "Claude 3.5"])
        self.add_setting_row("Dịch bằng AI:", self.combo_online_ai, "Chọn AI xử lý lời dịch bài hát")

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Nhập API Key tại đây...")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.add_setting_row("API Key:", self.api_key_input, "Mã code để sử dụng dịch vụ AI Cloud")
        
        help_lbl = QLabel('Lấy key tại: <a href="https://platform.openai.com/" style="color: #00f7ff;">OpenAI Dashboard</a>')
        help_lbl.setOpenExternalLinks(True)
        help_lbl.setStyleSheet("color: #666; font-size: 10px; margin-left: 130px; margin-top: -15px;")
        self.content_layout.addWidget(help_lbl)
        
        self.combo_genius_mode = QComboBox()
        self.combo_genius_mode.addItems(["Tắt (Nhanh)", "Bật (Chính xác cao)"])
        self.add_setting_row("Chế độ Genius:", self.combo_genius_mode, "Bật để AI tìm lời gốc trên mạng trước khi dịch")

        # THÊM MỚI: GENIUS API KEY
        self.genius_key_input = QLineEdit()
        self.genius_key_input.setPlaceholderText("Nhập Genius Access Token...")
        self.genius_key_input.setEchoMode(QLineEdit.Password)
        self.add_setting_row("Genius Key:", self.genius_key_input, "Dùng để đối soát lời bài hát gốc (Max Accuracy)")
        
        genius_help = QLabel('Lấy token tại: <a href="https://genius.com/api-clients" style="color: #00f7ff;">Genius API</a>')
        genius_help.setOpenExternalLinks(True)
        genius_help.setStyleSheet("color: #666; font-size: 10px; margin-left: 130px; margin-top: -15px;")
        self.content_layout.addWidget(genius_help)
              
        # --- PHẦN 3: HỆ THỐNG ---
        self.add_section_title("⚙️ System")
        
        btn_layout = QHBoxLayout()
        self.btn_reset = QPushButton("Reset về mặc định")
        self.btn_reset.setFixedWidth(150)
        self.btn_reset.clicked.connect(self.reset_to_defaults)
        
        self.btn_save = QPushButton("LƯU CÀI ĐẶT")
        self.btn_save.setFixedWidth(150)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #00f7ff; color: black; font-weight: bold; border-radius: 5px; padding: 10px;
            }
            QPushButton:hover { background-color: #00b8bd; }
        """)
        self.btn_save.clicked.connect(self.save_settings)

        btn_layout.addWidget(self.btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        self.content_layout.addLayout(btn_layout)
        
        self.content_layout.addStretch()
        
        scroll.setWidget(container)
        main_layout.addWidget(scroll)
        
        self.setStyleSheet(self.get_qss())

    def add_section_title(self, title):
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #00f7ff; font-size: 16px; font-weight: bold; margin-top: 10px;")
        self.content_layout.addWidget(lbl)

    def add_setting_row(self, label_text, widget, help_text):
        row = QVBoxLayout()
        h_layout = QHBoxLayout()
        
        lbl = QLabel(label_text)
        lbl.setFixedWidth(120)
        lbl.setStyleSheet("color: white; font-weight: bold;")
        
        widget.setMinimumHeight(30)
        widget.setStyleSheet("background: #1a1a1a; color: white; border: 1px solid #333; padding: 5px;")
        
        h_layout.addWidget(lbl)
        h_layout.addWidget(widget)
        
        help_lbl = QLabel(help_text)
        help_lbl.setStyleSheet("color: #666; font-size: 10px; margin-left: 125px;")
        
        row.addLayout(h_layout)
        row.addWidget(help_lbl)
        self.content_layout.addLayout(row)

    # --- LOGIC LƯU TRỮ ---
    def save_settings(self):
        new_config = {
            "ai_model": self.combo_model.currentText(),
            "device": self.combo_device.currentText(),
            "online_provider": self.combo_online_ai.currentText(),
            "api_key": self.api_key_input.text(),
            "use_genius": self.combo_genius_mode.currentText(),
            "genius_key": self.genius_key_input.text()
        }
        
        for key, value in new_config.items():
            self.settings.setValue(key, value)
            
        # 🔥 HIỆN CỬA SỔ BÁO THÀNH CÔNG
        msg = QMessageBox(self)
        msg.setWindowTitle("Thông báo")
        msg.setText("✅ Đã lưu cấu hình thành công!")
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Ok)
        # Tùy chỉnh màu chữ cho hộp thoại vì app đang dùng nền tối
        msg.setStyleSheet("QLabel{ color: white; } QPushButton{ width: 80px; }")
        msg.exec()
        
    def load_settings(self):
        self.combo_model.setCurrentText(self.settings.value("ai_model", "base"))
        self.combo_device.setCurrentText(self.settings.value("device", "cpu"))
        self.combo_online_ai.setCurrentText(self.settings.value("online_provider", "Local Default"))
        self.api_key_input.setText(self.settings.value("api_key", ""))
        self.combo_genius_mode.setCurrentText(self.settings.value("use_genius", "Tắt (Nhanh)"))
        self.genius_key_input.setText(self.settings.value("genius_key", ""))

    def reset_to_defaults(self):
        # 🔥 HIỆN CỬA SỔ XÁC NHẬN TRƯỚC KHI RESET
        confirm = QMessageBox.question(
            self, "Xác nhận", 
            "Bạn có chắc chắn muốn đưa tất cả cài đặt về mặc định không?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.combo_model.setCurrentText("base")
            self.combo_device.setCurrentText("cpu")
            self.combo_online_ai.setCurrentText("Local Default")
            self.api_key_input.clear()
            self.combo_genius_mode.setCurrentText("Tắt (Nhanh)")
            self.genius_key_input.clear()
            self.save_settings_silent()
            QMessageBox.information(self, "Hoàn tất", "🔄 Đã reset cài đặt về mặc định!")

    # Hàm phụ để lưu mà không hiện pop-up (tránh làm phiền khi Reset)
    def save_settings_silent(self):
        new_config = {
            "ai_model": self.combo_model.currentText(),
            "device": self.combo_device.currentText(),
            "online_provider": self.combo_online_ai.currentText(),
            "api_key": self.api_key_input.text(),
            "use_genius": self.combo_genius_mode.currentText(),
            "genius_key": self.genius_key_input.text()
        }
        for key, value in new_config.items():
            self.settings.setValue(key, value)
        self.settings_changed.emit(new_config)
        
    def get_qss(self):
        return """
            /* ... giữ nguyên code cũ ... */
            
            /* Style cho các hộp thoại thông báo */
            QMessageBox { background-color: #1a1a1a; }
            QMessageBox QLabel { color: white; font-size: 14px; }
            QMessageBox QPushButton { 
                background-color: #00f7ff; 
                color: black; 
                font-weight: bold; 
                min-width: 70px; 
                padding: 5px;
            }
            QMessageBox QPushButton:hover { background-color: #00b8bd; }
        """