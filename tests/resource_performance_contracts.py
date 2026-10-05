"""Exact resource-phase restoration before all historical contract gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_resource_changes(relative, raw=False):
    # The export phase is newer than this frozen resource phase.  Validate and
    # peel off only that reviewed UI adapter before applying the historical
    # resource snapshots below; never recapture an older manifest.
    from tests.video_export_contracts import before_video_export_changes
    current = before_video_export_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/resource-performance/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/resource-performance/reviewed' / relative).read_bytes()
        original = (ROOT / 'docs/resource-performance/original' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Resource archive changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed resource change: ' + relative)
        if hashlib.sha256(original).hexdigest() != entry['before_sha256']:
            raise AssertionError('Resource baseline changed: ' + relative)
        current = original
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
