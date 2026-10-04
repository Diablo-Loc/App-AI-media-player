"""Offline ASR/refine coverage probe; media and existing subtitles stay read-only."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "app_resources/libs"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(LIBS))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ["PATH"] = str(ROOT / "bin") + os.pathsep + os.environ.get("PATH", "")
DLL_HANDLES = [os.add_dll_directory(str(path))
               for path in (LIBS / "ctranslate2", LIBS / "torch/lib")
               if os.name == "nt" and path.exists()]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def options():
    # Exact existing primary ASR options, no model/provider download.
    return dict(language=None, word_timestamps=True, condition_on_previous_text=False,
                beam_size=3, temperature=0.0, vad_filter=False,
                vad_parameters=dict(min_silence_duration_ms=1000), initial_prompt=" .+")


def serialize(segment):
    result = {key: getattr(segment, key) for key in (
        "id", "start", "end", "text", "avg_logprob", "no_speech_prob", "compression_ratio")}
    result["words"] = [{key: getattr(word, key) for key in ("start", "end", "word", "probability")}
                       for word in (segment.words or [])]
    return result


def probe(media, output, model_name, device, prefix_seconds=None, variants=False, repair=False):
    # Match the production spawned worker's import order and existing env guard.
    import torch
    from faster_whisper import WhisperModel
    from pipeline.extractor import extract_audio
    from pipeline.aligner import refine_segments
    from pipeline.jp_normalizer import universal_text_reconstruct
    from faster_whisper import __version__
    from faster_whisper.audio import decode_audio
    output.mkdir(parents=True, exist_ok=True)
    model_path = ROOT / "app_resources/whisper_models" / model_name
    if not (model_path / "model.bin").is_file():
        raise RuntimeError("Requested local model is missing; no download allowed")
    start = time.monotonic()
    model = WhisperModel(str(model_path), device=device,
                         compute_type="float16" if device == "cuda" else "int8",
                         local_files_only=True)
    print("Model loaded:", model_name, device, flush=True)
    for media_path in media:
        report = {"media": str(media_path), "model": model_name, "device": device,
                  "faster_whisper": __version__, "options": options()}
        with tempfile.TemporaryDirectory(prefix="botube-asr-probe-") as temp:
            audio = Path(temp) / "audio.wav"
            if not extract_audio(str(media_path), str(audio)):
                raise RuntimeError("Audio extraction failed")
            tick = time.monotonic()
            model_audio = str(audio)
            if prefix_seconds:
                import wave
                prefix_audio = Path(temp) / "prefix.wav"
                with wave.open(str(audio), "rb") as reader:
                    params = reader.getparams()
                    data = reader.readframes(round(prefix_seconds * reader.getframerate()))
                with wave.open(str(prefix_audio), "wb") as writer:
                    writer.setparams(params)
                    writer.writeframes(data)
                audio = prefix_audio
                model_audio = str(audio)
            segments, info = model.transcribe(model_audio, **options())
            segments = list(segments)
            report.update(language=info.language, language_probability=info.language_probability,
                          duration=info.duration, asr_seconds=time.monotonic() - tick,
                          raw=[serialize(segment) for segment in segments])
            raw = [{"start": segment.start, "end": segment.end,
                    "text": universal_text_reconstruct(segment.words, segment.text),
                    "words": [{"start": word.start, "end": word.end, "word": word.word}
                              for word in (segment.words or [])]} for segment in segments]
            cjk = info.language in ("ja", "zh", "ko")
            report["refined"] = refine_segments(raw, max_chars=22 if cjk else 74,
                min_pause=0.54 if cjk else 0.6, start_offset=-0.2 if cjk else 0,
                end_padding=0.27 if cjk else 0.6, gap_threshold=0.6, memory_reset_t=3.0)
            target = output / (media_path.stem + ".json")
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(media_path.name, "language:", info.language, "raw:", len(segments),
                  "first:", [(segment.start, segment.text) for segment in segments[:3]],
                  "refined:", len(report["refined"]), "seconds:", round(report["asr_seconds"], 1), flush=True)
            if repair:
                from pipeline.asr_coverage import repair_missing_subtitles
                repaired, diagnostic = repair_missing_subtitles(model, audio, info.language, report["refined"],
                    dict(max_chars=22 if cjk else 74, min_pause=0.54 if cjk else 0.6,
                         start_offset=-0.2 if cjk else 0, end_padding=0.27 if cjk else 0.6,
                         gap_threshold=0.6, memory_reset_t=3.0),
                    progress_cb=lambda percent, message: print(message, flush=True))
                (output / f"{media_path.stem}-repaired.json").write_text(json.dumps(
                    dict(cues=repaired, diagnostic=diagnostic), ensure_ascii=False, indent=2), encoding="utf-8")
                print("repaired:", repaired[:8], "report:", diagnostic, flush=True)
            if variants:
                for name, changes in (
                    ("no-prompt", dict(initial_prompt=None)),
                    ("intro-retry", dict(language=info.language, no_speech_threshold=None,
                                          initial_prompt=None, clip_timestamps=[0, min(30, info.duration)])),
                    ("intro-no-word-times", dict(language=info.language, no_speech_threshold=None,
                                                initial_prompt=None, word_timestamps=False,
                                                clip_timestamps=[0, min(30, info.duration)])),
                ):
                    tick = time.monotonic()
                    generator, variant_info = model.transcribe(model_audio, **dict(options(), **changes))
                    result = [serialize(segment) for segment in generator]
                    target = output / f"{media_path.stem}-{name}.json"
                    target.write_text(json.dumps(dict(options=dict(options(), **changes),
                        raw=result, seconds=time.monotonic() - tick), ensure_ascii=False, indent=2), encoding="utf-8")
                    print(name, [(segment["start"], segment["end"], segment["text"]) for segment in result], flush=True)
                waveform = decode_audio(str(audio))
                from faster_whisper.vad import get_speech_timestamps
                speech = get_speech_timestamps(waveform[:45 * 16000])
                (output / f"{media_path.stem}-speech.json").write_text(
                    json.dumps([{k: v / 16000 for k, v in span.items()} for span in speech], indent=2), encoding="utf-8")
                print("speech:", [{k: round(v / 16000, 2) for k, v in span.items()} for span in speech], flush=True)
                for left, right in ((0, 12), (10, 24), (20, 32)):
                    generator, _ = model.transcribe(waveform[left * 16000:right * 16000],
                        **dict(options(), language=info.language, initial_prompt=None, no_speech_threshold=None))
                    result = [serialize(segment) for segment in generator]
                    (output / f"{media_path.stem}-slice-{left}-{right}.json").write_text(
                        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    print("slice", left, right, [(segment["start"] + left, segment["end"] + left,
                                                segment["text"]) for segment in result], flush=True)
    print("Total seconds:", round(time.monotonic() - start, 1), flush=True)


def production_probe(media, output, model_name, device):
    """Exercise the real pipeline through export, bypass translation only."""
    import types
    from unittest.mock import patch
    import torch
    from ai import pipeline
    from pipeline.utils import TempFileManager
    translation = types.ModuleType("translate.pipeline")
    translation.TranslateMode = types.SimpleNamespace(PIVOT_VI="probe")
    translation.translate_pipeline = lambda subs, **kwargs: subs
    translation.clear_translator = lambda: None
    online = types.ModuleType("translate.online_logic")
    online.translate_online_pipeline = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Network is forbidden in this probe"))
    class Settings:
        def value(self, key, default=None):
            return {"ai_model": model_name, "device": device, "api_key": "",
                    "online_provider": "Local Default"}.get(key, default)
    output.mkdir(parents=True, exist_ok=True)
    for index, media_path in enumerate(media):
        with tempfile.TemporaryDirectory(prefix="botube-production-asr-") as temp:
            with patch.dict(sys.modules, {"translate.pipeline": translation, "translate.online_logic": online}), \
                    patch.object(pipeline, "QSettings", lambda *args: Settings()), \
                    patch.object(TempFileManager, "create_unique_path", return_value=Path(temp) / "audio.wav"):
                result = pipeline.run_ai_pipeline(str(media_path), str(output), f"probe-{index}",
                    progress_cb=lambda percent, message: print(percent, message, flush=True))
            rows = [{"start": sub.start, "end": sub.end, "text": sub.top.text}
                    for sub in result["segments"]]
            # Include the actual save/render boundary in an isolated probe tree.
            # Never open user storage or overwrite their existing subtitles.
            from core.subtitle_manager import SubtitleManager
            manager = SubtitleManager(str(output / "probe-storage"))
            saved_ass = manager.save_segments(f"probe-{index}", result["segments"], str(media_path))
            if not saved_ass:
                raise RuntimeError("Production subtitle save/render failed")
            saved = manager.get_raw_data(f"probe-{index}")
            (output / f"{media_path.stem}-saved.json").write_text(
                json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            if [(row["start"], row["end"]) for row in rows] != [
                    (row["start"], row["end"]) for row in saved["segments"]]:
                raise RuntimeError("Saving changed already-aligned subtitle times")
            if any(left["end"] > right["start"] for left, right in zip(rows, rows[1:])):
                raise RuntimeError("Production output contains overlapping cues")
            (output / f"{media_path.stem}-production.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Production output:", len(rows), rows[:3], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--prefix-seconds", type=float)
    parser.add_argument("--variants", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if args.production:
        production_probe(args.media, args.output, args.model, args.device)
    else:
        probe(args.media, args.output, args.model, args.device, args.prefix_seconds, args.variants, args.repair)
