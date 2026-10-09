KANJI_FIX = {
    "高級神": "高級感",
    "潮り": "香り",
    "地球全部": "世界中",
    "のり返っちゃおう": "乗り越えちゃおう"
}

import re
import unicodedata

def is_cjk(char):
    if not char: return False
    code = ord(char)
    return (
        0x3040 <= code <= 0x309F or  # Hiragana
        0x30A0 <= code <= 0x30FF or  # Katakana
        0x4E00 <= code <= 0x9FFF or  # Kanji
        0x3400 <= code <= 0x4DBF or  # CJK Ext A
        0xF900 <= code <= 0xFAFF     # CJK Compatibility
    )

def universal_text_reconstruct(words_list, original_text):
    """
    Xây dựng lại câu từ danh sách từ (words).
    - Tự động thêm dấu cách nếu là Latin.
    - Tự động dính liền nếu là CJK (Nhật/Trung).
    """
    if not words_list: 
        return original_text.strip()
    
    # Lấy danh sách text của từng từ
    w_texts = [w.word.strip() for w in words_list if w.word and w.word.strip()]
    if not w_texts: return original_text.strip()

    result = w_texts[0]
    
    for i in range(1, len(w_texts)):
        prev_word = w_texts[i-1]
        curr_word = w_texts[i]
        
        # Lấy ký tự cuối của từ trước và ký tự đầu của từ sau
        last_char = prev_word[-1]
        first_char = curr_word[0]

        # LOGIC QUYẾT ĐỊNH:
        # Nếu cả 2 đều là CJK -> Dính liền
        if is_cjk(last_char) and is_cjk(first_char):
            result += curr_word
        # Các trường hợp còn lại (Anh-Anh, Anh-Nhật, Việt-Việt) -> Thêm cách
        else:
            result += " " + curr_word
            
    return result

def normalize_japanese(text: str) -> str:
    """
    Chuẩn hóa v4 (Bản Final):
    - Nguyên tắc: Chỉ xóa dấu cách nằm giữa 2 ký tự CJK (Nhật/Trung).
    - Mọi chỗ khác (Anh-Anh, Anh-Nhật, Số-Nhật...) -> GIỮ NGUYÊN DẤU CÁCH.
    """
    if not text: return ""

    # 1. Chuẩn hóa Unicode
    text = unicodedata.normalize('NFKC', text)
    text = text.strip()
    
    # Xóa chữ rác nếu muốn
    text = re.sub(r"(BGM|bgm)", "", text)

    # 2. Nếu không có dấu cách nào thì trả về luôn (đỡ tốn công xử lý)
    if " " not in text:
        return text

    # 3. Tách từ dựa trên dấu cách gốc của Whisper
    # (Whisper bản chất đã output dấu cách chuẩn cho tiếng Anh rồi)
    words = text.split(" ")
    
    # Lọc bỏ khoảng trắng thừa (VD: ['a', '', 'b'] -> ['a', 'b'])
    words = [w for w in words if w]

    if not words: return ""

    # 4. Bắt đầu ghép (Stitching) dựa trên "Nam châm CJK"
    result = words[0]

    for i in range(1, len(words)):
        prev_word = words[i-1]
        curr_word = words[i]

        # Lấy ký tự biên giới
        last_char = prev_word[-1]
        first_char = curr_word[0]

        # LOGIC QUYẾT ĐỊNH DUY NHẤT:
        # Chỉ dán dính nếu: Cả 2 biên giới đều là Chữ Tượng Hình (CJK)
        if is_cjk(last_char) and is_cjk(first_char):
            result += curr_word  # Dán liền (Nhật nối Nhật)
        else:
            result += " " + curr_word  # Cách ra (Có dính dáng đến Latin/Số)

    return result