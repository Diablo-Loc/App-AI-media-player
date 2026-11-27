"""True word-level karaoke timing sidecar & piecewise-linear progress curves.

Storage & compatibility guarantees:
- Word timings live strictly in `storage/subtitles/words/<media_id>.json`.
- `storage/subtitles/json/<media_id>.json` and `ass/<media_id>.ass` keep their exact
  5-key schema (`start`, `end`, `jp`, `en`, `vi`) with zero extra keys.
- Never mutates cue `start`, `end`, or `orig` text computed by the lyric pipeline.
- Supports all spoken languages (JP, ZH, KO, EN, VI, etc.), reference-snapped text
  edits via monotonic character alignment, editor time-shift resilience, and instant
  linear fallback for 600+ existing songs or when the word-karaoke toggle is OFF.
"""
from __future__ import annotations

from bisect import bisect_right
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Callable, Iterable
import unicodedata

from core.subtitle_persistence import atomic_bytes

WORD_SIDECAR_VERSION = 1
_RE_SPACE = re.compile(r"\s+")


def _is_cjk_separate_char(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch[0])
    return (
        0x2E80 <= cp <= 0x9FFF
        or 0xF900 <= cp <= 0xFAFF
        or 0x20000 <= cp <= 0x323AF
        or cp >= 0x1F000
    )


def count_karaoke_units(text: str) -> int:
    """Count visual sweep units matching `subtitle_particles.word_units` (0 Qt dependency)."""
    if not text or not text.strip():
        return 0
    units = 0
    in_word = False
    for ch in text:
        if unicodedata.combining(ch):
            continue
        if ch.isspace():
            if in_word:
                units += 1
                in_word = False
        elif _is_cjk_separate_char(ch):
            if in_word:
                units += 1
                in_word = False
            units += 1
        else:
            in_word = True
    if in_word:
        units += 1
    return max(1, units)


def normalize_lyric_for_match(text: str) -> str:
    """Compact case-folded lyric key ignoring whitespace and soft punctuation."""
    if not text:
        return ""
    out = []
    for ch in unicodedata.normalize("NFKC", str(text)).lower():
        cat = unicodedata.category(ch)
        if cat.startswith(("L", "N")):
            out.append(ch)
    return "".join(out)


def collect_whisper_word_pool(raw_segments: Iterable) -> list[dict]:
    """Extract raw timed words from Whisper segments (dicts or Segment objects) without mutating input."""
    pool: list[dict] = []
    if not raw_segments:
        return pool
    for seg in raw_segments:
        words = seg.get("words") if isinstance(seg, dict) else getattr(seg, "words", None)
        if not words:
            continue
        for w in words:
            if isinstance(w, dict):
                w_text = str(w.get("w", w.get("word", w.get("text", ""))) or "").strip()
                w_start = w.get("s", w.get("start"))
                w_end = w.get("e", w.get("end"))
            else:
                w_text = str(getattr(w, "word", getattr(w, "text", "")) or "").strip()
                w_start = getattr(w, "start", None)
                w_end = getattr(w, "end", None)
            if not w_text or w_start is None or w_end is None:
                continue
            try:
                s_val = float(w_start)
                e_val = max(s_val, float(w_end))
            except (TypeError, ValueError):
                continue
            pool.append({"s": round(s_val, 3), "e": round(e_val, 3), "w": w_text})
    pool.sort(key=lambda item: (item["s"], item["e"]))
    return pool


def collect_fa_word_pool(
    candidates_by_cue: dict | None,
    fallback_pool: list[dict] | None = None,
    cues: Iterable | None = None,
) -> list[dict]:
    """Merge high-confidence CUDA forced-alignment words with primary Whisper words per cue."""
    base_pool = list(fallback_pool or [])
    if not candidates_by_cue or not isinstance(candidates_by_cue, dict):
        return base_pool

    cue_list = list(cues or [])
    replaced_spans: list[tuple[float, float]] = []
    fa_words: list[dict] = []

    for idx, raw_words in candidates_by_cue.items():
        if not raw_words:
            continue
        parsed_cue_words: list[dict] = []
        probs: list[float] = []
        for w in raw_words:
            if not isinstance(w, dict):
                continue
            txt = str(w.get("word", w.get("w", "")) or "").strip()
            if not txt:
                continue
            try:
                ws = float(w["start"])
                we = max(ws, float(w["end"]))
                prob = float(w.get("probability", 1.0))
            except (KeyError, TypeError, ValueError):
                continue
            parsed_cue_words.append({"s": round(ws, 3), "e": round(we, 3), "w": txt})
            probs.append(prob)
        if not parsed_cue_words:
            continue
        mean_prob = sum(probs) / len(probs) if probs else 0.0
        if mean_prob < 0.24:
            continue
        fa_words.extend(parsed_cue_words)
        if isinstance(idx, int) and 0 <= idx < len(cue_list):
            c = cue_list[idx]
            cs = float(c.get("start", parsed_cue_words[0]["s"]) if isinstance(c, dict) else getattr(c, "start", parsed_cue_words[0]["s"]))
            ce = float(c.get("end", parsed_cue_words[-1]["e"]) if isinstance(c, dict) else getattr(c, "end", parsed_cue_words[-1]["e"]))
            replaced_spans.append((cs - 0.06, ce + 0.06))
        else:
            replaced_spans.append((parsed_cue_words[0]["s"] - 0.04, parsed_cue_words[-1]["e"] + 0.04))

    if not fa_words:
        return base_pool
    if not base_pool:
        fa_words.sort(key=lambda item: (item["s"], item["e"]))
        return fa_words

    merged = list(fa_words)
    for w in base_pool:
        mid = 0.5 * (float(w["s"]) + float(w["e"]))
        if not any(span_s <= mid <= span_e for span_s, span_e in replaced_spans):
            merged.append(w)
    merged.sort(key=lambda item: (item["s"], item["e"]))
    return merged


def _tokenize_display_lyric(text: str) -> list[str]:
    """Split a lyric line into compact singable tokens for Latin/VI/KO and CJK scripts."""
    stripped = str(text or "").strip()
    if not stripped:
        return []
    tokens: list[str] = []
    buf: list[str] = []
    for ch in stripped:
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf.clear()
        elif _is_cjk_separate_char(ch):
            if buf:
                tokens.append("".join(buf))
                buf.clear()
            tokens.append(ch)
        else:
            if tokens and _is_cjk_separate_char(tokens[-1]) and unicodedata.category(ch).startswith("P"):
                tokens[-1] += ch
            else:
                buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


def _align_candidates_to_orig(
    orig_text: str,
    candidates: list[dict],
    cue_start: float,
    cue_end: float,
) -> list[dict]:
    """Map acoustic word timestamps onto `orig_text`, surviving minor reference/ASR edits."""
    if not orig_text or not candidates or cue_end <= cue_start:
        return []

    clamped: list[dict] = []
    cursor_t = cue_start
    for cand in candidates:
        w_txt = str(cand.get("w", "") or "").strip()
        if not w_txt:
            continue
        s_t = max(cue_start, min(cue_end, float(cand["s"])))
        e_t = max(s_t, min(cue_end, float(cand["e"])))
        if s_t < cursor_t:
            s_t = cursor_t
        if e_t < s_t + 0.015:
            e_t = min(cue_end, s_t + 0.015)
        clamped.append({"s": s_t, "e": e_t, "w": w_txt})
        cursor_t = e_t

    if not clamped:
        return []

    raw_joined_norm = normalize_lyric_for_match("".join(c["w"] for c in clamped))
    orig_norm = normalize_lyric_for_match(orig_text)

    # Fast path: ASR tokens already spell the exact normalized text (common for Whisper EN/VI/JA/ZH)
    if raw_joined_norm and raw_joined_norm == orig_norm and len(clamped) >= 1:
        # If space-delimited language and token counts match whitespace words, preserve exact display words
        ws_words = orig_text.split()
        if len(ws_words) > 1 and len(ws_words) == len(clamped):
            return [
                {"s": round(c["s"], 3), "e": round(c["e"], 3), "w": ws_w}
                for ws_w, c in zip(ws_words, clamped)
            ]
        if len(ws_words) <= 1 or not any(" " in c["w"] for c in clamped):
            # Keep Whisper's exact word/morpheme spans if they concatenate cleanly (or map via char spans below)
            if _RE_SPACE.sub("", "".join(c["w"] for c in clamped)).lower() == _RE_SPACE.sub("", orig_text).lower():
                return [{"s": round(c["s"], 3), "e": round(c["e"], 3), "w": c["w"]} for c in clamped]

    # General monotonic character-span projection (handles Kanji/spelling fixes from LRCLIB/Genius)
    raw_chars: list[str] = []
    raw_spans: list[tuple[float, float]] = []
    for c in clamped:
        compact_w = [ch for ch in c["w"] if not ch.isspace()]
        if not compact_w:
            continue
        dur = max(0.0, c["e"] - c["s"])
        n_ch = len(compact_w)
        for idx, ch in enumerate(compact_w):
            cs = c["s"] + dur * (idx / n_ch)
            ce = c["s"] + dur * ((idx + 1) / n_ch)
            raw_chars.append(ch.lower())
            raw_spans.append((cs, ce))

    target_tokens = _tokenize_display_lyric(orig_text)
    if not target_tokens or not raw_spans:
        return []

    target_chars: list[str] = []
    token_char_ranges: list[tuple[int, int]] = []
    for tok in target_tokens:
        start_idx = len(target_chars)
        for ch in tok:
            if not ch.isspace():
                target_chars.append(ch.lower())
        end_idx = len(target_chars)
        if end_idx > start_idx:
            token_char_ranges.append((start_idx, end_idx))
        else:
            token_char_ranges.append((start_idx, start_idx))

    n_raw = len(raw_chars)
    n_tgt = len(target_chars)
    if n_tgt == 0:
        return []

    tgt_spans: list[tuple[float, float] | None] = [None] * n_tgt
    matcher = SequenceMatcher(None, "".join(raw_chars), "".join(target_chars), autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size > 0]

    for b in blocks:
        for k in range(b.size):
            tgt_spans[b.b + k] = raw_spans[b.a + k]

    # Interpolate any unmatched target characters monotonically between anchored blocks
    vocal_first_s = raw_spans[0][0]
    vocal_last_e = raw_spans[-1][1]
    idx = 0
    while idx < n_tgt:
        if tgt_spans[idx] is not None:
            idx += 1
            continue
        gap_start = idx
        while idx < n_tgt and tgt_spans[idx] is None:
            idx += 1
        gap_end = idx

        # Find corresponding raw window between neighboring anchors for pause preservation
        left_raw_idx = -1
        right_raw_idx = n_raw
        for b in blocks:
            if b.b + b.size <= gap_start:
                left_raw_idx = max(left_raw_idx, b.a + b.size - 1)
            elif b.b >= gap_end and right_raw_idx == n_raw:
                right_raw_idx = b.a

        if left_raw_idx + 1 < right_raw_idx:
            win_s = raw_spans[left_raw_idx + 1][0]
            win_e = raw_spans[right_raw_idx - 1][1]
        else:
            win_s = tgt_spans[gap_start - 1][1] if gap_start > 0 and tgt_spans[gap_start - 1] else vocal_first_s
            win_e = tgt_spans[gap_end][0] if gap_end < n_tgt and tgt_spans[gap_end] else vocal_last_e

        if win_e < win_s:
            win_e = win_s
        count = max(1, gap_end - gap_start)
        span_dur = win_e - win_s
        for offset in range(count):
            cs = win_s + span_dur * (offset / count)
            ce = win_s + span_dur * ((offset + 1) / count)
            tgt_spans[gap_start + offset] = (cs, max(cs, ce))

    aligned_words: list[dict] = []
    prev_end = cue_start
    for tok, (c0, c1) in zip(target_tokens, token_char_ranges):
        if c1 <= c0:
            continue
        first_span = tgt_spans[c0]
        last_span = tgt_spans[c1 - 1]
        if first_span is None or last_span is None:
            continue
        ws = max(prev_end, min(cue_end, first_span[0]))
        we = max(ws, min(cue_end, last_span[1]))
        aligned_words.append({"s": round(ws, 3), "e": round(we, 3), "w": tok})
        prev_end = we

    return aligned_words


def extract_and_align_cue_words(subs: Iterable, word_pool: list[dict]) -> list[dict]:
    """Build read-only word timing entries for final `subs` without altering `subs`."""
    sub_list = list(subs or [])
    if not sub_list or not word_pool:
        return []

    cue_bounds: list[tuple[float, float, str]] = []
    for seg in sub_list:
        if isinstance(seg, dict):
            s = float(seg.get("start", 0.0) or 0.0)
            e = float(seg.get("end", 0.0) or 0.0)
            orig = str(seg.get("orig", seg.get("jp", seg.get("text", ""))) or "").strip()
        else:
            s = float(getattr(seg, "start", 0.0) or 0.0)
            e = float(getattr(seg, "end", 0.0) or 0.0)
            orig = str(getattr(seg, "text", "") or "").strip()
        cue_bounds.append((s, e, orig))

    buckets: list[list[dict]] = [[] for _ in cue_bounds]
    cue_starts = [b[0] for b in cue_bounds]

    for w in word_pool:
        ws = float(w["s"])
        we = float(w["e"])
        w_mid = 0.5 * (ws + we)
        idx = max(0, bisect_right(cue_starts, w_mid) - 1)
        best_idx = None
        best_score = -1e9
        for cand_idx in (idx - 1, idx, idx + 1):
            if 0 <= cand_idx < len(cue_bounds):
                cs, ce, orig = cue_bounds[cand_idx]
                if not orig or ce <= cs:
                    continue
                overlap = min(we, ce + 0.08) - max(ws, cs - 0.08)
                dist = 0.0
                if w_mid < cs:
                    dist = cs - w_mid
                elif w_mid > ce:
                    dist = w_mid - ce
                if overlap > -0.02 and dist <= 0.22:
                    score = overlap - dist * 0.5
                    if score > best_score:
                        best_score = score
                        best_idx = cand_idx
        if best_idx is not None:
            buckets[best_idx].append(w)

    entries: list[dict] = []
    for (cs, ce, orig), bucket in zip(cue_bounds, buckets):
        if not orig or not bucket or ce <= cs:
            continue
        aligned = _align_candidates_to_orig(orig, bucket, cs, ce)
        if aligned:
            entries.append({
                "start": round(cs, 3),
                "end": round(ce, 3),
                "orig": orig,
                "words": aligned,
            })
    return entries


def save_word_timings(words_dir: str | Path, media_id: str, entries: list[dict] | None) -> Path | None:
    """Atomically write `words/<media_id>.json` (or remove stale file when `entries` is empty)."""
    if not media_id:
        return None
    folder = Path(words_dir)
    target = folder / f"{media_id}.json"
    if not entries:
        try:
            if target.is_file():
                target.unlink()
        except OSError:
            pass
        return None
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": WORD_SIDECAR_VERSION,
        "cues": entries,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    atomic_bytes(target, raw)
    return target


def load_word_timings(words_dir: str | Path, media_id: str) -> list[dict]:
    """Load `words/<media_id>.json` safely; returns `[]` for 600+ existing songs without sidecars."""
    if not media_id:
        return []
    target = Path(words_dir) / f"{media_id}.json"
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        cues = data.get("cues") if isinstance(data, dict) else data
        if not isinstance(cues, list):
            return []
        valid: list[dict] = []
        for item in cues:
            if not isinstance(item, dict):
                continue
            words = item.get("words")
            if not isinstance(words, list) or not words:
                continue
            valid.append(item)
        return valid
    except Exception:
        return []


def match_words_to_loaded_cues(
    loaded_subtitles: list[dict],
    word_entries: list[dict] | None,
) -> dict[int, list[dict]]:
    """Match saved word-timing entries to loaded subtitle cues (in ms!).

    Note: `SubtitleLayer.subtitles` stores `start` and `end` in MILLISECONDS (`converter.json_to_internal`),
    whereas `word_entries` on disk stores seconds (`s`, `e`). Returned dict maps `cue_index` ->
    `[{"s_ms": float, "e_ms": float, "w": str}, ...]`.
    - If a user manually edited a line's `orig` text in `SubtitleEditor`, its normalized text
      no longer matches, so that cue cleanly drops back to linear sweep.
    - If a user only nudged/snapped cue timestamps in `SubtitleEditor` (same `orig` text within 4s),
      word timestamps shift/scale smoothly with the cue!
    """
    if not loaded_subtitles or not word_entries:
        return {}

    unused = list(range(len(word_entries)))
    entry_norms = [normalize_lyric_for_match(e.get("orig", "")) for e in word_entries]
    matched: dict[int, list[dict]] = {}

    for cue_idx, cue in enumerate(loaded_subtitles):
        cue_orig = str(cue.get("orig", "") or "").strip()
        cue_norm = normalize_lyric_for_match(cue_orig)
        if not cue_norm:
            continue
        cue_s_ms = float(cue.get("start", 0.0) or 0.0)
        cue_e_ms = float(cue.get("end", 0.0) or 0.0)
        if cue_e_ms <= cue_s_ms:
            continue
        cue_s_sec = cue_s_ms / 1000.0

        best_pos = None
        best_diff = 4.0  # allow up to 4.0s editor time-shift when text is identical
        for pos in unused:
            if entry_norms[pos] != cue_norm:
                continue
            ent = word_entries[pos]
            ent_s = float(ent.get("start", 0.0) or 0.0)
            diff = abs(ent_s - cue_s_sec)
            if diff <= best_diff:
                best_diff = diff
                best_pos = pos
                if diff < 0.02:
                    break

        if best_pos is None:
            continue
        unused.remove(best_pos)
        ent = word_entries[best_pos]
        ent_s_ms = float(ent.get("start", 0.0) or 0.0) * 1000.0
        ent_e_ms = float(ent.get("end", 0.0) or 0.0) * 1000.0
        shift_ms = cue_s_ms - ent_s_ms
        ent_dur = max(1.0, ent_e_ms - ent_s_ms)
        cue_dur = max(1.0, cue_e_ms - cue_s_ms)
        scale = cue_dur / ent_dur if abs(cue_dur - ent_dur) > 60.0 else 1.0

        cue_words_ms: list[dict] = []
        prev_e = cue_s_ms
        for w in ent.get("words", ()):
            w_txt = str(w.get("w", "") or "").strip()
            if not w_txt:
                continue
            try:
                raw_ws = float(w["s"]) * 1000.0
                raw_we = float(w["e"]) * 1000.0
            except (KeyError, TypeError, ValueError):
                continue
            if scale != 1.0:
                ws = cue_s_ms + (raw_ws - ent_s_ms) * scale
                we = cue_s_ms + (raw_we - ent_s_ms) * scale
            else:
                ws = raw_ws + shift_ms
                we = raw_we + shift_ms
            ws = max(prev_e, min(cue_e_ms, ws))
            we = max(ws, min(cue_e_ms, we))
            cue_words_ms.append({"s_ms": ws, "e_ms": we, "w": w_txt})
            prev_e = we

        if cue_words_ms:
            matched[cue_idx] = cue_words_ms

    return matched


def build_unit_curve(
    words_ms: list[dict],
    transform_token: Callable[[str], str] | None = None,
) -> tuple[tuple[float, float, float, float], ...]:
    """Compile timed words into `(s_ms, e_ms, f_start, f_end)` cumulative unit segments."""
    if not words_ms:
        return ()
    spans: list[tuple[float, float, int]] = []
    total_units = 0
    for item in words_ms:
        tok = str(item.get("w", "") or "")
        if transform_token is not None:
            tok = transform_token(tok)
        u = max(1, count_karaoke_units(tok))
        s_ms = float(item["s_ms"])
        e_ms = max(s_ms, float(item["e_ms"]))
        spans.append((s_ms, e_ms, u))
        total_units += u

    if total_units <= 0:
        return ()

    curve: list[tuple[float, float, float, float]] = []
    acc = 0
    for s_ms, e_ms, u in spans:
        f0 = acc / total_units
        acc += u
        f1 = acc / total_units
        curve.append((s_ms, e_ms, f0, f1))
    return tuple(curve)


def eval_unit_curve(curve: tuple[tuple[float, float, float, float], ...], pts_ms: float) -> float:
    """Evaluate exact non-linear word karaoke progress in `[0.0, 1.0]` at `pts_ms`.

    - Holds at `0.0` before the first sung word (pre-vocal lead margin).
    - Advances smoothly across each word's `[s_ms, e_ms]` proportional to its visual units
      (slow on sustained notes, fast on rapid syllables).
    - Holds steady during mid-sentence vocal breaths/pauses (`e_k < pts_ms < s_{k+1}`).
    - Holds at `1.0` after the final sung word (post-vocal tail hold).
    """
    if not curve:
        return 0.0
    t = float(pts_ms)
    if t <= curve[0][0]:
        return 0.0
    if t >= curve[-1][1]:
        return 1.0
    for s_ms, e_ms, f0, f1 in curve:
        if t < s_ms:
            return f0
        if t <= e_ms:
            dur = e_ms - s_ms
            if dur <= 0.5:
                return f1
            return f0 + (f1 - f0) * ((t - s_ms) / dur)
    return 1.0
