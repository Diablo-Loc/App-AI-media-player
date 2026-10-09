"""Restore exact pre referents-fallback sources before historical gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_genius_referents_fallback_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    # Translation-stability tuning is newer than Genius referents fallback.
    # Peel it first so this historical manifest remains frozen.
    from tests.lyric_translation_stability_contracts import before_lyric_translation_stability_changes
    current = before_lyric_translation_stability_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / "docs/genius-referents-fallback/reviewed-sources.json").read_text(encoding="utf-8")
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/genius-referents-fallback/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/genius-referents-fallback/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Genius referents reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed Genius referents source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Genius referents baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
