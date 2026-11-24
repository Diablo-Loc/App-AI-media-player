"""Zero-disk 64-bit FFmpeg -> RAM ring buffer -> WASAPI Shared/Exclusive audio engine."""
from collections import deque
import logging
import os
import subprocess
import threading

import numpy as np

from core.audio_effects import find_tool
from core.audio_profile import AudioProfile, build_realtime_filter_graph

logger = logging.getLogger(__name__)


def is_stream_engine_available():
    """Return True when sounddevice/PortAudio and FFmpeg are usable."""
    try:
        import sounddevice  # noqa: F401
        find_tool('ffmpeg')
        return True
    except Exception:
        return False


def quantize_pcm(samples_f32: np.ndarray, dtype: str, rng: np.random.Generator | None = None) -> bytes:
    """Quantize stereo float32 [-1, 1] frames to target DAC format with optional TPDF dither."""
    if samples_f32.size == 0:
        return b''
    arr = np.asarray(samples_f32, dtype=np.float32)
    if dtype == 'float32':
        return np.clip(arr, -1.0, 1.0).astype('<f4', copy=False).tobytes()

    if dtype == 'int32':
        if rng is not None:
            dither = (rng.random(arr.shape, dtype=np.float32) - rng.random(arr.shape, dtype=np.float32)) * (1.0 / 2147483647.0)
            arr = arr + dither
        scaled = np.clip(arr * 2147483647.0, -2147483648.0, 2147483647.0)
        return scaled.astype('<i4').tobytes()

    if dtype == 'int24':
        if rng is not None:
            dither = (rng.random(arr.shape, dtype=np.float32) - rng.random(arr.shape, dtype=np.float32)) * (1.0 / 8388607.0)
            arr = arr + dither
        scaled = np.clip(arr * 8388607.0, -8388608.0, 8388607.0).astype('<i4')
        return scaled.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()

    if dtype == 'int16':
        if rng is not None:
            dither = (rng.random(arr.shape, dtype=np.float32) - rng.random(arr.shape, dtype=np.float32)) * (1.0 / 32767.0)
            arr = arr + dither
        scaled = np.clip(arr * 32767.0, -32768.0, 32767.0)
        return scaled.astype('<i2').tobytes()

    raise ValueError(f'Unsupported PCM dtype: {dtype}')


def apply_micro_fade(
    block: np.ndarray,
    current_amp: float,
    target_amp: float,
    fade_samples: int,
) -> tuple[np.ndarray, float]:
    """Smoothly ramp amplitude via raised-cosine micro-fade to prevent IEM clicks/pops."""
    out = block.copy()
    if len(out) == 0:
        return out, float(current_amp)
    if abs(target_amp - current_amp) < 1e-6:
        if abs(target_amp - 1.0) > 1e-6:
            out *= float(target_amp)
        return out, float(target_amp)
    n = min(len(out), max(1, int(fade_samples)))
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    weights = 0.5 - 0.5 * np.cos(np.pi * t)
    ramp = float(current_amp) + (float(target_amp) - float(current_amp)) * weights
    out[:n] *= ramp[:, None]
    if len(out) > n:
        out[n:] *= float(target_amp)
        end_amp = float(target_amp)
    else:
        end_amp = float(ramp[-1])
    return out, end_amp


def select_wasapi_device(sd, preferred_name: str = ''):
    """Locate the WASAPI output device matching Qt's active device description."""
    hostapis = sd.query_hostapis()
    wasapi = next((h for h in hostapis if 'WASAPI' in h['name']), None)
    if wasapi is None:
        idx = int(sd.default.device[1])
        return idx, sd.query_devices(idx)

    outputs = []
    for dev_idx in wasapi['devices']:
        info = sd.query_devices(dev_idx)
        if info['max_output_channels'] >= 2:
            outputs.append((dev_idx, info))

    pref = (preferred_name or '').strip().lower()
    if pref and outputs:
        for dev_idx, info in outputs:
            if info['name'].strip().lower() == pref:
                return dev_idx, info
        for dev_idx, info in outputs:
            name_l = info['name'].strip().lower()
            if pref in name_l or name_l in pref:
                return dev_idx, info

    default_idx = int(wasapi.get('default_output_device', -1))
    if default_idx >= 0:
        return default_idx, sd.query_devices(default_idx)
    if outputs:
        return outputs[0]
    idx = int(sd.default.device[1])
    return idx, sd.query_devices(idx)


class _AudioRingBuffer:
    """Bounded in-RAM FIFO of float32 stereo frames with backpressure."""

    def __init__(self, capacity_frames: int):
        self.capacity = max(2048, int(capacity_frames))
        self._chunks: deque[np.ndarray] = deque()
        self._head_offset = 0
        self._frames = 0
        self._eof = False
        self._closed = False
        self._cond = threading.Condition()

    def push(self, chunk: np.ndarray, cancel_event: threading.Event) -> bool:
        if len(chunk) == 0:
            return True
        with self._cond:
            while self._frames >= self.capacity and not self._closed and not cancel_event.is_set():
                self._cond.wait(timeout=0.05)
            if self._closed or cancel_event.is_set():
                return False
            self._chunks.append(chunk)
            self._frames += len(chunk)
            self._cond.notify_all()
            return True

    def mark_eof(self):
        with self._cond:
            self._eof = True
            self._cond.notify_all()

    def pop(self, count: int) -> tuple[np.ndarray, int, bool]:
        """Non-blocking pop of up to `count` stereo float32 frames for the WASAPI callback."""
        with self._cond:
            if self._frames == 0:
                return np.zeros((count, 2), dtype=np.float32), 0, self._eof
            out = np.zeros((count, 2), dtype=np.float32)
            filled = 0
            while filled < count and self._chunks:
                head = self._chunks[0]
                avail = len(head) - self._head_offset
                take = min(count - filled, avail)
                out[filled:filled + take] = head[self._head_offset:self._head_offset + take]
                filled += take
                self._head_offset += take
                self._frames -= take
                if self._head_offset >= len(head):
                    self._chunks.popleft()
                    self._head_offset = 0
            eof_reached = self._eof and self._frames == 0
            self._cond.notify_all()
            return out, filled, eof_reached

    def close(self):
        with self._cond:
            self._closed = True
            self._chunks.clear()
            self._head_offset = 0
            self._frames = 0
            self._cond.notify_all()


class AudioStreamEngine:
    """Real-time FFmpeg 64-bit DSP pipe feeding WASAPI Shared or Exclusive."""

    def __init__(self, on_before_exclusive=None, on_after_exclusive=None):
        self._lock = threading.RLock()
        self._on_before_exclusive = on_before_exclusive
        self._on_after_exclusive = on_after_exclusive

        self._op_id = 0
        self._stream = None
        self._proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ring: _AudioRingBuffer | None = None

        self._user_volume = 0.5
        self._muted = False
        self._trim_linear = 1.0
        self._current_amp = 0.0
        self._fading_out = False

        self._playing = False
        self._paused = False
        self._exclusive_held = False

        self._start_ms = 0.0
        self._played_frames = 0
        self._out_sr = 48000
        self._out_dtype = 'float32'
        self._playback_rate = 1.0
        self._device_name = ''
        self._actual_mode = 'shared'
        self._fallback_reason = ''
        self._filter_summary = {}

        # Active source parameters for resume/seek/reconfigure.
        self._source_path = ''
        self._profile = AudioProfile()
        self._source_info = None
        self._gain_db = 0.0
        self._track = 0
        self._preferred_device = ''

    def set_user_volume(self, volume: float, muted: bool = False):
        with self._lock:
            self._user_volume = max(0.0, min(1.0, float(volume)))
            self._muted = bool(muted)

    def set_dynamic_trim_db(self, trim_db: float):
        clamped = max(-24.0, min(12.0, float(trim_db)))
        with self._lock:
            self._trim_linear = 10.0 ** (clamped / 20.0)

    def is_active(self) -> bool:
        with self._lock:
            return self._playing and not self._paused and self._stream is not None

    def position_ms(self) -> int:
        with self._lock:
            if self._out_sr <= 0:
                return int(self._start_ms)
            elapsed = (self._played_frames / float(self._out_sr)) * 1000.0 * self._playback_rate
            return max(0, int(round(self._start_ms + elapsed)))

    def status_info(self) -> dict:
        with self._lock:
            return {
                'active': self._playing,
                'paused': self._paused,
                'device_name': self._device_name,
                'output_mode': self._actual_mode,
                'sample_rate': self._out_sr,
                'dtype': self._out_dtype,
                'fallback_reason': self._fallback_reason,
                'filter_summary': dict(self._filter_summary),
            }

    def _make_callback(self, ring: _AudioRingBuffer, sr: int, dtype: str, stop_event: threading.Event):
        local_rng = np.random.default_rng() if dtype != 'float32' else None
        fade_samples = max(1, int(0.012 * sr))

        def _callback(outdata, frames, _time_info, _status):
            # Strictly wait-free relative to self._lock so Pa_AbortStream/Pa_StopStream can never deadlock.
            pcm, popped, _ = ring.pop(frames)
            if stop_event.is_set() or self._fading_out or self._muted or not self._playing or self._paused:
                target_amp = 0.0
            else:
                target_amp = self._user_volume * self._trim_linear
            if popped > 0:
                self._played_frames += popped
            processed, end_amp = apply_micro_fade(pcm, self._current_amp, target_amp, fade_samples)
            self._current_amp = end_amp
            raw_bytes = quantize_pcm(processed, dtype, rng=local_rng)
            expected = len(outdata)
            if len(raw_bytes) >= expected:
                outdata[:] = raw_bytes[:expected]
            else:
                outdata[:len(raw_bytes)] = raw_bytes
                outdata[len(raw_bytes):] = b'\x00' * (expected - len(raw_bytes))

        return _callback

    def _open_wasapi_stream(
        self,
        profile: AudioProfile,
        source_info: dict | None,
        preferred_device: str,
        stop_event: threading.Event,
    ):
        import sounddevice as sd

        dev_idx, dev_info = select_wasapi_device(sd, preferred_device)
        dev_name = str(dev_info['name'])
        dev_sr = int(round(float(dev_info.get('default_samplerate') or 48000)))
        source_sr = int((source_info or {}).get('sample_rate') or dev_sr)

        if profile.output_mode == 'exclusive':
            with self._lock:
                should_notify = self._on_before_exclusive is not None and not self._exclusive_held
                if should_notify:
                    self._exclusive_held = True
            if should_notify:
                try:
                    self._on_before_exclusive()
                except Exception:
                    pass

            rates = []
            for r in (source_sr, dev_sr, 48000, 44100, 96000, 88200, 192000):
                if 44100 <= r <= 384000 and r not in rates:
                    rates.append(r)
            for sr in rates:
                for dtype in ('int32', 'int24', 'float32', 'int16'):
                    stream = None
                    ring = _AudioRingBuffer(int(sr * 0.40))
                    try:
                        stream = sd.RawOutputStream(
                            device=dev_idx,
                            channels=2,
                            dtype=dtype,
                            samplerate=sr,
                            latency=0.025,
                            extra_settings=sd.WasapiSettings(exclusive=True),
                            callback=self._make_callback(ring, sr, dtype, stop_event),
                        )
                        stream.start()
                        return stream, ring, dev_name, sr, dtype, 'exclusive', ''
                    except Exception:
                        ring.close()
                        if stream is not None:
                            try:
                                stream.abort()
                            except Exception:
                                pass
                            try:
                                stream.close()
                            except Exception:
                                pass

            with self._lock:
                release_excl = self._exclusive_held
                self._exclusive_held = False
            if release_excl and self._on_after_exclusive is not None:
                try:
                    self._on_after_exclusive()
                except Exception:
                    pass
            fallback_reason = 'Thiết bị không hỗ trợ Exclusive hoặc đang bận → Hi-Fi Shared'
        else:
            with self._lock:
                release_excl = self._exclusive_held
                self._exclusive_held = False
            if release_excl and self._on_after_exclusive is not None:
                try:
                    self._on_after_exclusive()
                except Exception:
                    pass
            fallback_reason = ''

        for sr in (dev_sr, 48000, 44100):
            stream = None
            ring = _AudioRingBuffer(int(sr * 0.40))
            try:
                stream = sd.RawOutputStream(
                    device=dev_idx,
                    channels=2,
                    dtype='float32',
                    samplerate=sr,
                    latency=0.035,
                    extra_settings=sd.WasapiSettings(exclusive=False),
                    callback=self._make_callback(ring, sr, 'float32', stop_event),
                )
                stream.start()
                actual_mode = 'shared_fallback' if fallback_reason else 'shared'
                return stream, ring, dev_name, sr, 'float32', actual_mode, fallback_reason
            except Exception:
                ring.close()
                if stream is not None:
                    try:
                        stream.abort()
                    except Exception:
                        pass
                    try:
                        stream.close()
                    except Exception:
                        pass

        raise RuntimeError('Không mở được thiết bị đầu ra WASAPI.')

    def _spawn_ffmpeg(self, source_path: str, start_ms: int, track: int, filter_graph: str) -> subprocess.Popen:
        ffmpeg = find_tool('ffmpeg')
        cmd = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '2']
        if start_ms > 20:
            cmd.extend(['-ss', f'{start_ms / 1000.0:.3f}'])
        cmd.extend([
            '-i', str(source_path),
            '-map', f'0:a:{int(track)}',
            '-vn', '-sn', '-dn',
            '-af', filter_graph,
            '-f', 'f32le', '-ac', '2',
            'pipe:1',
        ])
        flags = 0
        if os.name == 'nt':
            flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=65536,
            creationflags=flags,
        )

    def _reader_loop(self, proc: subprocess.Popen, ring: _AudioRingBuffer, cancel_event: threading.Event):
        chunk_bytes = 2048 * 2 * 4
        leftover = b''
        try:
            stdout = proc.stdout
            if stdout is None:
                return
            while not cancel_event.is_set():
                data = stdout.read(chunk_bytes)
                if not data:
                    break
                buf = leftover + data
                usable = len(buf) - (len(buf) % 8)
                leftover = buf[usable:]
                if usable > 0:
                    frames = np.frombuffer(buf[:usable], dtype='<f4').reshape(-1, 2).copy()
                    if not ring.push(frames, cancel_event):
                        break
        except Exception as err:
            logger.debug('AudioStreamEngine reader stopped: %s', err)
        finally:
            ring.mark_eof()

    def _detach_locked(self, release_exclusive: bool):
        stop_event = self._stop_event
        ring = self._ring
        proc = self._proc
        thread = self._reader_thread
        stream = self._stream
        release_excl = bool(release_exclusive and self._exclusive_held)
        if release_excl:
            self._exclusive_held = False
        self._ring = None
        self._proc = None
        self._reader_thread = None
        self._stream = None
        return (stop_event, ring, proc, thread, stream, release_excl)

    def _close_detached(self, detached):
        """Must always run OUTSIDE self._lock so PortAudio callback threads never deadlock."""
        stop_event, ring, proc, thread, stream, release_excl = detached
        if stop_event is not None:
            stop_event.set()
        if ring is not None:
            ring.close()
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if release_excl and self._on_after_exclusive is not None:
            try:
                self._on_after_exclusive()
            except Exception:
                pass

    def start_or_reconfigure(
        self,
        source_path: str,
        start_ms: int,
        profile: AudioProfile,
        source_info: dict | None,
        gain_db: float,
        playback_rate: float = 1.0,
        track: int = 0,
        preferred_device_name: str = '',
        paused: bool = False,
    ) -> dict:
        """Start or seamlessly reconfigure the in-RAM DSP + WASAPI pipeline."""
        with self._lock:
            self._op_id += 1
            op_id = self._op_id
            self._source_path = str(source_path)
            self._profile = profile
            self._source_info = source_info
            self._gain_db = float(gain_db)
            self._playback_rate = max(0.25, min(4.0, float(playback_rate or 1.0)))
            self._track = int(track)
            self._preferred_device = preferred_device_name or ''
            self._start_ms = float(max(0, int(start_ms)))
            self._played_frames = 0
            self._trim_linear = 1.0
            self._fading_out = False
            self._paused = bool(paused)
            self._playing = True
            detached = self._detach_locked(release_exclusive=paused)

        self._close_detached(detached)

        if paused:
            return self.status_info()

        stop_event = threading.Event()
        stream, ring, dev_name, out_sr, out_dtype, actual_mode, fallback_reason = self._open_wasapi_stream(
            profile, source_info, preferred_device_name or '', stop_event
        )
        filter_graph, summary = build_realtime_filter_graph(
            profile,
            source_info,
            gain_db,
            out_sr,
            playback_rate=max(0.25, min(4.0, float(playback_rate or 1.0))),
        )
        proc = self._spawn_ffmpeg(str(source_path), max(0, int(start_ms)), int(track), filter_graph)
        thread = threading.Thread(
            target=self._reader_loop,
            args=(proc, ring, stop_event),
            name='BoTube-HiFi-DSP-Pipe',
            daemon=True,
        )

        with self._lock:
            if op_id != self._op_id or not self._playing or self._paused:
                # Superseded while opening stream -> abort cleanly outside lock.
                superseded = (stop_event, ring, proc, None, stream, False)
            else:
                self._stop_event = stop_event
                self._current_amp = 0.0
                self._out_sr = out_sr
                self._out_dtype = out_dtype
                self._device_name = dev_name
                self._actual_mode = actual_mode
                self._fallback_reason = fallback_reason
                self._filter_summary = summary
                self._ring = ring
                self._proc = proc
                self._stream = stream
                self._reader_thread = thread
                superseded = None

        if superseded is not None:
            self._close_detached(superseded)
            return self.status_info()

        thread.start()
        return self.status_info()

    def pause(self):
        with self._lock:
            if not self._playing or self._paused:
                return
            self._op_id += 1
            self._fading_out = True
            self._paused = True
            self._start_ms = float(self.position_ms())
            self._played_frames = 0
            has_stream = self._stream is not None
        if has_stream:
            threading.Event().wait(0.018)
        with self._lock:
            detached = self._detach_locked(release_exclusive=True)
        self._close_detached(detached)

    def resume(self, current_pos_ms: int | None = None):
        with self._lock:
            if not self._source_path or not self._playing:
                return
            pos = int(current_pos_ms) if current_pos_ms is not None else int(self._start_ms)
            args = (
                self._source_path,
                pos,
                self._profile,
                self._source_info,
                self._gain_db,
                self._playback_rate,
                self._track,
                self._preferred_device,
            )
        self.start_or_reconfigure(*args, paused=False)

    def seek(self, pos_ms: int):
        with self._lock:
            if not self._playing or not self._source_path:
                return
            target_pos = max(0, int(pos_ms))
            if self._paused:
                self._start_ms = float(target_pos)
                self._played_frames = 0
                return
            args = (
                self._source_path,
                target_pos,
                self._profile,
                self._source_info,
                self._gain_db,
                self._playback_rate,
                self._track,
                self._preferred_device,
            )
        self.start_or_reconfigure(*args, paused=False)

    def stop(self):
        with self._lock:
            self._op_id += 1
            self._playing = False
            self._paused = False
            self._fading_out = True
            detached = self._detach_locked(release_exclusive=True)
        self._close_detached(detached)

    def shutdown(self):
        self.stop()
