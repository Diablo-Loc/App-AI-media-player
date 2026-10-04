"""New generation quality and saved-subtitle compatibility, without GPU/network."""
import ast
from collections import Counter
import copy
import hashlib
import json
import logging
from pathlib import Path
import pickle
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline.aligner import refine_segments as legacy_refine
from pipeline.lyric_refinement import (refine_lyrics, finalize_cue_times,
    compress_fused_fillers, mark_final_timing, join_tokens, accepts_source_text, _key)
from pipeline.asr_coverage import _candidate_cues
from core.subtitle_manager import SubtitleManager, SubtitleStatus
from subtitle.converter import refined_to_subtitles
from subtitle.timing_format import srt_time, lrc_time, ass_time


def word(start, end, text):
    return dict(start=start, end=end, word=text)


def segment(start, end, text, words=None):
    return dict(start=start, end=end, text=text, words=words or [])


def assert_timeline(test, cues, duration=None):
    for cue in cues:
        test.assertGreater(cue["end"], cue["start"])
        test.assertGreaterEqual(cue["start"], 0)
        if duration is not None:
            test.assertLessEqual(cue["end"], duration)
    for left, right in zip(cues, cues[1:]):
        test.assertLessEqual(left["end"], right["start"])


class LyricRefinementTests(unittest.TestCase):
    def test_onset_does_not_invert_negative_offset_or_add_large_tail(self):
        raw = [segment(10, 12, "世界中", [word(10, 11, "世界"), word(11, 12, "中")])]
        old = legacy_refine(raw)
        new = refine_lyrics(raw)
        self.assertEqual(old[0]["start"], 10.2)
        self.assertEqual(new, [dict(start=9.95, end=12.0, text="世界中")])

    def test_identical_and_near_identical_lyrics_at_distinct_times_survive(self):
        raw = [segment(1, 2, "Sing again."), segment(2.05, 3, "Sing again."),
               segment(3.05, 4, "Sing again!"), segment(4.05, 5, "Sing again.")]
        self.assertEqual(len(legacy_refine(raw, start_offset=0)), 3)
        new = refine_lyrics(raw)
        self.assertEqual([cue["text"] for cue in new], [row["text"] for row in raw])
        assert_timeline(self, new)

    def test_repeated_timed_words_and_real_la_ha_chorus_are_not_truncated(self):
        tokens = ["Ha"] * 10 + ["la"] * 10 + ["go"] * 8
        words = [word(i * 0.3, (i + 1) * 0.3, text) for i, text in enumerate(tokens)]
        new = refine_lyrics([segment(0, 8.4, " ".join(tokens), words)], max_chars=40)
        self.assertEqual(" ".join(cue["text"] for cue in new).split(), tokens)
        assert_timeline(self, new)

    def test_runaway_filter_does_not_edit_meaningful_words_or_separate_repetitions(self):
        self.assertEqual(compress_fused_fillers("hahahahahahahahaha!"), "hahaha!")
        for text in ("ha ha ha ha ha ha ha ha", "no no no no", "banana", "人々人々人々人々", "hahaha"):
            self.assertEqual(compress_fused_fillers(text), text)

    def test_long_filler_run_with_stalled_word_times_is_shortened_not_real_performance(self):
        words = [word(1, 1, "ha") for _ in range(10)]
        cues = refine_lyrics([segment(1, 1, " ".join(["ha"] * 10), words)])
        self.assertEqual(cues[0]["text"], "ha ha ha")
        progressing = [word(1 + i * 0.2, 1.2 + i * 0.2, "ha") for i in range(10)]
        cues = refine_lyrics([segment(1, 3, " ".join(["ha"] * 10), progressing)])
        self.assertEqual(" ".join(cue["text"] for cue in cues).split(), ["ha"] * 10)
        meaningful = [word(1, 1, "人") for _ in range(10)]
        cues = refine_lyrics([segment(1, 1, "人" * 10, meaningful)])
        self.assertEqual(cues[0]["text"], "人" * 10)

    def test_duplicate_acoustic_span_is_removed_but_repeated_performance_is_kept(self):
        raw = [segment(1, 2, "Sing again."), segment(1.01, 2.01, "Sing again."),
               segment(2.02, 3, "Sing again.")]
        self.assertEqual([cue["text"] for cue in refine_lyrics(raw)], ["Sing again."] * 2)

    def test_repeated_lyrics_with_overlapping_imprecise_asr_spans_are_not_deleted(self):
        raw = [segment(1, 4, "Sing again."), segment(1.2, 4.2, "Sing again.")]
        result = refine_lyrics(raw)
        self.assertEqual([cue["text"] for cue in result], ["Sing again."] * 2)
        assert_timeline(self, result)

    def test_short_real_lyrics_are_not_deleted_by_weak_you_or_music_filter(self):
        raw = [segment(1, 2, "I love you.", [word(1, 2, "I love you.")]),
               segment(2.1, 3, "I love you.", [word(2.1, 3, "I love you.")]),
               segment(4, 5, "Music", [word(4, 5, "Music")])]
        self.assertEqual([cue["text"] for cue in refine_lyrics(raw)], ["I love you."] * 2 + ["Music"])
        self.assertEqual(legacy_refine(raw), [])
        self.assertFalse(accepts_source_text("I love you."))
        self.assertFalse(accepts_source_text("thanks for watching", timed_words=True))

    def test_cross_chunk_boundary_word_duplicate_only_removed_at_same_acoustic_span(self):
        raw = [segment(1, 3, "We sing", [word(1, 2, "We"), word(2, 3, "sing")]),
               segment(2, 5, "sing again sing", [word(2, 3, "sing"), word(3, 4, "again"), word(4, 5, "sing")])]
        self.assertEqual(refine_lyrics(raw)[0]["text"], "We sing again sing")

    def test_sentence_punctuation_and_newlines_take_priority_over_chunk_boundaries(self):
        raw = [segment(1, 2, "Dr. Who", [word(1, 1.3, "Dr."), word(1.3, 2, "Who")]),
               segment(2, 5, "is here. Another line", [word(2, 2.3, "is"), word(2.3, 3, "here."),
                   word(3.1, 4, "Another\n"), word(4.1, 5, "line")])]
        self.assertEqual([cue["text"] for cue in refine_lyrics(raw)], ["Dr. Who is here.", "Another", "line"])

    def test_soft_length_target_does_not_cut_phrase_before_natural_pause(self):
        words = [word(1 + i * 0.3, 1.3 + i * 0.3, token)
                 for i, token in enumerate(["a", "small", "complete", "phrase"])]
        words.append(word(3, 4, "next"))
        cues = refine_lyrics([segment(1, 4, "a small complete phrase next", words)], max_chars=15)
        self.assertEqual([cue["text"] for cue in cues], ["a small complete phrase", "next"])

    def test_short_cues_do_not_reintroduce_overlap_via_minimum_duration(self):
        raw = [segment(1, 1.04, "A.", [word(1, 1.04, "A.")]),
               segment(1.1, 1.14, "B!", [word(1.1, 1.14, "B!")]),
               segment(1.2, 1.24, "C?", [word(1.2, 1.24, "C?")])]
        old = legacy_refine(raw, start_offset=0)
        self.assertTrue(any(a["end"] > b["start"] for a, b in zip(old, old[1:])))
        assert_timeline(self, refine_lyrics(raw))

    def test_zero_duration_cjk_repetitions_and_single_character_lines_survive(self):
        raw = [segment(1, 2, "人人人", [word(1, 1.2, "人"), word(1.2, 1.2, "人"), word(1.2, 2, "人")]),
               segment(3, 3, "I", [word(3, 3, "I")])]
        cues = refine_lyrics(raw)
        self.assertEqual([cue["text"] for cue in cues], ["人人人", "I"])
        assert_timeline(self, cues)

    def test_invalid_times_are_excluded_and_input_is_not_mutated(self):
        raw = [segment(1, 3, "safe words", [word(2, 3, "words"), word(1, 2, "safe"),
              word(float("nan"), 2, "bad"), word(3, 2, "bad")]), segment(float("inf"), 4, "invalid")]
        before = copy.deepcopy(raw)
        cues = refine_lyrics(raw)
        self.assertEqual(cues[0]["text"], "safe words")
        self.assertEqual(raw[0]["words"][:2], before[0]["words"][:2])
        assert_timeline(self, cues)

    def test_join_punctuation_cjk_latin_and_korean(self):
        self.assertEqual(join_tokens(["I", "love", "you", ",", "世界", "中", "。"]), "I love you, 世界中。")
        self.assertEqual(join_tokens(["너를", "사랑해"]), "너를 사랑해")

    def test_finalization_preserves_text_and_never_overlaps_on_many_short_intervals(self):
        rng = random.Random(1234)
        cues = [dict(start=rng.randrange(0, 1000) / 100, end=20, text=f"token{i}") for i in range(200)]
        before = copy.deepcopy(cues)
        result = finalize_cue_times(cues, duration=20)
        self.assertEqual(Counter(" ".join(cue["text"] for cue in result).split()),
                         Counter(cue["text"] for cue in cues))
        self.assertEqual(cues, before)
        assert_timeline(self, result, 20)
        self.assertEqual(finalize_cue_times(result, duration=20), result)

    def test_recovery_uses_new_profile_and_preserves_two_repeated_lines(self):
        words = [SimpleNamespace(start=1, end=2, word="Sing again.", probability=0.9),
                 SimpleNamespace(start=2.1, end=3, word="Sing again.", probability=0.9)]
        decoded = [SimpleNamespace(start=1, end=3, text="Sing again. Sing again.",
                                  words=words, avg_logprob=-0.2)]
        cues = _candidate_cues(decoded, 0, 12, [(0, 30)], [(0, 30)], {}, 30, refine_fn=refine_lyrics)
        self.assertEqual([cue["text"] for cue in cues], ["Sing again."] * 2)
        assert_timeline(self, cues)

    def test_recovery_keeps_whole_boundary_word_without_overlapping_next_cue(self):
        words = [SimpleNamespace(start=28.76, end=29.58, word="壊れた", probability=0.9),
                 SimpleNamespace(start=29.58, end=30.02, word="世界", probability=0.9),
                 SimpleNamespace(start=30.3, end=31.5, word="息を吸って", probability=0.9)]
        decoded = [SimpleNamespace(start=28.76, end=31.5, text="壊れた世界 息を吸って",
                                  words=words, avg_logprob=-0.2)]
        cues = _candidate_cues(decoded, 0, 32, [(0, 29.95)], [(0, 32)], {}, 60,
                              refine_fn=refine_lyrics, boundary_gap=0, boundary_tolerance=0.08)
        self.assertEqual([cue["text"] for cue in cues], ["壊れた世界"])
        self.assertLessEqual(cues[0]["end"], 29.95)
        from pipeline.asr_coverage import merge_recovered
        existing = [dict(start=29.95, end=34, text="息を吸って")]
        result = merge_recovered(existing, cues, safe_gap=0)
        self.assertEqual(len(result), 2)
        self.assertIs(result[1], existing[0])
        assert_timeline(self, result)

    def test_captured_three_video_word_inventory_is_retained_after_splitting(self):
        for path in sorted((ROOT / "docs/asr-coverage/verified-strict").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if "raw" not in data:
                continue
            with self.subTest(video=path.stem):
                source = [segment(row["start"], row["end"], join_tokens([w["word"] for w in row["words"]])
                                  or row["text"], row["words"]) for row in data["raw"]]
                cues = refine_lyrics(source, max_chars=22 if data["language"] in ("ja", "zh", "ko") else 74)
                expected = Counter()
                for row in source:
                    if accepts_source_text(row["text"], timed_words=bool(row["words"])):
                        expected.update(_key(join_tokens([w["word"] for w in row["words"]]) or row["text"]))
                actual = Counter(_key(" ".join(cue["text"] for cue in cues)))
                self.assertEqual(actual, expected)
                assert_timeline(self, finalize_cue_times(cues, data["duration"]), data["duration"])


class SavedSubtitleCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="botube-quality-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = SubtitleManager(str(self.root / "storage"))
        self.media = self.root / "old.mp4"
        self.media.write_bytes(b"synthetic-media")
        self.mid = self.manager.get_reliable_id(self.media)

    def test_marked_new_objects_survive_pickle_and_save_without_second_padding(self):
        cues = [dict(start=1, end=1.1, text="Hello."), dict(start=1.1, end=2, text="Hello.")]
        subs = refined_to_subtitles(cues, lang="en")
        mark_final_timing(subs)
        subs = pickle.loads(pickle.dumps(subs))
        self.manager.save_segments("new", subs)
        saved = self.manager.get_raw_data("new")["segments"]
        self.assertEqual([(cue["start"], cue["end"]) for cue in saved], [(1, 1.1), (1.1, 2)])
        self.assertTrue(all(set(cue) == {"start", "end", "jp", "en", "vi"} for cue in saved))
        assert_timeline(self, [dict(cue, text=cue["jp"]) for cue in saved])

    def test_unmarked_legacy_objects_keep_original_cleaning_contract(self):
        source = json.loads((ROOT / "tests/fixtures/legacy_contracts.json").read_text(encoding="utf-8"))["contracts"]["clean_segment"]["source"]
        namespace = dict(Any=object, Dict=dict, logger=logging.getLogger("quality-test"))
        exec(compile(source, "captured-legacy-clean", "exec"), namespace)
        for sample in (SimpleNamespace(start=1, end=2, top="JP", middle="EN", bottom="VI"),
                       SimpleNamespace(start=0.02, end=1.2345, text="Legacy")):
            self.assertEqual(self.manager._clean_segment(sample), namespace["_clean_segment"](None, sample))

    def test_open_old_subtitles_and_save_new_song_do_not_modify_old_bytes(self):
        payload = dict(media_id=self.mid, original_name="old", segments=[
            dict(start=1.123, end=2.789, jp="old lyric", en="old EN", vi="old VI")])
        original = json.dumps(payload, ensure_ascii=False, indent=3).encode("utf-8")
        json_path = self.manager.get_path(self.mid, "json")
        json_path.write_bytes(original)
        self.manager.render_ass_from_json(self.mid)
        ass_path = self.manager.get_path(self.mid, "ass")
        original_ass = ass_path.read_bytes()
        for _ in range(3):
            self.assertEqual(self.manager.request_subtitle(self.media).status, SubtitleStatus.READY)
            self.assertEqual(self.manager.get_raw_data(self.mid), payload)
            self.manager.get_segments_for_ui(self.mid)
        new = refined_to_subtitles(refine_lyrics([segment(1, 2, "New song.")]), "en")
        mark_final_timing(new)
        self.manager.save_segments("another-song", new)
        self.assertEqual(json_path.read_bytes(), original)
        self.assertEqual(ass_path.read_bytes(), original_ass)

    def test_missing_old_ass_renders_existing_json_times_without_realignment(self):
        payload = dict(media_id=self.mid, segments=[dict(start=4.1, end=4.2, jp="old", en="", vi="")])
        json_path = self.manager.get_path(self.mid, "json")
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        before = json_path.read_bytes()
        result = self.manager.request_subtitle(self.media)
        self.assertEqual(result.status, SubtitleStatus.READY)
        self.assertEqual(json_path.read_bytes(), before)
        self.assertIn("0:00:04.10,0:00:04.20", result.ass_path.read_text(encoding="utf-8-sig"))

    def test_manager_only_adds_marker_guard_all_other_original_logic_is_frozen(self):
        old_path = ROOT / "docs/subtitle-quality/original/subtitle_manager.py"
        baseline = json.loads((ROOT / "docs/restored-app-baseline.json").read_text(encoding="utf-8"))
        expected = next(entry["sha256"] for entry in baseline["sources"] if entry["path"] == "app/core/subtitle_manager.py")
        self.assertEqual(hashlib.sha256(old_path.read_bytes()).hexdigest(), expected)
        old, new = [ast.parse(path.read_text(encoding="utf-8-sig")) for path in
                    (old_path, ROOT / "app/core/subtitle_manager.py")]
        method = next(node for node in ast.walk(new) if isinstance(node, ast.FunctionDef) and node.name == "_clean_segment")
        block = next(node for node in ast.walk(method) if isinstance(node, ast.Try))
        guard = block.body[2]
        self.assertEqual(ast.dump(guard.test), ast.dump(ast.parse(
            'not getattr(seg, "_botube_final_timing", False)', mode="eval").body))
        block.body[2:3] = guard.body
        self.assertEqual(ast.dump(old), ast.dump(new))


class ExportTimingTests(unittest.TestCase):
    def test_rounding_preserves_milliseconds_and_carries_seconds_minutes_hours(self):
        for seconds, srt, lrc, ass in (
                (5.43, "00:00:05,430", "00:05.43", "0:00:05.43"),
                (14.35, "00:00:14,350", "00:14.35", "0:00:14.35"),
                (59.9996, "00:01:00,000", "01:00.00", "0:01:00.00"),
                (3599.9996, "01:00:00,000", "60:00.00", "1:00:00.00"),
                (-0.01, "00:00:00,000", "00:00.00", "0:00:00.00")):
            with self.subTest(seconds=seconds):
                self.assertEqual(srt_time(seconds), srt)
                self.assertEqual(lrc_time(seconds), lrc)
                self.assertEqual(ass_time(seconds), ass)

    def test_actual_export_helpers_use_shared_unit_rounding(self):
        from pipeline.lyric_formatter import format_time_srt, format_time_lrc
        from core.subtitle_renderer import ASSRenderer
        self.assertEqual(format_time_srt(59.9996), "00:01:00,000")
        self.assertEqual(format_time_lrc(59.9996), "01:00.00")
        self.assertEqual(ASSRenderer.format_time(59.9996), "0:01:00.00")

    def test_only_time_format_bodies_and_shared_import_changed(self):
        baseline = json.loads((ROOT / "docs/restored-app-baseline.json").read_text(encoding="utf-8"))
        for relative, names in (("app/pipeline/lyric_formatter.py", ("format_time_srt", "format_time_lrc")),
                                ("app/core/subtitle_renderer.py", ("format_time",))):
            old_path = ROOT / "docs/subtitle-quality/original" / Path(relative).name
            expected = next(entry["sha256"] for entry in baseline["sources"] if entry["path"] == relative)
            self.assertEqual(hashlib.sha256(old_path.read_bytes()).hexdigest(), expected)
            old, new = [ast.parse(path.read_text(encoding="utf-8-sig")) for path in (old_path, ROOT / relative)]
            new.body = [node for node in new.body if not (isinstance(node, ast.ImportFrom)
                        and node.module == "subtitle.timing_format")]
            original_functions = {node.name: node for node in ast.walk(old)
                                  if isinstance(node, ast.FunctionDef) and node.name in names}
            for node in ast.walk(new):
                if isinstance(node, ast.FunctionDef) and node.name in names:
                    self.assertEqual(ast.dump(node.args), ast.dump(original_functions[node.name].args))
                    returns = [item for item in ast.walk(node) if isinstance(item, ast.Return)]
                    self.assertEqual(len(returns), 1)
                    target = dict(format_time_srt="srt_time", format_time_lrc="lrc_time", format_time="ass_time")[node.name]
                    self.assertEqual(ast.dump(returns[0]), ast.dump(ast.parse(f"return {target}(seconds)").body[0]))
                    node.body = original_functions[node.name].body
            self.assertEqual(ast.dump(old), ast.dump(new), relative)


class LegacyAlignerCompatibilityTests(unittest.TestCase):
    def test_only_optional_short_lyric_guard_is_added_to_original_aligner(self):
        original_path = ROOT / "docs/asr-coverage/original/aligner.py"
        baseline = json.loads((ROOT / "docs/restored-app-baseline.json").read_text(encoding="utf-8"))
        expected = next(entry["sha256"] for entry in baseline["sources"] if entry["path"] == "app/pipeline/aligner.py")
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), expected)
        old, new = [ast.parse(path.read_text(encoding="utf-8-sig")) for path in
                    (original_path, ROOT / "app/pipeline/aligner.py")]
        function = next(node for node in new.body if isinstance(node, ast.FunctionDef) and node.name == "refine_segments")
        self.assertEqual(function.args.args[-1].arg, "allow_short_lyrics")
        self.assertEqual(ast.dump(function.args.defaults[-1]), ast.dump(ast.Constant(value=False)))
        function.args.args.pop()
        function.args.defaults.pop()
        conditional = next(node for node in ast.walk(function) if isinstance(node, ast.If)
            and isinstance(node.test, ast.BoolOp) and isinstance(node.test.values[0], ast.UnaryOp)
            and isinstance(node.test.values[0].operand, ast.Name)
            and node.test.values[0].operand.id == "allow_short_lyrics")
        conditional.test.values.pop(0)
        self.assertEqual(ast.dump(old), ast.dump(new))

    def test_legacy_default_outputs_match_captured_source_on_real_and_repeat_cases(self):
        namespace = {}
        source = (ROOT / "docs/asr-coverage/original/aligner.py").read_text(encoding="utf-8-sig")
        exec(compile(source, "captured-aligner", "exec"), namespace)
        cases = [[segment(1, 2, "I love you."), segment(2.1, 3, "I love you.")],
                 [segment(1, 2, "hahahahahahahahaha"), segment(3, 5, "normal lyrics")]]
        for path in (ROOT / "docs/asr-coverage/verified-strict").glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if "raw" in data:
                cases.append([segment(row["start"], row["end"], row["text"], row["words"]) for row in data["raw"]])
        for raw in cases:
            self.assertEqual(legacy_refine(raw), namespace["refine_segments"](raw))


if __name__ == "__main__":
    unittest.main()
