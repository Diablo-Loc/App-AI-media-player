"""Recover omitted speech while preserving accepted cue structure."""
import math
import re
from difflib import SequenceMatcher

from .aligner import refine_segments
from .jp_normalizer import universal_text_reconstruct

SAMPLE_RATE = 16000
WINDOW_SECONDS = 12.0
WINDOW_OVERLAP = 2.0
MIN_GAP_SECONDS = 4.0
AUDIT_MIN_GAP_SECONDS = 0.22
MIN_VOICED_GAP_SECONDS = 0.20
SHORT_GAP_WORD_PROB = 0.58
SHORT_GAP_LOGPROB = -0.72
SHORT_GAP_MAX_NO_SPEECH = 0.35
MIN_RECOVERY_WORD_PROBABILITY = 0.12
MIN_RECOVERY_SPEECH_FRACTION = 0.30
RECOVERY_VERIFY_NO_SPEECH_THRESHOLD = 0.60
RECOVERY_VERIFY_LOG_PROB_THRESHOLD = -1.0
RECOVERY_VERIFY_HALLUCINATION_SILENCE = 1.0
RETRY_CONTEXT_SECONDS = 1.35
LOW_PRIMARY_LOGPROB = -0.85
LOW_PRIMARY_WORD_PROB = 0.48
HIGH_PRIMARY_NO_SPEECH = 0.55
STRONG_RETRY_LOGPROB = -0.68
STRONG_RETRY_WORD_PROB = 0.60
MIN_WORD_PROB_GAIN = 0.10
MIN_LOGPROB_GAIN = 0.22
NEIGHBOR_TIMING_JITTER = 0.18


def _uncertain_filler(text):
    tokens = re.findall(r"[\w]+", text.lower())
    normalized = " ".join(tokens)
    if re.search(r"\b(?:thanks|thank you|you) for watching\b", normalized):
        return True
    if re.search(
        r"\b(?:we (?:ll|will) be right back|"
        r"(?:we (?:ll|will) )?see you next time|"
        r"i ll see you in (?:the )?next video|"
        r"see you in (?:the )?next video)\b",
        normalized,
    ):
        return True
    if normalized in {"thank you", "thanks", "for watching"}:
        return True
    # Music often produces confident 'oh/ah' hallucinations. Do not add those
    # solely from a gap retry; the original accepted lyrics remain untouched.
    return bool(tokens) and all(token in {"oh", "ooh", "ah", "aah", "hmm", "mm", "la", "na"}
                                for token in tokens)


def missing_ranges(cues, duration, min_gap=MIN_GAP_SECONDS):
    """Uncovered timeline ranges, including the beginning and end of the audio."""
    ranges = []
    cursor = 0.0
    for cue in sorted(cues, key=lambda cue: cue["start"]):
        start = min(duration, max(0.0, float(cue["start"])))
        end = min(duration, max(start, float(cue["end"])))
        if start - cursor >= min_gap:
            ranges.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= min_gap:
        ranges.append((cursor, duration))
    return ranges


def overlap(left, right, spans):
    return sum(max(0.0, min(right, end) - max(left, start)) for start, end in spans)


def _finite(value, default=None):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _mean_word_probability(segment):
    values = []
    for item in getattr(segment, "words", None) or ():
        value = _finite(getattr(item, "probability", None))
        if value is not None:
            values.append(value)
    return sum(values) / len(values) if values else None


def _segment_confidence(segment):
    return {
        "word_probability": _mean_word_probability(segment),
        "avg_logprob": _finite(getattr(segment, "avg_logprob", None)),
        "no_speech_prob": _finite(getattr(segment, "no_speech_prob", None), 0.0),
    }


def _primary_suspects(primary_segments, duration):
    """Weak primary spans may receive one bounded local verification."""
    suspects = []
    for index, segment in enumerate(primary_segments or ()):
        start = _finite(getattr(segment, "start", None))
        end = _finite(getattr(segment, "end", None))
        text = str(getattr(segment, "text", "") or "").strip()
        if start is None or end is None or end <= start or not text:
            continue
        start = min(duration, max(0.0, start))
        end = min(duration, max(start, end))
        if end - start < 0.18:
            continue
        confidence = _segment_confidence(segment)
        word_probability = confidence["word_probability"]
        avg_logprob = confidence["avg_logprob"]
        no_speech_prob = confidence["no_speech_prob"] or 0.0
        weak_words = word_probability is not None and word_probability < LOW_PRIMARY_WORD_PROB
        weak_segment = avg_logprob is not None and avg_logprob < LOW_PRIMARY_LOGPROB
        likely_nonspeech = (
            no_speech_prob >= HIGH_PRIMARY_NO_SPEECH
            and (word_probability is None or word_probability < 0.62)
        )
        if weak_words or weak_segment or likely_nonspeech:
            suspects.append({
                "id": index,
                "start": start,
                "end": end,
                "text": text,
                **confidence,
            })
    return suspects


def _primary_coverage_cues(primary_segments, duration):
    """Acoustic primary coverage, excluding rejected boilerplate and display padding."""
    if not primary_segments:
        return []
    from .lyric_accuracy import credit_text

    coverage = []
    for segment in primary_segments:
        text = str(getattr(segment, "text", "") or "").strip()
        words = []
        for word in getattr(segment, "words", None) or ():
            word_text = str(getattr(word, "word", "") or "").strip()
            start = _finite(getattr(word, "start", None))
            end = _finite(getattr(word, "end", None))
            if word_text and start is not None and end is not None and end >= start:
                words.append((start, end))
        if (not text or _uncertain_filler(text)
                or credit_text(text, timed_words=bool(words))):
            continue
        if words:
            start = min(item[0] for item in words)
            end = max(item[1] for item in words)
        else:
            start = _finite(getattr(segment, "start", None))
            end = _finite(getattr(segment, "end", None))
        if start is None or end is None or end <= start:
            continue
        start = min(duration, max(0.0, start))
        end = min(duration, max(start, end))
        if end > start:
            coverage.append({"start": start, "end": end, "text": text})
    return coverage


def _normalized_recovery_text(text):
    return re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "", str(text or "").casefold())


def _decoded_evidence(segments, offset):
    evidence = []
    for segment in segments or ():
        text = _normalized_recovery_text(getattr(segment, "text", ""))
        start = offset + float(getattr(segment, "start", 0.0))
        end = offset + float(getattr(segment, "end", start))
        if text and math.isfinite(start) and math.isfinite(end) and end > start:
            evidence.append((start, end, text))
    return evidence


def _supported_by_prior_decode(cue, evidence):
    text = _normalized_recovery_text(cue.get("text", ""))
    if not text:
        return False
    for start, end, other in evidence:
        time_overlap = min(float(cue["end"]), end) - max(float(cue["start"]), start)
        if time_overlap < 0.25:
            continue
        if text == other or (min(len(text), len(other)) >= 5 and (text in other or other in text)):
            return True
        if SequenceMatcher(None, text, other).ratio() >= 0.62:
            return True
    return False


def _verified_recovery_evidence(model, clip, offset, language, cancel_cb=None):
    """Re-decode one recovery clip conservatively before any new cue is accepted."""
    _check_cancel(cancel_cb)
    generator, _ = model.transcribe(
        clip,
        language=language,
        word_timestamps=True,
        condition_on_previous_text=False,
        # Keep the verifier's strict silence/hallucination guards, but do not
        # reduce lyric search quality versus the recovery decode itself.  A
        # greedy/single-beam pass can miss quiet sung words that beam=3 already
        # decoded correctly, which turns a safety check into a false deletion.
        beam_size=3,
        temperature=0.0,
        vad_filter=False,
        initial_prompt=None,
        no_speech_threshold=RECOVERY_VERIFY_NO_SPEECH_THRESHOLD,
        log_prob_threshold=RECOVERY_VERIFY_LOG_PROB_THRESHOLD,
        hallucination_silence_threshold=RECOVERY_VERIFY_HALLUCINATION_SILENCE,
    )
    verified = []
    for segment in generator:
        _check_cancel(cancel_cb)
        verified.append(segment)
    return _decoded_evidence(verified, offset)


def _needs_recovery_verification(cue, gaps, speech, duration):
    """Use the expensive strict verifier only where false positives are likeliest."""
    start = float(cue["start"])
    end = float(cue["end"])
    cue_duration = max(0.001, end - start)
    for gap_start, gap_end in gaps:
        if start < gap_start or start >= gap_end:
            continue
        if gap_end - gap_start < MIN_GAP_SECONDS:
            return True
        if gap_start <= 0.01 or gap_end >= duration - 0.01:
            return True
        return overlap(start, end, speech) / cue_duration < 0.55
    return True


def plan_windows(gaps, speech, duration, min_overlap=0.35):
    windows = []
    for left, right in gaps:
        cursor = max(0.0, left - WINDOW_OVERLAP)
        while cursor < right:
            end = min(duration, cursor + WINDOW_SECONDS)
            if end <= cursor:
                break
            if overlap(max(left, cursor), min(right, end), speech) >= min_overlap:
                windows.append((cursor, end))
            if end >= right:
                break
            cursor += WINDOW_SECONDS - WINDOW_OVERLAP
    return windows


def _gap_overlap_requirement(gap):
    return MIN_VOICED_GAP_SECONDS if gap[1] - gap[0] < MIN_GAP_SECONDS else 0.35


def _voiced_gaps(gaps, speech):
    return [
        gap for gap in gaps
        if overlap(gap[0], gap[1], speech) >= _gap_overlap_requirement(gap)
    ]


def _plan_gap_windows(gaps, speech, duration):
    windows = []
    for gap in gaps:
        windows.extend(plan_windows(
            [gap], speech, duration, min_overlap=_gap_overlap_requirement(gap)
        ))
    return windows


def _merge_windows(windows, duration):
    """Coalesce retry windows while keeping every local decode at most 12 seconds."""
    merged = []
    for left, right in sorted(windows):
        left = max(0.0, min(duration, left))
        right = max(left, min(duration, right))
        if right <= left:
            continue
        if merged and left <= merged[-1][1] + 0.20:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    bounded = []
    for left, right in merged:
        cursor = left
        while right - cursor > WINDOW_SECONDS:
            bounded.append((cursor, cursor + WINDOW_SECONDS))
            cursor += WINDOW_SECONDS - WINDOW_OVERLAP
        if right > cursor:
            bounded.append((cursor, right))
    return bounded


def _suspect_windows(suspects, duration):
    windows = []
    for item in suspects:
        left = max(0.0, item["start"] - RETRY_CONTEXT_SECONDS)
        right = min(duration, item["end"] + RETRY_CONTEXT_SECONDS)
        if right - left > WINDOW_SECONDS:
            middle = (item["start"] + item["end"]) / 2
            left = max(0.0, middle - WINDOW_SECONDS / 2)
            right = min(duration, left + WINDOW_SECONDS)
            left = max(0.0, right - WINDOW_SECONDS)
        windows.append((left, right))
    return _merge_windows(windows, duration)


def _meaningful_overlap(left, right, other_left, other_right, minimum=0.20):
    return max(0.0, min(right, other_right) - max(left, other_left)) >= minimum


def _strong_retry_segment(segment, primary):
    confidence = _segment_confidence(segment)
    word_probability = confidence["word_probability"]
    avg_logprob = confidence["avg_logprob"]
    if word_probability is None or avg_logprob is None:
        return False
    if word_probability < STRONG_RETRY_WORD_PROB or avg_logprob < STRONG_RETRY_LOGPROB:
        return False
    primary_word = primary.get("word_probability")
    primary_logprob = primary.get("avg_logprob")
    word_gain = primary_word is not None and word_probability >= primary_word + MIN_WORD_PROB_GAIN
    logprob_gain = primary_logprob is not None and avg_logprob >= primary_logprob + MIN_LOGPROB_GAIN
    return word_gain or logprob_gain


def _compatible_replacement_text(old_text, new_text):
    """Fail open unless a stronger retry clearly restores truncated text."""
    old = _normalized_recovery_text(old_text)
    new = _normalized_recovery_text(new_text)
    if not old or not new or old == new:
        return False
    # ASR-only evidence is safe for restoring a clearly truncated phrase, but
    # it is not strong enough to choose between close homophones/characters.
    # Those lexical corrections require an independently verified lyric source.
    return len(new) >= len(old) + 2 and old in new


def _replacement_from_retry(decoded, offset, clip_end, primary, refine_options,
                            refine_fn=refine_segments):
    """Return one materially stronger local phrase for a weak primary span."""
    choices = []
    for segment in decoded:
        local_start = _finite(getattr(segment, "start", None))
        local_end = _finite(getattr(segment, "end", None))
        if local_start is None or local_end is None:
            continue
        start = offset + local_start
        end = offset + local_end
        if start < offset or end <= start or end > clip_end + 0.02:
            continue
        intersection = max(0.0, min(end, primary["end"]) - max(start, primary["start"]))
        retry_duration = end - start
        primary_duration = primary["end"] - primary["start"]
        if intersection < max(0.25, 0.60 * min(retry_duration, primary_duration)):
            continue
        if not _strong_retry_segment(segment, primary):
            continue
        selected_words = []
        words = []
        for item in getattr(segment, "words", None) or ():
            word_start = _finite(getattr(item, "start", None))
            word_end = _finite(getattr(item, "end", None))
            word_text = str(getattr(item, "word", "") or "")
            if word_start is None or word_end is None:
                continue
            word_start += offset
            word_end += offset
            if word_start < offset or word_end < word_start or word_end > clip_end + 0.02:
                continue
            if word_text.strip():
                selected_words.append(item)
                words.append({"start": word_start, "end": word_end, "word": word_text})
        if not words:
            continue
        text = universal_text_reconstruct(selected_words, getattr(segment, "text", ""))
        if not text.strip() or _uncertain_filler(text):
            continue
        if not _compatible_replacement_text(primary["text"], text):
            continue
        check = {"start": start, "end": end, "text": text, "words": words}
        refined = refine_fn([check], **refine_options)
        if len(refined) != 1:
            continue
        confidence = _segment_confidence(segment)
        replacement = dict(refined[0])
        # Keep raw word bounds as private evidence. Display padding from refine_fn
        # must not expand an accepted cue into its neighbours.
        replacement["_evidence_start"] = words[0]["start"]
        replacement["_evidence_end"] = words[-1]["end"]
        choices.append((confidence["word_probability"], confidence["avg_logprob"], replacement))
    if not choices:
        return None
    return max(choices, key=lambda item: (item[0], item[1]))[2]


def _apply_text_replacement(cues, primary, replacement, speech=()):
    """Restore a truncated weak cue without crossing neighbouring cue bounds."""
    matches = []
    for index, cue in enumerate(cues):
        start = _finite(cue.get("start"))
        end = _finite(cue.get("end"))
        if start is None or end is None or end <= start:
            continue
        intersection = max(0.0, min(end, primary["end"]) - max(start, primary["start"]))
        if intersection >= max(
            0.20,
            0.45 * min(end - start, primary["end"] - primary["start"]),
        ):
            matches.append(index)
    if len(matches) != 1:
        return cues, False
    index = matches[0]
    old_text = str(cues[index].get("text", "") or "").strip()
    new_text = str(replacement.get("text", "") or "").strip()
    if not new_text or not _compatible_replacement_text(old_text, new_text):
        return cues, False

    old_start = _finite(cues[index].get("start"))
    old_end = _finite(cues[index].get("end"))
    evidence_start = _finite(replacement.get("_evidence_start"), old_start)
    evidence_end = _finite(replacement.get("_evidence_end"), old_end)
    new_start = min(old_start, evidence_start)
    new_end = max(old_end, evidence_end)

    # Existing neighbouring cues remain authoritative. If retry word timing
    # slightly overlaps their display span, clamp at that boundary rather than
    # splitting/rewriting either cue.
    left_limit = 0.0
    right_limit = math.inf
    for other_index, other in enumerate(cues):
        if other_index == index:
            continue
        other_start = _finite(other.get("start"))
        other_end = _finite(other.get("end"))
        if other_start is None or other_end is None or other_end <= other_start:
            continue
        if other_end <= old_start + 0.02:
            left_limit = max(left_limit, other_end)
        elif other_start >= old_end - 0.02:
            right_limit = min(right_limit, other_start)
        elif max(0.0, min(old_end, other_end) - max(old_start, other_start)) > 0.02:
            return cues, False
    if evidence_start < left_limit - NEIGHBOR_TIMING_JITTER:
        return cues, False
    if evidence_end > right_limit + NEIGHBOR_TIMING_JITTER:
        return cues, False
    new_start = max(new_start, left_limit)
    new_end = min(new_end, right_limit)
    if new_end <= new_start:
        return cues, False

    # A materially extended timestamp needs independent voice evidence in the
    # newly claimed area. This keeps instrumental gaps from being absorbed by a
    # stronger-looking local decode.
    extensions = []
    if old_start - new_start > 0.02:
        extensions.append((new_start, old_start))
    if new_end - old_end > 0.02:
        extensions.append((old_end, new_end))
    for left, right in extensions:
        required = min(right - left, max(
            MIN_VOICED_GAP_SECONDS,
            (right - left) * MIN_RECOVERY_SPEECH_FRACTION,
        ))
        if overlap(left, right, speech) < required:
            return cues, False

    updated = list(cues)
    updated[index] = dict(cues[index], start=new_start, end=new_end, text=new_text)
    return updated, True


def _expand_verified_primary_coverage(coverage, primary, replacement):
    """Teach gap auditing only about the one primary span a retry verified."""
    if not coverage:
        return
    matches = []
    for cue in coverage:
        start = _finite(cue.get("start"))
        end = _finite(cue.get("end"))
        if start is None or end is None or end <= start:
            continue
        intersection = max(0.0, min(end, primary["end"]) - max(start, primary["start"]))
        if intersection >= max(
            0.20,
            0.45 * min(end - start, primary["end"] - primary["start"]),
        ):
            matches.append(cue)
    if len(matches) != 1:
        return
    evidence_start = _finite(replacement.get("_evidence_start"))
    evidence_end = _finite(replacement.get("_evidence_end"))
    if evidence_start is not None:
        matches[0]["start"] = min(matches[0]["start"], evidence_start)
    if evidence_end is not None:
        matches[0]["end"] = max(matches[0]["end"], evidence_end)


def _retry_budget(duration):
    """Bound optional recovery work for both short and long media."""
    return min(24, max(10, int(math.ceil(max(1.0, duration) / 60.0)) * 4))


def _check_cancel(cancel_cb):
    if cancel_cb and cancel_cb():
        raise RuntimeError("AI cancelled by user")


def _candidate_cues(segments, offset, clip_end, gaps, speech, refine_options, duration,
                    refine_fn=refine_segments, boundary_gap=0.12, boundary_tolerance=0.0):
    """Only timestamped words inside the missing area can become new cues."""
    raw = []
    for segment in segments:
        if getattr(segment, "avg_logprob", -math.inf) < -1.0:
            continue
        if _uncertain_filler(segment.text):
            continue
        for gap_start, gap_end in gaps:
            words = []
            for word in segment.words or []:
                start, end = offset + word.start, offset + word.end
                if not (math.isfinite(start) and math.isfinite(end)):
                    continue
                # Do not retain words generated beyond the real cropped audio.
                if start < offset or end > clip_end + 0.02 or end < start:
                    continue
                margin = boundary_gap if gap_end < duration else 0.0
                tolerance = boundary_tolerance if gap_end < duration else 0.0
                # Slight boundary jitter must not remove a whole final word.
                # Its display tail is clipped below, never put over the next cue.
                if start < gap_start or start >= gap_end or end + margin > gap_end + tolerance:
                    continue
                if word.word and word.word.strip():
                    words.append(word)
            if not words:
                continue
            word_probabilities = [getattr(word, "probability", math.nan) for word in words]
            if any(not math.isfinite(value) or value < MIN_RECOVERY_WORD_PROBABILITY
                   for value in word_probabilities):
                continue
            probability = sum(word_probabilities) / len(word_probabilities)
            if not math.isfinite(probability) or probability < 0.35:
                continue
            if gap_end - gap_start < MIN_GAP_SECONDS:
                segment_logprob = _finite(getattr(segment, "avg_logprob", None), -math.inf)
                no_speech_prob = _finite(getattr(segment, "no_speech_prob", None), 0.0)
                if (probability < SHORT_GAP_WORD_PROB
                        or segment_logprob < SHORT_GAP_LOGPROB
                        or no_speech_prob > SHORT_GAP_MAX_NO_SPEECH):
                    continue
            # Check the original complete text first: slicing words must not
            # turn a rejected credit into an apparently acceptable fragment.
            check = {"start": offset + segment.start, "end": offset + segment.end,
                     "text": universal_text_reconstruct(segment.words, segment.text),
                     "words": [{"start": offset + word.start, "end": offset + word.end,
                                "word": word.word} for word in segment.words or []]}
            if not refine_fn([check], **refine_options):
                continue
            raw.append({"start": offset + words[0].start, "end": offset + words[-1].end,
                        "text": universal_text_reconstruct(words, segment.text),
                        "words": [{"start": offset + word.start, "end": offset + word.end,
                                   "word": word.word} for word in words]})
    result = []
    for cue in refine_fn(raw, **refine_options):
        # The new profile has a slight display lead. Keep that lead inside the
        # uncovered interval so it cannot suppress an otherwise valid candidate.
        for left, right in gaps:
            if cue["start"] >= left - 0.05 and cue["start"] < right:
                cue["start"] = max(left, cue["start"])
                break
        cue["end"] = min(cue["end"], duration)
        for left, right in gaps:
            if cue["start"] >= left and cue["start"] < right:
                cue["end"] = min(cue["end"], right - boundary_gap if right < duration else right)
                break
        if cue["end"] <= cue["start"]:
            continue
        if _uncertain_filler(cue["text"]):
            continue
        if overlap(cue["start"], cue["end"], speech) < max(
            0.25, (cue["end"] - cue["start"]) * MIN_RECOVERY_SPEECH_FRACTION
        ):
            continue
        if any(cue["start"] >= left and cue["end"] <= right for left, right in gaps):
            result.append(cue)
    return result


def merge_recovered(existing, candidates, safe_gap=0.12, overlap_tolerance=0.0):
    """Never rewrite the text/timing of an existing cue, including repeated lyrics."""
    result = list(existing)
    # Prefer a complete phrase from an overlapping clip over a truncated edge.
    # Only recovery candidates compete; original cues always win.
    for cue in sorted(candidates, key=lambda cue: (-(cue["end"] - cue["start"]),
                                                  -len(cue["text"]), cue["start"])):
        if any(cue["start"] < old["end"] + safe_gap - overlap_tolerance
               and cue["end"] > old["start"] - safe_gap + overlap_tolerance
               for old in result):
            continue
        result.append(cue)
    return sorted(result, key=lambda cue: cue["start"])


def repair_missing_subtitles(model, audio_path, language, cues, refine_options,
                             cancel_cb=None, progress_cb=None, refine_fn=refine_segments,
                             boundary_gap=0.12, boundary_tolerance=0.0,
                             primary_segments=None):
    """Retry missing speech in bounded clips using the already loaded model.

    VAD only selects retries; it never removes audio from the primary pass.
    Returns cues and a diagnostic report, not a claim of perfect recognition.
    """
    import wave
    with wave.open(str(audio_path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    long_gaps = missing_ranges(cues, duration)
    primary_coverage = _primary_coverage_cues(primary_segments, duration)
    coverage_cues = list(primary_coverage or cues)
    audit_gaps = missing_ranges(coverage_cues, duration, min_gap=AUDIT_MIN_GAP_SECONDS)
    # Keep the authoritative primary gaps immutable for candidate extraction.
    # Accepted recovery cues are provisional evidence: they may suppress
    # unnecessary future retries, but must not split a later overlapping local
    # decode into leftover fragments.  Overlapping recovery candidates already
    # compete in merge_recovered(), while original/primary cues always win.
    recovery_bounds = list(audit_gaps)
    suspects = _primary_suspects(primary_segments, duration)
    report = {
        "duration": duration,
        "gaps_before": long_gaps,
        "audit_gaps_before": audit_gaps,
        "attempts": [],
        "added_cues": 0,
        "replaced_cues": 0,
        "confidence_suspects": len(suspects),
        "coverage_basis": "primary_asr" if primary_coverage else "refined_cues",
    }
    if not audit_gaps and not suspects:
        report["unresolved_speech"] = []
        return cues, report
    _check_cancel(cancel_cb)
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import get_speech_timestamps
    waveform = decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE)
    _check_cancel(cancel_cb)
    # Local bundled Silero model. Never change the primary ASR's vad_filter.
    speech = [(span["start"] / SAMPLE_RATE, span["end"] / SAMPLE_RATE)
              for span in get_speech_timestamps(waveform)]
    report["speech"] = speech
    suspects = [
        item for item in suspects
        if overlap(item["start"], item["end"], speech) >= MIN_VOICED_GAP_SECONDS
    ]
    report["voiced_confidence_suspects"] = len(suspects)
    _check_cancel(cancel_cb)
    accepted_base = list(cues)
    combined = list(accepted_base)
    recovered = []
    attempted = set()
    first_round_evidence = []
    windows = _merge_windows(
        _plan_gap_windows(_voiced_gaps(audit_gaps, speech), speech, duration)
        + _suspect_windows(suspects, duration),
        duration,
    )
    budget = _retry_budget(duration)
    windows = windows[:budget]
    checked_suspects = set()
    for round_index in range(2):
        for left, right in windows:
            if len(attempted) >= budget:
                break
            token = (round(left, 3), round(right, 3))
            if token in attempted:
                continue
            attempted.add(token)
            _check_cancel(cancel_cb)
            current_gaps = missing_ranges(
                coverage_cues, duration, min_gap=AUDIT_MIN_GAP_SECONDS
            )
            current_voiced_gaps = _voiced_gaps(current_gaps, speech)
            pending_suspects = [
                item for item in suspects
                if item["id"] not in checked_suspects
                and _meaningful_overlap(left, right, item["start"], item["end"])
            ]
            if not any(
                min(right, gap_end) - max(left, gap_start) >= MIN_VOICED_GAP_SECONDS
                for gap_start, gap_end in current_voiced_gaps
            ) and not pending_suspects:
                continue
            if progress_cb:
                progress_cb(57, f"🛠 Kiểm tra lời bị thiếu: {left:.1f}–{right:.1f}s")
            # Explicit waveform slicing is reliable on the pinned 1.0.2 runtime;
            # clip_timestamps can still yield words past a padded clip boundary.
            clip = waveform[round(left * SAMPLE_RATE):round(right * SAMPLE_RATE)]
            try:
                generator, _ = model.transcribe(clip, language=language, word_timestamps=True,
                    condition_on_previous_text=False, beam_size=3, temperature=0.0,
                    vad_filter=False, initial_prompt=None, no_speech_threshold=None)
                decoded = []
                for segment in generator:
                    _check_cancel(cancel_cb)
                    decoded.append(segment)
            except Exception as error:
                _check_cancel(cancel_cb)
                report["error"] = str(error)
                break
            if round_index == 0:
                first_round_evidence.extend(_decoded_evidence(decoded, left))
            candidates = _candidate_cues(decoded, left, right, recovery_bounds, speech,
                                          refine_options, duration, refine_fn=refine_fn,
                                          boundary_gap=boundary_gap, boundary_tolerance=boundary_tolerance)
            proposed = len(candidates)
            verify_candidates = [
                item for item in candidates
                if _needs_recovery_verification(item, current_gaps, speech, duration)
            ]
            if verify_candidates:
                verification_ids = {id(item) for item in verify_candidates}
                try:
                    verification_evidence = _verified_recovery_evidence(
                        model, clip, left, language, cancel_cb=cancel_cb
                    )
                    candidates = [
                        item for item in candidates
                        if id(item) not in verification_ids
                        or _supported_by_prior_decode(item, verification_evidence)
                    ]
                except RuntimeError:
                    raise
                except Exception as error:
                    # Recovery is optional: a failed verifier must never inject
                    # an unconfirmed cue or erase the authoritative primary pass.
                    report.setdefault("verification_errors", []).append({
                        "start": left,
                        "end": right,
                        "error": str(error),
                    })
                    candidates = []
            if round_index > 0:
                # Round two exists to fix crop/boundary misses, not to invent a
                # brand-new lyric hypothesis. Require matching timestamped text
                # evidence from the first local decode before accepting it.
                candidates = [
                    item for item in candidates
                    if _supported_by_prior_decode(item, first_round_evidence)
                ]
            before = len(combined)
            recovered.extend(candidates)
            replacements = 0
            for primary in pending_suspects:
                checked_suspects.add(primary["id"])
                replacement = _replacement_from_retry(
                    decoded, left, right, primary, refine_options, refine_fn=refine_fn
                )
                if replacement is None:
                    continue
                accepted_base, changed = _apply_text_replacement(
                    accepted_base, primary, replacement, speech=speech
                )
                if changed:
                    _expand_verified_primary_coverage(primary_coverage, primary, replacement)
                    replacements += 1
                    report["replaced_cues"] += 1
            combined = merge_recovered(
                accepted_base,
                recovered,
                safe_gap=boundary_gap,
                overlap_tolerance=boundary_tolerance,
            )
            accepted_base_ids = {id(item) for item in accepted_base}
            recovered_accepted = [
                item for item in combined if id(item) not in accepted_base_ids
            ]
            coverage_cues = list(primary_coverage or accepted_base)
            coverage_cues.extend(
                {"start": item["start"], "end": item["end"], "text": item["text"]}
                for item in recovered_accepted
            )
            report["attempts"].append({"start": left, "end": right, "round": round_index + 1,
                                       "proposed": proposed, "confirmed": len(candidates),
                                       "added": len(combined) - before,
                                       "replaced": replacements})
        if "error" in report:
            break
        current_gaps = missing_ranges(
            coverage_cues, duration, min_gap=AUDIT_MIN_GAP_SECONDS
        )
        windows = _merge_windows(
            _plan_gap_windows(_voiced_gaps(current_gaps, speech), speech, duration),
            duration,
        )
        windows = [
            window for window in windows
            if (round(window[0], 3), round(window[1], 3)) not in attempted
        ]
        windows = windows[:max(0, budget - len(attempted))]
        if not windows:
            break
    report["added_cues"] = len(combined) - len(cues)
    report["unresolved_speech"] = [(max(left, start), min(right, end))
        for left, right in missing_ranges(
            coverage_cues, duration, min_gap=AUDIT_MIN_GAP_SECONDS
        ) for start, end in speech
        if min(right, end) - max(left, start) >= MIN_VOICED_GAP_SECONDS]
    return combined, report
