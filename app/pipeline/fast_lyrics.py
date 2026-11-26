"""Fast, zero-model pre-ASR lyric acquisition: Sidecar, Embedded Subs & Dual-Verified LRCLIB.

Design contract:
- Never adds AI models or GPU/CPU weight.
- Never applies unverified external timestamps onto MVs, short cuts, medleys, or covers.
- Synced LRCLIB lyrics are accepted ONLY when:
    1. Title/artist metadata matches strongly and duration agrees within +/-2.0s.
    2. Original script matches title script (rejects Romaji/translation for CJK songs).
    3. Local Silero VAD cross-check confirms first vocal onset (<=1.25s) and voiced cue overlap (>=55%).
- When synced verification fails (or only plainLyrics exist), clean plain lyrics are still
  returned as a Cloudflare-free reference candidate for single-pass online translation.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import unicodedata
import wave
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Optional

from pipeline.aligner import visual_len
from pipeline.lyric_accuracy import credit_text
from pipeline.lyric_refinement import finalize_cue_times

_SAMPLE_RATE = 16000
_LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
_LRCLIB_USER_AGENT = "BoTube/1.0 (https://github.com/botube-player)"
_VIDEO_CONTAINERS = frozenset({".mkv", ".mp4", ".m4v", ".mov", ".webm"})
_TEXT_SUB_CODECS = frozenset({"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"})

_LRC_TIME_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_LRC_TAG_RE = re.compile(r"^\[([a-zA-Z]+)\s*:\s*([^\]]*)\]$")
_LRC_INLINE_WORD_TIME_RE = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")
_ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")
_MUSIC_SYMBOL_RE = re.compile(r"^[\s♪♫♬🎵🎶♩♭♯•·.\-~—_=*()\[\]【】「」『』]+$")
_INSTRUMENTAL_LINE_RE = re.compile(
    r"^(?:\[?\s*(?:instrumental|music|interlude|outro|intro|solo|guitar solo|piano solo|間奏|前奏|後奏|伴奏|纯音乐|純音樂)\s*\]?)$",
    re.IGNORECASE,
)

_HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")
_CJK_IDEOGRAPH_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_THAI_RE = re.compile(r"[\u0e00-\u0e7f]")
_VI_SPECIFIC_RE = re.compile(
    r"[ăâđêôơưĂÂĐÊÔƠƯ"
    r"áàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    r"ÁÀẢÃẠẤẦẨẪẬẮẰẲẴẶÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ]"
)
_LATIN_RE = re.compile(r"[A-Za-z]")

_VERSION_PENALTY_MARKERS = (
    "romanized", "romaji", "english translation", "translation",
    "instrumental", "karaoke", "off vocal", "live", "remix",
    "cover", "acoustic", "nightcore", "sped up", "slowed", "short", "tv size", "medley",
)

_TITLE_BRACKET_RE = re.compile(r"[【\[]([^】\]]*)[】\]]|\(([^)]*)\)|（([^）]*)）")
_NOISE_TITLE_WORDS = frozenset({
    "official", "mv", "pv", "music", "video", "lyric", "lyrics", "audio",
    "4k", "hd", "fhd", "uhd", "hq", "visualizer", "amv", "full", "ver",
    "version", "sub", "vietsub", "engsub", "karaoke", "ost", "op", "ed",
    "theme", "song", "feat", "ft", "prod", "topic",
})


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def detect_text_language(text: str, fallback: str = "en") -> str:
    """Fast deterministic script-based language detection (0 ms, zero dependencies)."""
    sample = unicodedata.normalize("NFKC", str(text or ""))
    if not sample.strip():
        return fallback
    kana = len(_HIRAGANA_KATAKANA_RE.findall(sample))
    hangul = len(_HANGUL_RE.findall(sample))
    cjk = len(_CJK_IDEOGRAPH_RE.findall(sample))
    vi = len(_VI_SPECIFIC_RE.findall(sample))
    cyr = len(_CYRILLIC_RE.findall(sample))
    arab = len(_ARABIC_RE.findall(sample))
    thai = len(_THAI_RE.findall(sample))
    latin = len(_LATIN_RE.findall(sample))

    if kana >= 3 or (kana >= 1 and kana + cjk >= max(3, latin)):
        return "ja"
    if hangul >= 3 and hangul >= kana:
        return "ko"
    if cjk >= 3 and cjk >= latin // 2:
        return "zh"
    if cyr >= 4 and cyr > latin:
        return "ru"
    if arab >= 4 and arab > latin:
        return "ar"
    if thai >= 4 and thai > latin:
        return "th"
    if vi >= 2 and (vi / max(1, latin + vi)) >= 0.04:
        return "vi"
    if latin >= 3:
        return "en"
    return fallback


def _read_text_file_safe(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp932", "gb18030", "cp1252"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _clean_subtitle_line(text: str) -> str:
    text = _LRC_INLINE_WORD_TIME_RE.sub("", str(text or ""))
    text = _ASS_OVERRIDE_RE.sub("", text)
    text = text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    text = re.sub(r"<[^>]{1,40}>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_non_lyric_line(text: str) -> bool:
    if not text:
        return True
    if _MUSIC_SYMBOL_RE.fullmatch(text):
        return True
    if _INSTRUMENTAL_LINE_RE.fullmatch(text):
        return True
    if credit_text(text, timed_words=False):
        return True
    return False


def _cue_hold_cap_seconds(text: str) -> float:
    """Upper bound for how long an LRC cue with no explicit end timestamp may stay visible."""
    vlen = max(1, visual_len(text))
    is_cjk = bool(_HIRAGANA_KATAKANA_RE.search(text) or _CJK_IDEOGRAPH_RE.search(text) or _HANGUL_RE.search(text))
    cps = 4.2 if is_cjk else 11.5
    return max(3.5, min(8.0, (vlen / cps) + 1.8))


def parse_lrc_text(text: str, media_duration: Optional[float] = None) -> list[dict]:
    """Parse standard and multi-timestamp LRC text into non-overlapping timed cues.

    - Supports `[offset:±ms]` header tag.
    - Expands repeated chorus lines `[00:15.00][01:20.00] Text`.
    - Treats empty timestamp markers (`[00:19.50]`) as explicit cue end boundaries.
    - Strips credit/metadata/music-only lines and caps hold duration across instrumental breaks.
    """
    if not text or not str(text).strip():
        return []

    offset_sec = 0.0
    events: list[tuple[float, str, bool]] = []  # (time_sec, clean_text, is_spacer)

    for raw_line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        timestamps = list(_LRC_TIME_RE.finditer(line))
        if not timestamps:
            tag_match = _LRC_TAG_RE.match(line)
            if tag_match and tag_match.group(1).lower() == "offset":
                try:
                    offset_sec = float(tag_match.group(2).strip()) / 1000.0
                except ValueError:
                    pass
            continue

        body = _LRC_TIME_RE.sub("", line).strip()
        cleaned = _clean_subtitle_line(body)
        is_spacer = not cleaned or bool(_MUSIC_SYMBOL_RE.fullmatch(cleaned)) or bool(_INSTRUMENTAL_LINE_RE.fullmatch(cleaned))
        if not is_spacer and credit_text(cleaned, timed_words=False):
            is_spacer = True

        for match in timestamps:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            frac = match.group(3) or "0"
            if len(frac) == 1:
                sub_sec = int(frac) / 10.0
            elif len(frac) == 2:
                sub_sec = int(frac) / 100.0
            else:
                sub_sec = int(frac[:3]) / 1000.0
            t = minutes * 60.0 + seconds + sub_sec
            events.append((t, "" if is_spacer else cleaned, is_spacer))

    if not events:
        return []

    # Standard LRC spec: positive [offset:+ms] shifts lyrics earlier; clamp to >= 0.
    adjusted = []
    for t, body, is_spacer in events:
        adj_t = max(0.0, t - offset_sec)
        if media_duration is not None and media_duration > 0 and adj_t >= media_duration - 0.05:
            continue
        adjusted.append((adj_t, body, is_spacer))

    # Stable sort by timestamp, keeping lyric lines before spacer at identical timestamp.
    adjusted.sort(key=lambda item: (item[0], 1 if item[2] else 0))

    raw_cues: list[dict] = []
    total = len(adjusted)
    for idx, (start, body, is_spacer) in enumerate(adjusted):
        if is_spacer or not body:
            continue
        next_t = None
        next_is_spacer = False
        for nxt in range(idx + 1, total):
            if adjusted[nxt][0] > start + 0.05:
                next_t = adjusted[nxt][0]
                next_is_spacer = adjusted[nxt][2]
                break
        hold_cap = _cue_hold_cap_seconds(body)
        if next_t is not None:
            # Trust explicit empty-line spacer timestamps up to 8s; cap unspaced gaps to avoid frozen solos.
            cap = 8.0 if next_is_spacer else hold_cap
            end = min(next_t, start + cap)
        elif media_duration is not None and media_duration > start + 0.1:
            end = min(media_duration, start + hold_cap)
        else:
            end = start + hold_cap
        if end <= start + 0.05:
            end = start + 0.5
        raw_cues.append({"start": round(start, 3), "end": round(end, 3), "text": body})

    return finalize_cue_times(raw_cues, duration=media_duration)


def _normalize_parsed_cues(raw_segments: list[dict], media_duration: Optional[float] = None) -> list[dict]:
    cues = []
    for seg in raw_segments or ():
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", 0.0))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)) or end <= start:
            continue
        txt = _clean_subtitle_line(seg.get("text", "") or seg.get("orig", "") or seg.get("jp", ""))
        if _is_non_lyric_line(txt):
            continue
        cues.append({"start": round(max(0.0, start), 3), "end": round(end, 3), "text": txt})
    return finalize_cue_times(cues, duration=media_duration)


def probe_media_duration(media_path: str | Path) -> Optional[float]:
    """Read media duration via wave (for WAV) or ffprobe (timeout <= 2.5s)."""
    path = Path(media_path)
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                fr = w.getframerate()
                if fr > 0:
                    return w.getnframes() / float(fr)
        except Exception:
            pass
    try:
        from core.audio_effects import find_tool
        ffprobe = find_tool("ffprobe")
    except Exception:
        ffprobe = "ffprobe"
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=2.5,
            creationflags=_no_window_flags(),
        )
        if proc.returncode == 0:
            val = float((proc.stdout or "").strip())
            if math.isfinite(val) and val > 0:
                return val
    except Exception:
        pass
    return None


def find_sidecar_subtitle(media_path: str | Path, media_duration: Optional[float] = None) -> Optional[dict]:
    """Check for same-stem `.lrc`, `.srt`, or `.ass` next to the media file."""
    path = Path(media_path)
    parent = path.parent
    stem = path.stem
    if not parent.exists():
        return None

    from ui.subs_ui.subtitle_io import parse_srt_text, parse_ass_text

    for ext, source_name in ((".lrc", "sidecar_lrc"), (".srt", "sidecar_srt"), (".ass", "sidecar_ass")):
        candidate = parent / f"{stem}{ext}"
        if not candidate.is_file():
            continue
        try:
            raw_text = _read_text_file_safe(candidate)
            if ext == ".lrc":
                cues = parse_lrc_text(raw_text, media_duration=media_duration)
            elif ext == ".srt":
                cues = _normalize_parsed_cues(parse_srt_text(raw_text), media_duration=media_duration)
            else:
                cues = _normalize_parsed_cues(parse_ass_text(raw_text), media_duration=media_duration)
            if len(cues) >= 3:
                full_text = "\n".join(c["text"] for c in cues)
                return {
                    "source": source_name,
                    "path": str(candidate),
                    "cues": cues,
                    "language": detect_text_language(full_text),
                }
        except Exception:
            continue
    return None


def probe_video_duration_and_embedded(media_path: str | Path) -> tuple[Optional[float], Optional[dict]]:
    """Single combined ffprobe call for video containers (0 ffprobe calls for audio-only)."""
    path = Path(media_path)
    if path.suffix.lower() not in _VIDEO_CONTAINERS or not path.is_file():
        return None, None

    try:
        from core.audio_effects import find_tool
        ffprobe = find_tool("ffprobe")
        ffmpeg = find_tool("ffmpeg")
    except Exception:
        ffprobe, ffmpeg = "ffprobe", "ffmpeg"

    media_duration = None
    streams = []
    try:
        probe = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration:stream=index,codec_type,codec_name:stream_disposition=default,forced:stream_tags=language,title",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=2.2,
            creationflags=_no_window_flags(),
        )
        if probe.returncode == 0 and probe.stdout.strip():
            payload = json.loads(probe.stdout)
            raw_dur = (payload.get("format") or {}).get("duration")
            if raw_dur is not None:
                val = float(raw_dur)
                if math.isfinite(val) and val > 0:
                    media_duration = val
            streams = [
                st for st in (payload.get("streams") or [])
                if str(st.get("codec_type") or "").lower() == "subtitle"
            ]
    except Exception:
        return None, None

    candidates = []
    for st in streams:
        codec = str(st.get("codec_name") or "").lower()
        if codec not in _TEXT_SUB_CODECS:
            continue
        disp = st.get("disposition") or {}
        if int(disp.get("forced", 0) or 0) == 1:
            continue
        tags = st.get("tags") or {}
        title_l = str(tags.get("title") or "").lower()
        if any(skip in title_l for skip in ("sign", "signs", "songs only", "forced")):
            continue
        is_default = int(disp.get("default", 0) or 0) == 1
        candidates.append((0 if is_default else 1, int(st.get("index", 0)), tags))

    if not candidates:
        return media_duration, None

    candidates.sort(key=lambda item: (item[0], item[1]))
    from ui.subs_ui.subtitle_io import parse_srt_text

    for _, stream_index, tags in candidates[:2]:
        try:
            ext = subprocess.run(
                [
                    ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-i", str(path),
                    "-map", f"0:{stream_index}",
                    "-f", "srt", "pipe:1",
                ],
                capture_output=True,
                timeout=3.5,
                creationflags=_no_window_flags(),
            )
            if ext.returncode != 0 or not ext.stdout:
                continue
            srt_text = ext.stdout.decode("utf-8", errors="ignore")
            cues = _normalize_parsed_cues(parse_srt_text(srt_text), media_duration=media_duration)
            if len(cues) >= 3:
                full_text = "\n".join(c["text"] for c in cues)
                tag_lang = str(tags.get("language") or "").lower()[:2]
                detected = detect_text_language(full_text, fallback=tag_lang or "en")
                return media_duration, {
                    "source": "embedded_sub",
                    "stream_index": stream_index,
                    "cues": cues,
                    "language": detected,
                }
        except Exception:
            continue
    return media_duration, None


def extract_embedded_subtitle(media_path: str | Path, media_duration: Optional[float] = None) -> Optional[dict]:
    """Extract an embedded text subtitle track from MKV/MP4/WebM containers (< 0.4s)."""
    _, hit = probe_video_duration_and_embedded(media_path)
    return hit


def _clean_query_title(raw_title: str) -> str:
    text = unicodedata.normalize("NFKC", str(raw_title or "")).strip()
    text = re.sub(r"\.(?:mp3|m4a|aac|flac|wav|ogg|opus|mp4|mkv|webm|mov|avi)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", text)
    text = text.replace("_", " ")

    def _strip_noise_bracket(match: re.Match) -> str:
        inner = next((g for g in match.groups() if g is not None), "")
        words = set(re.findall(r"[a-z0-9]+", inner.casefold()))
        if words and (words & _NOISE_TITLE_WORDS or "music video" in inner.casefold()):
            return " "
        return match.group(0)

    text = _TITLE_BRACKET_RE.sub(_strip_noise_bracket, text)
    text = re.sub(r"\s+[-|｜]\s+(?:official\s*)?(?:music\s*)?(?:video|audio|lyrics?|mv|pv)\s*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" -|｜")


def _compact_alnum(text: str) -> str:
    norm = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(ch for ch in norm if ch.isalnum())


def _token_set(text: str) -> set[str]:
    norm = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return set(re.findall(r"[^\W_]+", norm, flags=re.UNICODE))


def _score_lrclib_candidate(raw_title: str, item: dict, media_duration: Optional[float]) -> tuple[float, Optional[float]]:
    """Score metadata + duration agreement conservatively."""
    query = _clean_query_title(raw_title)
    track = str(item.get("trackName") or item.get("name") or "").strip()
    artist = str(item.get("artistName") or "").strip()
    if not query or not track:
        return 0.0, None

    q_compact = _compact_alnum(query)
    t_compact = _compact_alnum(track)
    full_compact = _compact_alnum(f"{artist} {track}")
    rev_compact = _compact_alnum(f"{track} {artist}")
    if not q_compact or not t_compact:
        return 0.0, None

    full_ratio = max(
        SequenceMatcher(None, q_compact, full_compact, autojunk=False).ratio(),
        SequenceMatcher(None, q_compact, rev_compact, autojunk=False).ratio(),
    )
    title_ratio = SequenceMatcher(None, q_compact, t_compact, autojunk=False).ratio()
    containment = 1.0 if (len(t_compact) >= 3 and (t_compact in q_compact or q_compact in full_compact)) else 0.0

    q_tokens = _token_set(query)
    c_tokens = _token_set(f"{artist} {track}")
    token_overlap = len(q_tokens & c_tokens) / max(1, len(c_tokens)) if c_tokens else 0.0

    score = 0.42 * full_ratio + 0.24 * title_ratio + 0.22 * containment + 0.12 * token_overlap

    q_low = unicodedata.normalize("NFKC", raw_title).casefold()
    cand_low = unicodedata.normalize("NFKC", f"{artist} {track} {item.get('albumName') or ''}").casefold()
    for marker in _VERSION_PENALTY_MARKERS:
        in_q = marker in q_low
        in_c = marker in cand_low
        if in_c and not in_q:
            score -= 0.30 if marker in {"romanized", "romaji", "translation", "english translation", "instrumental", "karaoke"} else 0.20
        elif in_q and not in_c and marker in {"short", "tv size", "medley", "remix", "nightcore", "sped up", "slowed"}:
            # Query explicitly denotes a shortened/edited cut; studio album duration/timestamps won't match.
            score -= 0.25

    dur_diff = None
    try:
        cand_dur = float(item.get("duration") or 0.0)
        if media_duration and media_duration > 0 and cand_dur > 0:
            dur_diff = abs(cand_dur - media_duration)
            if dur_diff <= 1.0:
                score += 0.08
            elif dur_diff <= 2.0:
                score += 0.04
            elif dur_diff > 10.0:
                score -= 0.12
    except (TypeError, ValueError):
        pass

    return max(0.0, min(1.0, score)), dur_diff


def _script_compatible(raw_title: str, cues_text: str) -> bool:
    """Reject community Romaji/English translations when the song title is clearly CJK/Korean."""
    title_cjk = bool(_HIRAGANA_KATAKANA_RE.search(raw_title) or _CJK_IDEOGRAPH_RE.search(raw_title) or _HANGUL_RE.search(raw_title))
    if not title_cjk:
        return True
    lyric_cjk = len(_HIRAGANA_KATAKANA_RE.findall(cues_text)) + len(_CJK_IDEOGRAPH_RE.findall(cues_text)) + len(_HANGUL_RE.findall(cues_text))
    lyric_latin = len(_LATIN_RE.findall(cues_text))
    # Require real CJK/Hangul script in lyrics when the title itself is CJK/Hangul.
    return lyric_cjk >= 8 and lyric_cjk * 3 >= lyric_latin


_ANIME_TRACK_EXTRACT_RE = re.compile(
    r"(?:-\s*-([^-\n]{2,80}?)-(?:\s+by\b|$)|"
    r"[「『]([^」』]{1,80})[」』]|"
    r"\b(?:EP|OST|Opening(?:\s+Full)?|Ending(?:\s+Full)?|Full\s+(?:Opening|Ending)|OP\d*|ED\d*|Theme)\s*[-:｜|]\s*(.+)$)",
    re.IGNORECASE,
)


def _lrclib_query_variants(raw_title: str) -> tuple[str, ...]:
    """Build at most two clean search queries (handles anime/YouTube/Japanese title templates)."""
    primary = _clean_query_title(raw_title)
    variants: list[str] = []
    if primary and len(_compact_alnum(primary)) >= 2:
        cleaned_quotes = re.sub(r"[「」『』]", " ", primary)
        cleaned_quotes = re.sub(r"\s+", " ", cleaned_quotes).strip()
        variants.append(cleaned_quotes or primary)
    m = _ANIME_TRACK_EXTRACT_RE.search(primary or "")
    if m:
        extracted = next((g for g in m.groups() if g is not None), "").strip(" -|｜\"'「」『』")
        extracted = re.sub(r"\s+by\s+.+$", "", extracted, flags=re.IGNORECASE).strip(" -|｜")
        if extracted and len(_compact_alnum(extracted)) >= 2 and extracted not in variants:
            variants.append(extracted)
    return tuple(variants[:2])


def fetch_lrclib_items(
    song_title_raw: str,
    *,
    timeout: float = 2.0,
    http_get=None,
    cancel_cb=None,
) -> tuple[list[dict], str, str]:
    """Pure HTTP lookup against LRCLIB (designed to run in parallel with FFmpeg WAV extraction).

    Returns (items, effective_query_used, status_reason).
    """
    variants = _lrclib_query_variants(song_title_raw)
    if not variants:
        return [], "", "empty_query"

    getter = http_get
    if getter is None:
        import requests
        getter = requests.get

    last_reason = "no_results"
    for query in variants:
        if cancel_cb and cancel_cb():
            return [], query, "cancelled"
        try:
            resp = getter(
                _LRCLIB_SEARCH_URL,
                params={"q": query},
                headers={"User-Agent": _LRCLIB_USER_AGENT, "Accept": "application/json"},
                timeout=timeout,
            )
            status = getattr(resp, "status_code", 200)
            if status != 200:
                last_reason = f"http_{status}"
                continue
            items = resp.json()
            if isinstance(items, list) and items:
                return items, query, "ok"
            last_reason = "no_results"
        except Exception as err:
            return [], query, f"request_error:{type(err).__name__}"
    return [], variants[0], last_reason


def verify_synced_cues_against_audio(
    cues: list[dict],
    wav_path: str | Path,
    *,
    max_onset_diff_s: float = 1.25,
    min_voiced_ratio: float = 0.55,
    vad_probe_fn: Optional[Callable[[str | Path], Optional[dict]]] = None,
    prefetched_probe: Optional[dict] = None,
) -> tuple[bool, dict[str, Any], Optional[dict]]:
    """Cross-check synced lyric timestamps against actual audio vocals using bundled Silero VAD.

    Returns (verified_ok, diagnostic_info, probe_dict) so callers can reuse `probe_dict`
    directly inside `audit_primary_intro` without ever running Silero VAD twice.
    """
    info: dict[str, Any] = {"verified": False}
    if not cues or len(cues) < 3:
        info["reason"] = "too_few_cues"
        return False, info, prefetched_probe

    probe = prefetched_probe
    if probe is None:
        try:
            if vad_probe_fn is not None:
                probe = vad_probe_fn(wav_path)
            else:
                from pipeline.asr_intro_guard import _intro_speech_probe
                probe = _intro_speech_probe(wav_path)
        except Exception as err:
            info["reason"] = f"vad_error:{type(err).__name__}"
            return False, info, None

    if not probe:
        info["reason"] = "no_probe"
        return False, info, None

    speech = probe.get("speech") or []
    confirmed = probe.get("confirmed_speech") or speech
    if not speech:
        info["reason"] = "no_speech_detected"
        return False, info, probe

    first_vad = None
    for s, e in sorted(confirmed):
        if e - s >= 0.35:
            first_vad = s
            break
    if first_vad is None:
        for s, e in sorted(speech):
            if e - s >= 0.35:
                first_vad = s
                break
    if first_vad is None:
        info["reason"] = "no_sustained_vocal"
        return False, info, probe

    probed_cues = [c for c in cues if float(c["start"]) < 58.0]
    if not probed_cues:
        info["reason"] = "no_cues_in_probe_window"
        return False, info, probe

    first_lrc = float(probed_cues[0]["start"])
    onset_diff = abs(first_lrc - first_vad)
    info["first_lrc"] = round(first_lrc, 3)
    info["first_vad"] = round(first_vad, 3)
    info["onset_diff"] = round(onset_diff, 3)

    if onset_diff > max_onset_diff_s:
        info["reason"] = "onset_mismatch"
        return False, info, probe

    sample = probed_cues[:6]
    voiced_hits = 0
    for cue in sample:
        cs, ce = float(cue["start"]), min(59.5, float(cue["end"]))
        dur = max(0.05, ce - cs)
        ov = sum(max(0.0, min(ce, se) - max(cs, ss)) for ss, se in speech)
        if ov >= min(0.25, dur * 0.25):
            voiced_hits += 1
    ratio = voiced_hits / float(len(sample))
    info["voiced_ratio"] = round(ratio, 3)

    if ratio < min_voiced_ratio:
        info["reason"] = "low_voiced_overlap"
        return False, info, probe

    info["verified"] = True
    info["reason"] = "ok"
    return True, info, probe


def evaluate_lrclib_items(
    song_title_raw: str,
    items: list[dict],
    *,
    effective_query: str = "",
    fetch_reason: str = "ok",
    media_duration: Optional[float] = None,
    wav_path: Optional[str | Path] = None,
    vad_probe_fn=None,
) -> dict[str, Any]:
    """Score & dual-verify prefetched LRCLIB items (reuses single VAD probe if invoked)."""
    result: dict[str, Any] = {
        "synced_cues": None,
        "plain_lyrics": None,
        "language": None,
        "track_name": "",
        "artist_name": "",
        "verification": {},
        "vad_probe": None,
    }
    if not items:
        result["verification"] = {"reason": fetch_reason}
        return result

    match_title = effective_query or song_title_raw
    scored = []
    for item in items[:12]:
        if not isinstance(item, dict) or item.get("instrumental"):
            continue
        s1, d1 = _score_lrclib_candidate(song_title_raw, item, media_duration)
        if match_title != song_title_raw:
            s2, d2 = _score_lrclib_candidate(match_title, item, media_duration)
            score, dur_diff = (s2, d2) if s2 > s1 else (s1, d1)
        else:
            score, dur_diff = s1, d1
        scored.append((score, dur_diff, item))

    if not scored:
        result["verification"] = {"reason": "all_instrumental"}
        return result

    scored.sort(
        key=lambda row: (
            row[0],
            1 if row[2].get("syncedLyrics") else 0,
            -(row[1] if row[1] is not None else 999.0),
        ),
        reverse=True,
    )

    for score, dur_diff, item in scored:
        if score < 0.35:
            break
        plain = str(item.get("plainLyrics") or "").strip()
        if not plain and item.get("syncedLyrics"):
            parsed_tmp = parse_lrc_text(str(item.get("syncedLyrics") or ""))
            plain = "\n".join(c["text"] for c in parsed_tmp)
        if plain and _script_compatible(song_title_raw, plain):
            result["plain_lyrics"] = plain
            result["track_name"] = str(item.get("trackName") or "")
            result["artist_name"] = str(item.get("artistName") or "")
            break

    cached_probe = None
    for score, dur_diff, item in scored[:3]:
        synced_raw = str(item.get("syncedLyrics") or "").strip()
        if not synced_raw:
            continue
        if score < 0.45:
            result["verification"] = {"reason": "low_metadata_score", "score": round(score, 3)}
            continue
        if media_duration is None or dur_diff is None or dur_diff > 2.0:
            result["verification"] = {
                "reason": "duration_mismatch",
                "score": round(score, 3),
                "duration_diff": round(dur_diff, 2) if dur_diff is not None else None,
            }
            continue
        cues = parse_lrc_text(synced_raw, media_duration=media_duration)
        if len(cues) < 3:
            result["verification"] = {"reason": "too_few_parsed_cues"}
            continue
        joined_text = "\n".join(c["text"] for c in cues)
        if not _script_compatible(song_title_raw, joined_text):
            result["verification"] = {"reason": "script_mismatch"}
            continue
        if wav_path is not None:
            ok, vad_info, cached_probe = verify_synced_cues_against_audio(
                cues,
                wav_path,
                vad_probe_fn=vad_probe_fn,
                prefetched_probe=cached_probe,
            )
            result["vad_probe"] = cached_probe
            vad_info["score"] = round(score, 3)
            vad_info["duration_diff"] = round(dur_diff, 2)
            result["verification"] = vad_info
            if not ok:
                continue
        else:
            result["verification"] = {
                "verified": True,
                "reason": "metadata_and_duration_only",
                "score": round(score, 3),
                "duration_diff": round(dur_diff, 2),
            }

        result["synced_cues"] = cues
        result["language"] = detect_text_language(joined_text)
        result["track_name"] = str(item.get("trackName") or "")
        result["artist_name"] = str(item.get("artistName") or "")
        if not result["plain_lyrics"]:
            result["plain_lyrics"] = joined_text
        return result

    return result


def lookup_lrclib(
    song_title_raw: str,
    media_duration: Optional[float] = None,
    *,
    wav_path: Optional[str | Path] = None,
    timeout: float = 2.2,
    http_get=None,
    vad_probe_fn=None,
) -> dict[str, Any]:
    """Query LRCLIB.net with zero API keys and strict dual verification."""
    items, effective_query, reason = fetch_lrclib_items(
        song_title_raw,
        timeout=timeout,
        http_get=http_get,
    )
    return evaluate_lrclib_items(
        song_title_raw,
        items,
        effective_query=effective_query,
        fetch_reason=reason,
        media_duration=media_duration,
        wav_path=wav_path,
        vad_probe_fn=vad_probe_fn,
    )
