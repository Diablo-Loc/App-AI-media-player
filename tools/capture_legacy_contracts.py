"""Freeze selected original behavior for differential compatibility tests."""

import ast
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "4148c13"
CONTRACTS = {
    "navigate": ("app/ui/main_window.py", "MainWindow", "_navigate_active_playlist"),
    "scan": ("app/core/media_library.py", "MediaLibrary", "scan_folder"),
    "clean_segment": ("app/core/subtitle_manager.py", "SubtitleManager", "_clean_segment"),
    "raw_metadata": ("app/core/media_library.py", None, "get_raw_metadata"),
}


def main():
    contracts = {}
    for name, (path, class_name, method) in CONTRACTS.items():
        source = subprocess.check_output(
            ["git", "show", f"{REVISION}:{path}"], cwd=ROOT,
        ).decode("utf-8-sig")
        tree = ast.parse(source)
        scope = tree if class_name is None else next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        node = next(node for node in scope.body if isinstance(node, ast.FunctionDef) and node.name == method)
        contracts[name] = {"path": path, "source": ast.unparse(node)}
    target = ROOT / "tests" / "fixtures" / "legacy_contracts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"revision": REVISION, "contracts": contracts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Captured {len(contracts)} contracts from {REVISION}.")


if __name__ == "__main__":
    main()
