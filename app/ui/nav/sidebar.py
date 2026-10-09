import sys
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QApplication, QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QIcon
from ..icons import icon
from ..design_system import SIDEBAR_STYLE


class NavigationDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if not self.parent()._compact:
            return super().paint(painter, option, index)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        # PySide exposes this property by reference. Clearing it also clears a
        # borrowed wrapper; take a value copy before painting the background.
        decoration = QIcon(styled.icon)
        styled.icon = QIcon()
        styled.text = ""
        widget = styled.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, widget)
        side = 20
        rect = QRect(option.rect.center().x() - side // 2, option.rect.center().y() - side // 2, side, side)
        mode = QIcon.Mode.Selected if option.state & QStyle.StateFlag.State_Selected else QIcon.Mode.Normal
        decoration.paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode)

class Sidebar(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._compact = False
        self.setIconSize(QSize(20, 20))
        self.setItemDelegate(NavigationDelegate(self))
        
        # --- CẤU HÌNH GIAO DIỆN ---
        # Không set FixedWidth ở đây để MainWindow tự co giãn
        self.setFocusPolicy(Qt.NoFocus) # Bỏ viền xanh khi click
        self.setFrameShape(QListWidget.NoFrame) # Bỏ viền khung mặc định
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # Ẩn thanh cuộn
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Style Dark Mode (Giống YouTube)
        self.setStyleSheet(SIDEBAR_STYLE)

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
            # Preserve the legacy role values; use a separate visual label.
            names = {"🏠": "house", "🎶": "music", "📚": "library", "💾": "download", "⚙️": "settings"}
            visual_label = label_text if icon_text in names else full_text
            item.setData(Qt.UserRole + 3, visual_label)
            item.setIcon(icon(names.get(icon_text, "music")))
            item.setText("" if self._compact else visual_label)
            item.setToolTip(visual_label)
            
            self.addItem(item)

    def set_mini_mode(self):
        """Chế độ thu nhỏ: Chỉ hiện Icon, Căn giữa"""
        self._compact = True
        for i in range(self.count()):
            item = self.item(i)
            # Lấy icon đã lưu ra hiển thị
            icon_only = item.data(Qt.UserRole + 1)
            item.setText("")
            # Căn giữa icon trong ô
            item.setTextAlignment(Qt.AlignCenter)

    def set_full_mode(self):
        """Chế độ mở rộng: Hiện đầy đủ, Căn trái"""
        self._compact = False
        for i in range(self.count()):
            item = self.item(i)
            # Lấy full text đã lưu ra hiển thị
            full_text = item.data(Qt.UserRole + 2)
            item.setText(item.data(Qt.UserRole + 3))
            # Căn lề trái + Căn giữa theo chiều dọc
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

