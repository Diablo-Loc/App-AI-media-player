"""Tail-only behavior: sustained notes, rapid transitions, Unicode and EOF."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline.lyric_refinement import finalize_display_times, refine_lyrics
from tests.subtitle_display_tail_contracts import before_display_tail_changes
from tools.benchmark_lyric_tails import evaluate


def previous_display(cues, **kwargs):
    source = before_display_tail_changes("app/pipeline/lyric_refinement.py")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "finalize_display_times")
    namespace = dict(finalize_display_times.__globals__)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<previous-tail>", "exec"), namespace)
    return namespace["finalize_display_times"](cues, **kwargs)


class TailTests(unittest.TestCase):
    def test_exact_new_adapter_preserves_frozen_preceding_sources(self):
        manifest = json.loads((ROOT / "tests/fixtures/subtitle_display_tail.json").read_text(encoding="utf-8"))
        for relative, entry in manifest.items():
            restored = before_display_tail_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(restored.replace(b"\r\n", b"\n")).hexdigest(),
                             entry["before_sha256"])
            modified = (ROOT / relative).read_bytes() + b"\n# unreviewed\n"
            with self.assertRaises(AssertionError):
                before_display_tail_changes(relative, current=modified)

    def test_only_post_word_hold_is_reduced_never_one_third_of_sung_duration(self):
        for text in ("君の声", "Đừng rời xa", "Stay with me", "لا ترحل"):
            raw = [dict(start=1, end=20, text=text, words=[dict(start=1, end=20, word=text)])]
            acoustic = refine_lyrics(raw)
            original = copy.deepcopy(acoustic)
            for cjk, tail in ((True, .37), (False, .7)):
                old = previous_display(acoustic, cjk=cjk)
                new = finalize_display_times(acoustic, cjk=cjk)
                self.assertEqual(new[0]["start"], old[0]["start"])
                self.assertGreaterEqual(new[0]["end"], 20)
                self.assertAlmostEqual(new[0]["end"] - 20, tail - .1, delta=.001)
                self.assertAlmostEqual(old[0]["end"] - new[0]["end"], .1, delta=.001)
                self.assertEqual(new[0]["text"], text)
            self.assertEqual(acoustic, original)

    def test_fast_adjacent_cues_keep_the_same_transitions_and_no_blank_gap(self):
        cues = [dict(start=round(i * .22, 3), end=round((i + 1) * .22, 3),
                     text=str(i) + " go") for i in range(30)]
        for cjk in (False, True):
            old, new = previous_display(cues, cjk=cjk), finalize_display_times(cues, cjk=cjk)
            self.assertEqual([c["start"] for c in new], [c["start"] for c in old])
            self.assertEqual(new[:-1], old[:-1])
            self.assertTrue(all(a["end"] == b["start"] for a, b in zip(new, new[1:])))

    def test_real_pause_and_short_adlibs_keep_all_text_and_eof_bounds(self):
        cues = [dict(start=0, end=.02, text="Ah"), dict(start=.025, end=.045, text="Oh"),
                dict(start=5, end=10, text="Hold this note"), dict(start=19.99, end=20, text="Yeah")]
        for cjk in (False, True):
            old = previous_display(cues, cjk=cjk, duration=20)
            new = finalize_display_times(cues, cjk=cjk, duration=20)
            self.assertEqual([c["text"] for c in new], [c["text"] for c in old])
            self.assertEqual([c["start"] for c in new], [c["start"] for c in old])
            self.assertEqual(new[-1]["end"], 20)
            self.assertTrue(all(0 <= c["start"] < c["end"] <= 20 for c in new))
            self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(new, new[1:])))
            self.assertGreaterEqual(new[2]["end"], 10)
            self.assertLess(new[2]["end"], old[2]["end"])


class BenchmarkProtocolTests(unittest.TestCase):
    def test_ordered_refrains_match_each_performance_and_report_unmatched_words(self):
        gold = [dict(start=1, end=2, text="stay"), dict(start=2, end=3, text="here"),
                dict(start=5, end=6, text="stay"), dict(start=6, end=7, text="here")]
        cues = [dict(start=1, end=3.5, text="Stay here"),
                dict(start=4, end=4.5, text="fooblax"),
                dict(start=5, end=7.5, text="Stay here")]
        metrics = evaluate(cues, gold)
        self.assertEqual(metrics["matched_cues"], 2)
        self.assertEqual(metrics["matched_words"], 4)
        self.assertEqual(metrics["reference_word_recall"], 1)
        self.assertEqual(metrics["onset_mae_s"], 0)
        self.assertEqual(metrics["end_mae_s"], .5)
        self.assertEqual(metrics["late_ends"], 2)
        self.assertEqual(metrics["cue_count"], 3)

    def test_apostrophes_accents_and_no_matches_do_not_fake_perfect_timing(self):
        gold = [dict(start=0, end=.5, text="je"), dict(start=.5, end=1, text="m'en"),
                dict(start=1, end=1.5, text="vais")]
        metrics = evaluate([dict(start=0, end=1.6, text="Je m’en vais")], gold)
        self.assertEqual(metrics["matched_words"], 3)
        missing = evaluate([dict(start=0, end=1.6, text="fooblax")], gold)
        self.assertEqual(missing["reference_word_recall"], 0)
        self.assertIsNone(missing["end_mae_s"])


if __name__ == "__main__":
    unittest.main()
