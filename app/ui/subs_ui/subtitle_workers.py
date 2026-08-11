import re
import json
import gc
import socket
import requests
from PySide6.QtCore import QThread, Signal

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None


def is_connected() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False


class AlignWorker(QThread):
    finished_signal = Signal(list, int)
    error_signal = Signal(str)

    def __init__(self, whisper_lines, ref_text, provider, api_key, parent=None):
        super().__init__(parent)
        self.whisper_lines = whisper_lines
        self.ref_text = ref_text
        self.provider = provider
        self.api_key = api_key

    def run(self):
        machine_payload = "\n".join(
            f"{i}==={seg['text']}" for i, seg in enumerate(self.whisper_lines)
        )

        system_prompt = """
You are a professional song lyric alignment and correction engine.

You receive:
1. WHISPER TRANSCRIPT: lyrics recognized by Whisper, with numbered IDs.
2. REFERENCE LYRICS: the correct lyrics.

Your task is to correct the Whisper transcript using the reference lyrics.

STRICT RULES:
- Keep EXACTLY the same number of lines.
- Keep EVERY ID exactly unchanged.
- Do NOT create, delete, split, or merge IDs.
- Do NOT modify timestamps.
- Only correct the lyric text.
- Compare the ENTIRE Whisper transcript with the ENTIRE reference lyrics.
- Do NOT correct each line independently.
- Use surrounding lines and the chronological order of the song.
- The reference lyrics are the authoritative source for wording.
- Correct misheard words using the reference lyrics.
- Restore missing words when they clearly belong to an existing segment.
- If one Whisper segment contains multiple lyric lines, keep them together.
- NEVER invent lyrics.
- NEVER paraphrase lyrics.
- NEVER summarize lyrics.
- Preserve exact wording from the reference lyrics.
- Preserve vocal sounds such as la-la, hey-yah, oh-oh, ah, etc.
- Do not replace vocal sounds with normal lyrics.
- Do not create a new line for reference lyrics that have no Whisper segment.

IMPORTANT:
The Whisper ID represents an existing timestamp segment.
The final result must contain one corrected text for every Whisper ID.

OUTPUT ONLY:
ID===Corrected lyric

Example:
0===Sunlight through the window
1===Every sound feels so close
2===Half asleep, feet on the floor, hmm

No Markdown.
No explanation.
"""

        user_content = (
            "--- REFERENCE LYRICS ---\n"
            + self.ref_text.strip()
            + "\n\n--- WHISPER TRANSCRIPT ---\n"
            + machine_payload
        )

        try:
            corrected_raw = ""

            if "Gemini" in self.provider:
                if not genai:
                    raise Exception("google-genai chưa được cài đặt!")

                client = genai.Client(api_key=self.api_key)
                response = client.models.generate_content(
                    model="gemini-3-flash-preview",
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=0.1
                    )
                )
                corrected_raw = response.text or ""

            elif "Claude" in self.provider:
                r = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": "claude-3-5-sonnet-20240620",
                        "max_tokens": 4096,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_content}]
                    },
                    timeout=60
                )
                r.raise_for_status()
                data = r.json()
                if data.get("content"):
                    corrected_raw = data["content"][0]["text"]

            else:
                r = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        "temperature": 0.1
                    },
                    timeout=60
                )
                r.raise_for_status()
                data = r.json()
                if data.get("choices"):
                    corrected_raw = data["choices"][0]["message"]["content"]

            if not corrected_raw.strip():
                raise Exception("API trả về kết quả rỗng.")

            ai_results = {}
            for line in corrected_raw.strip().splitlines():
                if "===" not in line:
                    continue
                left, text = line.split("===", 1)
                match = re.search(r"\d+", left)
                if match and text.strip():
                    ai_results[int(match.group())] = text.strip()

            output = []
            for i, seg in enumerate(self.whisper_lines):
                text = ai_results.get(i, seg["text"])
                output.append(f"[{seg['start']:.2f} --> {seg['end']:.2f}] {text}")

            self.finished_signal.emit(output, len(ai_results))

        except Exception as e:
            self.error_signal.emit(str(e))


class TranslationWorker(QThread):
    finished_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, segments, settings, parent=None):
        super().__init__(parent)
        self.segments = segments
        self.settings = settings or {}

    def run(self):
        try:
            import torch
            from translate.pipeline import translate_pipeline, clear_translator
            from translate.online_logic import translate_online_pipeline

            class TextContainer:
                def __init__(self, text=""):
                    self.text = text

            class DummySub:
                def __init__(self, start_ms=0, end_ms=0, text=""):
                    self.start_ms = start_ms
                    self.end_ms = end_ms
                    self.top = TextContainer(text)
                    self.middle = None
                    self.bottom = None
                    self.text = text
                    self.en = ""
                    self.vi = ""

            subs_list = []
            for seg in self.segments:
                txt = seg.get('text', '') or seg.get('orig', '') or seg.get('jp', '')
                start_ms = int(float(seg.get('start', 0.0)) * 1000)
                end_ms = int(float(seg.get('end', 0.0)) * 1000)
                subs_list.append(DummySub(start_ms, end_ms, txt))

            detected_lang = self.settings.get("detected_lang", "auto") or "auto"
            detected_lang = detected_lang.lower().strip()

            use_online = self.settings.get("use_online_translation", False)
            online_provider = self.settings.get("online_provider", "Gemini") if use_online else "Local Default"
            api_key = self.settings.get("api_key", "")
            song_title_raw = self.settings.get("song_title_raw", "")
            translate_mode = self.settings.get("translate_mode", "default")

            result_subs = None

            if detected_lang == "vi":
                result_subs = subs_list
            else:
                if use_online and api_key and is_connected():
                    res = translate_online_pipeline(
                        subs_list,
                        online_provider,
                        api_key,
                        song_title_raw=song_title_raw
                    )
                    if res:
                        result_subs = res
                    else:
                        print("⚠️ Online translation thất bại, chuyển sang Local Default...")
                        result_subs = translate_pipeline(subs_list, provider="Local Default", src_lang=detected_lang, mode=translate_mode)
                else:
                    result_subs = translate_pipeline(
                        subs_list,
                        provider="Local Default",
                        src_lang=detected_lang,
                        mode=translate_mode
                    )

            clear_translator()
            gc.collect()
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()

            updated_segments = []
            final_list = result_subs if result_subs else subs_list

            for i, seg in enumerate(self.segments):
                sub_item = final_list[i] if i < len(final_list) else None
                new_seg = dict(seg)

                if sub_item:
                    orig_text = seg.get('text') or seg.get('orig') or seg.get('jp') or ''

                    item_middle_text = ""
                    if hasattr(sub_item, 'middle') and sub_item.middle:
                        item_middle_text = getattr(sub_item, 'middle', '')
                        if hasattr(item_middle_text, 'text'):
                            item_middle_text = item_middle_text.text

                    item_bottom_text = ""
                    if hasattr(sub_item, 'bottom') and sub_item.bottom:
                        item_bottom_text = getattr(sub_item.bottom, 'text', '')
                        if hasattr(item_bottom_text, 'text'):
                            item_bottom_text = item_bottom_text.text

                    item_en = getattr(sub_item, 'en', '') or item_middle_text
                    item_vi = getattr(sub_item, 'vi', '') or item_bottom_text
                    item_text = getattr(sub_item, 'text', '') or ''

                    if detected_lang == 'en':
                        new_seg['en'] = orig_text
                        translated_vi = item_vi or item_bottom_text
                        if not translated_vi and item_text and item_text != orig_text:
                            translated_vi = item_text
                        new_seg['vi'] = translated_vi or orig_text

                    elif detected_lang == 'vi':
                        new_seg['vi'] = orig_text
                        new_seg['en'] = item_en or item_middle_text or item_text

                    else:
                        translated_en = item_en or item_middle_text
                        new_seg['en'] = translated_en if translated_en else orig_text
                        translated_vi = item_vi or item_bottom_text
                        new_seg['vi'] = translated_vi if translated_vi else item_text

                updated_segments.append(new_seg)

            self.finished_signal.emit(updated_segments)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error_signal.emit(str(e))
