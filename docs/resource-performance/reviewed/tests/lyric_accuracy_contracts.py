"""Restore only exactly reviewed accuracy sources before older frozen gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_accuracy_changes(relative, raw=False):
    from tests.resource_performance_contracts import before_resource_changes
    current = before_resource_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/lyric-accuracy/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/lyric-accuracy/reviewed' / relative).read_bytes()
        original = (ROOT / 'docs/lyric-accuracy/original' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Accuracy reviewed archive changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed accuracy change: ' + relative)
        if hashlib.sha256(original).hexdigest() != entry['before_sha256']:
            raise AssertionError('Accuracy baseline changed: ' + relative)
        current = original
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
