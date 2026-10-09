"""Read-only source audit. No application imports, model loading or bytecode writes."""

import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def audit():
    sources = []
    graph = {}
    paths = sorted((ROOT / "app").rglob("*.py"))
    modules = {p.relative_to(ROOT / "app").with_suffix("").as_posix().replace("/", "."): p.relative_to(ROOT).as_posix() for p in paths}
    for path in paths:
        raw = path.read_bytes()
        source = raw.decode("utf-8-sig")
        compile(source, str(path), "exec")
        tree = ast.parse(source)
        relative = path.relative_to(ROOT).as_posix()
        current_module = path.relative_to(ROOT / "app").with_suffix("").as_posix().replace("/", ".")
        imports = []
        import_candidates = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    package = current_module.split(".")[:-node.level]
                    module = ".".join(package + ([node.module] if node.module else []))
                    imports.append("." * node.level + (node.module or ""))
                else:
                    module = node.module or ""
                    imports.append(module)
                import_candidates.append(module)
                import_candidates.extend(module + "." + alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
                import_candidates.extend(alias.name for alias in node.names)
        edges = set()
        for module in import_candidates:
            candidate = module.removeprefix("app.")
            if candidate in modules:
                edges.add(modules[candidate])
        graph[relative] = sorted(edges)
        functions = []
        def visit(scope, prefix=""):
            for node in getattr(scope, "body", []):
                if isinstance(node, ast.ClassDef):
                    visit(node, prefix + node.name + ".")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append({
                        "name": prefix + node.name, "line": node.lineno,
                        "lines": node.end_lineno - node.lineno + 1,
                        "calls": sorted({ast.unparse(call.func) for call in ast.walk(node) if isinstance(call, ast.Call)}),
                    })
        visit(tree)
        sources.append({"path": relative, "lines": len(source.splitlines()), "sha256": hashlib.sha256(raw).hexdigest(), "imports": sorted(set(imports)), "functions": functions})
    reachable = set()
    def follow(path):
        if path in reachable:
            return
        reachable.add(path)
        for dependency in graph.get(path, []):
            follow(dependency)
    follow("app/run_app.py")
    tree_files = [{"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size} for p in sorted((ROOT / "app").rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    diff = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "app"], cwd=ROOT)
    return {"audit_date": "2026-10-03", "git_revision": revision, "tracked_app_matches_head": diff.returncode == 0, "python_files": len(sources), "python_lines": sum(row["lines"] for row in sources), "scope": "Source syntax/hash/import/call analysis only. Static reachability is not proof of runtime execution or dead code. Binary/log/data files inventoried, not executed.", "sources": sources, "import_graph": graph, "statically_reachable_from_entry": sorted(reachable), "other_sources": sorted(set(graph) - reachable), "tree_files": tree_files}


def main():
    result = audit()
    target = ROOT / "docs" / "restored-app-baseline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    groups = defaultdict(lambda: [0, 0])
    for row in result["sources"]:
        group = str(Path(row["path"]).parent).replace("\\", "/")
        groups[group][0] += 1
        groups[group][1] += row["lines"]
    print(f"Parsed/compiled {result['python_files']} Python files; {result['python_lines']} lines.")
    print(f"Tracked app matches HEAD: {result['tracked_app_matches_head']}")
    for group, (count, lines) in sorted(groups.items()):
        print(f"{group}: {count} files, {lines} lines")
    print("Outside static entry import graph:")
    print("\n".join(result["other_sources"]))


if __name__ == "__main__":
    main()
