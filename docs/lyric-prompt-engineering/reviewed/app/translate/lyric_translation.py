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


_FEW_SHOT_EXAMPLES = (
    "Examples show the required fidelity, brevity and format only; never copy their wording into unrelated cues.\n"
    '{"id":0,"duration_s":3.2,"en_preferred_chars":"28-56","vi_preferred_chars":"30-59","source":"夜空に浮かぶ月を見て"}\n'
    "0===Watching the moon float in the night sky===Ngắm vầng trăng lơ lửng giữa trời đêm\n"
    '{"id":1,"duration_s":1.8,"en_preferred_chars":"16-32","vi_preferred_chars":"16-33","source":"Stay with me"}\n'
    "1===Stay with me===Ở lại bên tôi\n"
    '{"id":2,"duration_s":1.2,"en_preferred_chars":"13-26","vi_preferred_chars":"14-28","source":"La la la"}\n'
    "2===La la la===La la la"
)


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
    context = (
        "Use only the supplied same-ID verified reference lyric to correct a recognition mistake when it clearly supports that correction; otherwise preserve the source cue as recognized."
        if has_reference else (
            "The source is machine-recognized song lyrics and may contain minor recognition mistakes; do not repair, complete or reinterpret uncertain wording unless the surrounding cues make the intended wording unambiguous."
        )
    )
    title = str(song_title or "").strip()
    title_context = f" Song context: {title}." if title else ""
    return (
        "You are a professional lyric subtitle translator for a commercial media player. "
        + context + title_context + " "
        "Priority: (1) preserve meaning, (2) sound like a natural lyric subtitle, (3) stay concise. "
        "Each cue's translation must stand alone as a subtitle. Read neighboring cues only to disambiguate the current cue; never borrow meaning from them. "
        "Preserve intent, emotional tone, imagery, negation, modality, relationships, names, numbers and meaningful repetition. Add nothing the current cue or its same-ID verified reference does not say, including a new subject, object, cause, event, metaphor, emotion or degree of certainty. "
        "Use fluent, idiomatic English and contemporary Vietnamese rather than stiff word-for-word prose, but never embellish ambiguous wording. "
        "Aim near each preferred character range; exceed it when shortening would remove or alter meaning. Never pad naturally short lines or reduce full clauses to keyword fragments. "
        "Preserve short ad-libs, vocalizations and refrains instead of turning them into fuller sentences. Keep bracketed non-speech markers as short markers rather than inventing lyric content. "
        "If the source already reads naturally in English or Vietnamese, the same-language target may copy or lightly normalize it; do not paraphrase merely for variety. "
        "In Vietnamese, add a pronoun only when the source or same-ID reference clearly establishes it; otherwise keep the relationship neutral where natural. "
        "Verify each final line keeps the source's meaning and certainty and contains no unsupported detail. "
        "Return exactly one line for every non-empty source cue in this format: ID===English translation===Vietnamese translation. "
        "Keep the original ID, output no commentary, no markdown, no extra lines, and never place === or a newline inside a translation.\n\n"
        + _FEW_SHOT_EXAMPLES
    )


def lyric_translation_user_content(subs, song_title: str = "", reference_lyric: str | None = None) -> str:
    parts = []
    if song_title:
        parts.append(f"SONG: {song_title}")
    if reference_lyric:
        parts.append("REFERENCE LYRICS:\n" + str(reference_lyric).strip())
    parts.append("CUES (JSONL; preferred character ranges are soft targets):\n" + build_translation_rows(subs))
    return "\n\n".join(parts)
