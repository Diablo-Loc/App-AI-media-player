"""Explicit developer-reviewed capture, never used to auto-approve in tests."""
import difflib
import hashlib
import json
from pathlib import Path

from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'docs/audio-effects'
    manifest, patches = {}, []
    for snapshot in sorted((destination / 'original').rglob('*')):
        if not snapshot.is_file():
            continue
        relative = snapshot.relative_to(destination / 'original').as_posix()
        old, new = snapshot.read_bytes(), (ROOT / relative).read_bytes()
        old_text, new_text = old.decode('utf-8-sig'), new.decode('utf-8-sig')
        before, after = (functions(old_text), functions(new_text)) if relative.endswith('.py') else ({}, {})
        manifest[relative] = {
            'before_sha256': hashlib.sha256(old).hexdigest(),
            'after_sha256': hashlib.sha256(new).hexdigest(),
            'changed_functions': [name for name in before if before[name] != after.get(name)],
            'added_functions': [name for name in after if name not in before],
        }
        patches.extend(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                          fromfile='before/' + relative, tofile='after/' + relative))
    (destination / 'reviewed-sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (destination / 'reviewed.patch').write_text(''.join(patches), encoding='utf-8')
    helpers = ['app/core/audio_profile.py', 'app/core/audio_effects.py', 'app/control/audio_effects.py',
               'app/ui/audio_effects_panel.py', 'app/ui/assets/icons/sliders-horizontal.svg']
    (destination / 'new-source-hashes.json').write_text(json.dumps({
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in helpers}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
