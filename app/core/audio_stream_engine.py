"""Zero-disk 64-bit FFmpeg -> RAM pre-buffer -> GIL-free C-blocking WASAPI Shared/Exclusive engine."""
import logging
import os
import subprocess
import threading
import time

import numpy as np

from core.audio_effects import find_tool
from core.audio_profile import AudioProfile, build_realtime_filter_graph

logger = logging.getLogger(__name__)

# Prime-length 64-bit TPDF dither table (~2.1 MB RAM) lazily initialized only when
# integer PCM quantization (16/24/32-bit) is actually requested; float32 WASAPI skips it.
_TPDF_LEN = 262147
_TPDF_R_STRIDE = 131071
_TPDF_TABLE: np.ndarray | None = None
_TPDF_LOCK = threading.Lock()


def _get_tpdf_table() -> np.ndarray:
    global _TPDF_TABLE
    table = _TPDF_TABLE
    if table is None:
        with _TPDF_LOCK:
            if _TPDF_TABLE is None:
                _TPDF_TABLE = (
                    np.random.default_rng(20261124).random(_TPDF_LEN, dtype=np.float64)
                    - np.random.default_rng(20261125).random(_TPDF_LEN, dtype=np.float64)
                )
            table = _TPDF_TABLE
    return table


def is_stream_engine_available():
    """Return True when sounddevice/PortAudio and FFmpeg are usable."""
    try:
        import sounddevice  # noqa: F401
        find_tool('ffmpeg')
        return True
    except Exception:
        return False


def _tpdf_slice_1d(start: int, length: int) -> np.ndarray:
    table = _get_tpdf_table()
    s = start % _TPDF_LEN
    if s + length <= _TPDF_LEN:
        return table[s:s + length]
    idx = (np.arange(length, dtype=np.int64) + s) % _TPDF_LEN
    return table[idx]


def _tpdf_slice(shape, offset: int) -> np.ndarray:
    if len(shape) == 2 and int(shape[1]) == 2:
        n = int(shape[0])
        left = _tpdf_slice_1d(offset, n)
        right = _tpdf_slice_1d(offset + _TPDF_R_STRIDE, n)
        return np.column_stack((left, right))
    total = int(shape[0]) * int(shape[1])
    return _tpdf_slice_1d(offset, total).reshape(shape)


def quantize_pcm(
    samples: np.ndarray,
    dtype: str,
    rng: np.random.Generator | None = None,
    dither_offset: int = 0,
) -> bytes:
    """Quantize stereo float64/float32 [-1, 1] frames to target DAC format with 64-bit TPDF dither."""
    if samples.size == 0:
        return b''
    if dtype == 'float32':
        arr_f = np.asarray(samples)
        return np.clip(arr_f, -1.0, 1.0).astype('<f4', copy=False).tobytes()

    arr = np.asarray(samples, dtype=np.float64)

    def _dither(lsb_scale: float) -> np.ndarray:
        if rng is not None:
            return (rng.random(arr.shape, dtype=np.float64) - rng.random(arr.shape, dtype=np.float64)) * lsb_scale
        return _tpdf_slice(arr.shape, dither_offset) * lsb_scale

    if dtype == 'int32':
        arr = arr + _dither(1.0 / 2147483647.0)
        scaled = np.clip(arr * 2147483647.0, -2147483648.0, 2147483647.0)
        return scaled.astype('<i4').tobytes()

    if dtype == 'int24':
        arr = arr + _dither(1.0 / 8388607.0)
        scaled = np.clip(arr * 8388607.0, -8388608.0, 8388607.0).astype('<i4')
        return scaled.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()

    if dtype == 'int16':
        arr = arr + _dither(1.0 / 32767.0)
        scaled = np.clip(arr * 32767.0, -32768.0, 32767.0)
        return scaled.astype('<i2').tobytes()

    raise ValueError(f'Unsupported PCM dtype: {dtype}')


def apply_micro_fade(
    block: np.ndarray,
    current_amp: float,
    target_amp: float,
    fade_samples: int,
) -> tuple[np.ndarray, float]:
    """Smoothly ramp amplitude via raised-cosine micro-fade while preserving float64 precision."""
    out = block.copy()
    if len(out) == 0:
        return out, float(current_amp)
    if abs(target_amp - current_amp) < 1e-6:
        if abs(target_amp - 1.0) > 1e-6:
            out *= float(target_amp)
        return out, float(target_amp)
    work_dtype = np.float64 if out.dtype == np.float64 else np.float32
    n = min(len(out), max(1, int(fade_samples)))
    t = np.linspace(0.0, 1.0, n, dtype=work_dtype)
    weights = 0.5 - 0.5 * np.cos(np.pi * t)
    ramp = float(current_amp) + (float(target_amp) - float(current_amp)) * weights
    out[:n] *= ramp[:, None]
    if len(out) > n:
        out[n:] *= float(target_amp)
        end_amp = float(target_amp)
    else:
        end_amp = float(ramp[-1])
    return out, end_amp


def build_release_tail(last_frame: np.ndarray, release_samples: int) -> np.ndarray:
    """Generate a smooth half-cosine decay from last_frame to exact zero-crossing."""
    n = max(2, int(release_samples))
    t = np.linspace(1.0 / n, 1.0, n, dtype=np.float64)
    envelope = 0.5 * (1.0 + np.cos(np.pi * t))
    return np.asarray(last_frame, dtype=np.float64).reshape(1, 2) * envelope[:, None]


def _device_matches(actual_name: str, requested_name: str) -> bool:
    """Return True when actual WASAPI endpoint name matches requested/pinned device."""
    req = (requested_name or '').strip().lower()
    act = (actual_name or '').strip().lower()
    if not req or not act:
        return False
    return act == req or req in act or act in req


def list_wasapi_output_devices() -> list[str]:
    """Return available stereo+ WASAPI output endpoint names in host order."""
    try:
        import sounddevice as sd
        hostapis = sd.query_hostapis()
        wasapi = next((h for h in hostapis if 'WASAPI' in h['name']), None)
        if wasapi is None:
            return []
        names = []
        seen = set()
        for dev_idx in wasapi['devices']:
            info = sd.query_devices(dev_idx)
            if info.get('max_output_channels', 0) >= 2:
                name = str(info.get('name') or '').strip()
                key = name.lower()
                if name and key not in seen:
                    seen.add(key)
                    names.append(name)
        return names
    except Exception:
        return []


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


def preferred_exclusive_rates(source_sr: int, dev_sr: int, upsample: str = 'off') -> list[int]:
    """Return ordered candidate WASAPI Exclusive sample rates for synchronous oversampling or native mode."""
    src = int(source_sr or 0)
    dev = int(dev_sr or 48000)
    is_44k_family = (src > 0 and src % 44100 == 0)

    if upsample == 'hires_sync':
        if is_44k_family:
            candidates = [max(src, 176400), 88200, 192000, 96000, src, dev, 48000, 44100]
        else:
            candidates = [max(src, 192000), 96000, 176400, 88200, src, dev, 48000, 44100]
    elif upsample == 'max_dac':
        if is_44k_family:
            candidates = [352800, 384000, 176400, 192000, 88200, 96000, src, dev, 48000, 44100]
        else:
            candidates = [384000, 352800, 192000, 176400, 96000, 88200, src, dev, 48000, 44100]
    else:
        candidates = [src, dev, 48000, 44100, 96000, 88200, 192000, 176400]

    rates = []
    for r in candidates:
        if 44100 <= r <= 384000 and r not in rates:
            rates.append(r)
    return rates


class AudioStreamEngine:
    """Zero-disk FFmpeg 64-bit DSP pipe feeding C-blocking WASAPI Shared or Exclusive."""

    _CHUNK_FRAMES = 2048
    _PREBUFFER_CHUNKS = 3  # ~128 ms pre-buffered before starting hardware DAC stream

    @classmethod
    def _chunk_frames_for_rate(cls, out_sr: int) -> int:
        scale = max(1, int(round(max(8000, int(out_sr)) / 48000.0)))
        return cls._CHUNK_FRAMES * scale

    def __init__(self, on_before_exclusive=None, on_after_exclusive=None):
        self._lock = threading.RLock()
        self._on_before_exclusive = on_before_exclusive
        self._on_after_exclusive = on_after_exclusive

        self._op_id = 0
        self._writer_thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._active_proc: subprocess.Popen | None = None
        self._active_stream = None
        self._active_stream_lock = None
        self._active_stream_closed: list[bool] | None = None

        self._user_volume = 0.5
        self._muted = False
        self._base_gain_db = 0.0
        self._gain_db = 0.0
        self._target_gain_linear = 1.0
        self._current_amp = 0.0

        self._playing = False
        self._paused = False
        self._exclusive_held = False

        self._start_ms = 0.0
        self._played_frames = 0
        self._last_write_mono = 0.0
        self._out_sr = 48000
        self._out_dtype = 'float32'
        self._latency_sec = 0.16
        self._playback_rate = 1.0
        self._device_name = ''
        self._actual_mode = 'shared'
        self._fallback_reason = ''
        self._filter_summary = {}
        self._underflows = 0

        self._source_path = ''
        self._profile = AudioProfile()
        self._source_info = None
        self._gain_db = 0.0
        self._track = 0
        self._preferred_device = ''
        self._last_exclusive_format: dict[tuple[str, str, int], tuple[int, str]] = {}

    def set_user_volume(self, volume: float, muted: bool = False):
        with self._lock:
            self._user_volume = max(0.0, min(1.0, float(volume)))
            self._muted = bool(muted)

    def set_gain_db(self, gain_db: float):
        clamped = max(-24.0, min(12.0, float(gain_db)))
        with self._lock:
            self._gain_db = clamped
            self._target_gain_linear = 10.0 ** (clamped / 20.0)

    def set_dynamic_trim_db(self, trim_db: float):
        with self._lock:
            base = self._base_gain_db
        self.set_gain_db(base + float(trim_db))

    def is_active(self) -> bool:
        with self._lock:
            return self._playing and not self._paused and self._active_stream is not None

    def position_ms(self) -> int:
        with self._lock:
            if self._out_sr <= 0:
                return int(self._start_ms)
            hw_latency = self._latency_sec if (self._playing and not self._paused) else 0.0
            base_sec = (self._played_frames / float(self._out_sr)) - hw_latency
            interp_sec = 0.0
            if self._playing and not self._paused and self._last_write_mono > 0.0 and base_sec > 0.0:
                chunk_sec = self._chunk_frames_for_rate(self._out_sr) / float(self._out_sr)
                dt = max(0.0, time.monotonic() - self._last_write_mono)
                interp_sec = min(dt, chunk_sec * 1.25)
            elapsed = max(0.0, base_sec + interp_sec) * 1000.0 * self._playback_rate
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
                'underflows': self._underflows,
                'latency_ms': round(self._latency_sec * 1000.0, 1),
            }

    def refresh_devices(self) -> list[str]:
        """Re-enumerate PortAudio WASAPI endpoints safely after USB DAC or Bluetooth hotplug."""
        self._stop_active_worker(release_exclusive=True)
        with self._lock:
            self._last_exclusive_format.clear()
        try:
            import sounddevice as sd
            term = getattr(sd, '_terminate', None)
            init = getattr(sd, '_initialize', None)
            with self._lock:
                if (
                    callable(term)
                    and callable(init)
                    and type(term).__module__ != 'unittest.mock'
                    and type(init).__module__ != 'unittest.mock'
                ):
                    term()
                    init()
        except Exception:
            pass
        return list_wasapi_output_devices()

    def _open_wasapi_stream(self, profile: AudioProfile, source_info: dict | None, preferred_device: str):
        import sounddevice as sd

        explicit_pin = str(getattr(profile, 'output_device', '') or '').strip()
        target_pref = explicit_pin or preferred_device
        dev_idx, dev_info = select_wasapi_device(sd, target_pref)
        dev_name = str(dev_info['name'])
        pin_missing_note = ''
        if explicit_pin and not _device_matches(dev_name, explicit_pin):
            pin_missing_note = f'Chưa cắm "{explicit_pin}" → Tạm phát qua {dev_name}'
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

            rates = preferred_exclusive_rates(source_sr, dev_sr, profile.upsample)
            sr_family = 44100 if (source_sr > 0 and source_sr % 44100 == 0) else 48000
            fmt_cache_key = (dev_name.lower(), str(profile.upsample), sr_family)
            with self._lock:
                cached_fmt = self._last_exclusive_format.get(fmt_cache_key)
            attempts: list[tuple[int, str]] = []
            if cached_fmt is not None and cached_fmt[0] in rates:
                attempts.append(cached_fmt)
            for sr in rates:
                for dtype in ('int32', 'int24', 'float32', 'int16'):
                    pair = (sr, dtype)
                    if pair != cached_fmt:
                        attempts.append(pair)
            for sr, dtype in attempts:
                stream = None
                try:
                    # No Python callback: PortAudio runs WASAPI Exclusive pump in pure C!
                    stream = sd.RawOutputStream(
                        device=dev_idx,
                        channels=2,
                        dtype=dtype,
                        samplerate=sr,
                        blocksize=0,
                        latency=0.10,
                        extra_settings=sd.WasapiSettings(exclusive=True),
                    )
                    with self._lock:
                        self._last_exclusive_format[fmt_cache_key] = (sr, dtype)
                    return stream, dev_name, sr, dtype, 'exclusive', pin_missing_note
                except Exception:
                    if stream is not None:
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
            fallback_reason = pin_missing_note or 'Thiết bị không hỗ trợ Exclusive hoặc đang bận → Hi-Fi Shared'
        else:
            with self._lock:
                release_excl = self._exclusive_held
                self._exclusive_held = False
            if release_excl and self._on_after_exclusive is not None:
                try:
                    self._on_after_exclusive()
                except Exception:
                    pass
            fallback_reason = pin_missing_note

        for sr in (dev_sr, 48000, 44100):
            stream = None
            try:
                stream = sd.RawOutputStream(
                    device=dev_idx,
                    channels=2,
                    dtype='float32',
                    samplerate=sr,
                    blocksize=0,
                    latency=0.16,
                    extra_settings=sd.WasapiSettings(exclusive=False),
                )
                actual_mode = 'shared_fallback' if fallback_reason else 'shared'
                return stream, dev_name, sr, 'float32', actual_mode, fallback_reason
            except Exception:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass

        raise RuntimeError('Không mở được thiết bị đầu ra WASAPI.')

    def _spawn_ffmpeg(
        self,
        source_path: str,
        start_ms: int,
        track: int,
        filter_graph: str,
        out_sr: int = 48000,
    ) -> subprocess.Popen:
        ffmpeg = find_tool('ffmpeg')
        cmd = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '2']
        if start_ms > 20:
            cmd.extend(['-ss', f'{start_ms / 1000.0:.3f}'])
        cmd.extend([
            '-i', str(source_path),
            '-map', f'0:a:{int(track)}',
            '-vn', '-sn', '-dn',
            '-af', filter_graph,
            '-f', 'f64le', '-ac', '2',
            'pipe:1',
        ])
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        buf_bytes = max(262144, self._chunk_frames_for_rate(out_sr) * 2 * 8 * 4)
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=buf_bytes,
            creationflags=flags,
        )

    @staticmethod
    def _read_exact(stdout, size: int, cancel_event: threading.Event) -> bytes:
        chunks = []
        remaining = size
        while remaining > 0 and not cancel_event.is_set():
            part = stdout.read(remaining)
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        return b''.join(chunks)

    def _writer_loop(
        self,
        op_id: int,
        stream,
        proc: subprocess.Popen,
        out_sr: int,
        out_dtype: str,
        cancel_event: threading.Event,
        stream_lock=None,
        stream_closed: list[bool] | None = None,
    ):
        frame_bytes = 16  # Stereo 64-bit float (2 * 8 bytes)
        chunk_bytes = self._chunk_frames_for_rate(out_sr) * frame_bytes
        fade_samples = max(1, int(0.012 * out_sr))
        dither_offset = 0
        current_amp = 0.0
        last_frame = np.zeros(2, dtype=np.float64)
        with self._lock:
            current_gain_lin = self._target_gain_linear
        started = False
        try:
            stdout = proc.stdout
            if stdout is None:
                return

            # Pre-buffer ~128ms of end-to-end 64-bit DSP audio in RAM BEFORE starting DAC stream.
            prebuffer = []
            while len(prebuffer) < self._PREBUFFER_CHUNKS and not cancel_event.is_set():
                raw = self._read_exact(stdout, chunk_bytes, cancel_event)
                if not raw:
                    break
                usable = len(raw) - (len(raw) % frame_bytes)
                if usable > 0:
                    prebuffer.append(np.frombuffer(raw[:usable], dtype='<f8').reshape(-1, 2).copy())
                if len(raw) < chunk_bytes:
                    break

            if cancel_event.is_set() or op_id != self._op_id or not prebuffer:
                return

            with self._lock:
                current_gain_lin = self._target_gain_linear
            stream.start()
            started = True

            def _emit_chunk(pcm: np.ndarray) -> bool:
                nonlocal current_amp, current_gain_lin, dither_offset, last_frame
                with self._lock:
                    if cancel_event.is_set() or op_id != self._op_id or self._muted or not self._playing or self._paused:
                        target_amp = 0.0
                    else:
                        target_amp = self._user_volume
                    target_gain = self._target_gain_linear

                # Slew mastering gain smoothly in 64-bit float at <= 0.6 dB/sec so adjustments are inaudible.
                if abs(target_gain - current_gain_lin) > 1e-6:
                    max_ratio = 10.0 ** (0.6 * (len(pcm) / float(max(8000, out_sr))) / 20.0)
                    if target_gain > current_gain_lin:
                        next_gain = min(target_gain, current_gain_lin * max_ratio)
                    else:
                        next_gain = max(target_gain, current_gain_lin / max_ratio)
                    ramp = np.linspace(current_gain_lin, next_gain, len(pcm), dtype=np.float64)[:, None]
                    pcm_gained = pcm * ramp
                    current_gain_lin = next_gain
                else:
                    pcm_gained = pcm * float(current_gain_lin)

                processed, current_amp = apply_micro_fade(pcm_gained, current_amp, target_amp, fade_samples)
                if len(processed) > 0:
                    last_frame = processed[-1].copy()
                raw_bytes = quantize_pcm(processed, out_dtype, rng=None, dither_offset=dither_offset)
                dither_offset = (dither_offset + len(pcm)) % _TPDF_LEN
                uf = stream.write(raw_bytes)
                with self._lock:
                    self._current_amp = current_amp
                    if op_id == self._op_id:
                        self._played_frames += len(pcm)
                        self._last_write_mono = time.monotonic()
                        if uf:
                            self._underflows += 1
                return not (cancel_event.is_set() or op_id != self._op_id)

            for chunk in prebuffer:
                if not _emit_chunk(chunk):
                    return

            while not cancel_event.is_set() and op_id == self._op_id:
                raw = self._read_exact(stdout, chunk_bytes, cancel_event)
                if not raw:
                    break
                usable = len(raw) - (len(raw) % frame_bytes)
                if usable > 0:
                    pcm = np.frombuffer(raw[:usable], dtype='<f8').reshape(-1, 2).copy()
                    if not _emit_chunk(pcm):
                        break
                if len(raw) < chunk_bytes:
                    break
        except Exception as err:
            logger.debug('AudioStreamEngine writer exited: %s', err)
        finally:
            # Smooth zero-crossing cosine release ONLY on natural EOF (skip blocking writes on seek/stop cancel).
            if started and not cancel_event.is_set() and float(np.max(np.abs(last_frame))) > 1e-5:
                try:
                    tail = build_release_tail(last_frame, max(8, int(0.006 * out_sr)))
                    raw_tail = quantize_pcm(tail, out_dtype, rng=None, dither_offset=dither_offset)
                    stream.write(raw_tail)
                except Exception:
                    pass
            def _close_stream_once():
                if stream_closed is not None:
                    if stream_closed[0]:
                        return
                    stream_closed[0] = True
                try:
                    stream.abort()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass

            if stream_lock is not None:
                with stream_lock:
                    _close_stream_once()
            else:
                _close_stream_once()
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

    def _stop_active_worker(self, release_exclusive: bool = True):
        with self._lock:
            cancel_ev = self._cancel_event
            proc = self._active_proc
            stream = self._active_stream
            stream_lock = self._active_stream_lock
            stream_closed = self._active_stream_closed
            thread = self._writer_thread
            release_excl = bool(release_exclusive and self._exclusive_held)
            if release_excl:
                self._exclusive_held = False
            self._active_proc = None
            self._active_stream = None
            self._active_stream_lock = None
            self._active_stream_closed = None
            self._writer_thread = None

        if cancel_ev is not None:
            cancel_ev.set()
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        # PortAudio WASAPI is not thread-safe for concurrent Pa_AbortStream + Pa_WriteStream.
        # Killing FFmpeg + setting cancel_event lets _writer_loop finish its active ~42ms
        # chunk and close the stream cleanly on its own thread; only abort externally if
        # a stalled DAC/driver keeps the writer blocked past the grace window.
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.22)
            if thread.is_alive() and stream is not None:
                if stream_lock is not None:
                    with stream_lock:
                        if stream_closed is None or not stream_closed[0]:
                            try:
                                stream.abort()
                            except Exception:
                                pass
                else:
                    try:
                        stream.abort()
                    except Exception:
                        pass
                thread.join(timeout=0.28)
        elif stream is not None:
            def _close_now():
                if stream_closed is not None:
                    if stream_closed[0]:
                        return
                    stream_closed[0] = True
                try:
                    stream.abort()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass

            if stream_lock is not None:
                with stream_lock:
                    _close_now()
            else:
                _close_now()

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
        """Start or seamlessly reconfigure the in-RAM DSP + C-blocking WASAPI pipeline."""
        effective_gain_db = float(gain_db)
        if (
            not profile.normalize
            and source_info is None
            and (profile.tone not in ('off', 'studio_room') or profile.restorer in ('natural', 'vivid'))
            and abs(effective_gain_db) < 0.01
        ):
            effective_gain_db = -0.8
        clamped_gain = max(-24.0, min(12.0, effective_gain_db))

        with self._lock:
            self._op_id += 1
            op_id = self._op_id
            self._source_path = str(source_path)
            self._profile = profile
            self._source_info = source_info
            self._base_gain_db = clamped_gain
            self._gain_db = clamped_gain
            self._target_gain_linear = 10.0 ** (clamped_gain / 20.0)
            self._playback_rate = max(0.25, min(4.0, float(playback_rate or 1.0)))
            self._track = int(track)
            self._preferred_device = preferred_device_name or ''
            self._start_ms = float(max(0, int(start_ms)))
            self._played_frames = 0
            self._last_write_mono = 0.0
            self._underflows = 0
            self._paused = bool(paused)
            self._playing = True

        self._stop_active_worker(release_exclusive=paused)
        if paused:
            return self.status_info()

        stream, dev_name, out_sr, out_dtype, actual_mode, fallback_reason = self._open_wasapi_stream(
            profile, source_info, preferred_device_name or ''
        )
        filter_graph, summary = build_realtime_filter_graph(
            profile,
            source_info,
            gain_db,
            out_sr,
            playback_rate=max(0.25, min(4.0, float(playback_rate or 1.0))),
        )
        proc = self._spawn_ffmpeg(str(source_path), max(0, int(start_ms)), int(track), filter_graph, out_sr=out_sr)
        cancel_event = threading.Event()
        stream_lock = threading.Lock()
        stream_closed = [False]
        thread = threading.Thread(
            target=self._writer_loop,
            args=(op_id, stream, proc, out_sr, out_dtype, cancel_event, stream_lock, stream_closed),
            name='BoTube-HiFi-WASAPI-Pump',
            daemon=True,
        )

        with self._lock:
            if op_id != self._op_id or not self._playing or self._paused:
                superseded = True
            else:
                superseded = False
                self._cancel_event = cancel_event
                self._active_stream = stream
                self._active_stream_lock = stream_lock
                self._active_stream_closed = stream_closed
                self._active_proc = proc
                self._writer_thread = thread
                self._current_amp = 0.0
                self._out_sr = out_sr
                self._out_dtype = out_dtype
                raw_lat = getattr(stream, 'latency', None)
                if isinstance(raw_lat, (int, float)) and not isinstance(raw_lat, bool) and 0.001 <= float(raw_lat) <= 0.5:
                    self._latency_sec = float(raw_lat)
                else:
                    self._latency_sec = 0.10 if actual_mode == 'exclusive' else 0.16
                self._device_name = dev_name
                self._actual_mode = actual_mode
                self._fallback_reason = fallback_reason
                self._filter_summary = summary

        if superseded:
            cancel_event.set()
            try:
                stream.close()
            except Exception:
                pass
            try:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
            return self.status_info()

        thread.start()
        return self.status_info()

    def pause(self):
        with self._lock:
            if not self._playing or self._paused:
                return
            paused_pos_ms = float(self.position_ms())
            self._op_id += 1
            self._paused = True
            self._start_ms = paused_pos_ms
            self._played_frames = 0
            self._last_write_mono = 0.0
        self._stop_active_worker(release_exclusive=True)

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

    def stop(self, release_exclusive: bool = True):
        with self._lock:
            self._op_id += 1
            self._playing = False
            self._paused = False
            self._last_write_mono = 0.0
        self._stop_active_worker(release_exclusive=release_exclusive)

    def shutdown(self):
        self.stop()
