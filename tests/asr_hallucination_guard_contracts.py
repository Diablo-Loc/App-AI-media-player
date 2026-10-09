"""Peel the reviewed primary-ASR hallucination guard before older phases."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def before_asr_hallucination_guard_changes(relative, current=None, raw=False):
    if current is None:
        current = (ROOT / relative).read_bytes()
    from tests.asr_credit_meta_guard_contracts import before_asr_credit_meta_guard_changes
    current = before_asr_credit_meta_guard_changes(relative, current=current, raw=True)
    manifest = json.loads(
        (ROOT / "docs/asr-hallucination-guard/reviewed-sources.json").read_text(
            encoding="utf-8"
        )
    )
    if relative in manifest:
        entry = manifest[relative]
        reviewed = (ROOT / "docs/asr-hallucination-guard/reviewed" / relative).read_bytes()
        original = (ROOT / "docs/asr-hallucination-guard/original" / relative).read_bytes()
        if hashlib.sha256(reviewed).hexdigest() != entry["after_sha256"]:
            raise AssertionError("ASR hallucination reviewed archive changed: " + relative)
        if current.replace(b"\r\n", b"\n") != reviewed.replace(b"\r\n", b"\n"):
            raise AssertionError("Unreviewed ASR hallucination change: " + relative)
        if hashlib.sha256(original).hexdigest() != entry["before_sha256"]:
            raise AssertionError("ASR hallucination baseline changed: " + relative)
        current = original
    return current if raw else current.decode("utf-8-sig").replace("\r\n", "\n")
