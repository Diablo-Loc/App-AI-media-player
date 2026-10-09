"""Prompt shaping for concise, meaning-preserving lyric subtitles.

This module deliberately does not truncate translated text. It gives the
online translator a soft readability budget for each cue and lets meaning win
when a faithful line needs a little more space.
"""
from __future__ import annotations

import json
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
    """Encode cues as JSONL and bind any verified reference to its exact cue ID."""
    rows = []
    ids = list(range(len(subs))) if cue_ids is None else list(cue_ids)
    if len(ids) != len(subs):
        raise ValueError("cue_ids must match subs length")
    references = verified_references or {}
    for idx, cue in zip(ids, subs):
        source = _source_text(cue)
        if not source:
            continue
        duration = cue_duration_seconds(cue)
        en_min, en_max = soft_character_range(duration, "en")
        vi_min, vi_max = soft_character_range(duration, "vi")
        row = {
            "id": idx,
            "duration_s": round(duration, 2),
            "en_preferred_chars": f"{en_min}-{en_max}",
            "vi_preferred_chars": f"{vi_min}-{vi_max}",
            "source": source,
        }
        reference = _SPACE_RE.sub(" ", str(references.get(idx, "") or "")).strip()
        if reference:
            row["verified_reference"] = reference
        rows.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
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
    context = (
        "Some cue rows include verified_reference matched to that exact cue. Use it as strong evidence for correcting obvious recognition errors."
        if has_reference else (
            "The source is machine-recognized song lyrics and may contain recognition mistakes. Use the full supplied song context and language knowledge to correct an error only when the intended lyric is reasonably clear."
        )
    )
    title = str(song_title or "").strip()
    title_context = (
        f" Song metadata only: {title}. Never insert title or artist wording into a cue unless the cue source or same-ID verified reference actually supports it."
        if title else ""
    )
    return (
        "You are a professional lyric subtitle translator for a commercial media player. "
        + context + title_context + " "
        "Translate each cue into natural English and Vietnamese while reading the whole batch as song context. "
        "Preserve every meaningful source part, including extra wording in repeated refrains; never silently drop a suffix, clause, negation, relationship, name, number or meaningful repetition. "
        "Do not invent lyric content or copy wording from song-title/artist metadata into a cue unless the cue source or same-ID verified reference supports it. "
        "Prefer smooth lyric wording over literal prose. Keep it concise enough for subtitles, aiming near the preferred character range when meaning stays complete; exceed the range whenever shortening would lose meaning. "
        "Keep naturally short lines, ad-libs and vocalizations short. If source wording is uncertain, translate it conservatively instead of guessing a prettier line. "
        "Return exactly one line for every non-empty source cue in this format: ID===English translation===Vietnamese translation. "
        "Keep the original ID, output no commentary, no markdown, no extra lines, and never place === or a newline inside a translation."
    )


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
        parts.append(f"SONG: {song_title}")
    if reference_lyric:
        parts.append("REFERENCE LYRICS:\n" + str(reference_lyric).strip())
    if context_before:
        parts.append("PREVIOUS CONTEXT ONLY (do not translate/output): " + str(context_before).strip())
    if context_after:
        parts.append("NEXT CONTEXT ONLY (do not translate/output): " + str(context_after).strip())
    parts.append(
        "CUES (JSONL; preferred character ranges are soft targets):\n"
        + build_translation_rows(
            subs,
            cue_ids=cue_ids,
            verified_references=verified_references,
        )
    )
    return "\n\n".join(parts)
