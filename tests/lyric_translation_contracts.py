"""Restore the lyric-translation prompt phase before historical source gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_lyric_translation_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    # Genius reference assistance is newer than lyric translation shaping.
    # Peel it before validating the frozen translation phase.
    from tests.genius_reference_contracts import before_genius_reference_changes
    current = before_genius_reference_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / 'docs/lyric-translation/reviewed-sources.json').read_text(encoding='utf-8')
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/lyric-translation/reviewed' / relative).read_bytes()
        original = (ROOT / 'docs/lyric-translation/original' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Lyric-translation reviewed archive changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed lyric-translation source: ' + relative)
        if hashlib.sha256(original).hexdigest() != entry['before_sha256']:
            raise AssertionError('Lyric-translation baseline changed: ' + relative)
        current = original
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
