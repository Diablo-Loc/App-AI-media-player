from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
                               QPushButton, QScrollArea, QLineEdit, QFrame, 
                               QSizePolicy)
from PySide6.QtCore import Qt, QSize, Signal, QTimer, QEvent, QRect, QPoint,QRectF
from PySide6.QtGui import QPixmap, QImage, QPainter, QPainterPath, QColor, QPen
import os
import random
from functools import lru_cache # [TỐI ƯU] Import thêm để cache ảnh

# ==========================================
# [TỐI ƯU] CACHE ẢNH THUMBNAIL
# Giúp cuộn danh sách mượt hơn, không đọc lại ổ cứng liên tục
# ==========================================
@lru_cache(maxsize=100)
def load_and_scale_image_rounded(path, w, h, radius=8):
    """
    Load ảnh, scale, crop giữa, và bo tròn góc.
    radius: Độ bo tròn (mặc định 8px)
    """
    if not path or not os.path.exists(path):
        return None
    
    # 1. Load ảnh gốc
    src_pixmap = QPixmap(path)
    if src_pixmap.isNull():
        return None

    # 2. Scale và Center Crop (Logic cũ của bác để chống bè hình)
    scaled_src = src_pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    x = (scaled_src.width() - w) // 2
    y = (scaled_src.height() - h) // 2
    cropped_src = scaled_src.copy(x, y, w, h)

    # 3. Tạo một Pixmap mới trong suốt để vẽ lên
    dest_pixmap = QPixmap(w, h)
    dest_pixmap.fill(Qt.transparent)

    # 4. Bắt đầu vẽ (QPainter)
    painter = QPainter(dest_pixmap)
    # Bật chế độ khử răng cưa cho góc tròn mịn màng
    painter.setRenderHint(QPainter.Antialiasing) 
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    # Tạo đường dẫn hình chữ nhật bo tròn
    path = QPainterPath()
    # Điều chỉnh nhẹ rect để viền không bị cắt (inset 0.5px)
    rect = QRectF(0.5, 0.5, w - 1, h - 1)
    path.addRoundedRect(rect, radius, radius)

    # Cắt khung vẽ theo hình bo tròn
    painter.setClipPath(path)
    # Vẽ ảnh đã crop vào khung
    painter.drawPixmap(0, 0, cropped_src)

    # (Tùy chọn) Vẽ thêm viền mỏng màu xám cho đẹp
    pen = QPen(QColor("#333")) # Màu viền
    pen.setWidth(1)            # Độ dày viền
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)

    painter.end()
    
    return dest_pixmap
# ==========================================
# CLASS 1: VIDEO STAGE (KHUNG ĐEN 16:9)
# ==========================================
class VideoStage(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setStyleSheet("background-color: black; border-radius: 12px;")

        self.video_width = 1920
        self.video_height = 1080

        self.video_widget = None
        self.subtitle_window = None
        
        # [TỐI ƯU] Timer để chống spam sự kiện resize
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.setInterval(20) # Delay 20ms
        self._layout_timer.timeout.connect(self.update_layout_execution)

    def set_components(self, video_widget, subtitle_window=None):
        if video_widget:
            self.video_widget = video_widget
            self.video_widget.setParent(self)
            self.video_widget.show()

        if subtitle_window:
            self.subtitle_window = subtitle_window
            self.subtitle_window.enable_render = True
            self.subtitle_window.show()

        self.update_layout()

    def update_layout(self):
        # [TỐI ƯU] Không chạy logic nặng ngay, mà kích hoạt timer
        self._layout_timer.start()

    def update_layout_execution(self):
        # Đây là hàm logic cũ của bác, được gọi khi timer đếm xong
        if not self.subtitle_window or not self.video_widget:
            return
               
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0: return 

        scale = min(w / self.video_width, h / self.video_height)
        target_w = int(self.video_width * scale)
        target_h = int(self.video_height * scale)

        local_x = (w - target_w) // 2
        local_y = (h - target_h) // 2

        self.video_widget.setGeometry(local_x, local_y, target_w, target_h)

        # Lấy tọa độ gốc của Stage
        stage_pos = self.mapToGlobal(QPoint(0, 0))
        
        # Tính toán tọa độ thực tế của Video trên màn hình
        v_global_x = stage_pos.x() + local_x
        v_global_y = stage_pos.y() + local_y
        v_bottom_global = v_global_y + target_h

        self.subtitle_window.adjustSize()
        sub_h = self.subtitle_window.height()
                
        bottom_margin = 10 
        target_sub_y = v_bottom_global - sub_h - bottom_margin
        
        anchor_rect = QRect(v_global_x, target_sub_y, target_w, sub_h)
        
        if hasattr(self.subtitle_window, 'set_bottom_margin'):
            self.subtitle_window.set_bottom_margin(0)
            
        if not self.subtitle_window.parent():
            # Nếu không có cha (Window riêng), dùng tọa độ Global
            self.subtitle_window.setGeometry(anchor_rect)
        else:
            # Nếu có cha, dùng set_anchor_rect để nó tự tính theo Local
            self.subtitle_window.set_anchor_rect(anchor_rect)
            
        # Thêm dòng này để chắc chắn nó không bị thằng nào đè
        self.subtitle_window.raise_()
                
    def resizeEvent(self, event):
        self.update_layout() # Gọi qua timer
        super().resizeEvent(event)

    def moveEvent(self, event):
        self.update_layout() # Gọi qua timer
        super().moveEvent(event)
                
# ==========================================
# CLASS 2: TRANG CHÍNH (FOR YOU PAGE)
# ==========================================
class ForYouPage(QWidget):
    playlist_item_clicked = Signal(object) 
    shuffle_req_signal = Signal()
    shuffle_toggled = Signal(bool)
    repeat_toggled = Signal(bool)
    
    # [TỐI ƯU] Định nghĩa Style tĩnh để tránh khởi tạo lại string nhiều lần
    CARD_STYLE_NORMAL = """
        QPushButton { background-color: transparent; border: none; border-radius: 8px; text-align: left; }
        QPushButton:hover { background-color: #333; }
    """
    CARD_STYLE_ACTIVE = """
        QPushButton { 
            background-color: #1a1a1a; 
            border-left: 4px solid #3ea6ff; 
            border-radius: 4px; 
            text-align: left; 
        }
    """
    
    def __init__(self):
        super().__init__()
        # --- QUẢN LÝ DỮ LIỆU LAZY LOAD ---
        self.all_items_data = []    
        self.original_data = []
        self.cards_map = {} 
        self.current_playing_id = None 
        self.loaded_count = 0     
        self.batch_size = 20      
        self.is_loading = False   
        self.is_shuffle = False
        self.is_repeat = False
        self._prev_window_state = None
        self.init_ui()
        
        self.playlist_scroll.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)

    def init_ui(self):
        # --- 1. SETUP LAYOUT CHÍNH ---
        self.page_layout = QVBoxLayout(self)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        self.page_layout.setSpacing(0)

        # --- 2. HEADER ---
        self.header_container = QWidget()
        self.header_container.setFixedHeight(60)
        self.header_container.setStyleSheet("background-color: #0f0f0f; border-bottom: 1px solid #222;")
        
        header_layout = QHBoxLayout(self.header_container)
        header_layout.setContentsMargins(15, 0, 20, 0)
        
        lbl_logo = QLabel("▶ FOR YOU")
        lbl_logo.setStyleSheet("color: white; font-weight: bold; font-size: 16px;")
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Tìm kiếm bài hát, ca sĩ...")
        self.search_input.setFixedSize(500, 40)
        self.search_input.setStyleSheet("""
            QLineEdit { 
                background-color: #121212; color: #efefef; 
                border: 1px solid #333; border-radius: 20px; 
                padding: 0px 15px; font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #1c62b9; }
        """)
        
        header_layout.addWidget(lbl_logo)
        header_layout.addStretch()
        header_layout.addWidget(self.search_input)
        header_layout.addStretch()
        
        lbl_avatar = QLabel("👤")
        lbl_avatar.setFixedSize(30, 30)
        lbl_avatar.setAlignment(Qt.AlignCenter)
        lbl_avatar.setStyleSheet("background: #333; border-radius: 15px; color: white;")
        header_layout.addWidget(lbl_avatar)
        
        self.page_layout.addWidget(self.header_container)

        # --- 3. BODY CONTAINER ---
        self.body_container = QWidget()
        self.body_container.setStyleSheet("background-color: #000000;")
        self.main_layout = QHBoxLayout(self.body_container)
        self.main_layout.setContentsMargins(16, 8, 16, 8)
        self.main_layout.setSpacing(24) 

        # CỘT TRÁI
        self.left_scroll_area = QScrollArea()
        self.left_scroll_area.setWidgetResizable(True)
        self.left_scroll_area.setFrameShape(QFrame.NoFrame)
        self.left_scroll_area.setStyleSheet("background: transparent;")
        
        self.left_content_widget = QWidget()
        self.left_column_layout = QVBoxLayout(self.left_content_widget)
        self.left_column_layout.setContentsMargins(0, 0, 0, 0)
        self.left_column_layout.setSpacing(15)

        self.video_container = VideoStage() 
        self.video_container.anchor_bottom = True
        
        self.info_container = QWidget()
        self.info_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        info_layout = QVBoxLayout(self.info_container)
        info_layout.setContentsMargins(0, 5, 0, 20)
        info_layout.setSpacing(5)
        
        self.title_label = QLabel("Đang chờ bài hát...")
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: white;")
        self.title_label.setWordWrap(True)
        
        self.artist_label = QLabel("--")
        self.artist_label.setStyleSheet("font-size: 15px; color: #aaa;")
        
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.artist_label)

        self.left_column_layout.addWidget(self.video_container, 1)
        self.left_column_layout.addWidget(self.info_container, 0)
        self.left_column_layout.addStretch()

        self.left_scroll_area.setWidget(self.left_content_widget)

        # CỘT PHẢI
        self.playlist_container = QFrame()
        self.playlist_container.setFixedWidth(400)
        self.playlist_container.setStyleSheet("QFrame { background-color: #0f0f0f; border: 1px solid #2a2a2a; border-radius: 12px; }")
        
        pl_layout = QVBoxLayout(self.playlist_container)
        pl_layout.setContentsMargins(0, 0, 0, 0)
        pl_layout.setSpacing(0)

        pl_header = QWidget()
        pl_header.setFixedHeight(110)
        pl_header.setStyleSheet("border-bottom: 1px solid #222; background: transparent; border-radius: 0px;")
        
        pl_header_layout = QVBoxLayout(pl_header)
        pl_header_layout.setContentsMargins(15, 15, 15, 10)
        
        row1 = QHBoxLayout()
        lbl_pl_title = QLabel("Danh sách phát")
        lbl_pl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: white; border: none;")
        self.lbl_count = QLabel("0/0")
        self.lbl_count.setStyleSheet("color: #aaa; font-size: 12px; border: none;")
        
        row1.addWidget(lbl_pl_title)
        row1.addStretch()
        row1.addWidget(self.lbl_count)
        
        row2 = QHBoxLayout()
        self.btn_repeat = QPushButton("🔁")
        self.btn_shuffle = QPushButton("🔀")
        
        for btn in [self.btn_repeat, self.btn_shuffle]:
            btn.setFixedSize(40, 40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton { font-size: 20px; color: white; border: none; background: transparent; } 
                QPushButton:hover { background: #333; border-radius: 20px; }
            """)
            
        self.btn_shuffle.clicked.connect(self.toggle_shuffle)
        self.btn_repeat.clicked.connect(self.toggle_repeat)
        
        row2.addWidget(self.btn_repeat)
        row2.addWidget(self.btn_shuffle)
        row2.addStretch()
        
        pl_header_layout.addLayout(row1)
        pl_header_layout.addLayout(row2)
        
        self.playlist_scroll = QScrollArea()
        self.playlist_scroll.setWidgetResizable(True)
        self.playlist_scroll.setStyleSheet("border: none; background: transparent;")
        
        self.playlist_items_widget = QWidget()
        self.playlist_items_widget.setStyleSheet("background: transparent;")
        self.playlist_items_layout = QVBoxLayout(self.playlist_items_widget)
        self.playlist_items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.playlist_items_layout.setContentsMargins(10, 10, 10, 10)
        self.playlist_items_layout.setSpacing(5)
        
        self.playlist_scroll.setWidget(self.playlist_items_widget)

        pl_layout.addWidget(pl_header)
        pl_layout.addWidget(self.playlist_scroll)

        self.main_layout.addWidget(self.left_scroll_area)
        self.main_layout.addWidget(self.playlist_container)
        self.page_layout.addWidget(self.body_container)

        scrollbar_style = """
            QScrollBar:vertical { border: none; background: #0f0f0f; width: 10px; margin: 0px; }
            QScrollBar::handle:vertical { background: #444; min-height: 30px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #666; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
        """
        self.left_scroll_area.verticalScrollBar().setStyleSheet(scrollbar_style)
        self.playlist_scroll.verticalScrollBar().setStyleSheet(scrollbar_style)
        
        self.search_input.textChanged.connect(self.filter_playlist)
        
    # ==========================================
    # LOGIC XỬ LÝ (LAZY LOAD, UPDATE UI)
    # ==========================================

    def refresh_playlist_ui(self):
        self.loaded_count = 0
        self.is_loading = False
        
        # [TỐI ƯU] Xóa widget an toàn hơn
        while self.playlist_items_layout.count():
            item = self.playlist_items_layout.takeAt(0)
            if item.widget(): 
                item.widget().deleteLater()
                
        self.cards_map = {}    
        
        if self.current_playing_id:
             # Load đợt đầu tiên trước
            self.load_next_batch()
            # Sau đó highlight và tính số
            self.mark_playing_item(self.current_playing_id)
        else:
            self.update_playing_status(0, len(self.all_items_data))
            self.load_next_batch()
        
    def on_scroll_changed(self, value):
        if self.is_loading: return
        scrollbar = self.playlist_scroll.verticalScrollBar()
        # [TỐI ƯU] Thêm kiểm tra > 0 để tránh load khi danh sách rỗng
        if scrollbar.maximum() > 0 and value > scrollbar.maximum() * 0.9:
            self.load_next_batch()

    def create_playlist_card(self, index, title, author, thumb_path_input, item_data):
        card = QPushButton()
        card.setFixedHeight(88)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        # [TỐI ƯU] Dùng biến tĩnh
        card.setStyleSheet(self.CARD_STYLE_NORMAL)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(8,4,8,4)
        
        # 1. Index
        lbl_idx = QLabel(str(index))
        lbl_idx.setStyleSheet("color:#aaa; border:none; font-size: 10px;")
        lbl_idx.setFixedWidth(24)
        
        # 2. Thumbnail
        lbl_thumb = QLabel()
        w_thumb, h_thumb = 140, 78 
        lbl_thumb.setFixedSize(w_thumb, h_thumb)
        lbl_thumb.setStyleSheet("background-color: #222; border: none;")
        lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        actual_thumb = getattr(item_data, 'thumbnail', None) or getattr(item_data, 'thumbnail_path', None)
        
        # [TỐI ƯU] Sử dụng hàm cache ảnh
        pixmap = load_and_scale_image_rounded(actual_thumb,w_thumb, h_thumb, radius=8)
        if pixmap:
            lbl_thumb.setPixmap(pixmap)
        else:
            lbl_thumb.setText("🎵")
            lbl_thumb.setAlignment(Qt.AlignCenter)
            lbl_thumb.setStyleSheet("background-color: #282828; color: #555; border-radius: 8px; border: 1px solid #333;")
            
        # 3. Info
        info = QVBoxLayout()
        info.setSpacing(2)
        info.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        t = QLabel(title)
        t.setProperty("is_title", True)
        t.setStyleSheet("color:white; font-weight:bold; border:none; font-size: 13px;")
        t.setWordWrap(True)               # 1. Cho phép xuống dòng
        t.setAlignment(Qt.AlignTop | Qt.AlignLeft) # 2. Căn lên trên cùng bên trái
        t.setMaximumHeight(38)            # 3. Chiều cao tối đa (tương đương 2 dòng)
        
        t.setToolTip(title)
        
        a = QLabel(author)
        a.setStyleSheet("color:#aaa; font-size: 12px; border:none; margin-top: 4px;")
        info.addWidget(t); info.addWidget(a)
        
        layout.addWidget(lbl_idx)
        layout.addWidget(lbl_thumb)
        layout.addSpacing(10)
        layout.addLayout(info)
        layout.addStretch()
        
        if item_data:
            card.clicked.connect(lambda: self.playlist_item_clicked.emit(item_data))
            
        return card

    def setup_content(self, video_widget, subtitle_window=None):
        self.video_container.set_components(video_widget, subtitle_window)

    def update_art(self, media_item):
        self.title_label.setText(media_item.title)
        self.artist_label.setText(getattr(media_item, "artist", "Unknown"))
    
    def update_playing_status(self, current_index, total_count):
        self.lbl_count.setText(f"Bài hát - {current_index}/{total_count}")

    def toggle_shuffle(self):
        # Khi bấm nút trên màn hình -> Gửi tín hiệu về MainWindow xử lý
        self.shuffle_req_signal.emit()
    
    def set_shuffle_visual(self, is_active):
        """
        Hàm này để MainWindow gọi xuống.
        Nhiệm vụ: Đổi màu nút và cập nhật biến cờ.
        """
        self.is_shuffle = is_active
        if self.is_shuffle:
            self.btn_shuffle.setStyleSheet("QPushButton { font-size: 20px; color: #3ea6ff; border: none; background: #222; border-radius: 20px; }")
        else:
            self.btn_shuffle.setStyleSheet("QPushButton { font-size: 20px; color: white; border: none; } QPushButton:hover { background: #333; border-radius: 20px; }")
    
    def get_shuffled_list(self):
        """Helper: Trả về danh sách đã trộn để MainWindow dùng"""
        if not self.original_data: return []
        
        # Logic trộn bài nằm ở đây (hoặc đưa ra MainWindow cũng được)
        shuffled = list(self.original_data)
        import random
        random.shuffle(shuffled)
        
        # (Mẹo) Đưa bài đang hát lên đầu
        if self.current_playing_id:
             for i, item in enumerate(shuffled):
                 if item.id == self.current_playing_id:
                     shuffled.pop(i)
                     shuffled.insert(0, item)
                     break
        return shuffled
    
    def toggle_repeat(self):
        self.is_repeat = not self.is_repeat
        if self.is_repeat:
            self.btn_repeat.setStyleSheet("QPushButton { font-size: 18px; color: #3ea6ff; border: none; background: #222; border-radius: 17px; }")
        else:
            self.btn_repeat.setStyleSheet("QPushButton { font-size: 18px; color: white; border: none; } QPushButton:hover { background: #333; border-radius: 17px; }")
        self.repeat_toggled.emit(self.is_repeat)

    def load_playlist(self, playlist_data):
        if not playlist_data: return
        self.original_data = list(playlist_data) 
        self.all_items_data = list(playlist_data)
        self.refresh_playlist_ui()
        
    def load_next_batch(self):
        if self.loaded_count >= len(self.all_items_data): return
        self.is_loading = True
        
        end_idx = min(self.loaded_count + self.batch_size, len(self.all_items_data))
        for i in range(self.loaded_count, end_idx):
            item = self.all_items_data[i]
            card = self.create_playlist_card(i + 1, item.title, getattr(item, 'artist', 'Unknown'), None, item)
            self.cards_map[item.id] = card
            
            if self.current_playing_id == item.id:
                self.set_card_active_style(card)
                
            self.playlist_items_layout.addWidget(card)
            
        self.loaded_count = end_idx
        self.is_loading = False
    
    def filter_playlist(self, text):
        search_text = text.lower().strip()
        if not search_text:
            if not self.is_shuffle:
                self.all_items_data = list(self.original_data)
        else:
            self.all_items_data = [
                item for item in self.original_data 
                if search_text in item.title.lower() or search_text in getattr(item, 'artist', '').lower()
            ]
        self.refresh_playlist_ui()
    
    def set_card_active_style(self, card):
        card.setStyleSheet(self.CARD_STYLE_ACTIVE)
        for label in card.findChildren(QLabel):
            if label.property("is_title"):
                label.setStyleSheet("color: #3ea6ff; font-weight: bold; font-size: 13px; border: none;")

    def set_card_normal_style(self, card):
        card.setStyleSheet(self.CARD_STYLE_NORMAL)
        for label in card.findChildren(QLabel):
            if label.property("is_title"):
                label.setStyleSheet("color: #efefef; font-weight: 600; font-size: 13px; border: none;")
    
    def mark_playing_item(self, media_id):
        # 1. Xử lý Style thẻ cũ (giữ nguyên)
        if self.current_playing_id in self.cards_map:
            try:
                self.set_card_normal_style(self.cards_map[self.current_playing_id])
            except RuntimeError:
                pass 

        self.current_playing_id = media_id

        # 2. Highlight thẻ mới (giữ nguyên)
        if media_id in self.cards_map:
            active_card = self.cards_map[media_id]
            self.set_card_active_style(active_card)
            self.playlist_scroll.ensureWidgetVisible(active_card)

        # --- [MỚI] TÍNH TOÁN SỐ THỨ TỰ ĐỂ CẬP NHẬT LABEL 0/0 ---
        current_index = -1
        # Duyệt qua danh sách hiện tại (đã shuffle hoặc filter) để tìm vị trí
        for idx, item in enumerate(self.all_items_data):
            if item.id == media_id:
                current_index = idx + 1 # +1 vì đếm từ 1
                break
        
        total = len(self.all_items_data)
        
        # Nếu tìm thấy bài thì hiện "5/100", không thấy thì hiện "0/100"
        display_idx = current_index if current_index != -1 else 0
        self.update_playing_status(display_idx, total)
        # -------------------------------------------------------
    
    def showEvent(self, event):
        super().showEvent(event)

        win = self.window()
        if not win:
            return

        # 1. Lưu trạng thái cũ (Giữ nguyên code của bạn)
        if self._prev_window_state is None:
            if win.isFullScreen():
                self._prev_window_state = "fullscreen"
            elif win.isMaximized():
                self._prev_window_state = "max"
            else:
                self._prev_window_state = "normal"

        # 2. Phóng to màn hình
        if not win.isFullScreen():
            win.showMaximized()

    def hideEvent(self, event):
        super().hideEvent(event)

        win = self.window()
        if not win or self._prev_window_state is None:
            return

        if self._prev_window_state == "normal":
            win.showNormal()
        elif self._prev_window_state == "max":
            win.showMaximized()
        elif self._prev_window_state == "fullscreen":
            win.showFullScreen()

        self._prev_window_state = None