import json
import os
import logging
from pathlib import Path
from dataclasses import asdict, is_dataclass
from subtitle.model import Subtitle, SubtitleLine, SubtitleStyle
from paths import storage_dir

logger = logging.getLogger(__name__)

# --- PHẦN 1: QUẢN LÝ DỮ LIỆU PHỤ ĐỀ (JSON DATA) ---

def save_subtitles(subs, path):
    """Lưu danh sách phụ đề xuống file JSON một cách an toàn"""
    def custom_serialize(obj):
        if is_dataclass(obj):
            return asdict(obj)
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return obj

    try:
        # Đảm bảo thư mục tồn tại
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        data = []
        for s in subs:
            # Nếu là dict (đã qua xử lý dịch thuật)
            if isinstance(s, dict):
                data.append(s)
                continue
            
            # Nếu là Object Subtitle chuẩn
            item = {
                "start": getattr(s, 'start', 0),
                "end": getattr(s, 'end', 0),
                "top": custom_serialize(s.top) if getattr(s, 'top', None) else None,
                "bottom": custom_serialize(s.bottom) if getattr(s, 'bottom', None) else None
            }
            data.append(item)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Đã lưu thành công {len(data)} dòng phụ đề vào: {path}")
        return True
    except Exception as e:
        logger.error(f"❌ Lỗi khi save_subtitles: {e}")
        return False

def load_subtitles(path):
    """Tải và phục hồi Object Subtitle từ JSON"""
    path = Path(path)
    if not path.exists():
        return []
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        subs = []
        for item in data:
            sub = Subtitle(start=item.get("start", 0), end=item.get("end", 0))
            
            # Khôi phục phần Top (Nhật)
            if item.get("top"):
                t_data = item["top"]
                style_data = t_data.pop("style", {})
                sub.top = SubtitleLine(**t_data, style=SubtitleStyle(**style_data))
            
            # Khôi phục phần Bottom (Việt/Anh)
            if item.get("bottom"):
                b_data = item["bottom"]
                style_data = b_data.pop("style", {})
                sub.bottom = SubtitleLine(**b_data, style=SubtitleStyle(**style_data))
                
            subs.append(sub)
        return subs
    except Exception as e:
        logger.error(f"❌ Lỗi khi load_subtitles: {e}")
        return []


# --- PHẦN 2: QUẢN LÝ PROFILE (CẤU HÌNH GIAO DIỆN) ---

class SubtitleProfile:
    def __init__(self):
        # Tách biệt thư mục Profile để không đè vào file Data
        self.storage_dir = storage_dir() / "subtitle_profiles"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, video_path):
        """Tạo đường dẫn file config riêng biệt: video_name.profile.json"""
        if not video_path:
            return None
        video_name = Path(video_path).stem
        return self.storage_dir / f"{video_name}.profile.json"

    def save(self, video_path, mode, font_size, color):
        """Lưu cấu hình hiển thị của người dùng"""
        path = self._get_path(video_path)
        if not path: return

        data = {
            "mode": mode.value if hasattr(mode, 'value') else mode,
            "font_size": font_size,
            "color": color,
            "last_updated": os.path.getmtime(video_path) if os.path.exists(video_path) else 0
        }
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"❌ Lỗi khi lưu profile: {e}")

    def load(self, video_path):
        """Tải cấu hình hiển thị"""
        path = self._get_path(video_path)
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ Lỗi khi đọc profile: {e}")
        return None