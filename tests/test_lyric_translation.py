"""Focused contracts for concise, meaning-preserving online lyric translation."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from translate.lyric_translation import (
    build_translation_rows,
    cue_duration_seconds,
    lyric_translation_system_prompt,
    lyric_translation_user_content,
    partition_translation_batches,
    soft_character_range,
)
from translate import online_logic
from tests.lyric_translation_contracts import before_lyric_translation_changes
from tests.lyric_translation_stability_contracts import before_lyric_translation_stability_changes
from tests.gemini_default_compat_contracts import before_gemini_default_compat_changes
from tests.lyric_prompt_engineering_contracts import before_lyric_prompt_engineering_changes
from tests.lyric_long_translation_contracts import before_lyric_long_translation_changes
from tests.api_request_pacing_contracts import before_api_request_pacing_changes
from tests.lyric_clause_completeness_contracts import before_lyric_clause_completeness_changes
from tests.translation_reference_binding_contracts import before_translation_reference_binding_changes
from tests.online_translation_authority_contracts import before_online_translation_authority_changes
from tests.translation_semantic_review_contracts import before_translation_semantic_review_changes
from tests.translation_single_pass_contracts import before_translation_single_pass_changes


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

    def test_verified_reference_is_bound_inside_its_exact_global_cue_row(self):
        rows = build_translation_rows(
            [cue('全て繋げてく残りの足')],
            cue_ids=[47],
            verified_references={47: '全て繋げてく残りの糸', 48: 'foreign cue'},
        ).splitlines()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0])
        self.assertEqual(payload['id'], 47)
        self.assertEqual(payload['source'], '全て繋げてく残りの足')
        self.assertEqual(payload['verified_reference'], '全て繋げてく残りの糸')
        self.assertNotIn('foreign cue', rows[0])

    def test_prompt_requires_semantic_fidelity_without_hard_truncation(self):
        prompt = lyric_translation_system_prompt('Synthetic Song', has_reference=True)
        for phrase in (
            'reading the whole batch as song context',
            'Preserve every meaningful source part',
            'extra wording in repeated refrains',
            'negation',
            'meaningful repetition',
            'exceed the range whenever shortening would lose meaning',
            'Keep naturally short lines, ad-libs and vocalizations short',
            'ID===English translation===Vietnamese translation',
        ):
            self.assertIn(phrase, prompt)

        self.assertNotIn('silently check', prompt)

    def test_online_model_may_repair_asr_with_or_without_genius_but_may_not_drop_fragments(self):
        no_reference = lyric_translation_system_prompt('Synthetic Song', has_reference=False)
        self.assertIn('full supplied song context', no_reference)
        self.assertIn('Song metadata only: Synthetic Song', no_reference)
        self.assertIn('Never insert title or artist wording into a cue', no_reference)
        self.assertIn('Preserve every meaningful source part', no_reference)
        self.assertIn('extra wording in repeated refrains', no_reference)

        with_reference = lyric_translation_system_prompt('Synthetic Song', has_reference=True)
        self.assertIn('verified_reference', with_reference)
        self.assertIn('strong evidence for correcting obvious recognition errors', with_reference)
        self.assertIn('reading the whole batch as song context', with_reference)

    def test_successful_normal_online_translation_is_single_pass(self):
        rows = [
            SimpleNamespace(start=0.0, end=2.0, top=SimpleNamespace(text='全て繋げてく'), middle=None, bottom=None),
            SimpleNamespace(start=2.0, end=5.0, top=SimpleNamespace(text='全て繋げてく残りの足'), middle=None, bottom=None),
        ]
        settings = Mock()
        settings.value.side_effect = lambda key, default=None: default
        request = Mock()
        first = Mock()
        first.json.return_value = {
            'choices': [{'message': {'content': (
                '0===Connecting everything===Kết nối tất cả\n'
                '1===Connecting everything with the remaining steps===Kết nối tất cả cùng những bước chân còn lại'
            )}}]
        }
        request.post.return_value = first
        with patch.object(online_logic, 'QSettings', return_value=settings), \
                patch.object(online_logic, 'requests', request), \
                patch.object(online_logic.time, 'sleep'):
            result = online_logic.translate_online_pipeline(
                rows, 'OpenAI (GPT-4o)', 'synthetic-key', 'Synthetic Song'
            )
        self.assertIs(result, rows)
        self.assertEqual(request.post.call_count, 1)
        self.assertEqual(rows[0].middle.text, 'Connecting everything')
        self.assertEqual(rows[1].middle.text, 'Connecting everything with the remaining steps')
        self.assertEqual(rows[1].bottom.text, 'Kết nối tất cả cùng những bước chân còn lại')

    def test_prompt_preserves_semantic_risk_markers(self):
        prompt = lyric_translation_system_prompt()
        for phrase in (
            'negation',
            'relationship',
            'name',
            'number',
            'meaningful repetition',
        ):
            self.assertIn(phrase, prompt)

    def test_online_provider_sampling_is_low_variance(self):
        source = (ROOT / 'app/translate/online_logic.py').read_text(encoding='utf-8-sig')
        self.assertEqual(source.count('temperature=0.2'), 1)
        self.assertEqual(source.count('"temperature": 0.2'), 2)
        self.assertNotIn('temperature=0.3', source)
        self.assertNotIn('"temperature": 0.3', source)

    def test_gemini_has_explicit_output_budget(self):
        source = (ROOT / 'app/translate/online_logic.py').read_text(encoding='utf-8-sig')
        self.assertIn('max_output_tokens=16384', source)

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

    def test_request_embeds_verified_reference_in_same_cue_json_not_loose_block(self):
        content = lyric_translation_user_content(
            [cue('Machine recognized tail', 0.0, 2.0)],
            song_title='Synthetic Song',
            cue_ids=[12],
            verified_references={12: 'Verified corrected tail'},
        )
        self.assertNotIn('VERIFIED CUE REFERENCES', content)
        payload = json.loads(content.split(
            'CUES (JSONL; preferred character ranges are soft targets):\n', 1
        )[1])
        self.assertEqual(payload['id'], 12)
        self.assertEqual(payload['source'], 'Machine recognized tail')
        self.assertEqual(payload['verified_reference'], 'Verified corrected tail')

    def test_long_lyrics_batch_by_count_and_source_size_keep_global_ids(self):
        rows = [cue(f'Line {i}', i, i + 2) for i in range(121)]
        batches = partition_translation_batches(rows)
        self.assertEqual([len(batch) for batch in batches], [60, 60, 1])
        self.assertEqual(batches[0][0][0], 0)
        self.assertEqual(batches[1][0][0], 60)
        self.assertEqual(batches[2][0][0], 120)

        huge = [cue('x' * 7000), cue('y' * 7000), cue('z')]
        size_batches = partition_translation_batches(huge)
        self.assertEqual([[idx for idx, _ in batch] for batch in size_batches], [[0], [1, 2]])

    def test_batched_content_keeps_global_ids_and_boundary_context_outside_jsonl(self):
        content = lyric_translation_user_content(
            [cue('Current line')],
            song_title='Synthetic Song',
            cue_ids=[60],
            context_before='Previous line',
            context_after='Next line',
        )
        self.assertIn('PREVIOUS CONTEXT ONLY (do not translate/output): Previous line', content)
        self.assertIn('NEXT CONTEXT ONLY (do not translate/output): Next line', content)
        payload = json.loads(content.split('CUES (JSONL; preferred character ranges are soft targets):\n', 1)[1])
        self.assertEqual(payload['id'], 60)

    def _run_long_online(self, row_count, fail_calls=None):
        rows = [
            SimpleNamespace(
                start=float(i), end=float(i + 1),
                top=SimpleNamespace(text=f'Line {i}'), middle=None, bottom=None,
            )
            for i in range(row_count)
        ]
        settings = Mock()
        settings.value.side_effect = lambda key, default=None: default
        request = Mock()

        call_number = 0
        def post(_url, json=None, **_kwargs):
            nonlocal call_number
            call_number += 1
            content = json['messages'][1]['content']
            payload_text = content.split('CUES (JSONL; preferred character ranges are soft targets):\n', 1)[1]
            batch_rows = [json_module.loads(line) for line in payload_text.splitlines() if line.strip()]
            if call_number in set(fail_calls or ()):
                batch_rows = batch_rows[:-1]
            translated = '\n'.join(
                f"{row['id']}===EN {row['id']}===VI {row['id']}" for row in batch_rows
            )
            response = Mock()
            response.json.return_value = {'choices': [{'message': {'content': translated}}]}
            return response

        json_module = json
        request.post.side_effect = post
        with patch.object(online_logic, 'QSettings', return_value=settings), \
                patch.object(online_logic, 'requests', request), \
                patch.object(online_logic.time, 'sleep'):
            result = online_logic.translate_online_pipeline(
                rows, 'OpenAI (GPT-4o)', 'synthetic-key', 'Synthetic Song'
            )
        return rows, result, request.post.call_count

    def test_extremely_long_online_translation_batches_and_merges_atomically(self):
        rows, result, calls = self._run_long_online(121)
        self.assertIs(result, rows)
        self.assertEqual(calls, 3)
        self.assertEqual(rows[0].bottom.text, 'VI 0')
        self.assertEqual(rows[60].bottom.text, 'VI 60')
        self.assertEqual(rows[120].bottom.text, 'VI 120')

    def test_incomplete_online_batch_repairs_only_missing_ids_with_same_provider(self):
        rows, result, calls = self._run_long_online(121, fail_calls={2})
        self.assertIs(result, rows)
        self.assertEqual(calls, 4)
        self.assertEqual(rows[119].bottom.text, 'VI 119')
        self.assertEqual(rows[120].bottom.text, 'VI 120')

    def test_failed_online_repair_keeps_entire_song_unmodified_for_fallback(self):
        rows, result, calls = self._run_long_online(121, fail_calls={2, 3})
        self.assertIsNone(result)
        self.assertEqual(calls, 3)
        self.assertTrue(all(row.middle is None and row.bottom is None for row in rows))

    def test_transient_sdk_503_retries_once_with_backoff(self):
        class Temporary503(RuntimeError):
            status_code = 503

        call = Mock(side_effect=[Temporary503('unavailable'), 'ok'])
        with patch.object(online_logic.time, 'sleep') as sleep:
            self.assertEqual(online_logic._call_provider_once_with_retry(call, 'Gemini'), 'ok')
        self.assertEqual(call.call_count, 2)
        sleep.assert_called_once_with(online_logic._TRANSIENT_RETRY_DELAY_S)

    def test_nontransient_sdk_error_is_not_retried(self):
        class BadRequest(RuntimeError):
            status_code = 400

        call = Mock(side_effect=BadRequest('bad request'))
        with patch.object(online_logic.time, 'sleep') as sleep:
            with self.assertRaises(BadRequest):
                online_logic._call_provider_once_with_retry(call, 'Gemini')
        self.assertEqual(call.call_count, 1)
        sleep.assert_not_called()

    def test_http_503_respects_short_retry_after_and_retries_once(self):
        first = Mock(status_code=503, headers={'Retry-After': '0.7'})
        second = Mock(status_code=200, headers={})
        post = Mock(side_effect=[first, second])
        with patch.object(online_logic.requests, 'post', post), \
                patch.object(online_logic.time, 'sleep') as sleep:
            result = online_logic._post_provider_once_with_retry(
                'https://example.invalid', label='OpenAI', json={'x': 1}, timeout=1
            )
        self.assertIs(result, second)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.7)

    def test_request_pacing_is_bounded_and_genius_does_not_gain_retries(self):
        source = (ROOT / 'app/translate/online_logic.py').read_text(encoding='utf-8-sig')
        self.assertIn('_GENIUS_MIN_INTERVAL_S = 0.40', source)
        self.assertIn('_TRANSLATION_BATCH_DELAY_S = 0.65', source)
        self.assertIn('_TRANSIENT_RETRY_DELAY_S = 1.35', source)
        self.assertIn('paced_genius_call(lambda: genius.search_songs', source)
        self.assertIn('paced_genius_call(lambda: genius.lyrics', source)
        self.assertIn('referents = paced_genius_call(', source)


class LyricTranslationSourceContractTests(unittest.TestCase):
    def test_single_pass_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_translation_single_pass_changes(relative, raw=True)
            original = (
                ROOT / 'docs/translation-single-pass/original' / relative
            ).read_bytes()
            self.assertEqual(restored, original)

    def test_semantic_review_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_translation_semantic_review_changes(relative, raw=True)
            original = (
                ROOT / 'docs/translation-semantic-review/original' / relative
            ).read_bytes()
            self.assertEqual(restored, original)

    def test_online_authority_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_online_translation_authority_changes(relative, raw=True)
            original = (
                ROOT / 'docs/online-translation-authority/original' / relative
            ).read_bytes()
            self.assertEqual(restored, original)

    def test_reference_binding_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_translation_reference_binding_changes(relative, raw=True)
            original = (
                ROOT / 'docs/translation-reference-binding/original' / relative
            ).read_bytes()
            self.assertEqual(restored, original)

    def test_clause_completeness_adapter_restores_exact_pre_phase_source(self):
        relative = 'app/translate/lyric_translation.py'
        restored = before_lyric_clause_completeness_changes(relative, raw=True)
        original = (
            ROOT / 'docs/lyric-clause-completeness/original' / relative
        ).read_bytes()
        self.assertEqual(restored, original)

    def test_api_request_pacing_adapter_restores_exact_pre_phase_source(self):
        relative = 'app/translate/online_logic.py'
        restored = before_api_request_pacing_changes(relative, raw=True)
        original = (ROOT / 'docs/api-request-pacing/original' / relative).read_bytes()
        self.assertEqual(restored, original)

    def test_long_translation_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_lyric_long_translation_changes(relative, raw=True)
            original = (ROOT / 'docs/lyric-long-translation/original' / relative).read_bytes()
            self.assertEqual(restored, original)

    def test_prompt_engineering_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_lyric_prompt_engineering_changes(relative, raw=True)
            original = (ROOT / 'docs/lyric-prompt-engineering/original' / relative).read_bytes()
            self.assertEqual(restored, original)

    def test_missing_gemini_default_adapter_restores_lyric_phase_source(self):
        relative = 'app/translate/online_logic.py'
        reviewed = (ROOT / 'docs/gemini-default-compat/reviewed' / relative).read_bytes()
        restored = before_gemini_default_compat_changes(relative, current=reviewed, raw=True)
        original = (ROOT / 'docs/gemini-default-compat/original' / relative).read_bytes()
        self.assertEqual(restored, original)

    def test_stability_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_lyric_translation_stability_changes(relative, raw=True)
            original = (ROOT / 'docs/lyric-translation-stability/original' / relative).read_bytes()
            self.assertEqual(restored, original)

    def test_exact_adapter_restores_pre_phase_online_logic(self):
        relative = 'app/translate/online_logic.py'
        restored = before_lyric_translation_changes(relative, raw=True)
        original = (ROOT / 'docs/lyric-translation/original' / relative).read_bytes()
        self.assertEqual(restored, original)


if __name__ == '__main__':
    unittest.main()
