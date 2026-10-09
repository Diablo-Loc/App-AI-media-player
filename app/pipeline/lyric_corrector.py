import re
import requests
from PySide6.QtCore import QSettings

from translate.translation_models import (
    extract_openai_responses_text,
    openai_uses_responses_api,
    resolve_translation_model,
)

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

def correct_raw_segments_online(raw_segments, provider, key, master_lyric, song_title_raw=None):
    """
    Hàm đối soát chữ Whisper theo Lyric chuẩn.
    An toàn tuyệt đối: Bất kỳ lỗi nào xảy ra sẽ tự động trả lại raw_segments gốc.
    """
    settings = QSettings("MyStudio", "AI_Music_Player")
    provider = str(provider or settings.value("online_provider", "Local Default") or "").strip()
    key = str(key or settings.value("api_key", "") or "").strip()
    translation_model = resolve_translation_model(
        provider,
        settings.value("translation_model", ""),
    )

    # Guard clause: Kiểm tra dữ liệu đầu vào và provider online hợp lệ.
    if (
        not raw_segments
        or not key
        or not master_lyric
        or not str(master_lyric).strip()
        or not translation_model
    ):
        return raw_segments

    clean_title = song_title_raw or "Unknown Song"

    # --- BƯỚC 1: XÂY DỰNG PROMPT ---
    if master_lyric == "AUTO":
        system_prompt = (
            f"Bạn là chuyên gia biên tập phụ đề. Bài hát: '{clean_title}'.\n"
            "Dựa vào kiến thức Lời bài hát chính thức, hãy sửa lỗi nghe nhầm/chính tả cho 'LỜI MÁY' (Whisper).\n"
            "QUY TẮC:\n"
            "1. KHÔNG thêm/xóa dòng. Giữ nguyên ID ở đầu mỗi dòng.\n"
            "2. Nếu không chắc chắn về bài hát, CHỈ sửa chính tả trên LỜI MÁY, KHÔNG bịa lời.\n"
            "ĐỊNH DẠNG TRẢ VỀ: ID===Lời đã sửa"
        )
        user_content = f"BÀI HÁT: {clean_title}\n\n--- LỜI MÁY WHISPER ---\n" + \
                       "\n".join([f"{i}==={s['text']}" for i, s in enumerate(raw_segments)])
    else:
        system_prompt = (
            "Bạn là công cụ căn chỉnh phụ đề.\n"
            "Dựa vào 'LYRIC CHUẨN', hãy thay thế chữ nghe nhầm của 'LỜI MÁY' bằng chữ đúng từ Lyric chuẩn.\n"
            "QUY TẮC:\n"
            "1. KHÔNG thêm/xóa dòng. Giữ nguyên ID ở đầu mỗi dòng từ ID 0 đến cuối.\n"
            "2. BẮT BUỘC dùng chữ từ Lyric chuẩn, không tự dịch sang tiếng khác.\n"
            "ĐỊNH DẠNG TRẢ VỀ:\n"
            "0===Chữ chuẩn dòng 0\n"
            "1===Chữ chuẩn dòng 1"
        )
        user_content = f"--- LYRIC CHUẨN ---\n{master_lyric}\n\n--- LỜI MÁY WHISPER ---\n" + \
                       "\n".join([f"{i}==={s['text']}" for i, s in enumerate(raw_segments)])

    corrected_response_text = ""

    # --- BƯỚC 2: GỌI API AN TOÀN ---
    try:
        if provider == "Google Gemini":
            if not genai:
                print("⚠️ Thư viện google-genai chưa cài đặt.")
                return raw_segments
                
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=translation_model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.0,
                    max_output_tokens=16384,
                )
            )
            corrected_response_text = response.text or ""

        elif provider == "Claude 3.5":
            headers = {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": translation_model,
                "max_tokens": 8192,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
                "temperature": 0.0
            }
            r = requests.post("https://api.anthropic.com/v1/messages", json=payload, timeout=30)
            r.raise_for_status()
            corrected_response_text = r.json()['content'][0]['text']

        elif provider == "OpenAI (GPT-4o)":
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            if openai_uses_responses_api(translation_model):
                payload = {
                    "model": translation_model,
                    "instructions": system_prompt,
                    "input": user_content,
                    "store": False,
                }
                r = requests.post(
                    "https://api.openai.com/v1/responses",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                r.raise_for_status()
                corrected_response_text = extract_openai_responses_text(r.json())
            else:
                payload = {
                    "model": translation_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.0
                }
                r = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                r.raise_for_status()
                corrected_response_text = r.json()['choices'][0]['message']['content']
        else:
            return raw_segments

    except Exception as e:
        print(f"⚠️ API Sửa Lyric gặp sự cố ({e}). Tự động dùng kết quả Whisper gốc.")
        return raw_segments

    # --- BƯỚC 3: HẬU XỬ LÝ DỮ LIỆU ---
    if not corrected_response_text.strip():
        return raw_segments

    aligned_segments = [s.copy() for s in raw_segments]
    matched_count = 0

    for line in corrected_response_text.strip().split("\n"):
        if "===" not in line:
            continue
        try:
            parts = line.split("===", 1)
            if len(parts) < 2:
                continue
                
            idx_match = re.search(r'\d+', parts[0])
            if not idx_match:
                continue
                
            idx = int(idx_match.group())
            if 0 <= idx < len(aligned_segments):
                clean_text = parts[1].strip()
                if clean_text:
                    aligned_segments[idx]["text"] = clean_text
                    matched_count += 1
        except Exception:
            continue

    print(f"✅ Đã đối soát & cập nhật thành công {matched_count}/{len(raw_segments)} dòng.")
    return aligned_segments
