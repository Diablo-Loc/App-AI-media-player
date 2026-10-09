"""Keep floating subtitles draggable without covering application controls."""
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, QTimer, QCoreApplication
from PySide6.QtGui import QRegion, QMouseEvent


class OverlayInputGuard(QObject):
    _GEOMETRY_EVENTS = frozenset((
        QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
        QEvent.Type.Hide, QEvent.Type.ParentChange,
    ))

    def __init__(self, owner, overlay, controls):
        super().__init__(owner)
        self.overlay = overlay
        self.controls = tuple(controls)
        self._updating = False
        self._mouse_target = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        for widget in (owner, overlay, *self.controls):
            widget.installEventFilter(self)
        self.refresh()

    def eventFilter(self, watched, event):
        if event.type() in self._GEOMETRY_EVENTS:
            self.refresh()
            # Native window creation/reparenting can reset the mask after Show.
            self._refresh_timer.start(0)
        if watched is self.overlay and isinstance(event, QMouseEvent):
            return self._forward_control_event(event)
        return False

    def _forward_control_event(self, event):
        """Fallback for platforms that cannot apply masks to floating windows."""
        kind = event.type()
        if kind == QEvent.Type.MouseMove and not event.buttons():
            self._mouse_target = None
            return False
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            point = event.globalPosition().toPoint()
            self._mouse_target = None
            for control in self.controls:
                local = control.mapFromGlobal(point)
                if control.isVisible() and control.rect().contains(local):
                    self._mouse_target = control.childAt(local) or control
                    break
        target = self._mouse_target
        if target is None or kind not in (
            QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease,
        ):
            return False
        local = target.mapFromGlobal(event.globalPosition().toPoint())
        forwarded = QMouseEvent(kind, local, event.globalPosition(),
                                event.button(), event.buttons(), event.modifiers())
        QCoreApplication.sendEvent(target, forwarded)
        if kind == QEvent.Type.MouseButtonRelease:
            self._mouse_target = None
        return True

    def refresh(self):
        if self._updating:
            return
        self._updating = True
        try:
            overlay = self.overlay
            origin = overlay.mapToGlobal(QPoint(0, 0))
            region = QRegion(overlay.rect())
            for control in self.controls:
                if control.isVisible():
                    rect = QRect(control.mapToGlobal(QPoint(0, 0)) - origin, control.size())
                    region = region.subtracted(QRegion(rect))
            if region == QRegion(overlay.rect()):
                if not overlay.mask().isEmpty():
                    overlay.clearMask()
            else:
                # An empty QWidget mask means "no mask". A nonempty region
                # outside its bounds instead makes a fully covered overlay inert.
                if region.isEmpty():
                    region = QRegion(-1, -1, 1, 1)
                if region != overlay.mask():
                    overlay.setMask(region)
        finally:
            self._updating = False
