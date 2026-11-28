"""Commercial-grade zero-disk audio benchmark (ITU-R BS.1770-4, EBU R128, AES17, RMAA)."""
from collections import OrderedDict
import copy
import math
import os
import subprocess
import threading
import time

import numpy as np

from core.audio_effects import AudioPreparationCancelled, find_tool, run_tool
from core.audio_loudness import (
    _parse_ebur128_stderr,
    _parse_loudnorm_stderr,
    probe_audio_stream,
    valid_measurement,
)
from core.audio_profile import (
    AudioProfile,
    DEFAULT_TARGET_LUFS,
    _rbj_magnitude_db,
    build_realtime_filter_graph,
    resolve_profile_gain_db,
    resolve_restorer,
    tone_peak_pad_db,
)
from core.audio_stream_engine import quantize_pcm
from control.worker_lifecycle import OwnedProcesses

_LAB_CACHE_LOCK = threading.Lock()
_LAB_SUITE_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_LAB_CACHE_MAX = 32

BENCH_FREQS = [
    round(10.0 ** (math.log10(20.0) + (math.log10(20000.0) - math.log10(20.0)) * (i / 127.0)), 2)
    for i in range(128)
]
THD_FFT_FREQS = [
    round(10.0 ** (math.log10(20.0) + (math.log10(20000.0) - math.log10(20.0)) * (i / 191.0)), 2)
    for i in range(192)
]


def _fmt_db_floor(val: float, floor: float = -140.0) -> str:
    return f'< {floor:.0f} dB' if float(val) <= floor else f'{float(val):.1f} dB'


def _fmt_pct_floor(pct: float, floor_pct: float = 0.00001) -> str:
    return f'< {floor_pct:.5f}%' if float(pct) < floor_pct else f'{float(pct):.5f}%'


def _fmt_noise_floor(snr_db: float) -> str:
    floor_db = -abs(float(snr_db))
    return '< -144 dBFS' if floor_db <= -144.0 else f'{floor_db:.1f} dBFS'


def _blackman_harris_4(n: int) -> np.ndarray:
    idx = np.arange(n, dtype=np.float64)
    ang = (2.0 * math.pi * idx) / float(n)
    return 0.35875 - 0.48829 * np.cos(ang) + 0.14128 * np.cos(2.0 * ang) - 0.01168 * np.cos(3.0 * ang)


def measure_true_peak_4x(samples_f64: np.ndarray, slices: int = 96) -> tuple[float, int, list[float]]:
    """Compute ITU-R BS.1770-4 4x FFT oversampled intersample True-Peak (dBTP), clip count & timeline."""
    arr = np.asarray(samples_f64, dtype=np.float64)
    n_slices = max(8, int(slices))
    if arr.size == 0 or len(arr) < 4:
        return -120.0, 0, [-72.0] * n_slices

    if arr.ndim == 1:
        arr = np.column_stack((arr, arr))
    total = len(arr)
    block = 16384
    max_lin = 0.0
    clip_count = 0
    clip_thresh = 10.0 ** (-0.01 / 20.0)
    bucket_peaks = np.full(n_slices, 1e-6, dtype=np.float64)

    for start in range(0, total, block):
        end = min(total, start + block)
        seg = arr[start:end]
        n = len(seg)
        if n < 8:
            abs_up = np.abs(seg)
        else:
            pad_spec = np.zeros((2 * n + 1, seg.shape[1]), dtype=np.complex128)
            spec = np.fft.rfft(seg, axis=0)
            pad_spec[: len(spec), :] = spec
            up = np.fft.irfft(pad_spec, n=4 * n, axis=0) * 4.0
            abs_up = np.abs(up)

        blk_max = float(np.max(abs_up))
        if blk_max > max_lin:
            max_lin = blk_max
        frame_peak = np.max(abs_up, axis=1)
        clip_count += int(np.sum(frame_peak > clip_thresh))

        b_start = min(n_slices - 1, (start * n_slices) // total)
        b_end = min(n_slices - 1, ((end - 1) * n_slices) // total)
        up_len = len(frame_peak)
        for b in range(b_start, b_end + 1):
            f0 = max(start, (b * total) // n_slices)
            f1 = min(end, max(f0 + 1, ((b + 1) * total) // n_slices))
            u0 = max(0, ((f0 - start) * up_len) // n)
            u1 = min(up_len, max(u0 + 1, ((f1 - start) * up_len) // n))
            local_pk = float(np.max(frame_peak[u0:u1]))
            if local_pk > bucket_peaks[b]:
                bucket_peaks[b] = local_pk

    peak_dbtp = round(20.0 * math.log10(max(1e-6, max_lin)), 2)
    env_db = [round(max(-72.0, 20.0 * math.log10(max(1e-6, float(v)))), 2) for v in bucket_peaks]
    return peak_dbtp, clip_count, env_db


def _welch_avg_power(samples_f64: np.ndarray, sample_rate: int, base_nperseg: int = 4096):
    arr = np.asarray(samples_f64, dtype=np.float64)
    if arr.size == 0 or sample_rate <= 0:
        return None, None
    if arr.ndim == 1:
        arr = np.column_stack((arr, arr))

    nperseg = max(1024, int(round(float(base_nperseg) * float(sample_rate) / 48000.0)))
    nperseg += nperseg % 2
    if len(arr) < nperseg:
        pad = np.zeros((nperseg - len(arr), arr.shape[1]), dtype=np.float64)
        arr = np.vstack((arr, pad))

    win = np.hanning(nperseg).astype(np.float64)
    scale = 2.0 / max(1e-9, float(np.sum(win)))
    hop = max(256, nperseg // 2)
    acc = None
    count = 0
    for pos in range(0, len(arr) - nperseg + 1, hop):
        seg = arr[pos:pos + nperseg] * win[:, None]
        spec = np.fft.rfft(seg, axis=0) * scale
        pwr = 0.5 * (spec[:, 0].real ** 2 + spec[:, 0].imag ** 2 + spec[:, 1].real ** 2 + spec[:, 1].imag ** 2)
        acc = pwr if acc is None else (acc + pwr)
        count += 1
    if acc is None or count == 0:
        return None, None

    fft_freqs = np.fft.rfftfreq(nperseg, d=1.0 / float(sample_rate))
    return fft_freqs, acc / float(count)


def welch_log_spectrum_db(
    samples_f64: np.ndarray,
    sample_rate: int,
    freqs_hz: list[float] | None = None,
    smooth_oct: float = 1.0 / 24.0,
) -> list[float]:
    """Compute calibrated stereo Hann Welch PSD with optional 1/12-octave Gaussian log smoothing."""
    freqs = list(freqs_hz or BENCH_FREQS)
    fft_freqs, avg_pwr = _welch_avg_power(samples_f64, sample_rate)
    if fft_freqs is None or avg_pwr is None:
        return [-120.0] * len(freqs)

    if smooth_oct <= 0.0:
        interp_pwr = np.interp(freqs, fft_freqs, avg_pwr, left=1e-12, right=1e-12)
        return [round(max(-120.0, 10.0 * math.log10(max(1e-12, float(p)))), 2) for p in interp_pwr]

    pos_mask = fft_freqs > 1.0
    pf = fft_freqs[pos_mask]
    pp = avg_pwr[pos_mask]
    log_pf = np.log2(pf)
    out = []
    span = smooth_oct * 3.0
    for f in freqs:
        lf = math.log2(max(2.0, float(f)))
        in_win = (log_pf >= lf - span) & (log_pf <= lf + span)
        if np.any(in_win):
            d = (log_pf[in_win] - lf) / smooth_oct
            w = np.exp(-0.5 * d * d)
            val = float(np.sum(pp[in_win] * w) / max(1e-12, float(np.sum(w))))
        else:
            val = float(np.interp(float(f), pf, pp, left=1e-12, right=1e-12))
        out.append(round(max(-120.0, 10.0 * math.log10(max(1e-12, val))), 2))
    return out


def _windowed_crest_dr(samples_f64: np.ndarray, sample_rate: int) -> float:
    arr = np.asarray(samples_f64, dtype=np.float64)
    if arr.size == 0 or sample_rate <= 0:
        return 0.0
    if arr.ndim == 1:
        arr = np.column_stack((arr, arr))
    blk = max(64, int(round(0.30 * float(sample_rate))))
    if len(arr) < blk * 2:
        rms = float(np.sqrt(np.mean(arr * arr)))
        pk = float(np.max(np.abs(arr)))
        return round(20.0 * math.log10(max(1e-9, pk) / max(1e-9, rms)), 2)

    n_blocks = len(arr) // blk
    trimmed = arr[: n_blocks * blk].reshape(n_blocks, blk, arr.shape[1])
    rms_blocks = np.sqrt(np.mean(trimmed * trimmed, axis=(1, 2)))
    pk_blocks = np.max(np.abs(trimmed), axis=(1, 2))
    max_rms = float(np.max(rms_blocks))
    if max_rms <= 1e-8:
        return 0.0
    active = rms_blocks >= (max_rms * (10.0 ** (-35.0 / 20.0)))
    crests = 20.0 * np.log10(np.maximum(1e-9, pk_blocks[active]) / np.maximum(1e-9, rms_blocks[active]))
    return round(float(np.percentile(crests, 90)), 2) if crests.size else 0.0


def _analyze_source_forensics(orig_f64: np.ndarray, in_sr: int) -> dict:
    flat_clips = 0
    if orig_f64.size >= 4:
        frame_max = np.max(np.abs(orig_f64), axis=1)
        hot = frame_max >= 0.9995
        flat_clips = int(np.sum(hot[:-1] & hot[1:]))

    fft_freqs, avg_pwr = _welch_avg_power(orig_f64, in_sr, base_nperseg=4096)
    max_scan = min(48000, int(in_sr * 0.46)) if in_sr >= 88200 else min(20200, int(in_sr * 0.46))
    cutoff_hz = min(max_scan, int(in_sr * 0.45))
    if fft_freqs is not None and avg_pwr is not None and in_sr >= 32000:
        spec_db = 10.0 * np.log10(np.maximum(1e-12, avg_pwr))
        mid_mask = (fft_freqs >= 2000.0) & (fft_freqs <= 7000.0)
        if np.any(mid_mask):
            ref_db = float(np.percentile(spec_db[mid_mask], 85))
            if ref_db >= -70.0:
                if in_sr >= 88200:
                    hi_lo = min(42000.0, float(in_sr) * 0.43)
                    hi_mask = (fft_freqs >= hi_lo) & (fft_freqs <= float(in_sr) * 0.48)
                    step = 400
                else:
                    hi_mask = (fft_freqs >= 19800.0) & (fft_freqs <= min(23500.0, float(in_sr) * 0.48))
                    step = 200
                ceil_db = float(np.median(spec_db[hi_mask])) if np.any(hi_mask) else (ref_db - 60.0)
                thresh = min(ref_db - 22.0, max(ceil_db + 8.0, ref_db - 42.0))
                cutoff_hz = 10000
                for center in range(max_scan, 9999, -step):
                    half_w = 350.0 if in_sr >= 88200 else 250.0
                    band = (fft_freqs >= center - half_w) & (fft_freqs <= center + half_w)
                    if np.any(band) and float(np.median(spec_db[band])) >= thresh:
                        if in_sr < 88200 and center >= 19700:
                            cutoff_hz = 20000
                        else:
                            cutoff_hz = center
                        break

    return {'source_flat_clips': flat_clips, 'source_cutoff_hz': cutoff_hz}


def compute_k_weighted_db(samples_f64: np.ndarray, sample_rate: int) -> float:
    """Compute ITU-R BS.1770-4 K-weighted integrated loudness (LKFS/LUFS approx) in RAM."""
    arr = np.asarray(samples_f64, dtype=np.float64)
    if arr.size == 0 or sample_rate <= 0:
        return -70.0
    fft_freqs, avg_pwr = _welch_avg_power(arr, int(sample_rate), base_nperseg=2048)
    if fft_freqs is None or avg_pwr is None:
        return -70.0
    mask = fft_freqs >= 20.0
    pf = fft_freqs[mask]
    pp = avg_pwr[mask]
    if pf.size == 0:
        return -70.0

    # Analytical ITU-R BS.1770-4 pre-filter (+4 dB high-shelf @ 1681.97 Hz) + 2nd-order RLB high-pass (@ 38.135 Hz)
    log_grid = [
        10.0 ** (math.log10(20.0) + (math.log10(20000.0) - math.log10(20.0)) * (i / 63.0))
        for i in range(64)
    ]
    shelf_grid_db = _rbj_magnitude_db(log_grid, 1681.97, 0.7072, 4.0, float(sample_rate), 'highshelf')
    shelf_db = np.interp(pf, log_grid, shelf_grid_db)
    f0 = 38.13547087602444
    q_hp = 0.5003270373238773
    f_sq = pf * pf
    f0_sq = f0 * f0
    hp_sq = (f_sq * f_sq) / (((f_sq - f0_sq) ** 2) + ((pf * f0 / q_hp) ** 2))
    k_weight_sq = (10.0 ** (shelf_db / 10.0)) * hp_sq
    total_pwr = float(np.sum(pp * k_weight_sq))
    return round(max(-70.0, -0.691 + 10.0 * math.log10(max(1e-12, total_pwr))), 2)


def _describe_tonal_character(profile: AudioProfile, lab: dict) -> str:
    low = float(lab.get('low_delta_db', 0.0))
    mid = float(lab.get('mid_delta_db', 0.0))
    hi = float(lab.get('high_delta_db', 0.0))
    xt = float(lab.get('crosstalk_db', -140.0))
    traits = []
    if low >= 0.8:
        traits.append('âm trầm ấm và sâu hơn')
    elif low <= -0.8:
        traits.append('gọn bớt âm trầm')
    if mid >= 0.8:
        traits.append('giọng hát nổi rõ hơn')
    elif mid <= -0.6:
        traits.append('dịu bớt dải trung gắt')
    if hi >= 0.8:
        traits.append('dải cao thoáng sáng hơn')
    elif hi <= -0.8:
        traits.append('mượt bớt âm sibilance/chói')
    if xt > -45.0:
        traits.append('mở không gian như loa ngoài')
    if not traits:
        return 'cân chỉnh nhẹ nhàng'
    if len(traits) == 1:
        return traits[0]
    return ', '.join(traits[:-1]) + ' và ' + traits[-1]


def _stereo_correlation(samples_f64: np.ndarray) -> float:
    if len(samples_f64) < 16 or samples_f64.ndim != 2 or samples_f64.shape[1] < 2:
        return 1.0
    l_ch = samples_f64[:, 0]
    r_ch = samples_f64[:, 1]
    denom = float(np.sqrt(np.sum(l_ch * l_ch) * np.sum(r_ch * r_ch)))
    if denom <= 1e-12:
        return 1.0
    return round(float(np.sum(l_ch * r_ch) / denom), 3)


def _quantize_and_reconstruct(samples_f64: np.ndarray, out_dtype: str) -> np.ndarray:
    arr = np.asarray(samples_f64, dtype=np.float64)
    if arr.size == 0:
        return arr
    raw = quantize_pcm(arr, out_dtype)
    if out_dtype == 'int32':
        return np.frombuffer(raw, dtype='<i4').reshape(-1, 2).astype(np.float64) / 2147483647.0
    if out_dtype == 'int24':
        padded = np.zeros((len(arr) * 2, 4), dtype=np.uint8)
        b3 = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        padded[:, 1:4] = b3
        return (padded.view('<i4').reshape(-1, 2).astype(np.float64) / 256.0) / 8388607.0
    if out_dtype == 'int16':
        return np.frombuffer(raw, dtype='<i2').reshape(-1, 2).astype(np.float64) / 32767.0
    return np.frombuffer(raw, dtype='<f4').reshape(-1, 2).astype(np.float64)


def _run_pipe_tool(command, input_bytes: bytes, processes: OwnedProcesses, cancelled, timeout: float = 20.0) -> bytes:
    if cancelled():
        raise AudioPreparationCancelled()
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0
    proc = processes.track(
        subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
        )
    )

    def _feed():
        try:
            if proc.stdin is not None:
                proc.stdin.write(input_bytes)
                proc.stdin.close()
        except Exception:
            pass

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()
    started = time.monotonic()
    try:
        while True:
            try:
                stdout, _stderr = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancelled() or time.monotonic() - started > timeout:
                    processes.stop()
                    processes.wait()
                    if cancelled():
                        raise AudioPreparationCancelled()
                    raise RuntimeError('Đo kiểm phòng thu quá thời gian.')
        if cancelled():
            raise AudioPreparationCancelled()
        if proc.returncode:
            raise RuntimeError('Không chạy được chuỗi thử nghiệm phòng thu.')
        return stdout
    finally:
        if proc.poll() is None:
            processes.stop()
            processes.wait()
        processes.release(proc)


def _compute_log_fft_db(seg_mono: np.ndarray, sample_rate: int) -> tuple[np.ndarray, np.ndarray, list[float]]:
    n = len(seg_mono)
    w = _blackman_harris_4(n)
    w_scale = 2.0 / max(1e-9, float(np.sum(w)))
    x = np.abs(np.fft.rfft(seg_mono * w)) * w_scale
    fft_f = np.fft.rfftfreq(n, 1.0 / float(sample_rate))
    fft_db = 20.0 * np.log10(np.maximum(1e-9, x))
    log_f = np.log2(np.maximum(1.0, fft_f))
    half_step = (math.log2(20000.0 / 20.0) / float(len(THD_FFT_FREQS) - 1)) * 0.55
    binned = []
    for tf in THD_FFT_FREQS:
        ltf = math.log2(tf)
        m = (log_f >= ltf - half_step) & (log_f <= ltf + half_step)
        val = float(np.max(fft_db[m])) if np.any(m) else float(np.interp(tf, fft_f, fft_db))
        binned.append(round(max(-165.0, min(6.0, val)), 2))
    return x, fft_f, binned


def run_lab_suite(
    profile: AudioProfile,
    source_info: dict | None,
    gain_db: float,
    out_sr: int,
    out_dtype: str,
    processes: OwnedProcesses,
    cancelled,
) -> dict:
    """Single-pass 64-bit lab stimulus (Impulse, 1kHz THD+N, SMPTE IMD, AES17 -60dB SNR, Crosstalk)."""
    in_sr = max(8000, int((source_info or {}).get('sample_rate') or out_sr))
    actual_sr = in_sr if not profile.enabled else max(8000, int(out_sr))
    src_bits = int((source_info or {}).get('bits_per_raw_sample') or 24)
    ref_dtype = 'int16' if src_bits == 16 else 'int24'
    rest_mode = (resolve_restorer(profile, source_info) or {}).get('mode', 'Bypass')
    cache_k = (profile, in_sr, actual_sr, out_dtype, ref_dtype, rest_mode)
    if not cancelled():
        with _LAB_CACHE_LOCK:
            hit = _LAB_SUITE_CACHE.get(cache_k)
            if hit is not None:
                _LAB_SUITE_CACHE.move_to_end(cache_k)
                return copy.deepcopy(hit)

    ratio = float(actual_sr) / float(in_sr)
    blk_fft = 16384
    out_fft = max(8192, int(round(blk_fft * ratio)))
    out_fft += out_fft % 2

    # Coherent bin frequencies aligned to actual output FFT grid (eliminates 44.1->48k skirt leakage)
    f_1k = round(1000.0 * out_fft / float(actual_sr)) * float(actual_sr) / float(out_fft)
    f_60 = max(1, round(60.0 * out_fft / float(actual_sr))) * float(actual_sr) / float(out_fft)
    f_7k = round(7000.0 * out_fft / float(actual_sr)) * float(actual_sr) / float(out_fft)

    n_imp = max(4096, int(round(0.35 * in_sr)))
    imp = np.zeros((n_imp, 2), dtype=np.float64)
    imp[min(2048, n_imp // 2), 0] = 0.25

    n_tone = max(blk_fft + 4096, int(round(0.55 * in_sr)))
    t = np.arange(n_tone, dtype=np.float64) / float(in_sr)
    # Headroom-safe -14 dBFS stimulus so even +12 dB EQ stays strictly linear inside f64le DSP
    amp_in = 0.20
    s1k = (amp_in * np.sin(2.0 * math.pi * f_1k * t))[:, None] * np.ones((1, 2))
    s_imd = (0.16 * np.sin(2.0 * math.pi * f_60 * t) + 0.04 * np.sin(2.0 * math.pi * f_7k * t))[:, None] * np.ones((1, 2))
    s60 = (amp_in * (10.0 ** (-59.0 / 20.0)) * np.sin(2.0 * math.pi * f_1k * t))[:, None] * np.ones((1, 2))

    lab_in = np.vstack([imp, s1k, s_imd, s60]).astype('<f8')

    # Reference 1 kHz FFT at source's native PCM depth (bin-coherent at in_sr & AES17 -1.0 dBFS)
    f_1k_ref = round(1000.0 * blk_fft / float(in_sr)) * float(in_sr) / float(blk_fft)
    target_amp = 10.0 ** (-1.0 / 20.0)
    t_ref = np.arange(blk_fft, dtype=np.float64) / float(in_sr)
    s1k_ref = (target_amp * np.sin(2.0 * math.pi * f_1k_ref * t_ref))[:, None] * np.ones((1, 2))
    ref_q = _quantize_and_reconstruct(s1k_ref, ref_dtype)[:, 0]
    _, _, ref_thd_fft_db = _compute_log_fft_db(ref_q, in_sr)

    if not profile.enabled:
        out_f64 = lab_in
    else:
        ffmpeg = find_tool('ffmpeg')
        af, _ = build_realtime_filter_graph(profile, source_info, gain_db, out_sr)
        cmd = [
            ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '2',
            '-f', 'f64le', '-ar', str(in_sr), '-ac', '2', '-i', 'pipe:0',
            '-af', af, '-f', 'f64le', '-ac', '2', 'pipe:1',
        ]
        raw_out = _run_pipe_tool(cmd, lab_in.tobytes(), processes, cancelled, timeout=20.0)
        usable = len(raw_out) - (len(raw_out) % 16)
        out_f64 = np.frombuffer(raw_out[:usable], dtype='<f8').reshape(-1, 2)

    # 1. Impulse Transfer |H_L(f)|, Phase <H_L(f) and 1 kHz Stereo Crosstalk in linear 64-bit float
    n_imp_out = min(len(out_f64), int(round(n_imp * ratio)))
    n_tone_out = max(out_fft, int(round(n_tone * ratio)))
    ir_scale = (1.0 / 0.25) * (float(in_sr) / float(actual_sr))
    ir = out_f64[:n_imp_out] * ir_scale

    h_l = np.fft.rfft(ir[:, 0])
    h_r = np.fft.rfft(ir[:, 1])
    ir_freqs = np.fft.rfftfreq(len(ir), 1.0 / float(actual_sr))

    idx_1k = int(np.argmin(np.abs(ir_freqs - f_1k)))
    xtalk_db = 20.0 * math.log10(max(1e-18, abs(h_r[idx_1k])) / max(1e-18, abs(h_l[idx_1k])))
    xtalk_db = round(max(-160.0, min(0.0, xtalk_db)), 1)

    mag_db_all = 20.0 * np.log10(np.maximum(1e-9, np.abs(h_l)))
    lab_transfer_db = [round(float(np.interp(f, ir_freqs, mag_db_all)), 2) for f in BENCH_FREQS]

    n_pk = int(np.argmax(np.abs(ir[:, 0])))
    h_aligned = np.fft.rfft(np.roll(ir[:, 0], -n_pk))
    unwrapped = np.unwrap(np.angle(h_aligned)) * (180.0 / math.pi)
    lab_phase_raw = [float(np.interp(f, ir_freqs, unwrapped)) for f in BENCH_FREQS]
    idx_ref = min(len(lab_phase_raw) - 1, max(0, int(round(len(BENCH_FREQS) * 0.56))))
    wrap_shift = round(lab_phase_raw[idx_ref] / 360.0) * 360.0
    lab_phase_deg = [round(max(-180.0, min(180.0, p - wrap_shift)), 1) for p in lab_phase_raw]

    nyq_audible = min(18500.0, float(in_sr) * 0.44)
    transfer_audible = [v for f, v in zip(BENCH_FREQS, lab_transfer_db) if 25.0 <= f <= nyq_audible]
    mid_ref_v = float(np.median([v for f, v in zip(BENCH_FREQS, lab_transfer_db) if 700.0 <= f <= 1500.0]))
    tonal_rms_db = round(
        math.sqrt(sum((v - mid_ref_v) ** 2 for v in transfer_audible) / max(1, len(transfer_audible))), 2
    )
    low_vals = [v - mid_ref_v for f, v in zip(BENCH_FREQS, lab_transfer_db) if 25.0 <= f <= 250.0]
    mid_vals = [v - mid_ref_v for f, v in zip(BENCH_FREQS, lab_transfer_db) if 250.0 < f <= 4000.0]
    hi_vals = [v - mid_ref_v for f, v in zip(BENCH_FREQS, lab_transfer_db) if 4000.0 < f <= nyq_audible]
    low_delta_db = round(float(np.mean(low_vals)) if low_vals else 0.0, 2)
    mid_delta_db = round(float(np.mean(mid_vals)) if mid_vals else 0.0, 2)
    high_delta_db = round(float(np.mean(hi_vals)) if hi_vals else 0.0, 2)

    hi_bin = min(out_fft // 2, int(20000.0 * out_fft / float(actual_sr)))

    def _steady_slice_raw(seg_idx: int) -> np.ndarray:
        seg_start = n_imp_out + seg_idx * n_tone_out
        seg_end = min(len(out_f64), seg_start + n_tone_out)
        if seg_end - seg_start < out_fft:
            return np.zeros((out_fft, 2), dtype=np.float64)
        s = seg_start + ((seg_end - seg_start) - out_fft) // 2
        return out_f64[s:s + out_fft]

    # 2. 1 kHz Blackman-Harris THD+N & Log-Max FFT Spectrum calibrated to AES17 -1.0 dBFS at DAC quantizer
    raw_seg1 = _steady_slice_raw(0)
    scale_1k = target_amp / max(1e-9, float(np.max(np.abs(raw_seg1))))
    seg1 = _quantize_and_reconstruct(raw_seg1 * scale_1k, out_dtype)[:, 0] if profile.enabled else (raw_seg1[:, 0] * scale_1k)
    x1, _, thd_fft_db = _compute_log_fft_db(seg1, actual_sr)
    pk1 = int(np.argmax(x1[:hi_bin])) if hi_bin > 8 else 1
    sig_p = float(np.sum(x1[max(0, pk1 - 6):pk1 + 7] ** 2))
    n1_p = float(np.sum(x1[3:max(3, pk1 - 6)] ** 2) + np.sum(x1[pk1 + 7:hi_bin] ** 2))
    thdn_db = round(max(-165.0, min(0.0, 10.0 * math.log10(max(1e-30, n1_p) / max(1e-30, sig_p)))), 1)
    thdn_pct = round(100.0 * (10.0 ** (thdn_db / 20.0)), 6)

    # 3. SMPTE 60 Hz + 7 kHz (4:1) IMD calibrated to AES17 -1.0 dBFS at DAC quantizer
    raw_seg_imd = _steady_slice_raw(1)
    scale_imd = target_amp / max(1e-9, float(np.max(np.abs(raw_seg_imd))))
    seg_imd = _quantize_and_reconstruct(raw_seg_imd * scale_imd, out_dtype)[:, 0] if profile.enabled else (raw_seg_imd[:, 0] * scale_imd)
    w = _blackman_harris_4(out_fft)
    w_scale = 2.0 / max(1e-9, float(np.sum(w)))
    x_imd = np.abs(np.fft.rfft(seg_imd * w)) * w_scale
    b7k = max(10, int(round(f_7k * out_fft / float(actual_sr))))
    b60 = max(1, int(round(f_60 * out_fft / float(actual_sr))))
    carr_p = float(np.sum(x_imd[max(0, b7k - 5):b7k + 6] ** 2))
    side_p = 0.0
    for k in range(1, 6):
        lo_s = max(4, b7k - k * b60)
        hi_s = min(hi_bin - 4, b7k + k * b60)
        side_p += float(np.sum(x_imd[lo_s - 3:lo_s + 4] ** 2))
        side_p += float(np.sum(x_imd[hi_s - 3:hi_s + 4] ** 2))
    imd_db = round(max(-165.0, min(0.0, 10.0 * math.log10(max(1e-30, side_p) / max(1e-30, carr_p)))), 1)
    imd_pct = round(100.0 * (10.0 ** (imd_db / 20.0)), 6)

    # 4. AES17 -60 dBFS Dynamic Range & Effective Bits (ENOB)
    raw_seg60 = _steady_slice_raw(2)
    seg60 = _quantize_and_reconstruct(raw_seg60 * scale_1k, out_dtype)[:, 0] if profile.enabled else (raw_seg60[:, 0] * scale_1k)
    x60 = np.abs(np.fft.rfft(seg60 * w)) * w_scale
    sig60_p = float(np.sum(x60[max(0, pk1 - 6):pk1 + 7] ** 2))
    n60_p = float(np.sum(x60[3:max(3, pk1 - 6)] ** 2) + np.sum(x60[pk1 + 7:hi_bin] ** 2))
    raw_snr = 60.0 + 10.0 * math.log10(max(1e-30, sig60_p) / max(1e-30, n60_p))
    snr_cap = 192.0 if out_dtype == 'int32' else 150.0
    snr_db = round(min(snr_cap, max(0.0, raw_snr)), 1)
    max_bits = 32.0 if out_dtype == 'int32' else 24.0
    enob_bits = round(min(max_bits, max(0.0, (snr_db - 1.76) / 6.02)), 1)

    lab_res = {
        'lab_transfer_db': lab_transfer_db,
        'lab_phase_deg': lab_phase_deg,
        'tonal_rms_db': tonal_rms_db,
        'low_delta_db': low_delta_db,
        'mid_delta_db': mid_delta_db,
        'high_delta_db': high_delta_db,
        'crosstalk_db': xtalk_db,
        'thdn_db': thdn_db,
        'thdn_pct': thdn_pct,
        'thd_fft_freqs': list(THD_FFT_FREQS),
        'thd_fft_db': thd_fft_db,
        'ref_thd_fft_db': ref_thd_fft_db,
        'ref_bit_depth': 16 if ref_dtype == 'int16' else 24,
        'imd_db': imd_db,
        'imd_pct': imd_pct,
        'snr_db': snr_db,
        'noise_floor_db': round(max(-150.0, -abs(snr_db)), 1),
        'noise_floor_label': _fmt_noise_floor(snr_db),
        'enob_bits': enob_bits,
    }
    with _LAB_CACHE_LOCK:
        _LAB_SUITE_CACHE[cache_k] = copy.deepcopy(lab_res)
        _LAB_SUITE_CACHE.move_to_end(cache_k)
        while len(_LAB_SUITE_CACHE) > _LAB_CACHE_MAX:
            _LAB_SUITE_CACHE.popitem(last=False)
    return lab_res


def _pipe_f64_filter(
    ffmpeg: str,
    samples_f64: np.ndarray,
    in_sr: int,
    filter_graph: str,
    processes: OwnedProcesses,
    cancelled,
) -> np.ndarray:
    arr = np.asarray(samples_f64, dtype='<f8')
    if arr.size == 0:
        return np.zeros((0, 2), dtype=np.float64)
    cmd = [
        ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '2',
        '-f', 'f64le', '-ar', str(int(in_sr)), '-ac', '2', '-i', 'pipe:0',
        '-af', filter_graph, '-f', 'f64le', '-ac', '2', 'pipe:1',
    ]
    stdout = _run_pipe_tool(cmd, arr.tobytes(), processes, cancelled, timeout=25.0)
    usable = len(stdout) - (len(stdout) % 16)
    if usable <= 0:
        return np.zeros((0, 2), dtype=np.float64)
    return np.frombuffer(stdout[:usable], dtype='<f8').reshape(-1, 2).copy()


def _target_benchmark_sr(profile: AudioProfile, in_sr: int) -> int:
    sr = max(8000, int(in_sr or 48000))
    if not profile.enabled or profile.upsample == 'off':
        return sr
    is_44k = (sr % 44100 == 0)
    if profile.upsample == 'hires_sync':
        return max(sr, 176400 if is_44k else 192000)
    if profile.upsample == 'max_dac':
        return max(sr, 352800 if is_44k else 384000)
    return sr


def _decode_f64_excerpt(
    ffmpeg: str,
    source_path: str,
    track: int,
    start_sec: float,
    dur_sec: float,
    filter_graph: str,
    processes: OwnedProcesses,
    cancelled,
) -> np.ndarray:
    cmd = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '2']
    if start_sec > 0.05:
        cmd.extend(['-ss', f'{start_sec:.2f}'])
    cmd.extend([
        '-probesize', '262144', '-analyzeduration', '500000',
        '-t', f'{dur_sec:.2f}',
        '-i', str(source_path),
        '-map', f'0:a:{int(track)}',
        '-vn', '-sn', '-dn',
        '-af', filter_graph,
        '-f', 'f64le', '-ac', '2', 'pipe:1',
    ])
    stdout, _ = run_tool(cmd, processes, cancelled, timeout=25)
    usable = len(stdout) - (len(stdout) % 16)
    if usable <= 0:
        return np.zeros((0, 2), dtype=np.float64)
    return np.frombuffer(stdout[:usable], dtype='<f8').reshape(-1, 2).copy()


def _measure_excerpt_loudness(
    ffmpeg: str,
    source_path: str,
    track: int,
    start_sec: float,
    duration: float,
    processes: OwnedProcesses,
    cancelled,
) -> dict:
    meas_dur = min(30.0, max(1.0, float(duration or 12.0) - start_sec)) if duration > 0 else 15.0
    cmd = [ffmpeg, '-nostdin', '-hide_banner', '-threads', '4']
    if start_sec > 0.05 and duration > 34.0:
        cmd.extend(['-ss', f'{start_sec:.2f}', '-t', f'{meas_dur:.2f}'])
    cmd.extend([
        '-i', str(source_path), '-map', f'0:a:{int(track)}',
        '-vn', '-sn', '-dn', '-af', 'ebur128=peak=true', '-f', 'null', '-',
    ])
    _, stderr = run_tool(cmd, processes, cancelled, timeout=20)
    meas = _parse_ebur128_stderr(stderr)
    if meas is not None:
        return meas
    _, stderr2 = run_tool(
        [
            ffmpeg, '-nostdin', '-hide_banner', '-threads', '2',
            '-i', str(source_path), '-map', f'0:a:{int(track)}',
            '-vn', '-sn', '-dn', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=50:print_format=json',
            '-f', 'null', '-',
        ],
        processes,
        cancelled,
        timeout=20,
    )
    meas2 = _parse_loudnorm_stderr(stderr2)
    return meas2 if meas2 is not None else {'lufs': -16.0, 'peak_db': -1.0, 'silent': False}


def _build_listener_summary(
    profile: AudioProfile,
    source_info: dict | None,
    orig_tp_db: float,
    orig_clips: int,
    proc_tp_db: float,
    proc_clips: int,
    dr_delta_db: float,
    tonal_rms_db: float,
    lab: dict,
    full_peak_db: float | None = None,
    gain_db: float = 0.0,
) -> dict:
    tone_desc = _describe_tonal_character(profile, lab)
    thdn_db = float(lab.get('thdn_db', -140.0))
    climax_hot = bool(full_peak_db is not None and full_peak_db > 0.05)
    headroom_pad = tone_peak_pad_db(profile, source_info=source_info)
    climax_fixed = bool(climax_hot and (float(full_peak_db or 0.0) + float(gain_db) + headroom_pad) <= -0.5)

    # 3 non-expert comparison pillars
    if not profile.enabled:
        if orig_tp_db > -0.1 or orig_clips > 0:
            p_clean = {
                'title': 'Độ trong trẻo',
                'verdict': 'Dễ rè nhẹ',
                'detail': f'File gốc có {orig_clips:,} điểm vượt ngưỡng khi mở to.',
                'tone': 'warn',
            }
        elif climax_hot:
            p_clean = {
                'title': 'Độ trong trẻo',
                'verdict': 'Dễ rè cao trào',
                'detail': f'Đoạn cao trào toàn bài vượt trần ({full_peak_db:+.2f} dBTP).',
                'tone': 'warn',
            }
        else:
            p_clean = {
                'title': 'Độ trong trẻo',
                'verdict': 'Sạch như gốc',
                'detail': 'Phát thẳng nguyên bản, không có điểm vỡ đỉnh.',
                'tone': 'good',
            }
    elif proc_tp_db > -0.05 or proc_clips > 0:
        p_clean = {
            'title': 'Độ trong trẻo',
            'verdict': 'Kém hơn gốc',
            'detail': f'Xuất hiện {proc_clips:,} điểm vỡ đỉnh; nên bật Tự giảm Preamp.',
            'tone': 'warn',
        }
    elif (orig_clips > 0 or orig_tp_db > -0.2 or climax_fixed) and proc_clips == 0 and proc_tp_db <= -0.8:
        if orig_clips > 0:
            detail_c = f'Đã khử sạch {orig_clips:,} điểm vượt trần về 0 clip.'
        elif climax_fixed:
            detail_c = f'Đã hạ đỉnh cao trào toàn bài ({full_peak_db:+.2f} dBTP) về vùng sạch.'
        else:
            detail_c = 'Đã hạ đỉnh về vùng an toàn cho DAC.'
        p_clean = {
            'title': 'Độ trong trẻo',
            'verdict': 'Tốt hơn gốc',
            'detail': detail_c,
            'tone': 'good',
        }
    else:
        p_clean = {
            'title': 'Độ trong trẻo',
            'verdict': 'Sạch như gốc',
            'detail': 'Không phát sinh vỡ tiếng hay méo nền.',
            'tone': 'good',
        }

    if abs(dr_delta_db) <= 0.35:
        p_dyn = {
            'title': 'Độ nảy & Chi tiết',
            'verdict': 'Giữ nguyên 100%',
            'detail': 'Không nén động, giữ nguyên nhịp nảy gốc.',
            'tone': 'good',
        }
    elif dr_delta_db >= -1.2:
        p_dyn = {
            'title': 'Độ nảy & Chi tiết',
            'verdict': 'Tự nhiên',
            'detail': f'Biến thiên nhẹ {dr_delta_db:+.2f} dB theo đáp tuyến EQ.',
            'tone': 'neutral',
        }
    else:
        p_dyn = {
            'title': 'Độ nảy & Chi tiết',
            'verdict': 'Hụt độ nảy',
            'detail': f'Giảm {dr_delta_db:+.2f} dB độ động so với bản gốc.',
            'tone': 'warn',
        }

    if not profile.enabled or (tonal_rms_db <= 0.08 and float(lab.get('crosstalk_db', -140.0)) <= -45.0):
        p_tone = {
            'title': 'Màu âm & Không gian',
            'verdict': 'Nguyên bản 1:1',
            'detail': 'Không đổi chất giọng hay màu nhạc cụ gốc.',
            'tone': 'good',
        }
    elif tonal_rms_db <= 3.8:
        p_tone = {
            'title': 'Màu âm & Không gian',
            'verdict': 'Tinh chỉnh hài hòa',
            'detail': f'Nghe {tone_desc}.',
            'tone': 'good',
        }
    elif tonal_rms_db <= 6.5:
        p_tone = {
            'title': 'Màu âm & Không gian',
            'verdict': 'Đổi màu âm mạnh',
            'detail': f'Chỉnh đậm ({tone_desc}); hãy nghe thử A/B.',
            'tone': 'neutral',
        }
    else:
        p_tone = {
            'title': 'Màu âm & Không gian',
            'verdict': 'Kéo EQ quá tay',
            'detail': f'Lệch ±{tonal_rms_db:.1f} dB dễ làm biến dạng giọng hát.',
            'tone': 'warn',
        }

    if not profile.enabled:
        if orig_tp_db > -0.1 or orig_clips > 0:
            overall_tag = 'ĐANG PHÁT GỐC · CÓ VỠ ĐỈNH'
            overall_tone = 'warn'
            plain_conclusion = (
                f'Đang phát nguyên gốc chưa xử lý. File gốc có {orig_clips:,} điểm vượt ngưỡng dễ gây rè nhẹ khi mở to — '
                'nên bật Nguyên bản hoặc Dawn Pro 2 để làm sạch.'
            )
        elif climax_hot:
            overall_tag = 'ĐANG PHÁT GỐC · CAO TRÀO VƯỢT TRẦN'
            overall_tone = 'warn'
            plain_conclusion = (
                f'Đoạn trích hiện tại êm nhưng cao trào toàn bài vượt ngưỡng ({full_peak_db:+.2f} dBTP) dễ gây rè khi mở lớn — '
                'nên bật Nguyên bản hoặc Dawn Pro 2 để làm sạch.'
            )
        else:
            overall_tag = 'GIỮ NGUYÊN BẢN GỐC'
            overall_tone = 'neutral'
            plain_conclusion = 'Đang phát nguyên gốc 100%, không thay đổi âm lượng hay màu âm.'
    elif proc_tp_db > -0.05 or proc_clips > 0:
        overall_tag = 'KÉM HƠN GỐC · BỊ VỠ TIẾNG'
        overall_tone = 'warn'
        plain_conclusion = (
            f'Đang kém hơn bản gốc: Xuất hiện {proc_clips:,} điểm vỡ đỉnh sau xử lý gây rè méo tiếng. '
            'Hãy bật Tự giảm Preamp hoặc Cân bằng âm lượng.'
        )
    elif tonal_rms_db > 6.5:
        overall_tag = 'CHỈNH QUÁ ĐÀ · DỄ LỆCH TIẾNG'
        overall_tone = 'warn'
        plain_conclusion = (
            f'Đang kéo EQ quá mạnh (±{tonal_rms_db:.1f} dB) làm biến dạng màu âm gốc, dễ gây ù đục hoặc chói tai. '
            'Nên giảm các cần EQ về gần 0 dB.'
        )
    elif thdn_db > -90.0 or dr_delta_db < -1.2:
        overall_tag = 'CẦN ĐIỀU CHỈNH LẠI'
        overall_tone = 'warn'
        plain_conclusion = 'Độ động hoặc độ méo đang kém hơn bản gốc, nên chuyển về cấu hình khuyên dùng.'
    elif (orig_clips > 0 or orig_tp_db > -0.2 or climax_fixed) and proc_clips == 0 and proc_tp_db <= -0.8:
        if tonal_rms_db <= 0.08:
            overall_tag = 'SẠCH HƠN BẢN GỐC'
            overall_tone = 'good'
            if orig_clips > 0:
                plain_conclusion = (
                    f'Tốt hơn bản gốc về độ trong trẻo: Đã khử sạch {orig_clips:,} điểm vượt trần gây rè ở đoạn cao trào, '
                    'giữ nguyên 100% chất giọng & chi tiết gốc.'
                )
            elif climax_fixed:
                plain_conclusion = (
                    f'Tốt hơn bản gốc về độ trong trẻo: Đã hạ đỉnh cao trào toàn bài ({full_peak_db:+.2f} dBTP) về ngưỡng sạch chống rè, '
                    'giữ nguyên 100% chất giọng & chi tiết gốc.'
                )
            else:
                plain_conclusion = 'Sạch đỉnh hơn bản gốc: Đã tạo khoảng trống an toàn chống méo DAC, giữ nguyên 100% chất âm gốc.'
        else:
            overall_tag = 'SẠCH ĐỈNH HƠN · ĐÃ CHỈNH GU ÂM'
            overall_tone = 'good'
            clip_phrase = (
                f'khử {orig_clips:,} điểm vượt trần về 0'
                if orig_clips > 0
                else (f'hạ đỉnh cao trào {full_peak_db:+.2f} dBTP về vùng sạch' if climax_fixed else 'hạ đỉnh về ngưỡng sạch')
            )
            plain_conclusion = (
                f'Sạch hơn gốc ({clip_phrase}) kèm tinh chỉnh {tone_desc}. '
                'Bấm "Nghe thử A/B" bên dưới để tự kiểm chứng bằng tai.'
            )
    else:
        if tonal_rms_db <= 0.08:
            overall_tag = 'TRUNG THỰC NHƯ GỐC'
            overall_tone = 'good'
            plain_conclusion = (
                'Bản gốc vốn đã rất sạch; chế độ hiện tại giữ nguyên 100% chi tiết gốc và truyền thẳng ra DAC rời.'
                if profile.output_mode == 'exclusive'
                else 'Bản gốc vốn đã sạch; chế độ hiện tại giữ nguyên 100% âm sắc gốc và cân bằng âm lượng êm tai giữa các bài.'
            )
        else:
            overall_tag = 'SẠCH NHƯ GỐC · ĐỔI MÀU ÂM THEO GU'
            overall_tone = 'good'
            plain_conclusion = (
                f'Độ sạch ngang bản gốc (0 vỡ tiếng, giữ nguyên độ nảy), màu âm được chỉnh {tone_desc}. '
                'Hãy bấm "Nghe thử A/B" để xem hợp tai bạn hơn không.'
            )

    return {
        'overall_tag': overall_tag,
        'overall_tone': overall_tone,
        'plain_conclusion': plain_conclusion,
        'pillars': [p_clean, p_dyn, p_tone],
    }


def _build_comparison_and_verdict(
    profile: AudioProfile,
    source_info: dict,
    in_sr: int,
    out_sr: int,
    out_dtype: str,
    gain_db: float,
    orig_lufs: float | None,
    proc_lufs: float | None,
    orig_tp_db: float,
    orig_clips: int,
    proc_tp_db: float,
    proc_clips: int,
    orig_dr_db: float,
    proc_dr_db: float,
    dr_delta_db: float,
    stereo_corr_orig: float,
    stereo_corr_proc: float,
    tonal_rms_db: float,
    null_residual_db: float | None,
    lab: dict,
    forensics: dict,
    full_peak_db: float | None = None,
) -> tuple[list[dict], dict]:
    orig_lufs_s = f'{orig_lufs:.1f} LUFS' if isinstance(orig_lufs, (int, float)) else '—'
    proc_lufs_s = f'{proc_lufs:.1f} LUFS' if isinstance(proc_lufs, (int, float)) else '—'
    plr_o = round(orig_tp_db - orig_lufs, 1) if isinstance(orig_lufs, (int, float)) else None
    plr_p = round(proc_tp_db - proc_lufs, 1) if isinstance(proc_lufs, (int, float)) else None
    dr_o_s = f'PLR {plr_o:.1f} · DR {orig_dr_db:.1f} dB' if plr_o is not None else f'DR {orig_dr_db:.1f} dB'
    dr_p_s = f'PLR {plr_p:.1f} · DR {proc_dr_db:.1f} dB' if plr_p is not None else f'DR {proc_dr_db:.1f} dB'

    ref_bits = int(lab.get('ref_bit_depth') or 24)
    ref_noise_lbl = '< -96 dB (16-bit)' if ref_bits == 16 else '< -140 dB (24-bit)'

    tp_status = (
        'Quá ngưỡng (> 0 dBTP)' if (proc_tp_db > -0.05 or proc_clips > 0)
        else ('Đạt ≤ -1.0 dBTP' if proc_tp_db <= -1.0 else 'An toàn (< 0 dBTP)')
    )
    tp_tone = 'warn' if (proc_tp_db > -0.05 or proc_clips > 0) else 'good'

    # Standardized 8-row Pre vs Post table (identical units on both columns)
    lu_delta = (
        round(float(proc_lufs) - float(orig_lufs), 2)
        if isinstance(orig_lufs, (int, float)) and isinstance(proc_lufs, (int, float))
        else float(gain_db)
    )
    rows = [
        {
            'metric': 'Độ lớn tích hợp (BS.1770-4)',
            'orig': orig_lufs_s,
            'proc': proc_lufs_s,
            'status': 'Không đổi' if (not profile.enabled or abs(lu_delta) < 0.05) else f'{lu_delta:+.1f} LU',
            'tone': 'good' if profile.enabled else 'neutral',
        },
        {
            'metric': 'Đỉnh thực (4× True-Peak)',
            'orig': f'{orig_tp_db:+.2f} dBTP',
            'proc': f'{proc_tp_db:+.2f} dBTP',
            'status': tp_status,
            'tone': tp_tone,
        },
        {
            'metric': 'Mẫu vượt trần (ISP > 0 dBTP)',
            'orig': f'{orig_clips:,} mẫu',
            'proc': f'{proc_clips:,} mẫu',
            'status': 'Sạch clip' if proc_clips == 0 else f'Còn {proc_clips:,} mẫu',
            'tone': 'good' if proc_clips == 0 else 'warn',
        },
        {
            'metric': 'Tỷ lệ Đỉnh / Độ lớn (PLR · DR)',
            'orig': dr_o_s,
            'proc': dr_p_s,
            'status': f'Giữ nguyên ({dr_delta_db:+.2f} dB)' if abs(dr_delta_db) <= 0.25 else f'Δ {dr_delta_db:+.2f} dB',
            'tone': 'good' if abs(dr_delta_db) <= 0.25 else 'neutral',
        },
        {
            'metric': 'Đáp tuyến (20 Hz – 20 kHz)',
            'orig': '0.00 dB (Phẳng)',
            'proc': '0.00 dB (Phẳng)' if tonal_rms_db <= 0.08 else f'±{tonal_rms_db:.2f} dB',
            'status': 'Bit-Pure' if tonal_rms_db <= 0.08 else ('Biên độ lớn' if tonal_rms_db > 6.5 else 'Theo EQ'),
            'tone': 'good' if tonal_rms_db <= 0.08 else ('warn' if tonal_rms_db > 6.5 else 'neutral'),
        },
        {
            'metric': 'Tương quan pha Stereo (L/R)',
            'orig': f'{stereo_corr_orig:+.2f}',
            'proc': f'{stereo_corr_proc:+.2f}',
            'status': 'Crossfeed 30°' if lab['crosstalk_db'] > -45.0 else 'Giữ nguyên trường âm',
            'tone': 'neutral' if lab['crosstalk_db'] > -45.0 else 'good',
        },
        {
            'metric': 'Tách kênh Stereo (@ 1 kHz)',
            'orig': '< -140 dB',
            'proc': _fmt_db_floor(lab['crosstalk_db']),
            'status': f'Hòa kênh {lab["crosstalk_db"]:.1f} dB' if lab['crosstalk_db'] > -45.0 else 'Độc lập L/R',
            'tone': 'neutral' if lab['crosstalk_db'] > -45.0 else 'good',
        },
        {
            'metric': 'Méo hài & IMD chuỗi DSP',
            'orig': ref_noise_lbl,
            'proc': f'{_fmt_db_floor(lab["thdn_db"])} ({_fmt_pct_floor(lab["thdn_pct"])})',
            'status': 'Tuyến tính' if lab['thdn_db'] <= -110.0 else ('Đạt chuẩn' if lab['thdn_db'] <= -90.0 else 'Méo cao'),
            'tone': 'good' if lab['thdn_db'] <= -90.0 else 'warn',
        },
    ]

    listener_summary = _build_listener_summary(
        profile=profile,
        source_info=source_info,
        orig_tp_db=orig_tp_db,
        orig_clips=orig_clips,
        proc_tp_db=proc_tp_db,
        proc_clips=proc_clips,
        dr_delta_db=dr_delta_db,
        tonal_rms_db=tonal_rms_db,
        lab=lab,
        full_peak_db=full_peak_db,
        gain_db=gain_db,
    )

    findings = []
    if not profile.enabled:
        badge = 'NGUYÊN GỐC (BYPASS)'
        headline = 'Đầu ra đi thẳng 1:1 không qua chuỗi xử lý 64-bit.'
        climax_warn = bool(full_peak_db is not None and full_peak_db > 0.05)
        findings.append({
            'level': 'warn' if (orig_tp_db > -0.1 or orig_clips > 0 or climax_warn) else 'good',
            'title': 'Kiểm soát đỉnh phát',
            'detail': (
                f'Đỉnh gốc {orig_tp_db:+.2f} dBTP ({orig_clips:,} mẫu vượt 0 dBTP); nên bật Nguyên bản để giảm về ≤ -1.0 dBTP.'
                if (orig_tp_db > -0.1 or orig_clips > 0)
                else (
                    f'Đoạn trích {orig_tp_db:+.2f} dBTP, nhưng đỉnh toàn bài đạt {full_peak_db:+.2f} dBTP; nên bật Nguyên bản để bảo vệ cao trào.'
                    if climax_warn
                    else f'Đỉnh gốc {orig_tp_db:+.2f} dBTP nằm dưới trần 0 dBTP (0 mẫu clip).'
                )
            ),
        })
        findings.append({
            'level': 'neutral',
            'title': 'Độ động & Âm sắc',
            'detail': f'{orig_lufs_s} · {dr_o_s}. Tín hiệu giữ nguyên bản 100%, không can thiệp EQ.',
        })
        findings.append({
            'level': 'neutral',
            'title': 'Phổ nguồn file gốc',
            'detail': f'Băng thông đo thực {forensics["source_cutoff_hz"] / 1000.0:.1f} kHz · {in_sr / 1000.0:g} kHz gốc.',
        })
        return rows, {
            'badge': badge,
            'headline': headline,
            'findings': findings,
            'listener_summary': listener_summary,
        }

    # 1. Headroom & EBU R128 compliance
    if proc_tp_db > -0.05 or proc_clips > 0:
        findings.append({
            'level': 'warn',
            'title': 'Quá ngưỡng đỉnh DAC',
            'detail': f'Đỉnh {proc_tp_db:+.2f} dBTP ({proc_clips:,} mẫu clip). Bật Tự giảm Preamp hoặc Cân bằng âm lượng.',
        })
    elif orig_tp_db > -0.2 and proc_tp_db <= -0.8:
        findings.append({
            'level': 'good',
            'title': 'Chuẩn hóa đỉnh EBU R128',
            'detail': f'{orig_tp_db:+.2f} dBTP ({orig_clips:,} mẫu clip) → {proc_tp_db:+.2f} dBTP (0 clip, đạt trần ≤ -1.0 dBTP).',
        })
    else:
        findings.append({
            'level': 'good',
            'title': 'Dự phòng đỉnh DAC an toàn',
            'detail': f'{orig_lufs_s} → {proc_lufs_s} · đỉnh thực {proc_tp_db:+.2f} dBTP (0 mẫu clip).',
        })

    # 2. Micro-dynamics & Source Mastering compression check
    if plr_o is not None and plr_o < 8.0:
        findings.append({
            'level': 'neutral',
            'title': 'Độ động (PLR · Crest DR)',
            'detail': f'DSP giữ nguyên độ động ({dr_delta_db:+.2f} dB). Lưu ý: bản thu gốc nén sẵn khá chặt (PLR {plr_o:.1f} dB).',
        })
    else:
        findings.append({
            'level': 'good' if abs(dr_delta_db) <= 0.25 else 'neutral',
            'title': 'Độ động (PLR · Crest DR)',
            'detail': f'{dr_o_s} → {dr_p_s} (Δ {dr_delta_db:+.2f} dB, không nén động).',
        })

    # 3. Tonal Accuracy & Source Bandwidth
    cutoff_hz = int(forensics['source_cutoff_hz'])
    cutoff_khz = cutoff_hz / 1000.0
    bw_lbl = f'{cutoff_khz:.1f} kHz (Hi-Res)' if cutoff_hz >= 24000 else f'{cutoff_khz:.1f} kHz'
    noise_lbl = str(lab.get('noise_floor_label') or _fmt_noise_floor(lab['snr_db']))
    fmt_lbl = '32-bit Int' if out_dtype == 'int32' else '32-bit Float'

    if tonal_rms_db <= 0.08 and (null_residual_db is None or null_residual_db <= -120.0):
        null_s = f' · Null {null_residual_db:.1f} dBFS' if null_residual_db is not None else ''
        findings.append({
            'level': 'good',
            'title': 'Độ trung thực & Băng thông',
            'detail': f'Đáp tuyến 0.00 dB{null_s}, THD+N {_fmt_db_floor(lab["thdn_db"])}. Băng thông file {bw_lbl}.',
        })
    elif tonal_rms_db > 6.5:
        findings.append({
            'level': 'warn',
            'title': 'Độ lệch đáp tuyến lớn',
            'detail': (
                f'Lệch ±{tonal_rms_db:.2f} dB (Bass {lab["low_delta_db"]:+.1f} / Mid {lab["mid_delta_db"]:+.1f} '
                f'/ Treble {lab["high_delta_db"]:+.1f} dB); cân nhắc giảm bớt EQ.'
            ),
        })
    else:
        findings.append({
            'level': 'neutral',
            'title': 'Định hình EQ & Băng thông',
            'detail': (
                f'Bass {lab["low_delta_db"]:+.1f} · Mid {lab["mid_delta_db"]:+.1f} · Treble {lab["high_delta_db"]:+.1f} dB '
                f'(THD+N {_fmt_db_floor(lab["thdn_db"])}). Băng thông file {bw_lbl}.'
            ),
        })

    has_warn = any(f['level'] == 'warn' for f in findings)
    if has_warn:
        badge = 'CẦN LƯU Ý'
        headline = 'Có điểm cần điều chỉnh ở mức đỉnh hoặc biên độ EQ.'
    elif tonal_rms_db <= 0.08:
        badge = 'ĐẠT CHUẨN BIT-PURE'
        if profile.output_mode == 'exclusive' and not profile.normalize and profile.upsample == 'off':
            headline = f'Bit-Perfect Exclusive · Đáp tuyến 0.00 dB · Nền nhiễu {noise_lbl} · {fmt_lbl} {out_sr / 1000.0:g} kHz.'
        else:
            headline = f'Đáp tuyến phẳng 0.00 dB · Nền nhiễu {noise_lbl} · {fmt_lbl} {out_sr / 1000.0:g} kHz.'
    elif profile.output_mode == 'exclusive' or out_sr >= 88200:
        badge = 'CHUẨN HI-RES STUDIO'
        headline = f'Đầu ra DAC {fmt_lbl} {out_sr / 1000.0:g} kHz · Nền nhiễu {noise_lbl} · Đỉnh {proc_tp_db:+.2f} dBTP.'
    elif profile.youtube_loudness:
        badge = 'CHUẨN YOUTUBE (−14 LUFS)'
        headline = f'Khớp chuẩn phát YouTube · Nền nhiễu {noise_lbl} · Đỉnh {proc_tp_db:+.2f} dBTP.'
    else:
        badge = 'ĐẠT CHUẨN EBU R128'
        headline = f'Đạt trần phát sạch EBU R128 · Nền nhiễu {noise_lbl} · {out_sr / 1000.0:g} kHz.'

    return rows, {
        'badge': badge,
        'headline': headline,
        'findings': findings,
        'listener_summary': listener_summary,
    }


def _format_report_text(res: dict) -> str:
    noise_lbl = str(res.get('noise_floor_label') or _fmt_noise_floor(res.get('snr_db', 144.0)))
    ls = (res.get('verdict') or {}).get('listener_summary') or {}
    lines = [
        'BoTube Studio Audio Benchmark (ITU-R BS.1770-4 / EBU R128 / AES17)',
        f'File: {res["source_path"]}',
        f'Pipeline: {res["in_sr"]/1000:g} kHz -> {res["out_sr"]/1000:g} kHz ({res["out_dtype"]}), Gain {res["gain_db"]:+.2f} dB, Noise Floor {noise_lbl}',
        f'Verdict: {res["verdict"]["badge"]} — {res["verdict"]["headline"]}',
    ]
    if ls.get('overall_tag'):
        lines.append(f'Plain Verdict: {ls["overall_tag"]} — {ls.get("plain_conclusion", "")}')
    lines.append('')
    for r in res['comparison_rows']:
        lines.append(f'{r["metric"]}: Original=[{r["orig"]}] | Processed=[{r["proc"]}] => {r["status"]}')
    return '\n'.join(lines)


def run_audio_benchmark(
    source_path: str,
    profile: AudioProfile,
    target_lufs: int = DEFAULT_TARGET_LUFS,
    processes: OwnedProcesses | None = None,
    cancelled=None,
    cached_info: dict | None = None,
    cached_measurement: dict | None = None,
    max_excerpt_sec: float = 12.0,
) -> dict:
    """Measure objective Pre vs Post program metrics + APx/RMAA laboratory suite in RAM."""
    t0 = time.monotonic()
    proc = processes if processes is not None else OwnedProcesses()
    cancel_fn = cancelled if callable(cancelled) else (lambda: False)
    ffmpeg = find_tool('ffmpeg')

    info = dict(cached_info) if isinstance(cached_info, dict) else probe_audio_stream(source_path, 0, proc, cancel_fn)
    track = int(info.get('track', 0))
    in_sr = max(8000, int(info.get('sample_rate') or 48000))
    duration = max(0.0, float(info.get('duration') or 0.0))

    out_sr = _target_benchmark_sr(profile, in_sr)
    out_dtype = 'int32' if (profile.enabled and profile.output_mode == 'exclusive') else 'float32'
    excerpt_cap = 8.0 if out_sr >= 176400 else float(max_excerpt_sec)
    if duration > excerpt_cap + 4.0:
        start_sec = round(min(max(0.0, duration * 0.28), duration - excerpt_cap - 1.0), 2)
        dur_sec = excerpt_cap
    else:
        start_sec = 0.0
        dur_sec = min(excerpt_cap, max(0.5, duration)) if duration > 0 else excerpt_cap

    orig_f64 = _decode_f64_excerpt(
        ffmpeg, str(source_path), track, start_sec, dur_sec,
        'aformat=sample_fmts=dblp:channel_layouts=stereo',
        proc, cancel_fn,
    )
    orig_rms = float(np.sqrt(np.mean(orig_f64 ** 2))) if orig_f64.size else 1e-6
    if 20.0 * math.log10(max(1e-6, orig_rms)) < -42.0 and duration > 24.0:
        start_sec = round(min(max(0.0, duration * 0.52), duration - excerpt_cap - 1.0), 2)
        orig_f64 = _decode_f64_excerpt(
            ffmpeg, str(source_path), track, start_sec, dur_sec,
            'aformat=sample_fmts=dblp:channel_layouts=stereo',
            proc, cancel_fn,
        )

    if valid_measurement(cached_measurement):
        meas = dict(cached_measurement)
    else:
        meas = _measure_excerpt_loudness(ffmpeg, str(source_path), track, start_sec, duration, proc, cancel_fn)

    gain_db, peak_limited = resolve_profile_gain_db(profile, meas, int(target_lufs), source_info=info)

    if not profile.enabled:
        proc_f64 = orig_f64.copy()
        summary = {
            'restorer_active': 'Bypass',
            'tone': 'off',
            'custom_eq_active': False,
            'gain_db': 0.0,
            'resampled': False,
            'soxr_precision': 0,
            'upsample': 'off',
            'out_sample_rate': in_sr,
        }
        applied_gain = 0.0
    else:
        af, summary = build_realtime_filter_graph(profile, {**info, 'channels': 2}, gain_db, out_sr)
        proc_raw = _pipe_f64_filter(ffmpeg, orig_f64, in_sr, af, proc, cancel_fn)
        applied_gain = float(gain_db)
        proc_f64 = _quantize_and_reconstruct(proc_raw * (10.0 ** (applied_gain / 20.0)), out_dtype)

    orig_tp_db, orig_clips, orig_env_db = measure_true_peak_4x(orig_f64, slices=96)
    proc_tp_db, proc_clips, proc_env_db = measure_true_peak_4x(proc_f64, slices=96)

    orig_rms = float(np.sqrt(np.mean(orig_f64 ** 2))) if orig_f64.size else 1e-6
    proc_rms = float(np.sqrt(np.mean(proc_f64 ** 2))) if proc_f64.size else 1e-6
    orig_rms_db = round(20.0 * math.log10(max(1e-6, orig_rms)), 2)
    proc_rms_db = round(20.0 * math.log10(max(1e-6, proc_rms)), 2)
    orig_dr_db = _windowed_crest_dr(orig_f64, in_sr)
    proc_dr_db = _windowed_crest_dr(proc_f64, out_sr)
    dr_delta_db = round(proc_dr_db - orig_dr_db, 2)

    orig_spec_db = welch_log_spectrum_db(orig_f64, in_sr, BENCH_FREQS, smooth_oct=1.0 / 24.0)
    proc_spec_raw_db = welch_log_spectrum_db(proc_f64, out_sr, BENCH_FREQS, smooth_oct=1.0 / 24.0)

    spec_peak = max(orig_spec_db) if orig_spec_db else -60.0
    mid_diffs = [
        p - o
        for f, o, p in zip(BENCH_FREQS, orig_spec_db, proc_spec_raw_db)
        if 400.0 <= f <= 2500.0 and o >= spec_peak - 45.0
    ]
    mid_offset_db = round(float(np.median(mid_diffs)), 2) if mid_diffs else round(proc_rms_db - orig_rms_db, 2)
    proc_spec_matched_db = [round(p - mid_offset_db, 2) for p in proc_spec_raw_db]
    delta_spec_db = [round(m - o, 2) for m, o in zip(proc_spec_matched_db, orig_spec_db)]

    null_residual_db = None
    if out_sr == in_sr and len(orig_f64) == len(proc_f64) and len(orig_f64) > 0:
        inv_lin = 10.0 ** (-applied_gain / 20.0)
        res_rms = float(np.sqrt(np.mean((proc_f64 * inv_lin - orig_f64) ** 2)))
        null_residual_db = round(20.0 * math.log10(max(1e-18, res_rms)), 1)

    orig_lufs = meas.get('lufs')
    orig_lufs_r = round(float(orig_lufs), 2) if isinstance(orig_lufs, (int, float)) else None
    if isinstance(orig_lufs, (int, float)):
        if profile.enabled and profile.custom_eq_active and orig_f64.size > 0 and proc_f64.size > 0:
            k_orig_ex = compute_k_weighted_db(orig_f64, in_sr)
            k_proc_ex = compute_k_weighted_db(proc_f64, out_sr)
            if k_orig_ex > -68.0 and k_proc_ex > -68.0:
                proc_lufs_r = round(float(orig_lufs) + (k_proc_ex - k_orig_ex), 2)
            else:
                proc_lufs_r = round(float(orig_lufs) + applied_gain, 2)
        else:
            proc_lufs_r = round(float(orig_lufs) + applied_gain, 2)
    else:
        proc_lufs_r = None

    stereo_orig = _stereo_correlation(orig_f64)
    stereo_proc = _stereo_correlation(proc_f64)
    forensics = _analyze_source_forensics(orig_f64, in_sr)
    lab = run_lab_suite(profile, info, applied_gain, out_sr, out_dtype, proc, cancel_fn)

    raw_full_pk = meas.get('peak_db')
    full_peak_db = (
        round(float(raw_full_pk), 2)
        if isinstance(raw_full_pk, (int, float)) and not isinstance(raw_full_pk, bool) and math.isfinite(raw_full_pk)
        else None
    )
    comparison_rows, verdict = _build_comparison_and_verdict(
        profile=profile,
        source_info=info,
        in_sr=in_sr,
        out_sr=out_sr,
        out_dtype=out_dtype,
        gain_db=applied_gain,
        orig_lufs=orig_lufs_r,
        proc_lufs=proc_lufs_r,
        orig_tp_db=orig_tp_db,
        orig_clips=orig_clips,
        proc_tp_db=proc_tp_db,
        proc_clips=proc_clips,
        orig_dr_db=orig_dr_db,
        proc_dr_db=proc_dr_db,
        dr_delta_db=dr_delta_db,
        stereo_corr_orig=stereo_orig,
        stereo_corr_proc=stereo_proc,
        tonal_rms_db=lab['tonal_rms_db'],
        null_residual_db=null_residual_db,
        lab=lab,
        forensics=forensics,
        full_peak_db=full_peak_db,
    )

    result = {
        'source_path': str(source_path),
        'source_info': info,
        'measurement': meas,
        'profile_enabled': bool(profile.enabled),
        'window_start_sec': start_sec,
        'window_dur_sec': round(len(orig_f64) / float(in_sr), 2) if orig_f64.size else 0.0,
        'in_sr': in_sr,
        'out_sr': out_sr,
        'out_dtype': out_dtype,
        'gain_db': round(applied_gain, 2),
        'exact_gain_db': float(applied_gain),
        'peak_limited': bool(peak_limited),
        'filter_summary': summary,
        'orig_lufs': orig_lufs_r,
        'proc_lufs': proc_lufs_r,
        'orig_tp_db': orig_tp_db,
        'orig_clips': orig_clips,
        'proc_tp_db': proc_tp_db,
        'proc_clips': proc_clips,
        'orig_rms_db': orig_rms_db,
        'proc_rms_db': proc_rms_db,
        'orig_dr_db': orig_dr_db,
        'proc_dr_db': proc_dr_db,
        'dr_delta_db': dr_delta_db,
        'stereo_corr_orig': stereo_orig,
        'stereo_corr_proc': stereo_proc,
        'freqs_hz': list(BENCH_FREQS),
        'orig_spec_db': orig_spec_db,
        'proc_spec_raw_db': proc_spec_raw_db,
        'proc_spec_matched_db': proc_spec_matched_db,
        'delta_spec_db': delta_spec_db,
        'mid_offset_db': mid_offset_db,
        'null_residual_db': null_residual_db,
        'orig_env_db': orig_env_db,
        'proc_env_db': proc_env_db,
        'comparison_rows': comparison_rows,
        'verdict': verdict,
        'elapsed_ms': int(round((time.monotonic() - t0) * 1000.0)),
        **forensics,
        **lab,
    }
    result['report_text'] = _format_report_text(result)
    return result


def render_audition_pair(
    source_path: str,
    profile: AudioProfile,
    source_info: dict | None,
    gain_db: float,
    start_sec: float,
    dur_sec: float,
    play_sr: int = 48000,
    processes: OwnedProcesses | None = None,
    cancelled=None,
) -> dict:
    """Render sample-aligned RAM Original vs Processed audition buffers with BS.1770-4 Gain Match."""
    proc = processes if processes is not None else OwnedProcesses()
    cancel_fn = cancelled if callable(cancelled) else (lambda: False)
    ffmpeg = find_tool('ffmpeg')
    info = dict(source_info) if isinstance(source_info, dict) else probe_audio_stream(source_path, 0, proc, cancel_fn)
    track = int(info.get('track', 0))
    in_sr = max(8000, int(info.get('sample_rate') or play_sr))
    sr = max(8000, int(play_sr or 48000))

    raw_orig = _decode_f64_excerpt(
        ffmpeg, str(source_path), track, start_sec, dur_sec,
        'aformat=sample_fmts=dblp:channel_layouts=stereo',
        proc, cancel_fn,
    )
    if in_sr != sr:
        orig_f64 = _pipe_f64_filter(
            ffmpeg, raw_orig, in_sr, f'aresample={sr}:resampler=soxr:precision=28:dither_method=0', proc, cancel_fn
        )
    else:
        orig_f64 = raw_orig

    if not profile.enabled:
        proc_f64 = orig_f64.copy()
    else:
        dsp_sr = _target_benchmark_sr(profile, in_sr)
        af, _ = build_realtime_filter_graph(profile, {**info, 'channels': 2}, gain_db, dsp_sr)
        if dsp_sr != sr:
            af += f',aresample={sr}:resampler=soxr:precision=28:dither_method=0'
        raw_p = _pipe_f64_filter(ffmpeg, raw_orig, in_sr, af, proc, cancel_fn)
        proc_f64 = raw_p * (10.0 ** (float(gain_db) / 20.0))

    n = min(len(orig_f64), len(proc_f64))
    if n <= 0:
        return {
            'sample_rate': sr,
            'orig_f32': np.zeros((0, 2), dtype=np.float32),
            'proc_f32': np.zeros((0, 2), dtype=np.float32),
            'match_orig_lin': 1.0,
            'match_proc_lin': 1.0,
            'matched_lufs': -70.0,
            'delta_loudness_db': 0.0,
        }

    orig_f64 = orig_f64[:n].copy()
    proc_f64 = proc_f64[:n].copy()

    # Smooth 15 ms loop fade-in and 25 ms fade-out at boundaries (zero click)
    fade_in = min(n // 4, max(4, int(round(0.015 * sr))))
    fade_out = min(n // 4, max(4, int(round(0.025 * sr))))
    if fade_in > 1:
        w_in = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0.0, 1.0, fade_in, dtype=np.float64)))[:, None]
        orig_f64[:fade_in] *= w_in
        proc_f64[:fade_in] *= w_in
    if fade_out > 1:
        w_out = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0.0, 1.0, fade_out, dtype=np.float64)))[:, None]
        orig_f64[-fade_out:] *= w_out
        proc_f64[-fade_out:] *= w_out

    k_orig = compute_k_weighted_db(orig_f64, sr)
    k_proc = compute_k_weighted_db(proc_f64, sr)
    ref_k = min(k_orig, k_proc)
    g_orig = 10.0 ** ((ref_k - k_orig) / 20.0)
    g_proc = 10.0 ** ((ref_k - k_proc) / 20.0)

    pk = max(
        float(np.max(np.abs(orig_f64))) * g_orig,
        float(np.max(np.abs(proc_f64))) * g_proc,
        1e-6,
    )
    if pk > 0.96:
        scale_safe = 0.96 / pk
        g_orig *= scale_safe
        g_proc *= scale_safe
        ref_k += 20.0 * math.log10(scale_safe)

    return {
        'sample_rate': sr,
        'orig_f32': orig_f64.astype('<f4'),
        'proc_f32': proc_f64.astype('<f4'),
        'match_orig_lin': float(g_orig),
        'match_proc_lin': float(g_proc),
        'matched_lufs': round(ref_k, 1),
        'delta_loudness_db': round(k_proc - k_orig, 1),
    }
