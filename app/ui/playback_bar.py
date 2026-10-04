from PySide6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QLabel, 
                             QPushButton, QSlider, QWidget,QSizePolicy, QGridLayout)
from PySide6.QtCore import Qt, Signal, QEvent, QSize
from .video_info_popup import VideoInfoPopup
from .icons import button_icon, ACCENT, TEXT, INK
from .design_system import PLAYBACK_STYLE
from .track_label import TrackLabel
from .mini_video_dock import MiniVideoDock


class MetadataPanel(QFrame):
    """A preferred width that does not become the whole window's minimum."""
    preferred_width = 320

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(self.preferred_width)
        return size


class PlaybackBar(QFrame):
    play_toggled = Signal()
    seek_requested = Signal(int)
    next_requested = Signal()
    prev_requested = Signal()
    shuffle_clicked = Signal()
    repeat_toggled = Signal(bool)
    video_clicked = Signal()
    volume_btn_clicked = Signal()
    reload_clicked = Signal()
    dynamic_island_clicked = Signal()
    subtitle_tools_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(110)
        self.setObjectName("playbackBar")
        self.init_ui()
        self.video_mini_placeholder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.mini_video_dock = MiniVideoDock(self.video_mini_placeholder)
        self.info_popup = VideoInfoPopup(None)
        self._current_item_data = None # Biến lưu data bài hát hiện tại
        self.setStyleSheet(PLAYBACK_STYLE)
        controls = (
            (self.btn_shuffle, "shuffle", "Phát ngẫu nhiên"),
            (self.btn_prev, "skip-back", "Bài trước"),
            (self.btn_play, "play", "Phát / Tạm dừng"),
            (self.btn_next, "skip-forward", "Bài tiếp theo"),
            (self.btn_repeat, "repeat", "Lặp lại"),
            (self.btn_info, "info", "Thông tin bài hát"),
            (self.btn_subseting, "settings", "Cài đặt phụ đề"),
            (self.btn_sub, "captions", "Công cụ phụ đề"),
            (self.btn_reload, "refresh-cw", "Tạo lại phụ đề"),
            (self.btn_vol, "volume-2", "Âm lượng"),
            (self.btn_dynamic_island, "picture-in-picture-2", "Mini player"),
            (self.btn_fs, "maximize", "Toàn màn hình"),
        )
        for button, name, label in controls:
            if button is not self.btn_play:
                button.setFixedSize(36, 36)
            button_icon(button, name, label, color=INK if button is self.btn_play else TEXT)
        self._compact_layout = None
        self._arrange_controls(self.width())
        
    def init_ui(self):
        self.main_layout = QGridLayout(self)
        self.main_layout.setContentsMargins(14, 8, 14, 8)
        self.main_layout.setHorizontalSpacing(12)
        self.main_layout.setVerticalSpacing(4)
        self.main_layout.setColumnStretch(1, 1)

        # --- CỤM 1: THÔNG TIN (Sát trái) ---
        self.info_area = MetadataPanel()
        self.info_area.setObjectName("infoPanel")
        self.info_area.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_area.setMouseTracking(True)
        self.info_area.installEventFilter(self)
        self.info_area.setMinimumWidth(210)
        self.info_area.setMaximumWidth(320)
        
        self.info_layout = QHBoxLayout(self.info_area)
        self.info_layout.setContentsMargins(5, 5, 5, 5)
        self.info_layout.setSpacing(12)
        # Căn lề cụm 1 sát trái
        self.info_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.video_container = QFrame()
        self.video_container.setFixedSize(140, 80)
        self.video_container.setStyleSheet("background-color: #000; border-radius: 4px;")
        self.video_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        text_info_widget = QWidget()
        text_info_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_info_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text_info_layout = QVBoxLayout(text_info_widget)
        text_info_layout.setContentsMargins(0, 5, 0, 5)
        
        self.lbl_song_info = TrackLabel()
        self.lbl_song_info.setObjectName("songTitle")
        self.lbl_song_info.setTextFormat(Qt.TextFormat.RichText) # Cho phép hiện HTML
        self.lbl_song_info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.lbl_song_info.setMinimumWidth(0)
        self.lbl_song_info.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) # Để click xuyên qua vào info_area
        
        # Set text mặc định
        self.lbl_song_info.setText("""
            <div style='line-height: 120%;'>
                <span style='font-size: 14px; font-weight: bold; color: white;'>Chưa có tiêu đề</span><br>
                <span style='font-size: 11px; color: #b3b3b3;'>Chọn video để phát</span>
            </div>
        """)
        
        text_info_layout.addWidget(self.lbl_song_info)

        self.info_layout.addWidget(self.video_container)
        self.info_layout.addWidget(text_info_widget)

        # --- CỤM 2: ĐIỀU KHIỂN (Chính giữa) ---
        center_area = self.center_area = QWidget()
        center_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        center_layout = self.center_layout = QVBoxLayout(center_area)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)
        center_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # Slider nằm trên (Giống ảnh mẫu)
        self.slider_area = QWidget()
        slider_layout = QHBoxLayout(self.slider_area)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(8)
        self.lbl_current_time = QLabel("00:00")
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.time_slider.setMinimumWidth(80)
        self.lbl_total_time = QLabel("00:00")
        
        slider_layout.addWidget(self.lbl_current_time)
        slider_layout.addWidget(self.time_slider)
        slider_layout.addWidget(self.lbl_total_time)
        slider_layout.setAlignment(Qt.AlignmentFlag.AlignCenter) # Căn giữa slider

        # Nút bấm nằm dưới
        self.transport_area = QWidget()
        btns_layout = self.transport_layout = QHBoxLayout(self.transport_area)
        btns_layout.setContentsMargins(0, 0, 0, 0)
        btns_layout.setSpacing(8)
        self.btn_shuffle = QPushButton()
        self.btn_prev = QPushButton()
        self.btn_play = QPushButton()
        self.btn_play.setFixedSize(40, 40)
        self.btn_play.setObjectName("playButton")
        self.btn_next = QPushButton()
        self.btn_repeat = QPushButton()

        for btn in [self.btn_shuffle, self.btn_prev, self.btn_play, self.btn_next, self.btn_repeat]:
            btns_layout.addWidget(btn)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btns_layout.setAlignment(Qt.AlignmentFlag.AlignCenter) # Căn giữa các nút

        center_layout.addWidget(self.slider_area)
        center_layout.addWidget(self.transport_area)

        # --- CỤM 3: TIỆN ÍCH (Sát phải) ---
        extra_area = self.extra_area = QWidget()
        extra_layout = QHBoxLayout(extra_area)
        extra_layout.setContentsMargins(0, 0, 0, 0)
        extra_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        extra_area.setFixedWidth(7 * 36 + 6 * 4)
        
        #0. Nút Mở Popup Info
        self.btn_info = QPushButton()
        self.btn_info.setFixedSize(32, 32)
        self.btn_info.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_info.setToolTip("Thong tin chi tiết bài hát")
        
        # 1. Nút Cài đặt Sub
        self.btn_subseting = QPushButton()
        self.btn_subseting.setFixedSize(32, 32)
        self.btn_subseting.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_subseting.setToolTip("Cài đặt phụ đề")
        
        # 1. NÚT CÔNG CỤ PHỤ ĐỀ / BẢNG ĐEN (Subtitle Tools)
        self.btn_sub = QPushButton()
        self.btn_sub.setFixedSize(32, 32)
        self.btn_sub.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sub.setToolTip("Công cụ khớp & chỉnh sửa phụ đề (Subtitle Tools)")
        
        # 2. NÚT RELOAD
        self.btn_reload = QPushButton()
        self.btn_reload.setFixedSize(32, 32)
        self.btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload.setToolTip("Tạo lại phụ đề (AI Force)")
        self.btn_reload.setEnabled(False)
        
        # 3. Nút Loa
        self.btn_vol = QPushButton()
        self.btn_vol.setFixedSize(32, 32)
        self.btn_vol.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 3.5. Nút mở chế độ dynamic island
        self.btn_dynamic_island = QPushButton()
        self.btn_dynamic_island.setFixedSize(32, 32)
        self.btn_dynamic_island.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dynamic_island.setToolTip("Chế độ mini player")
        
        # 4. Nút Fullscreen
        self.btn_fs = QPushButton()
        
        extra_layout.addWidget(self.btn_info)
        extra_layout.addWidget(self.btn_subseting)
        extra_layout.addWidget(self.btn_sub)
        extra_layout.addWidget(self.btn_reload)
        extra_layout.addWidget(self.btn_vol)
        extra_layout.addWidget(self.btn_dynamic_island)
        extra_layout.addWidget(self.btn_fs)
        extra_layout.setSpacing(4)
        
        # --- THÊM VÀO LAYOUT CHÍNH THEO TỈ LỆ 3:4:3 ---
        self.main_layout.addWidget(self.info_area, 0, 0)
        self.main_layout.addWidget(center_area, 0, 1)
        self.main_layout.addWidget(extra_area, 0, 2)

        # Setup Video Mini & Signals
        self.video_mini_placeholder = self.video_container
        self.video_mini_layout = QVBoxLayout(self.video_mini_placeholder)
        self.video_mini_layout.setContentsMargins(0, 0, 0, 0)

        self.btn_play.clicked.connect(self.play_toggled.emit)
        self.btn_next.clicked.connect(self.next_requested.emit)
        self.btn_prev.clicked.connect(self.prev_requested.emit)
        self.btn_info.clicked.connect(self.show_video_info_popup)
        self.btn_reload.clicked.connect(self.reload_clicked.emit)
        self.btn_shuffle.clicked.connect(self.shuffle_clicked.emit)
        self.btn_dynamic_island.clicked.connect(self.dynamic_island_clicked.emit)
        
        self.time_slider.sliderReleased.connect(lambda: self.seek_requested.emit(self.time_slider.value()))
        self.time_slider.valueChanged.connect(self._on_slider_moved)
        self.btn_sub.clicked.connect(self.subtitle_tools_clicked.emit)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_compact_layout"):
            self._arrange_controls(event.size().width())

    def _arrange_controls(self, width):
        """Reflow the same controls; keep the video surface and footer height."""
        compact = width < 1000
        info_width = max(210, min(260 if compact else 320, int(width * 0.29)))
        if self.info_area.preferred_width != info_width:
            self.info_area.preferred_width = info_width
            self.info_area.updateGeometry()
        if self.info_area.maximumWidth() != info_width:
            self.info_area.setMaximumWidth(info_width)
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        self.transport_layout.setSpacing(4 if compact else 8)
        for widget in (self.info_area, self.center_area, self.extra_area, self.slider_area):
            self.main_layout.removeWidget(widget)
        self.center_layout.removeWidget(self.slider_area)
        if compact:
            self.main_layout.addWidget(self.info_area, 0, 0, 2, 1)
            self.main_layout.addWidget(self.slider_area, 0, 1, 1, 2)
            self.main_layout.addWidget(self.center_area, 1, 1)
            self.main_layout.addWidget(self.extra_area, 1, 2)
        else:
            self.center_layout.insertWidget(0, self.slider_area)
            self.main_layout.addWidget(self.info_area, 0, 0)
            self.main_layout.addWidget(self.center_area, 0, 1)
            self.main_layout.addWidget(self.extra_area, 0, 2)
        self.slider_area.show()

        
        # --- HÀM HỖ TRỢ XỬ LÝ CLICK ---
    def eventFilter(self, watched, event):
        # Kiểm tra nếu click vào vùng info_area hoặc bất kỳ con nào của nó
        if watched == self.info_area and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self.video_clicked.emit()
                return True # Đã xử lý xong sự kiện
        return super().eventFilter(watched, event)

    def format_time(self, ms):
        s = ms // 1000
        m, s = divmod(s, 60)
        return f"{m:02d}:{s:02d}"

    def _on_slider_moved(self, value):
        if self.time_slider.isSliderDown():
            self.lbl_current_time.setText(self.format_time(value))

    def update_play_state(self, is_playing):
        button_icon(self.btn_play, "pause" if is_playing else "play", color=INK)
        self.btn_play.setToolTip("Tạm dừng" if is_playing else "Phát")

    def update_position(self, ms, time_str):
        if not self.time_slider.isSliderDown():
            self.time_slider.blockSignals(True)
            self.time_slider.setValue(ms)
            self.time_slider.blockSignals(False)
            self.lbl_current_time.setText(time_str)

    def update_duration(self, ms, time_str):
        self.time_slider.setRange(0, ms)
        self.lbl_total_time.setText(time_str)

    def set_media_info(self, title, artist="",item_data=None):
        # Code này giờ sẽ chạy tốt vì self.lbl_song_info ĐÃ CÓ
        if not hasattr(self, 'lbl_song_info'):
            return
        self._current_item_data = item_data
        self.mini_video_dock.prepare_media()
        display_title = title
        if len(display_title) > 40:
            display_title = display_title[:37] + "..."

        if artist is None: 
            artist = "Unknown Artist"

        formatted_text = f"""
            <div style='line-height: 120%;'>
                <span style='font-size: 14px; font-weight: bold; color: white;'>{display_title}</span><br>
                <span style='font-size: 11px; color: #b3b3b3;'>{artist}</span>
            </div>
        """
        self.lbl_song_info.setText(formatted_text)
        self.lbl_song_info.setToolTip(f"{title}\nNghệ sĩ: {artist}")
        
        # 🔥 KHI CÓ VIDEO -> BẬT NÚT RELOAD & FULLSCREEN
        self.btn_reload.setEnabled(True)
        main_win = self.window()
        if main_win and hasattr(main_win, 'media_manager') and getattr(main_win.media_manager, 'enabled', False):
            # Lấy biến title và artist sẵn có trong hàm của bác đẩy lên hệ thống
            main_win.media_manager.update_metadata(title, artist)
            main_win.media_manager.set_playing(True)
    
    # Thêm vào class PlaybackBar
    def set_mini_video_visible(self, visible):
        """Ẩn/Hiện khung chứa video nhỏ (Phiên bản Fix lỗi cứng đầu)"""
        print(f"DEBUG: Gọi lệnh ẩn/hiện video nhỏ: {visible}")
        
        if visible:
            # Khi hiện: Trả lại kích thước cũ và hiện lên
            self.video_mini_placeholder.setFixedSize(140, 80)
            self.video_mini_placeholder.show()
        else:
            # Khi ẩn: Ẩn đi VÀ ép kích thước về 0 để layout co lại
            self.video_mini_placeholder.hide()
            self.video_mini_placeholder.setFixedSize(0, 0)
            
        # Buộc layout cập nhật ngay lập tức
        self.info_area.updateGeometry()

    def set_shuffle_visual(self, is_active):
        """Đổi màu nút Shuffle dựa trên trạng thái từ MainWindow"""
        button_icon(self.btn_shuffle, "shuffle", color=ACCENT if is_active else TEXT)
        self.btn_shuffle.setToolTip("Phát ngẫu nhiên: bật" if is_active else "Phát ngẫu nhiên: tắt")

    def update_volume_icon(self, volume):
        name = "volume-x" if volume == 0 else "volume-1" if volume < 0.5 else "volume-2"
        button_icon(self.btn_vol, name)

    def update_fullscreen_icon(self, fullscreen):
        button_icon(self.btn_fs, "minimize" if fullscreen else "maximize")
        self.btn_fs.setToolTip("Thoát toàn màn hình" if fullscreen else "Toàn màn hình")
            
    def show_video_info_popup(self):
        """Hàm test luồng click nút (i)"""
        print("➔ [TEST CLIENT]: Đã click vào nút ⓘ thành công!")
        
        if hasattr(self, '_current_item_data'):
            print(f"➔ [TEST DATA]: Dữ liệu bài hát hiện tại = {self._current_item_data}")
            if self._current_item_data:
                self.info_popup.update_info(self._current_item_data)
                print("➔ [TEST POPUP]: Đang ra lệnh .show() cho Popup...")
                self.info_popup.show_above_widget(self)
            else:
                print("⚠️ [TEST WARNING]: Click được nhưng _current_item_data đang bị rỗng (None)!")
        else:
            print("⚠️ [TEST ERROR]: Khuyết thiếu thuộc tính _current_item_data!")
