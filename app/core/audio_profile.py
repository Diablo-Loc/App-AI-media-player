"""Conservative, constant-gain audio policies; no Qt or decoder dependencies."""
from dataclasses import dataclass
import math
import re

PROCESSOR_VERSION = 1
TARGET_LUFS = -18.0
PEAK_CEILING_DB = -1.7  # Includes 0.2 dB margin above the advertised -1.5 dBTP.
MAX_BOOST_DB = 12.0
TONES = {
    'off': '',
    'gentle': 'equalizer=f=3200:t=q:w=0.8:g=-2.5,treble=f=8000:g=-1.5',
    'balanced': 'equalizer=f=3500:t=q:w=1:g=-1.2,treble=f=10000:g=-0.7',
    # Conservative cut-only voicing. Existing profiles/version/keys stay frozen.
    'warm': 'equalizer=f=280:t=q:w=0.7:g=-0.7:r=f64,'
            'equalizer=f=3200:t=q:w=0.8:g=-1.5:r=f64,treble=f=8500:g=-0.8:r=f64',
    'headphones': 'equalizer=f=280:t=q:w=0.7:g=-0.7:r=f64,'
                  'equalizer=f=3200:t=q:w=0.8:g=-1.5:r=f64,treble=f=8500:g=-0.8:r=f64',
    # Separate opt-in voicing: small bass shelf and broad, gentle treble cuts.
    'easy': 'bass=f=100:t=q:w=0.707:g=1.5:r=f64,'
            'equalizer=f=3500:t=q:w=0.8:g=-1:r=f64,'
            'equalizer=f=7000:t=q:w=1:g=-1.5:r=f64,treble=f=10000:t=q:w=0.707:g=-1:r=f64',
    'easy_headphones': 'bass=f=100:t=q:w=0.707:g=1.5:r=f64,'
                       'equalizer=f=3500:t=q:w=0.8:g=-1:r=f64,'
                       'equalizer=f=7000:t=q:w=1:g=-1.5:r=f64,treble=f=10000:t=q:w=0.707:g=-1:r=f64',
}


@dataclass(frozen=True)
class AudioProfile:
    normalize: bool = False
    tone: str = 'off'

    @property
    def enabled(self):
        return self.normalize or self.tone != 'off'

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        tone = data.get('tone', 'off')
        return cls(normalize=data.get('normalize') is True,
                   tone=tone if isinstance(tone, str) and tone in TONES else 'off')

    def as_dict(self):
        return {'normalize': self.normalize, 'tone': self.tone}


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
    if loudness is None and peak is None:  # Silence: never amplify numerical noise.
        return GainDecision(0.0, None, None, False)
    if loudness is None or peak is None:
        raise ValueError('Incomplete loudness measurement')
    desired = min(MAX_BOOST_DB, TARGET_LUFS - loudness) if profile.normalize else 0.0
    gain = min(desired, PEAK_CEILING_DB - peak)
    return GainDecision(round(gain, 4), loudness, peak, gain < desired - 0.001)


def tone_filter(profile, sample_rate=48000, channels=2):
    ceiling = max(1, float(sample_rate) * 0.45)
    filters = re.sub(r'(?<=f=)\d+', lambda match: str(int(min(int(match[0]), ceiling))), TONES[profile.tone])
    if profile.tone in ('easy', 'easy_headphones'):
        # Preamp precedes both crossfeed and EQ. Full-chain peak measurement
        # still governs final constant gain; no dynamics processor is added.
        crossfeed = 'bs2b=profile=jmeier,' if profile.tone == 'easy_headphones' and channels == 2 and sample_rate >= 8000 else ''
        filters = 'volume=-1.5dB,' + crossfeed + filters
    if profile.tone == 'headphones' and channels == 2 and sample_rate >= 8000:
        # No reverse-IIR block delay, resampling, widening or artificial reverb.
        filters += ',crossfeed=strength=0.08:range=0.25:slope=0.5:level_in=1:level_out=1:block_size=0'
    return filters


def render_filter(profile, decision, sample_rate=48000, channels=2):
    parts = [tone_filter(profile, sample_rate, channels), f'volume={decision.gain_db:.4f}dB']
    return ','.join(part for part in parts if part)
