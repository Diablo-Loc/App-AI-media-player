"""Require reviewed prefetch bytes before restoring frozen selection-wait scope."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_prefetch_changes(relative, raw=False):
    from tests.audio_listening_contracts import before_listening_changes
    current = before_listening_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/audio-prefetch/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
            raise AssertionError('Unreviewed audio prefetch changes: ' + relative)
        current = (ROOT / 'docs/audio-prefetch/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Audio prefetch snapshot changed: ' + relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
