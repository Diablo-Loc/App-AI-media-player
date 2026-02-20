import re
from difflib import SequenceMatcher 

# ==========================================================
# 🔹 HÀM KIỂM TRA KÝ TỰ (GIỮ NGUYÊN)
# ==========================================================
def has_japanese_chars(text):
    """Kiểm tra xem chuỗi có chứa ký tự tiếng Nhật không"""
    jp_pattern = r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]'
    return bool(re.search(jp_pattern, text))

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
def is_cjk_or_kr(char):
    code = ord(char)
    return (
        0x3040 <= code <= 0x30FF or   # JP
        0x4E00 <= code <= 0x9FFF or   # CN
        0xAC00 <= code <= 0xD7AF      # KR (Hangul)
    )

def visual_len(text):
    return sum(2 if is_cjk_or_kr(c) else 1 for c in text)

def smart_join_buffer(buffer):
    """Nối danh sách từ thành câu (Logic Universal)."""
    if not buffer: return ""
    
    result = buffer[0]
    for i in range(1, len(buffer)):
        prev_char = result[-1]
        curr_word = buffer[i]
        first_char = curr_word[0]
        
        if is_cjk(prev_char) and is_cjk(first_char):
            result += curr_word
        else:
            result += " " + curr_word
            
    return result

# ==========================================================
# 🔥 HÀM KIỂM TRA TRÙNG LẶP THÔNG MINH (FUZZY CHECK)
# ==========================================================
def is_duplicate_or_contained(new_text, last_text):
    if not last_text or not new_text:
        return False

    n, l = new_text.lower().strip(), last_text.lower().strip()

    # 1. Nếu giống hệt nhau 100% thì mới tính là trùng
    if n == l:
        return True

    # 2. Với tiếng Nhật/Hoa/Hàn, tuyệt đối KHÔNG dùng logic "n in l" 
    # Thay vào đó, dùng SequenceMatcher với tỉ lệ cực cao (0.95 trở lên)
    # và chỉ so sánh nếu độ dài hai câu cực kỳ gần nhau.
    if abs(len(n) - len(l)) <= 2: 
        return SequenceMatcher(None, n, l).ratio() > 0.95

    return False

def clean_text_for_comparison(text):
    """Xóa khoảng trắng và ký tự đặc biệt để so sánh chính xác (Inst agram -> instagram)"""
    return re.sub(r'[\s\W_]+', '', text).lower()

# ==========================================================
# 🔹 LOGIC CĂN CHỈNH CHÍNH
# ==========================================================
def refine_segments(
    segments,
    max_chars=22,
    min_pause=0.54,
    start_offset=-0.2,
    end_padding=0.27,
    gap_threshold=0.6,    
    memory_reset_t=3.0    # Tự động quên câu cũ sau 3s im lặng
):
    # 1. NHÓM TỪ CẤM TUYỆT ĐỐI (Dài ngắn gì cũng xóa)
    # Đây là những từ đặc trưng của Hallucination/Intro/Credit
    CRITICAL_BAD_WORDS = [
        "soundhodori", "ゥホドリ", "사운드호돌이", "tiger", "🐯","instagram", "inst agram", "twitter", "ホドリ", "hodori",
        "bgm", "subtitles", "視聴", "チャンネル", "copyright", 
        "subscribe", "thanks for watching", "amara.org", "synced", "corrected by", "subs by",
        "captioned by", "translated by", "all rights reserved",
        "fiction", "resemblance", "coincidental", "unintentional",
        "living or dead", "work of fiction", "actual persons",
        "unidentified", "作詞", "作曲", "編曲", "歌詞", "音楽" ,
    ]
    HALLUCINATION_PHRASES = [
        # Tiếng Hàn (Đã có)
        "다음 영상에서 만나요", "시청해주셔서 감사합니다", "구독과 좋아요", 
        "한글자막 by", "자막 제작",
        
        # Tiếng Nhật (Mới bổ sung để chặn lỗi bạn vừa gặp)
        "ご視聴ありがとうございました", "視聴ありがとうございました", 
        "チャンネル登録", "ベルマーク", "高評価をお願い",
        "お会いしましょう", "ご覧いただきありがとうございます",
        
        # Tiếng Anh
        "subtitles by", "thanks for watching", "work of fiction", 
        "resemblance to actual persons", "please subscribe"
    ]
    # 2. NHÓM TỪ CẤM ĐIỀU KIỆN (Chỉ xóa nếu câu quá ngắn)
    # Tránh xóa nhầm lời bài hát có chữ "music" hay "bye"
    WEAK_BAD_WORDS = [
        "music",
        "peace.", "bye.", "watching.", "you."
    ]
    CRITICAL_BAD_WORDS_L = [w.lower() for w in CRITICAL_BAD_WORDS]
    HALLUCINATION_PHRASES_L = [p.lower() for p in HALLUCINATION_PHRASES]
    WEAK_BAD_WORDS_L = [w.lower() for w in WEAK_BAD_WORDS]
    output = []
    last_added_text = "" 
    
    for seg in segments:
        # --- LOGIC MEMORY RESET ---
        # Giúp giữ lại điệp khúc nếu nó lặp lại sau một khoảng thời gian
        last_end_global = output[-1]["end"] if output else -999
        if (seg["start"] - last_end_global) > memory_reset_t:
            last_added_text = ""

        text = seg.get("text", "").strip()
        if not text: continue
              
        # 🔥 BƯỚC 1: CLEAN TEXT GỐC NGAY LẬP TỨC
        # Cắt các từ lặp lại > 3 lần xuống còn 3 lần
        text = re.sub(r'(.{1,4}?)\1{3,}', r'\1\1\1', text)
        
        # [CẬP NHẬT] Lọc nâng cao: Xóa bỏ các ký tự gây nhiễu để so sánh chính xác hơn
        text_l = text.lower().strip()
        
        # --- CHECK BAD WORDS ---
        if any(bad in text_l for bad in CRITICAL_BAD_WORDS_L): continue
        if any(phrase in text_l for phrase in HALLUCINATION_PHRASES_L): continue
        if len(text) < 15 and any(weak in text_l for weak in WEAK_BAD_WORDS_L): continue

        words = seg.get("words", [])
        
        # --- 1. FALLBACK ---
        if not words:
            is_dup = is_duplicate_or_contained(text, last_added_text)
            gap = seg["start"] - last_end_global
            if gap > gap_threshold or not is_dup:
                output.append({
                    "start": max(0, seg["start"] - start_offset),
                    "end": seg["end"] + end_padding,
                    "text": text
                })
                last_added_text = text
            continue

        # --- 2. MAIN LOGIC (Từng từ) ---
        buffer = []
        sent_start = None
        for i, w in enumerate(words):
            w_text = w["word"].strip()
            if not w_text: continue
            if sent_start is None: sent_start = w["start"] 

            pause = max(0, w["start"] - words[i-1]["end"]) if i > 0 else 0
            current_sentence_len = visual_len(smart_join_buffer(buffer))
            
            # Điều kiện ngắt sub
            if ((pause >= min_pause or (current_sentence_len >= max_chars and pause > 0.1)) 
                and buffer):
                
                combined_text = smart_join_buffer(buffer)
                combined_text = re.sub(r'(.{1,4}?)\1{3,}', r'\1\1\1', combined_text) # Cắt lặp
                is_dup = is_duplicate_or_contained(combined_text, last_added_text)
                last_end_time = output[-1]["end"] if output else -999
                gap = sent_start - last_end_time

                if gap > gap_threshold or not is_dup:
                    output.append({
                        "start": max(0, sent_start - start_offset),
                        "end": words[i-1]["end"] + end_padding,
                        "text": combined_text
                    })
                    last_added_text = combined_text
                
                buffer = [w_text]
                sent_start = w["start"]
            else:
                buffer.append(w_text)

        # --- 3. XỬ LÝ BUFFER DƯ (Cuối segment) ---
        if buffer:
            combined_text = smart_join_buffer(buffer)
            combined_text = re.sub(r'(.{1,4}?)\1{3,}', r'\1\1\1', combined_text)
            is_dup = is_duplicate_or_contained(combined_text, last_added_text)
            last_end_time = output[-1]["end"] if output else -999
            gap = sent_start - last_end_time
            if len(combined_text) > 1 and (gap > gap_threshold or not is_dup):
                output.append({
                    "start": max(0, sent_start - start_offset),
                    "end": words[-1]["end"] + end_padding,
                    "text": combined_text
                })
                last_added_text = combined_text

    # --- 4. CHỐNG ĐÈ (Overlap fix) ---
    # Giữ nguyên logic SAFE_GAP 0.12 của bạn
    for i in range(len(output) - 1):
        SAFE_GAP = 0.12 
        if output[i]["end"] > (output[i+1]["start"] - SAFE_GAP):
            mid_point = (output[i]["end"] + output[i+1]["start"]) / 2
            output[i]["end"] = mid_point - (SAFE_GAP / 2)
            output[i+1]["start"] = mid_point + (SAFE_GAP / 2)
        if output[i]["end"] < output[i]["start"] + 0.35:
            output[i]["end"] = output[i]["start"] + 0.35

    return output