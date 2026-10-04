"""Gate the floating lyric window without changing video/window ownership."""
from bisect import bisect_right

from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from subtitle.mode import SubtitleMode


class SubtitlePresentationGuard(QObject):
    _EVENTS = frozenset((
        QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.ParentChange,
        QEvent.Type.WindowStateChange, QEvent.Type.WindowActivate,
        QEvent.Type.WindowDeactivate, QEvent.Type.ApplicationActivate,
        QEvent.Type.ApplicationDeactivate,
    ))

    def __init__(self, owner, overlay):
        super().__init__(owner)
        self.owner = owner
        self.overlay = overlay
        self._closed = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self.application = QApplication.instance()
        self.application.installEventFilter(self)

    def context_allows(self):
        owner, overlay = self.owner, self.overlay
        video = getattr(owner, 'video_display', None)
        if (self._closed or not owner.isVisible() or owner.isMinimized()
                or getattr(owner, 'is_mini_mode', False)
                or getattr(owner, 'video_mode', None) == 'mini'
                or not video or not video.isVisible() or video.window() is not owner
                or not overlay.enable_render or overlay.mode.value == SubtitleMode.OFF.value):
            return False
        if self.application.activeModalWidget() or self.application.activePopupWidget():
            return False
        if any(isinstance(window, QDialog) and window.isVisible()
               for window in self.application.topLevelWidgets()):
            return False
        active = self.application.activeWindow()
        if active is not overlay and not owner.isActiveWindow():
            return False
        return True

    def allows(self):
        if not self.context_allows():
            return False
        overlay = self.overlay
        idx = bisect_right(overlay._start_times, overlay._current_ms_cache) - 1
        if idx < 0 or idx >= len(overlay.subtitles):
            return False
        cue = overlay.subtitles[idx]
        return (cue['start'] <= overlay._current_ms_cache <= cue['end']
                and bool(overlay.build_text(cue).strip()))

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.owner and kind == QEvent.Type.Close:
            self.shutdown()
            return False
        if self._closed or kind not in self._EVENTS:
            return False
        video = getattr(self.owner, 'video_display', None)
        relevant = (watched is self.owner or watched is self.application
                    or isinstance(watched, QDialog)
                    or watched is video
                    or (isinstance(watched, QWidget) and video is not None
                        and watched is not self.overlay and watched.isAncestorOf(video)))
        if relevant:
            # Suppress before the dialog is painted. The queued refresh sees
            # the final activation/parent/visibility state, including paused video.
            if (isinstance(watched, QDialog) and kind == QEvent.Type.Show) or not self.allows():
                self.overlay._smart_hide(instant=True)
            self._refresh_timer.start(0)
        return False

    def schedule_refresh(self):
        if self._closed:
            return
        if not self.allows():
            self.overlay._smart_hide(instant=True)
        self._refresh_timer.start(0)

    def prepare_geometry(self):
        # For You can detach the Tool window from MainWindow. Its existing
        # VideoStage must place the newly sized cue before the first paint.
        stage = getattr(getattr(self.owner, 'foryou_page', None), 'video_container', None)
        video = getattr(self.owner, 'video_display', None)
        if (stage is not None and video is not None and video.parentWidget() is stage
                and not self.overlay._user_moved):
            stage.update_layout_execution()

    def refresh(self):
        if self._closed:
            return
        self.overlay.update_position(self.overlay._current_ms_cache)

    def shutdown(self):
        self._closed = True
        self._refresh_timer.stop()
        self.application.removeEventFilter(self)
        self.overlay._smart_hide(instant=True)
