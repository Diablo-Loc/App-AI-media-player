"""Restore exact particle-phase edits before all preceding source manifests."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_particle_changes(relative, raw=False):
    current = (ROOT / relative).read_bytes()
    manifest = json.loads((ROOT / 'docs/subtitle-particles/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT/'docs/subtitle-particles/reviewed'/relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Particle archive changed: '+relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed particle source: '+relative)
        current = (ROOT/'docs/subtitle-particles/original'/relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Particle baseline changed: '+relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
