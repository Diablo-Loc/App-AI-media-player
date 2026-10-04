"""Inspect every Python source under app without importing optional AI libraries."""

import ast
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def inspect_app():
    rows = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        imports = sorted({
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name for node in ast.walk(tree)
            if isinstance(node, ast.Import) for alias in node.names
        })
        rows.append({
            "path": path.relative_to(ROOT).as_posix(),
            "lines": len(source.splitlines()),
            "classes": [node.name for node in tree.body if isinstance(node, ast.ClassDef)],
            "functions": [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))],
            "imports": imports,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="Write a UTF-8 inventory JSON")
    args = parser.parse_args()
    rows = inspect_app()
    if args.output:
        files = [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size}
            for path in sorted((ROOT / "app").rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"python_files": len(rows), "python_lines": sum(row["lines"] for row in rows), "sources": rows, "tree_files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Parsed {len(rows)} Python files; {sum(row['lines'] for row in rows)} lines.")
    for row in rows:
        symbols = ", ".join(row["classes"] + row["functions"]) or "-"
        print(f"| `{row['path']}` | {row['lines']} | {symbols} |")


if __name__ == "__main__":
    main()
