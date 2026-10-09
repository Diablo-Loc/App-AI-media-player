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

def fetch_lyric_genius(song_title, token, source_text=None):
    """Fetch a small candidate set and trust Genius only after local ASR matching."""
    import lyricsgenius  # 🔥 LAZY IMPORT - chỉ load khi dùng Genius lyrics
    from translate.genius_reference import (
        clean_genius_lyrics,
        extract_song_results,
        rank_song_results,
        reference_match_metrics,
        search_query_variants,
    )

    if not token:
        return None
    try:
        genius = lyricsgenius.Genius(
            token,
            verbose=False,
            skip_non_songs=True,
            remove_section_headers=False,
        )
        tried = set()
        lyric_fetches = 0
        for query in search_query_variants(song_title):
            search_results = genius.search_songs(query, per_page=5)
            ranked = rank_song_results(song_title, extract_song_results(search_results))
            for metadata_score, hit in ranked:
                if metadata_score < 0.28:
                    continue
                identity = hit.get("id") or hit.get("url")
                if not identity or identity in tried:
                    continue
                tried.add(identity)
                if lyric_fetches >= 2:
                    return None
                lyric_fetches += 1

                url = hit.get("url")
                song_id = hit.get("id")
                if url:
                    raw_lyrics = genius.lyrics(song_url=url)
                elif song_id:
                    raw_lyrics = genius.lyrics(song_id=song_id)
                else:
                    continue
                lyrics = clean_genius_lyrics(raw_lyrics or "")
                if not lyrics:
                    continue

                if source_text:
                    metrics = reference_match_metrics(source_text, lyrics)
                    if metrics["score"] < 0.42 or metrics["sequence_coverage"] < 0.20:
                        print(
                            "⚠️ Genius: bỏ kết quả không khớp ASR "
                            f"(confidence={metrics['score']:.2f})."
                        )
                        continue
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
    
    # --- BƯỚC 1: GENIUS REFERENCE ASSIST CÓ KIỂM CHỨNG ---
    settings = QSettings("MyStudio", "AI_Music_Player")
    # Đọc cấu hình bật/tắt từ Settings
    use_genius = settings.value("use_genius", "Tắt (Nhanh)") == "Bật (Chính xác cao)"
    genius_token = settings.value("genius_key", "").strip()
    
    reference_lyric = None
    reference_by_id = {}
    from translate.genius_reference import (
        build_reference_hints,
        clean_search_title,
        source_text_from_subs,
    )
    clean_title = clean_search_title(song_title_raw or "") or song_title_raw

    # --- CHỈ CHẠY NẾU USER BẬT GENIUS ---
    if use_genius and genius_token and song_title_raw:
        print("🔍 Đang tìm lời gốc từ Genius...")
        source_text = source_text_from_subs(subs)
        reference_lyric = fetch_lyric_genius(clean_title, genius_token, source_text=source_text)
        if reference_lyric:
            reference_by_id = build_reference_hints(subs, reference_lyric)
            if reference_by_id:
                print(f"✅ Genius: xác minh và ghép tham chiếu {len(reference_by_id)}/{len(subs)} câu.")
            else:
                # Whole-song validation passed but no individual cue was safe
                # enough to bind. Do not send the full lyric to the translator.
                reference_lyric = None
                print("⚠️ Genius: đúng bài nhưng không đủ chắc để ghép theo câu; bỏ tham chiếu.")
    else:
        print("⚡ Chế độ nhanh: Bỏ qua Genius, dịch trực tiếp lời máy.")

    # --- BƯỚC 2: XÂY DỰNG PROMPT LYRIC THEO THỜI LƯỢNG CUE ---
    # Shape online translations for lyric display without a second API call or
    # post-translation truncation. The old provider/fallback/parser flow stays
    # intact; only the prompt/request content is replaced with per-cue soft
    # readability budgets derived from the cue duration.
    from translate.lyric_translation import (
        lyric_translation_system_prompt,
        lyric_translation_user_content,
    )
    system_prompt = lyric_translation_system_prompt(
        song_title=clean_title or "",
        has_reference=bool(reference_by_id),
    )
    reference_context = None
    if reference_by_id:
        reference_context = (
            "VERIFIED CUE REFERENCES. Each line belongs only to the same cue ID; "
            "never transfer its wording to another ID.\n"
            + "\n".join(f"ID {idx}: {text}" for idx, text in sorted(reference_by_id.items()))
        )
    user_content = lyric_translation_user_content(
        subs,
        song_title=clean_title or "",
        reference_lyric=reference_context,
    )

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
                model="gemini-2.5-flash",
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
        
        accepted = {}
        for line in translated_text.strip().split("\n"):
            if "===" not in line: continue
            
            try:
                # Tách làm 3 phần: ID, EN, VI
                parts = line.split("===", 2)
                
                if len(parts) < 3:
                    print(f"⚠️ Dòng không đủ phần: {line}")
                    continue
                    
                idx_match = re.fullmatch(r'\s*(?:ID\s*[:#]?\s*)?(\d+)\s*', parts[0], re.IGNORECASE)
                if not idx_match:
                    continue
                    
                idx = int(idx_match.group(1))
                if idx >= len(subs) or idx in accepted:
                    return None
                    
                en_text = parts[1].strip()
                vi_text = parts[2].strip()
                
                # Gán dòng giữa (Tiếng Anh)
                if en_text and vi_text:
                    accepted[idx] = (en_text, vi_text)
                
            except Exception as e:
                print(f"⚠️ Lỗi parse dòng: {line[:50]}... -> {e}")
                continue
        
        required = {i for i, s in enumerate(subs) if s.top and s.top.text.strip()}
        if not required.issubset(accepted):
            print(f"⚠️ Dịch thiếu {len(required - accepted.keys())} dòng; chuyển sang fallback hiện có.")
            return None
        for idx, (en_text, vi_text) in accepted.items():
            subs[idx].middle = SubtitleLine(text=en_text, lang="en", style="EN")
            subs[idx].bottom = SubtitleLine(text=vi_text, lang="vi", style="VI")
        print(f"✅ Dịch xong {len(accepted)}/{len(subs)} dòng")
        return subs

    except Exception as e:
        print(f"❌ Lỗi API {provider}: {e}")
        return None
