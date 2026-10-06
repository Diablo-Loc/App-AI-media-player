"""Conservative first-window ASR checks that fail open for real vocals.

The normal full-song Whisper pass remains authoritative.  Silero VAD is only
independent evidence: a cue is never removed merely because VAD missed it.
Known credit/boilerplate can be rejected directly; other pre-voice cues need a
single local no-prompt verification pass before they can be removed.  Language
is probed again only for a long intro plus a low-confidence primary decision.
"""
from __future__ import annotations

import math
import re
import unicodedata
from types import SimpleNamespace


SAMPLE_RATE = 16000
INTRO_SECONDS = 30.0
VOICE_SCAN_SECONDS = 60.0
MIN_LEADING_SILENCE = 2.5
LANGUAGE_PROBE_MIN_SILENCE = 4.0
LANGUAGE_RECHECK_MAX_PROB = 0.60
LANGUAGE_PROBE_MIN_PROB = 0.80
LANGUAGE_PROBE_MIN_GAIN = 0.15
PRUNE_MARGIN = 0.20
MIN_SPEECH_OVERLAP = 0.06
VERIFY_PAD = 0.45
VERIFY_TEXT_RATIO = 0.52
VERIFY_TIME_OVERLAP = 0.08
VERIFY_NO_SPEECH_THRESHOLD = 0.60
VERIFY_LOG_PROB_THRESHOLD = -1.0
VERIFY_HALLUCINATION_SILENCE = 1.0
LANGUAGE_PROBE_MAX_SECONDS = 9.0
LANGUAGE_PROBE_MIN_SECONDS = 1.5
RECOVERY_MIN_FIRST_VOICE = 8.0
RECOVERY_MAX_FIRST_VOICE = 24.0
RECOVERY_WINDOW_SECONDS = 12.0
RECOVERY_ONSET_OFFSETS = (1.8, 0.8)
RECOVERY_SEAM_LEFT = 20.0
RECOVERY_SEAM_RIGHT = 32.0
RECOVERY_MIN_LOGPROB = -0.85
RECOVERY_MIN_WORD_PROB = 0.42
RECOVERY_MIN_SPEECH = 0.25
RECOVERY_MIN_SPEECH_RATIO = 0.30
RECOVERY_ONSET_AGREEMENT = 0.52
RECOVERY_SEAM_AGREEMENT = 0.42
RECOVERY_CONTAMINATION_SECONDS = 1.0
RECOVERY_ONSET_RESET_GAP = 4.0
RECOVERY_DOMINATED_REPEAT_COUNT = 3
RECOVERY_DOMINATED_REPEAT_SECONDS = 6.0
RECOVERY_FALLBACK_WINDOWS = ((10.0, 24.0), (12.0, 26.0))


def _finite(value, default=None):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _check_cancel(cancel_cb):
    if cancel_cb and cancel_cb():
        raise RuntimeError("AI cancelled by user")


def _segment_span(segment):
    """Prefer acoustic word timing over display/segment padding."""
    word_spans = []
    for word in getattr(segment, "words", None) or ():
        start = _finite(getattr(word, "start", None))
        end = _finite(getattr(word, "end", None))
        if start is not None and end is not None and end >= start:
            word_spans.append((start, end))
    if word_spans:
        return min(item[0] for item in word_spans), max(item[1] for item in word_spans)
    start = _finite(getattr(segment, "start", None))
    end = _finite(getattr(segment, "end", None))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _overlap(left, right, spans):
    return sum(max(0.0, min(right, end) - max(left, start)) for start, end in spans)


def _normalized_text(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "", text)


def _text_support(primary, verified):
    """Loose identity check: verification may split/join the same lyric."""
    from difflib import SequenceMatcher

    left = _normalized_text(primary)
    right = _normalized_text(verified)
    if not left or not right:
        return False
    if left == right:
        return True
    if left in right or right in left:
        shorter = min(len(left), len(right))
        longer = max(len(left), len(right))
        return shorter >= 2 and shorter / max(1, longer) >= 0.45
    return SequenceMatcher(None, left, right, autojunk=False).ratio() >= VERIFY_TEXT_RATIO


def _read_intro_pcm16(audio_path, seconds=INTRO_SECONDS):
    """Read only the bounded normalized WAV prefix produced by extractor.py."""
    import wave
    import numpy as np

    with wave.open(str(audio_path), "rb") as audio:
        if (
            audio.getnchannels() != 1
            or audio.getsampwidth() != 2
            or audio.getframerate() != SAMPLE_RATE
        ):
            return None
        frames = min(audio.getnframes(), round(max(0.0, seconds) * SAMPLE_RATE))
        raw = audio.readframes(frames)
    if not raw:
        return np.empty((0,), dtype=np.float32)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _intro_speech_probe(audio_path):
    """Return a sensitive VAD map; false positives are safer than false deletion."""
    waveform = _read_intro_pcm16(audio_path, seconds=VOICE_SCAN_SECONDS)
    if waveform is None:
        return None
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(
        threshold=0.15,
        min_speech_duration_ms=96,
        max_speech_duration_s=float("inf"),
        min_silence_duration_ms=300,
        window_size_samples=1024,
        speech_pad_ms=350,
    )
    spans = [
        (item["start"] / SAMPLE_RATE, item["end"] / SAMPLE_RATE)
        for item in get_speech_timestamps(waveform, vad_options=options)
    ]
    confirmed = [
        (item["start"] / SAMPLE_RATE, item["end"] / SAMPLE_RATE)
        for item in get_speech_timestamps(waveform)
    ]
    return {"waveform": waveform, "speech": spans, "confirmed_speech": confirmed}


def _onset_speech(sensitive, confirmed):
    """Use default VAD for onset only when the sensitive map is degenerate."""
    if not confirmed:
        return sensitive
    if not sensitive:
        return confirmed
    sensitive_first = min(start for start, _ in sensitive)
    confirmed_first = min(start for start, _ in confirmed)
    sensitive_coverage = _overlap(0.0, INTRO_SECONDS, sensitive)
    if (sensitive_first <= 0.10
            and sensitive_coverage >= INTRO_SECONDS * 0.90
            and (confirmed_first >= MIN_LEADING_SILENCE or len(confirmed) > 1)):
        previous_end = None
        for index, (start, end) in enumerate(confirmed):
            reset = previous_end is None or start - previous_end >= RECOVERY_ONSET_RESET_GAP
            if reset and start >= MIN_LEADING_SILENCE:
                return confirmed[index:]
            previous_end = max(end, previous_end or end)
        return confirmed
    return sensitive


def _segment_confidence(segment):
    logprob = _finite(getattr(segment, "avg_logprob", None), -math.inf)
    probabilities = [
        _finite(getattr(word, "probability", None))
        for word in (getattr(segment, "words", None) or ())
    ]
    probabilities = [value for value in probabilities if value is not None]
    mean_word = sum(probabilities) / len(probabilities) if probabilities else 0.0
    return logprob, mean_word


def _absolute_segment(segment, offset):
    words = []
    for word in getattr(segment, "words", None) or ():
        start = _finite(getattr(word, "start", None))
        end = _finite(getattr(word, "end", None))
        if start is None or end is None or end < start:
            continue
        words.append(SimpleNamespace(
            start=offset + start,
            end=offset + end,
            word=getattr(word, "word", ""),
            probability=_finite(getattr(word, "probability", None), 0.0) or 0.0,
        ))
    return SimpleNamespace(
        start=offset + (_finite(getattr(segment, "start", None), 0.0) or 0.0),
        end=offset + (_finite(getattr(segment, "end", None), 0.0) or 0.0),
        text=str(getattr(segment, "text", "") or ""),
        words=words,
        avg_logprob=_finite(getattr(segment, "avg_logprob", None), -math.inf),
        no_speech_prob=_finite(getattr(segment, "no_speech_prob", None), 1.0),
        compression_ratio=_finite(getattr(segment, "compression_ratio", None), 0.0),
    )


def _decode_intro_window(model, waveform, left, right, language, cancel_cb=None):
    if waveform is None or right - left < 0.5:
        return []
    clip = waveform[round(left * SAMPLE_RATE):round(right * SAMPLE_RATE)]
    _check_cancel(cancel_cb)
    generator, _ = model.transcribe(
        clip,
        language=language or None,
        word_timestamps=True,
        condition_on_previous_text=False,
        beam_size=3,
        temperature=0.0,
        vad_filter=False,
        initial_prompt=None,
        no_speech_threshold=None,
    )
    decoded = []
    for item in generator:
        _check_cancel(cancel_cb)
        decoded.append(_absolute_segment(item, left))
    return decoded


def _accepted_recovery_segments(segments, confirmed_speech):
    from pipeline.lyric_accuracy import credit_text

    result = []
    for segment in segments or ():
        span = _segment_span(segment)
        if span is None:
            continue
        start, end = span
        duration = end - start
        if duration <= 0:
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        if not text or credit_text(text, timed_words=bool(getattr(segment, "words", None))):
            continue
        logprob, mean_word = _segment_confidence(segment)
        if logprob < RECOVERY_MIN_LOGPROB or mean_word < RECOVERY_MIN_WORD_PROB:
            continue
        voiced = _overlap(start, end, confirmed_speech)
        if voiced < max(RECOVERY_MIN_SPEECH, duration * RECOVERY_MIN_SPEECH_RATIO):
            continue
        result.append(segment)
    return result


def _window_text(segments, left, right):
    parts = []
    for segment in segments or ():
        span = _segment_span(segment)
        if span is None or min(right, span[1]) - max(left, span[0]) <= 0.05:
            continue
        parts.append(str(getattr(segment, "text", "") or ""))
    return _normalized_text(" ".join(parts))


def _agreement_ratio(left_segments, right_segments, left, right):
    from difflib import SequenceMatcher

    if right - left < 0.5:
        return 0.0
    first = _window_text(left_segments, left, right)
    second = _window_text(right_segments, left, right)
    if len(first) < 3 or len(second) < 3:
        return 0.0
    return SequenceMatcher(None, first, second, autojunk=False).ratio()


def _credit_contamination(segments, confirmed_speech):
    from pipeline.lyric_accuracy import credit_text

    if not confirmed_speech:
        return None
    ordered = sorted((start, end) for start, end in confirmed_speech if end > start)
    candidate_onsets = []
    previous_end = None
    for start, end in ordered:
        reset = previous_end is None or start - previous_end >= RECOVERY_ONSET_RESET_GAP
        if reset and RECOVERY_MIN_FIRST_VOICE <= start <= RECOVERY_MAX_FIRST_VOICE:
            candidate_onsets.append(start)
        previous_end = max(end, previous_end or end)

    for first_voice in candidate_onsets:
        contaminated = 0.0
        repeated = {}
        for segment in segments or ():
            span = _segment_span(segment)
            if span is None:
                continue
            start, end = span
            if start >= INTRO_SECONDS or end <= first_voice:
                continue
            voice_overlap = _overlap(max(start, first_voice), min(end, INTRO_SECONDS), confirmed_speech)
            if voice_overlap <= 0:
                continue
            text = str(getattr(segment, "text", "") or "").strip()
            if credit_text(text, timed_words=bool(getattr(segment, "words", None))):
                contaminated += voice_overlap
            normalized = _normalized_text(text)
            if len(normalized) >= 2:
                count, seconds = repeated.get(normalized, (0, 0.0))
                repeated[normalized] = (count + 1, seconds + voice_overlap)

        if contaminated >= RECOVERY_CONTAMINATION_SECONDS:
            return first_voice, "credit_over_voice"
        if any(count >= 3 and seconds >= 3.0 for count, seconds in repeated.values()):
            return first_voice, "repeated_over_voice"
    return None


def _first_window_domination(segments):
    """Detect a first window monopolized by one repeated/credit-like transcript."""
    from pipeline.lyric_accuracy import credit_text

    repeated = {}
    explicit_seconds = 0.0
    for segment in segments or ():
        span = _segment_span(segment)
        if span is None:
            continue
        start, end = span
        if start >= INTRO_SECONDS:
            continue
        clipped = max(0.0, min(end, INTRO_SECONDS) - max(0.0, start))
        if clipped <= 0:
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        normalized = _normalized_text(text)
        if credit_text(text, timed_words=bool(getattr(segment, "words", None))):
            explicit_seconds += clipped
        if len(normalized) >= 2:
            count, seconds = repeated.get(normalized, (0, 0.0))
            repeated[normalized] = (count + 1, seconds + clipped)

    suspicious = {
        text for text, (count, seconds) in repeated.items()
        if count >= RECOVERY_DOMINATED_REPEAT_COUNT
        and seconds >= RECOVERY_DOMINATED_REPEAT_SECONDS
    }
    if suspicious:
        return "repeated_first_window", suspicious
    if explicit_seconds >= 10.0:
        return "credit_dominated_window", set()
    return None


def _related_to_suspicious(text, suspicious):
    normalized = _normalized_text(text)
    if not normalized:
        return False
    return any(
        normalized == item
        or (len(normalized) <= len(item) and normalized in item)
        or (len(item) < len(normalized) and item in normalized)
        for item in suspicious
    )


def _stitch_intro_recovery(onset_segments, seam_segments, overlap_left, overlap_right):
    if not onset_segments or not seam_segments or overlap_right <= overlap_left:
        return []
    cut = (overlap_left + overlap_right) / 2.0
    result = []
    for segment in onset_segments:
        span = _segment_span(segment)
        if span is not None and (span[0] + span[1]) / 2.0 < cut:
            result.append(segment)
    covered_end = max((_segment_span(item)[1] for item in result), default=-math.inf)
    for segment in seam_segments:
        span = _segment_span(segment)
        if span is None or (span[0] + span[1]) / 2.0 < cut or span[1] <= covered_end + 0.02:
            continue
        candidate = segment
        if span[0] < covered_end - 0.02:
            words = [
                word for word in (getattr(segment, "words", None) or ())
                if ((_finite(getattr(word, "start", None), -math.inf)
                     + _finite(getattr(word, "end", None), -math.inf)) / 2.0) >= covered_end - 0.02
            ]
            if not words:
                continue
            from pipeline.jp_normalizer import universal_text_reconstruct
            candidate = SimpleNamespace(
                start=min(word.start for word in words),
                end=max(word.end for word in words),
                text=universal_text_reconstruct(words, getattr(segment, "text", "")),
                words=words,
                avg_logprob=getattr(segment, "avg_logprob", -math.inf),
                no_speech_prob=getattr(segment, "no_speech_prob", 1.0),
                compression_ratio=getattr(segment, "compression_ratio", 0.0),
            )
        result.append(candidate)
        covered_end = max(covered_end, _segment_span(candidate)[1])
    return sorted(result, key=lambda item: _segment_span(item)[0])


def _reconcile_contaminated_intro(model, waveform, segments, language, confirmed_speech,
                                  cancel_cb=None):
    trigger = _credit_contamination(segments, confirmed_speech)
    fallback = None if trigger is not None else _first_window_domination(segments)
    if (trigger is None and fallback is None) or waveform is None:
        return list(segments or ()), {}
    duration = len(waveform) / SAMPLE_RATE
    suspicious = set()

    if trigger is not None:
        first_voice, reason = trigger
        onset_windows = []
        for offset in RECOVERY_ONSET_OFFSETS:
            left = max(0.0, first_voice - offset)
            right = min(duration, left + RECOVERY_WINDOW_SECONDS)
            onset_windows.append((left, right))
    else:
        reason, suspicious = fallback
        first_voice = None
        onset_windows = [
            (min(duration, left), min(duration, right))
            for left, right in RECOVERY_FALLBACK_WINDOWS
            if min(duration, right) - min(duration, left) >= 0.5
        ]
        if len(onset_windows) != 2:
            return list(segments or ()), {"reconciliation_rejected": "short_fallback_audio"}

    onset_passes = []
    for left, right in onset_windows:
        decoded = _decode_intro_window(model, waveform, left, right, language, cancel_cb=cancel_cb)
        onset_passes.append(_accepted_recovery_segments(decoded, confirmed_speech))

    first_left, first_right = onset_windows[0]
    second_left, second_right = onset_windows[1]
    onset_overlap_left = max(first_left, second_left, first_voice or 0.0)
    onset_overlap_right = min(first_right, second_right)
    onset_ratio = _agreement_ratio(
        onset_passes[0], onset_passes[1], onset_overlap_left, onset_overlap_right
    )
    if onset_ratio < RECOVERY_ONSET_AGREEMENT:
        return list(segments or ()), {
            "reconciliation_rejected": "onset_disagreement",
            "reconciliation_onset_ratio": onset_ratio,
        }

    # Use the slightly earlier onset pass for output because it tends to retain
    # natural lyric-line boundaries; the later-start pass remains independent
    # confirmation that those words are not an instrumental hallucination.
    onset = onset_passes[0]
    if not onset:
        return list(segments or ()), {"reconciliation_rejected": "empty_onset"}

    if first_voice is None:
        supported = []
        for candidate in onset:
            span = _segment_span(candidate)
            if span is None:
                continue
            support = _agreement_ratio([candidate], onset_passes[1], max(span[0], second_left),
                                       min(span[1], second_right))
            if support >= 0.28:
                supported.append(candidate)
        if not supported:
            return list(segments or ()), {"reconciliation_rejected": "fallback_no_supported_onset"}
        first_supported = min(_segment_span(item)[0] for item in supported)
        onset = [item for item in onset if _segment_span(item)[1] >= first_supported - 0.05]
        first_voice = first_supported

    seam_left = min(duration, RECOVERY_SEAM_LEFT)
    seam_right = min(duration, RECOVERY_SEAM_RIGHT)
    seam = _accepted_recovery_segments(
        _decode_intro_window(model, waveform, seam_left, seam_right, language, cancel_cb=cancel_cb),
        confirmed_speech,
    )
    overlap_left = max(seam_left, first_left)
    overlap_right = min(seam_right, first_right)
    seam_ratio = _agreement_ratio(onset, seam, overlap_left, overlap_right)
    if seam_ratio < RECOVERY_SEAM_AGREEMENT:
        return list(segments or ()), {
            "reconciliation_rejected": "seam_disagreement",
            "reconciliation_onset_ratio": onset_ratio,
            "reconciliation_seam_ratio": seam_ratio,
        }

    stitched = _stitch_intro_recovery(onset, seam, overlap_left, overlap_right)
    if not stitched:
        return list(segments or ()), {"reconciliation_rejected": "empty_stitch"}
    first_span = _segment_span(stitched[0])
    last_span = _segment_span(stitched[-1])
    if (first_span is None or last_span is None
            or first_span[0] > first_voice + 1.0
            or last_span[1] < min(INTRO_SECONDS, first_voice + 6.0)):
        return list(segments or ()), {"reconciliation_rejected": "insufficient_coverage"}

    from pipeline.lyric_accuracy import credit_text

    replacement_start = first_span[0]
    replacement_end = last_span[1]
    kept = []
    removed = []
    for index, segment in enumerate(segments or ()):
        span = _segment_span(segment)
        if span is None:
            kept.append(segment)
            continue
        start, end = span
        text = str(getattr(segment, "text", "") or "").strip()
        if end <= replacement_start:
            if (credit_text(text, timed_words=bool(getattr(segment, "words", None)))
                    or _related_to_suspicious(text, suspicious)):
                removed.append((index, start, end, text, "reconciled_credit"))
            else:
                kept.append(segment)
            continue
        if start < replacement_end + PRUNE_MARGIN and end > replacement_start - PRUNE_MARGIN:
            removed.append((index, start, end, text, "reconciled_overlap"))
            continue
        kept.append(segment)

    reconciled = sorted(kept + stitched, key=lambda item: _segment_span(item)[0])
    return reconciled, {
        "intro_reconciled": True,
        "reconciliation_reason": reason,
        "reconciliation_first_voice": first_voice,
        "reconciliation_onset_ratio": onset_ratio,
        "reconciliation_seam_ratio": seam_ratio,
        "reconciliation_windows": onset_windows + [(seam_left, seam_right)],
        "reconciliation_removed": removed,
        "reconciliation_segments": len(stitched),
    }


def _prevoice_candidates(segments, speech):
    source = list(segments or ())
    if not source or not speech:
        return source, [], None
    first_voice = min(start for start, _ in speech)
    if first_voice < MIN_LEADING_SILENCE:
        return source, [], first_voice

    cutoff = min(INTRO_SECONDS, max(0.0, first_voice - PRUNE_MARGIN))
    candidates = []
    for index, segment in enumerate(source):
        span = _segment_span(segment)
        if span is None:
            continue
        start, end = span
        no_voice = _overlap(start, end, speech) < MIN_SPEECH_OVERLAP
        if start < INTRO_SECONDS and end <= cutoff and no_voice:
            candidates.append((index, segment, start, end))
    return source, candidates, first_voice


def _verification_support(candidate, verified_segments, verified_offset=0.0):
    _, segment, start, end = candidate
    primary_text = str(getattr(segment, "text", "") or "").strip()
    for verified in verified_segments or ():
        span = _segment_span(verified)
        if span is None:
            continue
        other_start, other_end = span
        other_start += verified_offset
        other_end += verified_offset
        if min(end, other_end) - max(start, other_start) < VERIFY_TIME_OVERLAP:
            continue
        if _text_support(primary_text, getattr(verified, "text", "")):
            return True
    return False


def filter_instrumental_intro_segments(
    segments, speech, verified_segments=None, verified_offset=0.0
):
    """Filter intro hallucinations without trusting VAD as a deletion oracle.

    Explicit credit/boilerplate is already invalid lyric material.  Every other
    cue before the independently detected first voice is kept unless a local
    no-prompt verification was actually performed and failed to reproduce it.
    Passing ``verified_segments=None`` therefore fails open for ordinary text.
    """
    from pipeline.lyric_accuracy import credit_text

    source, candidates, _ = _prevoice_candidates(segments, speech)
    if not candidates:
        return source, []

    candidate_by_index = {item[0]: item for item in candidates}
    kept = []
    removed = []
    verification_available = verified_segments is not None
    for index, segment in enumerate(source):
        candidate = candidate_by_index.get(index)
        if candidate is None:
            kept.append(segment)
            continue
        _, _, start, end = candidate
        text = str(getattr(segment, "text", "") or "").strip()
        explicit_boilerplate = credit_text(text, timed_words=bool(getattr(segment, "words", None)))
        reproduced = verification_available and _verification_support(
            candidate, verified_segments, verified_offset=verified_offset
        )
        if explicit_boilerplate or (verification_available and not reproduced):
            reason = "credit" if explicit_boilerplate else "verification_miss"
            removed.append((index, start, end, text, reason))
        else:
            kept.append(segment)
    return kept, removed


def _verify_prevoice_text(model, waveform, segments, speech, language, cancel_cb=None):
    """Decode at most one bounded intro clip, only when generic cues need proof."""
    from pipeline.lyric_accuracy import credit_text

    _, candidates, first_voice = _prevoice_candidates(segments, speech)
    if not candidates or waveform is None or first_voice is None:
        return None
    generic = [item for item in candidates if not credit_text(
        str(getattr(item[1], "text", "") or "").strip(),
        timed_words=bool(getattr(item[1], "words", None)),
    )]
    if not generic:
        return None

    left = max(0.0, min(item[2] for item in generic) - VERIFY_PAD)
    right = min(len(waveform) / SAMPLE_RATE, max(item[3] for item in generic) + VERIFY_PAD)
    if right - left < 0.25:
        return None
    clip = waveform[round(left * SAMPLE_RATE):round(right * SAMPLE_RATE)]
    _check_cancel(cancel_cb)
    generator, _ = model.transcribe(
        clip,
        language=language or None,
        word_timestamps=True,
        condition_on_previous_text=False,
        beam_size=3,
        temperature=0.0,
        vad_filter=False,
        initial_prompt=None,
        # The verifier must be less willing than the primary pass to invent
        # words from silence. These guards apply only to this bounded check.
        no_speech_threshold=VERIFY_NO_SPEECH_THRESHOLD,
        log_prob_threshold=VERIFY_LOG_PROB_THRESHOLD,
        hallucination_silence_threshold=VERIFY_HALLUCINATION_SILENCE,
    )
    verified = []
    for item in generator:
        _check_cancel(cancel_cb)
        verified.append(item)
    return verified, left


def _language_probe_bounds(waveform, speech):
    """Bound language detection to the earliest VAD-backed vocal region."""
    if waveform is None or not speech:
        return None
    duration = len(waveform) / SAMPLE_RATE
    ordered = sorted(
        (max(0.0, start), max(0.0, end))
        for start, end in speech
        if end > start
    )
    if not ordered:
        return None
    first_start, first_end = ordered[0]
    left = max(0.0, first_start - 0.15)
    budget_end = min(duration, left + LANGUAGE_PROBE_MAX_SECONDS)
    right = min(
        budget_end,
        max(first_end + 0.15, left + LANGUAGE_PROBE_MIN_SECONDS),
    )
    for start, end in ordered[1:]:
        if start >= budget_end:
            break
        right = min(budget_end, max(right, end + 0.15))
    if right - left < LANGUAGE_PROBE_MIN_SECONDS:
        return None
    return left, right


def _language_probe(model, waveform, speech, current_language, current_probability, cancel_cb=None):
    if waveform is None or not speech:
        return None
    first_voice = min(start for start, _ in speech)
    probability = _finite(current_probability, 0.0) or 0.0
    if first_voice < LANGUAGE_PROBE_MIN_SILENCE or probability >= LANGUAGE_RECHECK_MAX_PROB:
        return None

    bounds = _language_probe_bounds(waveform, speech)
    if bounds is None:
        return None
    left, right = bounds
    clip = waveform[round(left * SAMPLE_RATE):round(right * SAMPLE_RATE)]
    _check_cancel(cancel_cb)
    generator, info = model.transcribe(
        clip,
        language=None,
        word_timestamps=False,
        condition_on_previous_text=False,
        beam_size=1,
        temperature=0.0,
        vad_filter=False,
        initial_prompt=None,
    )
    # Language detection is completed before faster-whisper returns `info`;
    # do not decode the probe text because it is not user-visible subtitle data.
    del generator
    candidate = str(getattr(info, "language", "") or "").strip()
    candidate_probability = _finite(getattr(info, "language_probability", None), 0.0) or 0.0
    if not candidate or candidate == current_language:
        return None
    if candidate_probability < LANGUAGE_PROBE_MIN_PROB:
        return None
    if probability >= 0.45 and candidate_probability < probability + LANGUAGE_PROBE_MIN_GAIN:
        return None
    return candidate, candidate_probability


def audit_primary_intro(model, audio_path, segments, language, language_probability,
                        cancel_cb=None):
    """Audit only the problematic intro while preserving the normal full-song path.

    A second full-song decode is allowed only when a long instrumental intro and
    a low-confidence language decision are both present, and a short real-voice
    probe strongly identifies a different language.
    """
    original = list(segments or ())
    report = {
        "speech": [],
        "removed": [],
        "language_before": language,
        "language_probability_before": _finite(language_probability, 0.0) or 0.0,
        "language_after": language,
        "language_rerun": False,
    }
    try:
        probe = _intro_speech_probe(audio_path)
    except Exception as error:
        report["error"] = str(error)
        return original, language, report
    if not probe:
        return original, language, report

    speech = probe["speech"]
    confirmed_speech = probe.get("confirmed_speech", speech)
    onset_speech = _onset_speech(speech, confirmed_speech)
    report["speech"] = speech
    report["confirmed_speech"] = confirmed_speech
    working = original
    try:
        candidate = _language_probe(
            model,
            probe["waveform"],
            onset_speech,
            language,
            language_probability,
            cancel_cb=cancel_cb,
        )
        if candidate is not None:
            from pipeline.lyric_accuracy import primary_options

            candidate_language, candidate_probability = candidate
            options = primary_options()
            options["language"] = candidate_language
            _check_cancel(cancel_cb)
            generator, rerun_info = model.transcribe(str(audio_path), **options)
            rerun = []
            for segment in generator:
                _check_cancel(cancel_cb)
                rerun.append(segment)
            if original and not rerun:
                report["language_rerun_rejected"] = "empty_result"
            else:
                working = rerun
                language = str(getattr(rerun_info, "language", "") or candidate_language)
                report["language_after"] = language
                report["language_probability_after"] = _finite(
                    getattr(rerun_info, "language_probability", None), candidate_probability
                )
                report["language_rerun"] = True
    except RuntimeError:
        raise
    except Exception as error:
        # Language probing is optional; preserve the already accepted primary pass.
        report["language_probe_error"] = str(error)
        working = original
        language = report["language_before"]

    try:
        reconciled, reconciliation = _reconcile_contaminated_intro(
            model, probe["waveform"], working, language, confirmed_speech,
            cancel_cb=cancel_cb,
        )
        report.update(reconciliation)
        if reconciliation.get("intro_reconciled"):
            working = reconciled
    except RuntimeError:
        raise
    except Exception as error:
        report["reconciliation_error"] = str(error)

    verified_segments = None
    verified_offset = 0.0
    try:
        verification = _verify_prevoice_text(
            model,
            probe["waveform"],
            working,
            speech,
            language,
            cancel_cb=cancel_cb,
        )
        if verification is not None:
            verified_segments, verified_offset = verification
            report["verification_count"] = len(verified_segments)
    except RuntimeError:
        raise
    except Exception as error:
        # Verification is optional.  VAD alone never authorizes generic deletion.
        report["verification_error"] = str(error)

    filtered, removed = filter_instrumental_intro_segments(
        working,
        speech,
        verified_segments=verified_segments,
        verified_offset=verified_offset,
    )
    report["removed"] = removed
    if onset_speech:
        report["first_voice"] = min(start for start, _ in onset_speech)
    return filtered, language, report
