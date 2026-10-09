"""Restore exact sources before verified-reference row binding."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_translation_reference_binding_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.online_translation_authority_contracts import (
        before_online_translation_authority_changes,
    )
    current = before_online_translation_authority_changes(
        relative, current=current, raw=True
    )
    manifest = json.loads(
        (ROOT / "docs/translation-reference-binding/reviewed-sources.json").read_text(
            encoding="utf-8"
        )
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (
            ROOT / "docs/translation-reference-binding/reviewed" / relative
        ).read_bytes()
        original = (
            ROOT / "docs/translation-reference-binding/original" / relative
        ).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Reference-binding reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed reference-binding source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Reference-binding baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
