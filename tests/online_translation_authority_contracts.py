"""Restore exact sources before online-model authority/repair-pass changes."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_online_translation_authority_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.translation_semantic_review_contracts import (
        before_translation_semantic_review_changes,
    )
    current = before_translation_semantic_review_changes(
        relative, current=current, raw=True
    )
    manifest = json.loads(
        (ROOT / "docs/online-translation-authority/reviewed-sources.json").read_text(
            encoding="utf-8"
        )
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (
            ROOT / "docs/online-translation-authority/reviewed" / relative
        ).read_bytes()
        original = (
            ROOT / "docs/online-translation-authority/original" / relative
        ).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Online-authority reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed online-authority source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Online-authority baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
