"""New cue grouping and actual Qt display; no ASR, media or saved-file migration."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from pipeline.lyric_refinement import refine_lyrics, join_tokens
from tests.lyric_phrase_contracts import before_phrase_changes


def word(start, end, text):
    return dict(start=start, end=end, word=text)


def segment(words):
    return dict(start=words[0]['start'], end=max(w['end'] for w in words),
                text=join_tokens([w['word'] for w in words]), words=words)


class LyricPhraseTests(unittest.TestCase):
    def test_contiguous_short_complete_asr_lines_and_refrains_stay_separate(self):
        for tokens in (('Hold', 'my', 'hand'), ('君', 'の', '声'), ('Giữ', 'tay', 'em'),
                       ('너의', '손을', '잡아')):
            raw = [segment([word(1 + i * 2 + j * .6, 1 + i * 2 + (j + 1) * .6, token)
                            for j, token in enumerate(tokens)]) for i in range(3)]
            cues = refine_lyrics(raw)
            self.assertEqual([c['text'] for c in cues], [join_tokens(tokens)] * 3)
            self.assertTrue(all(a['end'] <= b['start'] for a, b in zip(cues, cues[1:])))

    def test_tiny_asr_fragments_are_joined_not_treated_as_complete_lines(self):
        raw = [segment([word(1, 1.4, 'Hold')]),
               segment([word(1.4, 1.6, 'my'), word(1.6, 3.4, 'hand')])]
        self.assertEqual([c['text'] for c in refine_lyrics(raw)], ['Hold my hand'])

    def test_short_refrains_without_punctuation_remain_separate_performances(self):
        raw = [segment([word(1 + i, 1.3 + i, 'I'), word(1.3 + i, 1.6 + i, 'love'),
                        word(1.6 + i, 2 + i, 'you')]) for i in range(3)]
        self.assertEqual([c['text'] for c in refine_lyrics(raw)], ['I love you'] * 3)

    def test_long_source_followed_by_tiny_continuation_does_not_orphan_last_word(self):
        raw = [segment([word(1, 3, 'I'), word(3, 5, 'remember')]),
               segment([word(5, 5.3, 'you')])]
        self.assertEqual([c['text'] for c in refine_lyrics(raw)], ['I remember you'])

    def test_long_sustained_note_does_not_force_eight_second_mid_sentence_cut(self):
        raw = [segment([word(1, 2, 'We'), word(2, 3, 'sing'), word(3, 12, 'again')])]
        cues = refine_lyrics(raw)
        self.assertEqual(cues, [dict(start=.95, end=12.08, text='We sing again')])

    def test_small_breath_inside_a_sentence_does_not_split_a_fragment(self):
        words = [word(1, 2, 'Please'), word(2, 3.5, 'stay'),
                 word(3.78, 4, 'with'), word(4, 5, 'me')]
        self.assertEqual([c['text'] for c in refine_lyrics([segment(words)], max_chars=10)],
                         ['Please stay with me'])

    def test_real_pause_stays_empty_and_does_not_extend_previous_sentence(self):
        raw = [segment([word(1, 2, 'Stay'), word(2, 3, 'here'),
                        word(6, 7, 'Come'), word(7, 8, 'back')])]
        self.assertEqual(refine_lyrics(raw), [dict(start=.95, end=3.08, text='Stay here'),
                                             dict(start=5.95, end=8.08, text='Come back')])

    def test_newline_before_word_breaks_before_not_after_that_word(self):
        raw = [segment([word(1, 2, 'First'), word(2, 3, '\nSecond'), word(3, 4, 'line')])]
        self.assertEqual([c['text'] for c in refine_lyrics(raw)], ['First', 'Second line'])

    def test_newline_inside_indivisible_word_has_no_invented_phrase_timestamp(self):
        raw = [segment([word(1, 4, 'First\nSecond')])]
        cues = refine_lyrics(raw)
        self.assertEqual(cues, [dict(start=.95, end=4.08, text='First Second')])

    def test_oversized_phrase_is_balanced_without_losing_or_orphaning_tokens(self):
        words = [word(1 + i * .2, 1.2 + i * .2, f'word{i:02d}') for i in range(25)]
        raw = [segment(words)]
        before = copy.deepcopy(raw)
        cues = refine_lyrics(raw, max_chars=74)
        self.assertEqual(len(cues), 2)
        self.assertTrue(all(10 <= len(c['text'].split()) <= 15 for c in cues))
        self.assertEqual([token for c in cues for token in c['text'].split()],
                         [w['word'] for w in words])
        self.assertEqual(raw, before)

    def test_missing_word_times_keep_source_text_whole_including_two_sentences(self):
        cues = refine_lyrics([dict(start=1, end=10, text='Stay here. Come back.', words=[])])
        self.assertEqual(cues, [dict(start=.95, end=10.08, text='Stay here. Come back.')])

    def test_captured_real_cases_no_longer_merge_adjacent_asr_lines_or_cut_small_breath(self):
        for name, start, expected in [
                ('Brand New Sky', 44.94, ["There's a world behind the fear", 'So it can make me feel alive']),
                ('人生エンドロール', 87.82, ['主人公じゃないから見合わないのに'])]:
            data = json.loads((ROOT / 'docs/asr-coverage/verified-strict' / f'{name}.json').read_text(encoding='utf-8'))
            raw = [dict(row, text=join_tokens([w['word'] for w in row['words']])) for row in data['raw']]
            cues = refine_lyrics(raw, max_chars=22 if data['language'] == 'ja' else 74)
            selected = [c['text'] for c in cues if start - .1 <= c['start'] <= start + 4]
            self.assertEqual(selected[:len(expected)], expected)

    def test_only_grouping_and_newline_adapters_change_refinement_source(self):
        before_phrase_changes()

    def test_qt_displays_only_active_phrase_and_retains_language_modes(self):
        from tools.ui_preview import APPLICATION, pump
        from ui.subs_ui.subtitle_layer import SubtitleLayer
        from subtitle.mode import SubtitleMode
        layer = SubtitleLayer(initial_mode=SubtitleMode.JP)
        self.addCleanup(layer.deleteLater)
        layer.load_subtitles([dict(start=1000, end=3000, jp='First phrase', en='English one', vi='Câu một'),
                              dict(start=6000, end=8000, jp='Second phrase', en='English two', vi='Câu hai')])
        layer.update_position(1500)
        self.assertEqual(layer.text(), 'First phrase')
        layer.set_mode(SubtitleMode.JP_EN_VI)
        layer.update_position(2000)
        self.assertEqual(layer.text(), 'First phrase\nEnglish one\nCâu một')
        layer.update_position(4000)
        pump(260)
        self.assertTrue(layer.isHidden())
        layer.set_mode(SubtitleMode.JP)
        layer.update_position(6500)
        self.assertEqual(layer.text(), 'Second phrase')
        APPLICATION.processEvents()
