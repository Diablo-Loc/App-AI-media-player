import hashlib
import json
import re
from pathlib import Path
from core.subtitle_persistence import atomic_bytes

class TranslationCache:
    def __init__(self, path="output/translation_cache.json"):
        self.path = Path(path)
        self.data = {}
        self._dirty = False

        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = loaded if isinstance(loaded, dict) else {}
            except:
                self.data = {}

    def _key(self, text: str) -> str:
        # Tạo key từ nội dung gốc
        return hashlib.md5(text.strip().encode("utf-8")).hexdigest()

    def _is_spam(self, text: str) -> bool:
        """
        Kiểm tra xem text trong cache có phải là spam/lỗi không.
        Nếu là spam -> Trả về True (để hủy cache này).
        """
        if not isinstance(text, str): return True
        if not text: return False
        
        # 1. Kiểm tra lặp từ đơn điệu (ví dụ: "No, no, no, no...")
        # Tách từ, bỏ dấu câu
        words = re.findall(r'\w+', text.lower())
        total = len(words)
        
        # Short refrains and normal long translations remain valid cache hits.
        if total >= 80:
            unique = set(words)
            if len(unique) / total < 0.1:
                return True
                
        return False

    def get(self, text: str):
        key = self._key(text)
        cached_item = self.data.get(key)
        if not isinstance(cached_item, dict):
            return None
        
        if cached_item:
            # --- LOGIC MỚI: KIỂM TRA CHẤT LƯỢNG CACHE ---
            # Lấy nội dung tiếng Việt và tiếng Anh (nếu có)
            vi_text = cached_item.get("vi", "")
            en_text = cached_item.get("en", "")
            
            # Nếu phát hiện tiếng Việt hoặc tiếng Anh lưu trong cache là RÁC
            if not isinstance(vi_text, str) or not vi_text.strip() or self._is_spam(vi_text) or self._is_spam(en_text):
                print(f"🧹 Bỏ qua Cache lỗi cho: '{text[:20]}...' để dịch lại khi được yêu cầu.")
                # Reading old cache never rewrites or migrates saved artifacts.
                return None # Trả về None để ép hệ thống dịch lại
                
        return cached_item

    def set(self, text: str, value: dict):
        # Trước khi lưu, cũng kiểm tra nhẹ một cái cho chắc
        vi_val = value.get("vi", "")
        if isinstance(vi_val, str) and vi_val.strip() and not self._is_spam(vi_val):
            self.data[self._key(text)] = value
            self._dirty = True

    def save(self):
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_bytes(self.path, json.dumps(self.data, ensure_ascii=False, indent=2).encode('utf-8'))
        self._dirty = False
