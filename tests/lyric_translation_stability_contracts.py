"""Restore exact pre translation-stability sources before historical gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_lyric_translation_stability_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    # Prompt-engineering tuning is newer than the stability phase. Peel it
    # before checking the frozen stability snapshot.
    from tests.lyric_prompt_engineering_contracts import before_lyric_prompt_engineering_changes
    current = before_lyric_prompt_engineering_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / "docs/lyric-translation-stability/reviewed-sources.json").read_text(encoding="utf-8")
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/lyric-translation-stability/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/lyric-translation-stability/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Lyric-translation stability reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed lyric-translation stability source: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Lyric-translation stability baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
