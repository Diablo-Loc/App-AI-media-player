"""Two background decoders, bounded to requests from currently visible rows."""
from collections import OrderedDict
from PySide6.QtCore import QObject, QThreadPool, Slot
from PySide6.QtWidgets import QApplication


class ThumbnailQueue(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.pending = OrderedDict()
        self.active = set()
        self.closed = False
        app.aboutToQuit.connect(self.shutdown)

    def submit(self, thumb, worker):
        previous = self.pending.pop(thumb, None)
        if previous:
            previous.cancel()
        self.pending[thumb] = worker
        self.drain()

    def drain(self):
        while not self.closed and len(self.active) < 2 and self.pending:
            thumb, worker = self.pending.popitem(last=False)
            try:
                valid = (not worker._is_cancelled and thumb.isVisible()
                         and thumb.property('playlist_visible') is True
                         and thumb._current_worker is worker)
            except RuntimeError:
                valid = False
            if not valid:
                worker.cancel()
                continue
            self.active.add(worker)
            worker.signals.done.connect(self.completed)
            self.pool.start(worker)

    @Slot(object)
    def completed(self, worker):
        self.active.discard(worker)
        self.drain()

    @Slot()
    def shutdown(self):
        self.closed = True
        for worker in list(self.pending.values()) + list(self.active):
            worker.cancel()
        self.pending.clear()
        self.pool.waitForDone()
        self.active.clear()


def thumbnail_queue():
    app = QApplication.instance()
    if not hasattr(app, '_playlist_thumbnail_queue'):
        app._playlist_thumbnail_queue = ThumbnailQueue(app)
    return app._playlist_thumbnail_queue
