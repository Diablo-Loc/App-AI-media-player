import os
import logging
import json
import psutil
import random
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QScrollArea, QFrame, QPushButton, QGridLayout, 
                             QFileDialog, QStackedWidget, QListWidget, QSizePolicy,QApplication,QLineEdit,QLabel)
from PySide6.QtCore import Qt, QTimer, QEvent, QPoint,QUrl,QObject, QFileSystemWatcher, QPropertyAnimation,QEasingCurve,QParallelAnimationGroup
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QShortcut, QKeySequence, QCursor,QPalette, QColor,QPalette
from PySide6.QtMultimediaWidgets import QVideoWidget
# Import UI components
from ui.playback_bar import PlaybackBar
from ui.media_card import MediaCard
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subs_ui.sub_panel import SettingsPanel
from subtitle.mode import SubtitleMode 
from ui.vol_panel import VolumePopup
from pipeline.utils import TempFileManager 
import shutil
# Import database components
from config import ConfigManager

from core.media_library import MediaLibrary

#Import pages for app
from ui.pages.mode_manager import HomePage, LibraryPage
from ui.pages.content_manager import ContentController
from ui.pages.for_you import ForYouPage
from ui.pages.settings import SettingsPage
from ui.pages.dynamic_island import MiniPlayer
from ui.nav.sidebar import Sidebar

logger = logging.getLogger(__name__)

class InternalMediaPlayer(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

        # 🎵 Audio
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.5)  # default 50%

        # 🎬 Player
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)

        # 🖼️ Video
        self.video_widget = QVideoWidget()
        self.player.setVideoOutput(self.video_widget)
    
    # (optional – tiện cho AppController)
    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()
        
class MainWindow(QMainWindow):
    def __init__(self, subtitle_manager, job_manager, media_library, media_player=None):
        super().__init__()
        self.app_controller = None
        self._normal_geometry = None
        self._normal_window_state = None

        # --- 0. CẤU HÌNH & DEPENDENCIES ---
        self.settings_file = "config.json"
        self.subtitle_manager = subtitle_manager
        self.job_manager = job_manager
        self.media_library = media_library
        self.vol_popup = VolumePopup(self)
        self.vol_popup.hide()
        self.is_global_shuffle = False
        # Tải cấu hình
        self.config = self.load_config()
        
        # --- 1. SETUP MEDIA PLAYER ---
        # (Làm trước để có video widget làm nền)
        if media_player is None:
            print("⚠️ MainWindow: Tự khởi tạo InternalMediaPlayer.")
            self.media_player = InternalMediaPlayer(self)
        else:
            self.media_player = media_player

        # Lấy Player gốc và Video Widget
        actual_player = getattr(self.media_player, 'player', self.media_player)
        
        if hasattr(self.media_player, 'video_widget'):
            self.video_display = self.media_player.video_widget
        else:
            print("⚠️ MainWindow: Video widget không tìm thấy, tạo fallback...")
            self.video_display = QVideoWidget()
            actual_player.setVideoOutput(self.video_display)

        # Audio Output
        self.audio_output = getattr(self.media_player, 'audio_output', None)

        # --- DYNAMIC ISLAND MINI PLAYER ---
        # 1. Tạo widget (Vẫn giữ self để app tự dọn rác khi đóng, nhưng sẽ ép nó tách ra ngoài)
        self.mini_player = MiniPlayer(self) 

        # 2. [THÊM MỚI] ÉP NÓ THÀNH CỬA SỔ ĐỘC LẬP & TRONG SUỐT TỪ TRONG TRỨNG NƯỚC
        self.mini_player.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.mini_player.setAttribute(Qt.WA_TranslucentBackground, True)
        self.mini_player.setAttribute(Qt.WA_NoSystemBackground, True)
        
        # Cố định luôn kích thước chuẩn ở đây để không bao giờ bị sai
        self.mini_player.setFixedSize(420, 64) 

        # 3. Mặc định ẩn chờ ngày được gọi
        self.mini_player.hide()  
        self.is_mini_mode = False
        self.saved_geometry = None  # Lưu kích thước cửa sổ cũ khi chuyển đổi

        # --- 2. SETUP SUBTITLE LAYER ---
        
        # 1. Lấy chuỗi từ config (ví dụ: "jp_en_vi")
        saved_mode_str = self.config.get("mode")
        
        # 2. Convert từ String -> Enum (Dùng try/except cho an toàn)
        try:
            # SubtitleMode(giá_trị) sẽ tự tìm Enum tương ứng
            initial_mode = SubtitleMode(saved_mode_str)
        except (ValueError, TypeError):
            # Nếu config rỗng hoặc lưu bậy bạ -> Về mặc định EN_VI
            initial_mode = SubtitleMode.EN_VI
            print(f"⚠️ Mode '{saved_mode_str}' không hợp lệ, về mặc định EN_VI")

        print(f"🎯 Loaded Subtitle Mode: {initial_mode.value}")

        # Khởi tạo Layer (Chỉ 1 lần duy nhất)
        self.sub_layer = SubtitleLayer(initial_mode=initial_mode, parent=self)
        
        # Áp dụng giao diện đã lưu ngay lập tức
        self.sub_layer.apply_style(
            font_size=self.config.get("font_size", 24),
            color=self.config.get("font_color", "#FFFF00"),
            bg_color=self.config.get("bg_color", "#000000"),
            bg_opacity=self.config.get("bg_opacity", 0.5)
        )
        
        # Kết nối player timeline với sub layer
        self.media_player.player.positionChanged.connect(self.sub_layer.update_position)
        
        # --- 3. SETUP CONTROLS (PlaybackBar) ---
        self.playback_bar = PlaybackBar(self)

        # --- 4. SETUP SETTINGS PANEL ---
        self.subsettings_panel = SettingsPanel(self) # Đổi tên thống nhất là settings_panel
        self.subsettings_panel.sync_ui(self.config)  # Đẩy config vào giao diện Settings
        
        # Kết nối: Khi kéo slider ở popup -> chỉnh âm lượng thật
        self.vol_popup.volumeChanged.connect(self.update_volume_from_popup)
        
        # --- 5. KẾT NỐI TÍN HIỆU (ĐÃ TỐI ƯU) ---
        
        # 1. Mode (Chỉ kết nối vào _update_mode vì hàm này đã gọi set_mode rồi)
        self.subsettings_panel.subtitle_mode_changed.connect(self._update_mode)

        # 2. Font Size (Chỉ kết nối vào _save_setting)
        # Hàm _save_setting của bác đã tự gọi apply_style rồi, nên không cần connect lẻ nữa
        self.subsettings_panel.font_size_changed.connect(lambda v: self._save_setting("font_size", v))

        # 3. Font Color
        self.subsettings_panel.font_color_changed.connect(lambda v: self._save_setting("font_color", v))

        # 4. Background Color
        self.subsettings_panel.bg_color_changed.connect(lambda v: self._save_setting("bg_color", v))

        # 5. Background Opacity
        self.subsettings_panel.bg_opacity_changed.connect(lambda v: self._save_setting("bg_opacity", v))

        # Các setting khác
        self.subsettings_panel.playback_speed_changed.connect(self.change_playback_speed)
        self.subsettings_panel.lock_position_changed.connect(self.sub_layer.set_locked)
        self.subsettings_panel.reset_requested.connect(self._reset_defaults)
        
        # Nút mở settings
        self.playback_bar.btn_subseting.clicked.connect(self.toggle_subsettings_panel)

        # --- 6. TRẠNG THÁI NỘI BỘ ---
        self.video_mode = None
        self.media_items = []      
        self.all_media_items = []
        self.grid_widgets = []     
        self.pending_items = []

        # --- 7. UI LAYOUT & WINDOW ---
        self.init_ui() 
        self.setWindowTitle("AI Media Player")
        self.resize(1100, 750)
        self.apply_global_styles()
        self.setup_shortcuts()
        self._connect_signals() # Các signal nội bộ khác của App

        # --- 8. TIMERS & FILTERS ---
        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.refresh_grid)

        self.mouse_hide_timer = QTimer()
        self.mouse_hide_timer.setSingleShot(True)
        self.mouse_hide_timer.timeout.connect(self.hide_controls)

        # Mouse Tracking
        self.setMouseTracking(True)
        self.central_widget.setMouseTracking(True)
        self.playback_bar.setMouseTracking(True)
        if self.video_display:
            self.video_display.setMouseTracking(True)
            self.video_display.installEventFilter(self)

        self.installEventFilter(self)
        if hasattr(self.playback_bar, 'video_mini_placeholder'):
            self.playback_bar.video_mini_placeholder.installEventFilter(self)
        
        self.playback_bar.video_clicked.connect(self.handle_panel_click)
        
        # --- 9. FINAL Z-ORDER (Sắp xếp lớp) ---
        self.update_video_location("mini")
        
        self.video_display.lower()       # Dưới cùng
        self.sub_layer.raise_()          # Đè lên video
        self.playback_bar.raise_()       # Đè lên sub (để click nút)
        self.subsettings_panel.raise_()     # Trên cùng

        QTimer.singleShot(0, lambda: self.update_video_location("mini"))
        QTimer.singleShot(100, lambda: self.sidebar.setCurrentRow(0))
                
    def changeEvent(self, event):
        """
        Xử lý sự kiện thay đổi trạng thái cửa sổ (Alt+Tab, Minimize)
        """
        # 1. Gọi hàm gốc của Qt trước để cập nhật trạng thái isActiveWindow()
        super().changeEvent(event)

        # Nếu chưa có sub_layer thì không làm gì cả
        if not hasattr(self, "sub_layer") or self.sub_layer is None:
            return

        # --- CASE 1: XỬ LÝ ALT + TAB (Chuyển cửa sổ) ---
        if event.type() == QEvent.Type.ActivationChange:
            # Nếu App đang được dùng (Active)
            if self.isActiveWindow():
                # Chỉ hiện sub nếu trước đó nó đang có nội dung (check cache > 0)
                # Và đảm bảo không hiện khi đang ở chế độ 'mini' (nếu bạn muốn thế)
                if getattr(self.sub_layer, "_current_ms_cache", 0) > 0:
                    # Logic phụ: Nếu đang ở màn hình duyệt file (video ẩn) thì đừng hiện sub
                    if hasattr(self, 'video_container') and not self.video_container.isHidden():
                         self.sub_layer.show()
                    elif hasattr(self, 'video_mode') and self.video_mode == 'large':
                         self.sub_layer.show()

            # Nếu App bị Alt+Tab sang app khác (Inactive)
            else:
                self.sub_layer.hide()

        # --- CASE 2: XỬ LÝ MINIMIZE (Thu nhỏ xuống Taskbar) ---
        elif event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.sub_layer.hide()
            elif self.isVisible() and not self.isMinimized():
                # Khôi phục lại khi mở lên
                if getattr(self.sub_layer, "_current_ms_cache", 0) > 0:
                    self.sub_layer.show()

    def closeEvent(self, event):
        """
        Xử lý đóng ứng dụng:
        1. Dừng Player.
        2. Dừng AI Worker.
        3. Xóa Cache.
        4. GIẾT SẠCH TIẾN TRÌNH (Force Kill).
        """
        print("🔻 Đang thực hiện quy trình đóng ứng dụng...")
        
        try:
            # --- BƯỚC 1: DỪNG PLAYER (Giải phóng file đang phát) ---
            if hasattr(self, "media_player") and self.media_player:
                player = getattr(self.media_player, "player", self.media_player)
                if hasattr(player, "stop"):
                    player.stop()
                    player.setSource(QUrl("")) # Nhả file ra

            # --- BƯỚC 2: HỦY CÁC LUỒNG AI ĐANG CHẠY ---
            # Nếu bạn có Controller quản lý AI, hãy gọi lệnh hủy tại đây
            if hasattr(self, "job_manager") and self.job_manager:
                print("⛔ Đang gửi lệnh dừng tới các Worker...")
                # Giả sử controller có hàm stop_all() hoặc cancel_all()
                if hasattr(self.job_manager, "abort_all_jobs"):
                    self.job_manager.abort_all_jobs()
                elif hasattr(self.job_manager, "terminate"): 
                    self.job_manager.terminate()
                    
            if hasattr(self, "app_controller") and self.app_controller:
                print("⛔ Đang dừng Thumbnail Scanner...")
                self.app_controller.stop_thumbnail_scan()
            
            # --- BƯỚC 3: DỌN DẸP FILE RÁC ---
            temp_path = TempFileManager.TEMP_DIR 
            if temp_path.exists():
                try:
                    shutil.rmtree(temp_path, ignore_errors=True)
                    print(f"✅ Đã dọn dẹp sạch sẽ: {temp_path}")
                except Exception as e:
                    print(f"⚠️ Không xóa được cache: {e}")

            # --- BƯỚC 4: GIẾT FFmpeg CÒN SÓT (Tùy chọn, cần thư viện psutil) ---
            # Đoạn này giúp đảm bảo không còn process ffmpeg.exe nào chạy ngầm
            try:
                current_process = psutil.Process()
                children = current_process.children(recursive=True)
                for child in children:
                    if "ffmpeg" in child.name().lower():
                        print(f"🔪 Đang diệt tiến trình con: {child.name()}")
                        child.kill()
            except Exception:
                pass

        except Exception as e:
            print(f"❌ Lỗi trong quá trình đóng: {e}")

        finally:
            print("💀 FORCE EXIT: Tắt toàn bộ hệ thống ngay lập tức!")
            event.accept()
            
            # 🔥 QUAN TRỌNG NHẤT: Lệnh này giết toàn bộ App, Thread, AI ngay lập tức
            os._exit(0)

    def moveEvent(self, event):
        """Kéo cửa sổ chính -> Sub trôi theo"""
        super().moveEvent(event)
        if hasattr(self, 'sub_layer') and self.sub_layer.isVisible():
            if not self.sub_layer._user_moved:
                self.sub_layer.center_at_bottom()
            else:
                self.sub_layer._ensure_within_bounds_global()
            
    def resizeEvent(self, event):
        super().resizeEvent(event)
            
        # ==============================================================
        # PHẦN 1: XỬ LÝ VIDEO & SUBTITLE (CHẠY NGAY LẬP TỨC)
        # ==============================================================
        video = getattr(self, "video_display", None)
        sub = getattr(self, "sub_layer", None)

        if video and video.isVisible():
            # 1. Cập nhật vị trí Subtitle
            if sub:
                # Lấy tọa độ tương đối của video so với MainWindow
                rect = video.geometry()
                pos = video.mapTo(self, QPoint(0, 0)) # Chuyển tọa độ
                
                # Đặt sub đè lên đúng vị trí video
                sub.setGeometry(pos.x(), pos.y(), rect.width(), rect.height())
                
                if hasattr(sub, "adaptive_resize"):
                    sub.adaptive_resize(rect.width())
                sub.raise_()

            # 2. Đảm bảo UI controls luôn nằm trên cùng
            if hasattr(self, "playback_bar"):
                self.playback_bar.raise_()
            if hasattr(self, "subsettings_panel"):
                self.subsettings_panel.raise_()
            
            self.sync_subtitle_margin()
        
        else:
            # Nếu không hiện video thì ẩn sub đi
            if sub: sub.hide()

        if hasattr(self, 'foryou_page') and self.content_stack.currentWidget() == self.foryou_page:
             video = getattr(self, "video_display", None)
             sub = getattr(self, "sub_layer", None)
             if video and sub and video.isVisible():
                 # Lấy vị trí video trong trang For You
                 pos = video.mapTo(self, QPoint(0, 0))
                 rect = video.rect()
                 # Ép Sub đè lên
                 sub.setGeometry(pos.x(), pos.y(), rect.width(), rect.height())
                 if hasattr(sub, "adaptive_resize"):
                    sub.adaptive_resize(rect.width())
                    
        # ==============================================================
        # PHẦN 2: XỬ LÝ GRID DANH SÁCH (CHẠY TRỄ / DEBOUNCE)
        # ==============================================================
        if hasattr(self, 'grid_widgets') and self.grid_widgets:
            
            # Reset timer mỗi khi resize
            if hasattr(self, '_resize_timer'):
                self._resize_timer.stop()
            else:
                self._resize_timer = QTimer()
                self._resize_timer.setSingleShot(True)
                # Kết nối tới hàm refresh_grid
                self._resize_timer.timeout.connect(self.refresh_grid)
            
            # Đợi 200ms sau khi ngừng kéo chuột mới tính toán lại cột
            self._resize_timer.start(200)

    def update_song_display(self):
        """Cắt chữ thông minh dựa trên kích thước thực tế của vùng hiển thị"""
        # 1. Kiểm tra an toàn trước khi xử lý
        if not hasattr(self, "lbl_title") or not hasattr(self, "info_area"):
            return

        # 2. Lấy không gian thực tế mà label có thể chiếm dụng
        # Ta dùng width của info_area làm mốc chuẩn
        available_width = self.info_area.width() - 20 # Trừ 20px padding
        
        # Đảm bảo chiều rộng không bị âm (gây lỗi Qt)
        available_width = max(available_width, 50) 

        # 3. Thực hiện elide (cắt chữ có dấu ...)
        metrics_title = self.lbl_title.fontMetrics()
        elided_title = metrics_title.elidedText(
            self.current_title, Qt.TextElideMode.ElideRight, available_width
        )
        self.lbl_title.setText(elided_title)

        metrics_artist = self.lbl_artist.fontMetrics()
        elided_artist = metrics_artist.elidedText(
            self.current_artist, Qt.TextElideMode.ElideRight, available_width
        )
        self.lbl_artist.setText(elided_artist)

        # 4. Tooltip (Quan trọng!) 
        # Vì chữ bị cắt, nên set tooltip để người dùng di chuột vào vẫn đọc được hết
        self.lbl_title.setToolTip(self.current_title)
        self.lbl_artist.setToolTip(self.current_artist)
    
    # --- UI INIT ---
    def init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.root_layout = QVBoxLayout(self.central_widget)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # Vùng chứa chính (Browser + Video Large)
        self.main_area = QWidget()
        self.main_area_layout = QGridLayout(self.main_area)
        self.main_area_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- SETUP BROWSER (Sidebar + Vùng nội dung) ---
        self.browser_widget = QWidget()
        self.browser_layout = QHBoxLayout(self.browser_widget)
        self.browser_layout.setContentsMargins(0, 0, 0, 0)
        
        # ===============================================================
        # 1. SETUP SIDEBAR CONTAINER (Cột Trái)
        # ===============================================================
        self.sidebar_container = QWidget()
        self.sidebar_container.setFixedWidth(160) # Mặc định mở
        self.sidebar_container.setStyleSheet("background-color: #0f0f0f;")
        
        self.sidebar_layout = QVBoxLayout(self.sidebar_container)
        self.sidebar_layout.setContentsMargins(0, 10, 0, 0)
        self.sidebar_layout.setSpacing(5)
        
        # A. Nút 3 gạch (Menu)
        self.btn_menu = QPushButton("☰")
        self.btn_menu.setFixedSize(36, 36)
        self.btn_menu.setCursor(Qt.PointingHandCursor)
        self.btn_menu.setStyleSheet("""
            QPushButton { border: none; color: white; font-size: 24px; background: transparent; }
            QPushButton:hover { background-color: #272727; border-radius: 25px; }
        """)

        self.btn_menu.setToolTip("Mở/Đóng Menu")
        # KẾT NỐI ANIMATION TẠI ĐÂY
        self.btn_menu.clicked.connect(self.toggle_nav_animation)

        # B. Sidebar Custom (Load từ file sidebar.py)
        self.sidebar = Sidebar()
        self.sidebar.add_menu_items(["🏠 Trang chủ", "🎶 For You", "📚 Thư viện", "⚙️ Tùy chỉnh"])

        # Add vào Container
        self.sidebar_layout.addWidget(self.btn_menu, alignment=Qt.AlignLeft)
        self.sidebar_layout.addWidget(self.sidebar)
        
        # 2. Content Stack (Nơi chứa 2 trang Home/Library)
        self.content_stack = QStackedWidget()
        self.home_page = HomePage()
        self.foryou_page = ForYouPage()
        self.library_page = LibraryPage()
        self.settings_page = SettingsPage()
        self.content_stack.addWidget(self.home_page)    # Index 0
        self.content_stack.addWidget(self.foryou_page)  # Index 1
        self.content_stack.addWidget(self.library_page) # Index 2
        self.content_stack.addWidget(self.settings_page) # Index 3
   
        # 3. Tạo Vỏ bọc (Toolbar + Stack)
        self.content_ctrl = ContentController(self)
        self.init_grid_page() 
        
        # Ráp Sidebar và Vỏ bọc vào Browser
        self.browser_layout.addWidget(self.sidebar_container) 
        self.browser_layout.addWidget(self.grid_main_page, 1)
        self.foryou_page.playlist_item_clicked.connect(self.on_playlist_item_clicked)
        # --- SETUP VIDEO LARGE ---
        self.video_container = QFrame()
        self.video_container.setStyleSheet("background-color: black;")
        self.video_main_layout = QGridLayout(self.video_container)
        self.video_main_layout.setContentsMargins(0, 0, 0, 0)
        self.video_container.hide() 
        if self.video_display:
            self.video_main_layout.addWidget(self.video_display, 0, 0)

        # Đè Browser và Video Large lên nhau
        self.main_area_layout.addWidget(self.browser_widget, 0, 0)
        self.main_area_layout.addWidget(self.video_container, 0, 0)

        # Thêm Main Area và Playback Bar vào Root
        self.root_layout.addWidget(self.main_area)
        self.root_layout.addWidget(self.playback_bar)

        # --- KẾT NỐI TÍN HIỆU ---
        self.sidebar.itemClicked.connect(self.handle_sidebar_click)

    #(thanh điều phối ở trên: mở thư mục và tìm kiếm ,...)
    def init_grid_page(self):
        # Tạo widget đại diện cho toàn bộ vùng bên phải
        self.grid_main_page = QWidget()
        layout = QVBoxLayout(self.grid_main_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # --- 1. TẠO VỎ BỌC CHO TOOLBAR ---
        self.top_toolbar_container = QWidget() # Đây là cái "công tắc" để ẩn/hiện
        toolbar_layout = QHBoxLayout(self.top_toolbar_container)
        toolbar_layout.setContentsMargins(0, 0, 10, 0)
        
        # A. Nút Mở Thư Mục
        self.btn_folder = QPushButton("📂 Mở Thư Mục Video")
        self.btn_folder.setFixedSize(200, 40)
        self.btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_folder.clicked.connect(self.choose_folder)
        
        # B. Thanh Tìm Kiếm
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Tìm kiếm video...")
        self.search_input.setFixedWidth(300)
        self.search_input.setFixedHeight(40)
        self.search_input.textChanged.connect(self.filter_grid)
        
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2b2b2b;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                border-radius: 20px; 
                padding: 0 15px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #1DB954;
                background-color: #333333;
            }
        """)

        toolbar_layout.addWidget(self.btn_folder)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.search_input)

        # --- 2. RÁP VÀO LAYOUT ---
        layout.addWidget(self.top_toolbar_container)
        layout.addWidget(self.content_stack)
        
    # --- SIGNALS & SLOTS ---
    def _connect_signals(self):
        player = self.media_player.player
        player.playbackStateChanged.connect(self.update_ui_state)
        player.positionChanged.connect(self.on_position_changed)
        player.durationChanged.connect(self.update_slider_range)
        player.mediaStatusChanged.connect(self.handle_media_status_wrapper)
        #player.mediaStatusChanged.connect(self.handle_media_status)
        
        self.playback_bar.btn_vol.clicked.connect(self.show_volume_popup)
        self.playback_bar.btn_play.clicked.connect(self.toggle_play_pause)
        self.playback_bar.btn_next.clicked.connect(self.play_next)
        self.playback_bar.btn_prev.clicked.connect(self.play_previous)
        self.playback_bar.btn_fs.clicked.connect(self.toggle_fullscreen)
        self.playback_bar.reload_clicked.connect(self.action_reload_current_video)
        self.sidebar.itemClicked.connect(self.handle_sidebar_click)
        self.foryou_page.shuffle_req_signal.connect(self.toggle_global_shuffle)
        self.playback_bar.shuffle_clicked.connect(self.toggle_global_shuffle)
        
        # 1. Khi đang kéo -> Cập nhật video liên tục
        self.playback_bar.time_slider.sliderMoved.connect(self.on_seek_move)
        # 2. Khi thả chuột -> Chốt vị trí (Fix lỗi đôi khi bị giật lại)
        self.playback_bar.time_slider.sliderReleased.connect(self.on_seek_release)
        
        if hasattr(self, 'mini_player'):
            self.mini_player.play_req.connect(self.toggle_play_pause)
            self.mini_player.next_req.connect(self.play_next)
            self.mini_player.prev_req.connect(self.play_previous)
            self.mini_player.restore_req.connect(self.switch_to_normal_mode)
            self.mini_player.focus_changed.connect(self.on_mini_player_focus_changed)
        # dynamic island button on playback bar
        if hasattr(self.playback_bar, 'dynamic_island_clicked'):
            self.playback_bar.dynamic_island_clicked.connect(self.switch_to_mini_mode)
            
    # --- CÁC HÀM PLAYER LOGIC ---
    def handle_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_next()

    def toggle_play_pause(self):
        if self.media_player.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.player.pause()
        else:
            self.media_player.player.play()
        self.sync_mini_player_state()
    
    def on_mini_player_focus_changed(self, has_focus):
        """Handle spacebar shortcut enable/disable khi MiniPlayer focus thay đổi"""
        if hasattr(self, 'spacebar_shortcut'):
            self.spacebar_shortcut.setEnabled(not has_focus)
            # print(f"Spacebar shortcut: {'DISABLED' if has_focus else 'ENABLED'}")

    def update_ui_state(self, state):
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        self.playback_bar.update_play_state(is_playing)
        # đồng bộ mini player mọi khi trạng thái phát thay đổi
        self.sync_mini_player_state()

    def on_position_changed(self, position):
        if not self.playback_bar.time_slider.isSliderDown():
            self.playback_bar.update_position(position, self.format_time(position))

    def update_slider_range(self, duration):
        if duration > 0:
            self.playback_bar.update_duration(duration, self.format_time(duration))

    def show_volume_popup(self):
        btn = self.playback_bar.btn_vol
        
        # 1. Lấy tọa độ toàn cục (Global)
        btn_pos = btn.mapToGlobal(QPoint(0, 0)) # Vị trí nút
        win_pos = self.mapToGlobal(QPoint(0, 0)) # Vị trí cửa sổ App
        
        # 2. Lấy kích thước
        popup_w = self.vol_popup.sizeHint().width()
        popup_h = self.vol_popup.sizeHint().height()
        btn_w = btn.width()
        
        # 3. Tính X ban đầu (Cố gắng căn giữa nút loa)
        x = btn_pos.x() + (btn_w // 2) - (popup_w // 2)
        
        # --- XỬ LÝ CHỐNG TRÀN MÉP PHẢI ---
        
        # Tính tọa độ mép phải của cửa sổ App
        app_right_edge = win_pos.x() + self.width()
        
        # Nếu mép phải của Popup (x + chiều rộng popup) > Mép phải App
        if (x + popup_w) > app_right_edge:
            # Dịch x lùi lại sao cho mép phải popup trùng với mép phải App
            # (-15px padding để nó cách viền ra một chút cho đẹp)
            x = app_right_edge - popup_w - 15
            
        # ---------------------------------
        
        # 4. Tính Y (Nằm trên nút loa)
        y = btn_pos.y() - popup_h - 15
        
        # 5. Cập nhật giá trị và hiển thị
        current_vol = int(self.audio_output.volume() * 100)
        self.vol_popup.set_value(current_vol)
        
        self.vol_popup.move(x, y)
        self.vol_popup.show()

    def update_volume_from_popup(self, value):
        """Hàm nhận giá trị từ popup để chỉnh âm thanh"""
        float_vol = value / 100.0
        self.audio_output.setVolume(float_vol)
        
        # Update icon loa ở thanh bar chính (Mute/Unmute icon)
        icon = "🔇" if float_vol == 0 else "🔉" if float_vol < 0.5 else "🔊"
        self.playback_bar.btn_vol.setText(icon)

    def adjust_volume(self, delta):
        """Xử lý khi bấm phím tắt Tăng/Giảm âm lượng"""
        if not self.audio_output:
            return
        current_vol = self.audio_output.volume()
        new_vol = max(0.0, min(1.0, current_vol + delta))
        self.audio_output.setVolume(new_vol)
        self.vol_popup.set_value(int(new_vol * 100))
        self.playback_bar.btn_vol.setText("🔇" if new_vol == 0 else "🔉" if new_vol < 0.5 else "🔊")

    def seek_relative(self, ms):
        player = self.media_player.player
        if player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            new_pos = max(0, player.position() + ms)
            player.setPosition(new_pos)

    def handle_sidebar_change(self, index):
        if index in [0, 1]: 
            self.update_video_location("mini")

    def format_time(self, ms):
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def setup_shortcuts(self):
        self.spacebar_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.spacebar_shortcut.activated.connect(self.toggle_play_pause)
        
        QShortcut(QKeySequence(Qt.Key.Key_F), self).activated.connect(self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(lambda: self.toggle_fullscreen() if self.isFullScreen() else None)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(lambda: self.seek_relative(10000))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(lambda: self.seek_relative(-10000))
        QShortcut(QKeySequence(Qt.Key.Key_Up), self).activated.connect(lambda: self.adjust_volume(0.05))
        QShortcut(QKeySequence(Qt.Key.Key_Down), self).activated.connect(lambda: self.adjust_volume(-0.05))

    # --- GRID & LOADING LOGIC (Giữ nguyên) ---
    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục video")
        if not folder: return

        # Lưu Config
        from config import ConfigManager
        ConfigManager.save_last_folder(folder)

        # Load folder (Chỉ truyền folder, không cần use_cache)
        self.load_folder_content(folder)

    def load_next_batch(self):
        """Load từng nhóm 12 video - Phiên bản tối ưu tính toán"""
        # 1. Kiểm tra nếu hết hàng
        if not self.pending_items:
            # Load xong hết thì bật lại UI cho chắc chắn
            self.scroll_area.setUpdatesEnabled(True)
            return

        # 2. Chuẩn bị batch
        batch_size = 12
        items_to_load = self.pending_items[:batch_size]
        self.pending_items = self.pending_items[batch_size:]

        # 🔥 Tắt vẽ UI (Quan trọng: Tắt trên scroll_area hiệu quả hơn container con)
        self.scroll_area.setUpdatesEnabled(False) 

        # --- TỐI ƯU: TÍNH TOÁN GRID MỘT LẦN DUY NHẤT ---
        # Thay vì gọi add_card_to_grid (tính đi tính lại), ta tính thủ công ở đây
        viewport_width = self.scroll_area.viewport().width()
        min_card_width = 230
        cols = max(1, viewport_width // min_card_width)
        
        # Lấy vị trí bắt đầu của batch này
        start_index = self.grid_layout.count()

        for i, item in enumerate(items_to_load):
            # A. Tạo Card
            card = MediaCard(item)
            card.clicked.connect(self.on_media_clicked)
            card.clicked.connect(lambda i=item: self.sync_to_foryou(i))
            # B. Lưu quản lý
            self.grid_widgets.append(card)
            
            if not hasattr(self, 'card_map'):
                self.card_map = {}
            self.card_map[item.id] = card
            
            # C. Tính vị trí nhanh (Không cần hàm divmod lặp lại logic width)
            # Vị trí thực = (Vị trí bắt đầu batch + thứ tự i)
            real_index = start_index + i
            row, col = divmod(real_index, cols)
            
            # D. Thêm vào layout
            self.grid_layout.addWidget(card, row, col)

            # E. Request Thumbnail
            if item.thumbnail and os.path.exists(item.thumbnail):
                card.update_thumbnail(item.thumbnail)
        
        # --- TỐI ƯU: SET STRETCH MỘT LẦN CUỐI CÙNG ---
        # Đảm bảo các cột dãn đều nhau
        for c in range(cols):
            self.grid_layout.setColumnStretch(c, 1)

        # 🔥 Bật lại UI -> Grid hiện ra nguyên khối (không bị chớp từng cái)
        self.scroll_area.setUpdatesEnabled(True)

        # Đệ quy: Nếu còn hàng thì nghỉ 10ms rồi load tiếp
        if self.pending_items:
            QTimer.singleShot(10, self.load_next_batch)
            
    def refresh_grid(self):
        """Tự động xếp lại card khi kích thước cửa sổ thay đổi"""
        # 1. Xác định trang mục tiêu
        current_page = self.content_stack.currentWidget()
        
        # Kiểm tra an toàn: trang phải tồn tại và có grid_container
        if not current_page or not hasattr(current_page, 'grid_container'):
            return
        if not self.isVisible(): 
            return
        
        layout = current_page.grid_layout
        if layout.count() == 0: 
            return

        # 2. Nếu đang tìm kiếm, dùng hàm filter_grid để reflow vị trí các card đang hiện
        if hasattr(self, 'search_input') and self.search_input.text().strip():
            self.filter_grid(self.search_input.text())
            return

        # 3. Logic xếp lại bình thường khi không search
        v_width = current_page.scroll_area.viewport().width()
        # Fallback nếu viewport chưa kịp render (trả về 0 hoặc < 100)
        if v_width < 100: 
            v_width = self.width() - 250 
        
        cols = max(1, v_width // 230)
        
        # Tối ưu: Nếu số cột không đổi thì thoát sớm cho nhẹ máy
        current_last_cols = getattr(current_page, '_last_cols', 0)
        if current_last_cols == cols:
            return
        current_page._last_cols = cols

        # Tắt vẽ để tránh giật lag khi xếp lại số lượng lớn card
        current_page.grid_container.setUpdatesEnabled(False)
        
        try:
            # Thu thập tất cả card hiện có trong layout
            all_widgets = []
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if w: 
                    all_widgets.append(w)

            # Xóa các tỉ lệ cột cũ
            for c in range(layout.columnCount()):
                layout.setColumnStretch(c, 0)

            # Xếp lại từng card vào vị trí mới (row, col)
            for i, widget in enumerate(all_widgets):
                row, col = divmod(i, cols)
                layout.addWidget(widget, row, col)
                    
            # Thiết lập tỉ lệ giãn đều cho các cột mới
            for c in range(cols):
                layout.setColumnStretch(c, 1)
                
        finally:
            # Quan trọng: Luôn bật lại vẽ dù có lỗi xảy ra hay không
            current_page.grid_container.setUpdatesEnabled(True)
    
    def load_library(self):
        # 1. Load dữ liệu từ ổ cứng/quét folder
        self.app_controller.scan_folder(...) 
        
        # 2. Tạo Card và hiển thị lên Grid
        self.populate_grid() 
        self.refresh_grid()
        
        # 3. 🔥 KÍCH HOẠT QUÉT THUMBNAIL NGẦM
        # Chỉ bắt đầu chạy nặng sau khi UI đã hiện lên (để app khởi động nhanh)
        self.app_controller.start_thumbnail_scan()
    
    def apply_global_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; }
            QListWidget { background-color: #000000; border: none; color: #b3b3b3; font-size: 14px; }
            QListWidget::item { padding: 15px; border-radius: 5px; }
            QListWidget::item:selected { background-color: #282828; color: white; }
            QSlider::groove:horizontal { height: 4px; background: #4d4d4d; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #1DB954; border-radius: 2px; }
            QSlider::handle:horizontal { background: white; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px; }
            QSlider::handle:horizontal:hover { background: #1DB954; width: 14px; height: 14px; }
        """)

    def play_next(self):
        """Phát bài tiếp theo dựa trên Playlist đã chốt"""
        self._navigate_active_playlist(1)

    def play_previous(self):
        """Phát bài trước đó dựa trên Playlist đã chốt"""
        self._navigate_active_playlist(-1)

    def _navigate_active_playlist(self, direction):
        """Hàm dùng chung để điều hướng trong Playlist ngầm"""
        if not hasattr(self, 'active_playlist') or not self.active_playlist:
            print("⚠️ Không có playlist để điều hướng")
            return

        try:
            # Tìm index dựa trên object media_item hiện tại (nhanh và chuẩn hơn so sánh path)
            current_idx = self.active_playlist.index(self.current_media_item)
            
            # Tính toán index mới
            new_idx = current_idx + direction
            
            # Kiểm tra biên
            if 0 <= new_idx < len(self.active_playlist):
                next_item = self.active_playlist[new_idx]
                self.on_media_clicked(next_item, update_playlist=False)
            else:
                # Nếu lùi quá bài đầu hoặc tiến quá bài cuối
                if direction > 0: # Hết list thì quay lại bài đầu (Repeat All)
                    self.on_media_clicked(self.active_playlist[0], update_playlist=False)
                else: # Lùi quá bài đầu thì về bài cuối
                    self.on_media_clicked(self.active_playlist[-1], update_playlist=False)
                    
        except (ValueError, AttributeError) as e:
            print(f"❌ Lỗi điều hướng: {e}")
            # Dự phòng: Phát bài đầu tiên nếu không tìm thấy vị trí hiện tại
            self.on_media_clicked(self.active_playlist[0], update_playlist=False)

    def switch_to_player_page(self):
        """Click vào video: Điều hướng thông minh dựa trên Tab hiện tại"""
        if not hasattr(self, 'media_player') or self.media_player.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            return

        # 1. Nếu đang ở chế độ Large (To) -> THU NHỎ VỀ
        if not self.video_container.isHidden():
            # --- [LOGIC QUAN TRỌNG: ĐƯỜNG VỀ NHÀ] ---
            # Kiểm tra xem đang ở tab nào?
            current_index = self.content_stack.currentIndex()
            
            if current_index == 1: # Giả sử 1 là Tab For You
                # Về chế độ Normal (tràn màn hình)
                self.manage_video_state("normal")
            else:
                # Về chế độ Mini (góc dưới)
                self.manage_video_state("mini")

        # 2. Nếu đang ở chế độ Mini hoặc Normal (Ẩn Large) -> PHÓNG TO
        else:
            self.manage_video_state("large")

    def handle_panel_click(self):
        """Xử lý khi click vào panel dưới đáy"""
        # Nếu media chưa chạy thì bỏ qua
        if not hasattr(self, 'media_player') or self.media_player.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            return

        # LOGIC TƯƠNG TỰ: Check Tab để quyết định hướng đi
        current_index = self.content_stack.currentIndex()
        is_foryou = (current_index == 1)
        
        # 1. Nếu đang ở Large -> Thu nhỏ
        if not self.video_container.isHidden():
            if not self.isFullScreen(): # Chỉ thu nhỏ khi không full screen (tùy bác)
                if is_foryou:
                    self.manage_video_state("normal")
                else:
                    self.manage_video_state("mini")
                print(f"Returning to {'For You' if is_foryou else 'Mini'} Mode")

        # 2. Nếu đang ở Mini -> Phóng to
        else:
            # Lưu ý: Nếu đang ở For You (Normal), thanh panel thường bị ẩn hoặc đè lên.
            # Nhưng nếu click được vào nó, ta vẫn cho phóng to Large.
            self.manage_video_state("large")
            print("Switching to Large Mode")
            
    def eventFilter(self, watched, event):
        # 1. Kiểm tra an toàn: Đảm bảo các widget quan trọng đã tồn tại
        if not hasattr(self, 'video_display') or not hasattr(self, 'playback_bar'):
            return super().eventFilter(watched, event)

        # 2. Định nghĩa các vùng tương tác
        is_mini_panel = (watched == self.playback_bar.video_mini_placeholder)
        is_video_click = (watched == self.video_display)

        # --- XỬ LÝ DOUBLE CLICK ---
        if event.type() == QEvent.Type.MouseButtonDblClick and is_video_click:
            if hasattr(self, 'toggle_fullscreen'):
                self.toggle_fullscreen()
            return True # Đã xử lý xong, không cho truyền tiếp (chặn zoom mặc định nếu có)

        # --- XỬ LÝ MOUSE MOVE ---
        if event.type() == QEvent.Type.MouseMove:
            if self.isFullScreen():
                self.show_controls()
                if hasattr(self, 'mouse_hide_timer'):
                    self.mouse_hide_timer.start(3000)
            return False # Luôn trả về False để UI bên dưới vẫn nhận được tọa độ chuột

        # --- XỬ LÝ CLICK TRÁI ---
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            # Case 1: Click vào khung mini ở góc
            if is_mini_panel:
                if self.isFullScreen(): return True
                
                if hasattr(self, 'video_container'):
                    # Logic toggle: Nếu đang ẩn hoặc đang ở mini thì chuyển đổi
                    mode = "large" if self.video_container.isHidden() else "mini"
                    self.update_video_location(mode)
                return True

            # Case 2: Click vào màn hình video chính
            if is_video_click:
                if hasattr(self, 'video_container') and not self.video_container.isHidden():
                    # Toggle ẩn/hiện thanh điều khiển
                    if self.playback_bar.isVisible():
                        self.hide_controls()
                    else:
                        self.show_controls()
                    return True
            
        # --- CUỐI CÙNG: TRẢ VỀ CHO HỆ THỐNG ---
        # Quan trọng: Không return False tùy tiện, hãy để super() lo phần còn lại
        return super().eventFilter(watched, event)

    def on_media_clicked(self, media_item, force_gen=False, update_playlist=True):
        """Xử lý khi click vào một bài hát / video"""

        # Lưu bài đang phát để hàm play_next biết đường mà tìm
        self.current_media_item = media_item

        # Chụp ảnh toàn bộ danh sách từ giao diện đang hiển thị
        if update_playlist:
            current_page = self.content_stack.currentWidget()
            self.active_playlist = [] # Reset playlist
            
            # TRƯỜNG HỢP 1: Trang For You (Dùng danh sách lazy load)
            if hasattr(self, 'foryou_page') and current_page == self.foryou_page:
                self.active_playlist = list(self.foryou_page.all_items_data)
                print(f"📋 Playlist ForYou: Đã chốt {len(self.active_playlist)} bài.")

            # TRƯỜNG HỢP 2: Các trang cũ (Dùng Grid Layout như Home/Library)
            elif current_page and hasattr(current_page, 'grid_layout'):
                layout = current_page.grid_layout
                for i in range(layout.count()):
                    widget = layout.itemAt(i).widget()
                    if widget and hasattr(widget, 'media_item'):
                        self.active_playlist.append(widget.media_item)
                print(f"📋 Playlist Library: Đã chốt {len(self.active_playlist)} bài.")

            # Sau khi chốt playlist, nếu For You đang mở thì đồng bộ giao diện bên phải luôn
            if self.active_playlist and hasattr(self, 'foryou_page'):
                # Dùng Signal hoặc gọi trực tiếp để bên For You vẽ lại danh sách bên phải
                self.foryou_page.load_playlist(self.active_playlist)
        
        # 0. HỦY JOB CŨ (AI, subtitle...)
        if hasattr(self, "app_controller"):
            self.app_controller.cancel_current_job()

        # =============================
        # 1. KIỂM TRA PATH
        # =============================
        video_path = str(media_item.path)

        if not video_path or not os.path.isfile(video_path):
            print(f"❌ File không tồn tại hoặc path lỗi: {video_path}")
            return

        print(f"▶️ Bắt đầu phát: {media_item.title} - {getattr(media_item, 'artist', '')} (Force: {force_gen})")

        # =============================
        # 2. CẬP NHẬT GIAO DIỆN (TITLE + ARTIST)
        # =============================
        # Đây là chỗ thay đổi để dùng hàm set_media_info mới
        if hasattr(self, "playback_bar") and hasattr(self.playback_bar, 'set_media_info'):
            # Lấy artist từ media_item, đề phòng trường hợp object cũ chưa có field artist
            artist_name = getattr(media_item, "artist", "Unknown Artist")
            self.playback_bar.set_media_info(media_item.title, artist_name)

        # =============================
        # 3. RESET PLAYER (CHỈ PLAYER)
        # =============================
        player = self.media_player.player
        player.stop()
        player.setSource(QUrl.fromLocalFile(video_path))
        
        # Ngắt kết nối cũ (để tránh gọi chồng chéo nhiều lần)
        try: player.metaDataChanged.disconnect(self._on_video_metadata_ready)
        except: pass
        # Kết nối mới
        player.metaDataChanged.connect(self._on_video_metadata_ready)
        
        player.play()

        # Fix audio mute state
        if hasattr(self, "audio_output") and self.audio_output:
            self.audio_output.setMuted(False)
            # Giữ nguyên volume hiện tại

        # =============================
        # 4. RESET SUBTITLE
        # =============================
        if hasattr(self, "sub_layer"):
            self.sub_layer.subtitles = []       # Xóa dữ liệu sub cũ
            self.sub_layer._start_times = []    # Xóa mốc thời gian
            self.sub_layer.setText("")          # Xóa text trên màn hình
            self.sub_layer.adjustSize()
            self.sub_layer.hide()               # Ẩn tạm thời

        # =============================
        # 5. GIAO QUYỀN CHO AppController (LOGIC AI/SUB)
        # =============================
        # Chỉ gọi 1 lần duy nhất ở đây
        if hasattr(self, "app_controller"):
            self.app_controller.on_media_item_clicked(media_item, force_gen=force_gen)
        QTimer.singleShot(100, self.sync_subtitle_margin)
        
        # =============================
        # 6. SYNC VỚI FOR YOU PAGE (Highlight bài đang phát)
        # =============================
        # Luôn gọi sync_to_foryou để highlight bài trên ForYou page
        # Nếu chưa ở ForYou, nhưng sau này switch sang ForYou, bài sẽ vẫn được highlight
        self.sync_to_foryou(media_item)
                
        if hasattr(self, 'foryou_page'):
            # 1. Cập nhật text tiêu đề chính
            self.foryou_page.title_label.setText(media_item.title)
            self.foryou_page.artist_label.setText(getattr(media_item, "artist", "Unknown"))
            
            # 2. Cập nhật Playlist nếu cần
            if update_playlist and hasattr(self, 'active_playlist'):
                self.foryou_page.load_playlist(self.active_playlist)

            # 3. THÊM DÒNG NÀY: Tô đậm bài đang phát trong danh sách bên phải
            self.foryou_page.mark_playing_item(media_item.id)
            
            # --- [MỚI] RESET VIDEO STAGE VỀ MẶC ĐỊNH ---
            # Tránh trường hợp video trước là dọc, video này là ngang mà chưa kịp load size
            self.foryou_page.video_container.video_width = 1920
            self.foryou_page.video_container.video_height = 1080
            self.foryou_page.video_container.resizeEvent(None)
        # ngay sau khi bài mới được kích hoạt, cập nhật mini player
        self.sync_mini_player_state()
    
    def _on_video_metadata_ready(self):
        """Hàm callback khi video load xong metadata (để lấy width/height)"""
        if not hasattr(self, 'foryou_page'): return
        
        # 1. Lấy resolution từ Player
        # Lưu ý: PySide6 trả về QSize
        video_size = self.media_player.player.videoSink().videoSize()
        
        if video_size.isValid():
            w = video_size.width()
            h = video_size.height()
            print(f"📏 Video Size Detected: {w}x{h}")
            
            # 2. Cập nhật vào VideoStage
            video_stage = self.foryou_page.video_container
            video_stage.video_width = w
            video_stage.video_height = h
            
            # 3. Ép tính toán lại giao diện ngay lập tức
            video_stage.resizeEvent(None)
                    
    # DÙNG CHO NÚT RELOAD / CONTEXT MENU
    def force_reload_subtitle(self, media_item):
        """
        Hàm này gắn vào nút 'Tạo lại Subtitle'.
        Nó kích hoạt quy trình cũ NHƯNG ép buộc AI chạy lại.
        """
        if not media_item: return
        print(f"♻️ Yêu cầu Reload Subtitle cho: {media_item.title}")
        
        # Gọi hàm chính với cờ force_gen = True
        self.on_media_clicked(media_item, force_gen=True)
     
    # Hàm trung gian để lấy video đang phát hiện tại và reload
    def action_reload_current_video(self):
        if hasattr(self, "app_controller") and self.app_controller.current_media_item:
            # Lấy item đang phát từ Controller và ép chạy lại
            self.force_reload_subtitle(self.app_controller.current_media_item)
        else:
            print("⚠️ Không có video nào đang phát để reload!")
        
    def _show_status(self, message):
        """Hiển thị thông báo lên thanh trạng thái (StatusBar)"""
        # Nếu bác có dùng self.statusBar() của QMainWindow
        self.statusBar().showMessage(message, 5000) # Hiện trong 5 giây
        print(f"📢 STATUS: {message}")
        
    def toggle_fullscreen(self):
        if self.isFullScreen():
            # Thoát fullscreen
            self.showNormal()
            self.sidebar.show()
            self.update_video_location("large")
            self.playback_bar.show()
            self.setCursor(Qt.ArrowCursor)
            self.playback_bar.btn_fs.setText("⛶")
            self.mouse_hide_timer.stop()
        else:
            # Vào fullscreen
            self.update_video_location("large")
            self.sidebar.hide()
            self.showFullScreen()
            self.playback_bar.show()
            self.setCursor(Qt.ArrowCursor)
            self.playback_bar.btn_fs.setText("↙️")
            self.mouse_hide_timer.start(3000)
        QTimer.singleShot(100, self.sync_subtitle_margin)
    
    def show_controls(self):
        if self.playback_bar.isHidden():
            self.playback_bar.show()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            
            # [SỬA] Gọi hàm đồng bộ thay vì set cứng
            self.sync_subtitle_margin()

    def hide_controls(self):
        """Ẩn thanh điều khiển và chuột"""
        if self.playback_bar.underMouse():
            return
            
        self.playback_bar.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.mouse_hide_timer.stop() 
        
        # [SỬA] Gọi hàm đồng bộ thay vì set cứng
        self.sync_subtitle_margin()
    
    def sync_subtitle_margin(self):
        if not hasattr(self, 'sub_layer') or not self.sub_layer:
            return

        current_index = self.content_stack.currentIndex()
        is_foryou_page = (current_index == 1)
        # Lấy mode hiện tại: 'normal', 'large', hoặc 'fullscreen'
        v_mode = getattr(self, 'video_mode', 'normal')

        # --- SỬA LẠI ĐIỀU KIỆN CHẶN ---
        # CHỈ chặn khi: Đang ở tab For You VÀ Video đang ở mode Normal (nằm trong khung nhỏ)
        if is_foryou_page and v_mode == 'normal':
            if hasattr(self.sub_layer, 'set_bottom_margin'):
                self.sub_layer.set_bottom_margin(0)
            return

        # --- CÁC TRƯỜNG HỢP CÒN LẠI (Home, Library, hoặc For You nhưng mode Large/Full) ---
        if self.playback_bar.isVisible():
            # Thường là mode Normal ở Home hoặc mode Large
            target_margin = 140  
        else:
            # Thường là mode Fullscreen
            target_margin = 40   

        if hasattr(self.sub_layer, 'set_bottom_margin'):
            self.sub_layer.set_bottom_margin(target_margin)
        
        if hasattr(self.sub_layer, 'update_after_resize'):
            self.sub_layer.update_after_resize()
        
    # tua
    def on_seek_move(self, position):
        self.media_player.player.setPosition(position)

        if not self.video_container.isHidden():
            if position != self.sub_layer._current_ms_cache:
                self.sub_layer.update_position(position)

    def on_seek_release(self):
        """Hàm này gọi khi người dùng THẢ chuột ra khỏi thanh trượt"""
        # Lấy giá trị cuối cùng của slider và set cho player (để chốt vị trí)
        position = self.playback_bar.time_slider.value()
        self.media_player.player.setPosition(position)
        
    def change_playback_speed(self, speed):
        """Xử lý thay đổi tốc độ phát"""
        self.media_player.player.setPlaybackRate(speed)
        # Hiển thị thông báo OSD nếu muốn (ví dụ: "Speed: 1.5x")
        print(f"Changed speed to {speed}x")
        
    def update_card_thumbnail(self, media_id, thumb_path):
        # 1. Tìm card trong kho (Dictionary) - Siêu nhanh O(1)
        if hasattr(self, 'card_map') and media_id in self.card_map:
            target_card = self.card_map[media_id]
            try:
                if target_card: 
                    target_card.update_thumbnail(thumb_path)
            except RuntimeError:
                pass # Card đã bị xóa
            return

        # 2. Fallback (Dự phòng nếu chưa dùng map)
        for card in self.grid_widgets:
            item = getattr(card, 'media_item', None)
            if item and item.id == media_id:
                card.update_thumbnail(thumb_path)
                break

    def toggle_subsettings_panel(self):
        """Bật tắt bảng cài đặt (Phiên bản căn lề phải chuẩn & sửa lỗi tọa độ)"""
        if self.subsettings_panel.isVisible():
            self.subsettings_panel.hide()
            return
            
        # 1. Ép panel tính lại kích thước thật dựa trên nội dung
        self.subsettings_panel.adjustSize() 

        # 2. Lấy nút settings
        btn = self.playback_bar.btn_subseting
        
        # 3. Lấy tọa độ TOÀN CỤC (Global) trên màn hình máy tính
        # Bắt buộc dùng Global vì Popup di chuyển theo tọa độ màn hình
        btn_pos = btn.mapToGlobal(QPoint(0, 0))
        
        # 4. Tính toán vị trí X (Căn lề PHẢI panel thẳng với lề PHẢI nút)
        # Công thức: Mép phải nút - Chiều rộng panel
        # (btn_pos.x() + btn.width()) là tọa độ mép phải của nút
        x = (btn_pos.x() + btn.width()) - self.subsettings_panel.width()
        
        # 5. Tính toán vị trí Y (Nằm phía TRÊN nút, cách 10px)
        y = btn_pos.y() - self.subsettings_panel.height() - 10
        
        # --- [Tùy chọn] Chống tràn mép trái ---
        # (Phòng trường hợp màn hình quá bé hoặc nút quá to)
        win_pos = self.mapToGlobal(QPoint(0, 0))
        if x < win_pos.x():
             x = win_pos.x() + 10 # Ép vào mép trái
        
        # 6. Di chuyển và hiển thị
        self.subsettings_panel.move(x, y)
        self.subsettings_panel.show()
        self.subsettings_panel.raise_()
        self.subsettings_panel.activateWindow()
    
    def set_app_controller(self, controller):
        # 1. Gắn Controller & Signal
        self.app_controller = controller
        if self.app_controller:
            self.app_controller.thumbnail_ready.connect(self.update_card_thumbnail)

        # 2. 🔥 KHỞI ĐỘNG THÔNG MINH (PHIÊN BẢN MỚI)
        # Không cần CacheManager, chỉ cần biết đường dẫn cũ là đủ
        from config import ConfigManager # Import ConfigManager
        
        last_folder = ConfigManager.get_last_folder()
        
        if last_folder:
            print(f"🔄 Khôi phục phiên làm việc: {last_folder}")
            
            # Dùng QTimer delay 100ms để giao diện hiện lên xong mới load nhạc
            QTimer.singleShot(100, lambda: self.load_folder_content(last_folder))
        else:
            print("🆕 Chưa có thư mục cũ, chờ người dùng chọn.")

    def _update_mode(self, mode):
        self.sub_layer.set_mode(mode)
        self.config["mode"] = mode.value
        self.save_config()

    def _save_setting(self, key, value):
        # 1. Lưu vào biến config
        self.config[key] = value
        # 2. Cập nhật Layer ngay lập tức
        if key == "font_size": self.sub_layer.apply_style(font_size=value)
        elif key == "font_color": self.sub_layer.apply_style(color=value)
        elif key == "bg_color": self.sub_layer.apply_style(bg_color=value)
        elif key == "bg_opacity": self.sub_layer.apply_style(bg_opacity=value)
        
        # 3. Ghi ra file
        self.save_config()

    def _reset_defaults(self):
        # Reset về mặc định
        defaults = {
            "mode": "en_vi",
            "font_size": 24,
            "font_color": "#FFFF00",
            "bg_color": "#000000",
            "bg_opacity": 0.5
        }
        self.config = defaults
        self.save_config()
        
        # Update Layer
        self.sub_layer.set_mode(SubtitleMode.EN_VI)
        self.sub_layer.apply_style(24, "#FFFF00", "#000000", 0.5)

    def load_config(self):
        try:
            with open(self.settings_file, "r") as f:
                return json.load(f)
        except:
            return {} # Trả về rỗng nếu chưa có file

    def save_config(self):
        with open(self.settings_file, "w") as f:
            json.dump(self.config, f, indent=4)
            
    def update_media_grid(self, media_items):
        if not media_items:
            self.clear_grid()
            return

        # Sắp xếp
        media_items.sort(key=lambda x: x.mtime or 0, reverse=True)
        
        # 1. Ép Qt cập nhật UI để Stack chuyển trang xong xuôi
        QApplication.processEvents() 

        # 2. Lấy trang đang hiện
        current_page = self.content_stack.currentWidget()
        
        if hasattr(current_page, 'grid_layout'):
            # Trỏ tham chiếu
            self.grid_layout = current_page.grid_layout
            self.scroll_area = current_page.scroll_area
            
            # 3. Dọn dẹp grid hiện tại
            self.clear_grid() 

            # 4. Gán danh sách chờ
            self.media_items = media_items
            self.pending_items = media_items.copy() # Quan trọng: phải gán ở đây

            # 5. Bắt đầu nạp
            self.load_next_batch()
        else:
            print("⚠️ Không tìm thấy Grid Layout!")
    
    def clear_grid(self):
        """Xóa sạch Grid một cách êm ái và an toàn"""
        
        # 1. Ngắt mạch nạp dữ liệu cũ (QUAN TRỌNG NHẤT)
        # Để hàm load_next_batch đang chạy dở sẽ tự dừng lại
        if not hasattr(self, 'scroll_area') or self.scroll_area is None:
            return
        self.pending_items = [] 
        
        # 2. Tắt vẽ
        self.scroll_area.setUpdatesEnabled(False)
        
        # 3. Xóa widget trong layout
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        # 4. Dọn dẹp danh sách quản lý
        self.grid_widgets.clear()
        if hasattr(self, 'card_map'):
            self.card_map.clear()
            
        # 5. Reset UI phụ trợ
        if hasattr(self, 'search_input'):
            self.search_input.clear() # Xóa chữ tìm kiếm cũ

        # 6. Đưa thanh cuộn về đỉnh (để thư mục mới bắt đầu từ trên cùng)
        self.scroll_area.verticalScrollBar().setValue(0)
        
        # 7. Bật lại vẽ (để nhỡ thư mục mới rỗng thì giao diện vẫn cập nhật trạng thái trắng)
        self.scroll_area.setUpdatesEnabled(True)
        self.card_map = {} 
        self.grid_widgets = [] # List cũ vẫn giữ để fallback
    
    def add_card_to_grid(self, card_widget):
        """
        Tính toán vị trí (row, col) cho card mới và thêm vào layout.
        """
        # 1. Tính số cột dựa trên chiều rộng hiện tại của trang đang mở
        viewport_width = self.scroll_area.viewport().width()
        min_card_width = 230 
        cols = max(1, viewport_width // min_card_width)
        
        # 2. Đảm bảo tất cả các cột tiềm năng đều có stretch bằng nhau (chỉ cần chạy 1 lần hoặc chạy lại nếu cols đổi)
        for c in range(cols):
            self.grid_layout.setColumnStretch(c, 1)
        
        # 3. Tính vị trí dựa trên tổng số item hiện có trong grid của trang đó
        index = self.grid_layout.count()
        row, col = divmod(index, cols)
        
        self.grid_layout.addWidget(card_widget, row, col)
        
        # 🔥 QUAN TRỌNG: Đảm bảo cột này cũng được co giãn
        self.grid_layout.setColumnStretch(col, 1)
        
    #lưu vị trí foulder chưa mp4,... cũ
    def load_folder_content(self, folder_path):
        """
        Load nội dung thư mục. 
        """
        if not folder_path: return
        
        # --- BƯỚC 1: DỌN DẸP SẠCH SẼ TRƯỚC TIÊN ---
        # Phải gọi cái này đầu tiên để ngắt mọi tiến trình cũ
        self.clear_grid() 
        
        # 0. Cập nhật UI đường dẫn
        if hasattr(self, 'input_le'):
            self.input_le.setText(folder_path)

        # 1. SETUP WATCHER (Giữ nguyên)
        if not hasattr(self, 'watcher'):
            self.watcher = QFileSystemWatcher()
            self.watcher.directoryChanged.connect(self.on_folder_changed)
        
        if hasattr(self, 'current_watched_folder') and self.current_watched_folder:
             self.watcher.removePath(self.current_watched_folder)
        
        self.watcher.addPath(folder_path)
        self.current_watched_folder = folder_path

        # 2. GỌI MEDIA LIBRARY (Scan file mới)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # Scan và lưu vào kho tổng
            scanned_items = self.media_library.scan_folder(folder_path)
            self.all_media_items = scanned_items # <--- CẬP NHẬT KHO TỔNG
            self.media_items = scanned_items     # Đồng bộ luôn vào biến cũ
        except Exception as e:
            print(f"Lỗi scan: {e}")
            self.all_media_items = []
            self.media_items = []
        finally:
            QApplication.restoreOverrideCursor()
        
        # 3. SAU KHI SCAN XONG:
        if self.all_media_items:
            # Sắp xếp kho tổng
            self.all_media_items.sort(key=lambda x: x.mtime if x.mtime else 0, reverse=True)
            
            # Gửi kho tổng sang Controller
            self.content_ctrl.set_new_data(self.all_media_items)
            
            # Cập nhật Sidebar UI (Lệnh này sẽ kích hoạt handle_sidebar_navigation)
            self.sidebar.setCurrentRow(0)

        # Nạp dữ liệu vào hàng chờ (SAU KHI ĐÃ CLEAR GRID)
        #self.pending_items = self.media_items.copy()
        
        # Bắt đầu bắn
        #self.load_next_batch()
        
        # 🔥 QUAN TRỌNG: KÍCH HOẠT QUÉT THUMBNAIL NGẦM 🔥
        # Sau khi UI bắt đầu load, ta ra lệnh cho Worker chạy ngầm
        if self.app_controller:
            print(f"🚀 Bắt đầu quét thumbnail cho {len(self.media_items)} file...")
            self.app_controller.start_thumbnail_scan()
        
    def on_folder_changed(self, path):
        """Xử lý khi file trong thư mục bị thay đổi"""
        print(f"🔄 Phát hiện thay đổi file tại: {path}")
        
        # Dùng QTimer (Debounce) để tránh reload liên tục khi copy nhiều file
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        # Đợi 1.5 giây sau khi ngừng copy mới quét lại
        self.update_timer.timeout.connect(lambda: self.load_folder_content(path))
        self.update_timer.start(1500)
    
    #Logic tìm kiếm 
    def filter_grid(self, text):
        """Lọc video và xếp lại Grid dựa trên trang hiện tại"""
        search_text = text.lower().strip()
        
        # 1. Lấy trang đang hiển thị
        current_page = self.content_stack.currentWidget()
        if not current_page: return

        # 2. Thu thập các card hiện có trong grid của trang đó
        visible_cards = []
        layout = current_page.grid_layout
        
        # Duyệt qua tất cả các item trong layout để lấy widget (card)
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if not widget: continue
            
            # Giả sử media_item lưu title, hoặc bác dùng widget.metadata.title tùy code bác
            title = ""
            if hasattr(widget, 'media_item'): title = widget.media_item.title.lower()
            elif hasattr(widget, 'metadata'): title = widget.metadata.title.lower()

            if search_text in title:
                widget.show()
                visible_cards.append(widget)
            else:
                widget.hide()
        
        # 3. Xếp lại vị trí (Reflow)
        if not visible_cards: return

        current_page.grid_container.setUpdatesEnabled(False)
        
        # Tính toán cột dựa trên trang hiện tại
        v_width = current_page.scroll_area.viewport().width()
        if v_width < 100: v_width = self.width() - 250
        
        cols = max(1, v_width // 230)
        
        # Xếp lại và reset stretch
        for c in range(layout.columnCount()):
            layout.setColumnStretch(c, 0)

        for i, card in enumerate(visible_cards):
            row, col = divmod(i, cols)
            layout.addWidget(card, row, col)
            
        for c in range(cols):
            layout.setColumnStretch(c, 1)

        current_page.grid_container.setUpdatesEnabled(True)
     
    #vị trí
    def update_video_location(self, mode="mini"):
        # 1. Chặn update trùng lặp (Giữ nguyên logic của bác)
        if hasattr(self, "video_mode") and self.video_mode == mode:
            current = self.content_stack.currentWidget()
            is_foryou = (hasattr(self, 'foryou_page') and current == self.foryou_page)
            
            if is_foryou and self.video_display.parent() == self.foryou_page.video_container: return
            if not is_foryou and self.video_display.parent() == self.playback_bar.video_mini_placeholder: return

        self.video_mode = mode

        try:
            sub = getattr(self, 'sub_layer', None)

            # =====================================================
            # 1. CHẾ ĐỘ LARGE (RẠP HÁT/ FULLSCREEN)
            # =====================================================
            if mode == "large":
                self.browser_widget.hide()
                self.video_container.show()
                self.playback_bar.set_mini_video_visible(False)

                # Setup Video
                self.video_display.setParent(self.video_container)
                self.video_main_layout.addWidget(self.video_display, 0, 0)
                self.video_display.setMinimumSize(0, 0)
                self.video_display.setMaximumSize(16777215, 16777215)

                # --- [FIX QUAN TRỌNG] ---
                if sub:
                    # Reset hoàn toàn trạng thái sub khi vào large
                    sub.setParent(self)
                    if hasattr(sub, 'reset_anchor_state'): sub.reset_anchor_state()
                    if hasattr(sub, '_custom_rect'): sub._custom_rect = None
                    if hasattr(sub, 'set_anchor_rect'): sub.set_anchor_rect(None)
                    
                    # Ép kích thước phủ kín màn hình ngay lập tức
                    sub.resize(self.size())
                    sub.setGeometry(0, 0, self.width(), self.height())
                    sub.show()
                    sub.enable_render = True
                    sub.raise_()
                    
                    if hasattr(sub, 'recalc_position'): sub.recalc_position()
                    self.sync_subtitle_margin()

            # =====================================================
            # 1.5. CHẾ ĐỘ NORMAL (FOR YOU WINDOWED)
            # =====================================================
            elif mode == "normal":
                self.browser_widget.show()
                self.video_container.hide()               
                self.playback_bar.set_mini_video_visible(False)

                # 2. GẮN VIDEO VÀO FOR YOU
                self.video_display.setParent(self.foryou_page.video_container)

                # 3. FIX LỖI VIDEO BÉ (Reset cực mạnh)
                # Gỡ bỏ hoàn toàn FixedSize cũ (quan trọng nhất)
                self.video_display.setMinimumSize(0, 0)
                self.video_display.setMaximumSize(16777215, 16777215)
                self.video_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                
                self.video_display.show()

                if sub:
                    # BƯỚC QUAN TRỌNG NHẤT: Cắt đứt quan hệ cha con
                    sub.setParent(None) 
                    
                    # Biến nó thành một Window độc lập, không viền, luôn nằm trên
                    sub.setWindowFlags(
                        Qt.WindowType.FramelessWindowHint | 
                        Qt.WindowType.WindowStaysOnTopHint |
                        Qt.WindowType.WindowDoesNotAcceptFocus |
                        Qt.WindowType.Tool          # Để không hiện icon ở Taskbar
                    )
                    
                    # Sau khi setWindowFlags thường Widget sẽ bị ẩn, phải show lại
                    sub.show() 
                    
                # Gọi hàm setup_content của ForYouPage như bác đang làm
                self.foryou_page.setup_content(self.video_display, sub)
        
            # =====================================================
            # 2. CHẾ ĐỘ MINI
            # =====================================================
            else: # mode == "mini" hoặc bất cứ cái gì khác
                self.browser_widget.show()
                self.video_container.hide()
                self.playback_bar.set_mini_video_visible(True)

                self.video_display.setParent(self.playback_bar.video_mini_placeholder)
                self.playback_bar.video_mini_layout.addWidget(self.video_display)
                self.video_display.setFixedSize(140, 80)
                self.video_display.show()

                if sub:
                    sub.setParent(self)
                    if hasattr(sub, 'reset_anchor_state'): sub.reset_anchor_state()
                    if hasattr(sub, '_custom_rect'): sub._custom_rect = None
                    if hasattr(sub, 'set_anchor_rect'): sub.set_anchor_rect(None)

                    sub.enable_render = False
                    sub.hide()

            # Luôn đảm bảo video hiện
            self.video_display.raise_()

        except Exception as e:
            print(f"Lỗi update video: {e}")
    
    def manage_video_state(self, target_mode="normal"):
        # --- SETUP BIẾN CỤC BỘ (Cho gọn code) ---
        current_index = self.content_stack.currentIndex()
        is_foryou_tab = (current_index == 1)
        sub = getattr(self, 'sub_layer', None)
        vid = self.video_display 
        
        # Lấy placeholder an toàn
        bar_placeholder = None
        if hasattr(self.playback_bar, 'video_mini_placeholder'):
            bar_placeholder = self.playback_bar.video_mini_placeholder

        self.video_mode = target_mode
            
        # Hàm nội bộ để hiển thị cuối cùng (giữ nguyên logic của bác)
        def final_show():
            vid.setVisible(True)
            vid.raise_()
            if sub:
                sub.show()
                sub.raise_()

        # =============================================================
        # TRƯỜNG HỢP 1: FOR YOU (Giữ nguyên logic FIX MẤT HÌNH)
        # =============================================================
        if is_foryou_tab and target_mode == "normal":
            if not self.isFullScreen():
                self.showMaximized()

            # 1. Xử lý Playback Bar: Bóp về 0
            self.playback_bar.set_mini_video_visible(False)
            if bar_placeholder:
                bar_placeholder.setFixedWidth(0)
                bar_placeholder.hide()

            # 2. Xử lý Container: Ẩn Large, Hiện Browser
            self.browser_widget.show()
            self.video_container.hide()

            # 3. Reset Video Widget (Logic cốt lõi giữ nguyên)
            vid.setParent(None) 
            vid.setMinimumSize(0, 0)
            vid.setMaximumSize(16777215, 16777215)
            # Giữ nguyên Policy Ignored (Quan trọng cho layout ForYou)
            vid.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

            # 4. Gắn vào For You
            self.foryou_page.setup_content(vid, sub)

            # 5. Hiển thị & Fix Layout (Giữ nguyên các Timer thần thánh)
            vid.show()
            vid.raise_()
            
            if sub:
                sub._user_moved = False
                sub._rel_x_offset = 0
                sub._rel_y_from_bottom = 0
                sub.enable_render = True
                QTimer.singleShot(310, sub.show)

            self.video_mode = "normal"
            QTimer.singleShot(250, final_show)
            return

        # =============================================================
        # TRƯỜNG HỢP 2: HOME / LIBRARY / LARGE MODE
        # =============================================================
        else:
            # 1. Thu hồi Video về container gốc (Soft Reset)
            # Logic này quan trọng để tránh update_video_location bị loạn parent
            if vid.parent() != self.video_container:
                vid.setParent(self.video_container)
                vid.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                vid.show()

            # 2. Trả lại hiện trạng cho Bar
            if bar_placeholder:
                bar_placeholder.setFixedWidth(140)
                bar_placeholder.show()

            # 3. Xử lý hiển thị Container
            if target_mode == "large":
                self.browser_widget.hide()
                self.video_container.show()
                if vid.parent() != self.video_container:
                    vid.setParent(self.video_container)
                    vid.show()
            else:
                self.browser_widget.show()
                self.video_container.hide()
                # Mini mode: video_container ẩn hay hiện phụ thuộc logic update_video_location

            # 4. Giữ Sub ở Main Window (để không bị trôi theo video khi chuyển parent)
            if sub and target_mode != "normal":
                if sub.parent() != self:
                    sub.setParent(self)
                    # sub.setWindowFlags(Qt.WindowType.Widget) # Uncomment nếu cần fix lỗi sub trôi nổi

            # 5. Cập nhật vị trí chính thức
            # Gọi hàm này để nó xử lý việc nhét vào Mini Bar hoặc để Fullscreen
            self.update_video_location(target_mode)

            if target_mode == "large" and sub:
                self.sync_subtitle_margin()

            QTimer.singleShot(200, final_show)
                         
    #logic mode trang chủ, ...
    def handle_sidebar_click(self, item):
        index = self.sidebar.row(item) 
        if index == self.content_stack.currentIndex():
            return

        # ===============================================================
        # BƯỚC 0: "NUCLEAR RESET" - TẨY NÃO SUBTITLE TRƯỚC KHI CHUYỂN
        # ===============================================================
        if hasattr(self, 'sub_layer') and self.sub_layer:
            sub = self.sub_layer
            sub.hide()
            sub.enable_render = False
            sub.setParent(self)
            if hasattr(sub, '_custom_rect'): sub._custom_rect = None 
            if hasattr(sub, 'reset_anchor_state'): sub.reset_anchor_state()
            if hasattr(sub, 'set_anchor_rect'): sub.set_anchor_rect(None)

        # ===============================================================
        # BƯỚC 1 & 2: LOGIC UI
        # ===============================================================
        # 1. Chuyển trang
        self.content_stack.setCurrentIndex(index)

        # 👉 GHI NHỚ TRANG HIỆN TẠI (CỰC KỲ QUAN TRỌNG)
        if index == 1:
            self.current_page = 'for_you'
        else:
            self.current_page = 'normal'

        # 2. Xử lý Ẩn/Hiện Toolbar và Playback Bar
        is_foryou = (index == 1)
        if is_foryou:
            if not self.isMaximized():
                self._normal_geometry = self.geometry()
                self._normal_window_state = self.windowState()
            self.top_toolbar_container.hide()
            self.showMaximized()
            if hasattr(self, 'playback_bar'): self.playback_bar.show()
        else:
            if self._normal_geometry is not None:
                self.setWindowState(self._normal_window_state)
                self.setGeometry(self._normal_geometry)
            self.top_toolbar_container.show()
            if hasattr(self, 'playback_bar'): self.playback_bar.show()

        is_setting= (index == 3)
        if is_setting:
            self.top_toolbar_container.hide()
        # ===============================================================
        # BƯỚC 3: ĐIỀU HƯỚNG
        # ===============================================================
        if hasattr(self, 'content_ctrl'):
            if index == 0: self.content_ctrl.switch_to_home()
            elif index == 1: self.content_ctrl.switch_to_foryou()
            elif index == 2: self.content_ctrl.switch_to_library()
            elif index == 3: self.content_ctrl.switch_to_settings()

        # 4. Cập nhật vị trí video & sub
        if index == 1:
            self.manage_video_state("normal")            
        else:
            self.manage_video_state("mini")
            
    
    def sync_to_foryou(self, media_item):
        """Đồng bộ thông tin bài hát sang trang For You"""
        if hasattr(self, 'foryou_page'): 
            try:
                # 1. Cập nhật Tên/Ca sĩ (Metadata)
                self.foryou_page.update_art(media_item)
                
                # 2. Highlight bài hát trên playlist (nếu đã load)
                # Chỉ gọi nếu ForYou page có dữ liệu
                if self.foryou_page.all_items_data:
                    self.foryou_page.mark_playing_item(media_item.id)
                
            except Exception as e:
                print(f"Sync ForYou Error: {e}")
       
    def refresh_home(self):
        """Lấy 20 video ngẫu nhiên từ kho gốc và nạp"""
        if not hasattr(self, 'all_media_items') or not self.all_media_items:
            return
        
        # Bốc ngẫu nhiên 20 ông từ danh sách gốc
        sampled_data = random.sample(self.all_media_items, min(len(self.all_media_items), 20))
        
        # Gọi hàm nạp batch mà bác vừa sửa
        self.update_media_grid(sampled_data)

    def refresh_library(self):
        """Nạp toàn bộ video từ kho gốc"""
        if not hasattr(self, 'all_media_items') or not self.all_media_items:
            return
            
        # Nạp toàn bộ danh sách gốc
        self.update_media_grid(self.all_media_items)
        
    def on_playlist_item_clicked(self, media_item):
        self.on_media_clicked(media_item) # Phát nhạc (giữ nguyên)
        self.sync_to_foryou(media_item)    # Cập nhật số 2/615 (gọi thêm)
    
    def toggle_global_shuffle(self):
        self.is_global_shuffle = not self.is_global_shuffle
        
        # 1. Đồng bộ giao diện (Màu nút)
        self.foryou_page.set_shuffle_visual(self.is_global_shuffle)
        self.playback_bar.set_shuffle_visual(self.is_global_shuffle)
        
        # 2. Lấy danh sách (Trộn hoặc Gốc)
        if self.is_global_shuffle:
            new_list = self.foryou_page.get_shuffled_list()
        else:
            new_list = list(self.foryou_page.original_data)

        # 3. Cập nhật UI Playlist
        self.foryou_page.all_items_data = new_list
        self.foryou_page.refresh_playlist_ui()
        
        # 4. ⭐ QUAN TRỌNG: Cập nhật danh sách phát nhạc (dùng cho next/prev)
        self.active_playlist = new_list

    # --- [HÀM MỚI] ĐỒNG BỘ CONTROLLER ---
    def sync_playlist_to_backend(self, playlist):
        if not hasattr(self, 'app_controller'): return
        
        self.app_controller.set_playlist(playlist)
        
        # Tìm lại vị trí bài đang hát để không bị ngắt quãng
        current = self.app_controller.current_media
        if current:
            # Tìm index mới
            new_idx = -1
            for i, item in enumerate(playlist):
                if item.id == current.id:
                    new_idx = i
                    break
            
            # Cập nhật index và số trang hiển thị
            if new_idx != -1:
                self.app_controller.current_index = new_idx
                self.foryou_page.update_playing_status(new_idx + 1, len(playlist))
            else:
                self.app_controller.current_index = 0
    
    def toggle_nav_animation(self):
        """Hàm xử lý hiệu ứng đóng mở Menu"""
        # Kiểm tra xem đang mở hay đóng dựa trên chiều rộng hiện tại
        current_width = self.sidebar_container.width()
        
        if current_width > 100:
            # Đang Mở -> Cần Đóng (Thu về 70px)
            end_width = 70
            self.sidebar.set_mini_mode() # Ẩn chữ, hiện icon giữa
        else:
            # Đang Đóng -> Cần Mở (Ra 200px)
            end_width = 160
            self.sidebar.set_full_mode() # Hiện full chữ
            
        # Tạo Animation cho Container
        self.anim_menu = QPropertyAnimation(self.sidebar_container, b"minimumWidth")
        self.anim_menu.setDuration(250) # 0.25 giây
        self.anim_menu.setStartValue(current_width)
        self.anim_menu.setEndValue(end_width)
        self.anim_menu.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        # Animation ép cả MaximumWidth để layout không tự nhảy
        self.anim_menu_max = QPropertyAnimation(self.sidebar_container, b"maximumWidth")
        self.anim_menu_max.setDuration(250)
        self.anim_menu_max.setStartValue(current_width)
        self.anim_menu_max.setEndValue(end_width)
        
        # Chạy song song
        self.anim_group = QParallelAnimationGroup(self)
        self.anim_group.addAnimation(self.anim_menu)
        self.anim_group.addAnimation(self.anim_menu_max)
        self.anim_group.start()

    def sync_mini_player_state(self):
        """Đẩy thông tin từ App chính sang Mini Player"""
        if not hasattr(self, 'mini_player'): return

        # 1. Lấy trạng thái Play/Pause từ Player gốc
        state = self.media_player.player.playbackState()
        is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)

        # 2. Lấy tên bài hát hiện tại và thumbnail
        cover_path = None
        if hasattr(self, 'current_media_item') and self.current_media_item:
            title = getattr(self.current_media_item, 'title', '')
            artist = getattr(self.current_media_item, 'artist', '')
            cover_path = getattr(self.current_media_item, 'thumbnail', None)
        else:
            # fallback: nếu đang ở ForYou page lấy từ label (có thể trống)
            title = ''
            artist = ''
            if hasattr(self, 'foryou_page'):
                title = self.foryou_page.title_label.text() if hasattr(self.foryou_page, 'title_label') else ''
                artist = self.foryou_page.artist_label.text() if hasattr(self.foryou_page, 'artist_label') else ''

        # 3. Cập nhật giao diện Mini (với thumbnail)
        self.mini_player.update_info(title, artist, is_playing, cover_path)
    
    def handle_media_status_wrapper(self, status):
        """Hàm bọc để vừa chạy logic cũ, vừa sync mini player"""
        # Gọi hàm xử lý cũ của bạn
        self.handle_media_status(status) 
        
        # Sau khi xử lý xong (đã có tên bài mới), cập nhật Mini Player
        self.sync_mini_player_state()
    
    def switch_to_mini_mode(self):
        if getattr(self, 'is_mini_mode', False): return
        self.saved_video_mode = getattr(self, 'video_mode', 'normal')
        # [FIX FOR_YOU] Reset subtitle state trước khi chuyển chế độ
        # (Similar to handle_sidebar_click để tránh subtitle "vương vấn" trạng thái cũ)
        sub = getattr(self, 'sub_layer', None)
        if sub:
            sub.hide()
            sub.enable_render = False
            sub.setParent(self)
            if hasattr(sub, '_custom_rect'): sub._custom_rect = None
            if hasattr(sub, 'reset_anchor_state'): sub.reset_anchor_state()
            if hasattr(sub, 'set_anchor_rect'): sub.set_anchor_rect(None)

        # 1. LƯU LẠI TRẠNG THÁI CỬA SỔ CHÍNH
        self.saved_geometry = self.saveGeometry()
        self.saved_window_state = self.saveState()

        # [FIX] Ẩn tất cả content widgets trước khi ẩn main window
        self.central_widget.hide()
        if hasattr(self, 'content_stack'): self.content_stack.hide()
        if hasattr(self, 'top_toolbar_container'): self.top_toolbar_container.hide()
        if hasattr(self, 'playback_bar'): self.playback_bar.hide()

        # 2. ẨN CỬA SỔ CHÍNH (Quan trọng: Phải ẩn để cắt đứt luồng render cũ)
        self.hide()

        # 3. TÍNH TOÁN VỊ TRÍ
        from PySide6.QtGui import QGuiApplication
        screen_geo = QGuiApplication.primaryScreen().availableGeometry()
        w, h = 420, 64
        new_x = screen_geo.x() + (screen_geo.width() - w) // 2
        new_y = screen_geo.y() + 10 

        # 4. SETUP VIÊN THUỐC (Vì nó đã là Window độc lập từ __init__)
        self.mini_player.setGeometry(new_x, new_y, w, h)
        self.sync_mini_player_state()
        
        # 5. HIỆN VIÊN THUỐC
        self.mini_player.show()
        # Đưa lên trên cùng để chắc chắn không bị app khác đè
        self.mini_player.raise_()
        self.mini_player.activateWindow()
        
        # [KHÔNG GỌI self.show()] -> Cửa sổ chính cứ ẩn đi cho sạch sẽ
        self.is_mini_mode = True
        
    def switch_to_normal_mode(self):
        if not getattr(self, 'is_mini_mode', False): return

        # 1. ẨN VIÊN THUỐC
        self.mini_player.hide()
        
        # ===============================================================
        # BƯỚC 0: "NUCLEAR RESET" (Bê nguyên từ handle_sidebar_click sang)
        # Tẩy não sub ngay khi MainWindow còn đang ẩn để không bị nháy
        # ===============================================================
        sub = getattr(self, 'sub_layer', None)
        if sub:
            sub.hide()
            sub.enable_render = False
            sub.setParent(self)
            if hasattr(sub, '_custom_rect'): sub._custom_rect = None 
            if hasattr(sub, 'reset_anchor_state'): sub.reset_anchor_state()
            if hasattr(sub, 'set_anchor_rect'): sub.set_anchor_rect(None)

        # 2. KHÔI PHỤC TRẠNG THÁI CỬA SỔ (MainWindow vẫn đang ẩn)
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | 
                           Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if hasattr(self, 'saved_geometry'): self.restoreGeometry(self.saved_geometry)
        if hasattr(self, 'saved_window_state'): self.restoreState(self.saved_window_state)

        # 3. HIỆN UI NỀN
        self.central_widget.show()
        if hasattr(self, 'content_stack'): self.content_stack.show()
        if hasattr(self, 'playback_bar'): self.playback_bar.show()
        
        is_foryou = getattr(self, 'current_page', '') == 'for_you'
        if hasattr(self, 'top_toolbar_container'):
            self.top_toolbar_container.setHidden(is_foryou)

        # 4. CẬP NHẬT VIDEO & SUB (Dùng manage_video_state như sidebar click)
        self.video_mode = None # Xóa dấu vết để ép manage chạy full logic
        target_mode = getattr(self, 'saved_video_mode', 'normal')
        
        # Chỉ gọi manage nếu là For You để tránh lỗi vị trí trang khác
        if is_foryou:
            self.manage_video_state(target_mode)
        else:
            self.update_video_location(target_mode)

        # 5. HIỂN THỊ CHÍNH THỨC
        self.show()
        self.raise_()
        self.activateWindow()
        
        QApplication.processEvents()
        
        # 6. KÍCH HOẠT HIỆN SUB (Dùng delay y hệt manage_video_state)
        if sub:
            if getattr(self, 'video_mode', 'normal') != 'mini':
                from PySide6.QtCore import QTimer
                # Gọi hàm safe đã có sync margin bên trong
                QTimer.singleShot(100, lambda: self._show_sub_safe(sub))
            else:
                sub.hide()

        self.is_mini_mode = False
    def _show_sub_safe(self, sub):
        # Kiểm tra lại một lần nữa để tránh trường hợp người dùng click 
        # chuyển mode cực nhanh trong lúc Timer đang đợi
        if getattr(self, 'video_mode', 'normal') == 'mini' or not self.isVisible():
            sub.hide()
            return
            
        # Xử lý sự kiện UI để lấy tọa độ chuẩn của MainWindow và Playback Bar
        QApplication.processEvents()
            
        if hasattr(self, 'sync_subtitle_margin'):
            self.sync_subtitle_margin()
            
        # Tính toán trước khi hiện
        sub.enable_render = True
        if hasattr(sub, 'recalc_position'): 
            sub.recalc_position()
            
        # Hiển thị
        sub.show()
        sub.raise_() 
        
        # Thêm update cuối cùng để tránh vết lưu (artifact) trên màn hình
        sub.update()