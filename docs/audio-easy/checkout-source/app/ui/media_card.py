from datetime import datetime
from pathlib import Path

# Thêm QCache để quản lý bộ nhớ đệm
from PySide6.QtGui import QImageReader, QPixmap, QPixmapCache
from PySide6.QtCore import Qt, QSize, Signal, QThreadPool, QRunnable, QObject
from PySide6.QtWidgets import (QWidget, QLabel, QVBoxLayout, QSizePolicy, QFrame)
from .icons import label_icon

QPixmapCache.setCacheLimit(102400)
# =========================================================
# ⚙️ WORKER: "CÔNG NHÂN" TẢI ẢNH (CHẠY NGẦM)
# =========================================================
class LoaderSignals(QObject):
    """Tín hiệu để gửi kết quả từ luồng ngầm về giao diện chính"""
    # Gửi kèm đường dẫn (str) để làm Key lưu vào Cache
    finished = Signal(str, QPixmap)

class ImageLoader(QRunnable):
    """
    Class này chịu trách nhiệm đọc ổ cứng ở một luồng khác (Thread).
    """
    def __init__(self, cache_key, path, target_w, target_h):
        super().__init__()
        self.cache_key = cache_key
        self.path = path
        self.target_w = target_w
        self.target_h = target_h
        self.signals = LoaderSignals()
        self._is_cancelled = False

    def cancel(self):
        """Hàm để bên ngoài ra lệnh dừng luồng"""
        self._is_cancelled = True
    
    def run(self):
        # ✅ Kiểm tra 1: Trước khi bắt đầu làm việc nặng
        if self._is_cancelled: return
        
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            orig_size = reader.size()
            
            # Tính toán kích thước scale để LẤP ĐẦY khung (không bị méo)
            # Qt.KeepAspectRatioByExpanding: Giữ tỉ lệ, phóng to để lấp đầy
            scaled_size = orig_size.scaled(
                self.target_w, self.target_h, 
                Qt.KeepAspectRatioByExpanding
            )
            
            # Chỉ đọc kích thước cần thiết (Tiết kiệm RAM cực lớn)
            reader.setScaledSize(scaled_size)
            
            # ✅ Kiểm tra 2: Ngay trước khi đọc ảnh (IO nặng)
            if self._is_cancelled: return
            
            image = reader.read()
            
            # ✅ Kiểm tra 3: Sau khi đọc xong, nếu đã bị cancel thì không gửi kết quả về
            if self._is_cancelled or image.isNull():
                return
            
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                # Gửi hàng về cho Main Thread (kèm đường dẫn để định danh)
                self.signals.finished.emit(self.cache_key, pixmap)
                
        except Exception:
            pass # Lỗi đọc file thì bỏ qua

# =========================================================
# 🎬 MAIN UI: MEDIA CARD (FINAL VERSION: ASYNC + CACHE)
# =========================================================
class MediaCard(QFrame): 
    clicked = Signal(object)
    
    # Hồ bơi Thread dùng chung cho TOÀN BỘ app (Quản lý CPU)
    thread_pool = QThreadPool()
    
    def __init__(self, metadata, parent=None):
        super().__init__(parent)
        
        self.media_item = metadata 
        self.id = metadata.id
        self.metadata = metadata
        self._is_active = False
        self._is_loaded = False # Cờ đánh dấu đã load xong chưa
        self._current_worker = None #Theo dõi worker hiện tại
        
        # Tạo Cache Key khởi tạo
        self._update_cache_key()
                
        self.setAttribute(Qt.WA_StyledBackground, True)

        # --- CẤU HÌNH KÍCH THƯỚC ---
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(200) 
        self.setFixedHeight(210) 
        
        self.setCursor(Qt.PointingHandCursor)
        self._setup_ui()
        
        # Mặc định hiện icon, chưa load ảnh ngay
        self.show_default_icon()

    def _update_cache_key(self):
        """Tạo định danh duy nhất dựa trên Path + Thời gian sửa file"""
        mtime = getattr(self.metadata, 'mtime', 0)
        self.cache_key = f"{self.metadata.thumbnail}::{mtime}"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- THUMBNAIL ---
        self.thumb_label = QLabel()
        self.thumb_label.setFixedHeight(125) 
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("""
            background-color: #000000; 
            border-radius: 6px;
            border: 1px solid #333;
        """)
        
        # --- INFO ---
        self.title_label = QLabel(self.metadata.title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.title_label.setFixedHeight(36) 

        # Xử lý ngày tháng
        raw_date = getattr(self.metadata, 'mtime', None)
        date_text = ""
        if isinstance(raw_date, (float, int)) and raw_date > 0:
            try:
                date_text = datetime.fromtimestamp(raw_date).strftime("%d/%m/%Y")
            except: pass
        elif isinstance(raw_date, str):
            date_text = raw_date
        
        self.date_label = QLabel(date_text)
        self.date_label.setObjectName("cardDate")
        self.date_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        layout.addWidget(self.thumb_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.date_label)
        layout.addStretch()

        self.refresh_style()

    def paintEvent(self, event):
        """Lazy Loading: Chỉ load khi Widget thực sự vẽ lên màn hình"""
        super().paintEvent(event)
        
        # Nếu chưa load và có đường dẫn -> Bắt đầu quy trình load
        if not self._is_loaded and self.metadata.thumbnail:
            self._start_async_loading() # ✅ Gọi trơn thôi
            self._is_loaded = True 

    def update_thumbnail(self, path):
        """
        Hàm này để tương thích với MainWindow cũ.
        Khi gọi hàm này, nó sẽ reset lại và thử load ảnh mới.
        """
        if hasattr(self, 'metadata') and self.metadata:
             self.metadata.thumbnail = path
             self._update_cache_key()
        
        # Reset cờ load để nó biết là cần load lại
        self._is_loaded = False
        
        # Nếu đang hiển thị thì load luôn, nếu không để paintEvent lo
        if self.isVisible():
            self._start_async_loading()
            self._is_loaded = True
        else:
            self.show_default_icon()

    def _start_async_loading(self):
        path = self.metadata.thumbnail
        if not path: return

        # 1. Check Cache RAM (Nhanh như điện)
        # Tìm chính xác theo Key (Path + mtime)
        cached_pixmap = QPixmapCache.find(self.cache_key)
        if cached_pixmap:
            self.thumb_label.setPixmap(cached_pixmap)
            self.thumb_label.setScaledContents(False)
            return 

        # 2. Quản lý luồng cũ
        if self._current_worker:
            try:
                self._current_worker.cancel()
            except Exception:
                pass

        if not Path(path).exists(): return

        w = self.thumb_label.width() if self.thumb_label.width() > 0 else 200
        h = self.thumb_label.height() if self.thumb_label.height() > 0 else 125
        pixel_ratio = self.devicePixelRatio()
        
        # Truyền cache_key vào Worker để đảm bảo tính nhất quán
        loader = ImageLoader(self.cache_key, str(path), int(w * pixel_ratio), int(h * pixel_ratio))
        try:
            loader.signals.finished.connect(self._on_thumbnail_loaded)
        except RuntimeError:
            pass
        self._current_worker = loader  # Lưu lại worker hiện tại để có thể hủy nếu cần
        MediaCard.thread_pool.start(loader)

    def _on_thumbnail_loaded(self, incoming_key, pixmap):
        """
        Nhận ảnh từ Worker.
        """
        self._current_worker = None  # Xong việc thì giải phóng tham chiếu
        try:
            if not isinstance(pixmap, QPixmap):
                return

            if pixmap.isNull():
                return

            pixmap.setDevicePixelRatio(self.devicePixelRatio())

            # 2. Luôn lưu vào Cache (để lần sau dùng lại)
            QPixmapCache.insert(incoming_key, pixmap)

            # 3. Safety Check: Widget còn sống không?
            if not self.parent():
                return

            # 4. Tính nhất quán: Chỉ hiển thị nếu Key trả về KHỚP với Key hiện tại
            if incoming_key == self.cache_key:
                self.thumb_label.clear()
                self.thumb_label.setPixmap(pixmap)
                self.thumb_label.setScaledContents(False)

        except RuntimeError:
            pass  # Widget đã bị xóa

    def show_default_icon(self):
        self.thumb_label.clear()
        label_icon(self.thumb_label, "music", size=36)
        self.thumb_label.setStyleSheet("""
            QLabel {
                background-color: #101722;
                border-radius: 8px;
                color: #555; 
                font-size: 40px;
                border: 1px solid #273445;
            }
        """)

    def set_active(self, is_active: bool):
        self._is_active = is_active
        self.refresh_style()

    def refresh_style(self):
        """CSS Styling"""
        if self._is_active:
            bg_color = "#19372F"
            border_color = "#77E0BE"
        else:
            bg_color = "#151C26"
            border_color = "#273445"

        self.setStyleSheet(f"""
            MediaCard {{
                background-color: {bg_color};
                border-radius: 12px;
                border: 2px solid {border_color};
            }}
            MediaCard:hover {{
                background-color: #1B2431;
            }}
            #cardTitle {{
                font-weight: bold;
                font-size: 13px;
                color: #FFFFFF;
                background: transparent;
                border: none;
            }}
            #cardDate {{
                font-size: 11px;
                color: #AAAAAA;
                background: transparent;
                border: none;
            }}
        """)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.metadata)
        super().mouseReleaseEvent(event)
