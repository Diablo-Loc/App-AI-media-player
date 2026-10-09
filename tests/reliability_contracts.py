"""Exact approved source restoration before running older phase contracts."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_reliability_changes(relative, raw=False):
    from tests.subtitle_presentation_contracts import before_presentation_changes
    current = before_presentation_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/reliability/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative not in manifest:
        return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
    entry = manifest[relative]
    if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
        raise AssertionError(f'Unreviewed change after reliability phase: {relative}')
    original = (ROOT / 'docs/reliability/original' / relative).read_bytes()
    if hashlib.sha256(original).hexdigest() != entry['before_sha256']:
        raise AssertionError(f'Reliability snapshot changed: {relative}')
    return original if raw else original.decode('utf-8-sig').replace('\r\n', '\n')
