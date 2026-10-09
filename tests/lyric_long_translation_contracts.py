"""Restore exact pre long-lyric batching sources before historical gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_lyric_long_translation_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.api_request_pacing_contracts import before_api_request_pacing_changes
    current = before_api_request_pacing_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / "docs/lyric-long-translation/reviewed-sources.json").read_text(encoding="utf-8")
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/lyric-long-translation/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/lyric-long-translation/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Long-lyric reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed long-lyric source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Long-lyric baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
