"""Sleek, collapsible bottom AI progress strip docked below PlaybackBar.

Stays completely hidden (0 px) when idle so normal playback layout & DPI tests are untouched.
Shows live stage text, determinate 0..100% bar, elapsed mm:ss timer, and 1-click Cancel while running.
"""
from __future__ import annotations

import time
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
)


class AIProgressBar(QFrame):
    """Collapsible studio-dark bottom status & progress strip for AI subtitle jobs."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiProgressStrip")
        self.setFixedHeight(30)
        self._running = False
        self._started_mono = 0.0
        self._percent = 0
        self._state = "idle"  # idle | running | success | error

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(500)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._auto_hide)

        self._build_ui()
        self.setStyleSheet(self._stylesheet())
        self.hide()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 2, 14, 2)
        layout.setSpacing(10)

        self.lbl_dot = QLabel("●")
        self.lbl_dot.setObjectName("aiDot")
        self.lbl_dot.setFixedWidth(12)
        self.lbl_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_status = QLabel("Đang chuẩn bị...")
        self.lbl_status.setObjectName("aiStatusText")
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.lbl_status.setMinimumWidth(140)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("aiBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setMinimumWidth(120)
        self.progress_bar.setMaximumWidth(220)

        self.lbl_percent = QLabel("0%")
        self.lbl_percent.setObjectName("aiPercent")
        self.lbl_percent.setFixedWidth(36)
        self.lbl_percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_elapsed = QLabel("00:00")
        self.lbl_elapsed.setObjectName("aiElapsed")
        self.lbl_elapsed.setFixedWidth(44)
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.btn_cancel = QPushButton("✕ Hủy")
        self.btn_cancel.setObjectName("aiCancelBtn")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.setFixedHeight(22)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)

        layout.addWidget(self.lbl_dot)
        layout.addWidget(self.lbl_status, 1)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.lbl_percent)
        layout.addWidget(self.lbl_elapsed)
        layout.addWidget(self.btn_cancel)

    @staticmethod
    def _stylesheet() -> str:
        return """
        QFrame#aiProgressStrip {
            background: #0E1520;
            border-top: 1px solid #223044;
        }
        QLabel#aiDot {
            color: #77E0BE;
            font-size: 10px;
            background: transparent;
            border: none;
        }
        QLabel#aiStatusText {
            color: #E2ECF7;
            font-size: 12px;
            font-weight: 500;
            background: transparent;
            border: none;
        }
        QLabel#aiPercent {
            color: #77E0BE;
            font-size: 12px;
            font-weight: 700;
            background: transparent;
            border: none;
        }
        QLabel#aiElapsed {
            color: #8CA0B8;
            font-size: 11px;
            font-family: 'Consolas', 'Segoe UI', monospace;
            background: transparent;
            border: none;
        }
        QProgressBar#aiBar {
            background: #1B2636;
            border: none;
            border-radius: 3px;
        }
        QProgressBar#aiBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #55D6A8, stop:1 #38BDF8);
            border-radius: 3px;
        }
        QPushButton#aiCancelBtn {
            background: #1B2431;
            color: #D7E2EE;
            border: 1px solid #2E3D52;
            border-radius: 6px;
            padding: 0 8px;
            font-size: 11px;
            font-weight: 600;
        }
        QPushButton#aiCancelBtn:hover {
            background: #3A2028;
            border-color: #E06C75;
            color: #FFD5D8;
        }
        """

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total = max(0, int(seconds))
        m, s = divmod(total, 60)
        return f"{m:02d}:{s:02d}"

    def _set_dot_color(self, color: str):
        self.lbl_dot.setStyleSheet(f"color: {color}; font-size: 10px; background: transparent; border: none;")

    def _tick_elapsed(self):
        if not self._running:
            return
        elapsed = time.monotonic() - self._started_mono
        self.lbl_elapsed.setText(self._format_elapsed(elapsed))
        # Subtle pulse on status dot so user always sees the worker is alive
        pulse = int(elapsed * 2) % 2 == 0
        self._set_dot_color("#77E0BE" if pulse else "#38BDF8")

    def start_job(self, message: str = "🤖 Đang khởi động AI phụ đề..."):
        self._hide_timer.stop()
        self._running = True
        self._state = "running"
        self._started_mono = time.monotonic()
        self._percent = 2
        self._set_dot_color("#77E0BE")
        self.lbl_status.setText(str(message or "🤖 Đang xử lý phụ đề..."))
        self.progress_bar.setValue(2)
        self.lbl_percent.setText("2%")
        self.lbl_elapsed.setText("00:00")
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.show()
        if not self._elapsed_timer.isActive():
            self._elapsed_timer.start()
        self.show()

    def update_progress(self, percent: int, message: str | None = None):
        if not self._running:
            self.start_job(message or "🤖 Đang xử lý phụ đề...")
        clamped = max(0, min(100, int(percent)))
        self._percent = clamped
        self.progress_bar.setValue(clamped)
        self.lbl_percent.setText(f"{clamped}%")
        if message:
            self.lbl_status.setText(str(message))
        self.lbl_elapsed.setText(self._format_elapsed(time.monotonic() - self._started_mono))
        if not self.isVisible():
            self.show()

    def update_message(self, message: str):
        if not message:
            return
        if not self._running:
            self.start_job(message)
            return
        self.lbl_status.setText(str(message))
        if not self.isVisible():
            self.show()

    def finish_job(self, message: str, hide_delay_ms: int = 4000):
        elapsed = time.monotonic() - self._started_mono if self._started_mono > 0 else 0.0
        self._running = False
        self._state = "success"
        self._elapsed_timer.stop()
        self._set_dot_color("#4ADE80")
        self.progress_bar.setValue(100)
        self.lbl_percent.setText("100%")
        if elapsed >= 0.1 and "s)" not in message:
            self.lbl_status.setText(f"{message} · {elapsed:.1f}s")
        else:
            self.lbl_status.setText(str(message))
        self.lbl_elapsed.setText(self._format_elapsed(elapsed))
        self.btn_cancel.hide()
        self.show()
        self._hide_timer.start(max(500, int(hide_delay_ms)))

    def fail_job(self, message: str, hide_delay_ms: int = 5000):
        elapsed = time.monotonic() - self._started_mono if self._started_mono > 0 else 0.0
        self._running = False
        self._state = "error"
        self._elapsed_timer.stop()
        self._set_dot_color("#F87171")
        short_msg = str(message or "Lỗi xử lý AI").splitlines()[0][:140]
        self.lbl_status.setText(short_msg)
        self.lbl_elapsed.setText(self._format_elapsed(elapsed))
        self.btn_cancel.hide()
        self.show()
        self._hide_timer.start(max(800, int(hide_delay_ms)))

    def reset_idle(self):
        self._running = False
        self._state = "idle"
        self._elapsed_timer.stop()
        self._hide_timer.stop()
        self.hide()

    def _auto_hide(self):
        if not self._running:
            self._state = "idle"
            self.hide()

    def shutdown(self):
        self._running = False
        self._elapsed_timer.stop()
        self._hide_timer.stop()
