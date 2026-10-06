import difflib
import requests
import re
import time
from PySide6.QtCore import QSettings
from subtitle.model import SubtitleLine

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("⚠️ google-genai chưa cài. Dùng: pip install google-genai")
    genai = None


_TRANSIENT_API_STATUS = {429, 502, 503, 504}
_TRANSLATION_BATCH_DELAY_S = 0.65
_TRANSIENT_RETRY_DELAY_S = 1.35
_GENIUS_MIN_INTERVAL_S = 0.40


def _exception_status_code(error):
    """Best-effort status extraction across provider SDK exception shapes."""
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    match = re.search(r"\b(429|502|503|504)\b", str(error))
    return int(match.group(1)) if match else None


def _retry_after_seconds(response, default=_TRANSIENT_RETRY_DELAY_S):
    headers = getattr(response, "headers", None)
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        delay = float(value)
    except (TypeError, ValueError):
        delay = float(default)
    return max(0.25, min(delay, 4.0))


def _call_provider_once_with_retry(call, label):
    """Retry one transient SDK failure; permanent/provider errors keep old fallback."""
    try:
        return call()
    except Exception as error:
        status = _exception_status_code(error)
        if status not in _TRANSIENT_API_STATUS:
            raise
        print(f"⚠️ {label}: lỗi tạm thời {status}; thử lại sau {_TRANSIENT_RETRY_DELAY_S:.2f}s.")
        time.sleep(_TRANSIENT_RETRY_DELAY_S)
        return call()


def _post_provider_once_with_retry(url, *, label, **kwargs):
    """Retry one transient HTTP response while respecting a short Retry-After."""
    response = requests.post(url, **kwargs)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and status in _TRANSIENT_API_STATUS:
        delay = _retry_after_seconds(response)
        print(f"⚠️ {label}: HTTP {status}; thử lại sau {delay:.2f}s.")
        time.sleep(delay)
        response = requests.post(url, **kwargs)
    final_status = getattr(response, "status_code", None)
    if isinstance(final_status, int) and final_status in _TRANSIENT_API_STATUS:
        raise RuntimeError(f"{label} HTTP {final_status} after retry")
    return response

def fetch_lyric_genius(song_title, token, source_text=None):
    """Fetch a small candidate set and trust Genius only after local ASR matching."""
    import lyricsgenius  # 🔥 LAZY IMPORT - chỉ load khi dùng Genius lyrics
    from translate.genius_reference import (
        clean_genius_lyrics,
        extract_referent_fragments,
        extract_song_results,
        rank_song_results,
        reference_match_metrics,
        search_query_variants,
    )

    if not token:
        return None
    try:
        # Keep construction version-tolerant.  LyricsGenius has changed its
        # optional constructor arguments across releases (notably `verbose`).
        # This flow uses raw search_songs plus our own filtering/cleanup, so the
        # access token is the only constructor input we actually require.
        genius = lyricsgenius.Genius(token)
        tried = set()
        reference_fetches = 0
        last_genius_request_at = None

        def paced_genius_call(call):
            nonlocal last_genius_request_at
            if last_genius_request_at is not None:
                remaining = _GENIUS_MIN_INTERVAL_S - (time.monotonic() - last_genius_request_at)
                if remaining > 0:
                    time.sleep(remaining)
            try:
                return call()
            finally:
                last_genius_request_at = time.monotonic()

        for query in search_query_variants(song_title):
            search_results = paced_genius_call(lambda: genius.search_songs(query, per_page=5))
            ranked = rank_song_results(song_title, extract_song_results(search_results))
            for metadata_score, hit in ranked:
                if metadata_score < 0.28:
                    continue
                identity = hit.get("id") or hit.get("url")
                if not identity or identity in tried:
                    continue
                tried.add(identity)
                if reference_fetches >= 2:
                    return None
                reference_fetches += 1

                url = hit.get("url")
                song_id = hit.get("id")
                raw_lyrics = None
                try:
                    if url:
                        raw_lyrics = paced_genius_call(lambda: genius.lyrics(song_url=url))
                    elif song_id:
                        raw_lyrics = paced_genius_call(lambda: genius.lyrics(song_id=song_id))
                    else:
                        continue
                except Exception as scrape_error:
                    print(
                        "⚠️ Genius: không đọc được trang lyrics "
                        f"({type(scrape_error).__name__}); thử reference API nếu có."
                    )
                lyrics = clean_genius_lyrics(raw_lyrics or "")

                # Genius increasingly protects public lyric pages with browser
                # challenges.  Use one remaining bounded retrieval attempt for
                # official API referent fragments instead of retrying/scraping
                # around the challenge.  Fragments are never trusted without the
                # same whole-song ASR confidence gate below.
                used_referents = False
                if not lyrics and source_text and song_id and reference_fetches < 2:
                    reference_fetches += 1
                    try:
                        referents = paced_genius_call(
                            lambda: genius.referents(
                                song_id=song_id,
                                per_page=50,
                                page=1,
                                text_format="plain",
                            )
                        )
                        lyrics = extract_referent_fragments(referents)
                        used_referents = bool(lyrics)
                    except Exception as referent_error:
                        print(
                            "⚠️ Genius: reference API không khả dụng "
                            f"({type(referent_error).__name__})."
                        )
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
                if used_referents:
                    print("✅ Genius: dùng lyric fragments từ API sau khi trang lyrics không đọc được.")
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
    from translate.translation_models import (
        extract_openai_responses_text,
        openai_uses_responses_api,
        resolve_translation_model,
    )
    translation_model = resolve_translation_model(
        provider,
        settings.value("translation_model", ""),
    )
    
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
            print("⚠️ Genius: không có reference đủ tin cậy; tiếp tục dịch bằng lời máy.")
    else:
        print("⚡ Chế độ nhanh: Bỏ qua Genius, dịch trực tiếp lời máy.")

    # --- BƯỚC 2: XÂY DỰNG PROMPT LYRIC THEO THỜI LƯỢNG CUE ---
    # Shape online translations for lyric display without a second API call or
    # post-translation truncation. The old provider/fallback/parser flow stays
    # intact; only the prompt/request content is replaced with per-cue soft
    # readability budgets derived from the cue duration.
    from translate.lyric_translation import (
        partition_translation_batches,
        lyric_translation_system_prompt,
        lyric_translation_user_content,
    )
    system_prompt = lyric_translation_system_prompt(
        song_title=clean_title or "",
        has_reference=bool(reference_by_id),
    )
    batches = partition_translation_batches(subs)
    if not batches:
        return None
    if len(batches) > 1:
        print(f"📚 Lyric dài: chia {len(batches)} batch an toàn để tránh giới hạn context/output.")

    # --- BƯỚC 3: GỌI API THEO PROVIDER ---
    try:
        gemini_client = genai.Client(api_key=key) if "Gemini" in provider and genai else None
        accepted = {}
        nonempty_ids = [i for i, s in enumerate(subs) if s.top and s.top.text.strip()]
        nonempty_pos = {idx: pos for pos, idx in enumerate(nonempty_ids)}

        for batch_number, batch in enumerate(batches, start=1):
            if batch_number > 1:
                time.sleep(_TRANSLATION_BATCH_DELAY_S)
            batch_ids = [idx for idx, _ in batch]
            batch_subs = [cue for _, cue in batch]
            batch_id_set = set(batch_ids)

            reference_context = None
            batch_references = {
                idx: text for idx, text in reference_by_id.items() if idx in batch_id_set
            }
            if batch_references:
                reference_context = (
                    "VERIFIED CUE REFERENCES. Each line belongs only to the same cue ID; "
                    "never transfer its wording to another ID.\n"
                    + "\n".join(f"ID {idx}: {text}" for idx, text in sorted(batch_references.items()))
                )

            first_pos = nonempty_pos[batch_ids[0]]
            last_pos = nonempty_pos[batch_ids[-1]]
            context_before = None
            context_after = None
            if first_pos > 0:
                previous = subs[nonempty_ids[first_pos - 1]]
                context_before = previous.top.text.strip() if previous.top else None
            if last_pos + 1 < len(nonempty_ids):
                following = subs[nonempty_ids[last_pos + 1]]
                context_after = following.top.text.strip() if following.top else None

            user_content = lyric_translation_user_content(
                batch_subs,
                song_title=clean_title or "",
                reference_lyric=reference_context,
                cue_ids=batch_ids,
                context_before=context_before,
                context_after=context_after,
            )
            translated_text = ""

        # --- NHÁNH 1: GOOGLE GEMINI ---
            if "Gemini" in provider:
                if not gemini_client: return None
                response = _call_provider_once_with_retry(
                    lambda: gemini_client.models.generate_content(
                        model=translation_model,
                        contents=user_content,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.2,
                            max_output_tokens=8192,
                        )
                    ),
                    "Gemini",
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
                    "model": translation_model,
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_content}]
                }
                r = _post_provider_once_with_retry(
                    "https://api.anthropic.com/v1/messages",
                    label="Claude",
                    headers=headers,
                    json=payload,
                    timeout=50,
                )
                translated_text = r.json()['content'][0]['text']

        # --- NHÁNH 3: OPENAI (MẶC ĐỊNH) ---
            else:
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                if openai_uses_responses_api(translation_model):
                    payload = {
                        "model": translation_model,
                        "instructions": system_prompt,
                        "input": user_content,
                        "store": False,
                    }
                    r = _post_provider_once_with_retry(
                        "https://api.openai.com/v1/responses",
                        label="OpenAI",
                        headers=headers,
                        json=payload,
                        timeout=40,
                    )
                    translated_text = extract_openai_responses_text(r.json())
                else:
                    payload = {
                        "model": translation_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        "temperature": 0.2
                    }
                    r = _post_provider_once_with_retry(
                        "https://api.openai.com/v1/chat/completions",
                        label="OpenAI",
                        headers=headers,
                        json=payload,
                        timeout=40,
                    )
                    translated_text = r.json()['choices'][0]['message']['content']

        # --- BƯỚC 4: HẬU XỬ LÝ ĐỔ DỮ LIỆU (GÁN CẢ MIDDLE VÀ BOTTOM) ---
            if not translated_text:
                print("⚠️ API trả về text rỗng")
                return None

            batch_accepted = {}
            for line in translated_text.strip().split("\n"):
                if "===" not in line: continue

                try:
                    parts = line.split("===", 2)
                    if len(parts) < 3:
                        print(f"⚠️ Dòng không đủ phần: {line}")
                        continue

                    idx_match = re.fullmatch(r'\s*(?:ID\s*[:#]?\s*)?(\d+)\s*', parts[0], re.IGNORECASE)
                    if not idx_match:
                        continue

                    idx = int(idx_match.group(1))
                    if idx not in batch_id_set or idx in batch_accepted or idx in accepted:
                        return None

                    en_text = parts[1].strip()
                    vi_text = parts[2].strip()
                    if en_text and vi_text:
                        batch_accepted[idx] = (en_text, vi_text)

                except Exception as e:
                    print(f"⚠️ Lỗi parse dòng: {line[:50]}... -> {e}")
                    continue

            if not batch_id_set.issubset(batch_accepted):
                missing = len(batch_id_set - batch_accepted.keys())
                print(
                    f"⚠️ Batch {batch_number}/{len(batches)} dịch thiếu {missing} dòng; "
                    "chuyển sang fallback hiện có."
                )
                return None
            accepted.update(batch_accepted)

        required = set(nonempty_ids)
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
