import json
import logging
import os
import sys
import time
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict, replace
from typing import Optional, List, Dict, Tuple

# Giả sử class SubtitleManager của bạn nằm ở đây
from core.subtitle_manager import SubtitleManager

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".mp3", ".mp4", ".mkv", ".wav", ".mov", ".avi"}

# ============================================================
# 1. HÀM HỖ TRỢ LẤY METADATA (FFPROBE)
# ============================================================
def get_raw_metadata(file_path: str) -> Tuple[str, str, float]:
    """
    Trả về (title, artist, duration) dùng ffprobe.
    Nếu không có, trả về (filename, 'Unknown Artist', 0)
    """
    default_title = Path(file_path).stem
    default_artist = "Unknown Artist"
    
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json', 
            '-show_format', '-show_streams', file_path
        ]
        # 🔥 FIX: Ẩn cửa sổ Console trên Windows
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        # Timeout 3s để tránh treo app nếu file lỗi
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=3, startupinfo=startupinfo)
        data = json.loads(result.stdout)
        
        # 1. Lấy Tags
        tags = data.get('format', {}).get('tags', {})
        
        # Title
        title = tags.get('title') or tags.get('TITLE')
        if not title:
            title = default_title
            
        # Artist
        artist = tags.get('artist') or tags.get('ARTIST')
        if not artist and " - " in title: # Thử tách tên nếu có dạng "Title - Artist"
             parts = title.split(" - ")
             if len(parts) >= 2:
                 title = parts[0].strip()
                 artist = parts[1].strip()
        
        if not artist:
            artist = default_artist

        # Duration
        raw_dur = data.get('format', {}).get('duration', '0')
        try:
            duration = float(raw_dur)
        except (ValueError, TypeError):
            duration = 0.0  # Fallback nếu gặp "N/A"

        return title, artist, duration

    except Exception as e:
        logger.error(f"⚠️ Lỗi đọc meta {Path(file_path).name}: {e}")
        return default_title, default_artist, 0.0


# ============================================================
# 2. DATA MODEL (Thêm artist)
# ============================================================
@dataclass
class MediaMetadata:
    id: str
    path: str
    title: str
    artist: str = "Unknown Artist"
    thumbnail: Optional[str] = None
    duration: float = 0
    mtime: Optional[float] = None


# ============================================================
# 3. MEDIA LIBRARY (Nâng cấp Logic Scan)
# ============================================================
class MediaLibrary:
    def __init__(self, db_path: str = "storage/library_cache.json"):
        self.db_path = Path(db_path)
        self.items: Dict[str, MediaMetadata] = {}
        self.subtitle_mgr = SubtitleManager()
        self.lock = threading.RLock()
        self._save_lock = threading.Lock()
        self.load()
        logger.info("✅ MediaLibrary initialized")

    def scan_folder(self, folder_path: str) -> List[MediaMetadata]:
        folder = Path(folder_path)
        if not folder.exists():
            return []

        new_items_in_scan: List[MediaMetadata] = []

        logger.info(f"📂 Đang quét: {folder_path}")

        count_cache = 0
        count_scan = 0
        
        for file in folder.rglob('*'):
            if getattr(self, '_cancel_scan', lambda: False)():
                break
            if not file.is_file(): continue
            if file.suffix.lower() in {'.part', '.ytdl', '.tmp', '.temp'}:
                continue
            if file.suffix.lower() not in SUPPORTED_EXTS: continue

            # Lấy ID ổn định (Hash hoặc Inode)
            media_id = self.subtitle_mgr.get_reliable_id(file)
            if not media_id: continue

            abs_path = str(file.resolve())
            stat = file.stat()

            # --- LOGIC QUAN TRỌNG ---
            if media_id in self.items:
                # A. File ĐÃ CÓ trong DB
                # Chỉ update đường dẫn (đề phòng di chuyển file) và mtime
                # KHÔNG chạy ffprobe lại để giữ tốc độ cao
                count_cache += 1
                meta = self.items[media_id]
                meta.path = abs_path
                meta.mtime = stat.st_mtime
                # Nếu trước đó chưa có duration, thì mới quét lại
                if meta.duration == 0:
                     t, a, d = get_raw_metadata(abs_path)
                     meta.duration = d
                     # Có thể cập nhật title/artist nếu muốn, hoặc giữ nguyên edit của user
            else:
                # B. File MỚI HOÀN TOÀN
                # Chạy FFprobe để lấy Title/Artist chuẩn ngay từ đầu
                count_scan += 1
                logger.debug(f"🔍 Phân tích file mới: {file.name}")
                raw_title, raw_artist, raw_duration = get_raw_metadata(abs_path)

                meta = MediaMetadata(
                    id=media_id,
                    path=abs_path,
                    title=raw_title,   # Tên chuẩn lấy từ file
                    artist=raw_artist, # Tên ca sĩ chuẩn
                    duration=raw_duration,
                    mtime=stat.st_mtime,
                    thumbnail=None
                )
                self.items[media_id] = meta
            
            new_items_in_scan.append(meta)

        self.save()
        print(f"-"*30)
        print(f"📊 KẾT QUẢ QUÉT: {folder_path}")
        print(f"✅ Lấy từ Cache: {count_cache} file (Siêu tốc)")
        print(f"🐌 Quét mới:     {count_scan} file (Chậm)")
        print(f"-"*30)
        return new_items_in_scan

    def update_thumbnail_in_db(self, media_id, thumb_path):
        """Worker gọi hàm này khi tạo xong ảnh để lưu vào JSON"""
        with self.lock:
            if media_id not in self.items:
                return
            self.items[media_id].thumbnail = thumb_path
        self.save()
        logger.info(f"💾 Đã lưu path thumbnail cho {media_id}")

    def cleanup(self):
        """
        Xóa các mục trong DB mà file thực tế không còn tồn tại.
        Nên gọi hàm này khi khởi động App hoặc định kỳ.
        """
        removed_count = 0
        ids_to_remove = []
        
        for mid, meta in self.items.items():
            if not Path(meta.path).exists():
                ids_to_remove.append(mid)
        
        for mid in ids_to_remove:
            del self.items[mid]
            removed_count += 1
            
        if removed_count > 0:
            logger.info(f"🧹 Đã dọn dẹp {removed_count} file rác khỏi thư viện.")
            self.save()

    def stage_thumbnail_in_db(self, media_id, thumb_path):
        """RAM update for the owned batch worker; the synchronous API stays intact."""
        with self.lock:
            item = self.items.get(media_id)
            if item is None or item.thumbnail == thumb_path:
                return False
            item.thumbnail = thumb_path
            return True

    def save(self):
        """
        Lưu file JSON với cơ chế chống lỗi WinError 5 (Access Denied)
        """
        # 1. Dùng Lock để đảm bảo chỉ 1 luồng được ghi file tại 1 thời điểm
        with self._save_lock:
            self._last_save_succeeded = False
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Convert data sang dict
                with self.lock:
                    snapshot = [(mid, replace(meta)) for mid, meta in self.items.items()]
                data = {mid: asdict(meta) for mid, meta in snapshot}
                
                temp_path = self.db_path.with_suffix(".tmp")
                
                # Ghi vào file tạm trước
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                # 2. Cơ chế Retry (Thử lại) khi replace file
                # Windows đôi khi khóa file trong vài mili-giây, ta cần kiên nhẫn
                max_retries = 5
                for i in range(max_retries):
                    try:
                        # Thử thay thế file cũ bằng file mới
                        temp_path.replace(self.db_path)
                        # Nếu thành công thì thoát vòng lặp
                        break 
                    except PermissionError:
                        # Nếu lỗi Access Denied
                        if i < max_retries - 1:
                            # Chờ 0.1 giây rồi thử lại
                            time.sleep(0.1) 
                        else:
                            # Nếu thử 5 lần vẫn ko được thì báo lỗi thật
                            logger.error(f"❌ Không thể ghi đè file DB sau {max_retries} lần thử.")
                            # Xóa file tạm cho đỡ rác
                            if temp_path.exists():
                                os.remove(temp_path)
                            raise
                self._last_save_succeeded = True
                            
            except Exception as e:
                logger.error(f"❌ Save library failed: {e}")

    def load(self):
        if not self.db_path.exists(): return
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Cẩn thận: Nếu JSON cũ không có field 'artist', code sẽ crash
            # Nên dùng .get hoặc **kwargs để an toàn
            for mid, info in data.items():
                # Fix lỗi thiếu field khi update phiên bản mới
                if 'artist' not in info: info['artist'] = "Unknown Artist"
                self.items[mid] = MediaMetadata(**info)
        except Exception as e:
            logger.error(f"❌ Load library failed: {e}")
