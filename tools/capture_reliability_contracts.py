"""Explicit developer capture after reviewing the phase diff, never run in tests."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def functions(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            result[node.name] = ast.dump(node)
        elif isinstance(node, ast.ClassDef):
            result.update({node.name + '.' + item.name: ast.dump(item) for item in node.body
                           if isinstance(item, ast.FunctionDef)})
    return result


def main():
    snapshots = ROOT / 'docs/reliability/original'
    manifest, patches = {}, []
    for old_path in sorted(snapshots.rglob('*.py')):
        relative = old_path.relative_to(snapshots).as_posix()
        old, new = old_path.read_bytes(), (ROOT / relative).read_bytes()
        old_text, new_text = old.decode('utf-8-sig'), new.decode('utf-8-sig')
        before, after = functions(old_text), functions(new_text)
        manifest[relative] = {
            'before_sha256': hashlib.sha256(old).hexdigest(),
            'after_sha256': hashlib.sha256(new).hexdigest(),
            'changed_functions': [name for name in before if before[name] != after.get(name)],
            'added_functions': [name for name in after if name not in before],
        }
        patches.extend(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                                          fromfile='before/' + relative, tofile='after/' + relative))
    destination = ROOT / 'docs/reliability'
    (destination / 'reviewed-sources.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / 'reviewed.patch').write_text(''.join(patches), encoding='utf-8')
    helpers = ('app/core/subtitle_persistence.py', 'app/control/library_scan.py', 'app/control/worker_lifecycle.py')
    (destination / 'new-source-hashes.json').write_text(json.dumps({
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in helpers}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
