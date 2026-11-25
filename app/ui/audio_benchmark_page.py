"""Commercial-grade audio analyzer & acoustic comparison tab (full-width scroll-safe studio layout)."""
import html
import math
from pathlib import Path
import threading

import numpy as np
from PySide6.QtCore import Qt, QThread, QPointF, QSize, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from control.worker_lifecycle import OwnedProcesses
from core.audio_benchmark import render_audition_pair, run_audio_benchmark
from core.audio_effects import source_signature
from core.audio_profile import AudioProfile, adaptive_master_profile, preset_profile
from core.audio_stream_engine import select_wasapi_device
from ui.design_system import FORM_STYLE
from ui.icons import ACCENT, INK, MUTED, TEXT, button_icon

COLOR_ORIG = '#F0B866'
COLOR_PROC = '#5ED9B8'
COLOR_PHASE = '#7CC0F5'
COLOR_CLIP = '#E86C6C'


class AudioBenchmarkWorker(QThread):
    """Background acoustic analyzer comparing Pre vs Post output through the real DAC quantizer."""

    finished_ok = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, generation: int, source_path: str, profile: AudioProfile, target_lufs: int,
                 cached_info=None, cached_measurement=None, parent=None):
        super().__init__(parent)
        self.generation = int(generation)
        self.source_path = str(source_path)
        self.profile = profile
        self.target_lufs = int(target_lufs)
        self.cached_info = cached_info
        self.cached_measurement = cached_measurement
        self.processes = OwnedProcesses()

    def run(self):
        try:
            res = run_audio_benchmark(
                self.source_path,
                self.profile,
                target_lufs=self.target_lufs,
                processes=self.processes,
                cancelled=self.isInterruptionRequested,
                cached_info=self.cached_info,
                cached_measurement=self.cached_measurement,
            )
            if not self.isInterruptionRequested():
                self.finished_ok.emit(self.generation, res)
        except Exception as err:
            if not self.isInterruptionRequested():
                self.failed.emit(self.generation, str(err))
        finally:
            self.processes.stop()
            self.processes.wait()

    def stop(self):
        self.requestInterruption()
        self.processes.stop()


class AuditionPrepWorker(QThread):
    """Prepare sample-aligned Original vs Processed RAM audition pair with BS.1770-4 gain match."""

    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, generation: int, source_path: str, profile: AudioProfile, source_info: dict | None,
                 gain_db: float, start_sec: float, dur_sec: float, preferred_device: str = '', parent=None):
        super().__init__(parent)
        self.generation = int(generation)
        self.source_path = str(source_path)
        self.profile = profile
        self.source_info = source_info
        self.gain_db = float(gain_db)
        self.start_sec = float(start_sec)
        self.dur_sec = float(dur_sec)
        self.preferred_device = str(preferred_device or '')
        self.processes = OwnedProcesses()

    def run(self):
        try:
            play_sr = 48000
            try:
                import sounddevice as sd
                _, dev_info = select_wasapi_device(sd, self.preferred_device)
                dev_sr = int(round(float(dev_info.get('default_samplerate') or 48000)))
                if 44100 <= dev_sr <= 192000:
                    play_sr = dev_sr
            except Exception:
                pass
            pair = render_audition_pair(
                self.source_path,
                self.profile,
                self.source_info,
                self.gain_db,
                self.start_sec,
                min(10.0, max(1.0, self.dur_sec)),
                play_sr=play_sr,
                processes=self.processes,
                cancelled=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.ready.emit(self.generation, pair)
        except Exception as err:
            if not self.isInterruptionRequested():
                self.failed.emit(self.generation, str(err))
        finally:
            self.processes.stop()
            self.processes.wait()

    def stop(self):
        self.requestInterruption()
        self.processes.stop()


class BenchmarkAuditionEngine:
    """Zero-disk RAM loop player for instant 12 ms click-free gain-matched A/B switching."""

    def __init__(self, volume_fn=None):
        self._lock = threading.RLock()
        self._volume_fn = volume_fn or (lambda: (0.5, False))
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._playing = False
        self._branch = 'proc'
        self._gain_matched = True
        self._pair: dict | None = None
        self._xfade_from: tuple[str, bool] | None = None
        self._xfade_pos = 0
        self._xfade_len = 576

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def set_branch(self, branch: str):
        target = 'orig' if branch == 'orig' else 'proc'
        with self._lock:
            if target != self._branch:
                self._xfade_from = (self._branch, self._gain_matched)
                self._xfade_pos = 0
                self._branch = target

    def set_gain_matched(self, matched: bool):
        m = bool(matched)
        with self._lock:
            if m != self._gain_matched:
                self._xfade_from = (self._branch, self._gain_matched)
                self._xfade_pos = 0
                self._gain_matched = m

    def start(self, pair: dict, branch: str = 'proc', gain_matched: bool = True, preferred_device: str = ''):
        self.stop()
        orig = pair.get('orig_f32')
        proc = pair.get('proc_f32')
        if orig is None or proc is None or len(orig) < 16 or len(proc) < 16:
            raise RuntimeError('Không có dữ liệu âm thanh để phát thử.')
        sr = max(8000, int(pair.get('sample_rate') or 48000))

        import sounddevice as sd
        dev_idx, _ = select_wasapi_device(sd, preferred_device)
        stream = sd.RawOutputStream(
            device=dev_idx,
            channels=2,
            dtype='float32',
            samplerate=sr,
            blocksize=0,
            latency=0.08,
            extra_settings=sd.WasapiSettings(exclusive=False),
        )
        cancel_ev = threading.Event()
        with self._lock:
            self._pair = pair
            self._branch = 'orig' if branch == 'orig' else 'proc'
            self._gain_matched = bool(gain_matched)
            self._xfade_from = None
            self._xfade_pos = 0
            self._xfade_len = max(64, int(round(0.012 * sr)))
            self._cancel_event = cancel_ev
            self._stream = stream
            self._playing = True

        t = threading.Thread(
            target=self._run_loop,
            args=(stream, pair, sr, cancel_ev),
            name='BoTube-AB-Audition',
            daemon=True,
        )
        with self._lock:
            self._thread = t
        t.start()

    def _run_loop(self, stream, pair: dict, sr: int, cancel_ev: threading.Event):
        orig = pair['orig_f32']
        proc = pair['proc_f32']
        n_frames = min(len(orig), len(proc))
        match_orig = float(pair.get('match_orig_lin', 1.0))
        match_proc = float(pair.get('match_proc_lin', 1.0))
        cursor = 0
        block_frames = 1024

        def _slice_pair(start_idx: int, count: int) -> tuple[np.ndarray, np.ndarray]:
            end_idx = start_idx + count
            if end_idx <= n_frames:
                return orig[start_idx:end_idx], proc[start_idx:end_idx]
            idx = (np.arange(count, dtype=np.int64) + start_idx) % n_frames
            return orig[idx], proc[idx]

        def _branch_block(seg_o: np.ndarray, seg_p: np.ndarray, br: str, matched: bool) -> np.ndarray:
            if br == 'orig':
                scale = match_orig if matched else 1.0
                return seg_o.astype(np.float64) * scale
            scale = match_proc if matched else 1.0
            return seg_p.astype(np.float64) * scale

        try:
            stream.start()
            while not cancel_ev.is_set():
                seg_o, seg_p = _slice_pair(cursor, block_frames)
                cursor = (cursor + block_frames) % n_frames
                with self._lock:
                    cur_state = (self._branch, self._gain_matched)
                    prev_state = self._xfade_from
                    x_pos = self._xfade_pos
                    x_len = self._xfade_len

                tgt = _branch_block(seg_o, seg_p, cur_state[0], cur_state[1])
                if prev_state is not None and x_pos < x_len:
                    src = _branch_block(seg_o, seg_p, prev_state[0], prev_state[1])
                    take = min(block_frames, x_len - x_pos)
                    t = (np.arange(take, dtype=np.float64) + float(x_pos) + 0.5) / float(x_len)
                    w = (0.5 * (1.0 - np.cos(np.pi * t)))[:, None]
                    tgt[:take] = src[:take] * (1.0 - w) + tgt[:take] * w
                    with self._lock:
                        self._xfade_pos += take
                        if self._xfade_pos >= x_len:
                            self._xfade_from = None

                vol, muted = self._volume_fn()
                out_scale = 0.0 if muted else max(0.0, min(1.0, float(vol)))
                pcm = np.clip(tgt * out_scale, -1.0, 1.0).astype('<f4', copy=False).tobytes()
                stream.write(pcm)
        except Exception:
            pass
        finally:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
            with self._lock:
                if self._stream is stream:
                    self._stream = None
                    self._playing = False

    def stop(self):
        with self._lock:
            ev = self._cancel_event
            stream = self._stream
            thread = self._thread
            self._playing = False
            self._stream = None
            self._thread = None
        ev.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.4)
            if thread.is_alive() and stream is not None:
                try:
                    stream.abort()
                except Exception:
                    pass
                thread.join(timeout=0.6)
        elif stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass


class BenchmarkChartCanvas(QWidget):
    """High-contrast dual-trace canvas: Gốc (Amber #F0B866) vs Sau xử lý (Mint #5ED9B8)."""

    _GRID_FREQS = ((20, '20'), (50, '50'), (100, '100'), (250, '250'), (500, '500'),
                   (1000, '1k'), (2000, '2k'), (4000, '4k'), (8000, '8k'), (16000, '16k'))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(244)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._data: dict | None = None
        self._mode = 'spectrum'
        self._match_level = True
        self._show_orig = True
        self._show_proc = True
        self._hover_pos: QPointF | None = None

    def set_result(self, result: dict | None):
        self._data = result
        self.update()

    def set_view_mode(self, mode: str):
        self._mode = mode if mode in ('spectrum', 'transfer', 'peaks', 'thd_fft') else 'spectrum'
        self.update()

    def set_match_level(self, match: bool):
        self._match_level = bool(match)
        self.update()

    def set_show_orig(self, show: bool):
        self._show_orig = bool(show)
        self.update()

    def set_show_proc(self, show: bool):
        self._show_proc = bool(show)
        self.update()

    def mouseMoveEvent(self, event):
        self._hover_pos = event.position()
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_pos = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        p.fillRect(self.rect(), QColor('#0B1017'))
        p.setPen(QPen(QColor('#1D2938'), 1.0))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

        fnt = self.font()
        fnt.setPointSizeF(8.0)
        p.setFont(fnt)
        fm = p.fontMetrics()

        if not self._data:
            p.setPen(QColor('#64778B'))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Chọn nguồn âm thanh rồi bấm Đo kiểm.')
            return

        if self._mode == 'transfer':
            self._paint_transfer(p, w, h, fm)
        elif self._mode == 'peaks':
            self._paint_peaks(p, w, h, fm)
        elif self._mode == 'thd_fft':
            self._paint_thd_fft(p, w, h, fm)
        else:
            self._paint_spectrum(p, w, h, fm)

    @staticmethod
    def _log_x(f: float, pad_l: float, gw: float) -> float:
        log_min = math.log10(20.0)
        log_max = math.log10(20000.0)
        return pad_l + ((math.log10(max(20.0, float(f))) - log_min) / (log_max - log_min)) * gw

    @staticmethod
    def _x_to_log_freq(x: float, pad_l: float, gw: float) -> float:
        t = max(0.0, min(1.0, (x - pad_l) / max(1.0, gw)))
        return 20.0 * (1000.0 ** t)

    def _paint_spectrum(self, p: QPainter, w: float, h: float, fm):
        freqs = self._data.get('freqs_hz') or []
        orig = self._data.get('orig_spec_db') or []
        proc = (self._data.get('proc_spec_matched_db') if self._match_level else self._data.get('proc_spec_raw_db')) or []
        delta = self._data.get('delta_spec_db') or []
        if not freqs or not orig or not proc:
            return

        pad_l = max(44.0, float(fm.horizontalAdvance('-150') + 12))
        pad_r = 16.0
        pad_t = max(26.0, float(fm.height() + 12))
        pad_b = max(22.0, float(fm.height() + 8))
        gap = 12.0
        usable_h = max(60.0, h - pad_t - pad_b - gap)
        top_h = usable_h * 0.65
        bot_top = pad_t + top_h + gap
        bot_h = usable_h - top_h
        gw = max(40.0, w - pad_l - pad_r)

        peak_val = max(max(orig), max(proc), -20.0)
        y_hi = float(min(15, max(0, int(math.ceil(peak_val / 15.0) * 15))))
        y_lo = float(y_hi - 75.0)

        def _y_top(db: float) -> float:
            c = max(y_lo, min(y_hi, float(db)))
            return pad_t + (1.0 - (c - y_lo) / (y_hi - y_lo)) * top_h

        def _y_bot(db: float) -> float:
            c = max(-8.0, min(8.0, float(db)))
            return bot_top + (1.0 - (c + 8.0) / 16.0) * bot_h

        for db in range(int(y_lo), int(y_hi) + 1, 15):
            yy = _y_top(db)
            p.setPen(QPen(QColor('#16202C'), 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            lbl = f'{db}'
            p.setPen(QColor('#64778B'))
            p.drawText(int(pad_l - fm.horizontalAdvance(lbl) - 6), int(yy + fm.ascent() / 2 - 1), lbl)

        for db in (6, 0, -6):
            yy = _y_bot(db)
            p.setPen(QPen(QColor('#2B3C50' if db == 0 else '#16202C'), 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            lbl = f'{db:+d}' if db != 0 else 'Δ0'
            p.setPen(QColor('#64778B'))
            p.drawText(int(pad_l - fm.horizontalAdvance(lbl) - 6), int(yy + fm.ascent() / 2 - 1), lbl)

        for freq, lbl in self._GRID_FREQS:
            xx = self._log_x(freq, pad_l, gw)
            p.setPen(QPen(QColor('#16202C'), 1.0))
            p.drawLine(QPointF(xx, pad_t), QPointF(xx, pad_t + top_h))
            p.drawLine(QPointF(xx, bot_top), QPointF(xx, bot_top + bot_h))
            p.setPen(QColor('#64778B'))
            p.drawText(int(xx - fm.horizontalAdvance(lbl) / 2.0), int(h - 5), lbl)

        cutoff = int(self._data.get('source_cutoff_hz') or 20000)
        if 10000 <= cutoff < 19500:
            cx = self._log_x(float(cutoff), pad_l, gw)
            p.setPen(QPen(QColor('#B98E4B'), 1.0, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(cx, pad_t), QPointF(cx, pad_t + top_h))

        # Shade area directly between Gốc and Sau xử lý (FabFilter Pro-Q style)
        if self._show_orig and self._show_proc:
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(len(freqs) - 1):
                x0 = self._log_x(freqs[i], pad_l, gw)
                x1 = self._log_x(freqs[i + 1], pad_l, gw)
                o0, o1 = _y_top(orig[i]), _y_top(orig[i + 1])
                p0, p1 = _y_top(proc[i]), _y_top(proc[i + 1])
                boost = (proc[i] + proc[i + 1]) >= (orig[i] + orig[i + 1])
                p.setBrush(QBrush(QColor(94, 217, 184, 52) if boost else QColor(240, 184, 102, 46)))
                p.drawPolygon(QPolygonF([QPointF(x0, p0), QPointF(x1, p1), QPointF(x1, o1), QPointF(x0, o0)]))

        if self._show_proc:
            self._draw_series(p, freqs, proc, lambda f: self._log_x(f, pad_l, gw), _y_top, COLOR_PROC, 2.0)

        if self._show_orig:
            overlapped = self._show_proc and self._match_level and float(self._data.get('tonal_rms_db', 0.0)) <= 0.15
            self._draw_series(
                p, freqs, orig, lambda f: self._log_x(f, pad_l, gw), _y_top,
                COLOR_ORIG, 1.75, dashed=overlapped,
            )

        if delta and self._show_proc:
            self._draw_series(p, freqs, delta, lambda f: self._log_x(f, pad_l, gw), _y_bot, COLOR_PROC, 1.7, fill_base=_y_bot(0.0))
        if self._show_orig:
            p.setPen(QPen(QColor(COLOR_ORIG), 1.1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(pad_l, _y_bot(0.0)), QPointF(w - pad_r, _y_bot(0.0)))

        legend = []
        if self._show_orig:
            legend.append((COLOR_ORIG, 'Gốc (Pre)'))
        if self._show_proc:
            legend.append((COLOR_PROC, 'Sau xử lý (Post)'))
        self._paint_legend(p, w - pad_r, 14, legend, fm)

        if self._hover_pos is not None and pad_l <= self._hover_pos.x() <= (w - pad_r):
            hx = float(self._hover_pos.x())
            hf = self._x_to_log_freq(hx, pad_l, gw)
            idx = min(range(len(freqs)), key=lambda i: abs(freqs[i] - hf))
            f_txt = f'{freqs[idx] / 1000.0:.2f} kHz' if freqs[idx] >= 1000 else f'{freqs[idx]:.0f} Hz'
            d_val = delta[idx] if idx < len(delta) else 0.0
            dot_y = _y_top(proc[idx] if self._show_proc else orig[idx])
            self._paint_crosshair(
                p, hx, pad_t, pad_t + top_h, dot_y,
                f'{f_txt}  |  Gốc {orig[idx]:.1f}  ·  Sau {proc[idx]:.1f} dB  (Δ {d_val:+.2f} dB)',
                pad_l, fm,
            )

    def _paint_transfer(self, p: QPainter, w: float, h: float, fm):
        freqs = self._data.get('freqs_hz') or []
        mag = self._data.get('lab_transfer_db') or []
        phase = self._data.get('lab_phase_deg') or []
        if not freqs or not mag:
            return

        pad_l = max(44.0, float(fm.horizontalAdvance('-150') + 12))
        pad_r = 16.0
        pad_t = max(26.0, float(fm.height() + 12))
        pad_b = max(22.0, float(fm.height() + 8))
        gap = 12.0
        usable_h = max(60.0, h - pad_t - pad_b - gap)
        top_h = usable_h * 0.64
        bot_top = pad_t + top_h + gap
        bot_h = usable_h - top_h
        gw = max(40.0, w - pad_l - pad_r)

        max_m = max((abs(float(v)) for v in mag), default=0.0)
        y_lim = 6.0 if max_m <= 5.0 else 15.0
        ticks = (6, 3, 0, -3, -6) if y_lim == 6.0 else (15, 7, 0, -7, -15)

        def _y_mag(db: float) -> float:
            c = max(-y_lim, min(y_lim, float(db)))
            return pad_t + (1.0 - (c + y_lim) / (2.0 * y_lim)) * top_h

        def _y_ph(deg: float) -> float:
            c = max(-90.0, min(90.0, float(deg)))
            return bot_top + (1.0 - (c + 90.0) / 180.0) * bot_h

        for db in ticks:
            yy = _y_mag(float(db))
            p.setPen(QPen(QColor('#2B3C50' if db == 0 else '#16202C'), 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            lbl = f'{db:+d}' if db != 0 else '0 dB'
            p.setPen(QColor('#64778B'))
            p.drawText(int(pad_l - fm.horizontalAdvance(lbl) - 6), int(yy + fm.ascent() / 2 - 1), lbl)

        for deg in (90, 0, -90):
            yy = _y_ph(float(deg))
            p.setPen(QPen(QColor('#2B3C50' if deg == 0 else '#16202C'), 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            lbl = f'{deg:+d}°' if deg != 0 else '0°'
            p.setPen(QColor('#64778B'))
            p.drawText(int(pad_l - fm.horizontalAdvance(lbl) - 6), int(yy + fm.ascent() / 2 - 1), lbl)

        for freq, lbl in self._GRID_FREQS:
            xx = self._log_x(freq, pad_l, gw)
            p.setPen(QPen(QColor('#16202C'), 1.0))
            p.drawLine(QPointF(xx, pad_t), QPointF(xx, pad_t + top_h))
            p.drawLine(QPointF(xx, bot_top), QPointF(xx, bot_top + bot_h))
            p.setPen(QColor('#64778B'))
            p.drawText(int(xx - fm.horizontalAdvance(lbl) / 2.0), int(h - 5), lbl)

        if self._show_proc:
            self._draw_series(p, freqs, mag, lambda f: self._log_x(f, pad_l, gw), _y_mag, COLOR_PROC, 2.1, fill_base=_y_mag(0.0))
            if phase:
                self._draw_series(p, freqs, phase, lambda f: self._log_x(f, pad_l, gw), _y_ph, COLOR_PHASE, 1.6)

        if self._show_orig:
            pen_ref = QPen(QColor(COLOR_ORIG), 1.5, Qt.PenStyle.DashLine)
            p.setPen(pen_ref)
            p.drawLine(QPointF(pad_l, _y_mag(0.0)), QPointF(w - pad_r, _y_mag(0.0)))
            p.drawLine(QPointF(pad_l, _y_ph(0.0)), QPointF(w - pad_r, _y_ph(0.0)))

        legend = []
        if self._show_orig:
            legend.append((COLOR_ORIG, 'Gốc (0 dB)'))
        if self._show_proc:
            legend.append((COLOR_PROC, 'Biên độ |H(f)|'))
            legend.append((COLOR_PHASE, 'Pha ∠H(f)'))
        self._paint_legend(p, w - pad_r, 14, legend, fm)

        if self._hover_pos is not None and pad_l <= self._hover_pos.x() <= (w - pad_r):
            hx = float(self._hover_pos.x())
            hf = self._x_to_log_freq(hx, pad_l, gw)
            idx = min(range(len(freqs)), key=lambda i: abs(freqs[i] - hf))
            f_txt = f'{freqs[idx] / 1000.0:.2f} kHz' if freqs[idx] >= 1000 else f'{freqs[idx]:.0f} Hz'
            ph_v = phase[idx] if idx < len(phase) else 0.0
            dot_y = _y_mag(mag[idx] if self._show_proc else 0.0)
            self._paint_crosshair(
                p, hx, pad_t, pad_t + top_h, dot_y,
                f'{f_txt}  |  |H| {mag[idx]:+.2f} dB  ·  Pha {ph_v:+.1f}°  (Gốc 0.00 dB)',
                pad_l, fm,
            )

    def _paint_peaks(self, p: QPainter, w: float, h: float, fm):
        orig_env = self._data.get('orig_env_db') or []
        proc_env = self._data.get('proc_env_db') or []
        if not orig_env or not proc_env:
            return

        pad_l = max(46.0, float(fm.horizontalAdvance('-150') + 12))
        pad_r = 16.0
        pad_t = max(26.0, float(fm.height() + 12))
        pad_b = max(22.0, float(fm.height() + 8))
        gw = max(40.0, w - pad_l - pad_r)
        gh = max(40.0, h - pad_t - pad_b)
        y_hi, y_lo = 3.0, -36.0

        def _x(i: int, n: int) -> float:
            return pad_l + (i / float(max(1, n - 1))) * gw

        def _y(db: float) -> float:
            c = max(y_lo, min(y_hi, float(db)))
            return pad_t + (1.0 - (c - y_lo) / (y_hi - y_lo)) * gh

        for db in (0, -6, -12, -24, -36):
            yy = _y(float(db))
            p.setPen(QPen(QColor(COLOR_CLIP if db == 0 else '#16202C'), 1.1 if db == 0 else 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            lbl = f'{db:+d}' if db > 0 else f'{db}'
            p.setPen(QColor(COLOR_CLIP if db == 0 else '#64778B'))
            p.drawText(int(pad_l - fm.horizontalAdvance(lbl) - 6), int(yy + fm.ascent() / 2 - 1), lbl)

        safe_y = _y(-1.0)
        p.setPen(QPen(QColor('#3E7E6B'), 1.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(pad_l, safe_y), QPointF(w - pad_r, safe_y))

        dur = float(self._data.get('window_dur_sec') or 0.0)
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            xx = pad_l + frac * gw
            p.setPen(QPen(QColor('#16202C'), 1.0))
            p.drawLine(QPointF(xx, pad_t), QPointF(xx, pad_t + gh))
            lbl = f'{dur * frac:.1f}s' if dur > 0 else f'{int(frac * 100)}%'
            p.setPen(QColor('#64778B'))
            tx = max(int(pad_l), min(int(w - pad_r - fm.horizontalAdvance(lbl)), int(xx - fm.horizontalAdvance(lbl) / 2.0)))
            p.drawText(tx, int(h - 5), lbl)

        n_p = len(proc_env)
        if self._show_proc:
            p_pts = [QPointF(_x(i, n_p), _y(v)) for i, v in enumerate(proc_env)]
            p_path = QPainterPath()
            p_path.moveTo(p_pts[0])
            for pt in p_pts[1:]:
                p_path.lineTo(pt)
            p.setPen(QPen(QColor(COLOR_PROC), 2.0))
            p.drawPath(p_path)

        n_o = len(orig_env)
        if self._show_orig:
            o_pts = [QPointF(_x(i, n_o), _y(v)) for i, v in enumerate(orig_env)]
            o_path = QPainterPath()
            o_path.moveTo(o_pts[0])
            for pt in o_pts[1:]:
                o_path.lineTo(pt)
            overlap = self._show_proc and not self._data.get('profile_enabled', True)
            pen_o = QPen(QColor(COLOR_ORIG), 1.75)
            if overlap:
                pen_o.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen_o)
            p.drawPath(o_path)

            p.setBrush(QBrush(QColor(COLOR_CLIP)))
            p.setPen(Qt.PenStyle.NoPen)
            for pt, val in zip(o_pts, orig_env):
                if val > 0.0:
                    p.drawEllipse(pt, 1.8, 1.8)
            p.setBrush(Qt.BrushStyle.NoBrush)

        legend = [(COLOR_CLIP, 'Trần 0 dBTP')]
        if self._show_orig:
            legend.append((COLOR_ORIG, 'Đỉnh gốc (Pre)'))
        if self._show_proc:
            legend.append((COLOR_PROC, 'Sau xử lý (Post)'))
        self._paint_legend(p, w - pad_r, 14, legend, fm)

        if self._hover_pos is not None and pad_l <= self._hover_pos.x() <= (w - pad_r):
            hx = float(self._hover_pos.x())
            idx = min(n_p - 1, max(0, int(round((hx - pad_l) / max(1.0, gw) * (n_p - 1)))))
            t_s = dur * (idx / float(max(1, n_p - 1)))
            dot_y = _y(proc_env[idx] if self._show_proc else orig_env[idx])
            self._paint_crosshair(
                p, _x(idx, n_p), pad_t, pad_t + gh, dot_y,
                f'{t_s:.2f}s  |  Gốc {orig_env[idx]:+.2f} dBTP  ·  Sau {proc_env[idx]:+.2f} dBTP',
                pad_l, fm,
            )

    def _paint_thd_fft(self, p: QPainter, w: float, h: float, fm):
        freqs = self._data.get('thd_fft_freqs') or []
        proc_vals = self._data.get('thd_fft_db') or []
        ref_vals = self._data.get('ref_thd_fft_db') or []
        if not freqs or not proc_vals:
            return

        pad_l = max(46.0, float(fm.horizontalAdvance('-150') + 12))
        pad_r = 16.0
        pad_t = max(26.0, float(fm.height() + 12))
        pad_b = max(22.0, float(fm.height() + 8))
        gw = max(40.0, w - pad_l - pad_r)
        gh = max(40.0, h - pad_t - pad_b)
        y_hi, y_lo = 6.0, -155.0

        def _y(db: float) -> float:
            c = max(y_lo, min(y_hi, float(db)))
            return pad_t + (1.0 - (c - y_lo) / (y_hi - y_lo)) * gh

        for db in (0, -30, -60, -90, -120, -150):
            yy = _y(float(db))
            p.setPen(QPen(QColor('#16202C'), 1.0))
            p.drawLine(QPointF(pad_l, yy), QPointF(w - pad_r, yy))
            lbl = f'{db}'
            p.setPen(QColor('#64778B'))
            p.drawText(int(pad_l - fm.horizontalAdvance(lbl) - 6), int(yy + fm.ascent() / 2 - 1), lbl)

        for freq, lbl in self._GRID_FREQS:
            xx = self._log_x(freq, pad_l, gw)
            p.setPen(QPen(QColor('#16202C'), 1.0))
            p.drawLine(QPointF(xx, pad_t), QPointF(xx, pad_t + gh))
            p.setPen(QColor('#64778B'))
            p.drawText(int(xx - fm.horizontalAdvance(lbl) / 2.0), int(h - 5), lbl)

        # Subtle harmonic guide ticks H2-H5
        for h_f, h_lbl in ((2000, 'H2'), (3000, 'H3'), (4000, 'H4'), (5000, 'H5')):
            hx_m = self._log_x(float(h_f), pad_l, gw)
            p.setPen(QPen(QColor('#243242'), 1.0, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(hx_m, pad_t + 16), QPointF(hx_m, pad_t + gh))
            p.setPen(QColor('#4D6075'))
            p.drawText(int(hx_m - 6), int(pad_t + 12), h_lbl)

        if self._show_proc:
            self._draw_series(p, freqs, proc_vals, lambda f: self._log_x(f, pad_l, gw), _y, COLOR_PROC, 1.9, fill_base=pad_t + gh)

        if self._show_orig and ref_vals:
            med_p = sorted(proc_vals)[len(proc_vals) // 2]
            med_r = sorted(ref_vals)[len(ref_vals) // 2]
            is_flat = self._show_proc and abs(float(med_p) - float(med_r)) < 3.0
            self._draw_series(
                p, freqs, ref_vals, lambda f: self._log_x(f, pad_l, gw), _y,
                COLOR_ORIG, 1.5, dashed=is_flat,
            )

        legend = []
        if self._show_orig and ref_vals:
            legend.append((COLOR_ORIG, f'Gốc ({self._data.get("ref_bit_depth", 24)}-bit)'))
        if self._show_proc:
            fmt = '32-bit Int' if self._data.get('out_dtype') == 'int32' else '32-bit Float'
            legend.append((COLOR_PROC, f'Sau xử lý ({fmt})'))
        self._paint_legend(p, w - pad_r, 14, legend, fm)

        if self._hover_pos is not None and pad_l <= self._hover_pos.x() <= (w - pad_r):
            hx = float(self._hover_pos.x())
            hf = self._x_to_log_freq(hx, pad_l, gw)
            idx = min(range(len(freqs)), key=lambda i: abs(freqs[i] - hf))
            f_txt = f'{freqs[idx] / 1000.0:.2f} kHz' if freqs[idx] >= 1000 else f'{freqs[idx]:.0f} Hz'
            ref_v = ref_vals[idx] if idx < len(ref_vals) else -144.0
            dot_y = _y(proc_vals[idx] if self._show_proc else ref_v)
            self._paint_crosshair(
                p, hx, pad_t, pad_t + gh, dot_y,
                f'{f_txt}  |  Gốc {ref_v:.1f} dBFS  ·  Sau xử lý {proc_vals[idx]:.1f} dBFS',
                pad_l, fm,
            )

    @staticmethod
    def _draw_series(p: QPainter, freqs, vals, x_fn, y_fn, color: str, width: float,
                     fill_base: float | None = None, dashed: bool = False):
        pts = [QPointF(x_fn(f), y_fn(v)) for f, v in zip(freqs, vals)]
        if not pts:
            return
        if fill_base is not None:
            fill = QPainterPath()
            fill.moveTo(pts[0].x(), fill_base)
            for pt in pts:
                fill.lineTo(pt)
            fill.lineTo(pts[-1].x(), fill_base)
            fill.closeSubpath()
            p.fillPath(fill, QBrush(QColor(94, 217, 184, 26)))
        path = QPainterPath()
        path.moveTo(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        pen = QPen(QColor(color), width)
        if dashed:
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([6.0, 4.0])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        p.drawPath(path)

    @staticmethod
    def _paint_crosshair(p: QPainter, hx: float, y_top: float, y_bot: float, dot_y: float, text: str, pad_l: float, fm):
        p.setPen(QPen(QColor('#38506B'), 1.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(hx, y_top), QPointF(hx, y_bot))
        p.setBrush(QBrush(QColor(COLOR_PROC)))
        p.setPen(QPen(QColor('#0B1017'), 1.5))
        p.drawEllipse(QPointF(hx, dot_y), 3.5, 3.5)

        tw = fm.horizontalAdvance(text) + 14
        ph = fm.height() + 6
        rx = int(pad_l + 6)
        ry = 4
        p.setBrush(QBrush(QColor(16, 23, 34, 235)))
        p.setPen(QPen(QColor('#2B3C50'), 1.0))
        p.drawRoundedRect(rx, ry, tw, ph, 5, 5)
        p.setPen(QColor('#EDF3FA'))
        p.drawText(rx + 7, ry + fm.ascent() + 3, text)

    @staticmethod
    def _paint_legend(p: QPainter, right_x: float, y: float, items: list[tuple[str, str]], fm):
        x = right_x
        for color, text in reversed(items):
            tw = fm.horizontalAdvance(text)
            x -= tw
            p.setPen(QColor('#A8B8CA'))
            p.drawText(int(x), int(y + fm.ascent() / 2 - 4), text)
            x -= 16
            p.setPen(QPen(QColor(color), 2.2))
            p.drawLine(QPointF(x, y), QPointF(x + 11, y))
            x -= 14


class AudioBenchmarkPage(QWidget):
    """2-Zone commercial analyzer tab: interactive dual-trace charts + Pre/Post measurement table & QC summary."""

    back_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._source_path = ''
        self._generation = 0
        self._worker: AudioBenchmarkWorker | None = None
        self._audition_gen = 0
        self._audition_worker: AuditionPrepWorker | None = None
        self._audition_cache_key: tuple | None = None
        self._audition_pair: dict | None = None
        self._last_result: dict | None = None
        self._last_profile: AudioProfile | None = None
        self._audition = BenchmarkAuditionEngine(volume_fn=self._current_output_volume)

        self.setObjectName('audioBenchmarkPage')
        self.setStyleSheet(FORM_STYLE + '''
            QWidget#audioBenchmarkPage { background: #0D1118; color: #EDF3FA; font-family: 'Segoe UI'; }
            QLabel { color: #EDF3FA; background: transparent; border: none; }
            QLabel#benchTitle { font-size: 20px; font-weight: 700; color: #EDF3FA; }
            QLabel#benchSource { font-size: 12px; color: #8FA2B7; }
            QFrame#benchCard { background: #141B25; border: 1px solid #202C3C; border-radius: 10px; }
            QLabel#cardSectionTitle { font-size: 12px; font-weight: 600; color: #8FA2B7; }
            QPushButton#segBtn { background: #101722; color: #8FA2B7; border: 1px solid #223042;
                border-radius: 7px; padding: 5px 11px; font-size: 12px; font-weight: 500; }
            QPushButton#segBtn:hover { color: #EDF3FA; background: #1A2432; }
            QPushButton#segBtn:checked { background: #19372F; color: #5ED9B8; border-color: #2D5A4E; font-weight: 600; }
            QLabel#verdictBadge { background: #19372F; color: #5ED9B8; border: 1px solid #2D5A4E;
                border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
            QLabel#verdictBadge[tone="warn"] { background: #362220; color: #F08A88; border-color: #6B3939; }
            QLabel#verdictBadge[tone="neutral"] { background: #1C2634; color: #AFC0D2; border-color: #314257; }
            QFrame#pillarTile { background: #0F151E; border: 1px solid #1E2A3A; border-radius: 8px; }
            QFrame#auditionBar { background: #0F151E; border: 1px solid #1E2A3A; border-radius: 8px; }
            QPushButton#abOrigBtn { background: #141B25; color: #A8B8CA; border: 1px solid #253344;
                border-radius: 7px; padding: 5px 12px; font-size: 12px; font-weight: 600; }
            QPushButton#abOrigBtn:checked { background: #342817; color: #F0B866; border-color: #7A5828; }
            QPushButton#abProcBtn { background: #141B25; color: #A8B8CA; border: 1px solid #253344;
                border-radius: 7px; padding: 5px 12px; font-size: 12px; font-weight: 600; }
            QPushButton#abProcBtn:checked { background: #16332B; color: #5ED9B8; border-color: #2D5A4E; }
            QFrame#tblDivider { background: #202C3C; max-height: 1px; border: none; }
            QScrollArea#benchScroll { background: transparent; border: none; }
            QWidget#benchScrollContent { background: transparent; border: none; }
            QScrollBar:vertical { background: #0D1118; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #263447; border-radius: 4px; min-height: 28px; }
            QScrollBar::handle:vertical:hover { background: #364A64; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QProgressBar { border: none; background: #1A2330; border-radius: 1px; }
            QProgressBar::chunk { background: #5ED9B8; }
        ''')

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # Header Toolbar
        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        self.btn_back = QPushButton('← Tùy chỉnh')
        self.btn_back.setFixedHeight(33)
        self.btn_back.clicked.connect(self.back_requested.emit)
        hdr.addWidget(self.btn_back)

        title = QLabel('Phân tích âm thanh')
        title.setObjectName('benchTitle')
        hdr.addWidget(title)
        hdr.addStretch()

        self.mode_combo = QComboBox()
        for text, key in (
            ('Cấu hình đang dùng', 'current'),
            ('Chuẩn Hi-Fi (Hợp nhất)', 'master_hifi'),
            ('Dawn Pro 2 · Aria 2', 'studio_dawn_aria2'),
            ('DAC Rời · Bit-Perfect', 'dac_bitperfect'),
            ('Nguyên bản', 'bit_pure'),
            ('YouTube', 'youtube'),
            ('Sống động', 'walkman_vivid'),
            ('Tắt (Bypass)', 'bypass'),
        ):
            self.mode_combo.addItem(text, key)
        self.mode_combo.setFixedHeight(33)
        self.mode_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mode_combo.setMinimumWidth(156)
        hdr.addWidget(self.mode_combo)

        self.btn_use_playing = QPushButton('Bài đang phát')
        self.btn_use_playing.setFixedHeight(33)
        self.btn_use_playing.clicked.connect(self._use_playing_or_library)
        hdr.addWidget(self.btn_use_playing)

        self.btn_pick_file = QPushButton('Chọn file…')
        self.btn_pick_file.setFixedHeight(33)
        button_icon(self.btn_pick_file, 'folder-open', 'Chọn file âm thanh', color=TEXT, size=14, icon_only=False)
        self.btn_pick_file.clicked.connect(self.pick_file_dialog)
        hdr.addWidget(self.btn_pick_file)

        self.btn_copy_report = QPushButton()
        self.btn_copy_report.setFixedSize(33, 33)
        button_icon(self.btn_copy_report, 'clipboard', 'Chép báo cáo đo kiểm', color=MUTED, size=15, icon_only=True)
        self.btn_copy_report.clicked.connect(self.copy_report_to_clipboard)
        self.btn_copy_report.setEnabled(False)
        hdr.addWidget(self.btn_copy_report)

        self.btn_run = QPushButton('Đo kiểm')
        self.btn_run.setProperty('role', 'primary')
        self.btn_run.setFixedHeight(33)
        button_icon(self.btn_run, 'play', 'Chạy đo kiểm', color=INK, size=13, icon_only=False)
        self.btn_run.clicked.connect(self.run_benchmark)
        hdr.addWidget(self.btn_run)
        root.addLayout(hdr)

        self.lbl_source = QLabel('Chưa chọn nguồn để đo kiểm.')
        self.lbl_source.setObjectName('benchSource')
        self.lbl_source.setWordWrap(True)
        self.lbl_source.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_source.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        root.addWidget(self.lbl_source)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setFixedHeight(2)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        root.addWidget(self.busy_bar)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName('benchScroll')
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        scroll_content.setObjectName('benchScrollContent')
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 2, 4)
        scroll_layout.setSpacing(10)

        # Zone 0: Plain-language Listener Comparison + 3 Visual Pillars + Gain-Matched A/B Audition
        summary_card = QFrame()
        summary_card.setObjectName('benchCard')
        summary_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(10)

        p_hdr = QHBoxLayout()
        p_hdr.setSpacing(10)
        self.lbl_plain_badge = QLabel('CHỜ ĐO KIỂM')
        self.lbl_plain_badge.setObjectName('verdictBadge')
        self.lbl_plain_badge.setProperty('tone', 'neutral')
        self.lbl_plain_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        p_hdr.addWidget(self.lbl_plain_badge, alignment=Qt.AlignmentFlag.AlignTop)

        self.lbl_plain_conclusion = QLabel(
            'Chọn bài nhạc rồi bấm Đo kiểm để biết ngay bản sau xử lý đang sạch hơn hay kém hơn bản gốc.'
        )
        self.lbl_plain_conclusion.setStyleSheet('font-size: 13px; font-weight: 600; color: #EDF3FA;')
        self.lbl_plain_conclusion.setWordWrap(True)
        self.lbl_plain_conclusion.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_plain_conclusion.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        p_hdr.addWidget(self.lbl_plain_conclusion, stretch=1)
        summary_layout.addLayout(p_hdr)

        pillars_row = QHBoxLayout()
        pillars_row.setSpacing(8)
        self._pillar_widgets: list[tuple[QLabel, QLabel, QLabel]] = []
        for default_title in ('Độ trong trẻo', 'Độ nảy & Chi tiết', 'Màu âm & Không gian'):
            tile = QFrame()
            tile.setObjectName('pillarTile')
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            t_lay = QVBoxLayout(tile)
            t_lay.setContentsMargins(12, 9, 12, 9)
            t_lay.setSpacing(3)

            top_r = QHBoxLayout()
            top_r.setSpacing(6)
            lbl_t = QLabel(default_title)
            lbl_t.setStyleSheet('font-size: 11px; color: #8FA2B7; font-weight: 600;')
            lbl_v = QLabel('—')
            lbl_v.setStyleSheet('font-size: 12px; color: #EDF3FA; font-weight: 700;')
            lbl_v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            top_r.addWidget(lbl_t)
            top_r.addStretch()
            top_r.addWidget(lbl_v)
            t_lay.addLayout(top_r)

            lbl_d = QLabel('Chưa có dữ liệu đo.')
            lbl_d.setStyleSheet('font-size: 12px; color: #9AAABC;')
            lbl_d.setWordWrap(True)
            lbl_d.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            lbl_d.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            t_lay.addWidget(lbl_d)
            pillars_row.addWidget(tile, stretch=1)
            self._pillar_widgets.append((lbl_t, lbl_v, lbl_d))
        summary_layout.addLayout(pillars_row)

        aud_bar = QFrame()
        aud_bar.setObjectName('auditionBar')
        aud_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        aud_lay = QHBoxLayout(aud_bar)
        aud_lay.setContentsMargins(12, 8, 12, 8)
        aud_lay.setSpacing(8)

        self.btn_audition_toggle = QPushButton('Nghe thử A/B')
        self.btn_audition_toggle.setProperty('role', 'primary')
        self.btn_audition_toggle.setFixedHeight(31)
        self.btn_audition_toggle.setEnabled(False)
        button_icon(self.btn_audition_toggle, 'play', 'Nghe đối chiếu A/B', color=INK, size=13, icon_only=False)
        self.btn_audition_toggle.clicked.connect(self.toggle_audition)
        aud_lay.addWidget(self.btn_audition_toggle)

        self.btn_ab_orig = QPushButton('A · Bản gốc')
        self.btn_ab_orig.setObjectName('abOrigBtn')
        self.btn_ab_orig.setCheckable(True)
        self.btn_ab_orig.setFixedHeight(31)
        self.btn_ab_orig.clicked.connect(lambda: self._select_audition_branch('orig'))
        aud_lay.addWidget(self.btn_ab_orig)

        self.btn_ab_proc = QPushButton('B · Sau xử lý')
        self.btn_ab_proc.setObjectName('abProcBtn')
        self.btn_ab_proc.setCheckable(True)
        self.btn_ab_proc.setChecked(True)
        self.btn_ab_proc.setFixedHeight(31)
        self.btn_ab_proc.clicked.connect(lambda: self._select_audition_branch('proc'))
        aud_lay.addWidget(self.btn_ab_proc)

        self.cb_audition_match = QCheckBox('Khớp bằng âm lượng')
        self.cb_audition_match.setChecked(True)
        self.cb_audition_match.setStyleSheet('color: #B8C7D6; font-size: 12px;')
        self.cb_audition_match.setToolTip(
            'Tự cân độ to hai bản về ngang nhau để tai không bị đánh lừa rằng to hơn là hay hơn.'
        )
        self.cb_audition_match.toggled.connect(self._on_audition_match_toggled)
        aud_lay.addWidget(self.cb_audition_match)

        self.lbl_audition_hint = QLabel('Nghe trực tiếp hai bản ở cùng một độ to để tự cảm nhận bằng tai.')
        self.lbl_audition_hint.setStyleSheet('font-size: 11px; color: #7F93A8;')
        self.lbl_audition_hint.setWordWrap(True)
        self.lbl_audition_hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_audition_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        aud_lay.addWidget(self.lbl_audition_hint, stretch=1)
        summary_layout.addWidget(aud_bar)
        scroll_layout.addWidget(summary_card, stretch=0)

        # Zone 1: Full-width Interactive Analyzer Chart
        chart_card = QFrame()
        chart_card.setObjectName('benchCard')
        chart_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(14, 10, 14, 12)
        chart_layout.setSpacing(8)

        chart_hdr = QHBoxLayout()
        chart_hdr.setSpacing(6)
        self.btn_view_spec = QPushButton('Phổ tần số RTA')
        self.btn_view_transfer = QPushButton('Đáp tuyến · Pha')
        self.btn_view_peaks = QPushButton('Đỉnh True-Peak')
        self.btn_view_thd = QPushButton('Phổ 1 kHz THD+N')
        for i, btn in enumerate((self.btn_view_spec, self.btn_view_transfer, self.btn_view_peaks, self.btn_view_thd)):
            btn.setObjectName('segBtn')
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            chart_hdr.addWidget(btn)
        chart_hdr.addStretch()

        self.cb_show_orig = QCheckBox('Gốc')
        self.cb_show_orig.setChecked(True)
        self.cb_show_orig.setStyleSheet(f'color: {COLOR_ORIG}; font-weight: 600; font-size: 12px;')
        self.cb_show_proc = QCheckBox('Sau xử lý')
        self.cb_show_proc.setChecked(True)
        self.cb_show_proc.setStyleSheet(f'color: {COLOR_PROC}; font-weight: 600; font-size: 12px;')
        self.cb_match_level = QCheckBox('Khớp mức LUFS')
        self.cb_match_level.setChecked(True)
        self.cb_match_level.setStyleSheet('color: #9AAABC; font-size: 12px;')
        self.cb_match_level.setToolTip('Căn thẳng mức dải giữa để đối chiếu âm sắc khi bật cân bằng âm lượng.')
        for cb in (self.cb_show_orig, self.cb_show_proc, self.cb_match_level):
            chart_hdr.addWidget(cb)
        chart_layout.addLayout(chart_hdr)

        self.canvas = BenchmarkChartCanvas(chart_card)
        chart_layout.addWidget(self.canvas, stretch=1)
        scroll_layout.addWidget(chart_card, stretch=1)

        # Zone 2: Full-width Clinical QC Verdict Banner (Zero Narrow Column Wrapping)
        verdict_card = QFrame()
        verdict_card.setObjectName('benchCard')
        verdict_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        verdict_layout = QVBoxLayout(verdict_card)
        verdict_layout.setContentsMargins(16, 12, 16, 12)
        verdict_layout.setSpacing(8)

        v_hdr = QHBoxLayout()
        v_hdr.setSpacing(10)
        self.lbl_verdict_badge = QLabel('CHỜ ĐO')
        self.lbl_verdict_badge.setObjectName('verdictBadge')
        self.lbl_verdict_badge.setProperty('tone', 'neutral')
        self.lbl_verdict_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        v_hdr.addWidget(self.lbl_verdict_badge)

        self.lbl_verdict_headline = QLabel('Chọn bài hát và cấu hình rồi bấm Đo kiểm.')
        self.lbl_verdict_headline.setStyleSheet('font-size: 13px; font-weight: 600; color: #EDF3FA;')
        self.lbl_verdict_headline.setWordWrap(True)
        self.lbl_verdict_headline.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_verdict_headline.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        v_hdr.addWidget(self.lbl_verdict_headline, stretch=1)
        verdict_layout.addLayout(v_hdr)

        self.findings_layout = QVBoxLayout()
        self.findings_layout.setSpacing(5)
        verdict_layout.addLayout(self.findings_layout)

        div = QFrame()
        div.setObjectName('tblDivider')
        div.setFrameShape(QFrame.Shape.HLine)
        verdict_layout.addWidget(div)

        self.lbl_spec_footer = QLabel('Chuẩn đo: ITU-R BS.1770-4 · AES17 · 4× True-Peak')
        self.lbl_spec_footer.setStyleSheet('font-size: 11px; color: #7F93A8;')
        self.lbl_spec_footer.setWordWrap(True)
        self.lbl_spec_footer.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_spec_footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        verdict_layout.addWidget(self.lbl_spec_footer)
        scroll_layout.addWidget(verdict_card, stretch=0)

        # Zone 3: Full-width Standardized ITU-R / AES17 Comparison Table
        table_card = QFrame()
        table_card.setObjectName('benchCard')
        table_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        table_box = QVBoxLayout(table_card)
        table_box.setContentsMargins(16, 12, 16, 12)
        table_box.setSpacing(8)
        tbl_title = QLabel('Thông số đối chiếu chuẩn ITU-R / AES17 (Gốc vs Sau xử lý)')
        tbl_title.setObjectName('cardSectionTitle')
        table_box.addWidget(tbl_title)

        self.table_grid = QGridLayout()
        self.table_grid.setContentsMargins(0, 0, 0, 0)
        self.table_grid.setHorizontalSpacing(16)
        self.table_grid.setVerticalSpacing(6)
        self.table_grid.setColumnStretch(0, 3)
        self.table_grid.setColumnStretch(1, 2)
        self.table_grid.setColumnStretch(2, 2)
        self.table_grid.setColumnStretch(3, 2)
        table_box.addLayout(self.table_grid)
        scroll_layout.addWidget(table_card, stretch=0)

        self.scroll_area.setWidget(scroll_content)
        root.addWidget(self.scroll_area, stretch=1)

        self.btn_view_spec.clicked.connect(lambda: self._switch_chart('spectrum'))
        self.btn_view_transfer.clicked.connect(lambda: self._switch_chart('transfer'))
        self.btn_view_peaks.clicked.connect(lambda: self._switch_chart('peaks'))
        self.btn_view_thd.clicked.connect(lambda: self._switch_chart('thd_fft'))
        self.cb_show_orig.toggled.connect(self.canvas.set_show_orig)
        self.cb_show_proc.toggled.connect(self.canvas.set_show_proc)
        self.cb_match_level.toggled.connect(self.canvas.set_match_level)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        player = getattr(self.controller, 'player', None)
        if player is not None and hasattr(player, 'playbackStateChanged'):
            player.playbackStateChanged.connect(self._on_main_player_state)

    def _switch_chart(self, mode: str):
        mapping = {
            'spectrum': self.btn_view_spec,
            'transfer': self.btn_view_transfer,
            'peaks': self.btn_view_peaks,
            'thd_fft': self.btn_view_thd,
        }
        target = mode if mode in mapping else 'spectrum'
        for k, b in mapping.items():
            b.setChecked(k == target)
        self.cb_match_level.setVisible(target == 'spectrum')
        self.canvas.set_view_mode(target)

    def _on_mode_changed(self):
        if self._source_path and Path(self._source_path).is_file():
            self.run_benchmark()

    def _resolve_default_source(self) -> str:
        orig = getattr(self.controller, '_original', None)
        if orig is not None and hasattr(orig, 'isLocalFile') and orig.isLocalFile():
            local = orig.toLocalFile()
            if local and Path(local).is_file():
                return local
        win = getattr(self.controller, 'window', None)
        for attr in ('all_media_items', 'media_items'):
            for item in (getattr(win, attr, None) or ()):
                fp = getattr(item, 'file_path', None) or (item.get('file_path') if isinstance(item, dict) else '')
                if fp and Path(fp).is_file():
                    return str(fp)
        return ''

    def sync_default_source(self):
        if self._source_path and Path(self._source_path).is_file():
            return True
        found = self._resolve_default_source()
        if found:
            self.set_source_file(found, auto_run=False)
            return True
        return False

    def _use_playing_or_library(self):
        found = self._resolve_default_source()
        if found:
            self.set_source_file(found, auto_run=True)

    def pick_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Chọn file nhạc hoặc video để đo kiểm',
            '',
            'Media Files (*.mp3 *.flac *.m4a *.wav *.opus *.ogg *.webm *.mp4 *.mkv *.aac);;All Files (*)',
        )
        if path:
            self.set_source_file(path, auto_run=True)

    def set_source_file(self, path: str, auto_run: bool = False):
        clean = str(path or '').strip()
        if not clean:
            return
        self.stop_audition()
        self._audition_pair = None
        self._audition_cache_key = None
        self._source_path = clean
        self.lbl_source.setText(Path(clean).name)
        self.lbl_source.setToolTip(clean)
        if auto_run:
            self.run_benchmark()

    def _selected_profile(self) -> tuple[AudioProfile, int]:
        key = self.mode_combo.currentData()
        if key == 'current' or not key:
            return self.controller.profile, int(self.controller.target_lufs)
        if key == 'master_hifi':
            return adaptive_master_profile(self.controller._effective_device_key())
        prof, lufs = preset_profile(str(key))
        return prof, int(lufs if isinstance(lufs, int) else self.controller.target_lufs)

    def copy_report_to_clipboard(self):
        if not self._last_result:
            return False
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(self._last_result.get('report_text', ''))
        info = self._last_result.get('source_info') or {}
        codec = str(info.get('codec_name') or '?').upper()
        self.lbl_source.setText(f'Đã chép báo cáo đo kiểm ({Path(self._source_path).name} · {codec})')
        return True

    def run_benchmark(self):
        if not self._source_path or not Path(self._source_path).is_file():
            if not self.sync_default_source():
                self.lbl_verdict_headline.setText('Chưa có file hợp lệ. Bấm Chọn file… để kiểm tra.')
                return

        self.stop_audition()
        self._audition_pair = None
        self._audition_cache_key = None
        self.btn_audition_toggle.setEnabled(False)

        self._generation += 1
        gen = self._generation
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

        prof, lufs = self._selected_profile()
        self._last_profile = prof
        cached_info = None
        cached_meas = None
        try:
            sig = source_signature(self._source_path)
            entry = self.controller.loudness_cache.lookup_full(sig, 0)
            if entry:
                cached_info = entry.get('source_info')
                cached_meas = entry.get('measurement')
        except Exception:
            pass

        self.busy_bar.show()
        self.btn_run.setEnabled(False)
        self.lbl_source.setText(f'{Path(self._source_path).name} · Đang đo kiểm…')

        worker = AudioBenchmarkWorker(gen, self._source_path, prof, lufs, cached_info, cached_meas, self)
        worker.finished_ok.connect(self._on_benchmark_done)
        worker.failed.connect(self._on_benchmark_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_benchmark_failed(self, generation: int, msg: str):
        if generation != self._generation:
            return
        self._worker = None
        self.busy_bar.hide()
        self.btn_run.setEnabled(True)
        self.lbl_source.setText(Path(self._source_path).name)
        self.lbl_verdict_badge.setText('LỖI')
        self.lbl_verdict_badge.setProperty('tone', 'warn')
        self.lbl_verdict_badge.style().unpolish(self.lbl_verdict_badge)
        self.lbl_verdict_badge.style().polish(self.lbl_verdict_badge)
        self.lbl_verdict_headline.setText(f'Không đo được file này: {msg}')

    def _on_benchmark_done(self, generation: int, res: dict):
        if generation != self._generation:
            return
        self._worker = None
        self._last_result = res
        self.busy_bar.hide()
        self.btn_run.setEnabled(True)
        self.btn_copy_report.setEnabled(True)
        self.btn_audition_toggle.setEnabled(True)

        info = res.get('source_info') or {}
        codec = str(info.get('codec_name') or '?').upper()
        kbps = int(round((info.get('bit_rate') or 0) / 1000.0))
        rate_s = f'{kbps} kbps' if kbps > 0 else 'Lossless'
        fmt_s = '32-bit Int' if res['out_dtype'] == 'int32' else '32-bit Float'
        self.lbl_source.setText(
            f'{Path(res["source_path"]).name}  ·  {codec} {rate_s} · {res["in_sr"] / 1000.0:g} kHz  '
            f'→  {fmt_s} {res["out_sr"] / 1000.0:g} kHz  ({res["elapsed_ms"]} ms)'
        )

        self.canvas.set_result(res)

        verdict = res.get('verdict') or {}
        ls = verdict.get('listener_summary') or {}
        p_tag = str(ls.get('overall_tag') or verdict.get('badge') or 'XONG')
        p_tone = str(ls.get('overall_tone') or 'good')
        if p_tone not in ('good', 'warn', 'neutral'):
            p_tone = 'neutral'
        self.lbl_plain_badge.setText(p_tag)
        self.lbl_plain_badge.setProperty('tone', p_tone)
        self.lbl_plain_badge.style().unpolish(self.lbl_plain_badge)
        self.lbl_plain_badge.style().polish(self.lbl_plain_badge)
        self.lbl_plain_conclusion.setText(str(ls.get('plain_conclusion') or verdict.get('headline') or ''))

        pillar_colors = {'good': COLOR_PROC, 'warn': '#F08A88', 'neutral': COLOR_ORIG}
        for widgets, item in zip(self._pillar_widgets, ls.get('pillars') or ()):
            lbl_t, lbl_v, lbl_d = widgets
            lbl_t.setText(str(item.get('title') or ''))
            lbl_v.setText(str(item.get('verdict') or '—'))
            lbl_v.setStyleSheet(
                f'font-size: 12px; font-weight: 700; color: {pillar_colors.get(item.get("tone"), "#EDF3FA")};'
            )
            lbl_d.setText(str(item.get('detail') or ''))

        self.lbl_audition_hint.setText(
            'Bấm "Nghe thử A/B" để nghe cùng một độ to giữa Bản gốc (A) và Sau xử lý (B).'
        )

        badge = str(verdict.get('badge') or 'XONG')
        tone = 'warn' if 'LƯU Ý' in badge else ('neutral' if ('NGUYÊN GỐC' in badge or 'BYPASS' in badge) else 'good')
        self.lbl_verdict_badge.setText(badge)
        self.lbl_verdict_badge.setProperty('tone', tone)
        self.lbl_verdict_badge.style().unpolish(self.lbl_verdict_badge)
        self.lbl_verdict_badge.style().polish(self.lbl_verdict_badge)
        self.lbl_verdict_headline.setText(str(verdict.get('headline') or ''))

        while self.findings_layout.count():
            w = self.findings_layout.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

        dot_colors = {'good': COLOR_PROC, 'warn': '#F08A88', 'neutral': COLOR_ORIG}
        for f in verdict.get('findings') or ():
            row = QWidget()
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            h_lay = QHBoxLayout(row)
            h_lay.setContentsMargins(0, 1, 0, 1)
            h_lay.setSpacing(8)

            dot_wrap = QVBoxLayout()
            dot_wrap.setContentsMargins(0, 5, 0, 0)
            dot_wrap.setSpacing(0)
            dot = QLabel()
            dot.setFixedSize(7, 7)
            dot.setStyleSheet(f'border-radius: 3px; background: {dot_colors.get(f.get("level"), COLOR_PROC)};')
            dot_wrap.addWidget(dot)
            dot_wrap.addStretch()

            title_txt = html.escape(str(f.get('title', '')))
            detail_txt = html.escape(str(f.get('detail', '')))
            lbl_line = QLabel(
                f'<span style="color:#EDF3FA; font-weight:600;">{title_txt}:</span> '
                f'<span style="color:#9AAABC;">{detail_txt}</span>'
            )
            lbl_line.setTextFormat(Qt.TextFormat.RichText)
            lbl_line.setStyleSheet('font-size: 12px;')
            lbl_line.setWordWrap(True)
            lbl_line.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            lbl_line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

            h_lay.addLayout(dot_wrap)
            h_lay.addWidget(lbl_line, stretch=1)
            self.findings_layout.addWidget(row)

        cutoff_hz = int(res.get('source_cutoff_hz') or 20000)
        bw_s = f'{cutoff_hz / 1000.0:.1f} kHz (Hi-Res)' if cutoff_hz >= 24000 else f'{cutoff_hz / 1000.0:.1f} kHz'
        noise_lbl = str(res.get('noise_floor_label') or f'-{float(res.get("snr_db", 144.0)):.1f} dBFS')
        self.lbl_spec_footer.setText(
            f'Định dạng: {codec} ({rate_s}) · Băng thông thực: {bw_s} · '
            f'Đầu ra: {fmt_s} {res["out_sr"] / 1000.0:g} kHz · Nền nhiễu số: {noise_lbl}'
        )

        while self.table_grid.count():
            w = self.table_grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()

        headers = ('Thông số', 'Gốc (Pre)', 'Sau xử lý (Post)', 'Đánh giá')
        for c, h_txt in enumerate(headers):
            hl = QLabel(h_txt)
            col_c = COLOR_ORIG if c == 1 else (COLOR_PROC if c == 2 else '#7F93A8')
            hl.setStyleSheet(f'font-size: 11px; font-weight: 600; color: {col_c}; padding-bottom: 2px;')
            self.table_grid.addWidget(hl, 0, c)

        status_colors = {'good': COLOR_PROC, 'warn': '#F08A88', 'neutral': '#AFC0D2'}
        for r_idx, row in enumerate(res.get('comparison_rows') or (), start=1):
            c0 = QLabel(row['metric'])
            c0.setStyleSheet('font-size: 12px; color: #D7E2EE;')
            c1 = QLabel(row['orig'])
            c1.setStyleSheet('font-size: 12px; color: #D9B477; font-family: Consolas;')
            c2 = QLabel(row['proc'])
            c2.setStyleSheet('font-size: 12px; color: #EDF3FA; font-family: Consolas;')
            c3 = QLabel(row['status'])
            c3.setStyleSheet(f'font-size: 12px; font-weight: 600; color: {status_colors.get(row.get("tone"), "#AFC0D2")};')
            for col_i, w in enumerate((c0, c1, c2, c3)):
                self.table_grid.addWidget(w, r_idx, col_i)

    def _current_output_volume(self) -> tuple[float, bool]:
        vol = float(self.controller.volume()) if hasattr(self.controller, 'volume') else 0.5
        win = getattr(self.controller, 'window', None)
        ao = getattr(win, 'audio_output', None)
        muted = bool(ao.isMuted()) if ao is not None and hasattr(ao, 'isMuted') else False
        return vol, muted

    def _on_main_player_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState and (
            self._audition.is_playing() or self._audition_worker is not None
        ):
            self.stop_audition()

    def _select_audition_branch(self, branch: str):
        is_orig = (branch == 'orig')
        self.btn_ab_orig.setChecked(is_orig)
        self.btn_ab_proc.setChecked(not is_orig)
        self._audition.set_branch('orig' if is_orig else 'proc')
        if self._audition.is_playing():
            self._refresh_audition_hint()

    def _on_audition_match_toggled(self, checked: bool):
        self._audition.set_gain_matched(bool(checked))
        if self._audition.is_playing():
            self._refresh_audition_hint()

    def _refresh_audition_hint(self):
        pair = self._audition_pair or {}
        br = 'A · Bản gốc' if self.btn_ab_orig.isChecked() else 'B · Sau xử lý'
        if self.cb_audition_match.isChecked():
            m_lufs = pair.get('matched_lufs')
            d_lu = float(pair.get('delta_loudness_db') or 0.0)
            extra = f' · Đang cân bằng {m_lufs:.1f} LUFS (chênh gốc {d_lu:+.1f} LU)' if m_lufs is not None else ''
            self.lbl_audition_hint.setText(f'Đang phát {br}{extra}.')
        else:
            self.lbl_audition_hint.setText(f'Đang phát {br} (chế độ âm lượng gốc, không bù dB).')

    def toggle_audition(self):
        if self._audition.is_playing() or self._audition_worker is not None:
            self.stop_audition()
            return
        if not self._last_result:
            return
        player = getattr(self.controller, 'player', None)
        if player is not None and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()

        prof = self._last_profile if self._last_profile is not None else self._selected_profile()[0]
        res = self._last_result
        key = (
            res.get('source_path'),
            prof,
            float(res.get('exact_gain_db', res.get('gain_db', 0.0))),
            float(res.get('window_start_sec', 0.0)),
        )
        if self._audition_pair is not None and self._audition_cache_key == key:
            self._begin_audition_playback(self._audition_pair)
            return

        self._audition_gen += 1
        gen = self._audition_gen
        self.btn_audition_toggle.setText('Đang chuẩn bị…')
        self.btn_audition_toggle.setEnabled(False)
        self.lbl_audition_hint.setText('Đang dựng luồng nghe thử A/B trong RAM (0 MB ổ cứng)…')
        worker = AuditionPrepWorker(
            gen,
            str(res['source_path']),
            prof,
            res.get('source_info'),
            float(res.get('exact_gain_db', res.get('gain_db', 0.0))),
            float(res.get('window_start_sec', 0.0)),
            float(res.get('window_dur_sec', 8.0) or 8.0),
            preferred_device=str(getattr(prof, 'output_device', '') or ''),
            parent=self,
        )
        worker.ready.connect(self._on_audition_ready)
        worker.failed.connect(self._on_audition_failed)
        worker.finished.connect(worker.deleteLater)
        self._audition_worker = worker
        worker.start()

    def _on_audition_ready(self, generation: int, pair: dict):
        if generation != self._audition_gen:
            return
        self._audition_worker = None
        self.btn_audition_toggle.setEnabled(True)
        res = self._last_result or {}
        prof = self._last_profile if self._last_profile is not None else self._selected_profile()[0]
        self._audition_cache_key = (
            res.get('source_path'),
            prof,
            float(res.get('exact_gain_db', res.get('gain_db', 0.0))),
            float(res.get('window_start_sec', 0.0)),
        )
        self._audition_pair = pair
        self._begin_audition_playback(pair)

    def _on_audition_failed(self, generation: int, msg: str):
        if generation != self._audition_gen:
            return
        self._audition_worker = None
        self.btn_audition_toggle.setEnabled(bool(self._last_result))
        self.btn_audition_toggle.setText('Nghe thử A/B')
        button_icon(self.btn_audition_toggle, 'play', 'Nghe đối chiếu A/B', color=INK, size=13, icon_only=False)
        self.lbl_audition_hint.setText(f'Không phát thử được: {msg}')

    def _begin_audition_playback(self, pair: dict):
        branch = 'orig' if self.btn_ab_orig.isChecked() else 'proc'
        matched = self.cb_audition_match.isChecked()
        pref = str(getattr(self._last_profile, 'output_device', '') or '')
        try:
            self._audition.start(pair, branch=branch, gain_matched=matched, preferred_device=pref)
            self.btn_audition_toggle.setText('Dừng nghe')
            button_icon(self.btn_audition_toggle, 'square', 'Dừng nghe thử A/B', color=INK, size=12, icon_only=False)
            self._refresh_audition_hint()
        except Exception as err:
            self.btn_audition_toggle.setText('Nghe thử A/B')
            button_icon(self.btn_audition_toggle, 'play', 'Nghe đối chiếu A/B', color=INK, size=13, icon_only=False)
            self.lbl_audition_hint.setText(f'Thiết bị âm thanh đang bận: {err}')

    def stop_audition(self):
        self._audition_gen += 1
        if self._audition_worker is not None:
            self._audition_worker.stop()
            self._audition_worker = None
        self._audition.stop()
        if hasattr(self, 'btn_audition_toggle'):
            self.btn_audition_toggle.setEnabled(bool(self._last_result))
            self.btn_audition_toggle.setText('Nghe thử A/B')
            button_icon(self.btn_audition_toggle, 'play', 'Nghe đối chiếu A/B', color=INK, size=13, icon_only=False)
            if self._last_result:
                self.lbl_audition_hint.setText(
                    'Bấm "Nghe thử A/B" để nghe cùng một độ to giữa Bản gốc (A) và Sau xử lý (B).'
                )

    def minimumSizeHint(self) -> QSize:
        return QSize(460, 300)

    def hideEvent(self, event):
        self.stop_audition()
        super().hideEvent(event)

    def shutdown(self):
        self.stop_audition()
        self._generation += 1
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait()
            self._worker = None
