"""Offline production benchmark; annotations are evaluation-only, never ASR input.

Supply a local Jamendo plan with audio_path, words and provenance metadata.
Both tail policies share the exact same recognition/alignment result.
"""
import argparse
import ast
import difflib
import json
from pathlib import Path
import re
import statistics
import subprocess
import time
import unicodedata


def tokens(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", text)


def evaluate(cues, reference):
    predicted, owners, expected, boundaries = [], [], [], []
    for index, cue in enumerate(cues):
        parts = tokens(cue["text"])
        predicted.extend(parts)
        owners.extend([index] * len(parts))
    for word in reference:
        parts = tokens(word["text"])
        expected.extend(parts)
        boundaries.extend([(word["start"], word["end"])] * len(parts))
    matcher = difflib.SequenceMatcher(None, predicted, expected, autojunk=False)
    matches = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            matches[block.a + offset] = block.b + offset
    grouped = {}
    for index, owner in enumerate(owners):
        grouped.setdefault(owner, []).append(index)
    measured = []
    for owner, indices in grouped.items():
        if (indices[0] not in matches or indices[-1] not in matches
                or sum(i in matches for i in indices) < .6 * len(indices)):
            continue
        first, last = matches[indices[0]], matches[indices[-1]]
        if first > last:
            continue
        cue = cues[owner]
        measured.append(dict(cue=owner, start_error=cue["start"] - boundaries[first][0],
                             end_error=cue["end"] - boundaries[last][1]))
    return dict(cue_count=len(cues), matched_cues=len(measured), word_count=len(predicted),
        reference_word_count=len(expected), matched_words=len(matches),
        reference_word_recall=len(matches) / max(1, len(expected)),
        onset_mae_s=statistics.mean(abs(r["start_error"]) for r in measured) if measured else None,
        end_mae_s=statistics.mean(abs(r["end_error"]) for r in measured) if measured else None,
        end_bias_s=statistics.mean(r["end_error"] for r in measured) if measured else None,
        early_ends=sum(r["end_error"] < -.1 for r in measured),
        late_ends=sum(r["end_error"] > .3 for r in measured), measurements=measured)


def run(plan_path, output, baseline):
    from tools.asr_coverage_probe import ROOT, production_probe
    from unittest.mock import patch
    import faster_whisper
    import psutil
    from pipeline import lyric_refinement, lyric_timing
    output.mkdir(parents=True, exist_ok=True)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    original_display = lyric_refinement.finalize_display_times
    source = subprocess.check_output(["git", "show", baseline + ":app/pipeline/lyric_refinement.py"],
                                      cwd=ROOT).decode("utf-8")
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == "finalize_display_times")
    namespace = dict(original_display.__globals__)
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<frozen-tail-baseline>", "exec"), namespace)
    old_display = namespace["finalize_display_times"]
    real_model, real_align = faster_whisper.WhisperModel, lyric_timing.align_lyric_onsets
    process = psutil.Process()
    report = dict(baseline=baseline, source="https://huggingface.co/datasets/jamendolyrics/jamendolyrics",
        protocol="One production pipeline run per audio with existing primary/recovery calls; both tail policies share its cues. Ordered text matching to word annotations; unmatched cues/words reported. No reference text/times supplied to ASR.",
        cases=[])
    for case in plan:
        audio_path = (ROOT / case["audio_path"]).resolve()
        if not audio_path.is_relative_to(ROOT):
            raise ValueError("Test media is outside workspace")
        captured, alignment_reports, calls = [], [], []

        def model_factory(path, *args, **kwargs):
            if not (Path(path) / "model.bin").is_file():
                raise AssertionError("Model downloads are forbidden")
            kwargs["local_files_only"] = True
            model = real_model(path, *args, **kwargs)
            transcribe = model.transcribe

            def tracked(*args, **kwargs):
                calls.append(dict(word_timestamps=kwargs.get("word_timestamps"),
                                  language=kwargs.get("language")))
                return transcribe(*args, **kwargs)

            model.transcribe = tracked
            return model

        def align(*args, **kwargs):
            cues, info = real_align(*args, **kwargs)
            alignment_reports.append(info)
            return cues, info

        def display(cues, *args, **kwargs):
            old, new = old_display(cues, *args, **kwargs), original_display(cues, *args, **kwargs)
            if [c["text"] for c in old] != [c["text"] for c in new]:
                raise AssertionError("Tail adjustment changed lyrics")
            if [c["start"] for c in old] != [c["start"] for c in new]:
                raise AssertionError("Tail adjustment changed onsets")
            captured.append((old, new))
            return new

        tick, cpu_before = time.monotonic(), process.cpu_times()
        print("BENCHMARK_START", case["case_id"], flush=True)
        try:
            with patch.object(faster_whisper, "WhisperModel", model_factory), \
                    patch.object(lyric_refinement, "finalize_display_times", display), \
                    patch.object(lyric_timing, "align_lyric_onsets", align):
                production_probe([audio_path], output / case["case_id"], "large-v3", "cuda")
            if len(captured) != 1:
                raise AssertionError("Unexpected production display count")
            old, new = captured[0]
            cpu_after = process.cpu_times()
            entry = dict(case_id=case["case_id"], name=case["name"], language=case["language"],
                excerpt=case.get("excerpt", False), duration_s=case["duration_s"],
                genre=case["genre"], lyric_overlap=case["lyric_overlap"], polyphonic=case["polyphonic"],
                non_lexical=case["non_lexical"], audio_sha256=case["sha256"],
                max_reference_word_duration_s=case["_long"], max_reference_words_per_s=case["_rate"],
                before=evaluate(old, case["words"]), after=evaluate(new, case["words"]),
                seconds=time.monotonic() - tick, cpu_seconds=cpu_after.user + cpu_after.system
                    - cpu_before.user - cpu_before.system, rss_after_bytes=process.memory_info().rss,
                alignment=alignment_reports, asr_calls=len(calls), translation_calls=0)
            (output / case["case_id"] / "paired-display.json").write_text(
                json.dumps(dict(before=old, after=new), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as error:
            entry = dict(case_id=case["case_id"], error=str(error), seconds=time.monotonic() - tick)
        report["cases"].append(entry)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("BENCHMARK_END", case["case_id"], {k: v for k, v in entry.items()
              if k in ("error", "seconds", "asr_calls", "alignment")}, flush=True)
    for label in ("before", "after"):
        rows = [m for c in report["cases"] if label in c for m in c[label]["measurements"]]
        report[label] = dict(matched_cues=len(rows),
            end_mae_s=statistics.mean(abs(r["end_error"]) for r in rows) if rows else None,
            end_bias_s=statistics.mean(r["end_error"] for r in rows) if rows else None,
            early_ends=sum(r["end_error"] < -.1 for r in rows),
            late_ends=sum(r["end_error"] > .3 for r in rows))
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FINAL_BENCHMARK", report["before"], report["after"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", default="8b13e8d")
    args = parser.parse_args()
    run(args.plan, args.output, args.baseline)
