"""Isolated dual-stream YouTube Online playback controller (4K Video + 64-bit Hi-Fi WASAPI Audio + CC sync).

Zero modifications to existing `AudioStreamEngine` or offline `MainWindow` media player:
subclasses `AudioStreamEngine` to add FFmpeg HTTP reconnect/headers support while inheriting
100% of BoTube's 64-bit DSP, Parametric EQ, Minimum-Phase Hi-Res Upsampling, TPDF Dither,
MMCSS Pro Audio kernel priority, and WASAPI Shared/Exclusive DAC output.
"""
from __future__ import annotations

import bisect
import logging
import os
import subprocess
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtWidgets import QWidget

from core.audio_effects import find_tool
from core.audio_profile import AudioProfile
from core.audio_stream_engine import AudioStreamEngine, is_stream_engine_available
from core.youtube_online_client import OnlineSubtitleCue, ResolvedStream

logger = logging.getLogger(__name__)


class OnlineVideoSurface(QWidget):
    """Hardware-friendly QVideoSink surface that scrolls smoothly, clips cleanly & composites CC overlays."""

    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sink = QVideoSink(self)
        self._frame: QVideoFrame | None = None
        self._sink.videoFrameChanged.connect(self._on_frame_changed)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(210)
        self._click_timer.timeout.connect(self.clicked.emit)

    def videoSink(self) -> QVideoSink:
        return self._sink

    def clear_frame(self) -> None:
        self._frame = None
        self.update()

    def _on_frame_changed(self, frame: QVideoFrame) -> None:
        if frame.isValid():
            self._frame = QVideoFrame(frame)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#05080D"))
        frame = self._frame
        if frame is not None and frame.isValid():
            fw = max(1, frame.width())
            fh = max(1, frame.height())
            ww = max(1, self.width())
            wh = max(1, self.height())
            scale = min(ww / float(fw), wh / float(fh))
            dw = fw * scale
            dh = fh * scale
            target = QRectF((ww - dw) * 0.5, (wh - dh) * 0.5, dw, dh)
            try:
                frame.paint(painter, target, QVideoFrame.PaintOptions())
            except Exception:
                img = frame.toImage()
                if not img.isNull():
                    painter.drawImage(target, img)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.start()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class OnlineAudioStreamEngine(AudioStreamEngine):
    """HTTP-resilient subclass of BoTube's 64-bit Hi-Fi AudioStreamEngine (0 edits to base class)."""

    def __init__(self, *, on_before_exclusive=None, on_after_exclusive=None):
        super().__init__(
            on_before_exclusive=on_before_exclusive,
            on_after_exclusive=on_after_exclusive,
        )
        self._http_headers: dict[str, str] = {}

    def set_http_headers(self, headers: dict[str, str] | None) -> None:
        with self._lock:
            self._http_headers = dict(headers or {})

    def has_reached_eof(self) -> bool:
        """Return True ONLY when the FFmpeg->WASAPI writer exited naturally at stream EOF."""
        with self._lock:
            if not self._playing or self._paused:
                return False
            thread = self._writer_thread
            cancel = self._cancel_event
            played = int(self._played_frames)
        if cancel is not None and cancel.is_set():
            return False
        if thread is None:
            return False
        return (not thread.is_alive()) and played > 0

    def is_buffering(self) -> bool:
        with self._lock:
            if not self._playing or self._paused:
                return False
            thread = self._writer_thread
            played = int(self._played_frames)
        return bool(thread is not None and thread.is_alive() and played == 0)

    def _spawn_ffmpeg(
        self,
        source_path: str,
        start_ms: int,
        track: int,
        filter_graph: str,
        out_sr: int = 48000,
    ) -> subprocess.Popen:
        src = str(source_path or "")
        is_http = src.startswith(("http://", "https://"))
        if not is_http:
            return super()._spawn_ffmpeg(src, start_ms, track, filter_graph, out_sr=out_sr)

        ffmpeg = find_tool("ffmpeg")
        cmd = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            "2",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-rw_timeout",
            "15000000",
        ]
        with self._lock:
            headers = dict(self._http_headers)
        ua = headers.get("User-Agent") or headers.get("user-agent")
        if ua:
            cmd.extend(["-user_agent", str(ua)])
        extra_hdrs = [
            f"{k}: {v}"
            for k, v in headers.items()
            if k.lower() not in ("user-agent", "accept-encoding", "connection", "host")
        ]
        if extra_hdrs:
            cmd.extend(["-headers", "\r\n".join(extra_hdrs) + "\r\n"])
        if start_ms > 20:
            cmd.extend(["-ss", f"{start_ms / 1000.0:.3f}"])
        cmd.extend([
            "-i",
            src,
            "-map",
            f"0:a:{int(track)}",
            "-vn",
            "-sn",
            "-dn",
            "-af",
            filter_graph,
            "-f",
            "f64le",
            "-ac",
            "2",
            "pipe:1",
        ])
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        buf_bytes = max(262144, self._chunk_frames_for_rate(out_sr) * 2 * 8 * 4)
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=buf_bytes,
            creationflags=flags,
        )


def pick_best_video_stream(stream: ResolvedStream, preferred_quality: str) -> tuple[str, dict | None]:
    """Select the closest available video quality bucket for a resolved YouTube stream."""
    buckets = stream.video_streams or {}
    if not buckets:
        if stream.progressive_url:
            return ("Auto", {"url": stream.progressive_url, "progressive": True})
        return ("", None)

    order = ["2160p", "1440p", "1080p", "720p", "480p", "360p"]
    pref = str(preferred_quality or "1080p").strip().lower()
    if pref in buckets:
        return (pref, buckets[pref])
    if pref == "auto":
        for cand in ("1080p", "720p", "1440p", "480p", "360p", "2160p"):
            if cand in buckets:
                return (cand, buckets[cand])
    if pref in order:
        idx = order.index(pref)
        # Prefer closest lower quality first (never unexpectedly jump up to 4K on a 720p setting)
        for cand in order[idx:] + list(reversed(order[:idx])):
            if cand in buckets:
                return (cand, buckets[cand])
    first_key = next(iter(buckets.keys()))
    return (first_key, buckets[first_key])


class YouTubeOnlinePlaybackController(QObject):
    """Self-contained online player coordinating 4K/1080p video, 64-bit WASAPI audio, and CC cues."""

    playback_starting = Signal()
    state_changed = Signal(bool)           # is_playing
    position_changed = Signal(int, int)    # pos_ms, duration_ms
    track_ended = Signal()
    subtitle_text_changed = Signal(str)
    audio_status_changed = Signal(str)
    buffering_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(
        self,
        video_widget: QWidget,
        *,
        profile_provider: Callable[[], AudioProfile] | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.video_widget = video_widget
        self._profile_provider = profile_provider

        self._qt_audio = QAudioOutput(self)
        self._qt_audio.setVolume(0.7)
        self._qt_player = QMediaPlayer(self)
        self._qt_player.setAudioOutput(self._qt_audio)
        if hasattr(self.video_widget, "videoSink") and isinstance(self.video_widget, OnlineVideoSurface):
            self._qt_player.setVideoSink(self.video_widget.videoSink())
        else:
            self._qt_player.setVideoOutput(self.video_widget)
        self._qt_player.mediaStatusChanged.connect(self._on_qt_media_status)
        self._qt_player.errorOccurred.connect(self._on_qt_error)

        self._hifi_engine: OnlineAudioStreamEngine | None = None
        if is_stream_engine_available():
            self._hifi_engine = OnlineAudioStreamEngine()

        self._stream: ResolvedStream | None = None
        self._audio_only = False
        self._quality = "1080p"
        self._active_quality = ""
        self._playback_rate = 1.0
        self._volume = 0.7
        self._muted = False
        self._using_hifi = False
        self._is_playing = False
        self._is_paused = False
        self._duration_ms = 0
        self._last_pos_ms = 0
        self._last_buffering = False
        self._eof_emitted = False
        self._video_start_pending_ms: int | None = None
        self._last_video_seek_mono = 0.0

        # Subtitle cue cache (fast O(log N) binary lookup, zero GUI allocations)
        self._sub_enabled = False
        self._cues: list[OnlineSubtitleCue] = []
        self._cue_starts: list[int] = []
        self._last_sub_text = ""

        # Authoritative 80ms sync clock (A/V drift guard + CC cue sync + EOF monitor)
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(80)
        self._clock_timer.timeout.connect(self._on_clock_tick)

    def _current_audio_profile(self) -> AudioProfile:
        if callable(self._profile_provider):
            try:
                prof = self._profile_provider()
                if isinstance(prof, AudioProfile):
                    return prof
            except Exception:
                pass
        return AudioProfile()

    @property
    def is_playing(self) -> bool:
        return self._is_playing and not self._is_paused

    @property
    def is_loaded(self) -> bool:
        return self._stream is not None

    @property
    def active_quality(self) -> str:
        return "Audio Hi-Fi" if self._audio_only else (self._active_quality or self._quality)

    def position_ms(self) -> int:
        if self._using_hifi and self._hifi_engine is not None:
            pos = int(self._hifi_engine.position_ms())
            if self._duration_ms > 0:
                return min(self._duration_ms, max(0, pos))
            return max(0, pos)
        if self._qt_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            return max(0, int(self._qt_player.position()))
        return max(0, self._last_pos_ms)

    def duration_ms(self) -> int:
        if self._duration_ms > 0:
            return self._duration_ms
        qt_dur = int(self._qt_player.duration())
        return max(0, qt_dur)

    # --- Public Playback Controls ---
    def load_and_play(
        self,
        stream: ResolvedStream,
        *,
        audio_only: bool | None = None,
        quality: str | None = None,
        start_ms: int = 0,
    ) -> None:
        self.stop(release_exclusive=False)
        self._stream = stream
        if audio_only is not None:
            self._audio_only = bool(audio_only)
        if quality is not None:
            self._quality = str(quality)
        self._duration_ms = max(0, int(round(float(stream.duration_sec or 0.0) * 1000)))
        self._last_pos_ms = max(0, int(start_ms))
        self._eof_emitted = False
        self._last_sub_text = ""
        self.subtitle_text_changed.emit("")
        self._start_playback_at(self._last_pos_ms)

    def _start_playback_at(self, start_ms: int) -> None:
        stream = self._stream
        if stream is None:
            return

        # Notify MainWindow to pause offline playback & free Exclusive DAC before we open WASAPI
        self.playback_starting.emit()

        pos_ms = max(0, int(start_ms))
        self._last_pos_ms = pos_ms
        self._eof_emitted = False

        want_hifi = (
            self._hifi_engine is not None
            and bool(stream.audio_url)
            and (not stream.is_live or self._audio_only)
        )

        hifi_ok = False
        if want_hifi and self._hifi_engine is not None:
            try:
                prof = self._current_audio_profile()
                self._hifi_engine.set_http_headers(stream.http_headers)
                self._hifi_engine.set_user_volume(self._volume, self._muted)
                src_info = {
                    "codec_name": stream.audio_codec or "opus",
                    "sample_rate": int(stream.audio_sr or 48000),
                    "channels": 2,
                    "bit_rate": int(round(float(stream.audio_abr or 128.0) * 1000)),
                    "duration": float(stream.duration_sec or 0.0),
                    "track": 0,
                }
                status = self._hifi_engine.start_or_reconfigure(
                    stream.audio_url,
                    pos_ms,
                    prof,
                    src_info,
                    0.0,
                    playback_rate=self._playback_rate,
                    track=0,
                    preferred_device_name=str(getattr(prof, "output_device", "") or ""),
                    paused=False,
                )
                hifi_ok = True
                self._using_hifi = True
                self._emit_audio_badge(status, stream)
            except Exception as err:
                logger.warning("Online Hi-Fi stream fallback to QtMultimedia: %s", err)
                hifi_ok = False

        if self._audio_only:
            self._qt_player.stop()
            self._qt_player.setSource(QUrl())
            self._active_quality = "Audio Hi-Fi"
            if not hifi_ok:
                # Fallback to Qt audio-only on direct audio or progressive URL
                fallback_url = stream.audio_url or stream.progressive_url
                if not fallback_url:
                    self.error_occurred.emit("Không tìm thấy luồng âm thanh khả dụng.")
                    return
                self._using_hifi = False
                self._qt_audio.setMuted(self._muted)
                self._qt_audio.setVolume(self._volume)
                self._qt_player.setSource(QUrl(fallback_url))
                self._qt_player.setPlaybackRate(self._playback_rate)
                self._video_start_pending_ms = pos_ms if pos_ms > 200 else None
                self._qt_player.play()
                self.audio_status_changed.emit("Standard Audio · Online")
        else:
            q_label, v_info = pick_best_video_stream(stream, self._quality)
            if v_info and v_info.get("url"):
                self._active_quality = q_label
                if hifi_ok:
                    # Dual-stream mode: Video via QtMultimedia (muted) + Hi-Fi Audio via 64-bit WASAPI!
                    self._qt_audio.setMuted(True)
                    self._qt_player.setSource(QUrl(str(v_info["url"])))
                    self._qt_player.setPlaybackRate(self._playback_rate)
                    self._video_start_pending_ms = pos_ms if pos_ms > 200 else None
                    self._qt_player.play()
                else:
                    # Fallback to progressive muxed stream on QtMultimedia
                    prog_url = stream.progressive_url or str(v_info["url"])
                    self._using_hifi = False
                    self._qt_audio.setMuted(self._muted)
                    self._qt_audio.setVolume(self._volume)
                    self._qt_player.setSource(QUrl(prog_url))
                    self._qt_player.setPlaybackRate(self._playback_rate)
                    self._video_start_pending_ms = pos_ms if pos_ms > 200 else None
                    self._qt_player.play()
                    self.audio_status_changed.emit(f"Standard · {q_label}")
            elif hifi_ok:
                # Audio available even if video track is missing
                self._active_quality = "Audio Hi-Fi"
            else:
                self.error_occurred.emit("Không tìm thấy luồng phát khả dụng cho video này.")
                return

        self._is_playing = True
        self._is_paused = False
        self._clock_timer.start()
        self.state_changed.emit(True)

    def _emit_audio_badge(self, status: dict, stream: ResolvedStream) -> None:
        mode = str(status.get("output_mode") or status.get("mode") or "shared")
        sr = int(status.get("sample_rate") or 48000)
        dtype = str(status.get("dtype") or "float32")
        sr_txt = f"{sr / 1000.0:.1f} kHz" if sr % 1000 else f"{sr // 1000} kHz"
        bits = {"int24": "24-bit", "int32": "32-bit", "int16": "16-bit"}.get(dtype, "32-bit Float")
        codec = (stream.audio_codec or "Opus").split(".")[0].upper()
        abr = f" {int(round(stream.audio_abr))}k" if stream.audio_abr > 0 else ""
        if mode == "exclusive":
            label = f"WASAPI Exclusive · {sr_txt} {bits} · {codec}{abr}"
        else:
            label = f"Hi-Fi 64-bit · {sr_txt} · {codec}{abr}"
        self.audio_status_changed.emit(label)

    def toggle_play_pause(self) -> None:
        if self._stream is None:
            return
        if self._is_playing and not self._is_paused:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self._stream is None:
            return
        if self._is_playing and not self._is_paused:
            return
        self.playback_starting.emit()
        pos_ms = self._last_pos_ms
        if self._eof_emitted:
            pos_ms = 0
            self._eof_emitted = False
        if self._using_hifi and self._hifi_engine is not None:
            try:
                self._hifi_engine.resume(pos_ms)
            except Exception:
                self._start_playback_at(pos_ms)
                return
            if not self._audio_only and self._qt_player.source().isValid():
                self._qt_player.setPosition(pos_ms)
                self._qt_player.play()
        else:
            if not self._qt_player.source().isValid():
                self._start_playback_at(pos_ms)
                return
            self._qt_player.play()
        self._is_playing = True
        self._is_paused = False
        self._clock_timer.start()
        self.state_changed.emit(True)

    def pause(self) -> None:
        if not self._is_playing or self._is_paused:
            return
        self._last_pos_ms = self.position_ms()
        self._is_paused = True
        if self._using_hifi and self._hifi_engine is not None:
            self._hifi_engine.pause()
        if self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._qt_player.pause()
        self._clock_timer.stop()
        self.buffering_changed.emit(False)
        self.state_changed.emit(False)

    def pause_if_playing(self) -> None:
        if self.is_playing:
            self.pause()

    def seek(self, pos_ms: int) -> None:
        if self._stream is None:
            return
        target = max(0, int(pos_ms))
        if self._duration_ms > 0:
            target = min(self._duration_ms, target)
        self._last_pos_ms = target
        self._eof_emitted = False
        self._last_video_seek_mono = time.monotonic()
        if self._using_hifi and self._hifi_engine is not None:
            self._hifi_engine.seek(target)
        if not self._audio_only and self._qt_player.source().isValid():
            self._qt_player.setPlaybackRate(self._playback_rate)
            self._qt_player.setPosition(target)
        elif not self._using_hifi and self._qt_player.source().isValid():
            self._qt_player.setPosition(target)
        self._sync_subtitle_for_pos(target)
        self.position_changed.emit(target, self.duration_ms())

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, float(volume)))
        if self._hifi_engine is not None:
            self._hifi_engine.set_user_volume(self._volume, self._muted)
        self._qt_audio.setVolume(self._volume)

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self._hifi_engine is not None:
            self._hifi_engine.set_user_volume(self._volume, self._muted)
        if not self._using_hifi:
            self._qt_audio.setMuted(self._muted)

    def set_playback_rate(self, rate: float) -> None:
        new_rate = max(0.5, min(2.0, float(rate or 1.0)))
        if abs(new_rate - self._playback_rate) < 0.01:
            return
        self._playback_rate = new_rate
        if self._stream is None:
            return
        pos = self.position_ms()
        was_playing = self.is_playing
        self._qt_player.setPlaybackRate(new_rate)
        if self._using_hifi and was_playing:
            self._start_playback_at(pos)

    def set_audio_only(self, audio_only: bool) -> None:
        flag = bool(audio_only)
        if flag == self._audio_only:
            return
        self._audio_only = flag
        if self._stream is None:
            return
        pos = self.position_ms()
        was_playing = self.is_playing
        if flag:
            # Switching Video -> Pure Audio Hi-Fi: drop video decode immediately, keep audio seamless!
            self._qt_player.stop()
            self._qt_player.setSource(QUrl())
            self._active_quality = "Audio Hi-Fi"
            if not self._using_hifi and was_playing:
                self._start_playback_at(pos)
        else:
            # Switching Audio-Only -> Video: attach video track synced to live audio clock!
            if was_playing:
                self._start_playback_at(pos)

    def set_quality(self, quality: str) -> None:
        q = str(quality or "1080p")
        if q == "audio_only":
            self.set_audio_only(True)
            return
        changed = (q != self._quality) or self._audio_only
        self._quality = q
        self._audio_only = False
        if changed and self._stream is not None:
            pos = self.position_ms()
            if self.is_playing:
                self._start_playback_at(pos)

    def reapply_audio_profile(self) -> None:
        """Re-apply BoTube's live AudioProfile (EQ/DAC/Exclusive) seamlessly when changed."""
        if self._stream is not None and self._using_hifi and self.is_playing:
            self._start_playback_at(self.position_ms())

    # --- Subtitle / CC Control ---
    def set_subtitles(self, cues: list[OnlineSubtitleCue], enabled: bool) -> None:
        self._cues = list(cues or [])
        self._cue_starts = [c.start_ms for c in self._cues]
        self._sub_enabled = bool(enabled)
        self._last_sub_text = ""
        if not self._sub_enabled or not self._cues:
            self.subtitle_text_changed.emit("")
        else:
            self._sync_subtitle_for_pos(self.position_ms())

    def set_subtitles_enabled(self, enabled: bool) -> None:
        self._sub_enabled = bool(enabled)
        if not self._sub_enabled:
            self._last_sub_text = ""
            self.subtitle_text_changed.emit("")
        else:
            self._sync_subtitle_for_pos(self.position_ms())

    def _sync_subtitle_for_pos(self, pos_ms: int) -> None:
        if not self._sub_enabled or not self._cues:
            if self._last_sub_text:
                self._last_sub_text = ""
                self.subtitle_text_changed.emit("")
            return
        idx = bisect.bisect_right(self._cue_starts, pos_ms) - 1
        text = ""
        if 0 <= idx < len(self._cues):
            cue = self._cues[idx]
            if cue.start_ms <= pos_ms <= cue.end_ms:
                text = cue.text
        if text != self._last_sub_text:
            self._last_sub_text = text
            self.subtitle_text_changed.emit(text)

    # --- Internal Clock & A/V Drift Sync ---
    def _on_clock_tick(self) -> None:
        if not self._is_playing or self._is_paused:
            return
        pos_ms = self.position_ms()
        dur_ms = self.duration_ms()
        self._last_pos_ms = pos_ms
        self.position_changed.emit(pos_ms, dur_ms)
        self._sync_subtitle_for_pos(pos_ms)

        if self._using_hifi and self._hifi_engine is not None:
            buf = self._hifi_engine.is_buffering()
            if buf != self._last_buffering:
                self._last_buffering = buf
                self.buffering_changed.emit(buf)

            # Smooth, non-thrashing A/V sync: never abort HTTP buffering with rapid seeks!
            if not self._audio_only and self._qt_player.source().isValid():
                status = self._qt_player.mediaStatus()
                in_flight = status in (
                    QMediaPlayer.MediaStatus.LoadingMedia,
                    QMediaPlayer.MediaStatus.BufferingMedia,
                )
                if buf:
                    if self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                        self._qt_player.pause()
                elif not in_flight:
                    if self._qt_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                        if status not in (
                            QMediaPlayer.MediaStatus.EndOfMedia,
                            QMediaPlayer.MediaStatus.InvalidMedia,
                        ):
                            self._qt_player.setPlaybackRate(self._playback_rate)
                            self._qt_player.play()
                    elif status == QMediaPlayer.MediaStatus.BufferedMedia:
                        now_m = time.monotonic()
                        v_pos = int(self._qt_player.position())
                        drift = pos_ms - v_pos  # positive = video lagging behind Hi-Fi audio
                        if abs(drift) > 750 and (now_m - self._last_video_seek_mono) >= 2.5:
                            self._last_video_seek_mono = now_m
                            self._qt_player.setPlaybackRate(self._playback_rate)
                            self._qt_player.setPosition(pos_ms)
                        elif 180 < drift <= 750:
                            self._qt_player.setPlaybackRate(min(2.2, self._playback_rate * 1.05))
                        elif -750 <= drift < -180:
                            self._qt_player.setPlaybackRate(max(0.45, self._playback_rate * 0.95))
                        elif abs(drift) <= 120:
                            if abs(float(self._qt_player.playbackRate()) - self._playback_rate) > 0.005:
                                self._qt_player.setPlaybackRate(self._playback_rate)

            # Reliable EOF detection for Hi-Fi audio stream
            if not self._eof_emitted and self._hifi_engine.has_reached_eof():
                self._eof_emitted = True
                self._is_playing = False
                self._is_paused = False
                self._clock_timer.stop()
                if self._qt_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._qt_player.pause()
                self.buffering_changed.emit(False)
                self.state_changed.emit(False)
                self.track_ended.emit()

    def _on_qt_media_status(self, status) -> None:
        if (
            self._video_start_pending_ms is not None
            and status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia)
        ):
            target = self._video_start_pending_ms
            self._video_start_pending_ms = None
            self._qt_player.setPosition(target)
        if not self._using_hifi and status == QMediaPlayer.MediaStatus.EndOfMedia:
            if not self._eof_emitted and self._is_playing:
                self._eof_emitted = True
                self._is_playing = False
                self._is_paused = False
                self._clock_timer.stop()
                self.state_changed.emit(False)
                self.track_ended.emit()

    def _on_qt_error(self, _error, error_string: str) -> None:
        if not self._using_hifi and error_string:
            self.error_occurred.emit(error_string)

    def stop(self, release_exclusive: bool = True) -> None:
        self._clock_timer.stop()
        self._is_playing = False
        self._is_paused = False
        self._video_start_pending_ms = None
        if self._hifi_engine is not None:
            self._hifi_engine.stop(release_exclusive=release_exclusive)
        self._qt_player.stop()
        self._qt_player.setSource(QUrl())
        if hasattr(self.video_widget, "clear_frame"):
            self.video_widget.clear_frame()
        self._last_buffering = False
        self.buffering_changed.emit(False)
        self.state_changed.emit(False)
        self.subtitle_text_changed.emit("")

    def shutdown(self) -> None:
        self.stop(release_exclusive=True)
        if self._hifi_engine is not None:
            self._hifi_engine.shutdown()
