"""Exact audio adapters and observed import compatibility before prior gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_audio_changes(relative, raw=False):
    from tests.audio_realtime_contracts import before_realtime_changes
    current = before_realtime_changes(relative, raw=True)
    manifest = json.loads((ROOT / 'docs/audio-effects/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
            raise AssertionError(f'Unreviewed change after audio phase: {relative}')
        current = (ROOT / 'docs/audio-effects/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError(f'Audio snapshot changed: {relative}')
    imports = {
        'app/ui/subs_ui/subtitle_layer.py': (b'from ui.subtitle_presentation import SubtitlePresentationGuard',
                                           b'from app.ui.subtitle_presentation import SubtitlePresentationGuard'),
        'app/ui/subtitle_presentation.py': (b'from subtitle.mode import SubtitleMode',
                                          b'from app.subtitle.mode import SubtitleMode'),
    }
    if relative in imports:
        original = (ROOT / 'docs/audio-effects/original' / relative).read_bytes()
        if current != original:
            raise AssertionError(f'Unreviewed change to pre-existing import correction: {relative}')
        source, destination = imports[relative]
        current = current.replace(source, destination, 1)
        if relative == 'app/ui/subs_ui/subtitle_layer.py':
            canonical = (ROOT / 'docs/audio-effects/import-compatibility' / relative).read_bytes()
            expected = 'ae21c5bad564969652f25e31dd069408db6a2ccf737da2026b02f66307ea8a0f'
            if hashlib.sha256(canonical).hexdigest() != expected:
                raise AssertionError('Prior reviewed presentation snapshot changed')
            if current.replace(b'\r\n', b'\n') != canonical.replace(b'\r\n', b'\n'):
                raise AssertionError('Import/line-ending compatibility exceeded its scope')
            current = canonical
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
