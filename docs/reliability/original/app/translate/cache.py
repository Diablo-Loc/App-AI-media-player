import hashlib
import json
import re
from pathlib import Path

class TranslationCache:
    def __init__(self, path="output/translation_cache.json"):
        self.path = Path(path)
        self.data = {}

        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
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
        if not text: return False
        
        # 1. Kiểm tra lặp từ đơn điệu (ví dụ: "No, no, no, no...")
        # Tách từ, bỏ dấu câu
        words = re.findall(r'\w+', text.lower())
        total = len(words)
        
        # Nếu câu dài > 10 từ mà tỷ lệ từ vựng < 20% -> CHẮC CHẮN LÀ RÁC
        if total > 10:
            unique = set(words)
            if len(unique) / total < 0.2:
                return True
                
        # 2. Kiểm tra độ dài bất thường (Subtitle không bao giờ quá 200 ký tự)
        if len(text) > 200:
            return True
            
        return False

    def get(self, text: str):
        key = self._key(text)
        cached_item = self.data.get(key)
        
        if cached_item:
            # --- LOGIC MỚI: KIỂM TRA CHẤT LƯỢNG CACHE ---
            # Lấy nội dung tiếng Việt và tiếng Anh (nếu có)
            vi_text = cached_item.get("vi", "")
            en_text = cached_item.get("en", "")
            
            # Nếu phát hiện tiếng Việt hoặc tiếng Anh lưu trong cache là RÁC
            if self._is_spam(vi_text) or self._is_spam(en_text):
                print(f"🧹 Phát hiện Cache lỗi cho: '{text[:20]}...' -> XÓA và DỊCH LẠI.")
                # Xóa ngay khỏi bộ nhớ để lần sau không gặp nữa
                del self.data[key] 
                return None # Trả về None để ép hệ thống dịch lại
                
        return cached_item

    def set(self, text: str, value: dict):
        # Trước khi lưu, cũng kiểm tra nhẹ một cái cho chắc
        vi_val = value.get("vi", "")
        if not self._is_spam(vi_val):
            self.data[self._key(text)] = value

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )