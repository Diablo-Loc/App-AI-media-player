"""Prepare one next EQ track on the same worker; user requests always win."""
import logging
from pathlib import Path
import time

from PySide6.QtCore import QObject, QThread, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from core.audio_profile import AudioProfile

logger = logging.getLogger(__name__)


def next_audio_source(playlist, current, original):
    """Match the existing list.index/equality and repeat-all navigation policy."""
    if not playlist or current is None:
        return None
    try:
        item = playlist[(playlist.index(current) + 1) % len(playlist)]
    except ValueError:
        item = playlist[0]
    path = str(getattr(item, 'path', ''))
    if not path or Path(path) == Path(original):
        return None
    return path


class NextAudioPrefetch(QObject):
    SETTLE_MS = 2000
    BUDGET_MS = 30000

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self.player = controller.player
        self._attempted = None
        self._last_position = None
        self._selecting = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.SETTLE_MS)
        self.timer.timeout.connect(self._start)
        self.budget = QTimer(self)
        self.budget.setSingleShot(True)
        self.budget.setInterval(self.BUDGET_MS)
        self.budget.timeout.connect(self._expired)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.mediaStatusChanged.connect(self._status_changed)
        self.player.sourceChanged.connect(lambda source: self._reset_position())
        self.player.positionChanged.connect(self._position_changed)
        slider = controller.window.playback_bar.time_slider
        slider.sliderPressed.connect(self.interaction)
        slider.sliderReleased.connect(self.schedule)
        manager = getattr(controller.window, 'job_manager', None)
        signal = getattr(manager, 'status_changed', None)
        if signal is not None and hasattr(signal, 'connect'):
            signal.connect(self._ai_activity)

    def _reset_position(self):
        self._last_position = None

    def _enabled(self):
        c = self.controller
        return not c._closed and c.prefetch_enabled and c.profile.tone != 'off'

    def schedule(self):
        if self._enabled() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            if not self.timer.isActive():
                self.timer.start()

    def invalidate(self, stop=True):
        self.timer.stop()
        self.budget.stop()
        self._attempted = None
        worker = self.controller.worker
        if stop and worker is not None and getattr(worker, 'prefetch', False):
            worker.stop()

    def refresh(self):
        self.invalidate()
        self.schedule()

    def interaction(self):
        self.invalidate()

    def _ai_busy(self):
        manager = getattr(self.controller.window, 'job_manager', None)
        worker = getattr(manager, '_worker', None)
        return isinstance(worker, QThread) and worker.isRunning()

    def _ai_activity(self, *_):
        if self._ai_busy():
            self.invalidate()
        self.schedule()

    def _state_changed(self, state):
        self._reset_position()
        worker = self.controller.worker
        if (state == QMediaPlayer.PlaybackState.StoppedState and self._selecting is not None
                and worker is not None and getattr(worker, 'prefetch', False)
                and QUrl.fromLocalFile(worker.source) == self._selecting
                and worker.profile.tone == self.controller.profile.tone):
            self.timer.stop()
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.schedule()
        else:
            self.invalidate()

    def stop_for_selection(self, source):
        self._selecting = source
        try:
            self.player.stop()
        finally:
            self._selecting = None

    def _status_changed(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self.schedule()
        elif status == QMediaPlayer.MediaStatus.StalledMedia:
            self.invalidate()

    def _position_changed(self, position):
        now = time.monotonic()
        old = self._last_position
        self._last_position = (position, now)
        if old is not None and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            expected = (now - old[1]) * self.player.playbackRate() * 1000
            if abs((position - old[0]) - expected) > 750:
                self.invalidate()
                self.schedule()

    def _start(self):
        c = self.controller
        if (not self._enabled() or c.worker is not None or c._pending or c.switching
                or self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
                or self.player.mediaStatus() not in (QMediaPlayer.MediaStatus.LoadedMedia,
                                                    QMediaPlayer.MediaStatus.BufferedMedia)):
            return
        if self._ai_busy():
            self.timer.start()
            return
        source = next_audio_source(getattr(c.window, 'active_playlist', ()),
                                   getattr(c.window, 'current_media_item', None), c._original.toLocalFile())
        if source is None:
            return
        key = (c._original.toString(), source, c.profile.tone)
        if key == self._attempted:
            return
        from control.audio_effects import AudioPreparationWorker
        worker = AudioPreparationWorker(source, AudioProfile(False, c.profile.tone), 0, c.cache,
                                        (self.player.source().toLocalFile(),), c)
        worker.prefetch = True
        worker.generation = c._generation
        c.worker = worker
        self._attempted = key
        worker.finished.connect(c._prepared)
        worker.finished.connect(worker.deleteLater)
        self.budget.start()
        worker.start()

    def promote(self, worker):
        c = self.controller
        if (getattr(worker, 'prefetch', False) and not worker.isInterruptionRequested()
                and QUrl.fromLocalFile(worker.source) == c._original
                and worker.profile.tone == c.profile.tone and worker.track == c._track):
            worker.prefetch = False
            worker.requested_profile = c.profile
            worker.generation = c._generation
            worker.progress.connect(c._progress)
            self.budget.stop()
            return True
        return False

    def finished(self, worker):
        self.budget.stop()
        if worker.error:
            logger.debug('Next-track audio preparation skipped: %s', worker.error)
        # Result only populates the owned cache; never changes current playback.

    def _expired(self):
        worker = self.controller.worker
        if worker is not None and getattr(worker, 'prefetch', False):
            worker.stop()

    def shutdown(self):
        self.invalidate()
