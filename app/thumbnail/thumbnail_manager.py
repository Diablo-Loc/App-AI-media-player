import os
import subprocess
import sys
from pathlib import Path

# Cấu hình đường dẫn Cache
CACHE_DIR = Path("data/thumbnails")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class ThumbnailManager:
    @staticmethod
    def get_thumbnail(media_item):
        """
        Quy trình tạo Thumbnail chuẩn High-End:
        1. Tìm Cache -> Có thì trả về ngay.
        2. Thử trích xuất Embedded Cover Art (Ưu tiên số 1).
        3. Nếu không có -> Chụp Frame tại giây 15 (Tránh intro đen).
        4. Nếu video quá ngắn -> Chụp Frame tại giây 1.
        """
        
        # 1. Kiểm tra đầu vào
        video_path = getattr(media_item, 'path', None)
        video_id = str(media_item.id)
        
        if not video_path or not os.path.exists(video_path):
            return None

        # Đường dẫn file ảnh đầu ra
        thumb_filename = f"{video_id}.jpg"
        thumb_path = CACHE_DIR / thumb_filename
        str_thumb_path = str(thumb_path)

        # ✅ CACHE HIT: Nếu ảnh đã tồn tại và hợp lệ (>0KB)
        if thumb_path.exists() and thumb_path.stat().st_size > 0:
            return str_thumb_path

        # 🔥 Cấu hình ẩn Console trên Windows (tránh nháy đen)
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # =========================================================
        # 💎 BƯỚC 1: TRÍCH XUẤT COVER ART (EMBEDDED)
        # =========================================================
        # File nhạc (MP3, FLAC) hoặc MKV/MP4 xịn thường có ảnh bìa chất lượng cao.
        try:
            cmd_extract = [
                'ffmpeg', '-y', 
                '-i', str(video_path),
                '-map', '0:v',        # Chọn tất cả luồng video
                '-map', '-0:V',       # TRỪ luồng video chính (chỉ giữ lại ảnh đính kèm)
                '-c:v', 'mjpeg',      # ⚠️ QUAN TRỌNG: Convert sang JPG (Fix lỗi nguồn là PNG)
                '-q:v', '2',          # Chất lượng cao nhất (2-31, nhỏ hơn là tốt hơn)
                '-f', 'image2',       
                str_thumb_path
            ]
            
            subprocess.run(
                cmd_extract, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL, 
                startupinfo=startupinfo,
                timeout=3 # Timeout ngắn vì copy rất nhanh
            )

            # Kiểm tra: Nếu file tạo ra ok thì trả về luôn
            if ThumbnailManager._is_valid_image(thumb_path):
                return str_thumb_path
            
            # Dọn dẹp file rác 0KB nếu thất bại
            if thumb_path.exists(): os.remove(thumb_path)

        except Exception:
            pass # Lỗi thì bỏ qua, sang bước chụp màn hình

        # =========================================================
        # 📸 BƯỚC 2: SMART CAPTURE (CHỤP MÀN HÌNH)
        # =========================================================
        
        # Chiến thuật: Thử chụp ở giây 15 (né Intro), nếu thất bại (video ngắn) chụp giây 1
        timestamps = ["00:00:15", "00:00:01"]
        
        for time_offset in timestamps:
            success = ThumbnailManager._capture_frame(
                video_path, str_thumb_path, time_offset, startupinfo
            )
            if success:
                return str_thumb_path

        # Nếu tất cả đều thất bại
        return None

    @staticmethod
    def _capture_frame(video_path, output_path, time_offset, startupinfo):
        """Hàm chụp ảnh màn hình với chất lượng cao"""
        try:
            cmd = [
                'ffmpeg', '-y',
                '-ss', time_offset,      # 🔥 Đặt trước -i để tua cực nhanh (Fast Seek)
                '-i', str(video_path),
                '-vframes', '1',         # Chỉ lấy 1 khung hình
                
                # 🔥 CẤU HÌNH CHẤT LƯỢNG CAO 🔥
                # 1. Scale 800px: Đủ nét cho màn hình Retina/4K khi hiển thị card nhỏ
                # 2. flags=lanczos: Thuật toán resize xịn nhất, nét hơn bicubic mặc định
                '-vf', 'scale=800:-1:flags=lanczos', 
                
                # 3. q:v 2: Chất lượng JPG gần như Lossless (không vỡ hạt)
                '-q:v', '2',             
                
                output_path
            ]
            
            subprocess.run(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL, 
                startupinfo=startupinfo,
                timeout=10 
            )
            
            return ThumbnailManager._is_valid_image(Path(output_path))
        except Exception:
            return False

    @staticmethod
    def _is_valid_image(path: Path):
        """Kiểm tra file có tồn tại và có dữ liệu không"""
        return path.exists() and path.stat().st_size > 1000 # Lớn hơn 1KB mới tính là ảnh