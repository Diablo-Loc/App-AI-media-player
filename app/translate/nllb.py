from transformers import AutoModelForSeq2SeqLM, AutoTokenizer, pipeline
import torch

# Khởi tạo model (Dùng bản 600M cho nhẹ, nếu máy mạnh bạn có thể dùng 1.3B hoặc 3.3B)
model_name = "facebook/nllb-200-distilled-600M"

# Kiểm tra xem có GPU (CUDA) không để chạy cho nhanh
device = 0 if torch.cuda.is_available() else -1

print(f"--- Đang tải model {model_name}... ---")
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

translator = pipeline(
    "translation",
    model=model,
    tokenizer=tokenizer,
    device=device
)

def translate_nllb(text, src_lang="jpn_Jpan", tgt_lang="vie_Latn"):
    """
    Dịch văn bản sử dụng model NLLB-200.
    src_lang: mã ngôn ngữ nguồn (VD: jpn_Jpan, eng_Latn)
    tgt_lang: mã ngôn ngữ đích (VD: vie_Latn, eng_Latn)
    """
    if not text or text.strip() == "":
        return ""
        
    output = translator(text, src_lang=src_lang, tgt_lang=tgt_lang, max_length=400)
    return output[0]['translation_text']