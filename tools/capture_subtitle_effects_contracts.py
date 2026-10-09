"""Capture this phase only; preceding manifests are never rewritten."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'docs/subtitle-effects'
PATHS = ('app/ui/main_window.py', 'app/ui/subs_ui/subtitle_layer.py',
         'app/ui/subs_ui/sub_panel.py', 'tests/runtime_import_contracts.py',
         'tests/test_runtime_imports.py', 'tests/test_ui_refresh.py', 'tests/test_volume_build.py')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', action='store_true')
    args = parser.parse_args()
    if args.before:
        if (DESTINATION / 'app-before.json').exists():
            raise RuntimeError('Phase baseline already captured')
        for relative in PATHS:
            target = DESTINATION / 'original' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        sources = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (ROOT / 'app').rglob('*.py')}
        DESTINATION.mkdir(parents=True, exist_ok=True)
        (DESTINATION / 'app-before.json').write_text(json.dumps(sources, indent=2), encoding='utf-8')
        saved = []
        for folder in ('storage', 'output', 'video'):
            for path in (ROOT / folder).rglob('*'):
                if path.is_file():
                    saved.append({'path': path.relative_to(ROOT).as_posix(),
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        (DESTINATION / 'saved-before.json').write_text(json.dumps(saved, indent=2), encoding='utf-8')
        return
    manifest, patch = {}, []
    for relative in PATHS:
        before = (DESTINATION / 'original' / relative).read_bytes()
        after = (ROOT / relative).read_bytes()
        target = DESTINATION / 'reviewed' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(after)
        manifest[relative] = {'before_sha256': hashlib.sha256(before).hexdigest(),
                              'after_sha256': hashlib.sha256(after).hexdigest()}
        patch.extend(difflib.unified_diff(before.decode('utf-8-sig').splitlines(True),
                     after.decode('utf-8-sig').splitlines(True),
                     fromfile='before/' + relative, tofile='after/' + relative))
    (DESTINATION / 'reviewed-sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (DESTINATION / 'reviewed.patch').write_text(''.join(patch), encoding='utf-8')
    helpers = {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
               for relative in ('app/ui/subtitle_effects.py', 'app/ui/subtitle_effects_panel.py')}
    (DESTINATION / 'helper-hash.json').write_text(json.dumps(helpers, indent=2), encoding='utf-8')
    normalized = DESTINATION / 'app-before-normalized.json'
    if not normalized.exists():
        # Derive checkout-safe hashes only from bytes matching the existing raw
        # baseline. Never replace that baseline or accept a content difference.
        baseline = json.loads((DESTINATION / 'app-before.json').read_text())
        canonical = {}
        for relative, digest in baseline.items():
            path = DESTINATION / 'original' / relative if relative in manifest else ROOT / relative
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError('Baseline content changed: ' + relative)
            canonical[relative] = hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()
        normalized.write_text(json.dumps(canonical, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
