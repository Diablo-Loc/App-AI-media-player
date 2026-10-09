"""Conservative first-window ASR checks that fail open for real vocals.

The normal full-song Whisper pass remains authoritative.  Silero VAD is only
independent evidence: a cue is never removed merely because VAD missed it.
Known credit/boilerplate can be rejected directly; ordinary first-window lyric
text is preserved even when VAD/verifier/confidence signals are weak. Language is
probed again only for a long intro plus a low-confidence primary decision.
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
LANGUAGE_CONSENSUS_MAX_PRIMARY_PROB = 0.82
LANGUAGE_CONSENSUS_MIN_PROB = 0.78
LANGUAGE_CONSENSUS_MIN_AVG_PROB = 0.82
LANGUAGE_CONSENSUS_MIN_GAIN = 0.08
LANGUAGE_CONSENSUS_MIN_START = 45.0
LANGUAGE_CONSENSUS_WINDOW_SECONDS = 8.0
LANGUAGE_CONSENSUS_MIN_SPACING = 9.0
LANGUAGE_CONSENSUS_MAX_WINDOWS = 3
LANGUAGE_CONSENSUS_REQUIRED = 2
PRUNE_MARGIN = 0.20
MIN_SPEECH_OVERLAP = 0.06
VERIFY_PAD = 0.45
VERIFY_CONTEXT_PAD = 2.0
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
RECOVERY_FALLBACK_WINDOWS = ((10.0, 24.0), (12.0, 26.0))
ANCHORED_RECOVERY_SECONDS = 40.0
ANCHORED_SPEECH_MIN_START = 8.0
ANCHORED_SPEECH_MAX_START = 24.0
ANCHORED_SPEECH_MIN_SECONDS = 8.0
INTRO_MEDIA_BOILERPLATE_MAX_LOGPROB = -0.85
INTRO_MEDIA_BOILERPLATE_MIN_NO_SPEECH = 0.35
GENERIC_PRUNE_MAX_LOGPROB = -0.95
GENERIC_PRUNE_MIN_NO_SPEECH = 0.45
GENERIC_PRUNE_MAX_WORD_PROB = 0.48
GENERIC_REPEAT_MIN_COUNT = 3
GENERIC_REPEAT_MIN_COMPRESSION = 2.80
RECOVERY_REPEAT_MIN_SECONDS = 6.0
PRIMARY_PRESERVE_OVERLAP = 0.18
_INTRO_MEDIA_BOILERPLATE = re.compile(
    r"\b(?:we\s+(?:ll|will)\s+be\s+right\s+back|"
    r"(?:we\s+(?:ll|will)\s+)?see\s+you\s+next\s+time|"
    r"i\s+ll\s+see\s+you\s+in\s+(?:the\s+)?next\s+video|"
    r"see\s+you\s+in\s+(?:the\s+)?next\s+video|"
    r"transcri(?:c|ç)[aã]o\s+e\s+legendas|legendas\s+por)\b",
    re.IGNORECASE,
)


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


def _intro_media_boilerplate(text):
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized).strip()
    return bool(_INTRO_MEDIA_BOILERPLATE.search(normalized))


def _has_intro_credit_signal(segments):
    """High-signal evidence that the first Whisper window is not lyric text."""
    from pipeline.lyric_accuracy import credit_text

    for segment in segments or ():
        span = _segment_span(segment)
        if span is None or span[0] >= INTRO_SECONDS:
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        if _intro_media_boilerplate(text) or credit_text(
            text, timed_words=bool(getattr(segment, "words", None))
        ):
            return True
    return False


def _sustained_intro_speech(confirmed_speech):
    """Return a long continuous vocal island inside the first Whisper window."""
    for start, end in sorted(confirmed_speech or ()):
        if end <= start:
            continue
        if (ANCHORED_SPEECH_MIN_START <= start <= ANCHORED_SPEECH_MAX_START
                and end - start >= ANCHORED_SPEECH_MIN_SECONDS):
            return start, end
    return None


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


def _segment_acoustically_weak(segment):
    """Require primary-side weakness before pruning an otherwise ordinary cue.

    Local re-decodes can miss quiet vocals for the same reason VAD misses them.
    A generic primary cue therefore fails open unless its own Whisper evidence is
    also weak. Missing metrics are treated as unknown, not as permission to prune.
    """
    logprob = _finite(getattr(segment, "avg_logprob", None))
    no_speech = _finite(getattr(segment, "no_speech_prob", None))
    word_probabilities = []
    for word in getattr(segment, "words", None) or ():
        probability = _finite(getattr(word, "probability", None))
        if probability is not None:
            word_probabilities.append(probability)
    mean_word_probability = (
        sum(word_probabilities) / len(word_probabilities)
        if word_probabilities else None
    )
    # Singing is much less stable than speech on any single Whisper metric.
    # Requiring only one weak number regressed older songs where a real quiet
    # opening had, for example, a low word probability but a good log-prob and
    # clear acoustic activity.  Generic primary text may be deleted only when
    # at least two independent primary-side confidence signals are weak.
    weak_signals = 0
    if logprob is not None and logprob < GENERIC_PRUNE_MAX_LOGPROB:
        weak_signals += 1
    if no_speech is not None and no_speech > GENERIC_PRUNE_MIN_NO_SPEECH:
        weak_signals += 1
    if (
        mean_word_probability is not None
        and mean_word_probability < GENERIC_PRUNE_MAX_WORD_PROB
    ):
        weak_signals += 1
    return weak_signals >= 2


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
    if (sensitive_first <= MIN_LEADING_SILENCE
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
        if contaminated >= RECOVERY_CONTAMINATION_SECONDS:
            return first_voice, "credit_over_voice"
    return None


def _first_window_domination(segments):
    """Detect a first window dominated by high-signal non-lyric material.

    Repetition by itself is valid lyric behavior. Only exact repeated text that
    also carries Whisper's pathological high-compression signal may trigger the
    bounded reconciliation path.
    """
    from pipeline.lyric_accuracy import credit_text

    explicit_seconds = 0.0
    compressed_repeats = {}
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
        if credit_text(text, timed_words=bool(getattr(segment, "words", None))):
            explicit_seconds += clipped
        normalized = _normalized_text(text)
        compression = _finite(
            getattr(segment, "compression_ratio", None), 0.0
        ) or 0.0
        if len(normalized) >= 2 and compression >= GENERIC_REPEAT_MIN_COMPRESSION:
            count, seconds = compressed_repeats.get(normalized, (0, 0.0))
            compressed_repeats[normalized] = (count + 1, seconds + clipped)

    suspicious = {
        text
        for text, (count, seconds) in compressed_repeats.items()
        if count >= GENERIC_REPEAT_MIN_COUNT
        and seconds >= RECOVERY_REPEAT_MIN_SECONDS
    }
    if suspicious:
        return "repeated_high_compression_window", suspicious
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


def _merge_recovery_primary_first(primary, recovered, max_overlap=PRIMARY_PRESERVE_OVERLAP):
    """Add recovery only where accepted primary ASR has no meaningful coverage."""
    result = list(primary or ())
    primary_spans = [
        span for span in (_segment_span(item) for item in result)
        if span is not None
    ]
    added = 0
    for candidate in sorted(recovered or (), key=lambda item: _segment_span(item)[0]):
        span = _segment_span(candidate)
        if span is None:
            continue
        start, end = span
        if any(min(end, old_end) - max(start, old_start) > max_overlap
               for old_start, old_end in primary_spans):
            continue
        result.append(candidate)
        primary_spans.append(span)
        added += 1
    return sorted(result, key=lambda item: _segment_span(item)[0]), added


def _recovery_covers_voiced_segment(segment, recovered, confirmed_speech):
    """Only replace suspicious text over real voice when recovery covers it."""
    span = _segment_span(segment)
    if span is None:
        return False
    start, end = span
    voiced = _overlap(start, end, confirmed_speech)
    if voiced < MIN_SPEECH_OVERLAP:
        return True
    covered = 0.0
    for candidate in recovered or ():
        candidate_span = _segment_span(candidate)
        if candidate_span is None:
            continue
        covered += max(
            0.0,
            min(end, candidate_span[1]) - max(start, candidate_span[0]),
        )
    required = min(voiced, max(0.25, (end - start) * 0.25))
    return covered >= required


def _preserve_vad_backed_consensus_intro(original, rerun, confirmed_speech):
    """Keep real first-window speech when only later windows changed language.

    Later-language consensus means the beginning may legitimately be a count-in
    or spoken/sung phrase in another language. Only default-VAD-backed,
    non-credit primary segments are allowed to own overlapping rerun time.
    """
    from pipeline.lyric_accuracy import credit_text

    preserved = []
    for segment in original or ():
        span = _segment_span(segment)
        if span is None:
            continue
        start, end = span
        if start >= INTRO_SECONDS:
            continue
        duration = max(0.001, min(end, INTRO_SECONDS) - start)
        voiced = _overlap(start, min(end, INTRO_SECONDS), confirmed_speech)
        if voiced < max(0.08, duration * 0.25):
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        if (
            not text
            or _intro_media_boilerplate(text)
            or credit_text(text, timed_words=bool(getattr(segment, "words", None)))
        ):
            continue
        # Default VAD overlap is independent acoustic evidence that a person is
        # present here.  Do not let a weak Whisper confidence number erase that
        # primary cue merely because a global language rerun split/omitted it.
        # Explicit credit/media text was already rejected above.
        preserved.append(segment)

    if not preserved:
        return list(rerun or ()), 0

    preserved_spans = [_segment_span(item) for item in preserved]
    kept_rerun = []
    for segment in rerun or ():
        span = _segment_span(segment)
        if span is None:
            kept_rerun.append(segment)
            continue
        start, end = span
        if any(
            min(end, old_end) - max(start, old_start) > PRIMARY_PRESERVE_OVERLAP
            for old_start, old_end in preserved_spans
        ):
            continue
        kept_rerun.append(segment)
    return sorted(preserved + kept_rerun, key=lambda item: _segment_span(item)[0]), len(preserved)


def _restore_primary_intro_gaps(original, rerun):
    """Restore non-credit primary intro cues only where a language rerun left a gap.

    The established full-song primary decode is the v4-compatible authority.
    A corrective language rerun may improve overlapping wording, but an omitted
    rerun span is not evidence that the original lyric was false.  Restore that
    gap and let the later pre-voice verifier remove it only when independent
    evidence actually proves an instrumental hallucination.
    """
    from pipeline.lyric_accuracy import credit_text

    result = list(rerun or ())
    result_spans = [
        span for span in (_segment_span(item) for item in result)
        if span is not None
    ]
    restored = 0
    for segment in original or ():
        span = _segment_span(segment)
        if span is None:
            continue
        start, end = span
        if start >= INTRO_SECONDS:
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        if (
            not text
            or _intro_media_boilerplate(text)
            or credit_text(text, timed_words=bool(getattr(segment, "words", None)))
        ):
            continue
        if any(
            min(end, other_end) - max(start, other_start) > PRIMARY_PRESERVE_OVERLAP
            for other_start, other_end in result_spans
        ):
            continue
        result.append(segment)
        result_spans.append(span)
        restored += 1
    return sorted(result, key=lambda item: _segment_span(item)[0]), restored


def _repeated_prevoice_indices(candidates):
    """Find exact repeated pre-voice hypotheses without treating repetition alone as false."""
    groups = {}
    for index, segment, _start, _end in candidates:
        normalized = _normalized_text(getattr(segment, "text", ""))
        if len(normalized) < 2:
            continue
        groups.setdefault(normalized, []).append(index)
    repeated = set()
    for indices in groups.values():
        if len(indices) >= GENERIC_REPEAT_MIN_COUNT:
            repeated.update(indices)
    return repeated


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

    kept = []
    removed = []
    for index, segment in enumerate(segments or ()):
        span = _segment_span(segment)
        if span is None:
            kept.append(segment)
            continue
        start, end = span
        text = str(getattr(segment, "text", "") or "").strip()
        explicit = (
            _intro_media_boilerplate(text)
            or credit_text(text, timed_words=bool(getattr(segment, "words", None)))
            or _related_to_suspicious(text, suspicious)
        )
        if (
            start < INTRO_SECONDS
            and explicit
            and _recovery_covers_voiced_segment(segment, stitched, confirmed_speech)
        ):
            removed.append((index, start, end, text, "reconciled_suspicious"))
            continue
        kept.append(segment)

    reconciled, added = _merge_recovery_primary_first(kept, stitched)
    if not removed and not added:
        return list(segments or ()), {"reconciliation_rejected": "no_safe_change"}
    return reconciled, {
        "intro_reconciled": True,
        "reconciliation_reason": reason,
        "reconciliation_first_voice": first_voice,
        "reconciliation_onset_ratio": onset_ratio,
        "reconciliation_seam_ratio": seam_ratio,
        "reconciliation_windows": onset_windows + [(seam_left, seam_right)],
        "reconciliation_removed": removed,
        "reconciliation_segments": added,
    }


def _anchored_no_prompt_recovery(model, waveform, segments, language, confirmed_speech,
                                 cancel_cb=None):
    """Recover a sustained lyric intro when the prompted first window is polluted.

    This path is intentionally rare: it requires an explicit credit/media signal
    in the primary first window plus one long default-VAD speech island.  The
    retry stays anchored at t=0 because Whisper can need the original musical
    lead-in to decode the following vocal correctly.
    """
    source = list(segments or ())
    if waveform is None or not _has_intro_credit_signal(source):
        return source, {}
    sustained = _sustained_intro_speech(confirmed_speech)
    if sustained is None:
        return source, {}

    duration = len(waveform) / SAMPLE_RATE
    right = min(duration, ANCHORED_RECOVERY_SECONDS)
    if right < sustained[0] + ANCHORED_SPEECH_MIN_SECONDS:
        return source, {"anchored_recovery_rejected": "short_audio"}

    decoded = _decode_intro_window(
        model, waveform, 0.0, right, language, cancel_cb=cancel_cb
    )
    recovered = [
        item for item in _accepted_recovery_segments(decoded, confirmed_speech)
        if not _intro_media_boilerplate(getattr(item, "text", ""))
    ]
    if not recovered:
        return source, {"anchored_recovery_rejected": "empty_retry"}

    first_span = _segment_span(recovered[0])
    last_span = _segment_span(recovered[-1])
    if (first_span is None or last_span is None
            or first_span[0] > sustained[0] + 1.25
            or last_span[1] < min(right, sustained[0] + ANCHORED_SPEECH_MIN_SECONDS)):
        return source, {"anchored_recovery_rejected": "insufficient_coverage"}

    from pipeline.lyric_accuracy import credit_text

    kept = []
    removed = []
    for index, segment in enumerate(source):
        span = _segment_span(segment)
        if span is None:
            kept.append(segment)
            continue
        start, end = span
        text = str(getattr(segment, "text", "") or "").strip()
        explicit = _intro_media_boilerplate(text) or credit_text(
            text, timed_words=bool(getattr(segment, "words", None))
        )
        if (
            explicit
            and start < INTRO_SECONDS
            and _recovery_covers_voiced_segment(segment, recovered, confirmed_speech)
        ):
            removed.append((index, start, end, text, "anchored_credit"))
            continue
        kept.append(segment)

    result, added = _merge_recovery_primary_first(kept, recovered)
    if not removed and not added:
        return source, {"anchored_recovery_rejected": "no_safe_change"}
    return result, {
        "anchored_recovery": True,
        "anchored_recovery_window": (0.0, right),
        "anchored_recovery_speech": sustained,
        "anchored_recovery_removed": removed,
        "anchored_recovery_segments": added,
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


def _needs_secondary_prevoice_verification(
    segments, speech, verified_segments, verified_offset=0.0
):
    """Pay for a second decode only when the first check actually missed text."""
    from pipeline.lyric_accuracy import credit_text

    _, candidates, _ = _prevoice_candidates(segments, speech)
    for candidate in candidates:
        text = str(getattr(candidate[1], "text", "") or "").strip()
        if credit_text(text, timed_words=bool(getattr(candidate[1], "words", None))):
            continue
        if not _verification_support(
            candidate, verified_segments, verified_offset=verified_offset
        ):
            return True
    return False


def filter_instrumental_intro_segments(
    segments, speech, verified_segments=None, verified_offset=0.0,
    verified_segments_secondary=None, verified_offset_secondary=0.0,
):
    """Keep first-window ASR by default and remove only explicit junk/credits.

    VAD misses, low confidence, verifier misses, repetition and compression are
    intentionally not deletion signals here. Quiet or stylized opening vocals
    are common in music, so ordinary lyric text must fail open.
    """
    from pipeline.lyric_accuracy import credit_text

    source = list(segments or ())
    kept = []
    removed = []
    for index, segment in enumerate(source):
        span = _segment_span(segment)
        text = str(getattr(segment, "text", "") or "").strip()
        if span is not None and span[0] < INTRO_SECONDS and _intro_media_boilerplate(text):
            removed.append((index, span[0], span[1], text, "media_boilerplate"))
            continue
        if (
            span is not None
            and span[0] < INTRO_SECONDS
            and credit_text(text, timed_words=bool(getattr(segment, "words", None)))
        ):
            removed.append((index, span[0], span[1], text, "credit"))
            continue
        kept.append(segment)
    return kept, removed


def _verify_prevoice_text(
    model, waveform, segments, speech, language, cancel_cb=None, pad=VERIFY_PAD
):
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

    pad = max(0.0, float(pad))
    left = max(0.0, min(item[2] for item in generic) - pad)
    right = min(len(waveform) / SAMPLE_RATE, max(item[3] for item in generic) + pad)
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


def _audio_duration(audio_path):
    import wave

    with wave.open(str(audio_path), "rb") as audio:
        if audio.getframerate() <= 0:
            return 0.0
        return audio.getnframes() / audio.getframerate()


def _read_pcm16_window(audio_path, left, right):
    """Read one bounded mono/16 kHz extractor window without loading the song."""
    import wave
    import numpy as np

    if right <= left:
        return None
    with wave.open(str(audio_path), "rb") as audio:
        if (
            audio.getnchannels() != 1
            or audio.getsampwidth() != 2
            or audio.getframerate() != SAMPLE_RATE
        ):
            return None
        start = min(audio.getnframes(), max(0, round(left * SAMPLE_RATE)))
        stop = min(audio.getnframes(), max(start, round(right * SAMPLE_RATE)))
        audio.setpos(start)
        raw = audio.readframes(stop - start)
    if not raw:
        return None
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _language_consensus_windows(segments, duration):
    """Pick a few well-separated later vocal windows from the primary timeline."""
    candidates = []
    for segment in segments or ():
        span = _segment_span(segment)
        if span is None:
            continue
        start, end = span
        if end <= LANGUAGE_CONSENSUS_MIN_START or start >= duration:
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        if not text or _intro_media_boilerplate(text):
            continue
        left = max(LANGUAGE_CONSENSUS_MIN_START, start - 0.35)
        right = min(duration, left + LANGUAGE_CONSENSUS_WINDOW_SECONDS)
        if right - left < LANGUAGE_PROBE_MIN_SECONDS:
            continue
        if candidates and left - candidates[-1][0] < LANGUAGE_CONSENSUS_MIN_SPACING:
            continue
        candidates.append((left, right))
        if len(candidates) >= LANGUAGE_CONSENSUS_MAX_WINDOWS:
            break
    return candidates


def _language_consensus_probe(model, audio_path, segments, current_language,
                              current_probability, cancel_cb=None):
    """Correct a first-window language mistake only after two later windows agree."""
    probability = _finite(current_probability, 0.0) or 0.0
    if probability >= LANGUAGE_CONSENSUS_MAX_PRIMARY_PROB and not _has_intro_credit_signal(segments):
        return None
    duration = _audio_duration(audio_path)
    windows = _language_consensus_windows(segments, duration)
    if len(windows) < LANGUAGE_CONSENSUS_REQUIRED:
        return None

    evidence = []
    for left, right in windows:
        _check_cancel(cancel_cb)
        clip = _read_pcm16_window(audio_path, left, right)
        if clip is None or len(clip) < round(LANGUAGE_PROBE_MIN_SECONDS * SAMPLE_RATE):
            continue
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
        del generator
        candidate = str(getattr(info, "language", "") or "").strip()
        confidence = _finite(getattr(info, "language_probability", None), 0.0) or 0.0
        if candidate and confidence >= LANGUAGE_CONSENSUS_MIN_PROB:
            evidence.append((candidate, confidence, left, right))
            if sum(1 for item in evidence if item[0] == candidate) >= LANGUAGE_CONSENSUS_REQUIRED:
                break

    grouped = {}
    for candidate, confidence, left, right in evidence:
        grouped.setdefault(candidate, []).append((confidence, left, right))
    if not grouped:
        return None
    winner, matches = max(
        grouped.items(),
        key=lambda item: (len(item[1]), sum(row[0] for row in item[1]) / len(item[1])),
    )
    if winner == current_language or len(matches) < LANGUAGE_CONSENSUS_REQUIRED:
        return None
    runner_up = max((len(rows) for lang, rows in grouped.items() if lang != winner), default=0)
    if runner_up >= len(matches):
        return None
    average = sum(row[0] for row in matches) / len(matches)
    if average < LANGUAGE_CONSENSUS_MIN_AVG_PROB:
        return None
    if probability >= 0.45 and average < probability + LANGUAGE_CONSENSUS_MIN_GAIN:
        return None
    return winner, average, evidence


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
        if candidate is None:
            consensus = _language_consensus_probe(
                model,
                audio_path,
                working,
                language,
                language_probability,
                cancel_cb=cancel_cb,
            )
            if consensus is not None:
                candidate_language, candidate_probability, evidence = consensus
                candidate = candidate_language, candidate_probability
                report["language_consensus"] = [
                    {
                        "language": item[0],
                        "probability": item[1],
                        "start": item[2],
                        "end": item[3],
                    }
                    for item in evidence
                ]
                report["language_probe_mode"] = "later_consensus"
        else:
            report["language_probe_mode"] = "first_voice"
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
                if report.get("language_probe_mode") == "later_consensus":
                    working, preserved_count = _preserve_vad_backed_consensus_intro(
                        original, rerun, confirmed_speech
                    )
                    if preserved_count:
                        report["language_intro_preserved"] = preserved_count
                else:
                    working, restored_count = _restore_primary_intro_gaps(original, rerun)
                    if restored_count:
                        report["language_intro_restored"] = restored_count
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

    if not report.get("intro_reconciled"):
        try:
            anchored, anchored_report = _anchored_no_prompt_recovery(
                model,
                probe["waveform"],
                working,
                language,
                confirmed_speech,
                cancel_cb=cancel_cb,
            )
            report.update(anchored_report)
            if anchored_report.get("anchored_recovery"):
                working = anchored
        except RuntimeError:
            raise
        except Exception as error:
            report["anchored_recovery_error"] = str(error)

    filtered, removed = filter_instrumental_intro_segments(
        working,
        onset_speech,
    )
    report["removed"] = removed
    if onset_speech:
        report["first_voice"] = min(start for start, _ in onset_speech)
    return filtered, language, report
