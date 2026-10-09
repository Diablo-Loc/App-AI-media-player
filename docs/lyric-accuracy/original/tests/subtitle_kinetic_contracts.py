"""Restore exact kinetic UI edits before the sweep and preceding source gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_kinetic_changes(relative, raw=False):
    current = (ROOT/relative).read_bytes()
    manifest = json.loads((ROOT/'docs/subtitle-kinetic/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT/'docs/subtitle-kinetic/reviewed'/relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Kinetic archive changed: '+relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed kinetic source: '+relative)
        current = (ROOT/'docs/subtitle-kinetic/original'/relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Kinetic baseline changed: '+relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
