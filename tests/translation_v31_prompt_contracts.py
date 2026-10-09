"""Restore exact sources before the v3.1-style lyric prompt simplification."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_translation_v31_prompt_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.dialogue_mode_contracts import before_dialogue_mode_changes
    current = before_dialogue_mode_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / "docs/translation-v31-prompt/reviewed-sources.json").read_text(
            encoding="utf-8-sig"
        )
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/translation-v31-prompt/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/translation-v31-prompt/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("V3.1-prompt reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed v3.1-prompt source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("V3.1-prompt baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
