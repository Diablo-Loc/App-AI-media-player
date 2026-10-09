"""Restore only exact reviewed presentation changes for older source gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_presentation_changes(relative, raw=False):
    from tests.audio_effects_contracts import before_audio_changes
    current = before_audio_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/subtitle-presentation/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
            raise AssertionError(f'Unreviewed change after subtitle presentation phase: {relative}')
        current = (ROOT / 'docs/subtitle-presentation/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError(f'Subtitle presentation snapshot changed: {relative}')
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
