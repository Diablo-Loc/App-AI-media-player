"""Read-only inventory/compile and saved-data checks for the final flow review."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'docs/final-flow-review'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compare', action='store_true')
    args = parser.parse_args()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    saved_path = DESTINATION / 'saved-before.json'
    if args.compare:
        original = json.loads(saved_path.read_text(encoding='utf-8'))
        checks = [dict(row, unchanged=Path(row['path']).is_file() and digest(Path(row['path'])) == row['sha256'])
                  for row in original]
        (DESTINATION / 'saved-file-check.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
        if not all(row['unchanged'] for row in checks):
            raise SystemExit('Saved-data hashes changed; inspect before continuing.')
        print(f'{len(checks)}/{len(checks)} saved-file hashes unchanged')
        return
    paths = json.loads((ROOT / 'docs/audio-easy/saved-before.json').read_text(encoding='utf-8-sig'))
    saved = [{'path': row['Path'], 'sha256': digest(Path(row['Path']))} for row in paths]
    saved_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
    started, sources, errors = time.perf_counter(), [], []
    for path in sorted((ROOT / 'app').rglob('*.py')):
        relative, raw = path.relative_to(ROOT).as_posix(), path.read_bytes()
        try:
            tree = ast.parse(raw, filename=relative)
            compile(tree, relative, 'exec')  # No imports, execution, model load or pyc writes.
            functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            sources.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest(),
                            'lines': len(raw.splitlines()), 'functions': len(functions),
                            'classes': sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree)),
                            'imports': sum(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))})
        except (SyntaxError, ValueError, TypeError) as error:
            errors.append({'path': relative, 'error': str(error)})
    report = {'head': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip(),
              'python': sys.version, 'mode': 'read-only AST/compile, not runtime feature parity',
              'source_count': len(sources), 'total_lines': sum(row['lines'] for row in sources),
              'total_functions': sum(row['functions'] for row in sources),
              'seconds': time.perf_counter() - started, 'errors': errors, 'sources': sources}
    (DESTINATION / 'inventory.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{report['source_count']} Python sources / {report['total_lines']} lines / {report['total_functions']} functions; {len(errors)} compile errors")
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
