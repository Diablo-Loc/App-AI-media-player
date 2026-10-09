"""Missing speech recovery contracts; no model/network/GPU needed for discovery."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import gc
import io
import os
import re
import time
from typing import Callable, Dict, Optional
from contextlib import redirect_stdout
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline.asr_coverage import (missing_ranges, plan_windows, merge_recovered,
                                  repair_missing_subtitles, _candidate_cues,
                                  _verified_recovery_evidence,
                                  _needs_recovery_verification,
                                  _compatible_replacement_text,
                                  _replacement_from_retry,
                                  _apply_text_replacement)

REFINE = dict(max_chars=74, min_pause=0.6, start_offset=0, end_padding=0.6,
              gap_threshold=0.6, memory_reset_t=3.0)


def word(start, end, text, probability=0.9):
    return SimpleNamespace(start=start, end=end, word=text, probability=probability)


def segment(start, end, text, words=None, logprob=-0.2):
    return SimpleNamespace(start=start, end=end, text=text, words=words or [], avg_logprob=logprob)


class CoverageRulesTests(unittest.TestCase):
    def test_gaps_include_intro_middle_tail_without_rewriting_cues(self):
        cues = [dict(start=30, end=40, text="verse"), dict(start=60, end=65, text="chorus")]
        original = json.loads(json.dumps(cues))
        self.assertEqual(missing_ranges(cues, 75), [(0, 30), (40, 60), (65, 75)])
        self.assertEqual(cues, original)
        self.assertEqual(missing_ranges([], 20), [(0, 20)])
        self.assertEqual(
            missing_ranges(
                [dict(start=0, end=1.0, text="a"), dict(start=1.4, end=2.0, text="b")],
                2.0,
                min_gap=0.22,
            ),
            [(1.0, 1.4)],
        )

    def test_windows_are_bounded_and_only_retry_uncovered_speech(self):
        windows = plan_windows([(0, 30), (40, 60)], [(5, 14)], 60)
        self.assertEqual(windows, [(0, 12), (10, 22)])
        self.assertTrue(all(end - start <= 12 for start, end in windows))
        self.assertEqual(plan_windows([(0, 30)], [], 30), [])

    def test_original_cues_always_win_and_repeated_chorus_is_kept(self):
        existing = [dict(start=30, end=35, text="same chorus")]
        candidates = [dict(start=5, end=8, text="same chorus"),
                      dict(start=30, end=35, text="wrong replacement"),
                      dict(start=5, end=7, text="truncated"),
                      dict(start=40, end=43, text="same chorus")]
        result = merge_recovered(existing, candidates)
        self.assertEqual([cue["text"] for cue in result], ["same chorus"] * 3)
        self.assertIs(result[1], existing[0])
        self.assertEqual(existing, [dict(start=30, end=35, text="same chorus")])

    def test_credit_low_confidence_and_padded_tail_are_not_added(self):
        decoded = [segment(0, 2, "subtitles by", [word(0, 2, "subtitles by")]),
                   segment(3, 5, "uncertain", [word(3, 5, "uncertain", 0.1)]),
                   segment(6, 8, "low logprob", [word(6, 8, "wrong")], -2),
                   segment(14, 18, "outside clip", [word(14, 18, "outside clip")])]
        self.assertEqual(_candidate_cues(decoded, 0, 12, [(0, 30)], [(0, 30)], REFINE, 30), [])

    def test_zero_duration_cjk_word_and_global_offsets_are_preserved(self):
        decoded = [segment(1, 3, "世界中", [word(1, 2, "世"), word(2, 2, "界"), word(2, 3, "中")])]
        cues = _candidate_cues(decoded, 10, 22, [(0, 30)], [(10, 15)], REFINE, 30)
        self.assertEqual(cues, [dict(start=11, end=13.6, text="世界中")])

    def test_end_padding_is_clipped_only_for_new_boundary_cue(self):
        decoded = [segment(0, 2, "last words", [word(0, 2, "last words")])]
        result = _candidate_cues(decoded, 28, 30, [(0, 30.2)], [(28, 30)], REFINE, 60)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["end"], 30.08)
        result = _candidate_cues(decoded, 28, 30, [(0, 30)], [(28, 30)], REFINE, 30)
        self.assertEqual(result[0]["end"], 30)

    def test_silence_thanks_and_nonlexical_hallucinations_are_not_added(self):
        decoded = [segment(1, 2, "Thank you", [word(1, 2, "Thank you")]),
                   segment(3, 4, "you for watching.", [word(3, 4, "you for watching.")]),
                   segment(5, 7, "Oh, oh, oh, oh", [word(5, 7, "Oh, oh, oh, oh")])]
        self.assertEqual(_candidate_cues(decoded, 0, 12, [(0, 30)], [(0, 30)], REFINE, 30), [])
        existing = [dict(start=0, end=3, text="Thank you"), dict(start=10, end=12, text="La la la")]
        self.assertEqual(merge_recovered(existing, []), existing)

    def test_video_boilerplate_from_gap_retry_is_not_added(self):
        for text in ("We'll be right back.", "We'll see you next time."):
            decoded = [segment(1, 3, text, [word(1, 3, text)])]
            self.assertEqual(_candidate_cues(decoded, 0, 12, [(0, 30)], [(0, 30)], REFINE, 30), [])

    def test_weak_text_repair_restores_only_clear_truncation(self):
        self.assertTrue(_compatible_replacement_text("不寂寥", "世间原来不寂寥"))
        self.assertTrue(_compatible_replacement_text("phrase tail", "missing phrase tail"))
        self.assertFalse(_compatible_replacement_text("玉龙银玄鸟", "魚龍引玄鳥"))
        self.assertFalse(_compatible_replacement_text("correct lyric", "different lyric"))


    def test_weak_retry_can_restore_timing_across_thirty_second_boundary(self):
        primary = dict(start=30.2, end=34.0, text="phrase tail",
                       word_probability=0.40, avg_logprob=-0.96)
        decoded = [segment(3.0, 8.0, "missing phrase tail", [
            word(3.0, 5.0, "missing phrase", 0.91),
            word(5.0, 8.0, "tail", 0.92),
        ], -0.22)]
        replacement = _replacement_from_retry(decoded, 26.0, 38.0, primary, REFINE)
        self.assertIsNotNone(replacement)

        cues = [
            dict(start=25.0, end=28.8, text="previous"),
            dict(start=30.2, end=34.0, text="phrase tail"),
            dict(start=34.8, end=38.0, text="next"),
        ]
        result, changed = _apply_text_replacement(
            cues, primary, replacement, speech=[(29.0, 34.0)]
        )
        self.assertTrue(changed)
        self.assertEqual(result[1]["text"], "missing phrase tail")
        self.assertEqual((result[1]["start"], result[1]["end"]), (29.0, 34.0))

    def test_timing_extension_is_clamped_to_neighbour_and_requires_voice(self):
        primary = dict(start=29.9, end=30.8, text="phrase tail",
                       word_probability=0.40, avg_logprob=-0.96)
        replacement = dict(start=27.7, end=31.4, text="missing phrase tail",
                           _evidence_start=27.7, _evidence_end=30.8)
        cues = [
            dict(start=25.0, end=27.84, text="previous"),
            dict(start=29.9, end=30.8, text="phrase tail"),
            dict(start=31.5, end=34.0, text="next"),
        ]
        unchanged, changed = _apply_text_replacement(cues, primary, replacement, speech=[])
        self.assertFalse(changed)
        self.assertEqual(unchanged, cues)

        result, changed = _apply_text_replacement(
            cues, primary, replacement, speech=[(27.7, 30.8)]
        )
        self.assertTrue(changed)
        self.assertEqual(result[1]["start"], 27.84)
        self.assertEqual(result[1]["end"], 30.8)


class CoverageOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="botube-coverage-")
        self.path = Path(self.directory.name) / "audio.wav"
        with wave.open(str(self.path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\0\0" * 45 * 16000)
        audio = ModuleType("faster_whisper.audio")
        audio.decode_audio = Mock(return_value=range(45 * 16000))
        vad = ModuleType("faster_whisper.vad")
        vad.get_speech_timestamps = Mock(return_value=[dict(start=5 * 16000, end=9 * 16000)])
        self.decode = audio.decode_audio
        self.vad = vad.get_speech_timestamps
        self.modules = patch.dict(sys.modules, {"faster_whisper.audio": audio, "faster_whisper.vad": vad})
        self.modules.start()

    def tearDown(self):
        self.modules.stop()
        self.directory.cleanup()

    def test_complete_primary_pass_does_no_extra_audio_decode_or_asr(self):
        cues = [dict(start=0, end=45, text="complete")]
        model = Mock()
        result, report = repair_missing_subtitles(model, self.path, "en", cues, REFINE)
        self.assertIs(result, cues)
        self.assertEqual(report["added_cues"], 0)
        self.decode.assert_not_called()
        self.vad.assert_not_called()
        model.transcribe.assert_not_called()

    def test_confident_primary_text_is_never_locally_rewritten(self):
        cues = [
            dict(start=0, end=24, text="lead"),
            dict(start=24, end=28, text="complete phrase"),
            dict(start=28, end=45, text="tail"),
        ]
        primary = [
            segment(0, 24, "lead", [word(0, 24, "lead", 0.92)], -0.2),
            segment(24, 28, "complete phrase", [word(24, 28, "complete phrase", 0.91)], -0.2),
            segment(28, 45, "tail", [word(28, 45, "tail", 0.93)], -0.2),
        ]
        model = Mock()

        result, report = repair_missing_subtitles(
            model, self.path, "en", cues, REFINE, primary_segments=primary
        )

        self.assertIs(result, cues)
        self.assertEqual(report["replaced_cues"], 0)
        self.decode.assert_not_called()
        self.vad.assert_not_called()
        model.transcribe.assert_not_called()

    def test_weak_primary_can_gain_missing_prefix_without_moving_cue(self):
        self.vad.return_value = [dict(start=24 * 16000, end=28 * 16000)]
        cues = [
            dict(start=0, end=24, text="lead"),
            dict(start=24, end=28, text="phrase tail"),
            dict(start=28, end=45, text="tail"),
        ]
        primary = [
            segment(0, 24, "lead", [word(0, 24, "lead", 0.92)], -0.2),
            segment(24, 28, "phrase tail", [word(24, 28, "phrase tail", 0.40)], -0.96),
            segment(28, 45, "tail", [word(28, 45, "tail", 0.93)], -0.2),
        ]
        model = Mock()
        model.transcribe.return_value = (
            iter([segment(1.35, 5.35, "missing phrase tail", [
                word(1.35, 5.35, "missing phrase tail", 0.91)
            ], -0.22)]),
            SimpleNamespace(language="en"),
        )

        result, report = repair_missing_subtitles(
            model, self.path, "en", cues, REFINE, primary_segments=primary
        )

        self.assertEqual(result[1]["text"], "missing phrase tail")
        self.assertEqual((result[1]["start"], result[1]["end"]), (24, 28))
        self.assertEqual(report["replaced_cues"], 1)
        self.assertEqual(report["added_cues"], 0)

    def test_weak_primary_rejects_unrelated_stronger_local_text(self):
        self.vad.return_value = [dict(start=24 * 16000, end=28 * 16000)]
        cues = [
            dict(start=0, end=24, text="lead"),
            dict(start=24, end=28, text="phrase tail"),
            dict(start=28, end=45, text="tail"),
        ]
        primary = [
            segment(0, 24, "lead", [word(0, 24, "lead", 0.92)], -0.2),
            segment(24, 28, "phrase tail", [word(24, 28, "phrase tail", 0.40)], -0.96),
            segment(28, 45, "tail", [word(28, 45, "tail", 0.93)], -0.2),
        ]
        model = Mock()
        model.transcribe.return_value = (
            iter([segment(1.35, 5.35, "unrelated local words", [
                word(1.35, 5.35, "unrelated local words", 0.94)
            ], -0.18)]),
            SimpleNamespace(language="en"),
        )

        result, report = repair_missing_subtitles(
            model, self.path, "en", cues, REFINE, primary_segments=primary
        )

        self.assertEqual(result, cues)
        self.assertEqual(report["replaced_cues"], 0)

    def test_instrumental_intro_does_not_force_a_fake_subtitle(self):
        self.vad.return_value = []
        cues = [dict(start=30, end=45, text="verse")]
        model = Mock()
        result, report = repair_missing_subtitles(model, self.path, "en", cues, REFINE)
        self.assertEqual(result, cues)
        model.transcribe.assert_not_called()
        self.assertEqual(report["unresolved_speech"], [])

    def test_missing_intro_uses_same_model_and_keeps_primary_timing(self):
        cues = [dict(start=30, end=45, text="existing verse")]
        model = Mock()
        model.transcribe.return_value = ([segment(5, 8, "recovered opening",
            [word(5, 8, "recovered opening")])], SimpleNamespace(language="en"))
        result, report = repair_missing_subtitles(model, self.path, "en", cues, REFINE)
        self.assertEqual(result[0], dict(start=5, end=8.6, text="recovered opening"))
        self.assertIs(result[-1], cues[0])
        self.assertEqual(report["added_cues"], 1)
        for call in model.transcribe.call_args_list:
            self.assertLessEqual(len(call.args[0]), 12 * 16000)
            self.assertEqual(call.kwargs["language"], "en")
            self.assertIsNone(call.kwargs["initial_prompt"])
            self.assertFalse(call.kwargs["vad_filter"])
        self.assertIsNone(model.transcribe.call_args_list[0].kwargs["no_speech_threshold"])
        self.assertEqual(model.transcribe.call_args_list[1].kwargs["no_speech_threshold"], 0.60)
        self.assertEqual(model.transcribe.call_args_list[1].kwargs["log_prob_threshold"], -1.0)
        self.assertEqual(model.transcribe.call_args_list[1].kwargs["hallucination_silence_threshold"], 1.0)

    def test_unstable_gap_decode_is_not_injected_into_subtitles(self):
        cues = [dict(start=30, end=45, text="existing verse")]
        model = Mock()
        model.transcribe.side_effect = [
            ([segment(5, 8, "invented opening", [word(5, 8, "invented opening")])],
             SimpleNamespace(language="en")),
            ([segment(5, 8, "different retry", [word(5, 8, "different retry")])],
             SimpleNamespace(language="en")),
        ]
        result, report = repair_missing_subtitles(model, self.path, "en", cues, REFINE)
        self.assertEqual(result, cues)
        self.assertEqual(report["added_cues"], 0)
        self.assertGreaterEqual(report["attempts"][0]["proposed"], 1)
        self.assertEqual(report["attempts"][0]["confirmed"], 0)

    def test_recovery_verifier_uses_strict_silence_guards(self):
        model = Mock()
        model.transcribe.return_value = (iter(()), SimpleNamespace())
        evidence = _verified_recovery_evidence(model, range(8 * 16000), 10.0, "ja")
        self.assertEqual(evidence, [])
        kwargs = model.transcribe.call_args.kwargs
        self.assertEqual(kwargs["beam_size"], 3)
        self.assertEqual(kwargs["no_speech_threshold"], 0.60)
        self.assertEqual(kwargs["log_prob_threshold"], -1.0)
        self.assertEqual(kwargs["hallucination_silence_threshold"], 1.0)
        self.assertIsNone(kwargs["initial_prompt"])

    def test_opening_recovery_verifier_keeps_primary_recovery_beam_quality(self):
        """Regression: an edge lyric must not disappear only because verifier used beam=1."""
        model = Mock()

        def transcribe(_clip, **kwargs):
            recovered = segment(5.48, 8.86, "real opening lyric", [
                word(5.48, 6.04, "real", probability=0.42),
                word(6.04, 8.86, " opening lyric", probability=0.90),
            ])
            recovered.avg_logprob = -0.39
            recovered.no_speech_prob = 0.45
            if kwargs.get("no_speech_threshold") is None:
                return iter([recovered]), SimpleNamespace(language="en")
            if kwargs.get("beam_size") == 3:
                return iter([recovered]), SimpleNamespace(language="en")
            return iter(()), SimpleNamespace(language="en")

        model.transcribe.side_effect = transcribe
        cues = [dict(start=30, end=45, text="existing verse")]
        result, report = repair_missing_subtitles(model, self.path, "en", cues, REFINE)
        self.assertTrue(any(item["text"] == "real opening lyric" for item in result))
        self.assertGreaterEqual(report["added_cues"], 1)

    def test_overlapping_retry_can_replace_truncated_recovery_with_complete_phrase(self):
        """A provisional crop edge must not split a later complete local decode."""
        self.vad.return_value = [
            dict(start=5 * 16000, end=int(14.5 * 16000)),
        ]
        cues = [dict(start=30, end=45, text="existing verse")]
        model = Mock()
        first = [
            segment(5.0, 8.0, "opening lyric", [word(5.0, 8.0, "opening lyric")]),
            segment(10.6, 11.9, "truncated phrase", [
                word(10.6, 11.9, "truncated phrase"),
            ]),
        ]
        complete = [
            segment(0.0, 4.1, "complete phrase continues", [
                word(0.0, 4.1, "complete phrase continues"),
            ]),
        ]
        model.transcribe.side_effect = [
            (iter(first), SimpleNamespace(language="en")),
            (iter(first), SimpleNamespace(language="en")),
            (iter(complete), SimpleNamespace(language="en")),
            (iter(complete), SimpleNamespace(language="en")),
        ]

        result, report = repair_missing_subtitles(model, self.path, "en", cues, REFINE)

        texts = [item["text"] for item in result]
        self.assertIn("opening lyric", texts)
        self.assertIn("complete phrase continues", texts)
        self.assertNotIn("truncated phrase", texts)
        self.assertIs(result[-1], cues[0])
        self.assertEqual(report["added_cues"], 2)

    def test_strong_middle_speech_does_not_pay_for_extra_verification(self):
        cue = dict(start=20.0, end=23.0, text="clear middle lyric")
        self.assertFalse(_needs_recovery_verification(
            cue, [(15.0, 25.0)], [(19.5, 23.5)], 60.0
        ))
        self.assertTrue(_needs_recovery_verification(
            cue, [(0.0, 25.0)], [(19.5, 23.5)], 60.0
        ))
        self.assertTrue(_needs_recovery_verification(
            cue, [(15.0, 60.0)], [(19.5, 23.5)], 60.0
        ))
        self.assertTrue(_needs_recovery_verification(
            dict(start=20.0, end=20.7, text="short missing lyric"),
            [(19.8, 21.0)], [(19.8, 21.0)], 60.0
        ))

    def test_empty_primary_pass_can_recover_real_speech(self):
        model = Mock()
        model.transcribe.return_value = ([segment(5, 8, "real speech",
            [word(5, 8, "real speech")])], SimpleNamespace(language="en"))
        result, report = repair_missing_subtitles(model, self.path, "en", [], REFINE)
        self.assertEqual(result[0]["text"], "real speech")
        self.assertEqual(report["added_cues"], 1)

    def test_decoder_failure_does_not_erase_primary_cues(self):
        cues = [dict(start=30, end=45, text="existing verse")]
        model = Mock()
        model.transcribe.side_effect = RuntimeError("decoder failed")
        result, report = repair_missing_subtitles(model, self.path, "en", cues, REFINE)
        self.assertEqual(result, cues)
        self.assertIn("decoder failed", report["error"])
        self.assertTrue(report["unresolved_speech"])

    def test_cancel_before_decode_and_during_generator_is_propagated(self):
        model = Mock()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            repair_missing_subtitles(model, self.path, "en", [], REFINE, cancel_cb=lambda: True)
        self.decode.assert_not_called()
        state = {"cancelled": False}
        def generator():
            state["cancelled"] = True
            yield segment(5, 8, "cancel", [word(5, 8, "cancel")])
        model.transcribe.return_value = (generator(), SimpleNamespace(language="en"))
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            repair_missing_subtitles(model, self.path, "en", [], REFINE,
                                     cancel_cb=lambda: state["cancelled"])


class PipelineContractTests(unittest.TestCase):
    def test_only_main_pipeline_body_and_coverage_import_are_changed(self):
        original_path = ROOT / "docs/asr-coverage/original/pipeline.py"
        snapshot = json.loads((ROOT / "docs/restored-app-baseline.json").read_text(encoding="utf-8"))
        original_hash = next(entry["sha256"] for entry in snapshot["sources"]
                             if entry["path"] == "app/ai/pipeline.py")
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), original_hash)
        old = ast.parse(original_path.read_text(encoding="utf-8-sig"))
        from tests.asr_intro_guard_contracts import before_asr_intro_guard_changes
        current = ast.parse(before_asr_intro_guard_changes("app/ai/pipeline.py"))
        current.body = [node for node in current.body if not (isinstance(node, ast.ImportFrom)
                        and node.module == "pipeline.asr_coverage")]
        modern_import = next(node for node in current.body if isinstance(node, ast.ImportFrom)
                             and node.module == "pipeline.lyric_refinement")
        self.assertEqual([name.name for name in modern_import.names],
                         ["refine_lyrics", "finalize_cue_times", "mark_final_timing"])
        current.body[current.body.index(modern_import)] = ast.parse(
            "from pipeline.aligner import refine_segments").body[0]
        previous_main = next(node for node in old.body if isinstance(node, ast.FunctionDef)
                             and node.name == "run_ai_pipeline")
        current_main = next(node for node in current.body if isinstance(node, ast.FunctionDef)
                            and node.name == "run_ai_pipeline")
        self.assertEqual(ast.dump(current_main.args), ast.dump(previous_main.args))
        current_main.body = previous_main.body
        self.assertEqual(ast.dump(current), ast.dump(old))

    def test_primary_whisper_and_refine_options_are_exactly_original(self):
        from tests.lyric_accuracy_contracts import before_accuracy_changes
        trees = [ast.parse((ROOT / "docs/asr-coverage/original/pipeline.py").read_text(encoding="utf-8-sig")),
                 ast.parse(before_accuracy_changes('app/ai/pipeline.py'))]
        for name in ("transcribe", "refine_segments"):
            calls = []
            for tree in trees:
                tree = copy.deepcopy(tree)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id == "refine_lyrics":
                        node.id = "refine_segments"
                calls.append([ast.dump(node) for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and ((isinstance(node.func, ast.Attribute) and node.func.attr == name)
                         or (isinstance(node.func, ast.Name) and node.func.id == name))])
            self.assertEqual(calls[0], calls[1], name)

    def test_original_flow_survives_removing_only_coverage_adapter(self):
        paths = (ROOT / "docs/asr-coverage/original/pipeline.py", ROOT / "app/ai/pipeline.py")
        from tests.empty_subtitle_contracts import before_empty_changes
        sources = [paths[0].read_text(encoding="utf-8-sig"), before_empty_changes("app/ai/pipeline.py")]
        old, current = [next(node for node in ast.parse(source).body
                            if isinstance(node, ast.FunctionDef) and node.name == "run_ai_pipeline")
                        for source in sources]
        for node in ast.walk(current):
            if isinstance(node, ast.Name) and node.id == "refine_lyrics":
                node.id = "refine_segments"
        original_try = next(node for node in old.body if isinstance(node, ast.Try))
        current_try = next(node for node in current.body if isinstance(node, ast.Try))
        cleanup_index = next(i for i, node in enumerate(original_try.body) if isinstance(node, ast.Delete))
        cleanup = original_try.body[cleanup_index:cleanup_index + 3]
        adapter_index = next(i for i, node in enumerate(current_try.body) if isinstance(node, ast.Assign)
                             and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "coverage")
        adapter = current_try.body[adapter_index + 1]
        self.assertIsInstance(adapter, ast.Try)
        self.assertEqual([ast.dump(node) for node in adapter.finalbody],
                         [ast.dump(node) for node in cleanup])
        call = next(node for node in ast.walk(adapter) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "repair_missing_subtitles")
        refine = next(node for node in ast.walk(old) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == "refine_segments")
        self.assertEqual([ast.dump(keyword) for keyword in call.args[4].keywords],
                         [ast.dump(keyword) for keyword in refine.keywords])
        self.assertEqual([ast.dump(keyword) for keyword in call.keywords[-4:]],
                         [ast.dump(keyword) for keyword in ast.parse(
            "repair(refine_fn=refine_segments, boundary_gap=0.0, boundary_tolerance=0.08, primary_segments=segments_list)").body[0].value.keywords])
        finalization = current_try.body[adapter_index + 2]
        self.assertEqual(ast.dump(finalization), ast.dump(ast.parse(
            'final_segments = finalize_cue_times(final_segments, duration=coverage.get("duration"))').body[0]))
        self.assertEqual(ast.dump(current_try.body[adapter_index + 3]),
                         ast.dump(ast.parse("_check_cancel(cancel_cb)").body[0]))
        guard = current_try.body[adapter_index + 4]
        self.assertEqual(ast.dump(guard.test), ast.dump(ast.parse("not final_segments", mode="eval").body))
        # The adapter owns the model through its final pass, then uses the exact
        # original cleanup. Restore that earlier location for a full AST diff.
        del current_try.body[adapter_index:adapter_index + 5]
        marker_index = next(i for i, node in enumerate(current_try.body) if isinstance(node, ast.Expr)
                            and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                            and node.value.func.id == "mark_final_timing")
        self.assertEqual(ast.dump(current_try.body[marker_index]),
                         ast.dump(ast.parse("mark_final_timing(subs)").body[0]))
        del current_try.body[marker_index]
        for node in ast.walk(current_try):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple):
                target = node.targets[0]
                if len(target.elts) == 2 and isinstance(target.elts[1], ast.Name) and target.elts[1].id == "fallback_info":
                    target.elts[1].id = "_"
            for field in ("body", "orelse", "finalbody"):
                statements = getattr(node, field, None)
                if isinstance(statements, list):
                    statements[:] = [statement for statement in statements if not (
                        isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Attribute)
                        and isinstance(statement.value.value, ast.Name)
                        and statement.value.value.id == "fallback_info")]
        transcribe_index = next(i for i, node in enumerate(current_try.body) if isinstance(node, ast.Try)
            and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "transcribe" for call in ast.walk(node)))
        current_try.body[transcribe_index + 1:transcribe_index + 1] = copy.deepcopy(cleanup)
        raw_index = next(i for i, node in enumerate(current_try.body) if isinstance(node, ast.For)
                        and isinstance(node.iter, ast.Name) and node.iter.id == "segments_list")
        original_guard = next(node for node in original_try.body if isinstance(node, ast.If)
                             and isinstance(node.test, ast.UnaryOp) and isinstance(node.test.operand, ast.Name)
                             and node.test.operand.id == "raw_segments")
        current_try.body.insert(raw_index + 1, copy.deepcopy(original_guard))
        self.assertEqual(ast.dump(current), ast.dump(old))


class ProductionOrchestrationTests(unittest.TestCase):
    def run_pipeline(self, path, output, primary=None, recovery=None, fallback=False, configure=None, cancel_cb=None):
        from pipeline.aligner import refine_segments
        from pipeline.lyric_refinement import refine_lyrics, finalize_cue_times, mark_final_timing
        from pipeline.jp_normalizer import universal_text_reconstruct
        from pipeline.lyric_formatter import export_srt, export_lrc
        from subtitle.converter import refined_to_subtitles
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
        model = Mock()
        info = SimpleNamespace(language="en", language_probability=0.99)
        if primary is None:
            primary = [segment(1, 4, "A complete original line", [word(1, 4, "A complete original line")])]
        if fallback:
            model.transcribe.side_effect = [RuntimeError("cuda error"),
                (iter(primary), SimpleNamespace(language="vi", language_probability=0.9))]
        else:
            model.transcribe.return_value = (iter(primary), info)
        whisper = ModuleType("faster_whisper")
        whisper.WhisperModel = Mock(return_value=model)
        torch = ModuleType("torch")
        torch.cuda = SimpleNamespace(is_available=lambda: False, empty_cache=Mock())
        translation = ModuleType("translate.pipeline")
        translation.TranslateMode = SimpleNamespace(PIVOT_VI="probe")
        translation.translate_pipeline = Mock(side_effect=lambda subs, **kwargs: subs)
        translation.clear_translator = Mock()
        online = ModuleType("translate.online_logic")
        online.translate_online_pipeline = Mock(side_effect=AssertionError("No network"))
        renderer = ModuleType("subtitle.ass.renderer")
        renderer.render_ass = Mock()
        settings = SimpleNamespace(value=lambda key, default=None: dict(
            ai_model="tiny", device="cpu", api_key="", online_provider="Local Default").get(key, default))
        manager = SimpleNamespace(create_unique_path=Mock(return_value=output / "audio.wav"),
                                  safe_delete=Mock())
        repair = Mock(side_effect=lambda model, audio, language, cues, options, **kwargs:
            (recovery if recovery is not None else cues, dict(added_cues=len(recovery or []), attempts=[], unresolved_speech=[])))
        intro_audit = Mock(side_effect=lambda model, audio, segments, language, probability, **kwargs:
            (segments, language, {}))
        namespace = dict(Path=Path, os=os, sys=sys, gc=gc, time=SimpleNamespace(sleep=Mock()), re=re,
            Callable=Callable, Dict=Dict, Optional=Optional, __file__=str(ROOT / "app/ai/pipeline.py"),
            QSettings=lambda *args: settings, TempFileManager=manager,
            extract_audio=Mock(return_value=True), refine_segments=refine_segments,
            refine_lyrics=refine_lyrics, finalize_cue_times=finalize_cue_times, mark_final_timing=mark_final_timing,
            universal_text_reconstruct=universal_text_reconstruct, LANG_CONFIG=dict(cjk=["ja", "zh", "ko"]),
            export_srt=export_srt, export_lrc=export_lrc, refined_to_subtitles=refined_to_subtitles,
            repair_missing_subtitles=repair, audit_primary_intro=intro_audit,
            is_connected=Mock(return_value=False))
        self.pipeline_translation = translation
        self.pipeline_online = online
        self.pipeline_progress = []
        if configure is not None:
            configure(namespace, model)
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
        namespace["fix_nvidia_dlls"] = Mock()
        with patch.dict(sys.modules, {"torch": torch, "faster_whisper": whisper,
            "lyricsgenius": ModuleType("lyricsgenius"), "translate.pipeline": translation,
            "translate.online_logic": online, "subtitle.ass.renderer": renderer}), \
                redirect_stdout(io.StringIO()), patch.dict(os.environ):
            result = namespace["run_ai_pipeline"]("song.mp4", str(output), "same-media-id",
                progress_cb=lambda percent, message: self.pipeline_progress.append((percent, message)), cancel_cb=cancel_cb)
        manager.safe_delete.assert_called_once_with(output / "audio.wav")
        online.translate_online_pipeline.assert_not_called()
        return result, model, whisper.WhisperModel, repair

    def test_pipeline_only_changes_intended_timing_retains_exports_schema_and_load_count(self):
        with tempfile.TemporaryDirectory(prefix="botube-pipeline-") as temp:
            root = Path(temp)
            old, old_model, old_constructor, _ = self.run_pipeline(
                ROOT / "docs/asr-coverage/original/pipeline.py", root / "old")
            new, new_model, new_constructor, repair = self.run_pipeline(
                ROOT / "app/ai/pipeline.py", root / "new")
            def rows(result):
                return [(sub.start, sub.end, sub.top.text, sub.top.lang, sub.middle.text)
                        for sub in result["segments"]]
            self.assertEqual(rows(old)[0][2:], rows(new)[0][2:])
            self.assertEqual(rows(old)[0][:2], (1, 4.6))
            self.assertEqual(rows(new)[0][:2], (1.0, 4.7))
            self.assertTrue(getattr(new["segments"][0], "_botube_final_timing"))
            self.assertEqual(old.keys(), new.keys())
            for suffix in ("srt", "lrc"):
                relative = Path("subtitles/source") / suffix / f"song.{suffix}"
                from pipeline.lyric_formatter import export_srt, export_lrc
                expected = root / f"expected.{suffix}"
                writer = export_srt if suffix == "srt" else export_lrc
                writer([dict(start=1.0, end=4.7, text="A complete original line")], expected)
                self.assertEqual(expected.read_bytes(), (root / "new" / relative).read_bytes())
            old_constructor.assert_called_once()
            new_constructor.assert_called_once()
            old_model.transcribe.assert_called_once()
            new_model.transcribe.assert_called_once()
            self.assertEqual(old_model.transcribe.call_args.kwargs, new_model.transcribe.call_args.kwargs)
            self.assertIs(repair.call_args.args[0], new_model)
            from pipeline.lyric_refinement import refine_lyrics
            self.assertIs(repair.call_args.kwargs["refine_fn"], refine_lyrics)

    def test_empty_asr_recovery_reaches_export_and_old_result_schema(self):
        with tempfile.TemporaryDirectory(prefix="botube-empty-asr-") as temp:
            result, _, _, repair = self.run_pipeline(ROOT / "app/ai/pipeline.py", Path(temp),
                primary=[], recovery=[dict(start=5, end=8, text="Recovered real speech")])
            self.assertEqual(set(result), {"media_id", "segments"})
            self.assertEqual(result["segments"][0].top.text, "Recovered real speech")
            self.assertEqual(repair.call_args.args[3], [])

    def test_cpu_fallback_uses_returned_language_before_preprocessing(self):
        with tempfile.TemporaryDirectory(prefix="botube-fallback-") as temp:
            result, model, constructor, repair = self.run_pipeline(ROOT / "app/ai/pipeline.py",
                                                                    Path(temp), fallback=True)
            self.assertEqual(constructor.call_count, 2)
            self.assertEqual(model.transcribe.call_count, 2)
            self.assertEqual(repair.call_args.args[2], "vi")
            self.assertEqual(result["segments"][0].top.lang, "vi")


if __name__ == "__main__":
    unittest.main()
