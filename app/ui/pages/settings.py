from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QComboBox, QLineEdit, QPushButton, QScrollArea, QMessageBox)
from PySide6.QtCore import Qt, QSettings,Signal
from PySide6.QtGui import QFont
from ..icons import button_icon, INK
from ..design_system import FORM_STYLE

from download_core.download_source_app import ResourceDownloadDialog, check_resource_status

class SettingsPage(QWidget):
    settings_changed = Signal(dict)  # Tín hiệu phát ra khi cài đặt thay đổi, gửi dict mới
    def __init__(self):
        super().__init__()
        self.settings = QSettings("MyStudio", "AI_Music_Player")
        self.init_ui()
        self.refresh_model_list()
        self.load_settings()
        
    def init_ui(self):
        # Layout chính có ScrollArea vì setting có thể dài
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Tùy chỉnh trải nghiệm")
        title.setStyleSheet("color: #EDF3FA; font-size: 25px; font-weight: 700;")
        main_layout.addWidget(title)
        description = QLabel("Quản lý mô hình AI, dịch vụ dịch và cấu hình hệ thống.")
        description.setStyleSheet("color: #9AAABC; font-size: 13px; padding-bottom: 12px;")
        main_layout.addWidget(description)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        container = QWidget()
        container.setObjectName("settingsContent")
        container.setAttribute(Qt.WA_StyledBackground, True)
        container.setStyleSheet("QWidget#settingsContent { background: #0D1118; }")
        self.content_layout = QVBoxLayout(container)
        self.content_layout.setSpacing(25)
        
        # --- PHẦN 1: AI LOCAL (WHISPER) ---
        self.add_section_title("Mô hình AI · Nhận diện giọng nói")
        
        self.combo_model = QComboBox()
        self.add_setting_row("Whisper Model:", self.combo_model, "Chọn độ chính xác (Càng lớn càng chậm nhưng chuẩn)")

        self.combo_device = QComboBox()
        self.combo_device.addItems(["cuda", "cpu"])
        self.add_setting_row("Compute Device:", self.combo_device, "Sử dụng GPU (NVIDIA) để dịch nhanh hơn")
        
        # NÚT THÊM MỚI: KÍCH HOẠT DOWNLOAD MANAGER CÙNG CẤP APP
        btn_res_layout = QHBoxLayout()
        self.btn_download_resource = QPushButton("Tải / Cập nhật Resource AI (Thư viện & Model)")
        button_icon(self.btn_download_resource, "download", "Tải tài nguyên AI", icon_only=False)
        self.btn_download_resource.setFixedHeight(35)
        self.btn_download_resource.setCursor(Qt.PointingHandCursor)
        self.btn_download_resource.clicked.connect(self.open_download_manager)
        btn_res_layout.addWidget(self.btn_download_resource)
        self.content_layout.addLayout(btn_res_layout)

        # --- PHẦN 2: ONLINE AI (TRANSLATION & API) ---
        self.add_section_title("Dịch vụ AI · Dịch thuật")
        
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
        self.add_section_title("Hệ thống")
        
        btn_layout = QHBoxLayout()
        self.btn_reset = QPushButton("Reset về mặc định")
        self.btn_reset.setFixedWidth(150)
        self.btn_reset.clicked.connect(self.reset_to_defaults)
        
        self.btn_save = QPushButton("Lưu cài đặt")
        self.btn_save.setProperty("role", "primary")
        button_icon(self.btn_save, "save", "Lưu cài đặt", color=INK, icon_only=False)
        button_icon(self.btn_reset, "rotate-ccw", "Reset về mặc định", icon_only=False)
        self.btn_save.setFixedWidth(150)
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_settings)

        btn_layout.addWidget(self.btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        self.content_layout.addLayout(btn_layout)
        
        self.content_layout.addStretch()
        
        scroll.setWidget(container)
        main_layout.addWidget(scroll)
        
        self.setStyleSheet(self.get_qss())
        self.btn_download_resource.setStyleSheet("QPushButton { margin-left: 125px; }")

    def add_section_title(self, title):
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #A9F1D9; font-size: 16px; font-weight: 600; margin-top: 10px; padding-bottom: 8px;")
        self.content_layout.addWidget(lbl)

    def add_setting_row(self, label_text, widget, help_text):
        row = QVBoxLayout()
        h_layout = QHBoxLayout()
        
        lbl = QLabel(label_text)
        lbl.setFixedWidth(120)
        lbl.setStyleSheet("color: white; font-weight: bold;")
        
        widget.setMinimumHeight(30)
        widget.setMinimumHeight(38)
        
        h_layout.addWidget(lbl)
        h_layout.addWidget(widget)
        
        help_lbl = QLabel(help_text)
        help_lbl.setStyleSheet("color: #9AAABC; font-size: 12px; margin-left: 125px;")
        
        row.addLayout(h_layout)
        row.addWidget(help_lbl)
        self.content_layout.addLayout(row)

    def open_download_manager(self):
        if ResourceDownloadDialog is None:
            QMessageBox.critical(self, "Lỗi", "Không tìm thấy module Trình cài đặt tại đường dẫn 'app.download_core.download_source_app'")
            return
            
        # Khởi tạo giao diện tải tài nguyên
        downloader = ResourceDownloadDialog(self)
        
        # ✅ ĐỒNG BỘ CHUẨN QT: Tìm vị trí của chữ (Index) rồi ép cbo chọn vị trí đó
        idx_hardware = downloader.cbo_hardware.findText(self.combo_device.currentText())
        if idx_hardware != -1:
            downloader.cbo_hardware.setCurrentIndex(idx_hardware)
            
        idx_model = downloader.cbo_model.findText(self.combo_model.currentText())
        if idx_model != -1:
            downloader.cbo_model.setCurrentIndex(idx_model)
        
        # Mở dialog chặn (Modal)
        if downloader.exec():
            self.refresh_model_list()
            self.load_settings()


    # --- LOGIC LƯU TRỮ ---
    def save_settings(self):
        new_config = {
            "ai_model": self.combo_model.currentData(),
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
        self.settings_changed.emit(new_config)
        
    def load_settings(self):
        model = self.settings.value("ai_model", "base")
        for i in range(self.combo_model.count()):
            if self.combo_model.itemData(i) == model:
                self.combo_model.setCurrentIndex(i)
                break
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
            for i in range(self.combo_model.count()):
                if self.combo_model.itemData(i) == "base":
                    self.combo_model.setCurrentIndex(i)
                    break
            self.combo_device.setCurrentText("cpu")
            self.combo_online_ai.setCurrentText("Local Default")
            self.api_key_input.clear()
            self.combo_genius_mode.setCurrentText("Tắt (Nhanh)")
            self.genius_key_input.clear()
            if hasattr(self, 'volume_percent'):
                self.volume_percent.setValue(50)
            self.save_settings_silent()
            QMessageBox.information(self, "Hoàn tất", "🔄 Đã reset cài đặt về mặc định!")

    # Hàm phụ để lưu mà không hiện pop-up (tránh làm phiền khi Reset)
    def save_settings_silent(self):
        new_config = {
            "ai_model": self.combo_model.currentData(),
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
        return FORM_STYLE
    
    def refresh_model_list(self):
        info = check_resource_status()

        current = self.settings.value("ai_model", "base")

        self.combo_model.blockSignals(True)
        self.combo_model.clear()

        models = [
            ("tiny", "Tiny (~75MB)"),
            ("base", "Base (~140MB)"),
            ("small", "Small (~460MB)"),
            ("medium", "Medium (~1.5GB)"),
            ("large-v2", "Large-v2 (~3GB)"),
            ("large-v3", "Large-v3 (~3GB)")
        ]

        current_index = 0

        for i, (key, title) in enumerate(models):

            installed = info["whisper"].get(key, False)

            if installed:
                text = f"{title}   ✔ Đã cài"
            else:
                text = f"{title}   ⬇ Chưa cài"

            self.combo_model.addItem(text, key)

            if key == current:
                current_index = i

        self.combo_model.setCurrentIndex(current_index)
        self.combo_model.blockSignals(False)
