from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.bootstrap.runtime import configure_runtime
from app.paths import asset_dir, project_root, resources_dir


class RuntimePathTests(unittest.TestCase):
    def test_frozen_assets_and_writable_models_have_different_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "_internal"
            bundle.mkdir()
            (bundle / "icon.ico").touch()
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(root / "BoTube.exe")), patch.object(sys, "_MEIPASS", str(bundle), create=True):
                self.assertEqual(project_root(), root)
                self.assertEqual(resources_dir(), root / "app_resources")
                self.assertEqual(asset_dir("icon.ico"), bundle / "icon.ico")
                self.assertEqual(asset_dir("external.dll"), root / "external.dll")

    def test_runtime_paths_are_not_duplicated_on_repeated_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            (root / "app_resources" / "libs").mkdir(parents=True)
            with patch("app.bootstrap.runtime.project_root", return_value=root), patch("app.bootstrap.runtime.multiprocessing.freeze_support"), patch.dict(os.environ, {"PATH": "existing", "PYTHONPATH": ""}), patch.object(sys, "path", list(sys.path)):
                configure_runtime()
                configure_runtime()
                self.assertEqual(os.environ["PATH"].split(os.pathsep).count(str(root / "bin")), 1)
                self.assertEqual(sys.path.count(str(root / "app_resources" / "libs")), 1)

    def test_frozen_spawn_prepares_portable_paths_before_freeze_support(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            libraries = root / "app_resources" / "libs"
            libraries.mkdir(parents=True)
            def child_bootstrap():
                self.assertIn(str(libraries), sys.path)
                self.assertIn(str(libraries), os.environ["PYTHONPATH"].split(os.pathsep))
            with patch("app.bootstrap.runtime.project_root", return_value=root), patch("app.bootstrap.runtime.multiprocessing.freeze_support", side_effect=child_bootstrap), patch.dict(os.environ), patch.object(sys, "path", list(sys.path)):
                configure_runtime()
