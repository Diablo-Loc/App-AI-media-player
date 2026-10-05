"""Focused contracts for concise, meaning-preserving online lyric translation."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from translate.lyric_translation import (
    build_translation_rows,
    cue_duration_seconds,
    lyric_translation_system_prompt,
    lyric_translation_user_content,
    soft_character_range,
)
from tests.lyric_translation_contracts import before_lyric_translation_changes


ROOT = Path(__file__).resolve().parents[1]


def cue(text, start=0.0, end=2.5):
    return SimpleNamespace(start=start, end=end, top=SimpleNamespace(text=text))


class LyricTranslationPolicyTests(unittest.TestCase):
    def test_duration_supports_seconds_and_editor_milliseconds(self):
        self.assertEqual(cue_duration_seconds(cue('x', 1.0, 3.4)), 2.4)
        worker = SimpleNamespace(start_ms=1250, end_ms=3750, top=SimpleNamespace(text='x'))
        self.assertEqual(cue_duration_seconds(worker), 2.5)
        invalid = SimpleNamespace(start=4.0, end=3.0, top=SimpleNamespace(text='x'))
        self.assertEqual(cue_duration_seconds(invalid), 2.5)

    def test_soft_budgets_grow_with_duration_and_remain_bounded(self):
        en_short = soft_character_range(1.0, 'en')
        en_long = soft_character_range(4.0, 'en')
        vi_short = soft_character_range(1.0, 'vi')
        vi_long = soft_character_range(4.0, 'vi')
        self.assertLess(en_short[1], en_long[1])
        self.assertLess(vi_short[1], vi_long[1])
        self.assertLess(en_short[0], en_short[1])
        self.assertLess(vi_short[0], vi_short[1])
        self.assertLessEqual(en_long[1], 64)
        self.assertLessEqual(vi_long[1], 68)

    def test_jsonl_rows_keep_ids_unicode_and_skip_empty_cues(self):
        rows = build_translation_rows([
            cue('君の声が聞こえる', 0.0, 2.0),
            cue('   ', 2.0, 3.0),
            cue('Stay   with\nme', 3.0, 6.0),
        ]).splitlines()
        self.assertEqual(len(rows), 2)
        first, second = map(json.loads, rows)
        self.assertEqual(first['id'], 0)
        self.assertEqual(first['source'], '君の声が聞こえる')
        self.assertEqual(second['id'], 2)
        self.assertEqual(second['source'], 'Stay with me')
        self.assertIn('-', first['en_preferred_chars'])
        self.assertIn('-', first['vi_preferred_chars'])

    def test_prompt_requires_semantic_fidelity_without_hard_truncation(self):
        prompt = lyric_translation_system_prompt('Synthetic Song', has_reference=True)
        for phrase in (
            'Keep the original meaning',
            'negation',
            'meaningful repetition',
            'soft readability targets',
            'not a compression target',
            'modest poetic turn is welcome',
            'Do not translate word-for-word',
            'Naturally short source lines may stay shorter',
            'do not collapse the translation into keyword fragments, telegram-style wording',
            'ID===English translation===Vietnamese translation',
        ):
            self.assertIn(phrase, prompt)

    def test_request_contains_reference_context_and_per_cue_budget(self):
        content = lyric_translation_user_content(
            [cue('星を探して', 0.0, 1.6)],
            song_title='Synthetic Song',
            reference_lyric='星を探して',
        )
        self.assertIn('SONG: Synthetic Song', content)
        self.assertIn('REFERENCE LYRICS:', content)
        payload = json.loads(content.split('CUES (JSONL; preferred character ranges are soft targets):\n', 1)[1])
        self.assertEqual(payload['id'], 0)
        self.assertEqual(payload['source'], '星を探して')
        self.assertGreater(payload['duration_s'], 0)


class LyricTranslationSourceContractTests(unittest.TestCase):
    def test_exact_adapter_restores_pre_phase_online_logic(self):
        relative = 'app/translate/online_logic.py'
        restored = before_lyric_translation_changes(relative, raw=True)
        original = (ROOT / 'docs/lyric-translation/original' / relative).read_bytes()
        self.assertEqual(restored, original)


if __name__ == '__main__':
    unittest.main()
