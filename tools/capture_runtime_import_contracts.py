"""Capture narrow import corrections without rewriting any earlier manifest."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT/'docs/runtime-imports'
    manifest, patches = {}, []
    for path in sorted((destination/'original').rglob('*.py')):
        relative = path.relative_to(destination/'original').as_posix()
        before, after = path.read_bytes(), (ROOT/relative).read_bytes()
        reviewed = destination/'reviewed'/relative
        reviewed.parent.mkdir(parents=True, exist_ok=True)
        reviewed.write_bytes(after)
        manifest[relative] = {'before_sha256': hashlib.sha256(before).hexdigest(),
                              'after_sha256': hashlib.sha256(after).hexdigest()}
        patches.extend(difflib.unified_diff(before.decode('utf-8-sig').splitlines(True),
            after.decode('utf-8-sig').splitlines(True), fromfile='before/'+relative, tofile='after/'+relative))
    (destination/'reviewed-sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (destination/'reviewed.patch').write_text(''.join(patches), encoding='utf-8')


if __name__ == '__main__':
    main()
