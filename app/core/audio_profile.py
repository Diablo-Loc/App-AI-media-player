"""Studio 64-bit float DSP policies, loudness targets, and DAC protection; no Qt or decoder dependencies."""
from dataclasses import dataclass
import math
import re

PROCESSOR_VERSION = 1
SCHEMA_VERSION = 3
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

LOSSLESS_CODECS = frozenset({
    'flac', 'alac', 'wavpack', 'ape', 'tak', 'tta',
    'pcm_s16le', 'pcm_s24le', 'pcm_s32le', 'pcm_f32le', 'pcm_f64le',
    'pcm_s16be', 'pcm_s24be', 'pcm_s32be', 'pcm_u8',
    'dsd_lsbf', 'dsd_msbf', 'dsd_lsbf_planar', 'dsd_msbf_planar',
})

TONES = {
    'off': '',
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


@dataclass(frozen=True)
class AudioProfile:
    normalize: bool = False
    tone: str = 'off'
    restorer: str = 'off'
    output_mode: str = 'shared'

    @property
    def enabled(self):
        return (
            self.normalize
            or self.tone != 'off'
            or self.restorer != 'off'
            or self.output_mode == 'exclusive'
        )

    @classmethod
    def recommended(cls):
        """100% uncolored bit-pure tonal path + EBU R128 mastering loudness & intersample de-clip headroom."""
        return cls(normalize=True, tone='off', restorer='off', output_mode='shared')

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        tone = data.get('tone', 'off')
        restorer = data.get('restorer', 'off')
        output_mode = data.get('output_mode', 'shared')
        return cls(
            normalize=data.get('normalize') is True,
            tone=tone if isinstance(tone, str) and tone in TONES else 'off',
            restorer=restorer if isinstance(restorer, str) and restorer in RESTORER_MODES else 'off',
            output_mode=output_mode if isinstance(output_mode, str) and output_mode in OUTPUT_MODES else 'shared',
        )

    def as_dict(self):
        return {
            'normalize': self.normalize,
            'tone': self.tone,
            'restorer': self.restorer,
            'output_mode': self.output_mode,
        }


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


def compute_mastering_gain_db(
    measurement: dict | None,
    target_lufs: float,
    normalize: bool,
    exclusive: bool = False,
    headroom_pad_db: float = 0.0,
) -> tuple[float, bool]:
    """ReplayGain 2.0 / Roon pure linear gain preserving 100% transient dynamics and CS43198 headroom."""
    ceiling = CS43198_EXCLUSIVE_CEILING_DB if exclusive else CS43198_CEILING_DB
    lufs = None
    peak_db = None
    if isinstance(measurement, dict):
        raw_lufs = measurement.get('lufs')
        raw_peak = measurement.get('peak_db')
        if isinstance(raw_lufs, (int, float)) and not isinstance(raw_lufs, bool) and math.isfinite(raw_lufs):
            lufs = float(raw_lufs)
        if isinstance(raw_peak, (int, float)) and not isinstance(raw_peak, bool) and math.isfinite(raw_peak):
            peak_db = float(raw_peak)

    if normalize:
        if lufs is None or lufs <= -70.0:
            return 0.0, False
        desired = max(-24.0, min(MAX_BOOST_DB, float(target_lufs) - lufs))
        if peak_db is not None:
            actual = min(desired, ceiling - peak_db)
        else:
            actual = min(desired, 4.0)
        return round(actual, 3), actual < desired - 0.05

    if peak_db is not None and peak_db > ceiling:
        return round(max(-2.5, ceiling - peak_db), 3), False
    if headroom_pad_db < 0:
        return round(float(headroom_pad_db), 3), False
    if exclusive and measurement is None:
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


def build_realtime_filter_graph(
    profile: AudioProfile,
    source_info: dict | None,
    gain_db: float,
    out_sample_rate: int,
    playback_rate: float = 1.0,
) -> tuple[str, dict]:
    """Assemble unclipped bit-pure float decode path (resampling ONLY when sample rates differ)."""
    out_sr = max(8000, int(out_sample_rate))
    in_sr = int((source_info or {}).get('sample_rate') or out_sr)
    in_channels = int((source_info or {}).get('channels') or 2)

    if in_channels == 1:
        stages = ['aformat=sample_fmts=dblp,pan=stereo|c0=c0|c1=c0']
    else:
        stages = ['aformat=sample_fmts=dblp:channel_layouts=stereo']

    tempo = atempo_chain(playback_rate)
    if tempo:
        stages.append(tempo)

    restorer = resolve_restorer(profile, source_info)
    if restorer is not None:
        scale = 0.45 if profile.tone == 'aria2' else 1.0
        nyquist_cap = max(1000, int(min(max(8000, in_sr), out_sr) * 0.44))
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

    tone = tone_filter(profile, sample_rate=out_sr, channels=2)
    if tone:
        stages.append(tone)

    resampled = in_sr != out_sr
    if resampled:
        stages.append(f'aresample={out_sr}:resampler=soxr:precision=28')

    summary = {
        'restorer_active': restorer['mode'] if restorer else 'Bypass',
        'tone': profile.tone,
        'gain_db': float(gain_db),
        'resampled': resampled,
        'out_sample_rate': out_sr,
    }
    return ','.join(stages), summary
