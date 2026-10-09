"""Owned background scans, latest-folder cancellation and cache persistence."""
import copy
from dataclasses import replace
import threading
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot


class ScanWorker(QThread):
    def __init__(self, library, folder, parent=None):
        super().__init__(parent)
        self.library, self.folder = library, folder
        self.result, self.error = [], None

    def run(self):
        try:
            snapshot = copy.copy(self.library)
            with self.library.lock:
                snapshot.items = {key: replace(value) for key, value in self.library.items.items()}
            snapshot.lock = threading.RLock()
            snapshot.save = lambda: None
            snapshot._cancel_scan = self.isInterruptionRequested
            self.result = snapshot.scan_folder(self.folder)
        except Exception as error:
            self.error = str(error)


class CacheWriter(QThread):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library

    def run(self):
        self.library.save()


class LibraryScanQueue(QObject):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.worker = self.writer = None
        self.pending = None
        self.closed = self.persist_pending = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._launch)

    def request(self, folder):
        if self.closed:
            return
        self.pending = folder
        if self.worker:
            self.worker.requestInterruption()
        else:
            self.timer.start(0)

    @Slot()
    def _launch(self):
        if self.closed or not self.pending or self.worker:
            return
        folder, self.pending = self.pending, None
        self.worker = ScanWorker(self.library, folder, self)
        self.worker.finished.connect(self._finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    @Slot()
    def _finished(self):
        worker = self.sender()
        if worker is not self.worker:
            return
        self.worker = None
        if self.closed:
            return
        if self.pending or worker.isInterruptionRequested():
            if self.pending:
                self.timer.start(0)
            return
        if worker.error:
            self.failed.emit(worker.error)
            return
        result = []
        with self.library.lock:
            for item in worker.result:
                current = self.library.items.get(item.id)
                if current is None:
                    self.library.items[item.id] = current = item
                else:
                    current.path, current.mtime = item.path, item.mtime
                    if current.duration == 0:
                        current.duration = item.duration
                result.append(current)
        self._persist()
        self.completed.emit(result)

    def _persist(self):
        if self.writer:
            self.persist_pending = True
            return
        self.persist_pending = False
        self.writer = CacheWriter(self.library, self)
        self.writer.finished.connect(self._persist_finished)
        self.writer.finished.connect(self.writer.deleteLater)
        self.writer.start()

    @Slot()
    def _persist_finished(self):
        if self.sender() is not self.writer:
            return
        self.writer = None
        if self.persist_pending and not self.closed:
            self._persist()

    def shutdown(self):
        self.closed = True
        self.pending = None
        self.timer.stop()
        if self.worker:
            self.worker.requestInterruption()
            self.worker.wait()
        if self.writer:
            self.writer.wait()
        if self.persist_pending:
            self.library.save()
            self.persist_pending = False
