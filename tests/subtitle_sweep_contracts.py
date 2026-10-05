"""Restore only exact reviewed disappearing-word edits for prior source gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_sweep_changes(relative, raw=False):
    from tests.subtitle_kinetic_contracts import before_kinetic_changes
    current = before_kinetic_changes(relative, raw=True)
    # Newest reviewed live fade adapter is peeled off before the frozen sweep
    # archive is compared; older manifests remain byte-for-byte untouched.
    from tests.subtitle_sweep_fade_fix_contracts import before_sweep_fade_fix
    current = before_sweep_fade_fix(relative, current=current, raw=True)
    manifest = json.loads((ROOT/'docs/subtitle-sweep/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT/'docs/subtitle-sweep/reviewed'/relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Sweep archive changed: '+relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed sweep source: '+relative)
        current = (ROOT/'docs/subtitle-sweep/original'/relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Sweep baseline changed: '+relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
