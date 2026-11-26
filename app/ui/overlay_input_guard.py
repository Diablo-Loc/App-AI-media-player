"""Keep floating subtitles draggable without covering application controls."""
from PySide6.QtCore import QObject, QEvent, QPoint, QRect, QTimer, QCoreApplication
from PySide6.QtGui import QRegion, QMouseEvent


class OverlayInputGuard(QObject):
    _GEOMETRY_EVENTS = frozenset((
        QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
        QEvent.Type.Hide, QEvent.Type.ParentChange,
    ))
    _IMMEDIATE_EVENTS = frozenset((QEvent.Type.Show, QEvent.Type.ParentChange))

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
        kind = event.type()
        if kind in self._GEOMETRY_EVENTS:
            if kind in self._IMMEDIATE_EVENTS:
                self.refresh()
            # Coalesce rapid Move/Resize bursts onto a single 0ms tick.
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
            if not overlay.isVisible():
                return
            origin = overlay.mapToGlobal(QPoint(0, 0))
            overlay_rect = overlay.rect()
            overlay_global = QRect(origin, overlay_rect.size())

            overlapping = []
            for control in self.controls:
                if not control.isVisible():
                    continue
                c_origin = control.mapToGlobal(QPoint(0, 0))
                c_global = QRect(c_origin, control.size())
                if c_global.intersects(overlay_global):
                    overlapping.append(QRect(c_origin - origin, control.size()))

            if not overlapping:
                if not overlay.mask().isEmpty():
                    overlay.clearMask()
                return

            region = QRegion(overlay_rect)
            for rect in overlapping:
                region = region.subtracted(QRegion(rect))

            if region == QRegion(overlay_rect):
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
