"""Restore only this exact reviewed downloader phase for preceding gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_download_changes(relative, raw=False):
    from tests.runtime_import_contracts import before_import_changes
    current = before_import_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/download-quality/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/download-quality/reviewed' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Downloader reviewed snapshot changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed downloader changes: ' + relative)
        current = (ROOT / 'docs/download-quality/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Downloader baseline changed: ' + relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
