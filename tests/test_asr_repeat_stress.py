"""Stress contracts for long ASR filler loops versus distinct timed refrains."""
from collections import Counter
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline.lyric_refinement import refine_lyrics


def texts(cues):
    return " ".join(cue["text"] for cue in cues)


class RepeatStressTests(unittest.TestCase):
    def test_30_and_100_fused_or_stalled_fillers_do_not_expand_into_huge_subtitles(self):
        for count in (30, 100):
            with self.subTest(count=count):
                fused = dict(start=1, end=3, text="ha" * count,
                             words=[dict(start=1, end=3, word="ha" * count)])
                self.assertEqual(texts(refine_lyrics([fused])), "hahaha")
                stalled = dict(start=1, end=3, text=" ".join(["ha"] * count),
                    words=[dict(start=1, end=3, word="ha") for _ in range(count)])
                self.assertEqual(texts(refine_lyrics([stalled])), "ha ha ha")

    def test_two_or_three_close_repeated_lyric_lines_keep_every_performance(self):
        for count in (2, 3):
            for gap in (0.0, 0.02, 0.1):
                with self.subTest(count=count, gap=gap):
                    rows = [dict(start=1 + i * (1 + gap), end=2 + i * (1 + gap),
                        text="I love you.", words=[dict(start=1 + i * (1 + gap),
                        end=2 + i * (1 + gap), word="I love you.")]) for i in range(count)]
                    cues = refine_lyrics(rows)
                    self.assertEqual([cue["text"] for cue in cues], ["I love you."] * count)
                    self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(cues, cues[1:])))

    def test_two_or_three_syllables_are_not_capped_even_when_asr_word_times_stall(self):
        for count in (2, 3):
            row = dict(start=1, end=3, text=" ".join(["ha"] * count),
                       words=[dict(start=1, end=3, word="ha") for _ in range(count)])
            self.assertEqual(texts(refine_lyrics([row])).split(), ["ha"] * count)

    def test_progressing_word_times_are_not_evidence_of_hallucination_even_for_100_repetitions(self):
        # It could be a long chant OR invented ASR timing. Without audio evidence
        # the cleanup must not blindly cap it solely because there are many words.
        for token in ("ha", "love"):
            count = 100
            row = dict(start=1, end=21, text=" ".join([token] * count),
                words=[dict(start=1 + i * 0.2, end=1.2 + i * 0.2, word=token) for i in range(count)])
            self.assertEqual(Counter(texts(refine_lyrics([row])).split()), Counter({token: count}))


if __name__ == "__main__":
    unittest.main()
