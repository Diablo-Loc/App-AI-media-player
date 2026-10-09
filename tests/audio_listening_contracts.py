"""Restore only exactly reviewed listening presets before frozen prior gates."""
import hashlib
import json
from pathlib import Path
from tests.audio_easy_contracts import before_easy_changes

ROOT = Path(__file__).resolve().parents[1]


def before_listening_changes(relative, raw=False):
    current = before_easy_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/audio-listening/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
            raise AssertionError('Unreviewed listening changes: ' + relative)
        current = (ROOT / 'docs/audio-listening/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Listening snapshot changed: ' + relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
