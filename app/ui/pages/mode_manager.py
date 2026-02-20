from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QGridLayout
from PySide6.QtCore import Qt

class BaseVideoPage(QWidget):
    """Lớp cơ sở cung cấp cấu trúc Grid và Scroll cho MainWindow"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0) # Sát lề cho đẹp

        self.scroll_area = QScrollArea() # Đặt tên trùng với MainWindow để dễ trỏ
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container) # Đây là nơi MainWindow sẽ vẽ video vào
        self.grid_layout.setSpacing(15)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.scroll_area.setWidget(self.grid_container)
        self.layout.addWidget(self.scroll_area)

class HomePage(BaseVideoPage):
    """Trang chủ - Chỉ là cái vỏ chứa Grid"""
    pass

class LibraryPage(BaseVideoPage):
    """Thư viện - Chỉ là cái vỏ chứa Grid"""
    pass