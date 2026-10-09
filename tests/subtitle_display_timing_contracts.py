"""Peel only the reviewed final-display patch before historical source checks."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_display_timing_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.dialogue_mode_contracts import before_dialogue_mode_changes
    current = before_dialogue_mode_changes(relative, current=current, raw=True)
    from tests.subtitle_display_tail_contracts import before_display_tail_changes
    current = before_display_tail_changes(relative, current=current, raw=True)
    source = current.decode('utf-8-sig').replace('\r\n', '\n')
    manifest = json.loads((ROOT / 'tests/fixtures/subtitle_display_timing.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        if digest != entry['before_sha256']:
            if digest != entry['after_sha256']:
                raise AssertionError('Unreviewed display timing change: ' + relative)
            for edit in reversed(entry['edits']):
                if source.count(edit['after']) != 1:
                    raise AssertionError('Display timing adapter changed: ' + relative)
                source = source.replace(edit['after'], edit['before'], 1)
            if hashlib.sha256(source.encode('utf-8')).hexdigest() != entry['before_sha256']:
                raise AssertionError('Display timing baseline changed: ' + relative)
            current = source.encode('utf-8')
    return current if raw else source
