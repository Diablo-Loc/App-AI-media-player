"""Fetch the reviewed Lucide SVG subset; never called by the application."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
import hashlib
import json

REVISION = "500620a2e8123f8d1db191538886dc0c223f69a9"
NAMES = "house music library download settings menu folder-open search play pause skip-back skip-forward shuffle repeat info captions refresh-cw volume-x volume-1 volume-2 picture-in-picture-2 maximize minimize disc-3 save rotate-ccw trash square user circle-check chevron-down plus clipboard upload undo redo eye-off x languages sparkles".split()
DESTINATION = Path(__file__).resolve().parents[1] / "app/ui/assets/icons"
BASE = f"https://raw.githubusercontent.com/lucide-icons/lucide/{REVISION}"


def fetch(name):
    try:
        with urlopen(f"{BASE}/icons/{name}.svg", timeout=30) as response:
            data = response.read()
    except Exception as exc:
        raise RuntimeError(f"Cannot fetch icon {name}: {exc}") from exc
    if b"<svg" not in data or b"<script" in data:
        raise ValueError(name)
    (DESTINATION / f"{name}.svg").write_bytes(data)
    return name, hashlib.sha256(data).hexdigest()


if __name__ == "__main__":
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with urlopen(f"{BASE}/LICENSE", timeout=30) as response:
        (DESTINATION / "LICENSE").write_bytes(response.read())
    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes = dict(pool.map(fetch, NAMES))
    (DESTINATION / "manifest.json").write_text(json.dumps({
        "source": "https://github.com/lucide-icons/lucide", "revision": REVISION,
        "license": "ISC; inherited Feather icons also MIT (see LICENSE)",
        "sha256": hashes,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Vendored {len(hashes)} icons at {REVISION}")
