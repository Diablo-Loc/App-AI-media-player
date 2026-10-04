"""Refresh the existing mini video surface when its layout/first frame is ready."""
from PySide6.QtCore import QObject, QEvent, QTimer, Slot
from PySide6.QtMultimedia import QVideoFrame


class MiniVideoDock(QObject):
    def __init__(self, container):
        super().__init__(container)
        self.container = container
        self.video = None
        self._awaiting_frame = True
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        container.installEventFilter(self)

    def bind(self, video):
        if self.video is video:
            return
        if self.video is not None:
            self.video.removeEventFilter(self)
            self.video.videoSink().videoFrameChanged.disconnect(self._on_frame)
        self.video = video
        video.installEventFilter(self)
        video.videoSink().videoFrameChanged.connect(self._on_frame)
        self.prepare_media()

    def prepare_media(self):
        self._awaiting_frame = True
        self.refresh()
        self._timer.start(0)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize,
                            QEvent.Type.LayoutRequest, QEvent.Type.ParentChange):
            self._awaiting_frame = True
            self._timer.start(0)
        return False

    @Slot(QVideoFrame)
    def _on_frame(self, frame):
        if self.video is None or self.video.parentWidget() is not self.container:
            return
        if self._awaiting_frame and frame.isValid() and self.refresh():
            self._awaiting_frame = False

    @Slot()
    def refresh(self):
        video = self.video
        if video is None or video.parentWidget() is not self.container:
            return False
        if self.container.layout():
            self.container.layout().activate()
        rect = self.container.rect()
        if video.geometry() != rect:
            video.setGeometry(rect)
        if self.container.isVisible():
            # Startup lowered the native video surface. Restore it for the new
            # media and the first decoded frame without resetting the player.
            video.show()
            video.raise_()
            video.update()
        return True
