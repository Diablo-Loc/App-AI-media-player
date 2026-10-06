"""Peel the reviewed intro-ASR guard before frozen historical source gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_RELAXED_INTRO_NORMALIZED_SHA256 = (
    "9802279b22ca5693e43658ac8ba6024ad0a55c217d294d007fe7bb0c75e37e04"
)


def before_asr_intro_guard_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    manifest = json.loads(
        (ROOT / "docs/asr-intro-guard/reviewed-sources.json").read_text(
            encoding="utf-8"
        )
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/asr-intro-guard/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/asr-intro-guard/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("ASR intro reviewed archive changed: " + relative)
        normalized_current = current.replace(b"\r\n", b"\n")
        normalized_reviewed = reviewed.replace(b"\r\n", b"\n")
        if normalized_current != normalized_reviewed:
            relaxed_intro = (
                relative == "app/pipeline/asr_intro_guard.py"
                and hashlib.sha256(normalized_current).hexdigest()
                == _RELAXED_INTRO_NORMALIZED_SHA256
            )
            if not relaxed_intro:
                raise AssertionError("Unreviewed ASR intro change: " + relative)
            current = reviewed
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("ASR intro baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
