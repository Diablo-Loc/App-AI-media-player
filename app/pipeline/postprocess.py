import json
from pathlib import Path

def load_dictionary(path):
    """
    Đọc file JSON an toàn. 
    Nếu không có file hoặc file lỗi -> Trả về dictionary rỗng {} (để không bị crash)
    """
    p = Path(path)
    if not p.exists():
        print(f"   ⚠️ Không tìm thấy từ điển tại: {path} (Bỏ qua bước sửa lỗi)")
        return {}
    
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"   ⚠️ Lỗi đọc file JSON: {e}")
        return {}

def apply_dictionary(text, dictionary):
    """Thay thế từ sai bằng từ đúng"""
    # Nếu từ điển rỗng thì trả về luôn cho nhanh
    if not dictionary:
        return text

    for wrong, correct in dictionary.items():
        if wrong in text:
            text = text.replace(wrong, correct)
    return text

def postprocess_segments(segments, dict_path):
    # 1. Load từ điển an toàn
    dictionary = load_dictionary(dict_path)
    
    if dictionary:
        print(f"   ✅ Đã nạp {len(dictionary)} quy tắc sửa lỗi.")

    # 2. Duyệt qua từng câu để sửa
    for seg in segments:
        seg["text"] = apply_dictionary(seg["text"], dictionary)

    return segments