"""User volume stays separate from fixed loudness gain on the same QAudioOutput."""
import math
import time

from PySide6.QtCore import QObject, QTimer, Signal


class AudioVolumeControl(QObject):
    user_changed = Signal(float)

    def __init__(self, output, parent=None):
        super().__init__(parent)
        self.output = output
        self._user = output.volume()
        self._gain = 0.0
        self._inside = self._closed = False
        self._ramp = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        output.volumeChanged.connect(self._external_volume)
        output.deviceChanged.connect(self._device_changed)

    def volume(self):
        return self._user

    def set_volume(self, value):
        if self._closed:
            return
        self._user = max(0.0, min(1.0, float(value)))
        self.user_changed.emit(self._user)
        self._apply(False)

    def set_gain(self, gain_db, ramp=True):
        if not math.isfinite(gain_db):
            raise ValueError('Invalid audio gain')
        self._gain = gain_db
        self._apply(ramp)

    def _write(self, value):
        self._inside = True
        try:
            self.output.setVolume(value)
        finally:
            self._inside = False

    def _apply(self, ramp):
        target = min(1.0, self._user * 10 ** (self._gain / 20))
        self._timer.stop()
        self._ramp = None
        if ramp and abs(target - self.output.volume()) > 0.00001:
            self._ramp = (time.monotonic(), self.output.volume(), target)
            self._timer.start()
        else:
            self._write(target)

    def _tick(self):
        if self._closed or self._ramp is None:
            return
        started, initial, target = self._ramp
        fraction = min(1.0, (time.monotonic() - started) / 0.15)
        smooth = fraction * fraction * (3 - 2 * fraction)
        self._write(initial + (target - initial) * smooth)
        if fraction == 1:
            self._timer.stop()
            self._ramp = None

    def _external_volume(self, value):
        if not self._inside and not self._closed:
            self.set_volume(value)

    def _device_changed(self):
        if not self._closed:
            # Keep the current physical value through the old device-refresh
            # read/set cycle; do not reinterpret that value as user volume.
            self._apply(True)

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._ramp = None
        self._write(self._user)
        self.output.volumeChanged.disconnect(self._external_volume)
        self.output.deviceChanged.disconnect(self._device_changed)
