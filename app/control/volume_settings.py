"""Remember user volume, independently of normalization/EQ output gain."""
import json
import logging
import math
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QApplication
from core.subtitle_persistence import atomic_bytes


class VolumeSettings(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.path = Path(window.audio_effects.settings_path).with_name('playback-volume.json')
        self.percent = self._load()
        self.dirty = self.closed = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.flush)

        panel = QWidget(window.settings_page)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel('Âm thanh · Âm lượng')
        title.setStyleSheet('color: #A9F1D9; font-size: 16px; font-weight: 600; margin-top: 10px; padding-bottom: 8px;')
        layout.addWidget(title)
        row = QHBoxLayout()
        label = QLabel('Âm lượng:')
        label.setFixedWidth(120)
        row.addWidget(label)
        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setSuffix(' %')
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumHeight(38)
        self.spin.setStyleSheet('QSpinBox { background: #151C26; color: #EDF3FA; border: 1px solid #273445; border-radius: 8px; padding: 8px; } QSpinBox:focus { border-color: #77E0BE; }')
        self.spin.setAccessibleName('Âm lượng phát nhạc')
        row.addWidget(self.spin)
        layout.addLayout(row)
        self.hint = QLabel('Tự lưu mức cuối cùng khi chỉnh tại đây, nút loa hoặc phím ↑/↓. Lần đầu: 50%.')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color: #9AAABC; font-size: 12px; margin-left: 125px;')
        layout.addWidget(self.hint)
        window.settings_page.content_layout.insertWidget(0, panel)
        window.settings_page.volume_percent = self.spin

        window.audio_effects.set_volume(self.percent / 100)
        self._sync(window.audio_effects.volume())
        window.audio_effects.volume_control.user_changed.connect(self._changed)
        self.spin.valueChanged.connect(lambda value: window.audio_effects.set_volume(value / 100))
        self.spin.editingFinished.connect(self.flush)
        window.vol_popup.slider.sliderReleased.connect(self.flush)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def _load(self):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))['volume_percent']
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                return 50.0
            return float(value)
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            return 50.0

    def _sync(self, value):
        percent = int(round(value * 100))
        blocked = self.spin.blockSignals(True)
        self.spin.setValue(percent)
        self.spin.blockSignals(blocked)
        self.window.vol_popup.set_value(percent)
        self.window.playback_bar.update_volume_icon(value)

    def _changed(self, value):
        if self.closed:
            return
        self._sync(value)
        percent = round(value * 100, 4)
        if percent != self.percent:
            self.percent = percent
            self.dirty = True
            self.timer.start()

    def flush(self):
        self.timer.stop()
        if not self.dirty:
            return
        try:
            atomic_bytes(self.path, json.dumps({'volume_percent': self.percent}, indent=2).encode('utf-8'))
            self.dirty = False
            self.hint.setText('Tự lưu mức cuối cùng khi chỉnh tại đây, nút loa hoặc phím ↑/↓. Lần đầu: 50%.')
        except OSError:
            self.hint.setText('Không lưu được âm lượng. Kiểm tra quyền ghi thư mục storage.')
            logging.warning('Unable to save playback volume', exc_info=True)

    def shutdown(self):
        if not self.closed:
            self.flush()
            self.closed = True


def install_volume_settings(window):
    return VolumeSettings(window)
