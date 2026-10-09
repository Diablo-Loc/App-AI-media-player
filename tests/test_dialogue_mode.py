"""Opt-in speech behavior and equivalence of the closed lyric path."""
import ast
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from pipeline.content_mode import resolve_content_mode
from pipeline.dialogue import refine_dialogue, transcription_options
from tests.dialogue_mode_contracts import before_dialogue_mode_changes


class DialogueGroupingTests(unittest.TestCase):
    def test_missing_invalid_and_legacy_setting_keep_lyrics(self):
        for value in (None, "", "auto", "lyrics", "speech", 0):
            self.assertEqual(resolve_content_mode(value), "lyrics")
        self.assertEqual(resolve_content_mode("dialogue"), "dialogue")

    def test_spoken_credit_and_repetitions_survive_without_lyric_padding(self):
        raw = [dict(start=1, end=2, text="Please subscribe.", words=[]),
               dict(start=3, end=4, text="No no no!", words=[]),
               dict(start=5, end=6, text="ご視聴ありがとうございました", words=[])]
        original = copy.deepcopy(raw)
        result = refine_dialogue(raw)
        self.assertEqual(result, [{k: c[k] for k in ("start", "end", "text")} for c in raw])
        self.assertEqual(raw, original)

    def test_sentence_pause_and_word_boundaries_keep_all_text(self):
        words = [dict(start=1, end=1.4, word=" Hello."),
                 dict(start=1.45, end=1.8, word=" Are"),
                 dict(start=1.8, end=2.1, word=" you"),
                 dict(start=2.1, end=2.5, word=" there?"),
                 dict(start=3.4, end=3.8, word=" Yes.")]
        result = refine_dialogue([dict(start=1, end=3.8,
            text="Hello. Are you there? Yes.", words=words)])
        self.assertEqual(result, [dict(start=1, end=1.4, text="Hello."),
            dict(start=1.45, end=2.5, text="Are you there?"),
            dict(start=3.4, end=3.8, text="Yes.")])

    def test_partial_invalid_or_mismatched_words_preserve_whole_segment(self):
        for words in ([dict(start=1, end=2, word="Hello")],
                      [dict(start=float("nan"), end=2, word="Hello there.")],
                      [dict(start=0, end=8, word="Hello there.")]):
            self.assertEqual(refine_dialogue([dict(start=1, end=3, text="Hello there.", words=words)]),
                             [dict(start=1, end=3, text="Hello there.")])

    def test_long_speech_splits_only_at_existing_words_and_short_cues_survive(self):
        words = [dict(start=i*.18, end=(i+1)*.18, word=" word") for i in range(80)]
        result = refine_dialogue([dict(start=0, end=14.4, text="word "*80, words=words)])
        self.assertGreater(len(result), 1)
        self.assertEqual(" ".join(c["text"] for c in result).split(), ["word"]*80)
        for a, b in zip(result, result[1:]):
            self.assertLessEqual(a["end"], b["start"])
        self.assertEqual(refine_dialogue([dict(start=0, end=.05, text="え", words=[])]),
                         [dict(start=0, end=.05, text="え")])

    def test_multilingual_dialogue_keeps_text_and_existing_pauses(self):
        for text, tokens, cjk in (("待って。ここにいて。", ["待って。", "ここにいて。"], True),
                                  ("你好。别走。", ["你好。", "别走。"], True),
                                  ("Xin chào. Đừng đi.", ["Xin chào.", " Đừng đi."], False),
                                  ("مرحبا. انتظر.", ["مرحبا.", " انتظر."], False)):
            words = [dict(start=1, end=2, word=tokens[0]),
                     dict(start=2.5, end=3, word=tokens[1])]
            result = refine_dialogue([dict(start=1, end=3, text=text, words=words)], cjk=cjk)
            self.assertEqual([(c['start'], c['end']) for c in result], [(1, 2), (2.5, 3)])
            self.assertEqual(''.join(c['text'] for c in result).replace(' ', ''), text.replace(' ', ''))


class DialoguePipelineTests(unittest.TestCase):
    def run_case(self, folder, mode=None, baseline=False, primary=None, fallback=False):
        from tests.test_asr_coverage import ProductionOrchestrationTests, segment, word
        helper = ProductionOrchestrationTests()
        path = ROOT / "app/ai/pipeline.py"
        if baseline:
            path = folder / "before.py"
            path.write_bytes(before_dialogue_mode_changes("app/ai/pipeline.py", raw=True))
        self.namespace = None
        def configure(namespace, model):
            self.namespace = namespace
            values = dict(ai_model="tiny", device="cpu", api_key="", online_provider="Local Default")
            if mode is not None:
                values["subtitle_content_mode"] = mode
            namespace["QSettings"] = lambda *args: SimpleNamespace(value=lambda key, default=None: values.get(key, default))
        if primary is None:
            primary = [segment(1, 2, "Please subscribe.", [word(1, 2, "Please subscribe.")]),
                       segment(3, 4, "A normal line.", [word(3, 4, "A normal line.")])]
        return helper.run_pipeline(path, folder / "output", primary=primary,
                                   configure=configure, fallback=fallback)

    def test_music_absent_explicit_or_invalid_matches_previous_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(exist_ok=True)
            previous, old_model, _, old_repair = self.run_case(root, baseline=True)
            for mode in (None, "lyrics", "unknown"):
                current, model, constructor, repair = self.run_case(root, mode=mode)
                rows = lambda r: [(s.start, s.end, s.top.text, s.top.lang) for s in r["segments"]]
                self.assertEqual(rows(previous), rows(current))
                self.assertEqual(model.transcribe.call_args.kwargs, old_model.transcribe.call_args.kwargs)
                self.assertEqual(repair.call_args.args[3:], old_repair.call_args.args[3:])
                self.namespace["audit_primary_intro"].assert_called_once()
                constructor.assert_called_once()
                model.transcribe.assert_called_once()

    def test_dialogue_skips_music_filters_recovery_and_extra_alignment(self):
        with tempfile.TemporaryDirectory() as tmp, patch("pipeline.lyric_timing.align_lyric_onsets",
                side_effect=AssertionError("Dialogue must not invoke lyric alignment")):
            result, model, constructor, repair = self.run_case(Path(tmp), mode="dialogue")
            self.namespace["audit_primary_intro"].assert_not_called()
            repair.assert_not_called()
            model.transcribe.assert_called_once()
            constructor.assert_called_once()
            self.assertEqual(model.transcribe.call_args.kwargs, transcription_options())
            self.assertEqual([(s.start, s.end, s.top.text) for s in result["segments"]],
                [(1, 2, "Please subscribe."), (3, 4, "A normal line.")])
            self.assertTrue(all(getattr(s, "_botube_final_timing") for s in result["segments"]))
            self.assertIn("00:00:01,000 --> 00:00:02,000",
                (Path(tmp)/"output/subtitles/source/srt/song.srt").read_text(encoding="utf-8-sig"))

    def test_dialogue_cpu_fallback_uses_same_speech_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, model, constructor, repair = self.run_case(Path(tmp), mode="dialogue", fallback=True)
            self.assertEqual(model.transcribe.call_count, 2)
            self.assertEqual(constructor.call_count, 2)
            self.assertTrue(all(call.kwargs == transcription_options() for call in model.transcribe.call_args_list))
            repair.assert_not_called()

    def test_empty_dialogue_exports_without_loading_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, model, _, repair = self.run_case(Path(tmp), mode="dialogue", primary=[])
            self.assertEqual(result, dict(media_id="same-media-id", segments=[]))
            model.transcribe.assert_called_once()
            repair.assert_not_called()


class DialogueOnlineTests(unittest.TestCase):
    def call_provider(self, mode=None, setting="lyrics", response="0===Hello.===Xin chào."):
        from translate import online_logic
        from subtitle.model import Subtitle, SubtitleLine
        sub = Subtitle(start=1, end=2)
        sub.top = SubtitleLine(text="Hello.", lang="en", style="JP")
        settings = dict(subtitle_content_mode=setting, use_genius="Bật (Chính xác cao)",
                        genius_key="test-token", translation_model="gemini-2.5-flash")
        generate = Mock(return_value=SimpleNamespace(text=response))
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        kwargs = {} if mode is None else dict(content_mode=mode)
        with patch.object(online_logic, "QSettings", return_value=SimpleNamespace(
                value=lambda key, default=None: settings.get(key, default))), \
                patch.object(online_logic, "genai", SimpleNamespace(Client=Mock(return_value=client))), \
                patch.object(online_logic, "fetch_lyric_genius", return_value=None) as genius, \
                redirect_stdout(io.StringIO()):
            result = online_logic.translate_online_pipeline([sub], "Google Gemini", "test-key",
                                                             song_title_raw="Movie.mp4", **kwargs)
        return result, generate, genius

    def test_dialogue_one_request_no_genius_and_movie_title_cannot_repair_words(self):
        for explicit, setting in (("dialogue", "lyrics"), (None, "dialogue")):
            result, generate, genius = self.call_provider(explicit, setting)
            genius.assert_not_called()
            generate.assert_called_once()
            request = generate.call_args.kwargs
            self.assertIn("hội thoại", request["config"].system_instruction)
            self.assertNotIn("BÀI HÁT", request["contents"])
            self.assertNotIn("Movie", request["contents"])
            self.assertIn("0===Hello.", request["contents"])
            self.assertEqual(request["config"].temperature, .2)
            self.assertEqual(request["config"].max_output_tokens, 16384)
            self.assertEqual((result[0].start, result[0].end, result[0].top.text), (1, 2, "Hello."))

    def test_explicit_music_snapshot_ignores_later_settings_change(self):
        from translate.lyric_translation import lyric_translation_system_prompt
        _, generate, genius = self.call_provider("lyrics", "dialogue")
        genius.assert_called_once()
        self.assertEqual(generate.call_args.kwargs["config"].system_instruction,
                         lyric_translation_system_prompt(song_title="Movie", has_reference=False))

    def test_dialogue_missing_id_repair_remains_bounded_and_atomic(self):
        from translate import online_logic
        from tests.test_lyric_translation import cue
        generate = Mock(side_effect=[SimpleNamespace(text="0===One===Một"),
                                    SimpleNamespace(text="1===Two===Hai")])
        settings = SimpleNamespace(value=lambda key, default=None: "dialogue" if key == "subtitle_content_mode" else default)
        client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
        subs = [cue("One"), cue("Two")]
        with patch.object(online_logic, "QSettings", return_value=settings), \
                patch.object(online_logic, "genai", SimpleNamespace(Client=Mock(return_value=client))), \
                redirect_stdout(io.StringIO()):
            result = online_logic.translate_online_pipeline(subs, "Google Gemini", "test")
        self.assertEqual(generate.call_count, 2)
        self.assertIn("1===Two", generate.call_args.kwargs["contents"])
        self.assertEqual([s.bottom.text for s in result], ["Một", "Hai"])


class DialogueSettingsTests(unittest.TestCase):
    def test_real_widget_load_save_reset_and_genius_restore_use_only_test_settings(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QMessageBox
        from ui.pages import settings as module
        application = QApplication.instance() or QApplication([])
        values = dict(use_genius="Bật (Chính xác cao)", genius_key="test-token")
        fake = SimpleNamespace(value=lambda key, default=None: values.get(key, default),
                               setValue=lambda key, value: values.__setitem__(key, value))
        with patch.object(module, "QSettings", return_value=fake), \
                patch.object(module, "check_resource_status", return_value={"whisper": {}}):
            page = module.SettingsPage()
            self.addCleanup(page.deleteLater)
            self.assertNotIn("subtitle_content_mode", values)
            self.assertEqual(page.combo_content_mode.currentData(), "lyrics")
            page.combo_content_mode.setCurrentIndex(1)
            self.assertFalse(page.combo_genius_mode.isEnabled())
            page.save_settings_silent()
            self.assertEqual(values["subtitle_content_mode"], "dialogue")
            self.assertEqual(values["use_genius"], "Bật (Chính xác cao)")
            page.load_settings()
            self.assertFalse(page.combo_genius_mode.isEnabled())
            page.combo_content_mode.setCurrentIndex(0)
            self.assertTrue(page.combo_genius_mode.isEnabled())
            self.assertEqual(page.genius_key_input.text(), "test-token")
            page.combo_content_mode.setCurrentIndex(1)
            with patch.object(module.QMessageBox, "question", return_value=QMessageBox.Yes), \
                    patch.object(module.QMessageBox, "information"):
                page.reset_to_defaults()
            self.assertEqual(values["subtitle_content_mode"], "lyrics")
            application.processEvents()


class DialogueSourceTests(unittest.TestCase):
    def test_exact_adapter_restores_previous_music_sources_and_rejects_unknown_changes(self):
        manifest = json.loads((ROOT / "tests/fixtures/dialogue_mode.json").read_text(encoding="utf-8"))
        for relative, entry in manifest.items():
            restored = before_dialogue_mode_changes(relative)
            self.assertEqual(hashlib.sha256(restored.encode()).hexdigest(), entry["before_sha256"])
            with self.assertRaises(AssertionError):
                before_dialogue_mode_changes(relative, current=(ROOT / relative).read_bytes()+b"\n# unknown\n")

    def test_music_specialization_is_exactly_the_previous_asr_and_online_body(self):
        class MusicPath(ast.NodeTransformer):
            def visit_If(self, node):
                if isinstance(node.test, ast.Name) and node.test.id == "dialogue":
                    return [self.visit(n) for n in node.orelse]
                if (isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not)
                        and isinstance(node.test.operand, ast.Name) and node.test.operand.id == "dialogue"):
                    return [self.visit(n) for n in node.body]
                if (isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.And)
                        and ast.dump(node.test.values[0]) == ast.dump(ast.parse("not dialogue", mode="eval").body)):
                    node.test.values.pop(0)
                return self.generic_visit(node)

            def visit_ImportFrom(self, node):
                return None if node.module == "pipeline.content_mode" else node

            def visit_Assign(self, node):
                if any(isinstance(t, ast.Name) and t.id in ("content_mode", "dialogue") for t in node.targets):
                    return None
                if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id == "intro_report" and isinstance(node.value, ast.Dict)):
                    return None
                return self.generic_visit(node)

            def visit_Call(self, node):
                if isinstance(node.func, ast.Name) and node.func.id == "translate_online_pipeline":
                    node.keywords = [k for k in node.keywords if k.arg != "content_mode"]
                return self.generic_visit(node)

            def visit_FunctionDef(self, node):
                if node.name == "translate_online_pipeline":
                    self_outer.assertEqual(node.args.args[-1].arg, "content_mode")
                    node.args.args.pop()
                    node.args.defaults.pop()
                return self.generic_visit(node)

        self_outer = self
        for relative, function in (("app/ai/pipeline.py", "run_ai_pipeline"),
                                   ("app/translate/online_logic.py", "translate_online_pipeline")):
            old = ast.parse(before_dialogue_mode_changes(relative))
            current = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
            old_function = next(n for n in old.body if isinstance(n, ast.FunctionDef) and n.name == function)
            new_function = next(n for n in current.body if isinstance(n, ast.FunctionDef) and n.name == function)
            self.assertEqual(ast.dump(MusicPath().visit(new_function)), ast.dump(old_function), relative)


if __name__ == "__main__":
    unittest.main()
