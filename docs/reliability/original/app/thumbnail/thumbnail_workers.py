import os
from PySide6.QtCore import QThread, Signal
from thumbnail.thumbnail_manager import ThumbnailManager

class ThumbnailWorker(QThread):
    # Signal trả về: (ID_video, Đường_dẫn_ảnh)
    thumbnail_ready = Signal(str, str) 

    def __init__(self, media_library):
        super().__init__()
        self.library = media_library # 🔥 Cần giữ tham chiếu tới Library để gọi hàm Save
        
        # Lấy danh sách items từ library (chuyển dict values thành list)
        self.queue = list(media_library.items.values())
        self.is_running = True

    def run(self):
        for item in self.queue:
            if not self.is_running: break
            
            # 1. TỐI ƯU: Nếu trong Metadata đã có đường dẫn & file tồn tại -> Emit luôn
            # (Không cần gọi Manager làm gì cho tốn hàm)
            if item.thumbnail and os.path.exists(item.thumbnail):
                self.thumbnail_ready.emit(item.id, item.thumbnail)
                continue

            # 2. Nếu chưa có -> Gọi Manager để tìm/tạo ảnh
            # (Hàm này đã tối ưu: check file cache trước, nếu không có mới chạy FFmpeg)
            thumb_path = ThumbnailManager.get_thumbnail(item)
            
            if thumb_path:
                # 3. 🔥 QUAN TRỌNG: Lưu ngược đường dẫn vào Database (JSON)
                # Để lần sau mở App lên là load ngay lập tức
                self.library.update_thumbnail_in_db(item.id, thumb_path)

                # 4. Gửi tín hiệu để UI hiển thị
                self.thumbnail_ready.emit(item.id, thumb_path)
                
            # Nghỉ xíu để CPU không bị overload (20ms là đẹp)
            self.msleep(20)

    def stop(self):
        self.is_running = False
        try:
            self.wait(1000)
        except Exception:
            pass
        self.queue = []