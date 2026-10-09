import hashlib
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from subtitle.mode import SubtitleMode
from core.subtitle_persistence import atomic_bytes, publish, recover

logger = logging.getLogger(__name__)

# ======================================================
# STATUS & RESULT
# ======================================================
class SubtitleStatus:
    READY = "ready"
    NEED_AI = "need_ai_run"
    MISSING = "missing"


class SubtitleRequestResult:
    def __init__(self, status: str, media_id: Optional[str] = None, ass_path: Optional[Path] = None):
        self.status = status
        self.media_id = media_id
        self.ass_path = ass_path


# ======================================================
# SUBTITLE MANAGER
# ======================================================
class SubtitleManager:
    """
    QUY ƯỚC KIẾN TRÚC:
    - JSON = source of truth (luôn chứa jp/en/vi)
    - ASS = render theo mode (1 hoặc 2 ngôn ngữ)
    - media_index.json = Sổ địa chỉ ánh xạ ID <-> Tên File Gốc
    """

    def __init__(self, storage_root: str = "storage"):
        self.root = Path(storage_root)
        self.base_dir = self.root / "subtitles"

        self.dirs = {
            "ass": self.base_dir / "ass",
            "src_json": self.base_dir / "json",
            "temp": self.root / "temp",
        }

        for d in self.dirs.values():
            d.mkdir(parents=True, exist_ok=True)

        self.current_mode: SubtitleMode = SubtitleMode.JP_EN_VI
        
        # 🟢 1. KHỞI TẠO INDEX (QUAN TRỌNG)
        self.index_file = self.base_dir / "media_index.json"
        self._recover_pending()
        self.index_cache = self._load_index()

    # ==================================================
    # QUẢN LÝ INDEX (Sổ địa chỉ) - CÁC HÀM BỊ THIẾU
    # ==================================================
    def _load_index(self) -> Dict:
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _update_index(self, media_id: str, filename: str):
        """Lưu lại: ID này ứng với tên file nào?"""
        updated = dict(self.index_cache, **{media_id: filename})
        try:
            atomic_bytes(self.index_file, json.dumps(updated, ensure_ascii=False, indent=2).encode('utf-8'))
            self.index_cache = updated
            return True
        except Exception as e:
            logger.error(f"❌ Không lưu được index: {e}")
            return False

    def _recover_pending(self):
        try:
            if recover(self.base_dir) and hasattr(self, 'index_cache'):
                self.index_cache = self._load_index()
            return True
        except Exception as error:
            logger.error(f"Subtitle save recovery failed: {error}")
            return False

    def _save_bundle(self, media_id, data, filename=None):
        from core.subtitle_renderer import ASSRenderer
        if not self._recover_pending():
            return False
        try:
            encoded = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
            p_lang, s_lang = self._get_langs_from_mode(self.current_mode)
            with tempfile.TemporaryDirectory(prefix='subtitle-save-', dir=self.dirs['temp']) as temporary:
                rendered = Path(temporary) / 'render.ass'
                if not ASSRenderer.generate(data['segments'], rendered, p_lang, s_lang):
                    logger.error('Subtitle ASS preparation failed; existing files kept')
                    return False
                payloads = {self.get_path(media_id, 'json'): encoded,
                            self.get_path(media_id, 'ass'): rendered.read_bytes()}
                updated = dict(self.index_cache)
                if filename is not None:
                    updated[media_id] = filename
                    payloads[self.index_file] = json.dumps(updated, ensure_ascii=False, indent=2).encode('utf-8')
                publish(self.base_dir, payloads)
                self.index_cache = updated
            return True
        except Exception as error:
            logger.error(f"Subtitle save failed: {error}")
            return False

    def _get_filename_by_id(self, media_id: str) -> Optional[str]:
        return self.index_cache.get(media_id)

    # ==================================================
    # MODE
    # ==================================================
    def set_mode(self, mode: SubtitleMode):
        self.current_mode = mode
        logger.info(f"🔄 Subtitle mode → {mode.value}")

    # ==================================================
    # PATH
    # ==================================================
    def get_path(self, media_id: str, ext: str) -> Path:
        """
        Lấy đường dẫn file nội bộ.
        Logic mới: Tất cả file (ASS, JSON, TEMP) đều đặt tên theo MEDIA_ID.
        """
        # 1. File ASS
        if ext == "ass":
            return self.dirs["ass"] / f"{media_id}.ass"
        
        # 2. File JSON (Source data)
        # Lưu ý: Kiểm tra key trong __init__, nếu bạn đặt là "src_json" thì dùng "src_json"
        if ext == "json":
            return self.dirs["src_json"] / f"{media_id}.json"

        # 3. Các file tạm hoặc file nguồn import (srt, lrc...)
        # Thay vì cố tìm tên gốc, ta lưu tạm bằng ID luôn để tránh xung đột
        return self.dirs["temp"] / f"{media_id}.{ext}"

    # ==================================================
    # MEDIA ID
    # ==================================================
    def get_reliable_id(self, input_data) -> Optional[str]:
        try:
            if isinstance(input_data, dict):
                path_str = input_data.get("path")
            elif hasattr(input_data, "path"):
                path_str = input_data.path
            else:
                path_str = str(input_data)

            path = Path(path_str).resolve()
            if not path.exists():
                return None

            fingerprint = f"{str(path).lower()}_{path.stat().st_size}"
            return hashlib.md5(fingerprint.encode()).hexdigest()
        except Exception as e:
            logger.error(f"❌ media_id error: {e}")
            return None

    # ==================================================
    # CLEAN SEGMENT (OBJECT → DICT)
    # ==================================================
    def _clean_segment(self, seg: Any) -> Dict:
        try:
            start_sec = float(getattr(seg, "start", 0.0))
            end_sec = float(getattr(seg, "end", 0.0))

            # Newly aligned AI objects already carry their final display timing.
            # Unmarked legacy callers retain the exact original padding contract.
            if not getattr(seg, "_botube_final_timing", False):
                start_sec = max(0.0, start_sec - 0.1)
                end_sec = end_sec + 0.1

            def extract_text(obj):
                if not obj: return ""
                if isinstance(obj, str): return obj
                return getattr(obj, "text", "")

            jp = extract_text(getattr(seg, "top", None))
            en = extract_text(getattr(seg, "middle", None))
            vi = extract_text(getattr(seg, "bottom", None))

            if not jp and hasattr(seg, "text"):
                jp = seg.text

            return {
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "jp": jp.strip(),
                "en": en.strip(),
                "vi": vi.strip(),
            }

        except Exception as e:
            logger.error(f"❌ clean_segment error: {e}")
            return {"start": 0.0, "end": 0.0, "jp": "", "en": "", "vi": ""}

    # ==================================================
    # SAVE AI RESULT → JSON + ASS
    # ==================================================
    # 🟢 CẬP NHẬT: Thêm tham số source_path để lấy tên gốc
    def save_segments(self, media_id: str, segments: list, source_path: str = None) -> Optional[str]:
        if segments is None:
            logger.warning("⚠️ AI không trả về dữ liệu subtitle")
            return None

        # 1. Cập nhật Index (Sổ địa chỉ) nếu có source_path
        clean_filename = media_id
        if source_path:
            clean_filename = Path(source_path).stem
        else:
            # Nếu không truyền source, thử tra ngược lại xem có tên cũ không
            saved = self._get_filename_by_id(media_id)
            if saved: clean_filename = saved

        try:
            clean_segments = [self._clean_segment(s) for s in segments]

            # 2. SAVE JSON (FULL LANG)
            final_json = {
                "media_id": media_id,
                "original_name": clean_filename,
                "segments": clean_segments,
            }
            
            # Lưu file JSON (Hàm get_path giờ đã tự biết lưu vào thư mục source/json theo tên gốc)
            success = self._save_bundle(media_id, final_json, clean_filename if source_path else None)
            return str(self.get_path(media_id, 'ass')) if success else None

        except Exception as e:
            logger.error(f"❌ save_segments error: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ==================================================
    # JSON IO (Helper)
    # ==================================================
    def _save_json_file(self, path: Path, data: dict):
        try:
            atomic_bytes(path, json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
            return True
        except Exception as e:
            logger.error(f"❌ Save JSON failed: {e}")
            return False

    def get_raw_data(self, media_id: str) -> Optional[dict]:
        if not self._recover_pending():
            return None
        path = self.get_path(media_id, "json")
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
            
    # ==================================================
    # RENDER ASS (CÁC HÀM BẠN ĐANG THIẾU)
    # ==================================================
    def render_ass_from_json(self, media_id: str) -> bool:
        """Đọc JSON và tạo lại ASS (Dùng khi đổi mode hiển thị)"""
        data = self.get_raw_data(media_id)
        if not isinstance(data, dict) or not data:
            return False

        segments = data.get("segments")
        if not isinstance(segments, list):
            return False

        return self._render_ass_internal(media_id, segments) is not None

    def _render_ass_internal(self, media_id: str, segments: list) -> Optional[str]:
        """Hàm nội bộ để gọi ASSRenderer"""
        try:
            from core.subtitle_renderer import ASSRenderer
            
            ass_path = self.get_path(media_id, "ass")
            p_lang, s_lang = self._get_langs_from_mode(self.current_mode)

            with tempfile.TemporaryDirectory(prefix='subtitle-render-', dir=self.dirs['temp']) as temporary:
                rendered = Path(temporary) / 'render.ass'
                success = ASSRenderer.generate(segments, rendered, p_lang, s_lang)
                if success:
                    atomic_bytes(ass_path, rendered.read_bytes())
            
            if success:
                logger.info(f"✨ Rendered ASS: {ass_path.name}")
                return str(ass_path)
            return None
        except Exception as e:
            logger.error(f"❌ Render ASS failed: {e}")
            return None

    # ==================================================
    # REQUEST ENTRY
    # ==================================================
    def request_subtitle(self, media_item) -> SubtitleRequestResult:
        if not self._recover_pending():
            return SubtitleRequestResult(SubtitleStatus.MISSING)
        media_id = self.get_reliable_id(media_item)
        if not media_id:
            return SubtitleRequestResult(SubtitleStatus.MISSING)

        ass_path = self.get_path(media_id, "ass")
        json_path = self.get_path(media_id, "json")

        if ass_path.exists() and self._is_valid_ass(ass_path):
            return SubtitleRequestResult(SubtitleStatus.READY, media_id, ass_path)

        if json_path.exists():
            if self.render_ass_from_json(media_id):
                return SubtitleRequestResult(SubtitleStatus.READY, media_id, ass_path)

        return SubtitleRequestResult(SubtitleStatus.NEED_AI, media_id)

    # ==================================================
    # MODE → LANG
    # ==================================================
    def _get_langs_from_mode(self, mode: SubtitleMode):
        if mode == SubtitleMode.OFF: return None, None
        if mode == SubtitleMode.JP: return "jp", None
        if mode == SubtitleMode.JP_VI: return "jp", "vi"
        if mode == SubtitleMode.JP_EN: return "jp", "en"
        if mode == SubtitleMode.EN_VI: return "en", "vi"
        return "jp", "vi"

    # ==================================================
    # ASS UTIL
    # ==================================================
    def _is_valid_ass(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
            if "[Events]" in text and "Dialogue:" in text:
                return True
            # A header-only ASS is valid only with an explicit saved empty list.
            # Do not turn missing, malformed or truncated subtitle data into a
            # cached 'no lyrics' result merely because ASS has no Dialogue rows.
            data = self.get_raw_data(path.stem)
            return (all(header in text for header in ("[Script Info]", "[V4+ Styles]", "[Events]"))
                    and isinstance(data, dict) and data.get("segments") == [])
        except Exception:
            return False

    @staticmethod
    def parse_ass_time(time_str: str) -> int:
        try:
            h, m, s = time_str.split(":")
            sec, cs = s.split(".")
            return (int(h) * 3600000 + int(m) * 60000 + int(sec) * 1000 + int(cs) * 10)
        except Exception:
            return 0

    def get_segments_for_ui(self, media_id: str) -> List[Dict]:
        """Lấy data từ JSON cho UI editor"""
        data = self.get_raw_data(media_id)
        if not data: return []
        
        segments = data.get("segments", [])
        ui_segments = []
        for s in segments:
            # UI cần milliseconds
            item = s.copy()
            item["start"] = int(float(s["start"]) * 1000)
            item["end"] = int(float(s["end"]) * 1000)
            ui_segments.append(item)
            
        return ui_segments
    # ==================================================
    # BỔ SUNG HÀM BỊ THIẾU (Fix lỗi AttributeError)
    # ==================================================
    def save_raw_data(self, media_id: str, data: Any):
        """
        Hàm thông minh: Tự động phân loại dữ liệu để lưu đúng cách.
        Khắc phục lỗi: Object of type Subtitle is not JSON serializable
        """
        # Trường hợp 1: data là List (AI trả về danh sách segments dạng Object)
        if isinstance(data, list):
            # Chuyển hướng sang hàm save_segments để nó clean object -> dict
            return self.save_segments(media_id, data)
        
        # Trường hợp 2: data là Dict nhưng bên trong chứa segments dạng Object
        if isinstance(data, dict) and "segments" in data:
            raw_segments = data["segments"]
            if raw_segments and not isinstance(raw_segments[0], dict):
                # Convert list object -> list dict
                data["segments"] = [self._clean_segment(s) for s in raw_segments]

        # Trường hợp 3: data đã sạch, lưu thẳng xuống file
        if isinstance(data, dict) and isinstance(data.get('segments'), list):
            return self._save_bundle(media_id, data)
        path = self.get_path(media_id, "json")
        return self._save_json_file(path, data)
