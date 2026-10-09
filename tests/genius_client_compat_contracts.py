"""Restore the exact pre LyricsGenius-constructor compatibility source."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_genius_client_compat_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.genius_referents_fallback_contracts import before_genius_referents_fallback_changes
    current = before_genius_referents_fallback_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / "docs/genius-client-compat/reviewed-sources.json").read_text(encoding="utf-8")
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/genius-client-compat/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/genius-client-compat/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Genius-client reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed Genius-client source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Genius-client baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
