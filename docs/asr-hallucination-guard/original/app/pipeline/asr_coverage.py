"""Recover speech omitted by long-window ASR without replacing accepted cues."""
import math
import re

from .aligner import refine_segments
from .jp_normalizer import universal_text_reconstruct

SAMPLE_RATE = 16000
WINDOW_SECONDS = 12.0
WINDOW_OVERLAP = 2.0
MIN_GAP_SECONDS = 4.0
AUDIT_MIN_GAP_SECONDS = 0.22
MIN_VOICED_GAP_SECONDS = 0.20
RETRY_CONTEXT_SECONDS = 1.35
SHORT_GAP_WORD_PROB = 0.58
SHORT_GAP_LOGPROB = -0.72
SHORT_GAP_MAX_NO_SPEECH = 0.35
LOW_PRIMARY_LOGPROB = -0.85
LOW_PRIMARY_WORD_PROB = 0.48
HIGH_PRIMARY_NO_SPEECH = 0.55
STRONG_RETRY_LOGPROB = -0.68
STRONG_RETRY_WORD_PROB = 0.60
MIN_WORD_PROB_GAIN = 0.10
MIN_LOGPROB_GAIN = 0.22


def _uncertain_filler(text):
    tokens = re.findall(r"[\w]+", text.lower())
    normalized = " ".join(tokens)
    if re.search(r"\b(?:thanks|thank you|you) for watching\b", normalized):
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
    """Return weak primary ASR spans worth one bounded local verification."""
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
    """Acoustic ASR coverage without display lead/tail padding."""
    coverage = []
    for segment in primary_segments or ():
        text = str(getattr(segment, "text", "") or "").strip()
        if text and _uncertain_filler(text):
            continue
        timed_words = []
        for item in getattr(segment, "words", None) or ():
            word_text = str(getattr(item, "word", "") or "").strip()
            start = _finite(getattr(item, "start", None))
            end = _finite(getattr(item, "end", None))
            if word_text and start is not None and end is not None and end >= start:
                timed_words.append((start, end))
        if timed_words:
            start = min(item[0] for item in timed_words)
            end = max(item[1] for item in timed_words)
        else:
            if not text:
                continue
            start = _finite(getattr(segment, "start", None))
            end = _finite(getattr(segment, "end", None))
        if start is None or end is None or end <= start:
            continue
        start = min(duration, max(0.0, start))
        end = min(duration, max(start, end))
        if end > start:
            coverage.append({"start": start, "end": end, "text": text})
    return coverage


def _merge_windows(windows, duration):
    """Coalesce overlapping audit windows, then keep every decode <= 12 s."""
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


def _retry_budget(duration):
    """Bound extra local ASR while scaling gently for normal song length."""
    return min(24, max(10, int(math.ceil(max(1.0, duration) / 60.0)) * 4))


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


def _meaningful_overlap(left, right, other_left, other_right, minimum=0.20):
    return max(0.0, min(right, other_right) - max(left, other_left)) >= minimum


def _normalized_text(text):
    return re.sub(r"[\W_]+", "", str(text or "").casefold())


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
    word_gain = (
        primary_word is not None
        and word_probability >= primary_word + MIN_WORD_PROB_GAIN
    )
    logprob_gain = (
        primary_logprob is not None
        and avg_logprob >= primary_logprob + MIN_LOGPROB_GAIN
    )
    return word_gain or logprob_gain


def _replacement_from_retry(decoded, offset, clip_end, primary, refine_options,
                            refine_fn=refine_segments):
    """Return one stronger local text candidate for a low-confidence primary span."""
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
        intersection = max(
            0.0,
            min(end, primary["end"]) - max(start, primary["start"]),
        )
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
            midpoint = (word_start + word_end) / 2
            if (
                word_text.strip()
                and primary["start"] - 0.12 <= midpoint <= primary["end"] + 0.12
            ):
                selected_words.append(item)
                words.append({"start": word_start, "end": word_end, "word": word_text})
        if not words:
            continue
        text = universal_text_reconstruct(
            selected_words,
            getattr(segment, "text", ""),
        )
        if not text.strip() or _uncertain_filler(text):
            continue
        check = {"start": start, "end": end, "text": text, "words": words}
        refined = refine_fn([check], **refine_options)
        if len(refined) != 1:
            continue
        confidence = _segment_confidence(segment)
        choices.append((
            confidence["word_probability"],
            confidence["avg_logprob"],
            refined[0],
        ))
    if not choices:
        return None
    return max(choices, key=lambda item: (item[0], item[1]))[2]


def _apply_text_replacement(cues, primary, replacement):
    """Replace text only when exactly one accepted cue owns the weak span."""
    matches = []
    for index, cue in enumerate(cues):
        start = _finite(cue.get("start"))
        end = _finite(cue.get("end"))
        if start is None or end is None or end <= start:
            continue
        intersection = max(
            0.0,
            min(end, primary["end"]) - max(start, primary["start"]),
        )
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
    if not new_text or _normalized_text(old_text) == _normalized_text(new_text):
        return cues, False
    updated = list(cues)
    updated[index] = dict(cues[index], text=new_text)
    return updated, True


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
            probability = sum(word.probability for word in words) / len(words)
            if not math.isfinite(probability) or probability < 0.35:
                continue
            if gap_end - gap_start < MIN_GAP_SECONDS:
                segment_logprob = _finite(getattr(segment, "avg_logprob", None), -math.inf)
                no_speech_prob = _finite(getattr(segment, "no_speech_prob", None), 0.0)
                if (
                    probability < SHORT_GAP_WORD_PROB
                    or segment_logprob < SHORT_GAP_LOGPROB
                    or no_speech_prob > SHORT_GAP_MAX_NO_SPEECH
                ):
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
        if overlap(cue["start"], cue["end"], speech) < max(0.25, (cue["end"] - cue["start"]) * 0.5):
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
    audit_gaps = missing_ranges(
        coverage_cues, duration, min_gap=AUDIT_MIN_GAP_SECONDS
    )
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
    combined = list(cues)
    attempted = set()
    voiced_gaps = _voiced_gaps(audit_gaps, speech)
    windows = _merge_windows(
        _plan_gap_windows(voiced_gaps, speech, duration)
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
            pending_suspects = [
                item for item in suspects
                if item["id"] not in checked_suspects
                and _meaningful_overlap(
                    left, right, item["start"], item["end"], minimum=0.20
                )
            ]
            if (
                overlap(left, right, current_gaps) < MIN_VOICED_GAP_SECONDS
                and not pending_suspects
            ):
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
            candidates = _candidate_cues(decoded, left, right, current_gaps, speech,
                                          refine_options, duration, refine_fn=refine_fn,
                                          boundary_gap=boundary_gap, boundary_tolerance=boundary_tolerance)
            before = len(combined)
            combined = merge_recovered(
                combined, candidates, safe_gap=boundary_gap,
                overlap_tolerance=boundary_tolerance,
            )
            accepted_ids = {id(item) for item in combined}
            coverage_cues.extend(
                {"start": item["start"], "end": item["end"], "text": item["text"]}
                for item in candidates if id(item) in accepted_ids
            )
            replacements = 0
            for primary in pending_suspects:
                checked_suspects.add(primary["id"])
                replacement = _replacement_from_retry(
                    decoded, left, right, primary, refine_options,
                    refine_fn=refine_fn,
                )
                if replacement is None:
                    continue
                combined, changed = _apply_text_replacement(
                    combined, primary, replacement
                )
                if changed:
                    replacements += 1
                    report["replaced_cues"] += 1
            report["attempts"].append({"start": left, "end": right, "round": round_index + 1,
                                       "added": len(combined) - before,
                                       "replaced": replacements})
        if "error" in report:
            break
        gaps = missing_ranges(
            coverage_cues, duration, min_gap=AUDIT_MIN_GAP_SECONDS
        )
        voiced_gaps = _voiced_gaps(gaps, speech)
        # One second round is allowed only for still-uncovered voiced regions.
        # Low-confidence text is never repeatedly rewritten.
        windows = _merge_windows(
            _plan_gap_windows(voiced_gaps, speech, duration),
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
