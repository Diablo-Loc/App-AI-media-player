"""Studio 64-bit float DSP policies, loudness targets, and DAC protection; no Qt or decoder dependencies."""
from dataclasses import dataclass
import math
import re

PROCESSOR_VERSION = 1
SCHEMA_VERSION = 2
TARGET_LUFS = -18.0
DEFAULT_TARGET_LUFS = -16
VALID_TARGETS = (-16, -14, -18)
PEAK_CEILING_DB = -1.7  # Legacy v1 constant preserved for compatibility.
CS43198_CEILING_DB = -1.5
CS43198_LIMIT_LINEAR = round(10 ** (CS43198_CEILING_DB / 20.0), 6)  # 0.841395
MAX_BOOST_DB = 12.0
MAX_LIMITER_DRIVE_DB = 4.5

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
    # Moondrop Aria 2 + Dawn Pro 2 Reference: 64-bit float linear biquad polish.
    'aria2': 'bass=f=55:t=q:w=0.707:g=1.3:r=f64,'
             'equalizer=f=215:t=q:w=1.1:g=-0.8:r=f64,'
             'equalizer=f=3100:t=q:w=1.2:g=0.5:r=f64,'
             'equalizer=f=8000:t=q:w=2.5:g=-1.1:r=f64,'
             'treble=f=13500:t=q:w=0.707:g=1.3:r=f64',
    'vocal_clear': 'equalizer=f=185:t=q:w=1.0:g=-1.0:r=f64,'
                   'equalizer=f=2850:t=q:w=1.1:g=1.0:r=f64,'
                   'equalizer=f=7800:t=q:w=2.2:g=-0.8:r=f64,'
                   'treble=f=12500:t=q:w=0.707:g=1.1:r=f64',
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
    'aria2': -1.4,
    'vocal_clear': -1.2,
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
        return cls(normalize=True, tone='aria2', restorer='auto', output_mode='shared')

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
    """Decide whether and how strongly to run DSEE-style lossy high-frequency & transient restoration."""
    mode = getattr(profile, 'restorer', 'off')
    if mode == 'off':
        return None
    if source_info:
        sr = int(source_info.get('sample_rate') or 48000)
        if sr < 32000:
            return None
    if mode == 'natural':
        return {'mode': 'Natural', 'air_db': -22.5, 'crystalizer': 1.18}
    if mode == 'vivid':
        return {'mode': 'Vivid', 'air_db': -18.5, 'crystalizer': 1.50}
    # Auto mode: restore compressed MP3/AAC <= 192 kbps, strictly bypass lossless & high-bitrate streams.
    codec = str((source_info or {}).get('codec_name') or '').lower()
    bit_rate = int((source_info or {}).get('bit_rate') or 0)
    if codec in LOSSLESS_CODECS or codec.startswith('pcm_') or codec.startswith('dsd_'):
        return None
    kbps = bit_rate / 1000.0 if bit_rate > 0 else 0.0
    if 0 < kbps <= 140.0:
        return {'mode': 'Auto (≤128k)', 'air_db': -19.5, 'crystalizer': 1.38}
    if 140.0 < kbps <= 196.0 or (codec == 'mp3' and 0 < kbps <= 224.0) or (
        kbps == 0 and codec in {'mp3', 'aac', 'vorbis'}
    ):
        return {'mode': 'Auto (Lossy)', 'air_db': -22.5, 'crystalizer': 1.15}
    return None


def compute_mastering_gain_db(
    measurement: dict | None,
    target_lufs: float,
    normalize: bool,
    exclusive: bool = False,
) -> tuple[float, bool]:
    """Compute 64-bit float pre-gain allowing lookahead limiter headroom for CS43198 intersample protection."""
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
            max_allowed = (CS43198_CEILING_DB + MAX_LIMITER_DRIVE_DB) - peak_db
            actual = min(desired, max_allowed)
        else:
            actual = desired
        return round(actual, 3), actual < desired - 0.05

    # Unnormalized path: protect Cirrus Logic CS43198 internal oversampling filters from intersample clipping.
    if peak_db is not None and peak_db > CS43198_CEILING_DB:
        return round(max(-2.5, CS43198_CEILING_DB - peak_db), 3), False
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
    """Assemble a 64-bit float FFmpeg filtergraph with SoXR 28-bit resampling and CS43198 limiter."""
    out_sr = max(8000, int(out_sample_rate))
    stages = ['aformat=sample_fmts=dblp:channel_layouts=stereo']

    tempo = atempo_chain(playback_rate)
    if tempo:
        stages.append(tempo)

    restorer = resolve_restorer(profile, source_info)
    if restorer is not None:
        in_sr = int((source_info or {}).get('sample_rate') or out_sr)
        nyquist_cap = min(19500, int(min(max(8000, in_sr), out_sr) * 0.44))
        if nyquist_cap >= 14000:
            exciter = (
                'asplit=2[dry][exc];'
                f'[exc]highpass=f=6800:poles=2,volume=6dB,asoftclip=type=atan:param=1.5,'
                f'highpass=f=12500:poles=2,lowpass=f={nyquist_cap}:poles=2,'
                f'volume={restorer["air_db"]:.1f}dB[air];'
                f'[dry][air]amix=inputs=2:weights=1 1:normalize=0,crystalizer=i={restorer["crystalizer"]:.2f}:c=1'
            )
            stages.append(exciter)
        else:
            stages.append(f'crystalizer=i={restorer["crystalizer"]:.2f}:c=1')

    tone = tone_filter(profile, sample_rate=out_sr, channels=2)
    if tone:
        stages.append(tone)

    if abs(float(gain_db)) >= 0.01:
        stages.append(f'volume={float(gain_db):.3f}dB')

    stages.append(f'aresample={out_sr}:resampler=soxr:precision=28')
    stages.append(
        f'alimiter=level_in=1:level_out=1:limit={CS43198_LIMIT_LINEAR}:attack=5:release=50:asc=1:level=0'
    )

    summary = {
        'restorer_active': restorer['mode'] if restorer else 'Bypass',
        'tone': profile.tone,
        'gain_db': float(gain_db),
        'out_sample_rate': out_sr,
    }
    return ','.join(stages), summary
