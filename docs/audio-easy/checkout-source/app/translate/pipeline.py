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
        has_cuda = False
        try:
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                has_cuda = True
        except Exception:
            has_cuda = False

        device = "cuda" if has_cuda else "cpu"
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
    if total_len >= 12:
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
            if len(unique_words) <= 2 and total_len >= 24:
                return " ".join(words_raw[:3])
            
            # Nếu câu ngắn (dưới 5 từ) mà lặp 3 (ví dụ: "Bye bye bye") 
            # -> Giữ nguyên, đây là lời bài hát.

    # --- TẦNG 1: DỌN DẤU CÂU RÁC ---
    text = re.sub(r'([!?.])\1{2,}', r'\1', text) 
    
    # --- TẦNG 2: ENTROPY CHECK (Giữ nguyên) ---
    words = re.findall(r'\w+', text.lower())
    total_words = len(words)
    
    # Chỉ check entropy nếu câu dài (tránh cắt nhầm câu ngắn)
    if total_words >= 80:
        unique_words = set(words)
        diversity_ratio = len(unique_words) / total_words
        
        # Nếu dài mà nghèo nàn từ vựng (< 35%) -> Cắt
        if diversity_ratio < 0.1:
            limit = min(4, int(total_words / 3) + 1)
            shortened_text = " ".join(text.split()[:limit])
            return shortened_text.strip().rstrip(".,!?:") + "..."

    # --- TẦNG 3: REGEX LẶP CỤM (Tinh chỉnh) ---
    # Chỉ gộp nếu lặp > 3 lần liên tiếp (để giữ lại điệp khúc ngắn)
    # Ví dụ: "La la la" (3 lần) -> Giữ nguyên
    # "La la la la la" (5 lần) -> "La la la"
    text = re.sub(r'(?i)(\b\w+(?:[,\s]+\w+){0,5}[,\s]+)\1{11,}', r'\1\1\1', text)

    # --- TẦNG 4: HARD LIMIT ---
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
            # Accepted source lyrics must not be treated as generated spam.
            processed_batch.append(t.strip())
        
        try:
            # Gọi model NLLB để dịch
            res = translator.translate_batch(processed_batch, src_lang=src_lang, tgt_lang=tgt_lang)
            if not isinstance(res, (list, tuple)) or len(res) != len(batch):
                raise ValueError("Translation response cardinality mismatch")
            if any(not isinstance(t, str) or not t.strip() for t in res):
                raise ValueError("Translation response contains missing lines")
            results.extend(res)
        except Exception as e:
            print(f"⚠️ Lỗi dịch batch {i}-{i+batch_size} ({src_lang}->{tgt_lang}): {e}")
            # Fallback: Trả về chuỗi rỗng nếu lỗi, để không làm lệch index
            # A short response cannot be mapped safely. Retry each original row.
            for source in processed_batch:
                try:
                    item = translator.translate_batch([source], src_lang=src_lang, tgt_lang=tgt_lang)
                    if not isinstance(item, (list, tuple)) or len(item) != 1 or not isinstance(item[0], str) or not item[0].strip():
                        raise ValueError("Missing individual translation")
                    results.append(item[0])
                except Exception as retry_error:
                    raise RuntimeError(f"Không dịch được đầy đủ ({src_lang}->{tgt_lang}); chưa lưu kết quả lỗi vào cache.") from retry_error
            
        # Giải phóng VRAM sau mỗi batch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
    return results

# ==============================================================================
# 3. PIPELINE CHÍNH
# ==============================================================================
def translate_pipeline(subs, provider="Local Default", key=None, src_lang="ja", song_title="", mode=TranslateMode.PIVOT_VI):
    """
    Hàm dịch thuật tự động thông minh theo src_lang
    """
    import torch  # LAZY IMPORT
    
    if not subs: 
        return subs
        
    src_lang = str(src_lang).lower().strip()

    # ==============================================================================
    # 🇻🇳 TRƯỜNG HỢP SPECIAL: BÀI HÁT TIẾNG VIỆT
    # ==============================================================================
    if src_lang == 'vi':
        print("🇻🇳 Bài hát tiếng Việt: Gán tiếng Việt cho gốc & bỏ qua dịch AI.")
        for s in subs:
            orig_txt = s.top.text if s.top else ""
            s.bottom = SubtitleLine(text=orig_txt, lang="vi", style="VI")
            s.middle = SubtitleLine(text="", lang="en", style="EN") # Để trống tiếng Anh
        return subs

    # ==============================================================================
    # NHÁNH 1: DỊCH ONLINE (Chỉ chạy khi User chọn các nhà đài Cloud)
    # ==============================================================================
    if provider in ["OpenAI (GPT-4o)", "Google Gemini", "Claude 3.5"]:
        if key and key.strip():
            print(f"🌍 [ONLINE] Đang gọi API {provider} (src_lang: {src_lang})...")
            from translate.online_logic import translate_online_pipeline
            # 🔥 SỬA LỖI: Đã truyền thêm src_lang sang Online Logic
            online = translate_online_pipeline(subs, provider, key, song_title_raw=song_title)
            if online:
                return online
        else:
            print("⚠️ API Key trống! Tự động chuyển về Local NLLB...")

    # ==============================================================================
    # NHÁNH 2: DỊCH LOCAL NLLB
    # ==============================================================================
    cache = TranslationCache()
    
    # --- BƯỚC A: CHUẨN BỊ DỮ LIỆU ---
    all_texts = [s.top.text if s.top else "" for s in subs]
    to_translate = []
    mapping = [] 

    for i, text in enumerate(all_texts):
        if not text or not text.strip(): 
            continue
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
        translator = get_translator()
        BATCH_STEP_1 = 16 
        BATCH_STEP_2 = 8
        
        print(f"🌍 [LOCAL AI] Bắt đầu dịch {len(to_translate)} dòng từ '{src_lang}' (Mode: {mode})...")

        # ---------------------------------------------------------
        # 🇺🇸 TRƯỜNG HỢP 1: BÀI HÁT TIẾNG ANH HOẶC DỊCH THẲNG (DIRECT)
        # ---------------------------------------------------------
        if src_lang == 'en' or mode == TranslateMode.DIRECT_VI:
            print(f"🚀 Mode: Direct Translate ({src_lang} -> VI)")
            vi_new = run_safe_batch(translator, to_translate, src_lang, "vi", batch_size=BATCH_STEP_2)
            
            for idx, vi in zip(mapping, vi_new):
                clean_vi = clean_repetitive_text(vi)
                orig_en = all_texts[idx]
                
                # 🔥 SỬA LỖI CHÍ MẠNG: Gán rõ ràng cả Tiếng Anh (middle) và Tiếng Việt (bottom)
                if src_lang == 'en':
                    subs[idx].middle = SubtitleLine(text=orig_en, lang="en", style="EN")
                
                subs[idx].bottom = SubtitleLine(text=clean_vi, lang="vi", style="VI")
                cache.set(all_texts[idx], {"vi": clean_vi, "en": orig_en if src_lang == 'en' else ""})

        # ---------------------------------------------------------
        # 🇯🇵 🇰🇷 🇨🇳 TRƯỜNG HỢP 2: DỊCH BẮC CẦU (PIVOT JA/KO/ZH -> EN -> VI)
        # ---------------------------------------------------------
        else:
            print(f"🔄 Mode: Pivot Translate ({src_lang} -> EN -> VI)")
            
            # Bước 1: SRC -> EN
            print(f"    ↳ Bước 1: {src_lang} -> EN...")
            en_raw = run_safe_batch(translator, to_translate, src_lang, "en", batch_size=BATCH_STEP_1)

            en_clean_batch = [clean_repetitive_text(raw_text) for raw_text in en_raw]

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

            # Bước 2: EN -> VI
            print(f"    ↳ Bước 2: EN (Cleaned) -> VI...")
            vi_new = run_safe_batch(translator, en_clean_batch, "en", "vi", batch_size=BATCH_STEP_2)

            # Gán kết quả
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
