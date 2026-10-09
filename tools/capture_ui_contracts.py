"""Capture Qt signal wiring and function contracts from the ORIGINAL revision.

This is our own baseline source, not executable network content. AST fingerprints
supplement actual widget tests; they do not prove GPU/media/native parity.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "4148c138c1e38f4959574caf925f1c86dbcca339"


def fingerprint(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def contracts(source):
    tree = ast.parse(source)
    methods, signals, connections = {}, {}, []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            methods[node.name] = {"body": fingerprint(node), "args": fingerprint(node.args)}
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    methods[f"{node.name}.{child.name}"] = {"body": fingerprint(child), "args": fingerprint(child.args)}
                if isinstance(child, ast.Assign) and isinstance(child.value, ast.Call) and ast.unparse(child.value.func) == "Signal":
                    signals[f"{node.name}.{ast.unparse(child.targets[0])}"] = fingerprint(child)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connect":
            connections.append(fingerprint(node))
    return {"methods": methods, "signals": signals, "connections": sorted(connections)}


if __name__ == "__main__":
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", REVISION, "--", "app/ui"], cwd=ROOT).decode().splitlines()
    result = {"revision": REVISION, "scope": "Original UI source contracts; identical fingerprints mean identical AST, not full runtime parity.", "files": {}}
    for name in names:
        if name.endswith(".py"):
            source = subprocess.check_output(["git", "show", f"{REVISION}:{name}"], cwd=ROOT).decode("utf-8-sig")
            result["files"][name] = contracts(source)
    path = ROOT / "docs/ui/original-contracts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise SystemExit("Original contract fixture already exists; preserve it.")
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Captured original contracts from {len(result['files'])} UI files")
