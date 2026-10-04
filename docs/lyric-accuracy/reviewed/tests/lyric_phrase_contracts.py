"""Undo only the reviewed phrase edits before enforcing the rollback source."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_phrase_changes():
    from tests.lyric_accuracy_contracts import before_accuracy_changes
    source = before_accuracy_changes('app/pipeline/lyric_refinement.py')
    edits = json.loads((ROOT / 'docs/lyric-phrases/reviewed-edits.json').read_text(encoding='utf-8'))
    for edit in edits:
        if source.count(edit['after']) != 1:
            raise AssertionError(f"Phrase adapter changed outside review: {edit['name']}")
        source = source.replace(edit['after'], edit['before'], 1)
    original = (ROOT / 'docs/lyric-phrases/original/lyric_refinement.py').read_text(encoding='utf-8')
    if source != original:
        raise AssertionError('Unreviewed refinement change outside phrase grouping')
    rollback = (ROOT / 'docs/subtitle-timing/original/lyric_refinement.py').read_text(encoding='utf-8')
    if original != rollback:
        raise AssertionError('Phrase baseline is not the approved timestamp rollback')
    return source
