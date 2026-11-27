"""Conservative onset alignment for new lyrics, using the loaded ASR model.

This stage neither transcribes nor changes text. Uncertain alignment keeps the
existing interval; saved subtitles and reference SRTs never enter this path.
"""
import math
import re
import time
import unicodedata
import wave

from .lyric_refinement import ONSET_LEAD, finalize_cue_times


def _text_key(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def apply_onsets(cues, candidates, duration=None):
    """Accept small, confident delays; never advance or remove an existing cue."""
    output = [dict(cue) for cue in cues]
    changed = []
    for index, candidate in candidates.items():
        if not 0 <= index < len(cues):
            continue
        cue = cues[index]
        words = [word for word in candidate if word.get("word", "").strip()]
        if not words or _text_key("".join(w["word"] for w in words)) != _text_key(cue["text"]):
            continue
        try:
            start, end = float(words[0]["start"]), float(words[-1]["end"])
            probabilities = [float(w["probability"]) for w in words]
            spans = [(float(w["start"]), float(w["end"])) for w in words]
        except (KeyError, TypeError, ValueError):
            continue
        mean_prob = sum(probabilities) / len(probabilities)
        min_allowed = .06 if probabilities[0] >= .65 else .15
        mean_allowed = .62 if probabilities[0] >= .65 else .75
        if (not all(math.isfinite(v) for pair in spans for v in pair)
                or any(a > b for a, b in spans)
                or any(a[0] > b[0] or a[1] > b[1] for a, b in zip(spans, spans[1:]))
                or not all(math.isfinite(p) and 0 <= p <= 1 for p in probabilities)
                or probabilities[0] < .5 or min(probabilities) < min_allowed
                or mean_prob < mean_allowed):
            continue
        # Reject stretched/shortened readings, instrumental jumps and tiny cues.
        # The candidate may correct an early onset, not shorten an audible tail.
        span = cue["end"] - cue["start"]
        delay = start - (cue["start"] + ONSET_LEAD)
        limit = min(1.0, span * (.38 if probabilities[0] >= .75 else .25))
        following = cues[index + 1]["start"] if index + 1 < len(cues) else float("inf")
        if (.04 <= delay <= limit and abs(end - cue["end"]) <= 1.5
                and start - ONSET_LEAD < min(cue["end"], following) - .16
                and (duration is None or end <= duration)):
            output[index]["start"] = round(start - ONSET_LEAD, 3)
            changed.append(index)
    # Preserve transitions that already touched; delaying the incoming cue must
    # not introduce a new blank gap. Genuine pre-existing pauses stay untouched.
    for index in changed:
        if index and abs(cues[index - 1]["end"] - cues[index]["start"]) <= .02:
            output[index - 1]["end"] = max(output[index - 1]["end"], output[index]["start"])
    return finalize_cue_times(output, duration), changed


def _windows(cues, tokenizer, duration):
    """Bound audio and token batches, and never bridge an instrumental break."""
    batch, tokens, ranges = [], [], []
    left = right = 0.0
    padding = tokenizer.encode(" ...")
    for index, cue in enumerate(cues):
        start = max(0.0, cue["start"] - .6)
        end = min(duration, cue["end"] + .5)
        encoded = tokenizer.encode(" " + cue["text"])
        if batch and (end - left > 29.5 or len(tokens) + len(padding) + len(encoded) > 420
                      or cue["start"] - cues[batch[-1]]["end"] > 2.0):
            yield left, right, batch, tokens, ranges
            batch, tokens, ranges = [], [], []
        if end - start > 29.5 or len(padding) + len(encoded) > 420:
            continue  # Keep long/indivisible cues intact, with their old times.
        if not batch:
            left = start
        tokens.extend(padding)
        begin = len(tokens)
        tokens.extend(encoded)
        ranges.append((begin, len(tokens)))
        batch.append(index)
        right = end
    if batch:
        yield left, right, batch, tokens, ranges


def _align_window(model, tokenizer, audio, left, right, tokens, ranges):
    import numpy as np
    from faster_whisper.transcribe import pad_or_trim
    rate = model.feature_extractor.sampling_rate
    begin, end = round(left * rate), round(right * rate)
    audio.setpos(begin)
    clip = np.frombuffer(audio.readframes(end - begin), dtype="<i2").astype(np.float32) / 32768.0
    features = model.feature_extractor(clip)
    encoded = model.encode(pad_or_trim(features, model.feature_extractor.nb_max_frames))
    frames = len(clip) // model.feature_extractor.hop_length
    alignment = model.find_alignment(tokenizer, tokens, encoded, frames)
    cursor, mapped = 0, []
    for word in alignment:
        begin = cursor
        cursor += len(word["tokens"])
        mapped.append((begin, cursor, word))
    if cursor != len(tokens):
        raise ValueError("Alignment token coverage changed")
    return [[dict(word, start=left + word["start"], end=left + word["end"])
             for begin, end, word in mapped if begin >= a and end <= b]
            for a, b in ranges]


def align_lyric_onsets(model, audio_path, language, cues, cancel_cb=None, budget_s=15.0, progress_cb=None):
    """One bounded local alignment pass; failure/cap keeps unprocessed cue times."""
    report = dict(changed=0, windows=0, errors=0, capped=False, seconds=0.0)
    tick = time.monotonic()
    candidates = {}

    def check_cancel():
        if cancel_cb and cancel_cb():
            raise RuntimeError("Cancelled")

    check_cancel()
    if not cues:
        return cues, report
    try:
        from faster_whisper.tokenizer import Tokenizer
        tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                              task="transcribe", language=language)
        rate = model.feature_extractor.sampling_rate
        # Extractor already owns a mono PCM16 WAV. Read only the current window,
        # avoiding a second full-song decode/allocation on very long recordings.
        with wave.open(str(audio_path), "rb") as audio:
            if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                    or audio.getframerate() != rate or audio.getcomptype() != "NONE"):
                raise ValueError("Unexpected intermediate audio format")
            duration = audio.getnframes() / rate
            planned = list(_windows(cues, tokenizer, duration))
            total_windows = max(1, len(planned))
            for idx_w, (left, right, indices, tokens, ranges) in enumerate(planned, start=1):
                check_cancel()
                if time.monotonic() - tick >= budget_s:
                    report["capped"] = True
                    break
                report["windows"] += 1
                if progress_cb:
                    pct = 58 + int((idx_w / float(total_windows)) * 10)
                    progress_cb(pct, f"⏱ Căn mốc lời hát ({idx_w}/{total_windows})...")
                try:
                    words = _align_window(model, tokenizer, audio, left, right, tokens, ranges)
                    if len(words) != len(indices):
                        raise ValueError("Alignment cue coverage changed")
                    candidates.update(zip(indices, words))
                except Exception:
                    report["errors"] += 1
                    break  # Do not repeat a failed/OOM alignment on every window.
        check_cancel()
        output, changed = apply_onsets(cues, candidates, duration)
        report["changed"] = len(changed)
        report["word_candidates"] = candidates
    except Exception:
        check_cancel()
        report["errors"] += 1
        output = cues
    report["seconds"] = round(time.monotonic() - tick, 3)
    return output, report


def _lrc_align_windows(cues, tokenizer, duration):
    """Build <=29.0s / <=400-token windows for start-only LRC cues without crossing >3.5s breaks."""
    batch, tokens, ranges = [], [], []
    left = right = 0.0
    padding = tokenizer.encode(" ...")
    total = len(cues)
    for index, cue in enumerate(cues):
        c_start = float(cue["start"])
        next_start = float(cues[index + 1]["start"]) if index + 1 < total else float(duration)
        win_s = max(0.0, c_start - 0.45)
        win_e = min(float(duration), min(next_start + 0.30, c_start + 12.0))
        if win_e <= win_s + 0.15:
            continue
        encoded = tokenizer.encode(" " + cue["text"])
        if len(padding) + len(encoded) > 400 or (win_e - win_s) > 29.0:
            continue
        if batch and (
            (win_e - left) > 29.0
            or len(tokens) + len(padding) + len(encoded) > 400
            or (c_start - right) > 3.5
        ):
            yield left, right, batch, tokens, ranges
            batch, tokens, ranges = [], [], []
        if not batch:
            left = win_s
        tokens.extend(padding)
        begin = len(tokens)
        tokens.extend(encoded)
        ranges.append((begin, len(tokens)))
        batch.append(index)
        right = max(right, win_e)
    if batch:
        yield left, right, batch, tokens, ranges


def apply_lrc_ends(cues, candidates, *, language="en", duration=None, spacer_flags=None):
    """Verify LRC sync against forced word alignment, correct global master offset, and refine exact vocal ends.

    Returns (refined_cues, changed_indices, diagnostics_dict) when called with internal helper,
    while preserving 2-tuple return `(refined_cues, changed_indices)` for backward callers.
    """
    refined, changed, _diag = _apply_lrc_alignment(
        cues,
        candidates,
        language=language,
        duration=duration,
        spacer_flags=spacer_flags,
    )
    return refined, changed


def _apply_lrc_alignment(
    cues,
    candidates,
    *,
    language="en",
    duration=None,
    spacer_flags=None,
    strict_mv=False,
):
    """Align both global start offset (e.g. YouTube vs Spotify trim) and per-cue vocal endings from forced alignment.

    Also computes a strict sync-truth gate (`sync_verified`): if alignment coverage is too low or
    the LRC drifts unpredictably from the actual singing (`mad > 0.65s` or `|shift| > 1.80s`),
    `sync_verified` is False so the pipeline falls back to full Whisper ASR.
    """
    import statistics
    from .fast_lyrics import close_flicker_micro_gaps

    output = [dict(cue) for cue in cues]
    total = len(output)
    is_cjk = str(language or "").lower()[:2] in ("ja", "zh", "ko")
    tail_pad = 0.32 if is_cjk else 0.40
    diag = {
        "sync_verified": True,
        "global_shift": 0.0,
        "median_abs_residual": 0.0,
        "aligned_cues": 0,
        "reject_reason": "",
    }
    if not output or not candidates:
        if output:
            diag["sync_verified"] = False
            diag["reject_reason"] = "no_alignment_candidates"
        return output, [], diag

    parsed = {}
    start_deltas = []
    for index, candidate in candidates.items():
        if not 0 <= index < total:
            continue
        words = [word for word in (candidate or ()) if str(word.get("word", "")).strip()]
        if not words:
            continue
        try:
            w0_s = float(words[0]["start"])
            w0_e = float(words[0]["end"])
            w_end = float(words[-1]["end"])
            probs = [float(word["probability"]) for word in words]
            spans = [(float(word["start"]), float(word["end"])) for word in words]
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not all(math.isfinite(v) for pair in spans for v in pair)
            or any(a > b for a, b in spans)
            or not all(math.isfinite(p) and 0.0 <= p <= 1.0 for p in probs)
        ):
            continue
        mean_prob = sum(probs) / len(probs)
        last_prob = probs[-1]
        if mean_prob < 0.28:
            continue
        c_start = float(output[index]["start"])
        # DTW sometimes stretches a tiny first word over preceding silence (e.g. 'I' 13.5..15.6s);
        # when multiple words exist, anchor onset near w0_end - 0.25s to measure true vocal onset cleanly.
        w0_text = str(words[0].get("word", "")).strip()
        est_start = (
            (w0_e - 0.25)
            if (len(words) >= 2 and (w0_e - w0_s) > 0.65 and len(w0_text) <= 5)
            else w0_s
        )
        parsed[index] = (w0_s, est_start, w_end, mean_prob, last_prob)
        if mean_prob >= 0.35 and abs(est_start - c_start) <= 3.0:
            # Target acoustic vocal onset minus ONSET_LEAD (50ms) so subtitles feel snappy, not late
            start_deltas.append((est_start - ONSET_LEAD) - c_start)

    diag["aligned_cues"] = len(parsed)
    cov_ratio = 0.60 if strict_mv else 0.45
    min_required = min(total, max(3, int(math.ceil(total * cov_ratio))))
    if len(start_deltas) < min_required:
        diag["sync_verified"] = False
        diag["reject_reason"] = f"low_alignment_coverage({len(start_deltas)}/{total})"
        return output, [], diag

    global_shift = float(statistics.median(start_deltas))
    mad = float(statistics.median(abs(d - global_shift) for d in start_deltas))
    diag["global_shift"] = round(global_shift, 3)
    diag["median_abs_residual"] = round(mad, 3)

    max_shift = 2.40 if strict_mv else 1.80
    max_mad = 0.35 if strict_mv else 0.65
    if abs(global_shift) > max_shift or mad > max_mad:
        diag["sync_verified"] = False
        diag["reject_reason"] = f"lrc_drift(shift={global_shift:+.2f}s,mad={mad:.2f}s)"
        return output, [], diag

    # 1. Apply constant master offset (e.g. YouTube vs Spotify intro trim or MV intro logo).
    # For coarse-shifted MVs (`strict_mv`), lock any residual >=80ms; otherwise use asymmetric deadband.
    if strict_mv:
        applied_shift = global_shift if abs(global_shift) >= 0.08 else 0.0
    else:
        applied_shift = global_shift if (global_shift <= -0.14 or global_shift >= 0.25) else 0.0
    if applied_shift != 0.0:
        for cue in output:
            new_s = max(0.0, round(float(cue["start"]) + applied_shift, 3))
            new_e = max(new_s + 0.1, round(float(cue["end"]) + applied_shift, 3))
            cue["start"] = new_s
            cue["end"] = new_e

    # 2. Refine exact vocal endings for non-spacer cues
    changed = []
    for index, (w0_s, est_start, w_end, mean_prob, last_prob) in parsed.items():
        if spacer_flags and index < len(spacer_flags) and spacer_flags[index]:
            continue
        if last_prob < 0.15:
            continue
        c_start = float(output[index]["start"])
        next_t = (
            float(output[index + 1]["start"])
            if index + 1 < total
            else (float(duration) if duration is not None else float(output[index]["end"]))
        )
        if w0_s > c_start + 1.8 or w0_s < c_start - 2.6 or w_end < c_start + 0.35:
            continue
        proposed_end = round(min(next_t, max(c_start + 0.45, w_end + tail_pad)), 3)
        if duration is not None and math.isfinite(duration) and duration > 0:
            proposed_end = min(proposed_end, round(float(duration), 3))
        if proposed_end > c_start + 0.05 and abs(proposed_end - float(output[index]["end"])) >= 0.05:
            output[index]["end"] = proposed_end
            changed.append(index)

    finalized = finalize_cue_times(output, duration=duration)
    return close_flicker_micro_gaps(finalized, min_clean_gap=0.52), changed, diag


def align_lrc_ends(
    model,
    audio_path,
    language,
    cues,
    *,
    duration=None,
    spacer_flags=None,
    strict_mv=False,
    cancel_cb=None,
    budget_s=12.0,
    progress_cb=None,
):
    """One fast forced-alignment pass (no decoding) to verify LRC sync, fix global offset, and pinpoint vocal ends."""
    report = dict(
        changed=0,
        windows=0,
        errors=0,
        capped=False,
        seconds=0.0,
        sync_verified=True,
        global_shift=0.0,
        median_abs_residual=0.0,
        reject_reason="",
    )
    tick = time.monotonic()
    candidates = {}

    def check_cancel():
        if cancel_cb and cancel_cb():
            raise RuntimeError("Cancelled")

    check_cancel()
    if not cues:
        return cues, report
    try:
        from faster_whisper.tokenizer import Tokenizer

        lang_code = str(language or "en").lower()[:2]
        tokenizer = Tokenizer(
            model.hf_tokenizer,
            model.model.is_multilingual,
            task="transcribe",
            language=lang_code,
        )
        rate = model.feature_extractor.sampling_rate
        with wave.open(str(audio_path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != rate
                or audio.getcomptype() != "NONE"
            ):
                raise ValueError("Unexpected intermediate audio format")
            wav_dur = audio.getnframes() / rate
            eff_dur = float(duration) if (duration is not None and math.isfinite(duration) and duration > 0) else wav_dur
            planned = list(_lrc_align_windows(cues, tokenizer, wav_dur))
            total_windows = max(1, len(planned))
            for idx_w, (left, right, indices, tokens, ranges) in enumerate(planned, start=1):
                check_cancel()
                if time.monotonic() - tick >= budget_s:
                    report["capped"] = True
                    break
                report["windows"] += 1
                if progress_cb:
                    pct = 40 + int((idx_w / float(total_windows)) * 18)
                    progress_cb(pct, f"⏱ Căn mốc lời hát ({idx_w}/{total_windows})...")
                try:
                    words = _align_window(model, tokenizer, audio, left, right, tokens, ranges)
                    if len(words) != len(indices):
                        raise ValueError("LRC alignment cue coverage changed")
                    candidates.update(zip(indices, words))
                except Exception:
                    report["errors"] += 1
                    break
        check_cancel()
        output, changed, diag = _apply_lrc_alignment(
            cues,
            candidates,
            language=lang_code,
            duration=eff_dur,
            spacer_flags=spacer_flags,
            strict_mv=strict_mv,
        )
        report["changed"] = len(changed)
        report.update(diag)
        report["word_candidates"] = candidates
    except Exception:
        check_cancel()
        report["errors"] += 1
        output = cues
    report["seconds"] = round(time.monotonic() - tick, 3)
    return output, report
