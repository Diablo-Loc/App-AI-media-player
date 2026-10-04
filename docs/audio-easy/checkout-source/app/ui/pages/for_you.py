from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, 
                               QPushButton, QScrollArea, QLineEdit, QFrame, 
                               QSizePolicy,QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, Signal, QTimer, QRect, QPoint, QRectF, QThreadPool, QEvent
from PySide6.QtGui import QImage, QPixmap, QPainter, QPainterPath, QColor, QPen, QPixmapCache
from math import ceil, isclose
import os
import random
from ..icons import button_icon, label_icon, icon, ACCENT, TEXT
from ..design_system import ICON_BUTTON_STYLE
from ..elided_label import ElidedLabel
from ..playlist_thumbnail import PlaylistThumbnailLoader
from ..foryou_playlist_view import playlist_view
from ..playlist_thumbnail_queue import thumbnail_queue
from ..foryou_spacing import PAGE_GUTTER
# --------------------------------------------------
# helper widget for lazy-loading thumbnails in playlist
class LazyThumb(QLabel):
    def __init__(self, item_data, width, height, parent=None):
        super().__init__(parent)
        self.item_data = item_data
        self.setFixedSize(width, height)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background-color: #222; border: none;")
        # placeholder icon until loaded
        label_icon(self, "music", size=24)
        self.setStyleSheet(self.styleSheet() + " color: #555; font-size: 24px;")
        self._is_loaded = False
        self._build_cache_key()
        self._current_worker = None
        
    def _build_cache_key(self):
        path = getattr(self.item_data, 'thumbnail', None) or getattr(self.item_data, 'thumbnail_path', None)
        mtime = getattr(self.item_data, 'mtime', 0)
        self.cache_key = f"lazy_rounded_{path}_{self.width()}x{self.height()}_{mtime}"
        self._thumb_path = path

    def showEvent(self, event):
        super().showEvent(event)
        if not self._is_loaded and self._thumb_path:
            # Chỉ load khi thực sự hiển thị trên màn hình
            QTimer.singleShot(50, self._start_async_loading)

    def _start_async_loading(self):
        if not self.isVisible(): return
        dpr = self.devicePixelRatioF()
        if self._is_loaded and isclose(getattr(self, '_loaded_dpr', dpr), dpr): return
        self._is_loaded = False
        if self.property('playlist_visible') is False: return
        if (self._current_worker and not self._current_worker._is_cancelled
                and not self._current_worker._completed
                and isclose(self._current_worker.dpr, dpr)): return
        path = self._thumb_path
        if not path or not os.path.exists(path):
            return
        
        # 1. Kiểm tra cache: Tìm cái ĐÃ BO GÓC trước
        # Lưu ý: cache_key ở đây đã có chữ "lazy_rounded" từ hàm _build_cache_key
        target_w, target_h = ceil(self.width() * dpr), ceil(self.height() * dpr)
        cached = QPixmapCache.find(self.cache_key)
        if (cached and isclose(cached.devicePixelRatioF(), dpr)
                and cached.width() == target_w and cached.height() == target_h):
            self._apply_image(cached) # Hàm helper để apply đẹp
            return
        
        if self._current_worker:
            self._current_worker.cancel()
            
        loader = PlaylistThumbnailLoader(self.cache_key, str(path), target_w, target_h, dpr)
        loader.signals.finished.connect(self._on_loaded)
        self._current_worker = loader
        if self.property('playlist_visible') is True:
            thumbnail_queue().submit(self, loader)
        else:
            QThreadPool.globalInstance().start(loader)

    def _on_loaded(self, incoming_key, pixmap):
        try:
            if not self or incoming_key != self.cache_key or pixmap.isNull(): return
            if not self.isVisible(): return
            if self.property('playlist_visible') is False: return
            if isinstance(pixmap, QImage):
                if not isclose(pixmap.devicePixelRatioF(), self.devicePixelRatioF()): return
                pixmap = QPixmap.fromImage(pixmap)
            w = self.width()
            h = self.height()
            dpr = self.devicePixelRatioF()
            
            # 1. Tạo canvas chuẩn với dpr để không bị mờ trên màn hình cao cấp
            final_pixmap = QPixmap(ceil(w * dpr), ceil(h * dpr))
            final_pixmap.fill(Qt.transparent)
            final_pixmap.setDevicePixelRatio(dpr)
            
            painter = QPainter(final_pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            
            # 2. Tạo Path bo góc chuẩn radius 8
            path = QPainterPath()
            # Dùng RectF(0, 0, w, h) để khớp hoàn toàn với widget
            rect = QRectF(0, 0, w, h)
            path.addRoundedRect(rect, 8, 8)
            painter.setClipPath(path)
            
            # 3. LOGIC CROP GIỮA: Tính toán trực tiếp từ ảnh gốc (pixmap) 
            # Cách này chính xác hơn là scale trung gian rồi mới crop
            img_w = pixmap.width()
            img_h = pixmap.height()
            # Destination coordinates below already account for the display DPR.
            pixmap.setDevicePixelRatio(1.0)
            
            # Tính toán tỷ lệ để phủ kín khung 140x78
            scale = max(w * dpr / img_w, h * dpr / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            
            # Căn giữa ảnh trong khung
            off_x = (w * dpr - draw_w) / 2.0
            off_y = (h * dpr - draw_h) / 2.0
            
            # Vẽ trực tiếp ảnh gốc vào khung đã được set ClipPath (bo góc)
            # Tọa độ ở đây tính theo pixel thực tế (nhân dpr) vì painter đang vẽ trên final_pixmap
            painter.drawPixmap(off_x / dpr, off_y / dpr, draw_w / dpr, draw_h / dpr, pixmap)
            
            # 4. Vẽ viền mờ (Border) để thumbnail nổi bật trên nền đen
            pen = QPen(QColor(255, 255, 255, 25)) 
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawPath(path)
            
            painter.end()
            
            # Cập nhật và lưu cache
            self._apply_image(final_pixmap)
            QPixmapCache.insert(self.cache_key, final_pixmap)
        except (RuntimeError, Exception):
            pass

    def event(self, event):
        handled = super().event(event)
        if event.type() == QEvent.DevicePixelRatioChange and hasattr(self, "cache_key"):
            self._is_loaded = False
            if self._current_worker:
                self._current_worker.cancel()
            QTimer.singleShot(50, self._start_async_loading)
        return handled

    def _apply_image(self, pixmap):
        """Hàm helper để xóa placeholder và hiện ảnh"""
        self.setStyleSheet("background: transparent; border: none;")
        self.setText("") 
        self.setPixmap(pixmap)
        self._is_loaded = True
        self._loaded_dpr = self.devicePixelRatioF()
    
# --------------------------------------------------
# 1. TỐI ƯU HÀM LOAD ẢNH (Sử dụng Cache tốt hơn)
# --------------------------------------------------
def load_and_scale_image_rounded(path, w, h, radius=8):
    """
    Load ảnh, scale, crop giữa, và bo tròn góc.
    """
    if not path or not os.path.exists(path):
        return None
    
    # 0. Kiểm tra cache của Qt trước
    cache_key = f"rounded_{path}_{w}x{h}_{radius}"
    cached_pixmap = QPixmapCache.find(cache_key)
    if cached_pixmap:
        return cached_pixmap

    # 1. Load ảnh gốc
    src_pixmap = QPixmap(path)
    if src_pixmap.isNull():
        return None

    # 2. Scale và Center Crop
    scaled_src = src_pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    x = (scaled_src.width() - w) // 2
    y = (scaled_src.height() - h) // 2
    cropped_src = scaled_src.copy(x, y, w, h)

    # 3. Tạo một Pixmap mới trong suốt để vẽ lên
    dest_pixmap = QPixmap(w, h)
    dest_pixmap.fill(Qt.transparent)

    # 4. Bắt đầu vẽ (QPainter)
    painter = QPainter(dest_pixmap)
    painter.setRenderHint(QPainter.Antialiasing) 
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    path_obj = QPainterPath() # Đổi tên biến path -> path_obj để không trùng với parameter 'path'
    rect = QRectF(0.5, 0.5, w - 1, h - 1)
    path_obj.addRoundedRect(rect, radius, radius)

    painter.setClipPath(path_obj)
    painter.drawPixmap(0, 0, cropped_src)

    pen = QPen(QColor("#333")) 
    pen.setWidth(1)            
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path_obj)

    painter.end()
    
    # 5. Lưu kết quả vào QPixmapCache trước khi return
    QPixmapCache.insert(cache_key, dest_pixmap)
    
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
        # The shared video can already belong to mini/large mode while this
        # stage still has a pending resize or metadata callback.
        if self.video_widget and self.video_widget.parentWidget() is not self:
            return
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
        QPushButton:hover { background-color: #1B2431; }
    """
    CARD_STYLE_ACTIVE = """
        QPushButton { 
            background-color: #19372F;
            border-left: 4px solid #77E0BE;
            border-radius: 4px; 
            text-align: left; 
        }
    """
    
    def __init__(self):
        super().__init__()
        QPixmapCache.setCacheLimit(204800) # 200MB cache limit
        # --- QUẢN LÝ DỮ LIỆU LAZY LOAD ---
        self.master_data = []
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
        self.header_container.setFixedHeight(64)
        self.header_container.setObjectName("forYouHeader")
        self.header_container.setStyleSheet("#forYouHeader { background-color: #0D1118; border-bottom: 1px solid #273445; }")
        
        header_layout = QHBoxLayout(self.header_container)
        header_layout.setContentsMargins(PAGE_GUTTER, PAGE_GUTTER, PAGE_GUTTER, PAGE_GUTTER)
        header_layout.setSpacing(PAGE_GUTTER)
        
        lbl_logo = QLabel("For You")
        lbl_logo.setFixedWidth(96)
        lbl_logo.setStyleSheet("color: white; font-weight: bold; font-size: 16px;")
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm kiếm bài hát...")
        self.search_input.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setMinimumWidth(180)
        self.search_input.setMaximumWidth(420)
        self.search_input.setFixedHeight(40)
        self.search_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search_input.setStyleSheet("""
            QLineEdit { 
                background-color: #151C26; color: #EDF3FA;
                border: 1px solid #273445; border-radius: 10px;
                padding: 0px 15px; font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #77E0BE; }
        """)
        
        header_layout.addWidget(lbl_logo)
        header_layout.addStretch()
        header_layout.addWidget(self.search_input)
        header_layout.addStretch()
        
        lbl_avatar = QLabel()
        label_icon(lbl_avatar, "user", size=18)
        lbl_avatar.setFixedSize(30, 30)
        lbl_avatar.setAlignment(Qt.AlignCenter)
        lbl_avatar.setStyleSheet("background: #1B2431; border-radius: 15px; color: white;")
        avatar_slot = QWidget()
        avatar_slot.setFixedWidth(96)
        avatar_layout = QHBoxLayout(avatar_slot)
        avatar_layout.setContentsMargins(0, 0, 0, 0)
        avatar_layout.addWidget(lbl_avatar, alignment=Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(avatar_slot)
        
        self.page_layout.addWidget(self.header_container)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True) # Chỉ chạy 1 lần mỗi khi gọi
        self.search_timer.timeout.connect(self.execute_filter)
        
        # --- 3. BODY CONTAINER ---
        self.body_container = QWidget()
        self.body_container.setStyleSheet("background-color: #0D1118;")
        self.main_layout = QHBoxLayout(self.body_container)
        self.main_layout.setContentsMargins(PAGE_GUTTER, PAGE_GUTTER, PAGE_GUTTER, PAGE_GUTTER)
        self.main_layout.setSpacing(PAGE_GUTTER)

        # CỘT TRÁI
        self.left_scroll_area = QScrollArea()
        self.left_scroll_area.setWidgetResizable(True)
        self.left_scroll_area.setFrameShape(QFrame.NoFrame)
        self.left_scroll_area.setStyleSheet("background: transparent;")
        
        self.left_content_widget = QWidget()
        self.left_column_layout = QVBoxLayout(self.left_content_widget)
        self.left_column_layout.setContentsMargins(0, 0, 0, 0)
        self.left_column_layout.setSpacing(PAGE_GUTTER)

        self.video_container = VideoStage() 
        self.video_container.anchor_bottom = True
        
        self.info_container = QWidget()
        self.info_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        info_layout = QVBoxLayout(self.info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(5)
        
        self.title_label = QLabel("Đang chờ bài hát...")
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: white;")
        self.title_label.setWordWrap(True)
        
        self.artist_label = QLabel("--")
        self.artist_label.setStyleSheet("font-size: 15px; color: #aaa;")
        
        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.artist_label)

        self.left_column_layout.addWidget(self.video_container, 5)
        self.left_column_layout.addWidget(self.info_container, 0)
        self.left_column_layout.addStretch()

        self.left_scroll_area.setWidget(self.left_content_widget)

        # CỘT PHẢI
        self.playlist_container = QFrame()
        self.playlist_container.setFixedWidth(400)
        self.playlist_container.setObjectName("playlistPanel")
        self.playlist_container.setStyleSheet("QFrame#playlistPanel { background-color: #151C26; border: 1px solid #273445; border-radius: 12px; }")
        
        pl_layout = QVBoxLayout(self.playlist_container)
        pl_layout.setContentsMargins(0, 0, 0, 0)
        pl_layout.setSpacing(0)

        pl_header = QWidget()
        pl_header.setFixedHeight(110)
        pl_header.setStyleSheet("border-bottom: 1px solid #273445; background: transparent; border-radius: 0px;")
        
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
        self.btn_repeat = QPushButton()
        self.btn_shuffle = QPushButton()
        
        for btn in [self.btn_repeat, self.btn_shuffle]:
            btn.setFixedSize(40, 40)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_repeat.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_shuffle.setStyleSheet(ICON_BUTTON_STYLE)
        button_icon(self.btn_repeat, "repeat", "Lặp lại")
        button_icon(self.btn_shuffle, "shuffle", "Phát ngẫu nhiên")
            
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
        
        self.search_input.textChanged.connect(self.on_search_text_changed)
                
    # ==========================================
    # LOGIC XỬ LÝ (LAZY LOAD, UPDATE UI)
    # ==========================================

    def refresh_playlist_ui(self):
        return playlist_view(self).refresh()
        
    def on_scroll_changed(self, value):
        playlist_view(self).schedule()

    def create_playlist_card(self, index, title, author, thumb_path_input, item_data):
        card = QPushButton()
        card.setFixedHeight(88)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(self.CARD_STYLE_NORMAL)
        
        layout = QHBoxLayout(card)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        
        # 1. Index
        lbl_idx = QLabel(str(index))
        lbl_idx.setStyleSheet("color:#8391A3; background:transparent; border:none; font-size: 10px;")
        lbl_idx.setAlignment(Qt.AlignCenter)
        largest_index = max(index, len(self.all_items_data))
        lbl_idx.setFixedWidth(max(14, lbl_idx.fontMetrics().horizontalAdvance(str(largest_index)) + 2))
        
        # 2. Thumbnail
        w_thumb, h_thumb = 140, 78
        lbl_thumb = LazyThumb(item_data, w_thumb, h_thumb)        
        
        # 3. Info
        info = QVBoxLayout()
        info.setSpacing(4)
        info.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        t = ElidedLabel(title, max_lines=2)
        t.setProperty("is_title", True)
        t.setStyleSheet("color:white; font-weight:600; border:none; font-size: 13px;")
        t.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        t.setMaximumHeight(38)
        t.setToolTip(title)
        
        a = ElidedLabel(author)
        a.setStyleSheet("color:#A3AFBF; font-size: 12px; border:none; background:transparent;")
        info.addWidget(t)
        info.addWidget(a)
        
        layout.addWidget(lbl_idx)
        layout.addWidget(lbl_thumb)
        layout.addLayout(info, 1)
        
        if item_data:
            card._playlist_item = item_data
            card.clicked.connect(lambda _, row=card: self.playlist_item_clicked.emit(row._playlist_item))
            
        return card

    def setup_content(self, video_widget, subtitle_window=None):
        self.video_container.set_components(video_widget, subtitle_window)

    def update_art(self, media_item):
        self.title_label.setText(media_item.title)
        self.artist_label.setText(getattr(media_item, "artist", "Unknown"))
    
    def update_playing_status(self, current_index, total_count):
        self.lbl_count.setText(f"Bài hát - {current_index}/{total_count}")

    def toggle_shuffle(self):
        self.shuffle_req_signal.emit()
    
    def set_shuffle_visual(self, is_active):
        self.is_shuffle = is_active
        button_icon(self.btn_shuffle, "shuffle", color=ACCENT if self.is_shuffle else TEXT)
        self.btn_shuffle.setToolTip("Phát ngẫu nhiên: bật" if self.is_shuffle else "Phát ngẫu nhiên: tắt")
    
    def get_shuffled_list(self):
        if not self.master_data: return []
        
        shuffled = list(self.master_data)
        random.shuffle(shuffled)
        
        if self.current_playing_id:
            for i, item in enumerate(shuffled):
                if item.id == self.current_playing_id:
                    shuffled.pop(i)
                    shuffled.insert(0, item)
                    break
        return shuffled
    
    def toggle_repeat(self):
        self.is_repeat = not self.is_repeat
        button_icon(self.btn_repeat, "repeat", color=ACCENT if self.is_repeat else TEXT)
        self.btn_repeat.setToolTip("Lặp lại: bật" if self.is_repeat else "Lặp lại: tắt")
        self.repeat_toggled.emit(self.is_repeat)

    def load_playlist(self, playlist_data):
        return playlist_view(self).load(playlist_data)
        
    def load_next_batch(self):
        return playlist_view(self).render()

    def get_playback_playlist(self):
        return list(playlist_view(self).playback_order)

    def set_playback_playlist(self, playlist_data):
        return playlist_view(self).set_order(playlist_data)

    # ==========================================
    # CỬA SỔ TÌM KIẾM ĐÃ ĐƯỢC CHỈNH SỬA
    # ==========================================
    def on_search_text_changed(self, text):
        return playlist_view(self).request_filter(text)

    def execute_filter(self):
        return playlist_view(self).filter_async()

    def set_card_active_style(self, card):
        card.setStyleSheet(self.CARD_STYLE_ACTIVE)
        for label in card.findChildren(QLabel):
            if label.property("is_title"):
                label.setStyleSheet("color: #A9F1D9; font-weight: bold; font-size: 13px; border: none;")

    def set_card_normal_style(self, card):
        card.setStyleSheet(self.CARD_STYLE_NORMAL)
        for label in card.findChildren(QLabel):
            if label.property("is_title"):
                label.setStyleSheet("color: #efefef; font-weight: 600; font-size: 13px; border: none;")
    
    def mark_playing_item(self, media_id):
        return playlist_view(self).mark(media_id)

    # ==========================================
    # CÁC SỰ KIỆN HIỂN THỊ / ẨN (ĐÃ DỌN ĐÙNG HÀM LẶP)
    # ==========================================
    def showEvent(self, event):
        win = self.window()
        if not win or win.isMinimized():
            event.ignore()
            return
            
        super().showEvent(event)

        if hasattr(win, 'sub_layer') and win.sub_layer:
            if hasattr(win, 'media_player') and win.media_player.player.playbackState() == 1:
                win.sub_layer.show()
                win.sub_layer.raise_()

        if self._prev_window_state is None:
            if win.isFullScreen(): self._prev_window_state = "fullscreen"
            elif win.isMaximized(): self._prev_window_state = "max"
            else: self._prev_window_state = "normal"

        if not win.isFullScreen() and not win.isMaximized():
            win.showMaximized()

    def hideEvent(self, event):
        win = self.window()
        if win and win.isMinimized():
            if hasattr(win, 'sub_layer') and win.sub_layer:
                win.sub_layer.hide()
            super().hideEvent(event)
            return

        super().hideEvent(event)
        if not win or self._prev_window_state is None:
            return

        if self._prev_window_state == "normal": win.showNormal()
        elif self._prev_window_state == "max": win.showMaximized()
        elif self._prev_window_state == "fullscreen": win.showFullScreen()

        self._prev_window_state = None
