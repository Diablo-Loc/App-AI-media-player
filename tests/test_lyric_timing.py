"""Safety and lifecycle checks for the local onset-only alignment stage."""
import copy
from contextlib import nullcontext
import json
import statistics
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline import lyric_timing as timing
from pipeline.lyric_refinement import finalize_display_times


def cue(start=1, end=4, text="Stay with me."):
    return dict(start=start, end=end, text=text)


def word(start=1.45, end=4, text="Stay with me.", probability=.95):
    return dict(start=start, end=end, word=text, probability=probability)


class OnsetTests(unittest.TestCase):
    def test_recorded_reference_improves_timing_without_losing_or_resegmenting_lyrics(self):
        data = json.loads((ROOT / "tests/fixtures/lyric_onset_reference.json").read_text(encoding="utf-8"))
        cues = data["cues"]
        frozen = copy.deepcopy(cues)
        candidates = {int(index): words for index, words in data["candidates"].items()}
        output, changed = timing.apply_onsets(cues, candidates, data["duration"])
        before = finalize_display_times(cues, cjk=True, duration=data["duration"])
        after = finalize_display_times(output, cjk=True, duration=data["duration"])
        ref = data["reference"]

        def error(rows, edge):
            return statistics.mean(abs(rows[a[0 if edge == "start" else -1]][edge]
                - ref[b[0 if edge == "start" else -1]][edge]) for a, b in data["pairs"])

        self.assertGreater(len(changed), 0)
        self.assertLess(error(after, "start"), error(before, "start") * .75)
        self.assertLess(error(after, "end"), error(before, "end"))
        self.assertEqual(cues, frozen)
        self.assertEqual([row["text"] for row in after], [row["text"] for row in before])
        self.assertTrue(all(a["end"] <= b["start"] for a, b in zip(after, after[1:])))
        self.assertTrue(all(a["start"] >= b["start"] for a, b in zip(after, before)))

    def test_full_confident_cue_delays_onset_without_changing_text_or_tail(self):
        original = [cue(), cue(4, 7, "Don't leave.")]
        frozen = copy.deepcopy(original)
        output, changed = timing.apply_onsets(original, {
            0: [word()], 1: [word(4.6, 7, "Don't leave.")]})
        self.assertEqual(changed, [0, 1])
        self.assertEqual([row["text"] for row in output], [row["text"] for row in original])
        self.assertEqual(output[0]["start"], 1.4)
        self.assertEqual(output[0]["end"], output[1]["start"])
        self.assertEqual(output[1]["end"], 7)
        self.assertEqual(original, frozen)

    def test_existing_real_gap_stays_and_effects_receive_final_shared_timeline(self):
        original = [cue(), cue(8, 12, "A new line.")]
        output, changed = timing.apply_onsets(original, {1: [word(8.5, 12, "A new line.")]})
        self.assertEqual(output[0], original[0])
        self.assertEqual(changed, [1])
        display = finalize_display_times(output, cjk=True)
        self.assertEqual(display[1]["start"], 8.6)
        self.assertLess(display[0]["end"], 5)

    def test_incomplete_foreign_low_confidence_and_nonfinite_candidates_keep_old_times(self):
        cases = [[word(text="Stay.")], [word(text="Another line.")],
                 [word(probability=.49)], [word(probability=float("nan"))],
                 [word(start=float("inf"))], [word(end=1)],
                 [word(2, 3, "Stay "), word(1.5, 4, "with me.")],
                 [word(1.45, 2, "Stay "), word(2, 4, "with me.", .01)]]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                original = [cue()]
                self.assertEqual(timing.apply_onsets(original, {0: candidate}), (original, []))

    def test_no_advancing_outlier_jump_short_cue_or_truncated_tail(self):
        for candidate in (word(start=.5), word(start=2.5), word(end=2)):
            self.assertEqual(timing.apply_onsets([cue()], {0: [candidate]}), ([cue()], []))
        tiny = cue(1, 1.18)
        self.assertEqual(timing.apply_onsets([tiny], {0: [word(1.15, 1.18)]}), ([tiny], []))

    def test_whitespace_tokens_do_not_supply_a_false_start_or_confidence(self):
        output, changed = timing.apply_onsets([cue()], {
            0: [word(0, 1.45, " ", 0), word()]})
        self.assertEqual(changed, [0])
        self.assertEqual(output[0]["start"], 1.4)

    def test_languages_repetitions_and_cues_across_thirty_seconds_remain_intact(self):
        for text in ("君の声", "魚龍引玄鳥", "Stay, stay, stay.", "Đừng rời xa.", "لا ترحل"):
            original = [cue(29, 34, text), cue(35, 40, text)]
            result, changed = timing.apply_onsets(original, {
                0: [word(29.4, 34, text)], 1: [word(35.5, 40, text)]})
            self.assertEqual(changed, [0, 1])
            self.assertEqual([r["text"] for r in result], [text, text])
            self.assertGreater(result[0]["end"], 30)


class Tokenizer:
    def encode(self, text):
        return [ord(c) for c in text]


class WindowTests(unittest.TestCase):
    def test_audio_token_limits_long_indivisible_cue_and_instrumental_break(self):
        cues = [cue(1, 4), cue(4, 7), cue(20, 24), cue(24, 55),
                cue(57, 60, "x" * 421), cue(65, 69), cue(90, 94)]
        windows = list(timing._windows(cues, Tokenizer(), 95))
        accepted = [i for _, _, indices, _, _ in windows for i in indices]
        self.assertEqual(accepted, [0, 1, 2, 5, 6])
        self.assertEqual(windows[0][2], [0, 1])
        self.assertTrue(all(right - left <= 29.5 and len(tokens) <= 420
                            for left, right, _, tokens, _ in windows))

    def test_pcm_reader_loads_only_requested_samples_with_exact_normalization(self):
        import tempfile
        import wave
        import numpy as np
        samples = np.arange(32000, dtype=np.int16)
        seen = []

        class Features:
            sampling_rate = 16000
            hop_length = 160
            nb_max_frames = 3000

            def __call__(self, clip):
                seen.append(clip)
                return np.zeros((80, 1), dtype=np.float32)

        module = ModuleType("faster_whisper.transcribe")
        module.pad_or_trim = lambda data, size: data
        alignment = [dict(word="...", tokens=[1], start=0, end=.1, probability=.1),
                     dict(word=" ", tokens=[2], start=.1, end=.1, probability=0),
                     dict(word="Stay", tokens=[3], start=.1, end=.4, probability=.95)]
        model = SimpleNamespace(feature_extractor=Features(), encode=lambda data: data,
                                find_alignment=Mock(return_value=alignment))
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "probe.wav")
            with wave.open(path, "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(16000)
                writer.writeframes(samples.tobytes())
            with wave.open(path, "rb") as reader, patch.dict(sys.modules, {
                    "faster_whisper.transcribe": module}):
                result = timing._align_window(model, Tokenizer(), reader, .75, 1.25,
                                              [1, 2, 3], [(2, 3)])
                self.assertEqual(reader.tell(), 20000)
            self.assertEqual(len(seen[0]), 8000)
            np.testing.assert_array_equal(seen[0], samples[12000:20000].astype(np.float32) / 32768.0)
            self.assertEqual(result[0][0]["word"], "Stay")
            self.assertEqual(result[0][0]["start"], .85)
            self.assertEqual(model.find_alignment.call_args.args[-1], 50)
            self.assertTrue(reader._file is None)


class LifecycleTests(unittest.TestCase):
    def setup_mocks(self):
        tokenizer = ModuleType("faster_whisper.tokenizer")
        tokenizer.Tokenizer = Mock(return_value=Tokenizer())
        reader = SimpleNamespace(getnframes=lambda: 10000, getframerate=lambda: 100,
            getnchannels=lambda: 1, getsampwidth=lambda: 2, getcomptype=lambda: "NONE")
        self.wav_open = Mock(return_value=nullcontext(reader))
        self.model = SimpleNamespace(hf_tokenizer=object(), model=SimpleNamespace(is_multilingual=True),
                                     feature_extractor=SimpleNamespace(sampling_rate=100))
        self.context = patch.dict(sys.modules, {"faster_whisper.tokenizer": tokenizer})
        self.context.start()
        self.addCleanup(self.context.stop)
        self.wav_context = patch.object(timing.wave, "open", self.wav_open)
        self.wav_context.start()
        self.addCleanup(self.wav_context.stop)

    def setUp(self):
        self.setup_mocks()

    def test_no_cues_do_not_decode_and_budget_cap_keeps_original(self):
        result, report = timing.align_lyric_onsets(self.model, "never-opened.wav", "en", [])
        self.assertEqual(result, [])
        self.wav_open.assert_not_called()
        with patch.object(timing, "_align_window") as align:
            result, report = timing.align_lyric_onsets(self.model, "probe.wav", "en", [cue()], budget_s=0)
        align.assert_not_called()
        self.assertTrue(report["capped"])
        self.assertEqual(result, [cue()])

    def test_model_error_does_not_loop_or_drop_text(self):
        cues = [cue(), cue(20, 24)]
        with patch.object(timing, "_align_window", side_effect=RuntimeError("CUDA out of memory")) as align:
            result, report = timing.align_lyric_onsets(self.model, "probe.wav", "en", cues)
        self.assertEqual(align.call_count, 1)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(result, cues)

    def test_budget_is_checked_between_windows_and_preserves_remaining_cues(self):
        cues = [cue(), cue(20, 24)]
        with patch.object(timing.time, "monotonic", side_effect=[0, 0, 16, 17]), \
                patch.object(timing, "_align_window", return_value=[[word()]]) as align:
            result, report = timing.align_lyric_onsets(self.model, "probe.wav", "en", cues)
        self.assertEqual(align.call_count, 1)
        self.assertTrue(report["capped"])
        self.assertEqual(result[0]["start"], 1.4)
        self.assertEqual(result[1], cues[1])

    def test_cancellation_before_decode_and_during_alignment_is_propagated(self):
        with self.assertRaisesRegex(RuntimeError, "Cancelled"):
            timing.align_lyric_onsets(self.model, "probe.wav", "en", [cue()], cancel_cb=lambda: True)
        self.wav_open.assert_not_called()
        state = {"cancel": False}

        def cancel(*args):
            state["cancel"] = True
            return [[word()]]

        with patch.object(timing, "_align_window", side_effect=cancel):
            with self.assertRaisesRegex(RuntimeError, "Cancelled"):
                timing.align_lyric_onsets(self.model, "probe.wav", "en", [cue()],
                                           cancel_cb=lambda: state["cancel"])

    def test_isolated_failed_import_or_audio_keeps_original(self):
        self.wav_open.side_effect = OSError("unavailable")
        result, report = timing.align_lyric_onsets(self.model, "probe.wav", "ja", [cue()])
        self.assertEqual(result, [cue()])
        self.assertEqual(report["errors"], 1)

    def test_success_does_not_transcribe_read_srt_or_translate(self):
        with patch.object(timing, "_align_window", return_value=[[word()]]):
            result, report = timing.align_lyric_onsets(self.model, "only-audio.wav", "en", [cue()])
        self.assertEqual(report["changed"], 1)
        self.assertEqual(result[0]["start"], 1.4)
        self.wav_open.assert_called_once_with("only-audio.wav", "rb")


if __name__ == "__main__":
    unittest.main()
