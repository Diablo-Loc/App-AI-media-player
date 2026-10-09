"""Restore reviewed selection-wait changes before the frozen earlier gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_start_changes(relative, raw=False):
    from tests.audio_prefetch_contracts import before_prefetch_changes
    current = before_prefetch_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/audio-start/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
            raise AssertionError('Unreviewed audio start changes: ' + relative)
        current = (ROOT / 'docs/audio-start/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Audio start snapshot changed: ' + relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
