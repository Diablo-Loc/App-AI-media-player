"""Phrase grouping of accepted ASR words, without guessing new timestamps."""
import math

from .aligner import visual_len


def _length(words, join):
    return visual_len(join([word["text"] for word in words]))


def _duration(words):
    return max(word["end"] for word in words) - words[0]["start"]


def _comma(text):
    return text.rstrip('\"\'”’)]}').endswith((",", ";", ":", "，", "、", "；", "："))


def _readable_chunks(words, limit, join):
    """Balance oversized phrases at timed word boundaries, preferring pauses.

    A sustained note alone is not a reason to split. An indivisible word or a
    run with inseparable onsets may exceed the limit; never invent word times.
    """
    while _length(words, join) > limit:
        length = _length(words, join)
        target = length / math.ceil(length / limit)
        candidates = []
        previous_end = words[0]["end"]
        for index in range(1, len(words)):
            before, after = words[index - 1], words[index]
            left_length = _length(words[:index], join)
            if left_length > limit:
                break
            gap = after["start"] - previous_end
            previous_end = max(previous_end, after["end"])
            if (after["start"] <= words[0]["start"] or gap < -0.02
                    or left_length < max(4, target * 0.5)
                    or _length(words[index:], join) < 4):
                continue
            natural = _comma(before["text"]) or gap >= 0.12
            candidates.append((natural, -abs(left_length - target), index))
        if not candidates:
            break
        split = max(candidates)[2]
        yield words[:split]
        words = words[split:]
    if words:
        yield words


def group_words(events, max_chars, min_pause, join, terminal, continued_sources):
    """Yield one readable phrase, retaining short ASR fragments and repetitions.

    ASR segments are useful lyric-line hints, but a tiny segment is often just
    a fragment. Clear punctuation/newlines/pauses take precedence. A small
    intra-segment breath does not by itself end a sentence.
    """
    by_source = {}
    for event in events:
        if not event["fallback"]:
            by_source.setdefault(event["source"], []).append(event)
    standalone = {source: _duration(words) >= 1.5 and _length(words, join) >= 4
                  for source, words in by_source.items()}
    source_text = {source: join([word["text"] for word in words]).casefold()
                   for source, words in by_source.items()}
    limit = max(8, min(max_chars * 3, 128))
    buffer = []
    for event in events:
        if event["fallback"]:
            yield from _readable_chunks(buffer, limit, join)
            buffer = []
            # No word boundaries: retain the whole source cue and its timing.
            yield [event]
            continue
        if buffer:
            previous = buffer[-1]
            gap = event["start"] - max(word["end"] for word in buffer)
            duration = _duration(buffer)
            length = _length(buffer, join)
            repeated_line = (duration > 0 and _duration(by_source[event["source"]]) > 0
                             and length >= 4
                             and join([word["text"] for word in buffer]).casefold()
                             == source_text[event["source"]])
            source_boundary = (event["source"] != previous["source"] and gap >= -0.02
                               and event["source"] not in continued_sources
                               and ((duration >= 1.5 and length >= 4
                                     and standalone[event["source"]]) or repeated_line))
            explicit_boundary = (previous["break_after"] or event["break_before"]
                                 or terminal(previous["text"]))
            soft_boundary = (length >= max_chars and _comma(previous["text"]))
            long_phrase_pause = duration >= 8.0 and gap >= 0.12
            if (explicit_boundary or gap >= min_pause or source_boundary
                    or soft_boundary or long_phrase_pause):
                yield from _readable_chunks(buffer, limit, join)
                buffer = []
        buffer.append(event)
    yield from _readable_chunks(buffer, limit, join)
