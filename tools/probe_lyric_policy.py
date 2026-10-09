"""Replay/measure only cheap text filtering; never runs ASR or saves user cues."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from pipeline.lyric_refinement import refine_lyrics, join_tokens, _key, accepts_source_text


def main():
    output = ROOT / 'docs/lyric-accuracy'
    baseline = types.ModuleType('pipeline._before_accuracy_probe')
    baseline.__package__ = 'pipeline'
    original = output / 'original/app/pipeline/lyric_refinement.py'
    exec(compile(original.read_text(encoding='utf-8'), str(original), 'exec'), baseline.__dict__)
    comparisons = []
    for path in sorted((ROOT / 'docs/asr-resources').glob('*-round-*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        language = data['metrics']['language']
        raw = [dict(row, text=join_tokens([w['word'] for w in row['words']]) or row['text'])
               for row in data['raw']]
        options = dict(max_chars=22 if language in ('ja', 'zh', 'ko') else 74,
                       min_pause=.54 if language in ('ja', 'zh', 'ko') else .6)
        old, new = baseline.refine_lyrics(raw, **options), refine_lyrics(raw, **options)
        before, after = Counter(_key(join_tokens([c['text'] for c in old]))), Counter(_key(join_tokens([c['text'] for c in new])))
        comparisons.append(dict(dataset=path.name, old_cues=len(old), new_cues=len(new),
            exact_old_output_equal=old == new, previous_character_inventory_retained=not bool(before - after),
            added_characters=sum((after - before).values()),
            no_overlap=all(a['end'] <= b['start'] for a, b in zip(new, new[1:])),
            in_bounds=all(0 <= c['start'] < c['end'] <= data['metrics']['diagnostic']['duration'] for c in new),
            newly_accepted_text=[row['text'] for row in raw if
                not baseline.accepts_source_text(row['text'], timed_words=bool(row['words']))
                and accepts_source_text(row['text'], timed_words=bool(row['words']))]))
    samples = [('Eye of the tiger.', True), ('音楽が好きだ', True), ('I love you.', True),
               ('The sign is lightening up', True), ('Thanks for watching', True),
               ('作詞・作曲・編曲 初音ミク', False), ('A regular lyric line.', True), ('Music', False)] * 1250
    measurements = {}
    for name, fn in (('old_credit_policy', baseline.accepts_source_text), ('new_credit_policy', accepts_source_text)):
        times = []
        for _ in range(5):
            started = time.perf_counter()
            results = [fn(text, timed_words=timed) for text, timed in samples]
            times.append((time.perf_counter() - started) * 1000)
        measurements[name] = dict(calls=len(samples), median_ms=statistics.median(times), accepted=sum(results))
    saved = json.loads((output / 'saved-before.json').read_text(encoding='utf-8'))
    changed = [row['path'] for row in saved if not (ROOT / row['path']).is_file()
               or hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() != row['sha256']]
    report = dict(reference='Captured ASR replay and synthetic text benchmark; no fresh ASR/human ground truth',
        comparisons=comparisons, filter_benchmark=measurements, saved_files=len(saved), changed_saved_files=changed)
    assert not changed, changed
    assert all(c['previous_character_inventory_retained'] and c['no_overlap'] and c['in_bounds'] for c in comparisons)
    (output / 'policy-review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(datasets=len(comparisons), exact_old_output_equal=sum(c['exact_old_output_equal'] for c in comparisons),
                         measurements=measurements, saved_files=len(saved), changed_saved_files=changed), ensure_ascii=False))


if __name__ == '__main__':
    main()
