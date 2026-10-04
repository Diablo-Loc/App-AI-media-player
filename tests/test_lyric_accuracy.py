"""Lightweight accuracy contracts; no added model retry or saved-cue migration."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from pipeline.lyric_accuracy import credit_text, primary_options
from pipeline.lyric_refinement import refine_lyrics
from tests.lyric_accuracy_contracts import before_accuracy_changes


class LyricsTests(unittest.TestCase):
    def test_ordinary_lyric_vocabulary_is_not_credit_substrings(self):
        for text in ('Eye of the tiger.', 'This is fiction.', 'Keep your copyright.',
                     'I saw you on Instagram', '音楽が好きだ', '歌詞を忘れた', 'Music', 'I love you.'):
            with self.subTest(text=text):
                raw = dict(start=1, end=3, text=text, words=[dict(start=1, end=3, word=text)])
                self.assertEqual(refine_lyrics([raw])[0]['text'], text)

    def test_explicit_credit_is_rejected_with_or_without_word_times(self):
        for text in ('Thanks for watching', 'Subtitles by Amara.org', '作詞: Someone',
                     '作詞・作曲・編曲 初音ミク', 'ご視聴ありがとうございました',
                     '시청해주셔서 감사합니다', 'Please subscribe', 'Music: Someone'):
            for timed in (True, False):
                with self.subTest(text=text, timed=timed):
                    self.assertTrue(credit_text(text, timed_words=timed))
        self.assertTrue(credit_text('I love you.'))
        self.assertFalse(credit_text('I love you.', timed_words=True))

    def test_unicode_credit_normalization_and_empty_text(self):
        self.assertTrue(credit_text('ＳＵＢＴＩＴＬＥＳ\nＢＹ Somebody', True))
        self.assertEqual(refine_lyrics([dict(start=1, end=2, text=' ', words=[])]), [])

    def test_captured_brand_credits_stay_rejected_but_generic_social_lyrics_survive(self):
        for text in ('🐯 Sound Hod ori 사 운드 호돌 이 サウンドゥホドリ',
                     'Inst agram & Twitter ホドリ', 'SoundHodori', '사운드호돌이'):
            self.assertTrue(credit_text(text, timed_words=True), text)
        for text in ('I saw you on Instagram', 'Find me on Instagram and Twitter', 'Eye of the tiger.'):
            self.assertFalse(credit_text(text, timed_words=True), text)

    def test_two_three_four_repeated_performances_are_kept(self):
        text = 'The sign is lightening up'
        for count in (2, 3, 4):
            for gap in (0, .02, .2):
                rows = [dict(start=80.99 + i * (2.19 + gap), end=83.18 + i * (2.19 + gap),
                    text=text, words=[dict(start=81.04 + i * (2.19 + gap),
                    end=83.18 + i * (2.19 + gap), word=text)]) for i in range(count)]
                before = copy.deepcopy(rows)
                result = refine_lyrics(rows)
                self.assertEqual([c['text'] for c in result], [text] * count)
                self.assertTrue(all(a['end'] <= b['start'] for a, b in zip(result, result[1:])))
                self.assertEqual(rows, before)

    def test_sustained_note_keeps_available_end_without_filling_silence(self):
        source = [dict(start=1, end=13, text='Hold this note', words=[
            dict(start=1, end=2, word='Hold'), dict(start=2, end=3, word='this'),
            dict(start=3, end=13, word='note')]),
            dict(start=17, end=19, text='Next phrase', words=[dict(start=17, end=19, word='Next phrase')])]
        result = refine_lyrics(source)
        self.assertEqual(result[0]['text'], 'Hold this note')
        self.assertEqual(result[0]['end'], 13.08)
        self.assertEqual(result[1]['start'], 16.95)


class AccuracyScopeTests(unittest.TestCase):
    def test_only_two_production_adapters_and_lightweight_helper_change(self):
        inventory = json.loads((ROOT / 'docs/lyric-accuracy/app-before-normalized.json').read_text())
        for relative, digest in inventory.items():
            data = before_accuracy_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest(), digest, relative)
        hashes = json.loads((ROOT / 'docs/lyric-accuracy/helper-hash.json').read_text())
        self.assertEqual(set(hashes), {'app/pipeline/lyric_accuracy.py'})
        for relative, digest in hashes.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)

    def test_primary_coverage_and_rest_of_orchestration_preserved(self):
        relative = 'app/ai/pipeline.py'
        before = before_accuracy_changes(relative)
        after = (ROOT / relative).read_text(encoding='utf-8')
        primary = next(n for n in ast.walk(ast.parse(after)) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == 'transcribe'
            and any(k.arg == 'beam_size' for k in n.keywords))
        namespace = dict(model=Mock(), temp_wav_path='wave', prompt_text=' .+')
        eval(compile(ast.Expression(primary), relative, 'eval'), namespace)
        self.assertEqual(namespace['model'].transcribe.call_args.kwargs, primary_options())
        edits = [
            ('model = WhisperModel("medium", device="cpu", compute_type="int8")',
             'model = WhisperModel(fallback_model_path if os.path.isfile(os.path.join(fallback_model_path, "model.bin"))\n'
             '                                     else "medium", device="cpu", compute_type="int8")'),
            ('                segments_generator, fallback_info = model.transcribe(str(temp_wav_path), word_timestamps=True)',
             '                from pipeline.lyric_accuracy import primary_options\n'
             '                segments_generator, fallback_info = model.transcribe(str(temp_wav_path), **primary_options())')]
        expected = before
        for old, new in edits:
            self.assertEqual(expected.count(old), 1)
            expected = expected.replace(old, new, 1)
        self.assertEqual(after, expected)
        helper = ast.parse((ROOT / 'app/pipeline/lyric_accuracy.py').read_bytes())
        imports = {n.names[0].name for n in helper.body if isinstance(n, ast.Import)}
        self.assertEqual(imports, {'re', 'unicodedata'})
        self.assertEqual({n.name for n in helper.body if isinstance(n, ast.FunctionDef)},
                         {'primary_options', 'credit_text'})
