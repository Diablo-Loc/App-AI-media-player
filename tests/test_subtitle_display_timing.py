"""Display margins, saved timing and real Qt cue boundaries; no API/ASR jobs."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from pipeline.lyric_refinement import (
    finalize_display_times, finalize_cue_times, refine_lyrics, mark_final_timing,
)
from subtitle.converter import refined_to_subtitles
from core.subtitle_manager import SubtitleManager


class DisplayTimingTests(unittest.TestCase):
    def test_reviewed_patch_restores_exact_pre_change_sources(self):
        import hashlib
        from tests.subtitle_display_timing_contracts import before_display_timing_changes
        fixture = json.loads((ROOT / 'tests/fixtures/subtitle_display_timing.json').read_text(encoding='utf-8'))
        for relative, entry in fixture.items():
            restored = before_display_timing_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(restored.replace(b'\r\n', b'\n')).hexdigest(), entry['before_sha256'])
        relative = 'app/ai/pipeline.py'
        changed = (ROOT / relative).read_bytes() + b'\n# unreviewed\n'
        with self.assertRaises(AssertionError):
            before_display_timing_changes(relative, current=changed)

    def test_v31_cjk_onset_and_tail_are_applied_once_to_new_generation(self):
        raw = [dict(start=10, end=12, text='君の声', words=[
            dict(start=10, end=11, word='君の'), dict(start=11, end=12, word='声')])]
        acoustic = refine_lyrics(raw)
        before = copy.deepcopy(acoustic)
        display = finalize_display_times(acoustic, cjk=True)
        self.assertEqual(display, [dict(start=10.1, end=12.37, text='君の声')])
        self.assertEqual(acoustic, before)
        subs = refined_to_subtitles(display, lang='ja')
        mark_final_timing(subs)
        with tempfile.TemporaryDirectory() as folder:
            manager = SubtitleManager(folder)
            self.assertTrue(manager.save_segments('new-song', subs))
            saved = manager.get_raw_data('new-song')['segments'][0]
            self.assertEqual((saved['start'], saved['end']), (10.1, 12.37))
            self.assertEqual(saved['jp'], '君の声')

    def test_latin_onset_never_anticipates_word_and_tail_matches_v31_saved_tail(self):
        cues = refine_lyrics([dict(start=1, end=4, text='Stay with me.', words=[])])
        self.assertEqual(finalize_display_times(cues), [
            dict(start=1, end=4.7, text='Stay with me.')])

    def test_close_cues_keep_incoming_onset_and_clip_only_outgoing_tail(self):
        raw = [dict(start=1, end=3, text='First line.', words=[]),
               dict(start=3, end=5, text='Second line.', words=[])]
        acoustic = refine_lyrics(raw)
        for cjk, onset in ((False, 3.0), (True, 3.1)):
            display = finalize_display_times(acoustic, cjk=cjk)
            self.assertEqual(display[1]['start'], onset)
            self.assertEqual(display[0]['end'], onset)
            self.assertEqual([c['text'] for c in display], [c['text'] for c in acoustic])

    def test_real_gap_tail_short_cues_and_duration_never_drop_or_reorder_text(self):
        cues = [dict(start=0, end=.02, text='Ah'),
                dict(start=.025, end=.045, text='Oh'),
                dict(start=1, end=2, text='Stay.'),
                dict(start=5.97, end=6, text='Go!')]
        before = copy.deepcopy(cues)
        for cjk in (False, True):
            display = finalize_display_times(cues, cjk=cjk, duration=6)
            self.assertEqual([c['text'] for c in display], [c['text'] for c in cues])
            self.assertEqual(display[-1]['end'], 6)
            for a, b in zip(display, display[1:]):
                self.assertLessEqual(a['end'], b['start'])
            self.assertTrue(all(c['end'] > c['start'] >= 0 for c in display))
            self.assertLess(display[2]['end'], 3)
        self.assertEqual(cues, before)
        self.assertEqual(finalize_display_times([], duration=6), [])

    def test_two_recorded_songs_preserve_whole_song_text_and_coverage_timeline(self):
        for name in ('Brand New Sky', '人生エンドロール'):
            data = json.loads((ROOT / 'docs/asr-resources' / f'{name}-round-1.json').read_text(encoding='utf-8'))
            cues = data['final']
            before = copy.deepcopy(cues)
            cjk = data['metrics']['language'] in ('ja', 'zh', 'ko')
            display = finalize_display_times(cues, cjk=cjk,
                duration=data['metrics']['diagnostic']['duration'])
            self.assertEqual([c['text'] for c in display], [c['text'] for c in cues])
            self.assertEqual(cues, before)
            self.assertEqual(display, finalize_cue_times(display,
                duration=data['metrics']['diagnostic']['duration']))

    def test_qt_effects_and_static_use_the_same_new_boundaries_pause_seek_and_gap(self):
        from tools.ui_preview import APPLICATION, pump
        from ui.subs_ui.subtitle_layer import SubtitleLayer
        from subtitle.mode import SubtitleMode
        cues = finalize_display_times(refine_lyrics([
            dict(start=1, end=3, text='First line.', words=[]),
            dict(start=3, end=5, text='Second line.', words=[]),
            dict(start=8, end=10, text='Third line.', words=[])]), cjk=True)
        segments = [dict(start=round(c['start']*1000), end=round(c['end']*1000), orig=c['text'])
                    for c in cues]
        layer = SubtitleLayer(initial_mode=SubtitleMode.JP)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(False)
        layer.load_subtitles(segments)
        for enabled in (False, True):
            layer._subtitle_effects.configure(dict(enabled=enabled, trail='shuriken', erase_passed=True))
            for ms, text in ((1099, None), (1100, 'First line.'),
                             (3099, 'First line.'), (3100, 'Second line.'),
                             (5370, 'Second line.'), (5371, None),
                             (8000, None), (8100, 'Third line.'),
                             (2000, 'First line.'), (6000, None)):
                layer.update_position(ms)
                self.assertEqual(layer.isHidden(), text is None, (enabled, ms))
                if text is not None:
                    self.assertEqual(layer.text(), text)
                    if enabled:
                        self.assertEqual(layer._subtitle_effects.cue[1:3],
                            next((s['start'], s['end']) for s in segments if s['orig'] == text))
            pump(1)
        APPLICATION.processEvents()


if __name__ == '__main__':
    unittest.main()
