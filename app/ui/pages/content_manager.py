import random
from PySide6.QtCore import QTimer

# Định nghĩa hằng số cho dễ quản lý
PAGE_HOME = 0
PAGE_FORYOU = 1
PAGE_LIBRARY = 2
PAGE_DOWNLOAD = 3  # Tạm dùng Library làm Download
PAGE_SETTINGS = 4

class ContentController:
    def __init__(self, main_window):
        self.main = main_window 

    # --- HELPER METHODS (Hàm phụ trợ) ---
    def _has_data(self):
        """Kiểm tra xem có dữ liệu media không"""
        return hasattr(self.main, 'all_media_items') and self.main.all_media_items

    def _set_video_mode(self, mode):
        """Tự động chọn hàm đổi chế độ video (mini/normal) tùy theo main window có hàm nào"""
        if hasattr(self.main, 'manage_video_state'):
            self.main.manage_video_state(mode)
        elif hasattr(self.main, 'update_video_location'):
            self.main.update_video_location(mode)

    # --- MAIN LOGIC ---
    def set_new_data(self, media_items):
        self.main.all_media_items = media_items
        self.switch_to_home()

    def switch_to_home(self):
        if not self._has_data(): return
        
        # 1. Chuyển Tab & State
        self.main.content_stack.setCurrentIndex(PAGE_HOME)
        self._set_video_mode("mini")
            
        # 2. Load nội dung Home (Random 20 bài)
        sample_size = min(len(self.main.all_media_items), 20)
        items = random.sample(self.main.all_media_items, sample_size)
        self.main.update_media_grid(items)
        
    def switch_to_library(self):
        if not self._has_data(): return
        
        # 1. Chuyển Tab & State
        self.main.content_stack.setCurrentIndex(PAGE_LIBRARY)
        self._set_video_mode("mini")

        # 2. UI cụ thể của Library
        if hasattr(self.main, 'top_toolbar_container'):
            self.main.top_toolbar_container.show()
            
        # 3. Load toàn bộ item
        self.main.update_media_grid(self.main.all_media_items)

    def switch_to_foryou(self):
        if not self._has_data(): return

        # [FIX 1] Reset sạch Subtitle trước khi chuyển
        # Để nó không bị "vương vấn" tọa độ cũ bên Large/Home
        if hasattr(self.main, 'sub_layer') and self.main.sub_layer:
            self.main.sub_layer.hide() # Ẩn đi cho đỡ bị giật hình
            if hasattr(self.main.sub_layer, 'reset_anchor_state'):
                self.main.sub_layer.reset_anchor_state()

        # 1. Chuyển trang
        self.main.content_stack.setCurrentIndex(PAGE_FORYOU)

        # 2. Chuyển chế độ Normal
        # [FIX 2] Tăng Timer lên 1 chút hoặc dùng Nested Timer để đảm bảo UI vẽ xong
        def safe_switch():
            self._set_video_mode("normal")
            # Sau khi set mode xong, đợi thêm 1 xíu để window maximize hẳn rồi mới hiện sub
            if hasattr(self.main, 'foryou_page'):
                QTimer.singleShot(150, self.main.foryou_page.video_container.update_layout)

        QTimer.singleShot(50, safe_switch)

        # 3. Logic Playlist (Giữ nguyên)
        foryou = self.main.foryou_page
        if foryou.all_items_data:
            self.main.active_playlist = list(foryou.all_items_data)
            # Highlight bài hát đang phát (nếu có)
            if hasattr(self.main, 'current_media_item') and self.main.current_media_item:
                def highlight_current():
                    foryou.mark_playing_item(self.main.current_media_item.id)
                QTimer.singleShot(200, highlight_current)
            return

        sorted_items = sorted(
            self.main.all_media_items,
            key=lambda x: getattr(x, 'mtime', 0) or 0,
            reverse=True
        )
        foryou.load_playlist(sorted_items)
        self.main.active_playlist = sorted_items
        
        # Highlight bài hát đang phát (nếu có)
        if hasattr(self.main, 'current_media_item') and self.main.current_media_item:
            def highlight_current():
                foryou.mark_playing_item(self.main.current_media_item.id)
            QTimer.singleShot(200, highlight_current)

    def switch_to_download(self):
        """Chuyển tới trang Download - Hiện thanh playback bar ở chế độ mini"""
        # 1. Chuyển Tab
        self.main.content_stack.setCurrentIndex(PAGE_DOWNLOAD)
        
        # 2. Set chế độ mini để playback bar hiển thị
        self._set_video_mode("mini")
    
    def switch_to_settings(self):
        """Chuyển tới trang Settings - Chỉ hiện thanh playback bar"""
        # 1. Chuyển Tab
        self.main.content_stack.setCurrentIndex(PAGE_SETTINGS)
        
        # 2. Set chế độ mini để playback bar hiển thị
        self._set_video_mode("mini")