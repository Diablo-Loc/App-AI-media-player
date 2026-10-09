"""Read-only accuracy audit: replay captured ASR, never run/save real-song ASR."""
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline.asr_coverage import missing_ranges
from pipeline.lyric_refinement import refine_lyrics, finalize_cue_times, join_tokens, _key


def saved_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "storage/subtitles").rglob("*") if p.is_file()}


def main():
    before = saved_hashes()
    reports = []
    for path in sorted((ROOT / "docs/asr-resources").glob("*-round-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        language = data["metrics"]["language"]
        duration = data["metrics"]["diagnostic"]["duration"]
        raw = [dict(row, text=join_tokens([w["word"] for w in row["words"]]) or row["text"])
               for row in data["raw"]]
        current = finalize_cue_times(refine_lyrics(raw,
            max_chars=22 if language in ("ja", "zh", "ko") else 74,
            min_pause=.54 if language in ("ja", "zh", "ko") else .6), duration)
        reference = json.loads((ROOT / "docs/lyric-phrases/replay" / path.name)
                               .read_text(encoding="utf-8"))["after"]
        reports.append(dict(dataset=path.name, language=language, cues=len(current),
            equal_recorded_phrase_output=current == reference,
            accepted_text_order_equal=_key(join_tokens([c["text"] for c in current]))
                == _key(join_tokens([c["text"] for c in reference])),
            no_overlap=all(a["end"] <= b["start"] for a, b in zip(current, current[1:])),
            in_bounds=all(0 <= c["start"] < c["end"] <= duration for c in current)))
    samples = {}
    for text in ("I love you.", "Eye of the tiger.", "This is fiction.",
                 "Keep your copyright.", "音楽が好きだ", "ご視聴ありがとうございました"):
        samples[text] = refine_lyrics([dict(start=1, end=3, text=text,
            words=[dict(start=1, end=3, word=text)])])
    tree = ast.parse((ROOT / "app/ai/pipeline.py").read_text(encoding="utf-8-sig"))
    options = [{kw.arg: ast.unparse(kw.value) for kw in node.keywords}
               for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute) and node.func.attr == "transcribe"]
    result = dict(reference="Captured ASR replay; not human lyrics/timing ground truth or fresh ASR",
        datasets=len(reports), videos=len({r["dataset"].rsplit("-round-", 1)[0] for r in reports}),
        captured_languages=dict(Counter(r["language"] for r in reports)), reports=reports,
        synthetic_credit_policy_outputs=samples,
        synthetic_three_second_gap=missing_ranges([dict(start=0, end=2, text="a"),
            dict(start=5, end=10, text="b")], 10),
        production_transcribe_kwargs=options, saved_files=len(before),
        saved_hashes_unchanged=before == saved_hashes())
    assert reports and all(all(r[k] for k in ("equal_recorded_phrase_output",
        "accepted_text_order_equal", "no_overlap", "in_bounds")) for r in reports)
    assert result["saved_hashes_unchanged"]
    output = ROOT / "docs/asr-accuracy-review"
    output.mkdir(parents=True, exist_ok=True)
    (output / "review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)
                                        + "\n", encoding="utf-8")
    (output / "saved-hashes.json").write_text(json.dumps(before, ensure_ascii=False, indent=2)
                                              + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "reports"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
