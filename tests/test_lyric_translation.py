"""Focused contracts for natural, meaning-preserving online lyric translation."""
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
from tests.translation_v31_prompt_contracts import before_translation_v31_prompt_changes


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

    def test_legacy_soft_budget_helpers_remain_bounded_for_compatibility(self):
        en_short = soft_character_range(1.0, 'en')
        en_long = soft_character_range(4.0, 'en')
        vi_short = soft_character_range(1.0, 'vi')
        vi_long = soft_character_range(4.0, 'vi')
        self.assertLess(en_short[1], en_long[1])
        self.assertLess(vi_short[1], vi_long[1])
        self.assertLessEqual(en_long[1], 64)
        self.assertLessEqual(vi_long[1], 68)

    def test_simple_rows_keep_global_ids_unicode_and_skip_empty_cues(self):
        rows = build_translation_rows([
            cue('\u541b\u306e\u58f0\u304c\u805e\u3053\u3048\u308b', 0.0, 2.0),
            cue('   ', 2.0, 3.0),
            cue('Stay   with\nme', 3.0, 6.0),
        ]).splitlines()
        self.assertEqual(rows, [
            '0===\u541b\u306e\u58f0\u304c\u805e\u3053\u3048\u308b',
            '2===Stay with me',
        ])

    def test_verified_reference_stays_in_simple_same_id_block(self):
        content = lyric_translation_user_content(
            [cue('Machine lyric')],
            cue_ids=[47],
            verified_references={47: 'Verified lyric', 48: 'foreign cue'},
        )
        self.assertIn('THAM CHIẾU ĐÃ XÁC MINH (cùng ID):\n47===Verified lyric', content)
        self.assertIn('LỜI MÁY:\n47===Machine lyric', content)
        self.assertNotIn('foreign cue', content)

    def test_prompt_is_compact_natural_and_allows_complete_longer_lyrics(self):
        prompt = lyric_translation_system_prompt('Synthetic Song', has_reference=True)
        for phrase in (
            'toàn bộ các câu được gửi',
            'Dịch đầy đủ từng câu',
            'Giữ đủ ý và các vế có nghĩa',
            'đừng rút gọn chỉ để câu ngắn',
            'có thể dài hơn nếu cần để đúng và hay',
            'THAM CHIẾU ĐÃ XÁC MINH',
            'ID===English translation===Vietnamese translation',
        ):
            self.assertIn(phrase, prompt)
        self.assertLess(len(prompt), 1300)
        self.assertNotIn('preferred character', prompt.lower())
        self.assertNotIn('JSONL', prompt)

    def test_online_model_can_repair_clear_asr_without_verified_reference(self):
        prompt = lyric_translation_system_prompt('Synthetic Song', has_reference=False)
        self.assertIn('có thể sai một vài chữ', prompt)
        self.assertIn('ngữ cảnh bài hát', prompt)
        self.assertIn('Bài hát: Synthetic Song', prompt)
        self.assertNotIn('THAM CHIẾU ĐÃ XÁC MINH', prompt)

    def test_successful_normal_online_translation_is_single_pass(self):
        rows = [
            SimpleNamespace(start=0.0, end=2.0, top=SimpleNamespace(text='Line one'), middle=None, bottom=None),
            SimpleNamespace(start=2.0, end=5.0, top=SimpleNamespace(text='Line two with tail'), middle=None, bottom=None),
        ]
        settings = Mock()
        settings.value.side_effect = lambda key, default=None: default
        request = Mock()
        first = Mock()
        first.json.return_value = {
            'choices': [{'message': {'content': (
                '0===English one===Vietnamese one\n'
                '1===English two with full tail===Vietnamese two with full tail'
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
        self.assertEqual(rows[0].middle.text, 'English one')
        self.assertEqual(rows[1].middle.text, 'English two with full tail')
        self.assertEqual(rows[1].bottom.text, 'Vietnamese two with full tail')

    def test_online_provider_sampling_stays_low_variance(self):
        source = (ROOT / 'app/translate/online_logic.py').read_text(encoding='utf-8-sig')
        self.assertEqual(source.count('temperature=0.2'), 1)
        self.assertEqual(source.count('"temperature": 0.2'), 2)
        self.assertNotIn('temperature=0.3', source)
        self.assertNotIn('"temperature": 0.3', source)

    def test_gemini_has_explicit_output_budget(self):
        source = (ROOT / 'app/translate/online_logic.py').read_text(encoding='utf-8-sig')
        self.assertIn('max_output_tokens=16384', source)

    def test_request_uses_simple_v31_style_rows_without_per_cue_budget(self):
        content = lyric_translation_user_content(
            [cue('Source lyric', 0.0, 1.6)],
            song_title='Synthetic Song',
            reference_lyric='Reference lyric',
        )
        self.assertIn('BÀI HÁT: Synthetic Song', content)
        self.assertIn('LỜI THAM CHIẾU:\nReference lyric', content)
        self.assertIn('LỜI MÁY:\n0===Source lyric', content)
        self.assertNotIn('duration_s', content)
        self.assertNotIn('preferred_chars', content)
        self.assertNotIn('JSONL', content)

    def test_request_keeps_verified_reference_bound_by_same_id(self):
        content = lyric_translation_user_content(
            [cue('Machine recognized tail', 0.0, 2.0)],
            song_title='Synthetic Song',
            cue_ids=[12],
            verified_references={12: 'Verified corrected tail'},
        )
        self.assertIn('THAM CHIẾU ĐÃ XÁC MINH (cùng ID):\n12===Verified corrected tail', content)
        self.assertIn('LỜI MÁY:\n12===Machine recognized tail', content)

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

    def test_batched_content_ignores_boundary_metadata_and_keeps_global_id(self):
        content = lyric_translation_user_content(
            [cue('Current line')],
            song_title='Synthetic Song',
            cue_ids=[60],
            context_before='Previous line',
            context_after='Next line',
        )
        self.assertIn('LỜI MÁY:\n60===Current line', content)
        self.assertNotIn('Previous line', content)
        self.assertNotIn('Next line', content)

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
            payload_text = content.rsplit('LỜI MÁY:\n', 1)[1]
            batch_rows = []
            for line in payload_text.splitlines():
                if '===' not in line:
                    continue
                idx_text, source = line.split('===', 1)
                if idx_text.strip().isdigit():
                    batch_rows.append((int(idx_text), source))
            if call_number in set(fail_calls or ()):
                batch_rows = batch_rows[:-1]
            translated = '\n'.join(
                f"{idx}===EN {idx}===VI {idx}" for idx, _source in batch_rows
            )
            response = Mock()
            response.json.return_value = {'choices': [{'message': {'content': translated}}]}
            return response

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
    def test_v31_prompt_adapter_restores_exact_pre_phase_sources(self):
        for relative in (
            'app/translate/online_logic.py',
            'app/translate/lyric_translation.py',
        ):
            restored = before_translation_v31_prompt_changes(relative, raw=True)
            original = (
                ROOT / 'docs/translation-v31-prompt/original' / relative
            ).read_bytes()
            self.assertEqual(restored, original)

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
