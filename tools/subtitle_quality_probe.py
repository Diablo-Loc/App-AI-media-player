"""Replay captured real ASR words; write only docs/subtitle-quality artifacts."""
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline.aligner import refine_segments
from pipeline.lyric_refinement import (refine_lyrics, finalize_cue_times, join_tokens,
                                       mark_final_timing, accepts_source_text, _key)
from pipeline.lyric_formatter import export_srt, export_lrc
from subtitle.converter import refined_to_subtitles
from core.subtitle_manager import SubtitleManager


def overlaps(rows):
    return sum(a["end"] > b["start"] for a, b in zip(rows, rows[1:]))


def main():
    output = ROOT / "docs/subtitle-quality/replay"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted((ROOT / "docs/asr-coverage/verified-strict").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "raw" not in data:
            continue
        cjk = data["language"] in ("ja", "zh", "ko")
        options = dict(max_chars=22 if cjk else 74, min_pause=0.54 if cjk else 0.6,
                       start_offset=-0.2 if cjk else 0, end_padding=0.27 if cjk else 0.6,
                       gap_threshold=0.6, memory_reset_t=3.0)
        raw = [dict(start=row["start"], end=row["end"], words=row["words"],
                    text=join_tokens([word["word"] for word in row["words"]]) or row["text"])
               for row in data["raw"]]
        old = refine_segments(raw, **options)
        new = finalize_cue_times(refine_lyrics(raw, **options), data["duration"])
        legacy_saved = [dict(start=max(0, row["start"] - 0.1), end=row["end"] + 0.1) for row in old]
        expected = Counter()
        for row in raw:
            if accepts_source_text(row["text"], timed_words=bool(row["words"])):
                expected.update(_key(row["text"]))
        actual = Counter(_key(" ".join(row["text"] for row in new)))
        report = dict(video=path.stem, duration=data["duration"], language=data["language"],
                      original_cues=len(old), new_cues=len(new),
                      original_refined_overlaps=overlaps(old), original_saved_overlaps=overlaps(legacy_saved),
                      new_overlaps=overlaps(new), recognized_characters_preserved=(actual == expected),
                      source_reference="captured raw ASR, not human lyric/timing ground truth")
        (output / f"{path.stem}.json").write_text(json.dumps(
            dict(report=report, original=old, refined=new), ensure_ascii=False, indent=2), encoding="utf-8")
        export_srt(new, output / f"{path.stem}.srt")
        export_lrc(new, output / f"{path.stem}.lrc")
        manager = SubtitleManager(str(output / "probe-storage"))
        subtitles = refined_to_subtitles(new, data["language"])
        mark_final_timing(subtitles)
        manager.save_segments(path.stem, subtitles)
        report["new_saved_overlaps"] = overlaps(manager.get_raw_data(path.stem)["segments"])
        results.append(report)
    (output / "comparison.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
