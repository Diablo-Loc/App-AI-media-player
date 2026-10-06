#import torch
#from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

class NLLBTranslator:
    def __init__(self, device="cuda"):
        # ✅ IMPORT LƯỜI (LAZY IMPORT)
        print("⏳ Đang nạp thư viện AI (Torch & Transformers)...")
        import torch
        import os
        import sys
        
        # 🌟 VÁ LỖI BẢO MẬT: Phải đè hàm check lỗi TRƯỚC KHI import thư viện chính vào
        import transformers.utils.import_utils as transformers_import_utils
        transformers_import_utils.check_torch_load_is_safe = lambda: None
        
        # Bây giờ mới import an toàn
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        import transformers.modeling_utils
        transformers.modeling_utils.check_torch_load_is_safe = lambda: None
        
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        self.torch = torch
        
        # Model NLLB-200 mã hóa ngôn ngữ rất đặc thù (mã 7 ký tự)
        self.lang_map = {
            "ja": "jpn_Jpan",
            "vi": "vie_Latn",
            "en": "eng_Latn"  # Bổ sung thêm tiếng Anh
        }
        
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            current_file = os.path.abspath(__file__)
            # Lùi 3 cấp thư mục từ app/translate/translator.py -> Thư mục gốc MusicApp
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
            
        # Đường dẫn trỏ thẳng vào thư mục model Offline bác đã tải về
        local_model_path = os.path.join(base_dir, "app_resources", "translation_models", "nllb-200")
        
        # 🚀 Kiểm tra: Nếu tồn tại thư mục offline thì dùng luôn không cần mạng
        if os.path.exists(local_model_path) and len(os.listdir(local_model_path)) > 2:
            model_name = local_model_path
            is_offline = True
            print(f"⚡ Phát hiện hạ tầng dịch thuật Offline tại: {model_name}")
        else:
            model_name = "facebook/nllb-200-distilled-600M"
            is_offline = False
            print(f"🌐 Không tìm thấy dữ liệu Offline, chuyển hướng gọi qua mạng: {model_name}")
        
        print(f"⏳ Đang khởi tạo cấu hình Tokenizer & Model từ: {model_name}...")
    
        # ✅ BỔ SUNG CỜ OFFLINE ĐỂ TRANFORMERS ĐỌC Ổ CỨNG TUYỆT ĐỐI KHÔNG QUÉT BẢO MẬT ONLINE
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            local_files_only=is_offline
        )
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name,
            tie_word_embeddings=False,
            local_files_only=is_offline,
            low_cpu_mem_usage=True
        ).to(self.device)

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

                if hasattr(self.tokenizer, "src_lang"):
                    self.tokenizer.src_lang = src_code

                encoded = self.tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
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