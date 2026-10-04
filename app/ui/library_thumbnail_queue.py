"""Visible library/card image requests; two decoders and GUI-owned completion."""
from collections import OrderedDict
import weakref
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication


class LibraryThumbnailQueue(QObject):
    def __init__(self, app, pool):
        super().__init__(app)
        self.pool = pool
        self.pool.setMaxThreadCount(2)
        self.pending = OrderedDict()
        self.active = {}
        self.closed = False
        app.aboutToQuit.connect(self.shutdown)

    def submit(self, card, worker):
        self.cancel(card)
        if self.closed:
            worker.cancel()
            return
        self.pending[weakref.ref(card)] = worker
        self.drain()

    def cancel(self, card):
        previous = self.pending.pop(weakref.ref(card), None)
        if previous:
            previous.cancel()
        for worker, reference in self.active.items():
            if reference() is card:
                worker.cancel()

    def drain(self):
        while not self.closed and len(self.active) < 2 and self.pending:
            reference, worker = self.pending.popitem(last=False)
            card = reference()
            try:
                valid = (card is not None and not worker._is_cancelled
                         and card._current_worker is worker and card._can_load_thumbnail())
            except RuntimeError:
                valid = False
            if not valid:
                worker.cancel()
                continue
            self.active[worker] = reference
            worker.signals.done.connect(self.completed)
            self.pool.start(worker)

    @Slot(object)
    def completed(self, worker):
        self.active.pop(worker, None)
        self.drain()

    @Slot()
    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        for worker in list(self.pending.values()) + list(self.active):
            worker.cancel()
        self.pending.clear()
        self.pool.waitForDone()
        self.active.clear()


def library_thumbnail_queue(pool):
    app = QApplication.instance()
    previous = getattr(app, '_library_thumbnail_queue', None)
    if previous is None or previous.closed:
        if previous:
            previous.deleteLater()
        app._library_thumbnail_queue = LibraryThumbnailQueue(app, pool)
    return app._library_thumbnail_queue


def shutdown_library_thumbnails():
    app = QApplication.instance()
    queue = getattr(app, '_library_thumbnail_queue', None)
    if queue:
        queue.shutdown()
