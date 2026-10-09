"""Peel the reviewed targeted-ASR phase before frozen historical gates."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_asr_targeted_recovery_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.asr_hallucination_guard_contracts import before_asr_hallucination_guard_changes
    current = before_asr_hallucination_guard_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / "docs/asr-targeted-recovery/reviewed-sources.json").read_text(
            encoding="utf-8"
        )
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/asr-targeted-recovery/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/asr-targeted-recovery/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("Targeted ASR reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed targeted ASR change: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("Targeted ASR baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
