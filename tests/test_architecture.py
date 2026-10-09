from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import ast
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureTests(unittest.TestCase):
    def test_all_sources_compile_and_use_canonical_internal_imports(self):
        app = ROOT / "app"
        local_names = {path.stem for path in app.iterdir() if path.is_dir() or path.suffix == ".py"}
        for path in app.rglob("*.py"):
            with self.subTest(path=str(path.relative_to(ROOT))):
                source = path.read_text(encoding="utf-8-sig")
                compile(source, str(path), "exec")
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
                        self.assertNotIn(node.module.split(".")[0], local_names)
                        if node.module.startswith("app."):
                            target = ROOT.joinpath(*node.module.split("."))
                            self.assertTrue(target.with_suffix(".py").exists() or target.is_dir(), node.module)

    def test_entry_import_does_not_load_qt_ai_or_change_environment(self):
        code = (
            "import sys,os;sys.path.insert(0," + repr(str(ROOT)) + ");"
            "env=dict(os.environ);hook=sys.excepthook;import app.run_app;"
            "assert env==dict(os.environ);assert hook is sys.excepthook;"
            "assert not any(n in sys.modules for n in ('PySide6','torch','transformers'))"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
