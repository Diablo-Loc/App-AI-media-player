"""Explicit capture of reviewed listening changes; previous manifests frozen."""
import difflib
import hashlib
import json
from pathlib import Path
from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'docs/audio-listening'
    manifest, patches = {}, []
    for path in sorted((destination / 'original').rglob('*.py')):
        relative = path.relative_to(destination / 'original').as_posix()
        before, after = path.read_bytes(), (ROOT / relative).read_bytes()
        old, new = before.decode('utf-8-sig'), after.decode('utf-8-sig')
        old_functions, new_functions = functions(old), functions(new)
        manifest[relative] = {'before_sha256': hashlib.sha256(before).hexdigest(),
            'after_sha256': hashlib.sha256(after).hexdigest(),
            'changed_functions': [name for name in old_functions if old_functions[name] != new_functions.get(name)],
            'added_functions': [name for name in new_functions if name not in old_functions]}
        patches.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                         fromfile='before/' + relative, tofile='after/' + relative))
    (destination / 'reviewed-sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (destination / 'reviewed.patch').write_text(''.join(patches), encoding='utf-8')


if __name__ == '__main__':
    main()
