"""Peel the current tail-only adjustment before frozen timing source gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_display_tail_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    source = current.decode("utf-8-sig").replace("\r\n", "\n")
    manifest = json.loads((ROOT / "tests/fixtures/subtitle_display_tail.json").read_text(encoding="utf-8"))
    if relative in manifest:
        entry = manifest[relative]
        digest = hashlib.sha256(source.encode()).hexdigest()
        if digest == entry["after_sha256"]:
            for edit in reversed(entry["edits"]):
                if source.count(edit["after"]) != 1:
                    raise AssertionError("Tail adapter changed: " + relative)
                source = source.replace(edit["after"], edit["before"], 1)
            if hashlib.sha256(source.encode()).hexdigest() != entry["before_sha256"]:
                raise AssertionError("Tail baseline changed: " + relative)
            current = source.encode()
        elif digest != entry["before_sha256"] and digest not in entry["allowed_older_sha256"]:
            raise AssertionError("Unreviewed display tail change: " + relative)
    return current if raw else source
