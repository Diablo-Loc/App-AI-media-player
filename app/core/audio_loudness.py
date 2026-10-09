"""Read-only loudness measurement and gain policy for the existing Qt output."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re

from core.audio_effects import source_signature, cache_key, find_tool, run_tool, OWNER_MARKER
from core.audio_profile import AudioProfile, PEAK_CEILING_DB, MAX_BOOST_DB
from core.subtitle_persistence import atomic_bytes

MEASUREMENT_OWNER = 'botube-loudness-measurement'
MEASUREMENT_VERSION = 1
DEFAULT_TARGET = -14
TARGETS = (-14, -18)


@dataclass(frozen=True)
class NativeGain:
    gain_db: float
    effective_volume: float
    limited: bool


def native_gain(loudness, peak, target, user_volume):
    """Fixed gain; Qt's [0, 1] volume ceiling and actual output headroom apply."""
    user_volume = max(0.0, min(1.0, float(user_volume)))
    if loudness is None and peak is None:
        return NativeGain(0.0, user_volume, False)
    if loudness is None or peak is None or not all(math.isfinite(x) for x in (loudness, peak)):
        raise ValueError('Invalid loudness measurement')
    requested = target - loudness
    desired = min(MAX_BOOST_DB, requested)
    if user_volume == 0:
        return NativeGain(desired, 0.0, False)
    headroom = 10 ** max(-300, min(0.0, (PEAK_CEILING_DB - peak) / 20))
    effective = min(user_volume * 10 ** (desired / 20), 1.0, headroom)
    actual = 20 * math.log10(effective / user_volume)
    return NativeGain(actual, effective, actual < requested - 0.001)


def valid_measurement(data):
    if not isinstance(data, dict):
        return False
    level, peak = data.get('lufs'), data.get('peak_db')
    if level is None and peak is None:
        return data.get('silent') is True
    return (isinstance(level, (int, float)) and not isinstance(level, bool)
            and isinstance(peak, (int, float)) and not isinstance(peak, bool)
            and math.isfinite(level) and math.isfinite(peak)
            and -150 <= level <= 24 and -300 <= peak <= 60)


class LoudnessCache:
    def __init__(self, root, legacy_root, limit=256):
        self.root, self.legacy_root = Path(root).resolve(), Path(legacy_root).resolve()
        self.limit = limit

    def key(self, signature, track):
        return hashlib.sha256(json.dumps({'source': signature, 'track': track,
                                         'version': MEASUREMENT_VERSION}, sort_keys=True).encode()).hexdigest()

    def lookup(self, signature, track):
        key = self.key(signature, track)
        path = self.root / (key + '.json')
        if not path.is_symlink():
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if (isinstance(record, dict) and record.get('owner') == MEASUREMENT_OWNER
                        and record.get('key') == key and record.get('source') == signature
                        and record.get('track') == track and record.get('version') == MEASUREMENT_VERSION
                        and valid_measurement(record.get('measurement'))):
                    try:
                        os.utime(path, None)
                    except OSError:
                        pass
                    return record['measurement']
            except (OSError, ValueError):
                pass
        # Reuse already measured raw, EQ-off input from v1, without touching it.
        for normalize in (True, False):
            legacy_key = cache_key(signature, AudioProfile(normalize, 'off'), track)
            path = self.legacy_root / (legacy_key + '.json')
            if path.is_symlink():
                continue
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if (not isinstance(record, dict) or record.get('owner') != OWNER_MARKER
                        or record.get('key') != legacy_key or record.get('source') != signature
                        or record.get('version') != 1 or record.get('track') != track
                        or record.get('profile') != AudioProfile(normalize, 'off').as_dict()):
                    continue
                gain = record.get('gain', {})
                measured = {'lufs': gain.get('input_lufs'), 'peak_db': gain.get('input_peak_db'),
                            'silent': gain.get('input_lufs') is None and gain.get('input_peak_db') is None}
                if isinstance(gain, dict) and 'input_lufs' in gain and 'input_peak_db' in gain and valid_measurement(measured):
                    return measured
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return None

    def save(self, signature, track, measurement):
        self.root.mkdir(parents=True, exist_ok=True)
        key = self.key(signature, track)
        target = self.root / (key + '.json')
        if target.is_symlink():
            raise ValueError('Unowned loudness cache target')
        record = {'owner': MEASUREMENT_OWNER, 'key': key, 'source': signature,
                  'track': track, 'version': MEASUREMENT_VERSION, 'measurement': measurement}
        if target.exists():
            old = json.loads(target.read_text(encoding='utf-8'))
            if not isinstance(old, dict) or old.get('owner') != MEASUREMENT_OWNER or old.get('key') != key:
                raise ValueError('Unowned loudness cache target')
        atomic_bytes(target, json.dumps(record).encode('utf-8'))
        owned = []
        for path in self.root.glob('*.json'):
            if path.is_symlink() or not re.fullmatch(r'[0-9a-f]{64}\.json', path.name):
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data, dict) and data.get('owner') == MEASUREMENT_OWNER and data.get('key') == path.stem:
                    owned.append((path.stat().st_mtime_ns, path.name, path))
            except (OSError, ValueError):
                pass
        for _, _, path in sorted(owned)[:max(0, len(owned) - self.limit)]:
            if path != target:
                path.unlink()


def measure_loudness(source, track, cache, processes, cancelled, progress=lambda text: None):
    signature = source_signature(source)
    measured = cache.lookup(signature, track)
    if measured is not None:
        return {'measurement': measured, 'cache_hit': True}
    progress('Đang đo nền; bài tiếp tục phát, không đổi nguồn…')
    _, stderr = run_tool([find_tool('ffmpeg'), '-nostdin', '-hide_banner', '-threads', '1',
                         '-filter_threads', '1', '-i', signature['path'], '-map', f'0:a:{track}',
                         '-vn', '-sn', '-dn', '-af',
                         'loudnorm=I=-18:TP=-1.5:LRA=50:print_format=json', '-f', 'null', '-'],
                         processes, cancelled)
    blocks = re.findall(rb'\{\s*"input_i".*?\}', stderr, flags=re.DOTALL)
    if not blocks:
        raise ValueError('Không đo được âm lượng; giữ âm gốc.')
    data = json.loads(blocks[-1])
    level, peak = float(data['input_i']), float(data['input_tp'])
    silent = level == peak == -math.inf
    measured = {'lufs': None if silent else level, 'peak_db': None if silent else peak, 'silent': silent}
    if not valid_measurement(measured) or source_signature(source) != signature:
        raise ValueError('Số đo chưa hợp lệ hoặc nguồn vừa thay đổi; giữ âm gốc.')
    try:
        cache.save(signature, track, measured)
    except (OSError, ValueError):
        # An unavailable disposable cache must not suppress a valid result.
        return {'measurement': measured, 'cache_hit': False, 'cache_saved': False}
    return {'measurement': measured, 'cache_hit': False, 'cache_saved': True}
