from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from app.bootstrap.application import create_main_window
    from app.bootstrap.runtime import configure_runtime
    from app.ui.main_window import MainWindow
except ImportError:
    UI_AVAILABLE = False
else:
    UI_AVAILABLE = True
    APPLICATION = QApplication.instance() or QApplication([])


@unittest.skipUnless(UI_AVAILABLE, "Full UI dependencies not installed for this Python")
class MainWindowSmokeTests(unittest.TestCase):
    def test_composition_and_appearance_settings_work_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            native = Mock(enabled=False)
            with patch("app.bootstrap.application.storage_dir", return_value=root), patch("app.ui.main_window.storage_dir", return_value=root), patch("app.ui.main_window.ConfigManager.get_last_folder", return_value=""), patch("app.ui.main_window.SystemMediaManager", return_value=native), patch("app.ui.pages.settings.QSettings", return_value=preferences), patch("app.ui.main_window.TempFileManager.TEMP_DIR", root / "temp"), patch("app.ui.main_window.psutil.Process") as process:
                process.return_value.children.return_value = []
                with patch("app.bootstrap.runtime.project_root", return_value=root):
                    configure_runtime()
                window = create_main_window()
                try:
                    self.assertIsInstance(window, MainWindow)
                    self.assertIs(window.app_controller.media_lib, window.media_library)
                    self.assertIs(window.app_controller.subtitle_mgr, window.subtitle_manager)
                    self.assertIs(window.app_controller.ai, window.job_manager)
                    window.appearance.set_font_size(29)
                    self.assertEqual(window.config["font_size"], 29)
                    self.assertEqual(window.settings_store.load_appearance()["font_size"], 29)
                    window.appearance.reset()
                    self.assertEqual(window.config["font_size"], 24)
                    window.sync_playlist_to_backend([])
                    self.assertEqual(window.app_controller.current_index, 0)
                    folder = root / "media"
                    folder.mkdir()
                    (folder / "first.mp4").write_bytes(b"synthetic")
                    (folder / "second.mp3").write_bytes(b"synthetic")
                    gui_thread = threading.get_ident()
                    probe_threads = []
                    def probe(path):
                        probe_threads.append(threading.get_ident())
                        return Path(path).stem, "Artist", 12.5
                    with patch("app.core.media_library.get_raw_metadata", side_effect=probe), patch("app.thumbnail.thumbnail_manager.ThumbnailManager.get_thumbnail", return_value=None):
                        window.load_folder_content(str(folder))
                        deadline = time.monotonic() + 5
                        while window.library_controller.worker is not None and time.monotonic() < deadline:
                            APPLICATION.processEvents()
                            time.sleep(0.001)
                        self.assertIsNone(window.library_controller.worker)
                        self.assertEqual({item.title for item in window.all_media_items}, {"first", "second"})
                        self.assertEqual(len(window.foryou_page.all_items_data), 2)
                        self.assertEqual(len(window.media_items), 2)
                        self.assertEqual(window.current_watched_folder, str(folder))
                        self.assertTrue(probe_threads)
                        self.assertNotIn(gui_thread, probe_threads)
                        window.app_controller.stop_thumbnail_scan()
                finally:
                    window.close()
                    window.deleteLater()
