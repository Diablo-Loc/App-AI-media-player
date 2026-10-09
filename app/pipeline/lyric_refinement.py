"""Word-based refinement for newly generated lyrics; never used on saved files.

The legacy aligner stays available for old callers. This profile uses acoustic
word boundaries, small display margins, and temporal (not text-only) deduplication.
"""
import math
import re
import unicodedata

from .aligner import is_cjk, refine_segments as legacy_refine, visual_len
from .lyric_phrases import group_words

ONSET_LEAD = 0.05
OFFSET_TAIL = 0.08
FINAL_TIMING_ATTRIBUTE = "_botube_final_timing"
FILLER_TOKENS = {"ha", "haha", "he", "hehe", "hi", "ho", "ah", "oh", "la", "na", "ハ", "は", "ㅋ", "ㅎ"}


def _key(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text).casefold())


def compress_fused_fillers(text):
    """Shorten only runaway, fused nonlexical tokens, never timed repetitions.

    'hahahahahahahahaha' -> 'hahaha'; 'ha ha ha ha' and repeated meaningful
    words/phrases survive. Eight fused units is deliberately conservative.
    """
    return re.sub(
        r"(?<!\w)(ha|he|hi|ho|hà|há|hê|ah|oh|la|na|ハ|は|ㅋ|ㅎ)(?:\1){7,}(?!\w)",
        lambda match: match.group(1) * 3, text, flags=re.IGNORECASE)


def join_tokens(tokens):
    result = ""
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if not result:
            result = token
        elif (is_cjk(result[-1]) and is_cjk(token[0])) or token[0] in ",.;:!?，。！？、；：)]}”’":
            result += token
        elif token.startswith(("'", "’")):
            result += token
        elif result[-1] in "([{“‘":
            result += token
        else:
            result += " " + token
    return result


def _terminal(text):
    stripped = text.rstrip('"\'”’)]}')
    if stripped.endswith(("!", "?", "。", "！", "？")):
        return True
    if not stripped.endswith("."):
        return False
    # Do not split at familiar abbreviations or initials; decimals are one word.
    return not re.fullmatch(r"(?:[A-Za-z]|Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e)\.",
                            stripped, flags=re.IGNORECASE)


def _finite_span(item):
    try:
        start, end = float(item["start"]), float(item["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(start) and math.isfinite(end)) or end < start:
        return None
    return max(0.0, start), max(0.0, end)


def _same_acoustic_span(left, right):
    # A repeated phrase with distinct timestamps is always kept. Padding is not
    # part of this comparison. Zero-duration CJK tokens are never deduplicated.
    a, b = left
    c, d = right
    if b <= a or d <= c:
        return False
    if abs(a - c) > 0.02 or abs(b - d) > 0.02:
        return False
    intersection = max(0.0, min(b, d) - max(a, c))
    return intersection >= 0.85 * (b - a) and intersection >= 0.85 * (d - c)


def accepts_source_text(text, timed_words=False):
    """Keep real lyric vocabulary; reject explicit credit boilerplate only."""
    from .lyric_accuracy import credit_text
    return bool(text.strip()) and not credit_text(text, timed_words=timed_words)


def _compress_unaligned_filler_runs(events):
    """Only shorten long filler runs pinned to the same ASR word timestamps.

    Spaced syllables with advancing times represent separate performances and
    are retained. This cannot determine whether music really contains a voice.
    """
    output, run = [], []

    def flush():
        output.extend(run[:3] if len(run) >= 8 else run)
        run.clear()

    for event in events:
        identity = _key(event["text"])
        if event["fallback"] or identity not in FILLER_TOKENS:
            flush()
            output.append(event)
            continue
        if run and (identity != _key(run[0]["text"]) or event["source"] != run[0]["source"]
                    or abs(event["start"] - run[0]["start"]) > 0.02
                    or abs(event["end"] - run[0]["end"]) > 0.02):
            flush()
        run.append(event)
    flush()
    return output


def finalize_cue_times(cues, duration=None):
    """Copy and enforce finite, ordered, nonoverlapping millisecond intervals.

    Trim an outgoing cue at the incoming onset; do not move both boundaries to
    a padded midpoint or reintroduce overlap through a minimum display duration.
    Inseparable same-onset cues are joined, retaining all their text.
    """
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        duration = None
    output = []
    valid = []
    for cue in cues:
        span = _finite_span(cue)
        if span is None or not cue.get("text", "").strip():
            continue
        start, end = span
        if duration is not None:
            if start >= duration:
                continue
            end = min(end, duration)
        item = dict(cue, start=round(start, 3), end=round(max(start + 0.02, end), 3))
        if duration is not None:
            item["end"] = min(item["end"], math.floor(duration * 1000) / 1000)
        valid.append(item)
    for item in sorted(valid, key=lambda cue: cue["start"]):
        if output and item["start"] <= output[-1]["start"]:
            previous = output[-1]
            previous["text"] = join_tokens([previous["text"], item["text"]])
            previous["end"] = max(previous["end"], item["end"])
        else:
            output.append(item)
    for previous, following in zip(output, output[1:]):
        previous["end"] = min(previous["end"], following["start"])
    return [cue for cue in output if cue["end"] > cue["start"]]


def refine_lyrics(segments, max_chars=22, min_pause=0.54, start_offset=-0.2,
                  end_padding=0.27, gap_threshold=0.6, memory_reset_t=3.0):
    """New-generation profile; signature accepts existing orchestration options.

    start_offset/end_padding/gap_threshold/memory_reset_t are legacy settings,
    intentionally superseded by the word-boundary and temporal-identity rules.
    max_chars is a soft display target; punctuation/pause gets priority over an
    arbitrary character count. Phrase grouping preserves useful ASR line hints
    while joining tiny fragments; sustained notes do not force a timed cut.
    """
    events = []
    seen_segments = {}
    for source, segment in enumerate(segments):
        text = segment.get("text", "").strip()
        span = _finite_span(segment)
        if not text or span is None:
            continue
        words = []
        for word in segment.get("words") or []:
            timing = _finite_span(word)
            token = word.get("word", "")
            if timing is None or not token.strip():
                continue
            words.append(dict(start=timing[0], end=timing[1],
                              text=compress_fused_fillers(token.replace("\n", " ").replace("\r", " ").strip()),
                              source=source, break_before="\n" in token[:len(token) - len(token.lstrip())],
                              break_after="\n" in token[len(token.rstrip()):], fallback=False))
        if not accepts_source_text(text, timed_words=bool(words)):
            continue
        identity = _key(text)
        previous = seen_segments.get(identity)
        if previous is not None and _same_acoustic_span(span, previous):
            continue
        seen_segments[identity] = span
        if words:
            events.extend(words)
        else:
            events.append(dict(start=span[0], end=span[1], text=compress_fused_fillers(text),
                               source=source, newline=True, fallback=True))

    accepted_events = []
    seen_words = {}
    continued_sources = set()
    for event in _compress_unaligned_filler_runs(sorted(events, key=lambda item: item["start"])):
        if event["fallback"]:
            accepted_events.append(event)
            continue
        identity = _key(event["text"])
        previous = seen_words.get(identity)
        if previous is not None and previous["source"] != event["source"] and _same_acoustic_span(
                (event["start"], event["end"]), (previous["start"], previous["end"])):
            continued_sources.add(event["source"])
            continue
        seen_words[identity] = event
        accepted_events.append(event)
    output = []
    for phrase in group_words(accepted_events, max_chars, min_pause, join_tokens, _terminal,
                              continued_sources):
        output.append(dict(start=max(0.0, phrase[0]["start"] - ONSET_LEAD),
                           end=max(word["end"] for word in phrase) + OFFSET_TAIL,
                           text=phrase[0]["text"] if phrase[0]["fallback"] else
                           join_tokens([word["text"] for word in phrase])))
    return finalize_cue_times(output)


def finalize_display_times(cues, cjk=False, duration=None):
    """Apply playback margins once, after recognition and coverage are complete.

    Coverage keeps the existing narrow word margins. Playback restores v3.1's
    CJK onset (+100 ms from the word) and saved tails (370/700 ms). Latin cues
    start at their word onset instead of adding the old early storage padding.
    Only the outgoing tail is clipped at the next cue; no padded midpoint moves
    that cue's onset. Very short cues retain room for their original text.
    """
    cues = finalize_cue_times(cues, duration=duration)
    onset_shift = ONSET_LEAD + (0.1 if cjk else 0.0)
    tail_shift = (0.37 if cjk else 0.7) - OFFSET_TAIL
    output = []
    for cue in cues:
        start = min(cue["start"] + onset_shift,
                    max(cue["start"], cue["end"] - 0.02))
        output.append(dict(cue, start=start, end=cue["end"] + tail_shift))
    return finalize_cue_times(output, duration=duration)


def mark_final_timing(subtitles):
    """Runtime-only marker survives spawn/pickle; persisted schemas stay unchanged.

    Apply after translation so provider adapters cannot drop it. Only the new
    production ASR path calls this; loading/editing old JSON never calls it.
    """
    for subtitle in subtitles:
        setattr(subtitle, FINAL_TIMING_ATTRIBUTE, True)
