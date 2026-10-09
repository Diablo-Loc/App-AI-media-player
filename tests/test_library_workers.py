from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QTimer, QObject, Signal
    from PySide6.QtWidgets import QApplication
    from app.control.library_controller import LibraryController
    from app.control.app_controller import AppController
    from app.core.media_library import MediaLibrary
    from app.media.models import MediaMetadata
    from app.thumbnail.thumbnail_workers import ThumbnailWorker
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    APPLICATION = QApplication.instance() or QApplication([])


def pump_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APPLICATION.processEvents()
        time.sleep(0.001)
    if not predicate():
        raise AssertionError("Timed out waiting for Qt worker")


class SlowLibrary:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.thread_ids = []
        self.calls = []
        self.active = 0
        self.max_active = 0

    def scan_folder(self, folder, *, cancel_cb):
        self.thread_ids.append(threading.get_ident())
        self.calls.append(folder)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.entered.set()
        try:
            while not self.release.wait(0.002):
                if cancel_cb():
                    return [f"stale:{folder}"]
            if folder == "error":
                raise OSError("unreadable folder")
            return [folder]
        finally:
            self.active -= 1


@unittest.skipUnless(QT_AVAILABLE, "PySide6 not installed")
class LibraryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.library = SlowLibrary()
        self.controller = LibraryController(self.library)
        self.addCleanup(self.controller.shutdown)
        self.results, self.errors = [], []
        self.controller.scan_completed.connect(lambda folder, items: self.results.append((folder, items)))
        self.controller.scan_failed.connect(lambda folder, error: self.errors.append((folder, error)))

    def test_scan_keeps_gui_timer_alive_and_runs_on_another_thread(self):
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(1)
        self.addCleanup(timer.stop)
        self.controller.request_scan("folder")
        pump_until(lambda: self.library.entered.is_set() and len(ticks) >= 3)
        self.assertEqual(self.results, [])
        self.assertNotEqual(self.library.thread_ids[0], threading.get_ident())
        self.library.release.set()
        pump_until(lambda: bool(self.results))
        self.assertEqual(self.results, [("folder", ["folder"])])

    def test_only_latest_request_is_published_and_scans_are_serial(self):
        self.controller.request_scan("old")
        pump_until(self.library.entered.is_set)
        self.controller.request_scan("middle")
        self.controller.request_scan("latest")
        pump_until(lambda: "latest" in self.library.calls)
        self.library.release.set()
        pump_until(lambda: bool(self.results))
        self.assertEqual(self.results, [("latest", ["latest"])])
        self.assertEqual(self.library.calls, ["old", "latest"])
        self.assertEqual(self.library.max_active, 1)

    def test_shutdown_cancels_owned_thread_and_rejects_later_requests(self):
        self.controller.request_scan("old")
        pump_until(self.library.entered.is_set)
        self.controller.shutdown()
        APPLICATION.processEvents()
        self.controller.request_scan("new")
        self.assertIsNone(self.controller.worker)
        self.assertEqual(self.library.active, 0)
        self.assertEqual(self.results, [])
        self.assertEqual(self.library.calls, ["old"])

    def test_scan_failure_is_reported_and_a_new_scan_can_succeed(self):
        self.library.release.set()
        self.controller.request_scan("error")
        pump_until(lambda: bool(self.errors))
        self.assertEqual(self.errors, [("error", "unreadable folder")])
        self.controller.request_scan("ok")
        pump_until(lambda: bool(self.results))
        self.assertEqual(self.results, [("ok", ["ok"])])

    def test_thumbnail_worker_flushes_partial_batch_on_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            library = MediaLibrary(Path(directory) / "library.json")
            library.items = {str(i): MediaMetadata(str(i), f"{i}.mp4", f"Song {i}") for i in range(3)}
            worker = ThumbnailWorker(library)
            def thumbnail(item):
                worker.stop(wait=False)
                return f"{item.id}.jpg"
            with patch("app.thumbnail.thumbnail_workers.ThumbnailManager.get_thumbnail", side_effect=thumbnail), patch.object(library, "save", wraps=library.save) as save:
                worker.run()
                self.assertEqual(save.call_count, 1)
            self.assertEqual(MediaLibrary(library.db_path).items["0"].thumbnail, "0.jpg")
            self.assertIsNone(library.items["1"].thumbnail)

    def test_thumbnail_restart_never_waits_and_shutdown_prevents_restart(self):
        class FakeWorker(QObject):
            finished = Signal()
            thumbnail_ready = Signal(str, str)
            def __init__(self, library):
                super().__init__()
                self.stop = Mock()
                self.wait = Mock()
                self.start = Mock()
        ai = Mock()
        window = SimpleNamespace(media_player=SimpleNamespace(player=Mock()))
        library = Mock()
        library.snapshot_items.return_value = [object()]
        controller = AppController(window, library, ai, Mock())
        with patch("app.control.app_controller.ThumbnailWorker", FakeWorker):
            controller.start_thumbnail_scan()
            first = controller.thumb_worker
            controller.start_thumbnail_scan()
            first.stop.assert_called_once_with(wait=False)
            first.wait.assert_not_called()
            self.assertIs(controller.thumb_worker, first)
            first.finished.emit()
            second = controller.thumb_worker
            self.assertIsNot(first, second)
            controller.start_thumbnail_scan()
            controller.stop_thumbnail_scan(closing=True)
            second.finished.emit()
            self.assertIsNone(controller.thumb_worker)

    def test_thumbnail_worker_flushes_completed_items_if_manager_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            library = MediaLibrary(Path(directory) / "library.json")
            library.items = {str(i): MediaMetadata(str(i), f"{i}.mp4", f"Song {i}") for i in range(2)}
            worker = ThumbnailWorker(library)
            with patch("app.thumbnail.thumbnail_workers.ThumbnailManager.get_thumbnail", side_effect=["0.jpg", OSError("image failure")]):
                with self.assertRaisesRegex(OSError, "image failure"):
                    worker.run()
            self.assertEqual(MediaLibrary(library.db_path).items["0"].thumbnail, "0.jpg")
