from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import ConfigManager
from app.infrastructure.json_store import write_json_atomic
from app.infrastructure.settings_store import SettingsStore


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "settings.json"

    def test_unicode_write_and_sections_preserve_each_other(self):
        store = SettingsStore(self.path)
        store.save_section("download", {"quality": "High"})
        store.save_appearance({"font_color": "#FFFF00", "label": "日本語 / tiếng Việt"})
        store.save_section("download", {"quality": "Low"})
        data = store.load()
        self.assertEqual(data["appearance"]["label"], "日本語 / tiếng Việt")
        self.assertEqual(data["download"]["quality"], "Low")
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_failed_serialization_keeps_previous_file(self):
        write_json_atomic(self.path, {"saved": True})
        with self.assertRaises(TypeError):
            write_json_atomic(self.path, {"bad": object()})
        self.assertEqual(json.loads(self.path.read_text()), {"saved": True})
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_replace_failure_keeps_previous_file_and_cleans_temp(self):
        write_json_atomic(self.path, {"saved": True})
        with patch("app.infrastructure.json_store.os.replace", side_effect=PermissionError), patch("app.infrastructure.json_store.time.sleep"):
            with self.assertRaises(PermissionError):
                write_json_atomic(self.path, {"saved": False})
        self.assertEqual(json.loads(self.path.read_text()), {"saved": True})
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_legacy_flat_appearance_is_read(self):
        write_json_atomic(self.path, {"font_size": 30})
        self.assertEqual(SettingsStore(self.path).load_appearance(), {"font_size": 30})

    def test_concurrent_config_updates_keep_all_keys(self):
        with patch("app.config.CONFIG_FILE", str(self.path)):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i: ConfigManager.save_config({str(i): i}), range(12)))
            self.assertEqual(ConfigManager.get_config(), {str(i): i for i in range(12)})
