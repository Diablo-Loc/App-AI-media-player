from PySide6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QLabel, 
                             QPushButton, QSlider, QWidget,QSizePolicy)
from PySide6.QtCore import Qt, Signal, QEvent, QSize
from .video_info_popup import VideoInfoPopup

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
        # 1. ĐÃ XÓA 'cursor: pointer;' TRONG CSS (Vì Qt không hỗ trợ thuộc tính này trong QSS)
        self.setStyleSheet("""
            #playbackBar { background-color: #121212; border-top: 1px solid #282828; }
            #infoPanel { background-color: transparent; border-radius: 8px; }
            #infoPanel:hover { background-color: #282828; }
            QLabel { color: #b3b3b3; font-size: 12px; }
            #songTitle { color: white; font-weight: bold; font-size: 14px; }
            QPushButton { background: transparent; color: white; border: none; font-size: 18px; }
            QPushButton:hover { color: #1DB954; }
            
            /* Style cho nút bị Disable (Mờ đi) */
            QPushButton:disabled { color: #404040; }

            #playButton { 
                background-color: white; 
                color: black; 
                border-radius: 20px; 
                font-size: 16px;
            }
            #playButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.info_popup = VideoInfoPopup(None)
        self._current_item_data = None # Biến lưu data bài hát hiện tại
        
    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(15, 5, 15, 5)
        self.main_layout.setSpacing(5)

        # --- CỤM 1: THÔNG TIN (Sát trái) ---
        self.info_area = QFrame()
        self.info_area.setObjectName("infoPanel")
        self.info_area.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_area.setMouseTracking(True)
        self.info_area.installEventFilter(self)
        self.info_area.setFixedWidth(300)
        
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
        text_info_layout = QVBoxLayout(text_info_widget)
        text_info_layout.setContentsMargins(0, 5, 0, 5)
        
        self.lbl_song_info = QLabel()
        self.lbl_song_info.setObjectName("songTitle")
        self.lbl_song_info.setTextFormat(Qt.TextFormat.RichText) # Cho phép hiện HTML
        self.lbl_song_info.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
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
        center_area = QWidget()
        center_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        center_layout = QVBoxLayout(center_area)
        center_layout.setSpacing(3)
        
        # Slider nằm trên (Giống ảnh mẫu)
        slider_layout = QHBoxLayout()
        self.lbl_current_time = QLabel("00:00")
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_total_time = QLabel("00:00")
        
        slider_layout.addWidget(self.lbl_current_time)
        slider_layout.addWidget(self.time_slider)
        slider_layout.addWidget(self.lbl_total_time)
        slider_layout.setAlignment(Qt.AlignmentFlag.AlignCenter) # Căn giữa slider

        # Nút bấm nằm dưới
        btns_layout = QHBoxLayout()
        self.btn_shuffle = QPushButton("🔀")
        self.btn_prev = QPushButton("⏮")
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(40, 40)
        self.btn_play.setObjectName("playButton")
        self.btn_next = QPushButton("⏭")
        self.btn_repeat = QPushButton("🔁")

        for btn in [self.btn_shuffle, self.btn_prev, self.btn_play, self.btn_next, self.btn_repeat]:
            btns_layout.addWidget(btn)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        btns_layout.setAlignment(Qt.AlignmentFlag.AlignCenter) # Căn giữa các nút

        center_layout.addLayout(slider_layout)
        center_layout.addLayout(btns_layout)

        # --- CỤM 3: TIỆN ÍCH (Sát phải) ---
        extra_area = QWidget()
        extra_layout = QHBoxLayout(extra_area)
        extra_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        extra_area.setFixedWidth(310)
        
        #0. Nút Mở Popup Info
        self.btn_info = QPushButton("ℹ️")
        self.btn_info.setFixedSize(32, 32)
        self.btn_info.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_info.setToolTip("Thong tin chi tiết bài hát")
        self.btn_info.setStyleSheet("QPushButton { border: none; font-size: 16px; color: #b3b3b3; } QPushButton:hover { color: white; }")
        
        # 1. Nút Cài đặt Sub
        self.btn_subseting = QPushButton("⚙️")
        self.btn_subseting.setFixedSize(32, 32)
        self.btn_subseting.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_subseting.setToolTip("Cài đặt phụ đề")
        self.btn_subseting.setStyleSheet("QPushButton { border: none; font-size: 16px; color: #b3b3b3; } QPushButton:hover { color: white; }")
        
        # 1. NÚT CÔNG CỤ PHỤ ĐỀ / BẢNG ĐEN (Subtitle Tools)
        self.btn_sub = QPushButton("📝")
        self.btn_sub.setFixedSize(32, 32)
        self.btn_sub.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sub.setToolTip("Công cụ khớp & chỉnh sửa phụ đề (Subtitle Tools)")
        self.btn_sub.setStyleSheet("QPushButton { border: none; font-size: 16px; color: #b3b3b3; } QPushButton:hover { color: white; }")
        
        # 2. NÚT RELOAD
        self.btn_reload = QPushButton("🔄")
        self.btn_reload.setFixedSize(32, 32)
        self.btn_reload.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reload.setToolTip("Tạo lại phụ đề (AI Force)")
        self.btn_reload.setStyleSheet("QPushButton { border: none; font-size: 16px; color: #b3b3b3; } QPushButton:hover { color: white; }")
        self.btn_reload.setEnabled(False)
        
        # 3. Nút Loa
        self.btn_vol = QPushButton("🔊")
        self.btn_vol.setFixedSize(32, 32)
        self.btn_vol.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_vol.setStyleSheet("QPushButton { border: none; font-size: 18px; color: #b3b3b3; } QPushButton:hover { color: white; }")
        
        # 3.5. Nút mở chế độ dynamic island
        self.btn_dynamic_island = QPushButton("🍬")
        self.btn_dynamic_island.setFixedSize(32, 32)
        self.btn_dynamic_island.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dynamic_island.setToolTip("Chế độ mini player")
        self.btn_dynamic_island.setStyleSheet("QPushButton { border: none; font-size: 16px; color: #b3b3b3; } QPushButton:hover { color: white; }")
        
        # 4. Nút Fullscreen
        self.btn_fs = QPushButton("⤢")
        
        extra_layout.addWidget(self.btn_info)
        extra_layout.addWidget(self.btn_subseting)
        extra_layout.addWidget(self.btn_sub)
        extra_layout.addWidget(self.btn_reload)
        extra_layout.addWidget(self.btn_vol)
        extra_layout.addWidget(self.btn_dynamic_island)
        extra_layout.addWidget(self.btn_fs)
        extra_layout.setSpacing(4)
        
        # --- THÊM VÀO LAYOUT CHÍNH THEO TỈ LỆ 3:4:3 ---
        self.main_layout.addWidget(self.info_area, 3)
        self.main_layout.addWidget(center_area, 4)
        self.main_layout.addWidget(extra_area, 3)

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
    
    def set_shuffle_visual(self, is_active):
        """Cập nhật màu nút shuffle dựa trên trạng thái"""
        if is_active:
            self.btn_shuffle.setStyleSheet("QPushButton { background: transparent; color: #3ea6ff; border: none; font-size: 18px; } QPushButton:hover { color: #1DB954; }")
        else:
            self.btn_shuffle.setStyleSheet("QPushButton { background: transparent; color: white; border: none; font-size: 18px; } QPushButton:hover { color: #1DB954; }")
        
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
        self.btn_play.setText("⏸" if is_playing else "▶")
        self.btn_play.setStyleSheet("background-color: #1DB954;" if is_playing else "background-color: white;")

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
        if is_active:
            # Màu xanh (Active)
            self.btn_shuffle.setStyleSheet("color: #3ea6ff; font-size: 18px; border: none; background: transparent;")
        else:
            # Màu trắng (Inactive)
            self.btn_shuffle.setStyleSheet("color: white; font-size: 18px; border: none; background: transparent;")
            
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