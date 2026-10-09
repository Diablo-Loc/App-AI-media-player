"""Keep Qt workers alive to finished and cancel only their owned processes."""
import subprocess
import threading
from PySide6.QtCore import QObject, Slot


def _stop_process(process):
    if process.poll() is not None:
        return
    try:
        import psutil
        for child in reversed(psutil.Process(process.pid).children(recursive=True)):
            try:
                child.terminate()
            except psutil.Error:
                pass
    except Exception:
        pass
    try:
        process.terminate()
    except OSError:
        pass


class OwnedProcesses:
    def __init__(self):
        self.processes = set()
        self.lock = threading.Lock()
        self.stopped = False

    def track(self, process):
        with self.lock:
            self.processes.add(process)
            stopped = self.stopped
        if stopped:
            _stop_process(process)
        return process

    def release(self, process):
        with self.lock:
            self.processes.discard(process)

    def stop(self):
        with self.lock:
            self.stopped = True
            processes = tuple(self.processes)
        for process in processes:
            _stop_process(process)

    def wait(self):
        # Worker/shutdown only, never used by a normal-interaction GUI handler.
        with self.lock:
            processes = tuple(self.processes)
        for process in processes:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            self.release(process)


class WorkerOwner(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.workers = set()
        self.closed = False

    def own(self, worker):
        if self.closed:
            raise RuntimeError('Worker owner already shut down')
        worker.setParent(self)
        self.workers.add(worker)
        worker.finished.connect(self._finished)
        worker.finished.connect(worker.deleteLater)

    @Slot()
    def _finished(self):
        self.workers.discard(self.sender())

    def shutdown(self):
        self.closed = True
        workers = tuple(self.workers)
        for worker in workers:
            if hasattr(worker, 'stop'):
                worker.stop()
            else:
                worker.requestInterruption()
        for worker in workers:
            if worker.isRunning():
                worker.wait()


def editor_worker_owner():
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance()
    owner = getattr(application, '_subtitle_worker_owner', None)
    if owner is None or owner.closed:
        owner = WorkerOwner(application)
        application._subtitle_worker_owner = owner
        application.aboutToQuit.connect(owner.shutdown)
    return owner
