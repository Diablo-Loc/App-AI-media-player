"""Exact resource-phase restoration before all historical contract gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_resource_changes(relative, raw=False):
    # Lyric-translation shaping is newer than the resource/playback phases.
    # Validate and peel it before passing source through historical adapters.
    from tests.lyric_translation_contracts import before_lyric_translation_changes
    current = before_lyric_translation_changes(relative, raw=True)
    # Playback-continuity is newer than the export/resource phases. Validate
    # and peel it first, then pass those bytes through the existing adapter
    # chain so historical manifests stay frozen.
    from tests.playback_continuity_contracts import before_playback_continuity_changes
    current = before_playback_continuity_changes(relative, current=current, raw=True)
    from tests.video_export_contracts import before_video_export_changes
    current = before_video_export_changes(relative, current=current, raw=True)
    manifest = json.loads((ROOT / 'docs/resource-performance/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / 'docs/resource-performance/reviewed' / relative).read_bytes()
        original = (ROOT / 'docs/resource-performance/original' / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry['after_sha256']:
            raise AssertionError('Resource archive changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != reviewed.replace(b'\r\n', b'\n'):
            raise AssertionError('Unreviewed resource change: ' + relative)
        if hashlib.sha256(original).hexdigest() != entry['before_sha256']:
            raise AssertionError('Resource baseline changed: ' + relative)
        current = original
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
