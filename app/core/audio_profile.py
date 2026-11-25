"""Studio 64-bit float DSP policies, loudness targets, and DAC protection; no Qt or decoder dependencies."""
from dataclasses import dataclass
import math
import re

PROCESSOR_VERSION = 1
SCHEMA_VERSION = 4
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
PRESET_ORDER = ('studio_dawn_aria2', 'youtube', 'bit_pure', 'walkman_vivid', 'bypass')

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

    @property
    def enabled(self):
        return (
            self.normalize
            or self.youtube_loudness
            or self.tone != 'off'
            or self.restorer != 'off'
            or self.output_mode == 'exclusive'
            or self.upsample != 'off'
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
        return cls(
            normalize=normalize,
            tone=tone if isinstance(tone, str) and tone in TONES else 'off',
            restorer=restorer if isinstance(restorer, str) and restorer in RESTORER_MODES else 'off',
            output_mode=output_mode if isinstance(output_mode, str) and output_mode in OUTPUT_MODES else 'shared',
            upsample=upsample if isinstance(upsample, str) and upsample in UPSAMPLE_MODES else 'off',
            youtube_loudness=youtube_loudness,
        )

    def as_dict(self):
        return {
            'normalize': self.normalize,
            'tone': self.tone,
            'restorer': self.restorer,
            'output_mode': self.output_mode,
            'upsample': self.upsample,
            'youtube_loudness': self.youtube_loudness,
        }


def tone_peak_pad_db(profile: AudioProfile) -> float:
    """Return protective true-peak headroom pad (dB) for positive EQ shelves."""
    return float(TONE_PEAK_PAD_DB.get(getattr(profile, 'tone', 'off'), 0.0))


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
    if (
        profile.youtube_loudness
        and not profile.normalize
        and profile.tone == 'off'
        and profile.restorer == 'off'
        and profile.output_mode == 'shared'
        and profile.upsample == 'off'
    ):
        return 'youtube'
    if profile == AudioProfile.recommended() and int(target_lufs) == -16:
        return 'bit_pure'
    for key in ('studio_dawn_aria2', 'walkman_vivid'):
        expected_prof, expected_lufs = preset_profile(key)
        if profile == expected_prof and (expected_lufs is None or int(target_lufs) == int(expected_lufs)):
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


def compute_mastering_gain_db(
    measurement: dict | None,
    target_lufs: float,
    normalize: bool,
    exclusive: bool = False,
    headroom_pad_db: float = 0.0,
    youtube_loudness: bool = False,
    tone_pad_db: float = 0.0,
) -> tuple[float, bool]:
    """ReplayGain 2.0 / YouTube -14 LUFS attenuation law + CS43198 intersample peak protection."""
    base_ceiling = CS43198_EXCLUSIVE_CEILING_DB if exclusive else CS43198_CEILING_DB
    pad = max(0.0, float(tone_pad_db))
    effective_ceiling = base_ceiling - pad
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
            return 0.0, False
        desired = max(-24.0, min(0.0, -14.0 - lufs))
        if peak_db is not None:
            actual = min(desired, effective_ceiling - peak_db)
        else:
            actual = desired
        return round(actual, 3), actual < desired - 0.05

    if normalize:
        if lufs is None or lufs <= -70.0:
            return 0.0, False
        desired = max(-24.0, min(MAX_BOOST_DB, float(target_lufs) - lufs))
        if peak_db is not None:
            actual = min(desired, effective_ceiling - peak_db)
        else:
            actual = min(desired, 4.0 - pad)
        return round(actual, 3), actual < desired - 0.05

    if peak_db is not None and peak_db > effective_ceiling:
        return round(max(-4.5, effective_ceiling - peak_db), 3), False
    if headroom_pad_db < 0:
        return round(float(headroom_pad_db), 3), False
    if pad > 0 and measurement is None:
        return round(-max(1.0 if exclusive else 0.0, pad), 3), False
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
    """Assemble 64-bit float DSP graph with SoXR 33-bit oversampling before EQ to avoid Nyquist cramping."""
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

    resampled = in_sr != out_sr
    oversampling = resampled and out_sr > in_sr
    if oversampling:
        stages.append(f'aresample={out_sr}:resampler=soxr:precision=33')

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

    if resampled and not oversampling:
        stages.append(f'aresample={out_sr}:resampler=soxr:precision=33')

    summary = {
        'restorer_active': restorer['mode'] if restorer else 'Bypass',
        'tone': profile.tone,
        'gain_db': float(gain_db),
        'resampled': resampled,
        'soxr_precision': 33 if resampled else 0,
        'upsample': getattr(profile, 'upsample', 'off'),
        'out_sample_rate': out_sr,
    }
    return ','.join(stages), summary
