"""Studio 64-bit float DSP policies, loudness targets, 10-band EQ, and DAC protection; no Qt dependencies."""
import cmath
from dataclasses import dataclass, replace
import math
import re

PROCESSOR_VERSION = 1
SCHEMA_VERSION = 6
TARGET_LUFS = -18.0
DEFAULT_TARGET_LUFS = -16
VALID_TARGETS = (-16, -14, -18)
PEAK_CEILING_DB = -1.7  # Legacy v1 constant preserved for compatibility.
CS43198_CEILING_DB = -1.0
CS43198_EXCLUSIVE_CEILING_DB = -1.2
CS43198_LIMIT_LINEAR = round(10 ** (CS43198_CEILING_DB / 20.0), 6)  # 0.891251
MAX_BOOST_DB = 12.0

OUTPUT_MODES = ('shared', 'exclusive')
RESTORER_MODES = ('off', 'auto', 'natural', 'vivid')
UPSAMPLE_MODES = ('off', 'hires_sync', 'max_dac')
DAC_PHASES = ('linear', 'minimum')
PEQ_KINDS = ('PK', 'LS', 'HS')
MAX_PEQ_FILTERS = 16
PRESET_ORDER = ('studio_dawn_aria2', 'dac_bitperfect', 'youtube', 'bit_pure', 'walkman_vivid', 'bypass')

EQ_FREQS = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
EQ_LABELS = ('31', '62', '125', '250', '500', '1k', '2k', '4k', '8k', '16k')
FLAT_EQ_BANDS = (0.0,) * 10

PEQ_CURVES = {
    'aria2_squiglink': (
        'Aria 2 · Reference PEQ',
        -1.8,
        (
            ('LS', 95.0, 1.8, 0.707),
            ('PK', 210.0, -0.9, 1.3),
            ('PK', 1450.0, 0.6, 1.6),
            ('PK', 3350.0, -1.6, 2.4),
            ('PK', 7950.0, -2.2, 4.2),
            ('HS', 12800.0, 1.5, 0.707),
        ),
    ),
    'iem_de_ess_peq': (
        'Khử chói Sibilance (PEQ)',
        0.0,
        (
            ('PK', 6400.0, -2.8, 3.8),
            ('PK', 8300.0, -2.2, 4.5),
            ('HS', 13500.0, 1.0, 0.707),
        ),
    ),
}

EQ_CURVES = {
    'flat': ('Phẳng', (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
    'aria2_harman': ('Aria 2 · Harman', (2.5, 1.8, 0.3, -0.8, -0.3, 0.0, 0.4, -1.4, -1.0, 1.5)),
    'aria2_vocal': ('Aria 2 · Vocal', (1.2, 0.8, -0.5, -1.0, 0.2, 0.8, 1.2, -1.2, -0.8, 1.2)),
    'bass_boost': ('Tăng trầm', (5.5, 4.5, 2.5, 0.5, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0)),
    'bass_cut': ('Giảm trầm', (-5.0, -4.0, -2.0, -0.5, 0.0, 0.5, 0.8, 0.5, 0.0, 0.0)),
    'v_shape': ('V-Shape', (4.2, 3.5, 1.0, -1.0, -1.5, -0.5, 1.2, 2.5, 3.2, 3.8)),
    'vocal_studio': ('Vocal & Acoustic', (-1.5, -1.0, -0.5, 0.5, 1.8, 2.5, 2.2, 1.0, 0.5, 0.8)),
    'rock': ('Rock', (4.0, 3.2, 1.2, -0.8, -1.2, 0.5, 2.2, 3.0, 3.2, 3.0)),
    'pop': ('Pop', (2.0, 2.5, 1.2, 0.0, -0.6, 0.5, 1.5, 1.8, 1.8, 2.0)),
    'jazz_classical': ('Jazz & Cổ điển', (2.2, 1.6, 0.6, 0.0, -0.4, -0.2, 0.5, 1.2, 1.8, 2.2)),
    'lofi_warm': ('Ấm áp', (2.5, 2.8, 1.8, 0.8, 0.2, -0.3, -1.0, -1.8, -2.2, -2.5)),
    'treble_sparkle': ('Tăng sáng', (0.0, 0.0, 0.0, -0.3, 0.0, 0.4, 1.2, 2.2, 3.2, 4.0)),
}


def normalize_eq_bands(raw) -> tuple[float, ...]:
    """Validate and clamp a 10-band EQ array to [-12.0, 12.0] dB."""
    if not isinstance(raw, (list, tuple)) or len(raw) != len(EQ_FREQS):
        return FLAT_EQ_BANDS
    cleaned = []
    for item in raw:
        try:
            val = float(item)
            if not math.isfinite(val):
                return FLAT_EQ_BANDS
            cleaned.append(round(max(-12.0, min(12.0, val)), 2))
        except (TypeError, ValueError):
            return FLAT_EQ_BANDS
    return tuple(cleaned)


def normalize_peq_filters(raw) -> tuple[tuple[str, float, float, float], ...]:
    """Validate & return an immutable tuple of (kind, freq_hz, gain_db, q) parametric EQ filters."""
    if not isinstance(raw, (list, tuple)):
        return ()
    cleaned = []
    kind_map = {
        'PK': 'PK', 'PEQ': 'PK', 'PEAKING': 'PK',
        'LS': 'LS', 'LSC': 'LS', 'LOWSHELF': 'LS',
        'HS': 'HS', 'HSC': 'HS', 'HIGHSHELF': 'HS',
    }
    for item in raw[:MAX_PEQ_FILTERS]:
        try:
            if isinstance(item, dict):
                raw_k = item.get('kind', 'PK')
                raw_f = item.get('freq', 1000.0)
                raw_g = item.get('gain', 0.0)
                raw_q = item.get('q', 1.414)
            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                raw_k, raw_f, raw_g, raw_q = item[0], item[1], item[2], item[3]
            else:
                continue
            kind = kind_map.get(str(raw_k or 'PK').strip().upper())
            if kind is None:
                continue
            freq_hz = float(raw_f)
            gain_db = float(raw_g)
            q_val = float(raw_q)
            if not (math.isfinite(freq_hz) and math.isfinite(gain_db) and math.isfinite(q_val)):
                continue
            cleaned.append((
                kind,
                round(max(10.0, min(24000.0, freq_hz)), 1),
                round(max(-15.0, min(15.0, gain_db)), 2),
                round(max(0.1, min(18.0, q_val)), 3),
            ))
        except (TypeError, ValueError):
            continue
    return tuple(cleaned)

LOSSLESS_CODECS = frozenset({
    'flac', 'alac', 'wavpack', 'ape', 'tak', 'tta',
    'pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'pcm_f32le', 'pcm_f64le',
    'pcm_s16be', 'pcm_s24be', 'pcm_s32be', 'pcm_u8',
    'dsd_lsbf', 'dsd_msbf', 'dsd_lsbf_planar', 'dsd_msbf_planar',
})

TONES = {
    'off': '',
    # Dawn Pro 2 + Aria 2 Lab Reference + 30-degree Studio Monitor Room (1 kHz ~ 0.0 dB).
    'studio_aria2': 'equalizer=f=38:t=q:w=0.707:g=1.6:r=f64,'
                    'equalizer=f=205:t=q:w=1.2:g=-0.8:r=f64,'
                    'equalizer=f=3350:t=q:w=1.5:g=-1.2:r=f64,'
                    'equalizer=f=7800:t=q:w=3.0:g=-1.0:r=f64,'
                    'treble=f=13500:t=q:w=0.707:g=1.2:r=f64',
    # Pure 30-degree nearfield studio monitor crossfeed (0 dB tonal alteration).
    'studio_room': '',
    # Sony Walkman / Poweramp vivid contour (0 dB unity around 1 kHz).
    'walkman_vivid': 'equalizer=f=55:t=q:w=0.75:g=2.0:r=f64,'
                     'equalizer=f=230:t=q:w=1.2:g=-0.9:r=f64,'
                     'equalizer=f=2750:t=q:w=1.3:g=0.8:r=f64,'
                     'equalizer=f=7600:t=q:w=2.8:g=-0.9:r=f64,'
                     'treble=f=13000:t=q:w=0.707:g=1.7:r=f64',
    # Optional gentle Moondrop Aria 2 polish (no highpass phase rotation, 1 kHz = 0.0 dB).
    'aria2': 'equalizer=f=52:t=q:w=0.75:g=1.4:r=f64,'
             'equalizer=f=220:t=q:w=1.2:g=-0.6:r=f64,'
             'equalizer=f=2900:t=q:w=1.3:g=0.4:r=f64,'
             'equalizer=f=8000:t=q:w=3.0:g=-1.0:r=f64,'
             'treble=f=13000:t=q:w=0.707:g=1.1:r=f64',
    'vocal_clear': 'equalizer=f=190:t=q:w=1.1:g=-0.9:r=f64,'
                   'equalizer=f=2850:t=q:w=1.1:g=1.1:r=f64,'
                   'equalizer=f=7800:t=q:w=2.5:g=-0.8:r=f64,'
                   'treble=f=12500:t=q:w=0.707:g=1.2:r=f64',
    'gentle': 'equalizer=f=3200:t=q:w=0.8:g=-2.5:r=f64,treble=f=8000:g=-1.5:r=f64',
    'balanced': 'equalizer=f=3500:t=q:w=1:g=-1.2:r=f64,treble=f=10000:g=-0.7:r=f64',
    'warm': 'equalizer=f=280:t=q:w=0.7:g=-0.7:r=f64,'
            'equalizer=f=3200:t=q:w=0.8:g=-1.5:r=f64,treble=f=8500:g=-0.8:r=f64',
    'headphones': 'equalizer=f=280:t=q:w=0.7:g=-0.7:r=f64,'
                  'equalizer=f=3200:t=q:w=0.8:g=-1.5:r=f64,treble=f=8500:g=-0.8:r=f64',
    'easy': 'bass=f=100:t=q:w=0.707:g=1.5:r=f64,'
            'equalizer=f=3500:t=q:w=0.8:g=-1:r=f64,'
            'equalizer=f=7000:t=q:w=1:g=-1.5:r=f64,treble=f=10000:t=q:w=0.707:g=-1:r=f64',
    'easy_headphones': 'bass=f=100:t=q:w=0.707:g=1.5:r=f64,'
                       'equalizer=f=3500:t=q:w=0.8:g=-1:r=f64,'
                       'equalizer=f=7000:t=q:w=1:g=-1.5:r=f64,treble=f=10000:t=q:w=0.707:g=-1:r=f64',
}

TONE_PREAMP_DB = {
    'easy': -1.5,
    'easy_headphones': -1.5,
}

TONE_PEAK_PAD_DB = {
    'aria2': 1.4,
    'studio_aria2': 1.6,
    'walkman_vivid': 2.0,
    'vocal_clear': 1.2,
}


@dataclass(frozen=True)
class AudioProfile:
    normalize: bool = False
    tone: str = 'off'
    restorer: str = 'off'
    output_mode: str = 'shared'
    upsample: str = 'off'
    youtube_loudness: bool = False
    eq_enabled: bool = False
    eq_bands: tuple[float, ...] = FLAT_EQ_BANDS
    eq_preamp_db: float = 0.0
    eq_auto_preamp: bool = True
    eq_bass_db: float = 0.0
    eq_treble_db: float = 0.0
    eq_crossfeed: int = 0
    output_device: str = ''
    eq_peq_filters: tuple[tuple[str, float, float, float], ...] = ()
    dac_phase: str = 'linear'

    @property
    def enabled(self):
        return (
            self.normalize
            or self.youtube_loudness
            or self.tone != 'off'
            or self.restorer != 'off'
            or self.output_mode == 'exclusive'
            or self.upsample != 'off'
            or self.eq_enabled
            or bool(self.output_device)
        )

    @property
    def custom_eq_active(self) -> bool:
        return bool(
            self.eq_enabled
            and (
                any(abs(f[2]) >= 0.05 for f in self.eq_peq_filters)
                or (not self.eq_peq_filters and any(abs(g) >= 0.05 for g in self.eq_bands))
                or abs(self.eq_preamp_db) >= 0.05
                or abs(self.eq_bass_db) >= 0.05
                or abs(self.eq_treble_db) >= 0.05
                or self.eq_crossfeed > 0
            )
        )

    @classmethod
    def recommended(cls):
        """100% uncolored bit-pure tonal path + EBU R128 mastering loudness & intersample de-clip headroom."""
        return cls(normalize=True, tone='off', restorer='off', output_mode='shared')

    @classmethod
    def preset_profile(cls, preset_key: str) -> tuple['AudioProfile', int | None]:
        return preset_profile(preset_key)

    @classmethod
    def detect_preset(cls, profile: 'AudioProfile', target_lufs: int = -16) -> str:
        return detect_preset(profile, target_lufs)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        tone = data.get('tone', 'off')
        restorer = data.get('restorer', 'off')
        output_mode = data.get('output_mode', 'shared')
        upsample = data.get('upsample', 'off')
        youtube_loudness = data.get('youtube_loudness') is True
        normalize = False if youtube_loudness else (data.get('normalize') is True)
        eq_enabled = data.get('eq_enabled') is True
        eq_bands = normalize_eq_bands(data.get('eq_bands'))
        eq_peq_filters = normalize_peq_filters(data.get('eq_peq_filters'))
        dac_phase = 'minimum' if data.get('dac_phase') == 'minimum' else 'linear'

        def _clamp_float(key, default, lo, hi):
            try:
                v = float(data.get(key, default))
                return round(max(lo, min(hi, v)), 2) if math.isfinite(v) else float(default)
            except (TypeError, ValueError):
                return float(default)

        try:
            crossfeed_raw = data.get('eq_crossfeed', 0)
            eq_crossfeed = max(0, min(100, int(round(float(crossfeed_raw)))))
        except (TypeError, ValueError):
            eq_crossfeed = 0

        output_device = str(data.get('output_device') or '').strip()[:160]

        return cls(
            normalize=normalize,
            tone=tone if isinstance(tone, str) and tone in TONES else 'off',
            restorer=restorer if isinstance(restorer, str) and restorer in RESTORER_MODES else 'off',
            output_mode=output_mode if isinstance(output_mode, str) and output_mode in OUTPUT_MODES else 'shared',
            upsample=upsample if isinstance(upsample, str) and upsample in UPSAMPLE_MODES else 'off',
            youtube_loudness=youtube_loudness,
            eq_enabled=eq_enabled,
            eq_bands=eq_bands,
            eq_preamp_db=_clamp_float('eq_preamp_db', 0.0, -12.0, 12.0),
            eq_auto_preamp=False if data.get('eq_auto_preamp') is False else True,
            eq_bass_db=_clamp_float('eq_bass_db', 0.0, -6.0, 8.0),
            eq_treble_db=_clamp_float('eq_treble_db', 0.0, -6.0, 8.0),
            eq_crossfeed=eq_crossfeed,
            output_device=output_device,
            eq_peq_filters=eq_peq_filters,
            dac_phase=dac_phase,
        )

    def as_dict(self):
        return {
            'normalize': self.normalize,
            'tone': self.tone,
            'restorer': self.restorer,
            'output_mode': self.output_mode,
            'upsample': self.upsample,
            'youtube_loudness': self.youtube_loudness,
            'eq_enabled': self.eq_enabled,
            'eq_bands': list(self.eq_bands),
            'eq_preamp_db': self.eq_preamp_db,
            'eq_auto_preamp': self.eq_auto_preamp,
            'eq_bass_db': self.eq_bass_db,
            'eq_treble_db': self.eq_treble_db,
            'eq_crossfeed': self.eq_crossfeed,
            'output_device': self.output_device,
            'eq_peq_filters': [list(f) for f in self.eq_peq_filters],
            'dac_phase': self.dac_phase,
        }


def detect_eq_curve(eq_bands: tuple[float, ...] | list[float]) -> str:
    """Identify matching built-in EQ curve key or 'custom'."""
    norm = normalize_eq_bands(eq_bands)
    for key, (_, target) in EQ_CURVES.items():
        if all(abs(a - b) < 0.05 for a, b in zip(norm, target)):
            return key
    return 'custom'


def _rbj_coeffs(
    f0: float,
    q: float,
    gain_db: float,
    sr: float,
    kind: str = 'peaking',
) -> tuple[float, float, float, float, float, float]:
    """Compute normalized 64-bit RBJ Audio EQ Cookbook biquad coefficients."""
    fc = max(1.0, min(float(f0), float(sr) * 0.44))
    w0 = 2.0 * math.pi * fc / float(sr)
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    a_amp = 10.0 ** (float(gain_db) / 40.0)
    alpha = sin_w0 / (2.0 * max(0.1, float(q)))
    k_norm = kind.strip().lower()

    if k_norm in ('ls', 'lowshelf'):
        two_sqrt_a_alpha = 2.0 * math.sqrt(a_amp) * alpha
        b0 = a_amp * ((a_amp + 1.0) - (a_amp - 1.0) * cos_w0 + two_sqrt_a_alpha)
        b1 = 2.0 * a_amp * ((a_amp - 1.0) - (a_amp + 1.0) * cos_w0)
        b2 = a_amp * ((a_amp + 1.0) - (a_amp - 1.0) * cos_w0 - two_sqrt_a_alpha)
        a0 = (a_amp + 1.0) + (a_amp - 1.0) * cos_w0 + two_sqrt_a_alpha
        a1 = -2.0 * ((a_amp - 1.0) + (a_amp + 1.0) * cos_w0)
        a2 = (a_amp + 1.0) + (a_amp - 1.0) * cos_w0 - two_sqrt_a_alpha
    elif k_norm in ('hs', 'highshelf'):
        two_sqrt_a_alpha = 2.0 * math.sqrt(a_amp) * alpha
        b0 = a_amp * ((a_amp + 1.0) + (a_amp - 1.0) * cos_w0 + two_sqrt_a_alpha)
        b1 = -2.0 * a_amp * ((a_amp - 1.0) + (a_amp + 1.0) * cos_w0)
        b2 = a_amp * ((a_amp + 1.0) + (a_amp - 1.0) * cos_w0 - two_sqrt_a_alpha)
        a0 = (a_amp + 1.0) - (a_amp - 1.0) * cos_w0 + two_sqrt_a_alpha
        a1 = 2.0 * ((a_amp - 1.0) - (a_amp + 1.0) * cos_w0)
        a2 = (a_amp + 1.0) - (a_amp - 1.0) * cos_w0 - two_sqrt_a_alpha
    else:
        b0 = 1.0 + alpha * a_amp
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * a_amp
        a0 = 1.0 + alpha / a_amp
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / a_amp

    inv_a0 = 1.0 / a0
    return (b0 * inv_a0, b1 * inv_a0, b2 * inv_a0, 1.0, a1 * inv_a0, a2 * inv_a0)


def _rbj_biquad_stage(f0: float, q: float, gain_db: float, sr: float, kind: str = 'peaking') -> str:
    """Return 64-bit FFmpeg filter stage matching exact RBJ Cookbook / Equalizer APO biquad."""
    cap = max(1000.0, float(sr) * 0.44)
    fc = max(10.0, min(float(f0), cap))
    k_norm = kind.strip().lower()
    if k_norm in ('ls', 'lowshelf', 'hs', 'highshelf'):
        b0, b1, b2, _a0, a1, a2 = _rbj_coeffs(fc, q, gain_db, sr, kind=k_norm)
        return f'biquad=b0={b0:.12g}:b1={b1:.12g}:b2={b2:.12g}:a0=1:a1={a1:.12g}:a2={a2:.12g}:r=f64'
    return f'equalizer=f={fc:.2f}:t=q:w={max(0.1, float(q)):.4g}:g={float(gain_db):.2f}:r=f64'


def _rbj_magnitude_db(
    freqs_hz: list[float],
    f0: float,
    q: float,
    gain_db: float,
    sr: float,
    kind: str = 'peaking',
) -> list[float]:
    if abs(gain_db) < 1e-4 or sr <= 0:
        return [0.0] * len(freqs_hz)
    b0, b1, b2, a0, a1, a2 = _rbj_coeffs(f0, q, gain_db, sr, kind=kind)
    out = []
    for f in freqs_hz:
        w = 2.0 * math.pi * float(f) / sr
        z1 = cmath.exp(-1j * w)
        z2 = z1 * z1
        h = (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)
        out.append(20.0 * math.log10(max(1e-12, abs(h))))
    return out


def evaluate_eq_response_db(
    profile: AudioProfile,
    freqs_hz,
    sample_rate: float = 48000.0,
    include_preamp: bool = False,
    force_preview: bool = False,
) -> list[float]:
    """Compute exact 64-bit RBJ biquad magnitude curve (dB) at the supplied frequencies."""
    freqs = [float(f) for f in freqs_hz]
    if not freqs:
        return []
    total = [0.0] * len(freqs)
    if not getattr(profile, 'eq_enabled', False) and not force_preview:
        return total

    sr = max(8000.0, float(sample_rate or 48000.0))
    bass_db = float(getattr(profile, 'eq_bass_db', 0.0) or 0.0)
    if abs(bass_db) >= 0.05:
        for i, v in enumerate(_rbj_magnitude_db(freqs, 55.0, 0.707, bass_db, sr, 'lowshelf')):
            total[i] += v

    peq = normalize_peq_filters(getattr(profile, 'eq_peq_filters', ()))
    if peq:
        for kind, freq_hz, gain_db, q_val in peq:
            if abs(gain_db) >= 0.05:
                k_rbj = 'lowshelf' if kind == 'LS' else ('highshelf' if kind == 'HS' else 'peaking')
                for i, v in enumerate(_rbj_magnitude_db(freqs, freq_hz, q_val, gain_db, sr, k_rbj)):
                    total[i] += v
    else:
        bands = normalize_eq_bands(getattr(profile, 'eq_bands', FLAT_EQ_BANDS))
        for freq, gain_db in zip(EQ_FREQS, bands):
            if abs(gain_db) >= 0.05:
                for i, v in enumerate(_rbj_magnitude_db(freqs, float(freq), 1.414, gain_db, sr, 'peaking')):
                    total[i] += v

    treble_db = float(getattr(profile, 'eq_treble_db', 0.0) or 0.0)
    if abs(treble_db) >= 0.05:
        for i, v in enumerate(_rbj_magnitude_db(freqs, 12500.0, 0.707, treble_db, sr, 'highshelf')):
            total[i] += v

    if include_preamp:
        preamp = effective_eq_preamp_db(profile, sr, force_preview=force_preview)
        total = [v + preamp for v in total]
    return total


def custom_eq_peak_boost_db(
    profile: AudioProfile,
    sample_rate: float = 48000.0,
    force_preview: bool = False,
) -> float:
    """Return max positive boost (dB >= 0) of the combined PEQ / 10-band + Bass/Treble EQ curve."""
    if not getattr(profile, 'eq_enabled', False) and not force_preview:
        return 0.0
    log_min = math.log10(20.0)
    log_max = math.log10(20000.0)
    freqs = [10.0 ** (log_min + (log_max - log_min) * (i / 159.0)) for i in range(160)]
    for _, f_hz, _, _ in normalize_peq_filters(getattr(profile, 'eq_peq_filters', ())):
        if 20.0 <= f_hz <= 20000.0:
            freqs.append(float(f_hz))
    vals = evaluate_eq_response_db(profile, freqs, sample_rate=sample_rate, include_preamp=False, force_preview=force_preview)
    return round(max(0.0, max(vals) if vals else 0.0), 2)


def effective_eq_preamp_db(
    profile: AudioProfile,
    sample_rate: float = 48000.0,
    force_preview: bool = False,
) -> float:
    """Compute protective preamp offset (dB) for custom EQ."""
    if not getattr(profile, 'eq_enabled', False) and not force_preview:
        return 0.0
    user_preamp = float(getattr(profile, 'eq_preamp_db', 0.0) or 0.0)
    if getattr(profile, 'eq_auto_preamp', True):
        peak_boost = custom_eq_peak_boost_db(profile, sample_rate=sample_rate, force_preview=force_preview)
        return round(-peak_boost + min(0.0, user_preamp), 2)
    return round(user_preamp, 2)


def export_apo_text(profile: AudioProfile) -> str:
    """Export current Parametric PEQ or GraphicEQ settings in Equalizer APO text format."""
    preamp = float(getattr(profile, 'eq_preamp_db', 0.0) or 0.0)
    peq = normalize_peq_filters(getattr(profile, 'eq_peq_filters', ()))
    if peq:
        type_map = {'PK': 'PK', 'LS': 'LSC', 'HS': 'HSC'}
        lines = [f'Preamp: {preamp:+.1f} dB']
        for idx, (kind, freq_hz, gain_db, q_val) in enumerate(peq, start=1):
            apo_t = type_map.get(kind, 'PK')
            f_str = f'{int(round(freq_hz))}' if abs(freq_hz - round(freq_hz)) < 0.05 else f'{freq_hz:.1f}'
            lines.append(f'Filter {idx}: ON {apo_t} Fc {f_str} Hz Gain {gain_db:+.2f} dB Q {q_val:.3f}')
        return '\n'.join(lines)
    bands = normalize_eq_bands(getattr(profile, 'eq_bands', FLAT_EQ_BANDS))
    pairs = '; '.join(f'{f} {g:.1f}' for f, g in zip(EQ_FREQS, bands))
    return f'Preamp: {preamp:+.1f} dB\nGraphicEQ: {pairs}'


def _log_interp_points(points: list[tuple[float, float]]) -> tuple[float, ...]:
    pts = sorted(points, key=lambda p: p[0])
    xs = [math.log10(max(1.0, p[0])) for p in pts]
    ys = [p[1] for p in pts]
    out = []
    for freq in EQ_FREQS:
        tx = math.log10(float(freq))
        if tx <= xs[0]:
            g = ys[0]
        elif tx >= xs[-1]:
            g = ys[-1]
        else:
            g = ys[-1]
            for i in range(len(xs) - 1):
                if xs[i] <= tx <= xs[i + 1]:
                    span = xs[i + 1] - xs[i]
                    t = (tx - xs[i]) / span if span > 1e-9 else 0.0
                    g = ys[i] + t * (ys[i + 1] - ys[i])
                    break
        out.append(round(max(-12.0, min(12.0, g)), 2))
    return tuple(out)


def parse_apo_text(text: str) -> dict | None:
    """Parse Equalizer APO Preamp / GraphicEQ / exact Parametric PEQ Filter directives."""
    if not isinstance(text, str) or not text.strip():
        return None
    preamp_db = 0.0
    has_preamp = False
    bands = None
    peq_raw = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        m_pre = re.match(r'^Preamp\s*:\s*([+-]?\d+(?:[.,]\d+)?)\s*dB?', line, flags=re.IGNORECASE)
        if m_pre:
            preamp_db = round(max(-12.0, min(12.0, float(m_pre.group(1).replace(',', '.')))), 2)
            has_preamp = True
            continue
        m_geq = re.match(r'^GraphicEQ\s*:\s*(.+)$', line, flags=re.IGNORECASE)
        if m_geq:
            pts = []
            for part in m_geq.group(1).split(';'):
                nums = re.findall(r'[+-]?\d+(?:[.,]\d+)?', part)
                if len(nums) >= 2:
                    f = float(nums[0].replace(',', '.'))
                    g = float(nums[1].replace(',', '.'))
                    if math.isfinite(f) and math.isfinite(g) and f > 0:
                        pts.append((f, g))
            if pts:
                bands = _log_interp_points(pts)
            continue
        m_flt = re.match(
            r'^Filter\s*\d*\s*:\s*ON\s+(PK|PEQ|LS|LSC|HS|HSC)\b(?:\s+\d+(?:[.,]\d+)?\s*dB)?'
            r'\s+Fc\s+(\d+(?:[.,]\d+)?)\s*Hz\s+Gain\s+([+-]?\d+(?:[.,]\d+)?)\s*dB'
            r'(?:\s+(?:Q\s+(\d+(?:[.,]\d+)?)|BW\s+Oct\s+(\d+(?:[.,]\d+)?)))?',
            line,
            flags=re.IGNORECASE,
        )
        if m_flt:
            raw_type = m_flt.group(1).upper()
            f = float(m_flt.group(2).replace(',', '.'))
            g = float(m_flt.group(3).replace(',', '.'))
            q_str = m_flt.group(4)
            bw_str = m_flt.group(5)
            kind = 'LS' if raw_type.startswith('LS') else ('HS' if raw_type.startswith('HS') else 'PK')
            if q_str is not None:
                q_val = float(q_str.replace(',', '.'))
            elif bw_str is not None:
                bw = max(0.05, float(bw_str.replace(',', '.')))
                p2 = 2.0 ** bw
                q_val = math.sqrt(p2) / max(1e-6, p2 - 1.0)
            else:
                q_val = 0.707 if kind in ('LS', 'HS') else 1.414
            if math.isfinite(f) and math.isfinite(g) and math.isfinite(q_val) and f > 0:
                peq_raw.append((kind, f, g, q_val))

    peq_filters = normalize_peq_filters(peq_raw) if (bands is None and peq_raw) else ()
    if bands is None and peq_filters:
        # Approximate 10-band mirror for legacy callers while preserving exact Parametric PEQ in eq_peq_filters.
        mapped = []
        for target_f in EQ_FREQS:
            log_t = math.log2(float(target_f))
            acc = 0.0
            for _, f, g, _ in peq_filters:
                dist_oct = abs(math.log2(max(1.0, f)) - log_t)
                if dist_oct <= 1.0:
                    acc += g * (1.0 - dist_oct * 0.65)
            mapped.append(round(max(-12.0, min(12.0, acc)), 2))
        bands = tuple(mapped)

    if bands is None and not peq_filters and not has_preamp:
        return None
    return {
        'eq_enabled': True,
        'eq_preamp_db': preamp_db,
        'eq_bands': bands if bands is not None else FLAT_EQ_BANDS,
        'eq_peq_filters': peq_filters,
    }


def tone_peak_pad_db(profile: AudioProfile, source_info: dict | None = None) -> float:
    """Return protective true-peak headroom pad (dB) for positive EQ shelves, restorer, and 10-band EQ."""
    base = float(TONE_PEAK_PAD_DB.get(getattr(profile, 'tone', 'off'), 0.0))
    eq_boost = custom_eq_peak_boost_db(profile) if getattr(profile, 'eq_enabled', False) else 0.0
    rest = resolve_restorer(profile, source_info)
    rest_pad = 0.0
    if rest is not None:
        scale = 0.45 if getattr(profile, 'tone', 'off') in ('aria2', 'studio_aria2', 'walkman_vivid') else 1.0
        rest_pad = round(
            max(0.0, float(rest.get('sub_db', 0.0)), float(rest.get('pres_db', 0.0)), float(rest.get('air_db', 0.0)))
            * scale,
            2,
        )
    return round(base + eq_boost + rest_pad, 2)


def resolve_profile_gain_db(
    profile: AudioProfile,
    measurement: dict | None,
    target_lufs: int = DEFAULT_TARGET_LUFS,
    source_info: dict | None = None,
) -> tuple[float, bool]:
    """Compute exact 64-bit mastering gain + headroom protection shared by live playback and benchmark."""
    pad_db = tone_peak_pad_db(profile, source_info=source_info)
    preamp_offset = 0.0
    if profile.eq_enabled:
        if profile.eq_auto_preamp:
            if profile.normalize or profile.youtube_loudness:
                preamp_offset = min(0.0, float(profile.eq_preamp_db))
            else:
                preamp_offset = effective_eq_preamp_db(profile)
        else:
            preamp_offset = float(profile.eq_preamp_db)

    if measurement is not None:
        return compute_mastering_gain_db(
            measurement,
            target_lufs,
            profile.normalize,
            exclusive=(profile.output_mode == 'exclusive'),
            youtube_loudness=profile.youtube_loudness,
            tone_pad_db=pad_db,
            preamp_offset_db=preamp_offset,
        )
    if profile.normalize:
        return round(-max(1.5, pad_db) + min(0.0, float(profile.eq_preamp_db)), 3), False
    if profile.youtube_loudness:
        return round(-max(1.0, pad_db) + min(0.0, float(profile.eq_preamp_db)), 3), False
    return compute_mastering_gain_db(
        None,
        target_lufs,
        False,
        exclusive=(profile.output_mode == 'exclusive'),
        youtube_loudness=False,
        tone_pad_db=pad_db,
        preamp_offset_db=preamp_offset,
    )


def preset_profile(preset_key: str) -> tuple[AudioProfile, int | None]:
    """Return (AudioProfile, target_lufs_or_none) for a named studio/streaming quick preset."""
    if preset_key == 'studio_dawn_aria2':
        return (
            AudioProfile(
                normalize=True,
                tone='studio_aria2',
                restorer='auto',
                output_mode='exclusive',
                upsample='hires_sync',
                youtube_loudness=False,
            ),
            -16,
        )
    if preset_key == 'dac_bitperfect':
        return (
            AudioProfile(
                normalize=False,
                tone='off',
                restorer='off',
                output_mode='exclusive',
                upsample='off',
                youtube_loudness=False,
            ),
            None,
        )
    if preset_key == 'youtube':
        return (
            AudioProfile(
                normalize=False,
                tone='off',
                restorer='off',
                output_mode='shared',
                upsample='off',
                youtube_loudness=True,
            ),
            -14,
        )
    if preset_key == 'bit_pure':
        return AudioProfile.recommended(), -16
    if preset_key == 'walkman_vivid':
        return (
            AudioProfile(
                normalize=True,
                tone='walkman_vivid',
                restorer='auto',
                output_mode='shared',
                upsample='off',
                youtube_loudness=False,
            ),
            -14,
        )
    if preset_key == 'bypass':
        return AudioProfile(), None
    return AudioProfile.recommended(), -16


def detect_preset(profile: AudioProfile, target_lufs: int = -16) -> str:
    """Identify which quick preset matches the current profile & target LUFS, or 'custom'."""
    if not profile.enabled:
        return 'bypass'
    if getattr(profile, 'eq_enabled', False) or getattr(profile, 'dac_phase', 'linear') != 'linear':
        return 'custom'
    base = replace(
        profile,
        eq_enabled=False,
        eq_bands=FLAT_EQ_BANDS,
        eq_peq_filters=(),
        eq_preamp_db=0.0,
        eq_auto_preamp=True,
        eq_bass_db=0.0,
        eq_treble_db=0.0,
        eq_crossfeed=0,
        output_device='',
        dac_phase='linear',
    )
    if not base.enabled:
        return 'custom'
    if (
        base.youtube_loudness
        and not base.normalize
        and base.tone == 'off'
        and base.restorer == 'off'
        and base.output_mode == 'shared'
        and base.upsample == 'off'
    ):
        return 'youtube'
    if base == AudioProfile.recommended() and int(target_lufs) == -16:
        return 'bit_pure'
    for key in ('studio_dawn_aria2', 'dac_bitperfect', 'walkman_vivid'):
        expected_prof, expected_lufs = preset_profile(key)
        if base == expected_prof and (expected_lufs is None or int(target_lufs) == int(expected_lufs)):
            return key
    return 'custom'


@dataclass(frozen=True)
class GainDecision:
    gain_db: float
    input_lufs: float | None
    input_peak_db: float | None
    peak_limited: bool

    @property
    def output_lufs(self):
        return None if self.input_lufs is None else self.input_lufs + self.gain_db


def choose_gain(measurement, profile):
    """Legacy v1 gain selector preserved for offline cache compatibility."""
    def finite(name):
        try:
            value = float(measurement[name])
            if value == -math.inf:
                return None
            if not math.isfinite(value):
                raise ValueError('Invalid loudness measurement')
            return value
        except (KeyError, TypeError, ValueError):
            raise ValueError('Invalid loudness measurement') from None

    loudness, peak = finite('input_i'), finite('input_tp')
    if loudness is None and peak is None:
        return GainDecision(0.0, None, None, False)
    if loudness is None or peak is None:
        raise ValueError('Incomplete loudness measurement')
    desired = min(MAX_BOOST_DB, TARGET_LUFS - loudness) if profile.normalize else 0.0
    gain = min(desired, PEAK_CEILING_DB - peak)
    return GainDecision(round(gain, 4), loudness, peak, gain < desired - 0.001)


def tone_filter(profile, sample_rate=48000, channels=2):
    """Return FFmpeg biquad/crossfeed chain for the selected tone signature."""
    if profile.tone == 'studio_room':
        if channels == 2 and sample_rate >= 32000:
            return 'crossfeed=strength=0.07:range=0.32:slope=0.5:level_in=1:level_out=1:block_size=0'
        return ''
    raw_tone = TONES.get(profile.tone, '')
    if not raw_tone:
        return ''
    ceiling = max(1, int(float(sample_rate) * 0.44))
    filters = re.sub(r'(?<=f=)\d+', lambda match: str(int(min(int(match[0]), ceiling))), raw_tone)
    preamp = TONE_PREAMP_DB.get(profile.tone, 0.0)
    parts = []
    if preamp:
        parts.append(f'volume={preamp:.1f}dB')
    if profile.tone == 'easy_headphones' and channels == 2 and sample_rate >= 8000:
        parts.append('bs2b=profile=jmeier')
    parts.append(filters)
    if profile.tone == 'headphones' and channels == 2 and sample_rate >= 8000:
        parts.append('crossfeed=strength=0.08:range=0.25:slope=0.5:level_in=1:level_out=1:block_size=0')
    elif profile.tone == 'studio_aria2' and channels == 2 and sample_rate >= 32000:
        parts.append('crossfeed=strength=0.06:range=0.30:slope=0.5:level_in=1:level_out=1:block_size=0')
    return ','.join(part for part in parts if part)


def render_filter(profile, decision, sample_rate=48000, channels=2):
    parts = [tone_filter(profile, sample_rate, channels), f'volume={decision.gain_db:.4f}dB']
    return ','.join(part for part in parts if part)


def resolve_restorer(profile: AudioProfile, source_info: dict | None) -> dict | None:
    """Select phase-clean 64-bit contour compensation for legacy MP3/AAC; bypass Opus >=96k & lossless."""
    mode = getattr(profile, 'restorer', 'off')
    if mode == 'off':
        return None
    if source_info:
        sr = int(source_info.get('sample_rate') or 48000)
        if sr < 32000:
            return None
    if mode == 'natural':
        return {'mode': 'Natural', 'sub_db': 0.8, 'mud_db': -0.6, 'pres_db': 0.6, 'air_db': 1.5}
    if mode == 'vivid':
        return {'mode': 'Vivid', 'sub_db': 1.2, 'mud_db': -1.0, 'pres_db': 1.0, 'air_db': 2.4}

    codec = str((source_info or {}).get('codec_name') or '').lower()
    bit_rate = int((source_info or {}).get('bit_rate') or 0)
    if codec in LOSSLESS_CODECS or codec.startswith('pcm_') or codec.startswith('dsd_'):
        return None
    # Opus >= 96 kbps preserves full 20 kHz bandwidth natively.
    if codec == 'opus' and (bit_rate == 0 or bit_rate >= 96000):
        return None
    kbps = bit_rate / 1000.0 if bit_rate > 0 else 0.0
    if 0 < kbps <= 140.0:
        return {'mode': 'Auto (≤128k)', 'sub_db': 1.0, 'mud_db': -0.8, 'pres_db': 0.7, 'air_db': 1.8}
    if 140.0 < kbps <= 196.0 or (codec == 'mp3' and 0 < kbps <= 224.0) or (
        kbps == 0 and codec in {'mp3', 'aac', 'vorbis'}
    ):
        return {'mode': 'Auto (Lossy)', 'sub_db': 0.6, 'mud_db': -0.5, 'pres_db': 0.5, 'air_db': 1.2}
    return None


def custom_eq_filter(profile: AudioProfile, sample_rate: int = 48000, channels: int = 2, has_crossfeed: bool = False) -> str:
    """Return 64-bit float FFmpeg filter chain for user PEQ / 10-band EQ, shelves, and Crossfeed."""
    if not getattr(profile, 'eq_enabled', False):
        return ''
    sr = max(8000, int(sample_rate or 48000))
    parts = []

    bass_db = float(getattr(profile, 'eq_bass_db', 0.0) or 0.0)
    if abs(bass_db) >= 0.05:
        parts.append(_rbj_biquad_stage(55.0, 0.707, bass_db, float(sr), kind='lowshelf'))

    peq = normalize_peq_filters(getattr(profile, 'eq_peq_filters', ()))
    if peq:
        for kind, freq_hz, gain_db, q_val in peq:
            if abs(gain_db) >= 0.05:
                k_rbj = 'lowshelf' if kind == 'LS' else ('highshelf' if kind == 'HS' else 'peaking')
                parts.append(_rbj_biquad_stage(freq_hz, q_val, gain_db, float(sr), kind=k_rbj))
    else:
        bands = normalize_eq_bands(getattr(profile, 'eq_bands', FLAT_EQ_BANDS))
        for freq, gain_db in zip(EQ_FREQS, bands):
            if abs(gain_db) >= 0.05:
                parts.append(_rbj_biquad_stage(float(freq), 1.414, gain_db, float(sr), kind='peaking'))

    treble_db = float(getattr(profile, 'eq_treble_db', 0.0) or 0.0)
    if abs(treble_db) >= 0.05:
        parts.append(_rbj_biquad_stage(12500.0, 0.707, treble_db, float(sr), kind='highshelf'))

    cf = int(getattr(profile, 'eq_crossfeed', 0) or 0)
    if cf > 0 and not has_crossfeed and channels == 2 and sr >= 32000:
        strength = round(0.01 + 0.14 * (min(100, cf) / 100.0), 3)
        rng = round(0.18 + 0.30 * (min(100, cf) / 100.0), 3)
        parts.append(f'crossfeed=strength={strength}:range={rng}:slope=0.5:level_in=1:level_out=1:block_size=0')

    return ','.join(parts)


def compute_mastering_gain_db(
    measurement: dict | None,
    target_lufs: float,
    normalize: bool,
    exclusive: bool = False,
    headroom_pad_db: float = 0.0,
    youtube_loudness: bool = False,
    tone_pad_db: float = 0.0,
    preamp_offset_db: float = 0.0,
) -> tuple[float, bool]:
    """ReplayGain 2.0 / YouTube -14 LUFS law + manual preamp & CS43198 intersample peak protection."""
    base_ceiling = CS43198_EXCLUSIVE_CEILING_DB if exclusive else CS43198_CEILING_DB
    pad = max(0.0, float(tone_pad_db))
    effective_ceiling = base_ceiling - pad
    preamp = float(preamp_offset_db or 0.0)
    lufs = None
    peak_db = None
    if isinstance(measurement, dict):
        raw_lufs = measurement.get('lufs')
        raw_peak = measurement.get('peak_db')
        if isinstance(raw_lufs, (int, float)) and not isinstance(raw_lufs, bool) and math.isfinite(raw_lufs):
            lufs = float(raw_lufs)
        if isinstance(raw_peak, (int, float)) and not isinstance(raw_peak, bool) and math.isfinite(raw_peak):
            peak_db = float(raw_peak)

    if youtube_loudness:
        if lufs is None or lufs <= -70.0:
            return round(preamp, 3), False
        desired = max(-24.0, min(0.0, -14.0 - lufs)) + preamp
        if peak_db is not None:
            actual = min(desired, effective_ceiling - peak_db)
        else:
            actual = desired
        return round(actual, 3), actual < desired - 0.05

    if normalize:
        if lufs is None or lufs <= -70.0:
            return round(preamp, 3), False
        desired = max(-24.0, min(MAX_BOOST_DB, float(target_lufs) - lufs)) + preamp
        if peak_db is not None:
            actual = min(desired, effective_ceiling - peak_db)
        else:
            actual = min(desired, 4.0 - pad + min(0.0, preamp))
        return round(actual, 3), actual < desired - 0.05

    desired_unnorm = preamp
    if peak_db is not None:
        max_safe = effective_ceiling - peak_db
        if desired_unnorm > max_safe:
            return round(max(-16.0, max_safe), 3), False
        if abs(desired_unnorm) >= 0.01:
            return round(max(-16.0, min(12.0, desired_unnorm)), 3), False
        return 0.0, False
    if headroom_pad_db < 0:
        return round(float(headroom_pad_db) + preamp, 3), False
    if pad > 0 or abs(preamp) >= 0.01:
        base_pad = -(1.0 if exclusive else 0.0)
        return round(max(-16.0, min(12.0, min(base_pad, -pad) + preamp)), 3), False
    if exclusive:
        return -1.0, False
    return 0.0, False


def atempo_chain(rate: float) -> str:
    """Build chained FFmpeg atempo stages for arbitrary speed in [0.25, 4.0]."""
    try:
        r = max(0.25, min(4.0, float(rate)))
    except (TypeError, ValueError):
        return ''
    if abs(r - 1.0) <= 0.005:
        return ''
    stages = []
    while r > 2.0 + 1e-6:
        stages.append('atempo=2.0')
        r /= 2.0
    while r < 0.5 - 1e-6:
        stages.append('atempo=0.5')
        r /= 0.5
    stages.append(f'atempo={r:.4f}')
    return ','.join(stages)


def build_upsample_stage(in_sr: int, out_sr: int, dac_phase: str = 'linear') -> str:
    """Return 64-bit Linear-Phase SoXR 33-bit or Minimum-Phase causal IIR DAC oversampling stage."""
    src_sr = max(8000, int(in_sr))
    dst_sr = max(8000, int(out_sr))
    if dac_phase == 'minimum' and dst_sr >= src_sr * 2 and (dst_sr % src_sr) == 0:
        ratio = dst_sr // src_sr
        order = 14
        rp_db = 0.015
        eps = math.sqrt(10.0 ** (rp_db / 10.0) - 1.0)
        mu = math.asinh(1.0 / eps) / order
        f_p = src_sr * 0.445
        w_p = 2.0 * dst_sr * math.tan(math.pi * f_p / dst_sr)
        fs2 = 2.0 * dst_sr
        stages = [f'aresample={dst_sr}:resampler=swr:filter_size=1:phase_shift=0:linear_interp=0:dither_method=0']
        for k in range(1, order // 2 + 1):
            theta = math.pi * (2 * k - 1) / (2 * order)
            s_p = w_p * (-math.sinh(mu) * math.sin(theta) + 1j * math.cosh(mu) * math.cos(theta))
            z_p = (fs2 + s_p) / (fs2 - s_p)
            a1 = -2.0 * z_p.real
            a2 = abs(z_p) ** 2
            g_dc = (1.0 + a1 + a2) / 4.0
            stages.append(f'biquad=b0={g_dc:.12g}:b1={2.0 * g_dc:.12g}:b2={g_dc:.12g}:a0=1:a1={a1:.12g}:a2={a2:.12g}:r=f64')
        g_comp = 2.42 * (1.0 - 1.0 / float(ratio * ratio)) / 0.9375
        stages.append(f'equalizer=f={src_sr * 0.492:.1f}:t=q:w=0.85:g={g_comp:.3f}:r=f64')
        return ','.join(stages)
    return f'aresample={dst_sr}:resampler=soxr:precision=33:dither_method=0'


def build_realtime_filter_graph(
    profile: AudioProfile,
    source_info: dict | None,
    gain_db: float,
    out_sample_rate: int,
    playback_rate: float = 1.0,
) -> tuple[str, dict]:
    """Assemble 64-bit float DSP graph with SoXR Linear-Phase or Minimum-Phase oversampling before EQ."""
    out_sr = max(8000, int(out_sample_rate))
    in_sr = int((source_info or {}).get('sample_rate') or out_sr)
    in_channels = int((source_info or {}).get('channels') or 2)
    dac_phase = 'minimum' if getattr(profile, 'dac_phase', 'linear') == 'minimum' else 'linear'

    if in_channels == 1:
        stages = ['aformat=sample_fmts=dblp,pan=stereo|c0=c0|c1=c0']
    else:
        stages = ['aformat=sample_fmts=dblp:channel_layouts=stereo']

    tempo = atempo_chain(playback_rate)
    if tempo:
        stages.append(tempo)

    resampled = in_sr != out_sr
    oversampling = resampled and out_sr > in_sr
    if oversampling:
        stages.append(build_upsample_stage(in_sr, out_sr, dac_phase=dac_phase))

    eq_sr = out_sr if oversampling else in_sr
    restorer = resolve_restorer(profile, source_info)
    if restorer is not None:
        scale = 0.45 if profile.tone in ('aria2', 'studio_aria2', 'walkman_vivid') else 1.0
        nyquist_cap = max(1000, int(min(max(8000, in_sr), eq_sr) * 0.44))
        f_sub = min(58, nyquist_cap)
        f_mud = min(235, nyquist_cap)
        f_pres = min(4200, nyquist_cap)
        f_air = min(12000, nyquist_cap)
        stages.append(
            f'equalizer=f={f_sub}:t=q:w=0.8:g={restorer["sub_db"] * scale:.2f}:r=f64,'
            f'equalizer=f={f_mud}:t=q:w=1.3:g={restorer["mud_db"] * scale:.2f}:r=f64,'
            f'equalizer=f={f_pres}:t=q:w=1.4:g={restorer["pres_db"] * scale:.2f}:r=f64,'
            f'treble=f={f_air}:t=q:w=0.707:g={restorer["air_db"] * scale:.2f}:r=f64'
        )

    tone = tone_filter(profile, sample_rate=eq_sr, channels=2)
    if tone:
        stages.append(tone)

    custom_eq = custom_eq_filter(profile, sample_rate=eq_sr, channels=2, has_crossfeed=('crossfeed=' in tone))
    if custom_eq:
        stages.append(custom_eq)

    if resampled and not oversampling:
        stages.append(f'aresample={out_sr}:resampler=soxr:precision=33:dither_method=0')

    peq_count = len(normalize_peq_filters(getattr(profile, 'eq_peq_filters', ())))
    summary = {
        'restorer_active': restorer['mode'] if restorer else 'Bypass',
        'tone': profile.tone,
        'custom_eq_active': bool(custom_eq),
        'peq_count': peq_count,
        'gain_db': float(gain_db),
        'resampled': resampled,
        'soxr_precision': 33 if resampled else 0,
        'dac_phase': dac_phase,
        'upsample': getattr(profile, 'upsample', 'off'),
        'out_sample_rate': out_sr,
    }
    return ','.join(stages), summary
