"""Offline matched ASR/coverage benchmark; never writes user media/subtitles."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import threading
import time

# Reuse the existing offline portable bootstrap, not the production job's DLL
# reset between jobs. One local model owner for the entire measured workload.
from asr_coverage_probe import ROOT, options, serialize


class Resources:
    def __enter__(self):
        import psutil
        self.process = psutil.Process()
        self.before_rss = self.process.memory_info().rss
        self.peak_rss = self.before_rss
        self.cpu_before = self.process.cpu_times()
        self.gpu_samples = []
        self.stopped = threading.Event()
        self.tick = time.perf_counter()
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()
        return self

    def sample(self):
        next_gpu = 0
        while not self.stopped.is_set():
            self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
            if time.perf_counter() >= next_gpu:
                try:
                    result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    values = result.stdout.strip().splitlines()[0].split(",")
                    self.gpu_samples.append([float(value.strip()) for value in values])
                except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                    pass
                next_gpu = time.perf_counter() + 0.5
            self.stopped.wait(0.1)

    def __exit__(self, *error):
        self.elapsed = time.perf_counter() - self.tick
        self.stopped.set()
        self.thread.join(timeout=4)
        cpu_after = self.process.cpu_times()
        self.peak_rss = max(self.peak_rss, self.process.memory_info().rss)
        self.metrics = dict(seconds=self.elapsed,
            process_cpu_seconds=(cpu_after.user + cpu_after.system - self.cpu_before.user - self.cpu_before.system),
            process_rss_before_mib=self.before_rss / 1024**2,
            process_rss_peak_mib=self.peak_rss / 1024**2,
            process_rss_extra_peak_mib=max(0, self.peak_rss - self.before_rss) / 1024**2,
            gpu_total_memory_peak_mib=max((sample[0] for sample in self.gpu_samples), default=None),
            gpu_utilization_peak_percent=max((sample[1] for sample in self.gpu_samples), default=None),
            gpu_samples=len(self.gpu_samples))


class CountedModel:
    def __init__(self, model):
        self.model = model
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(dict(samples=len(audio), seconds=len(audio) / 16000))
        return self.model.transcribe(audio, **kwargs)


def digest_tree(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


def main(output, rounds):
    import sys
    import tempfile
    import wave
    import torch
    import psutil
    from faster_whisper import WhisperModel, __version__
    from pipeline.extractor import extract_audio
    from pipeline.jp_normalizer import universal_text_reconstruct
    from pipeline.lyric_refinement import (refine_lyrics, finalize_cue_times, accepts_source_text, _key)
    from pipeline.asr_coverage import repair_missing_subtitles
    from pipeline.lyric_formatter import export_srt
    output.mkdir(parents=True, exist_ok=True)
    model_path = ROOT / "app_resources/whisper_models/large-v3"
    if not (model_path / "model.bin").is_file():
        raise RuntimeError("Local model required; no model download allowed")
    before_storage = digest_tree(ROOT / "storage/subtitles")
    with Resources() as loaded:
        model = WhisperModel(str(model_path), device="cuda", compute_type="float16", local_files_only=True)
    summary = dict(python=sys.version, faster_whisper=__version__, psutil=psutil.__version__,
        model="local large-v3", device="cuda/float16", rounds=rounds, model_loads=1,
        model_load=loaded.metrics, measurement="wall/CPU seconds and sampled process RSS; NVIDIA memory is entire GPU, including other apps",
        files=[])
    print("Model loaded", loaded.metrics, flush=True)
    for media in sorted((ROOT / "video").glob("*.mp4")):
        report = dict(media=media.name, file_size=media.stat().st_size,
            media_sha256=hashlib.sha256(media.read_bytes()).hexdigest(), rounds=[])
        with tempfile.TemporaryDirectory(prefix="botube-resources-") as temp:
            audio = Path(temp) / "audio.wav"
            tick = time.perf_counter()
            if not extract_audio(str(media), str(audio)):
                raise RuntimeError("Extraction failed")
            report["extract_seconds"] = time.perf_counter() - tick
            with wave.open(str(audio), "rb") as wav:
                report["duration"] = wav.getnframes() / wav.getframerate()
            for number in range(rounds):
                print("START", media.name, "round", number + 1, flush=True)
                with Resources() as primary:
                    generator, info = model.transcribe(str(audio), **options())
                    decoded = list(generator)
                raw = [dict(start=row.start, end=row.end,
                    text=universal_text_reconstruct(row.words, row.text),
                    words=[dict(start=word.start, end=word.end, word=word.word)
                           for word in row.words or []]) for row in decoded]
                cjk = info.language in ("ja", "zh", "ko")
                settings = dict(max_chars=22 if cjk else 74, min_pause=0.54 if cjk else 0.6,
                    start_offset=-0.2 if cjk else 0, end_padding=0.27 if cjk else 0.6,
                    gap_threshold=0.6, memory_reset_t=3.0)
                baseline = finalize_cue_times(refine_lyrics(raw, **settings), report["duration"])
                before = copy.deepcopy(baseline)
                counted = CountedModel(model)
                with Resources() as coverage:
                    repaired, diagnostic = repair_missing_subtitles(counted, audio, info.language,
                        baseline, settings, refine_fn=refine_lyrics, boundary_gap=0, boundary_tolerance=0.08)
                final = finalize_cue_times(repaired, report["duration"])
                item = dict(number=number + 1, language=info.language, primary=primary.metrics,
                    coverage=coverage.metrics, retry_count=len(counted.calls),
                    retry_audio_seconds=sum(call["seconds"] for call in counted.calls),
                    primary_cues=len(before), final_cues=len(final),
                    added=diagnostic["added_cues"],
                    all_primary_text_times_unchanged=all(cue in final for cue in before),
                    primary_input_unmodified=(baseline == before),
                    no_overlap=all(a["end"] <= b["start"] for a, b in zip(final, final[1:])),
                    diagnostic=diagnostic)
                accepted = "".join(_key(row["text"]) for row in raw
                                  if accepts_source_text(row["text"], timed_words=bool(row["words"])))
                refined = "".join(_key(row["text"]) for row in before)
                item["primary_character_inventory_preserved"] = Counter(accepted) == Counter(refined)
                (output / f"{media.stem}-round-{number + 1}.json").write_text(json.dumps(
                    dict(metrics=item, raw=[serialize(row) for row in decoded], primary=before, final=final),
                    ensure_ascii=False, indent=2), encoding="utf-8")
                export_srt(final, output / f"{media.stem}-round-{number + 1}.srt")
                report["rounds"].append(item)
                print("DONE", media.name, number + 1, "ASR", round(primary.elapsed, 2),
                      "coverage", round(coverage.elapsed, 2), "retries", len(counted.calls),
                      "added", item["added"], "preserved", item["all_primary_text_times_unchanged"], flush=True)
        report["median_asr_seconds"] = statistics.median(item["primary"]["seconds"] for item in report["rounds"])
        report["median_coverage_seconds"] = statistics.median(item["coverage"]["seconds"] for item in report["rounds"])
        summary["files"].append(report)
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["existing_subtitle_files_unchanged"] = digest_tree(ROOT / "storage/subtitles") == before_storage
    summary["existing_subtitle_file_count"] = len(before_storage)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FINISHED", len(summary["files"]), "videos; old subtitle files unchanged:",
          summary["existing_subtitle_files_unchanged"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/asr-resources")
    parser.add_argument("--rounds", type=int, default=3)
    arguments = parser.parse_args()
    if arguments.rounds < 1:
        parser.error("rounds must be positive")
    main(arguments.output, arguments.rounds)
