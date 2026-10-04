"""Exact reviewed metadata adapters precede every frozen historical gate."""
import hashlib
import json
from pathlib import Path
from tests.volume_build_contracts import before_volume_changes

ROOT = Path(__file__).resolve().parents[1]


def before_media_info_changes(relative, raw=False):
    current = before_volume_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/media-info/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/media-info/reviewed' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Reviewed metadata source changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed metadata changes: ' + relative)
        current = (ROOT / 'docs/media-info/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Metadata baseline changed: ' + relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
