from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSlider, QLabel
from .icons import label_icon

class VolumePopup(QWidget):
    volumeChanged = Signal(int)  # Tín hiệu gửi ra khi kéo slider

    def __init__(self, parent=None):
        super().__init__(parent)
        # Qt.Popup: Cửa sổ nổi, tự đóng khi click ra ngoài
        # FramelessWindowHint: Bỏ viền cửa sổ mặc định của Win/Mac
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) # Để bo tròn được góc

        # Layout chính
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(15, 10, 15, 10) # Căn lề trong
        
        # Container (Cái hộp màu xám bo tròn)
        self.container = QWidget()
        self.container.setObjectName("popupContainer")
        self.container_layout = QHBoxLayout(self.container)
        
        # 1. Icon nhỏ (trang trí cho giống hình)
        self.lbl_icon = QLabel()
        label_icon(self.lbl_icon, "volume-2", size=20)
        self.lbl_icon.setStyleSheet("color: #b3b3b3; font-size: 16px; border: none; background: transparent;")
        
        # 2. Slider (Code style cũ của bạn)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setFixedWidth(180) # Chiều dài thanh trượt
        
        # 3. Label hiển thị số
        self.lbl_value = QLabel("50")
        self.lbl_value.setStyleSheet("color: white; font-size: 14px; margin-left: 8px; border: none; background: transparent;")
        self.lbl_value.setFixedWidth(30)

        # Thêm vào layout
        self.container_layout.addWidget(self.lbl_icon)
        self.container_layout.addWidget(self.slider)
        self.container_layout.addWidget(self.lbl_value)
        
        self.layout.addWidget(self.container)

        # Kết nối sự kiện
        self.slider.valueChanged.connect(self.on_slider_changed)

        # --- STYLE SHEET (Copy style slider màu cam vào đây) ---
        self.setStyleSheet("""
            #popupContainer {
                background-color: #151C26;
                border: 1px solid #405267;
                border-radius: 8px; /* Bo góc popup */
            }
            QSlider::groove:horizontal {
                border: none;
                height: 4px;
                background: #4A4A4A;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #77E0BE;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #77E0BE;
                border: 4px solid #2D2D2D;
                width: 18px; 
                height: 18px;
                margin: -7px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #9AEDD3;
                border: 4px solid #3c3c3c;
            }
        """)

    def on_slider_changed(self, value):
        self.lbl_value.setText(str(value))
        self.volumeChanged.emit(value) # Bắn tín hiệu ra ngoài để Main biết

    def set_volume(self, value):
        # Cập nhật slider khi mở lên mà không bắn tín hiệu vòng lặp
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.lbl_value.setText(str(value))
        self.slider.blockSignals(False)
    
    def set_value(self, value):
        """Hàm cập nhật giao diện popup (Slider + Số) mà không bắn tín hiệu ngược lại"""
        # 1. Chặn tín hiệu (để tránh vòng lặp vô tận: set -> signal -> main -> set...)
        self.slider.blockSignals(True)
        
        # 2. Gán giá trị
        self.slider.setValue(value)
        self.lbl_value.setText(str(value))
        
        # 3. Mở lại tín hiệu để người dùng kéo thì mới nhận
        self.slider.blockSignals(False)
