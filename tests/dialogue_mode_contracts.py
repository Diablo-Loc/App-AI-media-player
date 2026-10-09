"""Restore only the opt-in dialogue additions before frozen music gates."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_dialogue_mode_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    source = current.decode("utf-8-sig").replace("\r\n", "\n")
    manifest = json.loads((ROOT / "tests/fixtures/dialogue_mode.json").read_text(encoding="utf-8"))
    if relative in manifest:
        entry = manifest[relative]
        digest = hashlib.sha256(source.encode()).hexdigest()
        if digest == entry["after_sha256"]:
            lines = source.splitlines(True)
            for edit in reversed(entry["edits"]):
                start = edit["after_start"]
                size = len(edit["after"].splitlines(True))
                if "".join(lines[start:start + size]) != edit["after"]:
                    raise AssertionError("Dialogue adapter changed: " + relative)
                lines[start:start + size] = edit["before"].splitlines(True)
            source = "".join(lines)
            if hashlib.sha256(source.encode()).hexdigest() != entry["before_sha256"]:
                raise AssertionError("Dialogue baseline changed: " + relative)
            current = source.encode()
        elif digest != entry["before_sha256"] and digest not in entry["allowed_older_sha256"]:
            raise AssertionError("Unreviewed dialogue change: " + relative)
    return current if raw else source
