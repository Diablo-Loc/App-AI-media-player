"""Restore exact sources before single-pass online translation stabilization."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_translation_single_pass_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    manifest = json.loads(
        (ROOT / "docs/translation-single-pass/reviewed-sources.json").read_text(
            encoding="utf-8-sig"
        )
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/translation-single-pass/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/translation-single-pass/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Single-pass reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed single-pass source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Single-pass baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
