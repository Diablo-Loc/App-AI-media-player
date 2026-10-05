"""Restore the exact pre video-export source before historical phase gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_video_export_changes(relative, current=None, raw=False):
    """Validate the reviewed export edit, then expose the preceding source."""
    if current is None:
        current = (ROOT / relative).read_bytes()
    # The live sweep fade fix is restored by before_sweep_changes below.
    manifest = json.loads(
        (ROOT / 'docs/video-subtitle-export/reviewed-sources.json').read_text(encoding='utf-8')
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/video-subtitle-export/reviewed' / relative).read_bytes()
        original = (ROOT / 'docs/video-subtitle-export/original' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Video-export reviewed archive changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed video-export change: ' + relative)
        if hashlib.sha256(original).hexdigest() != entry['before_sha256']:
            raise AssertionError('Video-export baseline changed: ' + relative)
        current = original
    else:
        from tests.subtitle_sweep_contracts import before_sweep_changes
        current = before_sweep_changes(relative, raw=True)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
