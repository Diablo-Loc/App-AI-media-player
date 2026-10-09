"""Replay local captured ASR from eight videos; never regenerate saved songs."""
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from pipeline.lyric_refinement import refine_lyrics, finalize_cue_times, join_tokens, _key, mark_final_timing
from pipeline.lyric_formatter import export_srt, export_lrc
from subtitle.converter import refined_to_subtitles
from core.subtitle_manager import SubtitleManager


def baseline_refiner():
    module = types.ModuleType('pipeline._before_phrase_probe')
    module.__package__ = 'pipeline'
    source = ROOT / 'docs/lyric-phrases/original/lyric_refinement.py'
    exec(compile(source.read_text(encoding='utf-8'), str(source), 'exec'), module.__dict__)
    return module.refine_lyrics


def digest_saved():
    folder = ROOT / 'storage/subtitles'
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob('*') if path.is_file()}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    output = ROOT / 'docs/lyric-phrases/replay'
    output.mkdir(parents=True, exist_ok=True)
    saved_before = digest_saved()
    old_refine = baseline_refiner()
    reports = []
    with tempfile.TemporaryDirectory(prefix='botube-phrase-probe-') as directory:
        manager = SubtitleManager(directory)
        for path in sorted((ROOT / 'docs/asr-resources').glob('*-round-*.json')):
            data = json.loads(path.read_text(encoding='utf-8'))
            language = data['metrics']['language']
            duration = data['metrics']['diagnostic']['duration']
            raw = [dict(row, text=join_tokens([w['word'] for w in row['words']]) or row['text'])
                   for row in data['raw']]
            options = dict(max_chars=22 if language in ('ja', 'zh', 'ko') else 74,
                           min_pause=.54 if language in ('ja', 'zh', 'ko') else .6)
            before = finalize_cue_times(old_refine(raw, **options), duration)
            after = finalize_cue_times(refine_lyrics(raw, **options), duration)
            times = []
            for _ in range(5):
                tick = time.perf_counter()
                refine_lyrics(raw, **options)
                times.append((time.perf_counter() - tick) * 1000)
            media_name = path.stem.rsplit('-round-', 1)[0]
            media = ROOT / 'video' / f'{media_name}.mp4'
            report = dict(dataset=path.name, media_exists=media.is_file(), language=language,
                          raw_words=sum(len(row['words']) for row in raw),
                          before_cues=len(before), after_cues=len(after),
                          accepted_text_and_order_unchanged=_key(join_tokens([c['text'] for c in before]))
                              == _key(join_tokens([c['text'] for c in after])),
                          no_overlap=all(a['end'] <= b['start'] for a, b in zip(after, after[1:])),
                          finite_in_bounds=all(0 <= c['start'] < c['end'] <= duration for c in after),
                          median_refine_ms=statistics.median(times))
            subs = refined_to_subtitles(after, language)
            mark_final_timing(subs)
            saved_path = manager.save_segments(path.stem, subs)
            stored = manager.get_raw_data(path.stem)['segments']
            report['saved_times_equal_refined'] = [(c['start'], c['end']) for c in stored] == [
                (c['start'], c['end']) for c in after]
            report['ass_saved'] = bool(saved_path)
            (output / path.name).write_text(json.dumps(dict(report=report, before=before, after=after),
                ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            export_srt(after, output / f'{path.stem}.srt')
            export_lrc(after, output / f'{path.stem}.lrc')
            assert all(report[key] for key in ('media_exists', 'accepted_text_and_order_unchanged',
                'no_overlap', 'finite_in_bounds', 'saved_times_equal_refined', 'ass_saved')), report
            reports.append(report)
    unchanged = digest_saved() == saved_before
    assert unchanged
    summary = dict(datasets=len(reports), videos=len({r['dataset'].rsplit('-round-', 1)[0] for r in reports}),
                   existing_saved_files=len(saved_before), existing_saved_files_unchanged=unchanged,
                   reference='Captured ASR replay, not fresh ASR or human lyric/timing ground truth',
                   reports=reports)
    (output.parent / 'comparison.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output.parent / 'saved-hashes.json').write_text(json.dumps(saved_before, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key != 'reports'}, ensure_ascii=False))
    for row in reports[::3]:
        print(row['dataset'], row['before_cues'], '->', row['after_cues'],
              round(row['median_refine_ms'], 3), 'ms')


if __name__ == '__main__':
    main()
