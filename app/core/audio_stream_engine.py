"""Zero-disk 64-bit FFmpeg -> RAM pre-buffer -> GIL-free C-blocking WASAPI Shared/Exclusive engine."""
import logging
import os
import subprocess
import threading

import numpy as np

from core.audio_effects import find_tool
from core.audio_profile import AudioProfile, build_realtime_filter_graph

logger = logging.getLogger(__name__)

# Precomputed 65536-sample TPDF dither table (~256 KB RAM) for fast, zero-allocation quantization.
_TPDF_TABLE = (
    np.random.default_rng(20261124).random(65536, dtype=np.float32)
    - np.random.default_rng(20261125).random(65536, dtype=np.float32)
)


def is_stream_engine_available():
    """Return True when sounddevice/PortAudio and FFmpeg are usable."""
    try:
        import sounddevice  # noqa: F401
        find_tool('ffmpeg')
        return True
    except Exception:
        return False


def _tpdf_slice(shape, offset: int) -> np.ndarray:
    total = int(shape[0]) * int(shape[1])
    tbl_len = len(_TPDF_TABLE)
    start = offset % tbl_len
    if start + total <= tbl_len:
        return _TPDF_TABLE[start:start + total].reshape(shape)
    idx = (np.arange(total, dtype=np.int64) + start) % tbl_len
    return _TPDF_TABLE[idx].reshape(shape)


def quantize_pcm(
    samples_f32: np.ndarray,
    dtype: str,
    rng: np.random.Generator | None = None,
    dither_offset: int = 0,
) -> bytes:
    """Quantize stereo float32 [-1, 1] frames to target DAC format with optional TPDF dither."""
    if samples_f32.size == 0:
        return b''
    arr = np.asarray(samples_f32, dtype=np.float32)
    if dtype == 'float32':
        return np.clip(arr, -1.0, 1.0).astype('<f4', copy=False).tobytes()

    def _dither(lsb_scale: float) -> np.ndarray:
        if rng is not None:
            return (rng.random(arr.shape, dtype=np.float32) - rng.random(arr.shape, dtype=np.float32)) * lsb_scale
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


class AudioStreamEngine:
    """Zero-disk FFmpeg 64-bit DSP pipe feeding C-blocking WASAPI Shared or Exclusive."""

    _CHUNK_FRAMES = 2048
    _PREBUFFER_CHUNKS = 3  # ~128 ms pre-buffered before starting hardware DAC stream

    def __init__(self, on_before_exclusive=None, on_after_exclusive=None):
        self._lock = threading.RLock()
        self._on_before_exclusive = on_before_exclusive
        self._on_after_exclusive = on_after_exclusive

        self._op_id = 0
        self._writer_thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._active_proc: subprocess.Popen | None = None
        self._active_stream = None

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
            elapsed = max(0.0, (self._played_frames / float(self._out_sr)) - hw_latency) * 1000.0 * self._playback_rate
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
            }

    def _open_wasapi_stream(self, profile: AudioProfile, source_info: dict | None, preferred_device: str):
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
                        return stream, dev_name, sr, dtype, 'exclusive', ''
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
            bufsize=131072,
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
    ):
        chunk_bytes = self._CHUNK_FRAMES * 2 * 4
        fade_samples = max(1, int(0.012 * out_sr))
        dither_offset = 0
        current_amp = 0.0
        with self._lock:
            current_gain_lin = self._target_gain_linear
        started = False
        try:
            stdout = proc.stdout
            if stdout is None:
                return

            # Pre-buffer ~128ms of decoded 64-bit DSP audio in RAM BEFORE starting DAC stream.
            prebuffer = []
            while len(prebuffer) < self._PREBUFFER_CHUNKS and not cancel_event.is_set():
                raw = self._read_exact(stdout, chunk_bytes, cancel_event)
                if not raw:
                    break
                usable = len(raw) - (len(raw) % 8)
                if usable > 0:
                    prebuffer.append(np.frombuffer(raw[:usable], dtype='<f4').reshape(-1, 2).copy())
                if len(raw) < chunk_bytes:
                    break

            if cancel_event.is_set() or op_id != self._op_id or not prebuffer:
                return

            with self._lock:
                current_gain_lin = self._target_gain_linear
            stream.start()
            started = True

            def _emit_chunk(pcm: np.ndarray) -> bool:
                nonlocal current_amp, current_gain_lin, dither_offset
                with self._lock:
                    if cancel_event.is_set() or op_id != self._op_id or self._muted or not self._playing or self._paused:
                        target_amp = 0.0
                    else:
                        target_amp = self._user_volume
                    target_gain = self._target_gain_linear

                # Slew mastering gain smoothly at <= 0.6 dB/sec (~0.025 dB/chunk) so volume changes are inaudible.
                if abs(target_gain - current_gain_lin) > 1e-5:
                    max_ratio = 10.0 ** (0.6 * (len(pcm) / float(max(8000, out_sr))) / 20.0)
                    if target_gain > current_gain_lin:
                        next_gain = min(target_gain, current_gain_lin * max_ratio)
                    else:
                        next_gain = max(target_gain, current_gain_lin / max_ratio)
                    ramp = np.linspace(current_gain_lin, next_gain, len(pcm), dtype=np.float32)[:, None]
                    pcm_gained = pcm * ramp
                    current_gain_lin = next_gain
                else:
                    pcm_gained = pcm * float(current_gain_lin)

                processed, current_amp = apply_micro_fade(pcm_gained, current_amp, target_amp, fade_samples)
                raw_bytes = quantize_pcm(processed, out_dtype, rng=None, dither_offset=dither_offset)
                dither_offset = (dither_offset + pcm.size) % len(_TPDF_TABLE)
                uf = stream.write(raw_bytes)
                with self._lock:
                    self._current_amp = current_amp
                    if op_id == self._op_id:
                        self._played_frames += len(pcm)
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
                usable = len(raw) - (len(raw) % 8)
                if usable > 0:
                    pcm = np.frombuffer(raw[:usable], dtype='<f4').reshape(-1, 2).copy()
                    if not _emit_chunk(pcm):
                        break
                if len(raw) < chunk_bytes:
                    break
        except Exception as err:
            logger.debug('AudioStreamEngine writer exited: %s', err)
        finally:
            # Smooth 12ms fade-out tail if stream started and was paused/stopped cleanly.
            if started and current_amp > 1e-4:
                try:
                    tail = np.zeros((fade_samples, 2), dtype=np.float32)
                    raw_tail = quantize_pcm(tail, out_dtype, rng=None, dither_offset=dither_offset)
                    stream.write(raw_tail)
                except Exception:
                    pass
            try:
                stream.abort()
            except Exception:
                pass
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
            thread = self._writer_thread
            release_excl = bool(release_exclusive and self._exclusive_held)
            if release_excl:
                self._exclusive_held = False
            self._active_proc = None
            self._active_stream = None
            self._writer_thread = None

        if cancel_ev is not None:
            cancel_ev.set()
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.35)
            if thread.is_alive() and stream is not None:
                try:
                    stream.abort()
                except Exception:
                    pass
                thread.join(timeout=0.65)
        elif stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

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
        if not profile.normalize and (profile.tone != 'off' or profile.restorer != 'off') and abs(effective_gain_db) < 0.01:
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
        proc = self._spawn_ffmpeg(str(source_path), max(0, int(start_ms)), int(track), filter_graph)
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._writer_loop,
            args=(op_id, stream, proc, out_sr, out_dtype, cancel_event),
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
                self._active_proc = proc
                self._writer_thread = thread
                self._current_amp = 0.0
                self._out_sr = out_sr
                self._out_dtype = out_dtype
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
            self._op_id += 1
            self._paused = True
            self._start_ms = float(self.position_ms())
            self._played_frames = 0
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

    def stop(self):
        with self._lock:
            self._op_id += 1
            self._playing = False
            self._paused = False
        self._stop_active_worker(release_exclusive=True)

    def shutdown(self):
        self.stop()
