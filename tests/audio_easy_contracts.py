"""Restore only exactly reviewed easy-listening additions for prior gates."""
import hashlib
import json
from pathlib import Path
from tests.media_info_contracts import before_media_info_changes

ROOT = Path(__file__).resolve().parents[1]


def before_easy_changes(relative, raw=False):
    current = before_media_info_changes(relative, raw=True)
    # Existing tracked Windows files may contain mixed endings, whereas Git
    # stores LF and checks out CRLF. Accept ONLY newline-equivalent full bytes,
    # then restore the exact reviewed bytes expected by the frozen old gates.
    checkout = json.loads((ROOT / 'docs/audio-easy/checkout-sources.json').read_text(encoding='utf-8'))
    if relative in checkout:
        captured = (ROOT / 'docs/audio-easy/checkout-source' / relative).read_bytes()
        if hashlib.sha256(captured).hexdigest() != checkout[relative]:
            raise AssertionError('Checkout compatibility snapshot changed: ' + relative)
        if current.replace(b'\r\n', b'\n') != captured.replace(b'\r\n', b'\n'):
            raise AssertionError('Checkout compatibility exceeded newline-only scope: ' + relative)
        current = captured
    manifest = json.loads((ROOT / 'docs/audio-easy/reviewed-sources.json').read_text(encoding='utf-8'))
    if relative in manifest:
        entry = manifest[relative]
        if hashlib.sha256(current).hexdigest() != entry['after_sha256']:
            raise AssertionError('Unreviewed easy-listening changes: ' + relative)
        current = (ROOT / 'docs/audio-easy/original' / relative).read_bytes()
        if hashlib.sha256(current).hexdigest() != entry['before_sha256']:
            raise AssertionError('Easy-listening snapshot changed: ' + relative)
    return current if raw else current.decode('utf-8-sig').replace('\r\n', '\n')
