import gc
import re
import sys
from subtitle.model import SubtitleLine, Subtitle 
from translate.cache import TranslationCache

_translator_instance = None 

class TranslateMode:
    JP_ONLY = "jp_only"     # Chỉ giữ tiếng Nhật
    DIRECT_VI = "direct_vi" # Dịch thẳng Nguồn -> Việt (Nhanh, nhưng có thể kém chính xác với tiếng Á)
    PIVOT_VI = "pivot_vi"   # Dịch Nguồn -> Anh -> Việt (Chuẩn nhất cho Nhật/Trung/Hàn)
    
def get_translator():
    import torch  # 🔥 LAZY IMPORT - chỉ load torch khi thực sự dùng translator
    global _translator_instance
    if _translator_instance is None:
        from .translator import NLLBTranslator
        # Tự động chọn GPU nếu có
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🔌 Khởi tạo NLLB Translator trên thiết bị: {device.upper()}")
        _translator_instance = NLLBTranslator(device=device)
    return _translator_instance

# ==============================================================================
# 1. HÀM LỌC NỘI DUNG (CLEANER) - ĐÃ NÂNG CẤP
# ==============================================================================
def clean_repetitive_text(text):
    if not text: return ""
    text = text.strip()

    # Tách từ để phân tích
    words_raw = text.split()
    total_len = len(words_raw)

    # --- CHỐT CHẶN 0 (SỬA LẠI): DIỆT SPAM "NO NO NO" ---
    if total_len >= 3:
        # Lấy 3 từ đầu chuẩn hóa
        w1 = words_raw[0].lower().strip(".,!?:")
        w2 = words_raw[1].lower().strip(".,!?:")
        w3 = words_raw[2].lower().strip(".,!?:")
        
        # Nếu 3 từ đầu giống y hệt nhau
        if w1 == w2 == w3:
            # 🔥 LOGIC MỚI: Kiểm tra xem phía sau còn gì không?
            
            # Đếm số lượng từ vựng (Vocabulary) trong cả câu
            # Ví dụ: "Run run run away" -> {'run', 'away'} -> 2 từ -> OK
            # Ví dụ: "No no no no no" -> {'no'} -> 1 từ -> SPAM
            unique_words = set([w.lower().strip(".,!?:") for w in words_raw])
            
            # Nếu cả câu dài ngoằng mà chỉ loanh quanh 1-2 từ -> SPAM CHẮC CHẮN
            if len(unique_words) <= 2 and total_len > 5:
                return words_raw[0].rstrip(".,!?:") + "..."
            
            # Nếu câu ngắn (dưới 5 từ) mà lặp 3 (ví dụ: "Bye bye bye") 
            # -> Giữ nguyên, đây là lời bài hát.

    # --- TẦNG 1: DỌN DẤU CÂU RÁC ---
    text = re.sub(r'([!?.])\1{2,}', r'\1', text) 
    
    # --- TẦNG 2: ENTROPY CHECK (Giữ nguyên) ---
    words = re.findall(r'\w+', text.lower())
    total_words = len(words)
    
    # Chỉ check entropy nếu câu dài (tránh cắt nhầm câu ngắn)
    if total_words > 10: 
        unique_words = set(words)
        diversity_ratio = len(unique_words) / total_words
        
        # Nếu dài mà nghèo nàn từ vựng (< 35%) -> Cắt
        if diversity_ratio < 0.35: 
            limit = min(4, int(total_words / 3) + 1)
            shortened_text = " ".join(text.split()[:limit])
            return shortened_text.strip().rstrip(".,!?:") + "..."

    # --- TẦNG 3: REGEX LẶP CỤM (Tinh chỉnh) ---
    # Chỉ gộp nếu lặp > 3 lần liên tiếp (để giữ lại điệp khúc ngắn)
    # Ví dụ: "La la la" (3 lần) -> Giữ nguyên
    # "La la la la la" (5 lần) -> "La la la"
    text = re.sub(r'(?i)(\b\w+(?:[,\s]+\w+)*[,\s]*)\1{3,}', r'\1\1\1', text)

    # --- TẦNG 4: HARD LIMIT ---
    if len(text) > 150:
        text = text[:150].rsplit(' ', 1)[0].rstrip(".,!?:") + "..."
        
    return text.strip()

# ==============================================================================
# 2. HÀM CHẠY BATCH AN TOÀN (CORE LOGIC)
# ==============================================================================
def run_safe_batch(translator, text_list, src_lang, tgt_lang, batch_size=16):
    import torch  # 🔥 LAZY IMPORT - chỉ load torch khi thực sự dịch
    results = []
    total = len(text_list)
    
    for i in range(0, total, batch_size):
        batch = text_list[i : i + batch_size]
        
        # --- PRE-PROCESS: Làm sạch đầu vào trước khi đưa cho AI ---
        processed_batch = []
        for t in batch:
            # Dọn rác đầu vào để AI không bị loạn
            cleaned_t = clean_repetitive_text(t)
            
            # Cắt ngắn nếu vẫn quá dài (Tránh lỗi OOM bộ nhớ)
            if len(cleaned_t) > 1000: 
                processed_batch.append(cleaned_t[:1000])
            else:
                processed_batch.append(cleaned_t)
        
        try:
            # Gọi model NLLB để dịch
            res = translator.translate_batch(processed_batch, src_lang=src_lang, tgt_lang=tgt_lang)
            results.extend(res)
        except Exception as e:
            print(f"⚠️ Lỗi dịch batch {i}-{i+batch_size} ({src_lang}->{tgt_lang}): {e}")
            # Fallback: Trả về chuỗi rỗng nếu lỗi, để không làm lệch index
            results.extend([""] * len(batch))
            
        # Giải phóng VRAM sau mỗi batch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
    return results

# ==============================================================================
# 3. PIPELINE CHÍNH
# ==============================================================================
def translate_pipeline(subs, provider="Local Default", key=None, src_lang="ja", song_title="", mode=TranslateMode.PIVOT_VI):
    """
    Khai báo thêm 'provider' và 'key' để điều hướng.
    """
    import torch  # 🔥 LAZY IMPORT - chỉ load torch khi thực sự dịch
    
    if not subs: return subs
    if src_lang == 'vi':
        print("🇻🇳 Bài hát tiếng Việt, bỏ qua dịch thuật.")
        return subs

    # ==============================================================================
    # NHÁNH 1: DỊCH ONLINE (Chỉ chạy khi User chọn các nhà đài Cloud)
    # ==============================================================================
    if provider in ["OpenAI (GPT-4o)", "Google Gemini", "Claude 3.5"]:
        if key and key.strip():
            print(f"🌍 [ONLINE] Đang gọi API {provider}...")
            from translate.online_logic import translate_online_pipeline
            return translate_online_pipeline(subs, provider, key, song_title)
        else:
            print("⚠️ API Key trống! Tự động chuyển về Local NLLB...")
            # Nếu không có key, code sẽ tự trôi xuống phía dưới chạy Local

    # ==============================================================================
    # NHÁNH 2: DỊCH LOCAL (Giữ nguyên 100% logic gốc của bác)
    # ==============================================================================
    # Code của bác bắt đầu từ đây:
    cache = TranslationCache()
    translator = get_translator() 
    
    # --- BƯỚC A: CHUẨN BỊ DỮ LIỆU ---
    all_texts = [s.top.text if s.top else "" for s in subs]
    to_translate = []
    mapping = [] # Lưu index gốc để map lại sau khi dịch

    for i, text in enumerate(all_texts):
        if not text or not text.strip(): continue
        cached = cache.get(text)
        if cached and "vi" in cached:
            subs[i].bottom = SubtitleLine(text=cached["vi"], lang="vi", style="VI")
            if "en" in cached:
                subs[i].middle = SubtitleLine(text=cached["en"], lang="en", style="EN")
        else:
            to_translate.append(text)
            mapping.append(i)

    # --- BƯỚC B: THỰC HIỆN DỊCH ---
    if to_translate:
        BATCH_STEP_1 = 16 
        BATCH_STEP_2 = 8
        
        print(f"🌍 [LOCAL AI] Bắt đầu dịch {len(to_translate)} dòng từ '{src_lang}' (Mode: {mode})...")

        # ---------------------------------------------------------
        # TRƯỜNG HỢP 1: DỊCH THẲNG (DIRECT)
        # ---------------------------------------------------------
        if src_lang == 'en' or mode == TranslateMode.DIRECT_VI:
            print(f"🚀 Mode: Direct Translate ({src_lang} -> VI)")
            vi_new = run_safe_batch(translator, to_translate, src_lang, "vi", batch_size=BATCH_STEP_2)
            
            for idx, vi in zip(mapping, vi_new):
                clean_vi = clean_repetitive_text(vi)
                subs[idx].bottom = SubtitleLine(text=clean_vi, lang="vi", style="VI")
                cache_en = all_texts[idx] if src_lang == 'en' else ""
                cache.set(all_texts[idx], {"vi": clean_vi, "en": cache_en})

        # ---------------------------------------------------------
        # TRƯỜNG HỢP 2: DỊCH BẮC CẦU (PIVOT)
        # ---------------------------------------------------------
        else:
            print(f"🔄 Mode: Pivot Translate ({src_lang} -> EN -> VI)")
            
            # --- BƯỚC 1: SRC -> EN ---
            print(f"    ↳ Bước 1: {src_lang} -> EN...")
            en_raw = run_safe_batch(translator, to_translate, src_lang, "en", batch_size=BATCH_STEP_1)

            # 🔥🔥🔥 QUAN TRỌNG: LÀM SẠCH TIẾNG ANH NGAY LẬP TỨC 🔥🔥🔥
            en_clean_batch = []
            for raw_text in en_raw:
                cleaned = clean_repetitive_text(raw_text)
                en_clean_batch.append(cleaned)

            # Dọn dẹp bộ nhớ
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

            # --- BƯỚC 2: EN (ĐÃ SẠCH) -> VI ---
            print(f"    ↳ Bước 2: EN (Cleaned) -> VI...")
            vi_new = run_safe_batch(translator, en_clean_batch, "en", "vi", batch_size=BATCH_STEP_2)

            # --- GÁN KẾT QUẢ ---
            for idx, clean_en, vi in zip(mapping, en_clean_batch, vi_new):
                clean_vi = clean_repetitive_text(vi)
                subs[idx].middle = SubtitleLine(text=clean_en, lang="en", style="EN")
                subs[idx].bottom = SubtitleLine(text=clean_vi, lang="vi", style="VI")
                cache.set(all_texts[idx], {"en": clean_en, "vi": clean_vi})

    # --- BƯỚC C: KẾT THÚC ---
    cache.save()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return subs

def clear_translator():
    import torch  # 🔥 LAZY IMPORT - chỉ load torch khi cần dọn dẹp
    global _translator_instance
    if _translator_instance is not None:
        print("🧹 Giải phóng bộ nhớ AI...")
        del _translator_instance
        _translator_instance = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()