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
        if (not all(math.isfinite(v) for pair in spans for v in pair)
                or any(a > b for a, b in spans)
                or any(a[0] > b[0] or a[1] > b[1] for a, b in zip(spans, spans[1:]))
                or not all(math.isfinite(p) and 0 <= p <= 1 for p in probabilities)
                or probabilities[0] < .5 or min(probabilities) < .15
                or sum(probabilities) / len(probabilities) < .75):
            continue
        # Reject stretched/shortened readings, instrumental jumps and tiny cues.
        # The candidate may correct an early onset, not shorten an audible tail.
        span = cue["end"] - cue["start"]
        delay = start - (cue["start"] + ONSET_LEAD)
        limit = min(1.0, span * .25)
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


def align_lyric_onsets(model, audio_path, language, cues, cancel_cb=None, budget_s=15.0):
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
            for left, right, indices, tokens, ranges in _windows(cues, tokenizer, duration):
                check_cancel()
                if time.monotonic() - tick >= budget_s:
                    report["capped"] = True
                    break
                report["windows"] += 1
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
    except Exception:
        check_cancel()
        report["errors"] += 1
        output = cues
    report["seconds"] = round(time.monotonic() - tick, 3)
    return output, report
