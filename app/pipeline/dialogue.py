"""Dialogue-only word grouping; no lyric filters, retries or model loading."""
import math

from .aligner import visual_len
from .lyric_refinement import finalize_cue_times, join_tokens, _terminal


def transcription_options():
    # Keep soft/quiet speech available. The recognizer's own silence guards stay
    # active; no lyric prompt or music-specific recovery is used here.
    return dict(language=None, word_timestamps=True,
                condition_on_previous_text=False, beam_size=3, temperature=0.0,
                vad_filter=False, initial_prompt=None)


def refine_dialogue(segments, cjk=False):
    """Split at real word times, punctuation and pauses, preserving repetitions.

    Speaker diarization is not inferred. Missing/unusable word alignment keeps
    the original whole segment rather than dropping words or inventing times.
    No fixed onset delay or lyric tail is applied to dialogue.
    """
    output = []
    target = 22 if cjk else 84

    def span(item):
        try:
            start, end = float(item["start"]), float(item["end"])
            if math.isfinite(start) and math.isfinite(end) and end >= start:
                return max(0.0, start), max(0.0, end)
        except (KeyError, TypeError, ValueError):
            pass
        return None

    def emit(words):
        if words:
            output.append(dict(start=words[0]["start"],
                               end=max(w["end"] for w in words),
                               text=join_tokens([w["word"] for w in words])))

    for segment in segments:
        text = str(segment.get("text", "") or "").strip()
        interval = span(segment)
        if not text or interval is None:
            continue
        words = []
        usable = True
        for word in segment.get("words") or []:
            token = str(word.get("word", "") or "")
            if not token.strip():
                continue
            timing = span(word)
            if (timing is None or timing[0] < interval[0] - .1
                    or timing[1] > interval[1] + .1
                    or (words and timing[0] < words[-1]["start"])):
                usable = False
                break
            words.append(dict(start=timing[0], end=timing[1], word=token))
        # Full lexical agreement protects segment text when word arrays are
        # incomplete. Whitespace is immaterial to shaped CJK/spaced ASR tokens.
        compact = lambda value: "".join(value.split())
        if (not usable or not words
                or compact("".join(w["word"] for w in words)) != compact(text)):
            output.append(dict(start=interval[0], end=interval[1], text=text))
            continue
        buffer = []
        for word in words:
            if buffer:
                previous_end = max(w["end"] for w in buffer)
                gap = word["start"] - previous_end
                length = visual_len(join_tokens([w["word"] for w in buffer]))
                sentence_end = _terminal(buffer[-1]["word"].strip())
                readable_end = (length >= target or previous_end - buffer[0]["start"] >= 6.0)
                # Overlapping/same-onset words cannot be cut reliably.
                if (word["start"] > buffer[0]["start"] and gap >= -.02
                        and (sentence_end or gap >= .45 or readable_end)):
                    emit(buffer)
                    buffer = []
            buffer.append(word)
        emit(buffer)
    return finalize_cue_times(output)
