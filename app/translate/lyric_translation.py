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


def build_translation_rows(subs) -> str:
    """Encode cues as JSONL so source text cannot collide with output delimiters."""
    rows = []
    for idx, cue in enumerate(subs):
        source = _source_text(cue)
        if not source:
            continue
        duration = cue_duration_seconds(cue)
        en_min, en_max = soft_character_range(duration, "en")
        vi_min, vi_max = soft_character_range(duration, "vi")
        rows.append(json.dumps({
            "id": idx,
            "duration_s": round(duration, 2),
            "en_preferred_chars": f"{en_min}-{en_max}",
            "vi_preferred_chars": f"{vi_min}-{vi_max}",
            "source": source,
        }, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(rows)


def lyric_translation_system_prompt(song_title: str = "", has_reference: bool = False) -> str:
    context = "Use the supplied reference lyrics to correct recognition mistakes before translating." if has_reference else (
        "The source is machine-recognized song lyrics and may contain minor recognition mistakes; use song context conservatively."
    )
    title = str(song_title or "").strip()
    title_context = f" Song context: {title}." if title else ""
    return (
        "You are a professional lyric subtitle translator for a commercial media player. "
        + context + title_context + " "
        "Translate every cue independently into natural English and Vietnamese while using surrounding cues only for context. "
        "Keep the original meaning, intent, emotional tone, imagery, negation, modality, relationships, names, numbers and meaningful repetition. "
        "Do not merge meaning across cue IDs and do not invent explanations. "
        "Write polished lyric subtitles rather than literal prose. Prefer natural, emotionally faithful lyric wording with good flow and cadence; a modest poetic turn is welcome when it is directly supported by the source, but never invent new meaning. "
        "Do not translate word-for-word when a more idiomatic lyric line carries the same meaning. Keep important imagery and emotional color even when the shortest wording would sound stiff. "
        "The per-cue preferred character ranges are soft readability targets, not a compression target. Aim near them when natural, and freely exceed them a little when that makes the lyric smoother, clearer or more expressive without adding meaning. "
        "Naturally short source lines may stay shorter than the preferred range; never pad them. For normal full clauses, do not collapse the translation into keyword fragments, telegram-style wording or awkwardly terse phrasing. "
        "Preserve intentional refrains and repeated words when they are part of the lyric. "
        "For Vietnamese, favor fluent contemporary lyric language that sounds like a real song subtitle, with natural pronouns and word order; omit pronouns only when the source leaves them implicit and the relationship remains unambiguous. "
        "For English, favor idiomatic lyric phrasing and natural rhythm without adding subjects, metaphors or explanations absent from the source. "
        "Before answering, silently revise lines that sound mechanical, overly literal or needlessly long, choosing a smoother equivalent that preserves the same meaning. "
        "Return exactly one line for every non-empty source cue in this format: ID===English translation===Vietnamese translation. "
        "Keep the original ID, output no commentary, no markdown, no extra lines, and never place === or a newline inside a translation."
    )


def lyric_translation_user_content(subs, song_title: str = "", reference_lyric: str | None = None) -> str:
    parts = []
    if song_title:
        parts.append(f"SONG: {song_title}")
    if reference_lyric:
        parts.append("REFERENCE LYRICS:\n" + str(reference_lyric).strip())
    parts.append("CUES (JSONL; preferred character ranges are soft targets):\n" + build_translation_rows(subs))
    return "\n\n".join(parts)
