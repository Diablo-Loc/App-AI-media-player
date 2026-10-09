from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import os
from queue import Empty
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication, QDialog
    from app.control.ai_controller import AIController, _RESOURCE_CHECK_CACHE
    from app.ui.media_player import MediaPlayer
    from app.worker import AIWorker
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    APPLICATION = QApplication.instance() or QApplication([])

    class FakeWorker(QObject):
        started = Signal(str)
        progress = Signal(int, str)
        data_ready = Signal(str, list)
        failed = Signal(str, str)
        finished = Signal()

        def __init__(self, media_id="id", **kwargs):
            super().__init__()
            self.media_id = media_id
            self.running = False
            self.cancelled = False
            self.deleted = False

        def start(self):
            self.running = True
            self.started.emit(self.media_id)

        def isRunning(self):
            return self.running

        def stop(self):
            self.running = False

        def cancel(self):
            self.cancelled = True

        def deleteLater(self):
            self.deleted = True


@unittest.skipUnless(QT_AVAILABLE, "PySide6 not installed")
class WorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.worker = AIWorker("id", "input.mp4", "output")
        self.context = Mock()
        self.queue = self.context.Queue.return_value
        self.process = self.context.Process.return_value
        self.process.is_alive.return_value = False
        self.results, self.errors = [], []
        self.worker.data_ready.connect(lambda media_id, segments: self.results.append((media_id, segments)))
        self.worker.failed.connect(lambda media_id, error: self.errors.append(error))

    def run_worker(self):
        with patch("app.worker.multiprocessing.get_context", return_value=self.context) as context:
            self.worker.run()
            context.assert_called_once_with("spawn")

    def assert_cleaned(self):
        self.queue.close.assert_called_once()
        self.queue.join_thread.assert_called_once()
        self.assertIsNone(self.worker._process)
        self.assertIsNone(self.worker._queue)

    def test_finished_message_is_consumed_even_after_child_exits(self):
        self.queue.get.return_value = ("finished", {"segments": [{"text": "done"}]})
        self.run_worker()
        self.assertEqual(self.results, [("id", [{"text": "done"}])])
        self.assertEqual(self.errors, [])
        self.assert_cleaned()

    def test_process_start_failure_always_cleans_queue(self):
        self.process.start.side_effect = OSError("cannot spawn")
        self.run_worker()
        self.assertIn("cannot spawn", self.errors[0])
        self.assert_cleaned()

    def test_queue_failure_always_cleans_process(self):
        self.queue.get.side_effect = RuntimeError("broken queue")
        self.run_worker()
        self.assertIn("broken queue", self.errors[0])
        self.process.join.assert_called()
        self.assert_cleaned()

    def test_unexpected_child_exit_is_reported(self):
        self.queue.get.side_effect = Empty
        self.run_worker()
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.results, [])
        self.assert_cleaned()

    def test_cancellation_does_not_deliver_late_result(self):
        def cancel_then_return(**kwargs):
            self.worker.cancel()
            return ("finished", {"segments": [{"text": "late"}]})
        self.queue.get.side_effect = cancel_then_return
        self.run_worker()
        self.context.Event.return_value.set.assert_called_once()
        self.assertEqual(self.results, [])
        self.assert_cleaned()

    def test_cancel_before_start_does_not_spawn(self):
        self.worker.stop()
        with patch("app.worker.multiprocessing.get_context") as context:
            self.worker.run()
        context.assert_not_called()

    def test_unresponsive_child_is_killed_after_terminate(self):
        self.worker._process = self.process
        self.worker._queue = self.queue
        self.process.is_alive.return_value = True
        self.worker._cleanup_process()
        self.process.terminate.assert_called_once()
        self.process.kill.assert_called_once()
        self.assert_cleaned()

    def test_real_spawn_round_trip_serializes_canonical_subtitle_model(self):
        from tests.spawn_helpers import return_subtitle
        from app.subtitle.model import Subtitle

        with patch("app.worker._ai_process_wrapper", return_subtitle):
            self.worker.run()
        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.results), 1)
        self.assertIsInstance(self.results[0][1][0], Subtitle)
        self.assertEqual(self.results[0][1][0].top.text, "hello")
        self.assertIsNone(self.worker._process)
        self.assertIsNone(self.worker._queue)


@unittest.skipUnless(QT_AVAILABLE, "PySide6 not installed")
class ControllerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.cache = patch.dict(_RESOURCE_CHECK_CACHE, {"checked": True, "ready": True})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.factory = patch("app.control.ai_controller.AIWorker", FakeWorker)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.controller = AIController("output")

    def test_old_thread_finished_cannot_clear_new_worker(self):
        self.controller.start("id", "first.mp4")
        old = self.controller._worker
        newer = FakeWorker("id")
        self.controller._worker = newer
        old.finished.emit()
        self.assertIs(self.controller._worker, newer)
        self.assertTrue(old.deleted)

    def test_old_worker_result_for_same_media_id_is_ignored(self):
        self.controller.start("id", "first.mp4")
        old = self.controller._worker
        self.controller._worker = FakeWorker("id")
        received = []
        self.controller.job_finished.connect(lambda *args: received.append(args))
        old.data_ready.emit("id", [{"text": "stale"}])
        self.assertEqual(received, [])

    def test_cancel_invalidates_pending_result(self):
        self.controller.start("id", "first.mp4")
        worker = self.controller._worker
        received = []
        self.controller.job_finished.connect(lambda *args: received.append(args))
        self.controller.cancel()
        worker.data_ready.emit("id", [{"text": "stale"}])
        self.assertTrue(worker.cancelled)
        self.assertEqual(received, [])

    def test_successful_resource_install_refreshes_controller_cache(self):
        _RESOURCE_CHECK_CACHE.update(checked=False, ready=False)
        with patch("app.download_core.download_source_app.check_resource_status", side_effect=[{"ready": False}, {"ready": True}]), patch("app.download_core.download_source_app._get_resource_ready_flag", return_value=False), patch("app.download_core.download_source_app._set_resource_ready_flag"), patch("app.download_core.download_source_app.ResourceDownloadDialog") as dialog, patch("app.control.ai_controller.QMessageBox.warning"):
            dialog.return_value.exec.return_value = QDialog.Accepted
            self.controller.start("id", "input.mp4")
        self.assertTrue(self.controller._resource_ready)
        self.assertTrue(_RESOURCE_CHECK_CACHE["ready"])
        self.assertTrue(self.controller.is_running())


@unittest.skipUnless(QT_AVAILABLE, "PySide6 not installed")
class MediaPlayerSmokeTests(unittest.TestCase):
    def test_embeddable_player_has_video_output_and_forwards_position(self):
        widget = MediaPlayer()
        self.addCleanup(widget.deleteLater)
        self.assertIs(widget.player.videoOutput(), widget.video_widget)
        self.assertEqual(widget.layout().count(), 1)
        positions = []
        widget.positionChanged.connect(positions.append)
        widget.player.positionChanged.emit(1200)
        self.assertEqual(positions, [1200])
