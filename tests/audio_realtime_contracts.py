"""Require reviewed v2 bytes, then restore the frozen v1 source for prior gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_realtime_changes(relative, raw=False):
    from tests.audio_start_contracts import before_start_changes
    current = before_start_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/audio-realtime/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
            raise AssertionError('Unreviewed audio v2 changes: ' + relative)
        current = (ROOT / 'docs/audio-realtime/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Audio v2 prior snapshot changed: ' + relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
