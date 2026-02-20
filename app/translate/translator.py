#import torch
#from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

class NLLBTranslator:
    def __init__(self, device="cuda"):
        # ✅ IMPORT LƯỜI (LAZY IMPORT)
        # Chỉ khi class được khởi tạo, thư viện mới được nạp
        print("⏳ Đang nạp thư viện AI (Torch & Transformers)...")
        import torch
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
        # Lưu tham chiếu module torch vào self để dùng ở hàm khác (nếu cần)
        self.torch = torch
        # Model NLLB-200 mã hóa ngôn ngữ rất đặc thù (mã 7 ký tự)
        self.lang_map = {
            "ja": "jpn_Jpan",
            "vi": "vie_Latn",
            "en": "eng_Latn"  # Bổ sung thêm tiếng Anh
        }
        model_name = "facebook/nllb-200-distilled-600M"
        
        print(f"⏳ Đang tải Tokenizer & Model {model_name}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name,tie_word_embeddings=False).to(device)
        self.device = device

    def translate_batch(self, texts, src_lang="ja", tgt_lang="vi", batch_size=32):
        if not texts: return []

        import torch
        
        src_code = self.lang_map.get(src_lang, src_lang)
        tgt_code = self.lang_map.get(tgt_lang, tgt_lang)

        try:
            forced_bos_token_id = self.tokenizer.convert_tokens_to_ids(tgt_code)
        except:
            forced_bos_token_id = self.tokenizer.lang_code_to_id.get(tgt_code)

        results = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                raw_batch = texts[i : i + batch_size]
                batch = [str(t) if (t and str(t).strip()) else " " for t in raw_batch]

                encoded = self.tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    src_lang=src_code # Tối ưu: Truyền trực tiếp vào đây
                ).to(self.device)

                generated = self.model.generate(
                    **encoded,
                    forced_bos_token_id=forced_bos_token_id,
                    max_length=256,
                    num_beams=4,
                    early_stopping=True
                )

                decoded = self.tokenizer.batch_decode(generated, skip_special_tokens=True)
                results.extend([d.strip() for d in decoded])
        return results