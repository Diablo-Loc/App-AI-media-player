"""Developer capture after reviewing this phase; never called by tests."""
import difflib
import hashlib
import json
from pathlib import Path

from tools.capture_reliability_contracts import functions

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'docs/subtitle-presentation'
    manifest, patches = {}, []
    for snapshot in sorted((destination / 'original').rglob('*.py')):
        relative = snapshot.relative_to(destination / 'original').as_posix()
        old, new = snapshot.read_bytes(), (ROOT / relative).read_bytes()
        old_text, new_text = old.decode('utf-8-sig'), new.decode('utf-8-sig')
        before, after = functions(old_text), functions(new_text)
        manifest[relative] = dict(
            before_sha256=hashlib.sha256(old).hexdigest(),
            after_sha256=hashlib.sha256(new).hexdigest(),
            changed_functions=[name for name in before if before[name] != after.get(name)],
            added_functions=[name for name in after if name not in before],
        )
        patches.extend(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                          fromfile='before/' + relative, tofile='after/' + relative))
    (destination / 'reviewed-sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (destination / 'reviewed.patch').write_text(''.join(patches), encoding='utf-8')
    helper = 'app/ui/subtitle_presentation.py'
    (destination / 'helper-hash.json').write_text(json.dumps({
        helper: hashlib.sha256((ROOT / helper).read_bytes()).hexdigest()}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
