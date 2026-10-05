"""Restore the explicit sweep-track metadata phase before older source gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_sweep_track_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    manifest = json.loads(
        (ROOT / 'docs/subtitle-sweep-tracks/reviewed-sources.json').read_text(encoding='utf-8')
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/subtitle-sweep-tracks/reviewed' / relative).read_bytes()
        original = (ROOT / 'docs/subtitle-sweep-tracks/original' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Sweep-track reviewed archive changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed sweep-track source: ' + relative)
        if hashlib.sha256(original).hexdigest() != entry['before_sha256']:
            raise AssertionError('Sweep-track baseline changed: ' + relative)
        current = original
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
