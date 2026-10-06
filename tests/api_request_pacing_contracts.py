"""Restore exact pre request-pacing online source before historical gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_api_request_pacing_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.translation_reference_binding_contracts import (
        before_translation_reference_binding_changes,
    )
    current = before_translation_reference_binding_changes(
        relative, current=current, raw=True
    )
    from tests.lyric_clause_completeness_contracts import (
        before_lyric_clause_completeness_changes,
    )
    current = before_lyric_clause_completeness_changes(
        relative, current=current, raw=True
    )
    manifest = json.loads(
        (ROOT / "docs/api-request-pacing/reviewed-sources.json").read_text(encoding="utf-8")
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/api-request-pacing/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/api-request-pacing/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("API pacing reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed API pacing source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("API pacing baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
