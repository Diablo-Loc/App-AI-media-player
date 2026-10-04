"""Static local-import inventory for the existing direct app/run_app.py entry."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'


def scan():
    sources = sorted(APP.rglob('*.py'))
    local_roots = {p.relative_to(APP).parts[0].split('.')[0] for p in sources}
    records, graph, issues = [], {}, []
    for source in sources:
        relative = source.relative_to(APP)
        module = '.'.join(relative.with_suffix('').parts)
        if module.endswith('.__init__'):
            module = module[:-9]
        package = list(relative.parent.parts)
        imports = []
        for node in ast.walk(ast.parse(source.read_text(encoding='utf-8-sig'))):
            targets = []
            if isinstance(node, ast.Import):
                targets = [(alias.name, []) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                name = node.module or ''
                if node.level:
                    if node.level > len(package):
                        issues.append(dict(file=source.relative_to(ROOT).as_posix(), line=node.lineno,
                                           issue='relative import without a direct-entry package'))
                        # Still inspect its target to expose missing legacy API.
                        name = node.module or ''
                    else:
                        parent = package[:len(package)-node.level+1]
                        name = '.'.join(parent + ([name] if name else []))
                targets = [(name, [alias.name for alias in node.names])]
            for target_name, names in targets:
                if not target_name:
                    continue
                qualified_app = target_name.startswith('app.')
                if qualified_app:
                    if source.name != 'test_build_app.py':
                        issues.append(dict(file=source.relative_to(ROOT).as_posix(), line=node.lineno,
                                           issue='app.* requires repository root absent in direct entry'))
                    target_name = target_name[4:]
                if target_name.split('.')[0] not in local_roots:
                    continue
                target = APP.joinpath(*target_name.split('.'))
                target_file = target.with_suffix('.py')
                record = dict(file=source.relative_to(ROOT).as_posix(), line=node.lineno,
                              module=target_name, names=names, qualified_app=qualified_app)
                records.append(record)
                imports.append(target_name)
                if not target_file.is_file() and not target.is_dir():
                    issues.append(dict(file=record['file'], line=node.lineno,
                                       issue='local module missing: '+target_name))
                elif target_file.is_file() and names:
                    tree = ast.parse(target_file.read_text(encoding='utf-8-sig'))
                    exports = set()
                    for statement in tree.body:
                        if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                            exports.add(statement.name)
                        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                            exports.update(a.asname or a.name.split('.')[0] for a in statement.names)
                        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                            for item in ast.walk(statement):
                                if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                                    exports.add(item.id)
                    for name in names:
                        if name != '*' and name not in exports:
                            issues.append(dict(file=record['file'], line=node.lineno,
                                               issue='local attribute needs review: '+target_name+'.'+name))
                elif target.is_dir():
                    imports.extend(target_name+'.'+name for name in names
                                   if (target/(name+'.py')).is_file())
        graph[module] = imports
    reachable, pending = set(), ['run_app']
    while pending:
        module = pending.pop()
        if module not in reachable:
            reachable.add(module)
            pending.extend(graph.get(module, []))
    runtime_issues = [issue for issue in issues if '.'.join(
        Path(issue['file']).relative_to('app').with_suffix('').parts) in reachable]
    return dict(source_count=len(sources), local_import_count=len(records),
                local_imports=records, issues=issues,
                runtime_reachable_modules=sorted(reachable), runtime_issues=runtime_issues,
                limitation='Static local names only; optional external dependencies/dynamic targets need actual execution.')


if __name__ == '__main__':
    destination = ROOT/'docs/runtime-imports/import-inventory.json'
    result = scan()
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k,v in result.items() if k not in ('local_imports','runtime_reachable_modules')}))
