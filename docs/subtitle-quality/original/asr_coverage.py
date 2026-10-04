"""Recover speech omitted by long-window ASR without replacing accepted cues."""
import math
import re

from .aligner import refine_segments
from .jp_normalizer import universal_text_reconstruct

SAMPLE_RATE = 16000
WINDOW_SECONDS = 12.0
WINDOW_OVERLAP = 2.0
MIN_GAP_SECONDS = 4.0


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


def missing_ranges(cues, duration):
    """Uncovered timeline ranges, including the beginning and end of the audio."""
    ranges = []
    cursor = 0.0
    for cue in sorted(cues, key=lambda cue: cue["start"]):
        start = min(duration, max(0.0, float(cue["start"])))
        end = min(duration, max(start, float(cue["end"])))
        if start - cursor >= MIN_GAP_SECONDS:
            ranges.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= MIN_GAP_SECONDS:
        ranges.append((cursor, duration))
    return ranges


def overlap(left, right, spans):
    return sum(max(0.0, min(right, end) - max(left, start)) for start, end in spans)


def plan_windows(gaps, speech, duration):
    windows = []
    for left, right in gaps:
        cursor = max(0.0, left - WINDOW_OVERLAP)
        while cursor < right:
            end = min(duration, cursor + WINDOW_SECONDS)
            if end <= cursor:
                break
            if overlap(max(left, cursor), min(right, end), speech) >= 0.35:
                windows.append((cursor, end))
            if end >= right:
                break
            cursor += WINDOW_SECONDS - WINDOW_OVERLAP
    return windows


def _check_cancel(cancel_cb):
    if cancel_cb and cancel_cb():
        raise RuntimeError("AI cancelled by user")


def _candidate_cues(segments, offset, clip_end, gaps, speech, refine_options, duration):
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
                margin = 0.12 if gap_end < duration else 0.0
                if start < gap_start or end + margin > gap_end:
                    continue
                if word.word and word.word.strip():
                    words.append(word)
            if not words:
                continue
            probability = sum(word.probability for word in words) / len(words)
            if not math.isfinite(probability) or probability < 0.35:
                continue
            # Check the original complete text first: slicing words must not
            # turn a rejected credit into an apparently acceptable fragment.
            check = {"start": offset + segment.start, "end": offset + segment.end,
                     "text": universal_text_reconstruct(segment.words, segment.text), "words": []}
            if not refine_segments([check], **refine_options):
                continue
            raw.append({"start": offset + words[0].start, "end": offset + words[-1].end,
                        "text": universal_text_reconstruct(words, segment.text),
                        "words": [{"start": offset + word.start, "end": offset + word.end,
                                   "word": word.word} for word in words]})
    result = []
    for cue in refine_segments(raw, **refine_options):
        cue["end"] = min(cue["end"], duration)
        for left, right in gaps:
            if cue["start"] >= left and cue["start"] < right:
                cue["end"] = min(cue["end"], right - 0.12 if right < duration else right)
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


def merge_recovered(existing, candidates):
    """Never rewrite the text/timing of an existing cue, including repeated lyrics."""
    result = list(existing)
    # Prefer a complete phrase from an overlapping clip over a truncated edge.
    # Only recovery candidates compete; original cues always win.
    for cue in sorted(candidates, key=lambda cue: (-(cue["end"] - cue["start"]),
                                                  -len(cue["text"]), cue["start"])):
        if any(cue["start"] < old["end"] + 0.12 and cue["end"] > old["start"] - 0.12
               for old in result):
            continue
        result.append(cue)
    return sorted(result, key=lambda cue: cue["start"])


def repair_missing_subtitles(model, audio_path, language, cues, refine_options,
                             cancel_cb=None, progress_cb=None):
    """Retry missing speech in bounded clips using the already loaded model.

    VAD only selects retries; it never removes audio from the primary pass.
    Returns cues and a diagnostic report, not a claim of perfect recognition.
    """
    import wave
    with wave.open(str(audio_path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    gaps = missing_ranges(cues, duration)
    report = {"duration": duration, "gaps_before": gaps, "attempts": [], "added_cues": 0}
    if not gaps:
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
    _check_cancel(cancel_cb)
    combined = list(cues)
    recovered = []
    attempted = set()
    windows = plan_windows(gaps, speech, duration)
    for round_index in range(2):
        for left, right in windows:
            token = (round(left, 3), round(right, 3))
            if token in attempted:
                continue
            attempted.add(token)
            _check_cancel(cancel_cb)
            current_gaps = missing_ranges(combined, duration)
            if overlap(left, right, current_gaps) < 0.35:
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
            candidates = _candidate_cues(decoded, left, right, report["gaps_before"], speech,
                                          refine_options, duration)
            before = len(combined)
            recovered.extend(candidates)
            combined = merge_recovered(cues, recovered)
            report["attempts"].append({"start": left, "end": right, "round": round_index + 1,
                                       "added": len(combined) - before})
        if "error" in report:
            break
        gaps = missing_ranges(combined, duration)
        # A second, tighter clip helps short vocals drowned in a long music bed.
        windows = [(max(0.0, left - 2), min(duration, right + 2))
                   for gap_start, gap_end in gaps for left, right in speech
                   if min(gap_end, right) - max(gap_start, left) >= 0.35
                   and right - left <= WINDOW_SECONDS - 4]
        if not windows:
            break
    report["added_cues"] = len(combined) - len(cues)
    report["unresolved_speech"] = [(max(left, start), min(right, end))
        for left, right in missing_ranges(combined, duration) for start, end in speech
        if min(right, end) - max(left, start) >= 0.35]
    return combined, report
