import json
import logging
import os
from pathlib import Path
from dataclasses import asdict, is_dataclass
from subtitle.model import Subtitle, SubtitleLine, SubtitleStyle

# Cấu hình logger để truy vết nguyên nhân file rỗng
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SubtitleStorage")

def save_subtitles(subs, path):
    """
    Lưu danh sách phụ đề xuống file JSON.
    Cảnh báo nếu danh sách rỗng để debug.
    """
    if not subs:
        logger.warning(f"⚠️ CẢNH BÁO: Danh sách 'subs' rỗng! File tại {path} sẽ không có dữ liệu thoại.")
    
    def custom_serialize(obj):
        if is_dataclass(obj):
            return asdict(obj)
        return obj

    try:
        # Đảm bảo thư mục tồn tại
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = []
        for i, s in enumerate(subs):
            # Kiểm tra xem từng object có thực sự chứa nội dung không
            if not s.top and not s.bottom:
                logger.debug(f"Dòng thứ {i} (Time: {s.start}) không có cả nội dung Top lẫn Bottom.")

            item = {
                "start": getattr(s, 'start', 0),
                "end": getattr(s, 'end', 0),
                "top": custom_serialize(s.top) if s.top else None,
                "bottom": custom_serialize(s.bottom) if s.bottom else None,
            }
            data.append(item)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Đã lưu {len(data)} dòng vào: {path}")
        return True
    except Exception as e:
        logger.error(f"❌ Lỗi khi ghi file JSON: {e}", exc_info=True)
        return False

def load_subtitles(path):
    """
    Tải và phục hồi Object Subtitle từ JSON một cách an toàn.
    """
    path = Path(path)
    if not path.exists():
        logger.error(f"❌ File không tồn tại: {path}")
        return []
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data:
            logger.warning(f"⚠️ File JSON {path} tồn tại nhưng danh sách bên trong rỗng.")
            return []

        subs = []
        for item in data:
            sub = Subtitle(start=item.get("start", 0), end=item.get("end", 0))
            
            # Khôi phục an toàn cho Top và Bottom
            for side in ["top", "bottom"]:
                side_data = item.get(side)
                if side_data:
                    # Dùng .get() để tránh lỗi KeyError nếu file JSON thiếu field
                    # Copy dict để không làm hỏng dữ liệu gốc khi dùng .pop()
                    raw_data = side_data.copy()
                    style_data = raw_data.pop("style", {})
                    
                    style = SubtitleStyle(
                        font=style_data.get("font", "Arial"),
                        size=style_data.get("size", 20),
                        pos=tuple(style_data.get("pos", (960, 900))),
                        color=style_data.get("color", "&H00FFFFFF"),
                        alignment=style_data.get("alignment", 2),
                        margin_v=style_data.get("margin_v", 40)
                    )
                    
                    line = SubtitleLine(
                        text=raw_data.get("text", ""),
                        lang=raw_data.get("lang", ""),
                        style=style
                    )
                    setattr(sub, side, line)
            
            subs.append(sub)
            
        logger.info(f"📖 Đã load thành công {len(subs)} dòng từ JSON.")
        return subs
    except Exception as e:
        logger.error(f"❌ Lỗi khi giải mã file JSON: {e}", exc_info=True)
        return []

class SubtitleProfile:
    """Quản lý cấu hình hiển thị riêng biệt cho từng Video"""
    def __init__(self, base_dir="storage/profiles"):
        self.storage_dir = Path(base_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, video_path):
        if not video_path: return None
        video_name = Path(video_path).stem
        return self.storage_dir / f"{video_name}.profile.json"

    def save(self, video_path, mode, font_size, color):
        path = self._get_path(video_path)
        if not path: return

        data = {
            "mode": mode.value if hasattr(mode, 'value') else mode,
            "font_size": font_size,
            "color": color
        }
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            logger.info(f"💾 Đã lưu cấu hình giao diện tại: {path}")
        except Exception as e:
            logger.error(f"❌ Lỗi lưu profile: {e}")

    def load(self, video_path):
        path = self._get_path(video_path)
        if path and path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ Lỗi đọc profile: {e}")
        return None