import sys
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QApplication
from PySide6.QtCore import Qt

class Sidebar(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # --- CẤU HÌNH GIAO DIỆN ---
        # Không set FixedWidth ở đây để MainWindow tự co giãn
        self.setFocusPolicy(Qt.NoFocus) # Bỏ viền xanh khi click
        self.setFrameShape(QListWidget.NoFrame) # Bỏ viền khung mặc định
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # Ẩn thanh cuộn
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Style Dark Mode (Giống YouTube)
        self.setStyleSheet("""
            QListWidget {
                background-color: #0f0f0f;
                outline: none;
            }
            QListWidget::item {
                color: #f1f1f1;
                height: 48px;              /* Chiều cao chuẩn nút bấm */
                border-radius: 10px;       /* Bo tròn góc */
                margin: 4px 8px;           /* Cách lề: trên-dưới 4px, trái-phải 8px */
                padding-left: 10px;        /* Khoảng cách chữ với lề trái */
                font-size: 14px;
                font-family: "Segoe UI", sans-serif;
            }
            QListWidget::item:hover {
                background-color: #272727; /* Màu nền khi di chuột */
            }
            QListWidget::item:selected {
                background-color: #272727; /* Màu nền khi đang chọn */
                font-weight: bold;         /* Chữ đậm lên */
                color: white;
            }
        """)

    def add_menu_items(self, items_list):
        """
        Nhận vào danh sách dạng ["🏠 Trang chủ", "🎶 For You"...]
        Tự động tách Icon và Text để lưu trữ.
        """
        self.clear() # Xóa danh sách cũ nếu có
        
        for full_text in items_list:
            item = QListWidgetItem(full_text)
            
            # Xử lý tách chuỗi: "🏠 Trang chủ" -> icon="🏠", text="Trang chủ"
            parts = full_text.split(' ', 1)
            
            if len(parts) > 1:
                icon_text = parts[0]
                label_text = parts[1]
            else:
                # Trường hợp không có icon hoặc không có dấu cách
                icon_text = full_text[0] if full_text else "" 
                label_text = full_text
            
            # --- LƯU DỮ LIỆU ẨN (Quan trọng) ---
            # UserRole + 1: Lưu Icon
            item.setData(Qt.UserRole + 1, icon_text) 
            # UserRole + 2: Lưu Full Text (Icon + Chữ)
            item.setData(Qt.UserRole + 2, full_text) 
            
            self.addItem(item)

    def set_mini_mode(self):
        """Chế độ thu nhỏ: Chỉ hiện Icon, Căn giữa"""
        for i in range(self.count()):
            item = self.item(i)
            # Lấy icon đã lưu ra hiển thị
            icon_only = item.data(Qt.UserRole + 1)
            item.setText(icon_only)
            # Căn giữa icon trong ô
            item.setTextAlignment(Qt.AlignCenter)

    def set_full_mode(self):
        """Chế độ mở rộng: Hiện đầy đủ, Căn trái"""
        for i in range(self.count()):
            item = self.item(i)
            # Lấy full text đã lưu ra hiển thị
            full_text = item.data(Qt.UserRole + 2)
            item.setText(full_text)
            # Căn lề trái + Căn giữa theo chiều dọc
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

