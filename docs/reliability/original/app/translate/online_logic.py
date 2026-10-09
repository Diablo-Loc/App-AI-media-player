import difflib
import requests
import re
from PySide6.QtCore import QSettings
from subtitle.model import SubtitleLine

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("⚠️ google-genai chưa cài. Dùng: pip install google-genai")
    genai = None

def fetch_lyric_genius(song_title, token):
    import lyricsgenius  # 🔥 LAZY IMPORT - chỉ load khi dùng Genius lyrics
    if not token: return None
    try:
        # Cấu hình skip_non_songs để tránh trang danh sách/nghệ sĩ
        genius = lyricsgenius.Genius(token, verbose=False, skip_non_songs=True, remove_section_headers=False)
        
        # Tìm danh sách bài hát thay vì lấy bài đầu tiên ngay
        search_results = genius.search_songs(song_title) 
        
        if search_results and 'songs' in search_results:
            for hit in search_results['songs']:
                # Né các trang Wiki danh sách của Genius Japan
                if "list of" in hit['title'].lower() or "genius japan" in hit['artist_names'].lower():
                    continue
                
                song = genius.get_song(hit['id'])
                if song and song.lyrics:
                    # Làm sạch sơ bộ lời (Xóa Embed ở cuối)
                    lyrics = re.sub(r'\d*Embed$', '', song.lyrics)
                    # Xóa dòng đầu tiên (thường là tiêu đề bài hát)
                    lines = lyrics.split('\n')
                    if len(lines) > 1:
                        return '\n'.join(lines[1:])
                    return lyrics
        return None
    except Exception as e:
        print(f"⚠️ Genius Error: {e}")
        return None

def ask_ai_for_clean_title(raw_title, key):
    if not key: return raw_title
    try:
        client = genai.Client(api_key=key)
        # Sử dụng Prompt từ bản test thành công
        prompt = (
            f"Extract ONLY the original song title and artist from: '{raw_title}'. "
            "If it's a Japanese song, provide: 'Original Title (English Title) - Artist'. "
            "Example: 'ロンリーユニバース (Lonely Universe) - Aqu3ra'. "
            "Return only the string, no explanation."
        )
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1)
        )
        clean_name = response.text.strip()
        return clean_name
    except Exception as e:
        print(f"⚠️ Lỗi AI Clean: {e}")
        return raw_title
    
def translate_online_pipeline(subs, provider, key, song_title_raw=None):   
    if not subs or not key or not key.strip(): 
        return None
    
    # --- BƯỚC 1: TÌM LỜI GỐC (CHIẾN THUẬT 3 LỚP) ---
    settings = QSettings("MyStudio", "AI_Music_Player")
    # Đọc cấu hình bật/tắt từ Settings
    use_genius = settings.value("use_genius", "Tắt (Nhanh)") == "Bật (Chính xác cao)"
    genius_token = settings.value("genius_key", "").strip()
    
    reference_lyric = None
    clean_title = song_title_raw

    # --- CHỈ CHẠY NẾU USER BẬT GENIUS ---
    if use_genius and genius_token and song_title_raw:
        print("🔍 Đang tìm lời gốc từ Genius...")
        clean_title = ask_ai_for_clean_title(song_title_raw, key)
        reference_lyric = fetch_lyric_genius(clean_title, genius_token)
        # Nếu không thấy thì tự động dùng tên bài riêng để tìm tiếp (Lớp 3)
        if not reference_lyric and "-" in clean_title:
             only_song_name = clean_title.split("-")[0].strip()
             reference_lyric = fetch_lyric_genius(only_song_name, genius_token)
    else:
        print("⚡ Chế độ nhanh: Bỏ qua Genius, dịch trực tiếp lời máy.")

    # --- BƯỚC 2: XÂY DỰNG PROMPT TỐI ƯU ---
    if reference_lyric:
        system_prompt = (
            "Bạn là chuyên gia dịch thuật âm nhạc. Dùng 'Lời gốc' để sửa lỗi cho 'Lời máy'. "
            "Dịch sang Anh và Việt mượt mà theo phong cách âm nhạc. "
            "ĐỊNH DẠNG: ID===Bản dịch tiếng Anh===Bản dịch tiếng Việt."
        )
        user_content = f"BÀI HÁT: {clean_title}\n--- LỜI GỐC ---\n{reference_lyric}\n\n--- LỜI MÁY ---\n" + \
                       "\n".join([f"{i}==={s.top.text if s.top else ''}" for i, s in enumerate(subs)])
    else:
        system_prompt = (
            f"Bạn là chuyên gia âm nhạc. Tôi đang nghe bài: '{clean_title}'. "
            "Dựa vào 'Lời máy' (có thể sai chính tả), hãy dùng kiến thức của bạn để dịch. "
            "ĐỊNH DẠNG: ID===Bản dịch tiếng Anh===Bản dịch tiếng Việt."
        )
        user_content = "\n".join([f"{i}==={s.top.text if s.top else ''}" for i, s in enumerate(subs)])
    # --- BƯỚC 3: GỌI API THEO PROVIDER ---
    translated_text = ""
    try:
        # --- NHÁNH 1: GOOGLE GEMINI ---
        if "Gemini" in provider:
            if not genai: return None
            
            # Khởi tạo Client đơn giản nhất
            client = genai.Client(api_key=key)
            
            # Đổi model thành gemini-3-flash-preview
            response = client.models.generate_content(
                model="gemini-3-flash-preview", 
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3
                )
            )
            translated_text = response.text

        # --- NHÁNH 2: CLAUDE 3.5 (ANTHROPIC) ---
        elif "Claude" in provider:
            headers = {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": "claude-3-5-sonnet-20240620",
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}]
            }
            r = requests.post("https://api.anthropic.com/v1/messages", json=payload, timeout=50)
            translated_text = r.json()['content'][0]['text']

        # --- NHÁNH 3: OPENAI (MẶC ĐỊNH) ---
        else:
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.3
            }
            r = requests.post("https://api.openai.com/v1/chat/completions", json=payload, timeout=40)
            translated_text = r.json()['choices'][0]['message']['content']

        # --- BƯỚC 4: HẬU XỬ LÝ ĐỔ DỮ LIỆU (GÁN CẢ MIDDLE VÀ BOTTOM) ---
        if not translated_text: 
            print("⚠️ API trả về text rỗng")
            return None
        
        matched_count = 0
        for line in translated_text.strip().split("\n"):
            if "===" not in line: continue
            
            try:
                # Tách làm 3 phần: ID, EN, VI
                parts = line.split("===", 2)
                
                if len(parts) < 3:
                    print(f"⚠️ Dòng không đủ phần: {line}")
                    continue
                    
                idx_match = re.search(r'\d+', parts[0])
                if not idx_match:
                    continue
                    
                idx = int(idx_match.group())
                if idx >= len(subs):
                    continue
                    
                en_text = parts[1].strip()
                vi_text = parts[2].strip()
                
                # Gán dòng giữa (Tiếng Anh)
                subs[idx].middle = SubtitleLine(text=en_text, lang="en", style="EN") if en_text else None
                
                # Gán dòng dưới (Tiếng Việt)
                subs[idx].bottom = SubtitleLine(text=vi_text, lang="vi", style="VI") if vi_text else None
                
                matched_count += 1
                
            except Exception as e:
                print(f"⚠️ Lỗi parse dòng: {line[:50]}... -> {e}")
                continue
        
        print(f"✅ Dịch xong {matched_count}/{len(subs)} dòng")
        return subs

    except Exception as e:
        print(f"❌ Lỗi API {provider}: {e}")
        return None