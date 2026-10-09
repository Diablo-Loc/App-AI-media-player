"""Prompt shaping for natural, meaning-preserving online lyric translation."""
from __future__ import annotations

import math
import re


_SPACE_RE = re.compile(r"\s+")


LANGUAGE_PROFILES = {
    # Character budgets include spaces. These are soft lyric-display targets,
    # not hard validators; natural meaning may exceed them when necessary.
    "en": {"cps": 17.5, "floor": 26, "ceiling": 64, "min_ratio": 0.50},
    "vi": {"cps": 18.5, "floor": 28, "ceiling": 68, "min_ratio": 0.50},
}


def cue_duration_seconds(cue, fallback: float = 2.5) -> float:
    """Read duration from production Subtitle or editor-worker DummySub."""
    try:
        if hasattr(cue, "start") and hasattr(cue, "end"):
            duration = float(cue.end) - float(cue.start)
        elif hasattr(cue, "start_ms") and hasattr(cue, "end_ms"):
            duration = (float(cue.end_ms) - float(cue.start_ms)) / 1000.0
        else:
            duration = fallback
    except (TypeError, ValueError):
        duration = fallback
    if not math.isfinite(duration) or duration <= 0:
        return fallback
    return min(max(duration, 0.35), 12.0)


def soft_character_range(duration: float, language: str) -> tuple[int, int]:
    """Return a preferred compact range while leaving semantic overflow legal."""
    profile = LANGUAGE_PROFILES.get(language, {"cps": 16.0, "floor": 24, "ceiling": 60, "min_ratio": 0.55})
    upper = round(float(duration) * profile["cps"])
    upper = max(profile["floor"], min(profile["ceiling"], upper))
    lower = max(10, round(upper * profile["min_ratio"]))
    return int(lower), int(upper)


def _source_text(cue) -> str:
    top = getattr(cue, "top", None)
    text = getattr(top, "text", "") if top is not None else ""
    return _SPACE_RE.sub(" ", str(text or "")).strip()


def build_translation_rows(subs, cue_ids=None, verified_references=None) -> str:
    """Encode machine lyrics in the simple ID===source format used by v3.1.0."""
    rows = []
    ids = list(range(len(subs))) if cue_ids is None else list(cue_ids)
    if len(ids) != len(subs):
        raise ValueError("cue_ids must match subs length")
    for idx, cue in zip(ids, subs):
        source = _source_text(cue)
        if not source:
            continue
        rows.append(f"{idx}==={source}")
    return "\n".join(rows)


def partition_translation_batches(subs, max_cues: int = 60, max_source_chars: int = 12000):
    """Split only unusually large lyric jobs while preserving global cue IDs."""
    batches = []
    current = []
    current_chars = 0
    for idx, cue in enumerate(subs):
        source = _source_text(cue)
        if not source:
            continue
        source_chars = len(source)
        if current and (
            len(current) >= max_cues
            or current_chars + source_chars > max_source_chars
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append((idx, cue))
        current_chars += source_chars
    if current:
        batches.append(current)
    return batches


def lyric_translation_system_prompt(song_title: str = "", has_reference: bool = False) -> str:
    title = str(song_title or "").strip()
    parts = [
        "Bạn là chuyên gia dịch lời bài hát, dịch thuật âm nhạc.",
        "Lời đầu vào là lời máy nhận diện nên có thể sai một vài chữ; hãy dựa vào toàn bộ các câu được gửi và ngữ cảnh bài hát để hiểu đúng khi đủ rõ.",
    ]
    if title:
        parts.append(f"Bài hát: {title}.")
    if has_reference:
        parts.append("Nếu có phần THAM CHIẾU ĐÃ XÁC MINH, mỗi dòng chỉ áp dụng cho đúng ID tương ứng và có thể dùng để sửa lỗi nhận diện của câu đó.")
    parts.extend([
        "Dịch đầy đủ từng câu sang tiếng Anh và tiếng Việt, đúng nghĩa, tự nhiên, mượt và có chất lyric.",
        "Không bịa thêm nội dung không có căn cứ từ lời máy, ngữ cảnh hoặc tham chiếu cùng ID.",
        "Trả đúng một dòng cho mỗi câu theo dạng: ID===English translation===Vietnamese translation. Giữ nguyên ID và không thêm giải thích hay markdown.",
    ])
    return " ".join(parts)


def lyric_translation_user_content(
    subs,
    song_title: str = "",
    reference_lyric: str | None = None,
    verified_references=None,
    cue_ids=None,
    context_before: str | None = None,
    context_after: str | None = None,
) -> str:
    parts = []
    if song_title:
        parts.append(f"BÀI HÁT: {song_title}")
    if reference_lyric:
        parts.append("LỜI THAM CHIẾU:\n" + str(reference_lyric).strip())

    ids = list(range(len(subs))) if cue_ids is None else list(cue_ids)
    if len(ids) != len(subs):
        raise ValueError("cue_ids must match subs length")
    references = verified_references or {}
    reference_rows = []
    for idx in ids:
        reference = _SPACE_RE.sub(" ", str(references.get(idx, "") or "")).strip()
        if reference:
            reference_rows.append(f"{idx}==={reference}")
    if reference_rows:
        parts.append("THAM CHIẾU ĐÃ XÁC MINH (cùng ID):\n" + "\n".join(reference_rows))

    # Keep the normal provider request intentionally simple. The whole batch is
    # already the translation context, so boundary-only rows and per-cue length
    # metadata are unnecessary and can over-constrain lyric wording.
    parts.append("LỜI MÁY:\n" + build_translation_rows(subs, cue_ids=cue_ids))
    return "\n\n".join(parts)
