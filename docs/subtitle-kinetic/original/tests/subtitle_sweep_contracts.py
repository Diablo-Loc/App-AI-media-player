"""Restore only exact reviewed disappearing-word edits for prior source gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_sweep_changes(relative, raw=False):
    current = (ROOT/relative).read_bytes()
    manifest = json.loads((ROOT/'docs/subtitle-sweep/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT/'docs/subtitle-sweep/reviewed'/relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Sweep archive changed: '+relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed sweep source: '+relative)
        current = (ROOT/'docs/subtitle-sweep/original'/relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Sweep baseline changed: '+relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
