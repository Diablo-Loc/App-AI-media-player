"""Restore only exact reviewed method adapters for the existing baseline gates."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def before_search_changes(path):
    from tests.reliability_contracts import before_reliability_changes
    source = before_reliability_changes(path)
    approved = json.loads((ROOT / 'docs/foryou-search/approved-adapters.json').read_text(encoding='utf-8'))[path]
    original = (ROOT / 'docs/foryou-search/original' / Path(path).name).read_text(encoding='utf-8-sig')
    original_nodes = {f'{c.name}.{n.name}': n for c in ast.parse(original).body
                      if isinstance(c, ast.ClassDef) for n in c.body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)
    nodes = [(f'{c.name}.{n.name}', n) for c in ast.parse(source).body if isinstance(c, ast.ClassDef)
             for n in c.body if isinstance(n, ast.FunctionDef)]
    for name, node in reversed(nodes):
        if name not in approved:
            continue
        expected = ast.parse(approved[name]).body[0]
        assert ast.dump(node, include_attributes=False) == ast.dump(expected, include_attributes=False), name
        old_text = ast.get_source_segment(original, original_nodes[name])
        lines[node.lineno-1:node.end_lineno] = ['    ' + old_text + '\n']
    return ''.join(lines)
