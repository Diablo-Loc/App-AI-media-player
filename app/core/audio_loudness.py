"""Read-only audio stream probe and fast multi-threaded EBU R128 loudness index (tiny JSON metadata only)."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re

from core.audio_effects import source_signature, cache_key, find_tool, run_tool, OWNER_MARKER
from core.audio_profile import (
    AudioProfile,
    PEAK_CEILING_DB,
    MAX_BOOST_DB,
    DEFAULT_TARGET_LUFS,
    VALID_TARGETS,
)
from core.subtitle_persistence import atomic_bytes

MEASUREMENT_OWNER = 'botube-loudness-measurement'
MEASUREMENT_VERSION = 2
DEFAULT_TARGET = DEFAULT_TARGET_LUFS
TARGETS = VALID_TARGETS


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
    return (
        isinstance(level, (int, float)) and not isinstance(level, bool)
        and isinstance(peak, (int, float)) and not isinstance(peak, bool)
        and math.isfinite(level) and math.isfinite(peak)
        and -150 <= level <= 24 and -300 <= peak <= 60
    )


def _valid_source_info(info):
    return (
        isinstance(info, dict)
        and isinstance(info.get('codec_name'), str)
        and isinstance(info.get('sample_rate'), int)
        and info['sample_rate'] > 0
        and isinstance(info.get('channels'), int)
        and info['channels'] > 0
    )


class LoudnessCache:
    def __init__(self, root, legacy_root, limit=512):
        self.root, self.legacy_root = Path(root).resolve(), Path(legacy_root).resolve()
        self.limit = limit

    def key(self, signature, track, version=MEASUREMENT_VERSION):
        return hashlib.sha256(
            json.dumps({'source': signature, 'track': track, 'version': version}, sort_keys=True).encode()
        ).hexdigest()

    def lookup_full(self, signature, track):
        """Return {'measurement': dict, 'source_info': dict | None} if cached, else None."""
        for version in (MEASUREMENT_VERSION, 1):
            key = self.key(signature, track, version=version)
            path = self.root / (key + '.json')
            if path.is_symlink():
                continue
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                if (
                    isinstance(record, dict)
                    and record.get('owner') == MEASUREMENT_OWNER
                    and record.get('key') == key
                    and record.get('source') == signature
                    and record.get('track') == track
                    and record.get('version') == version
                    and valid_measurement(record.get('measurement'))
                ):
                    try:
                        os.utime(path, None)
                    except OSError:
                        pass
                    info = record.get('source_info')
                    return {
                        'measurement': record['measurement'],
                        'source_info': info if _valid_source_info(info) else None,
                    }
            except (OSError, ValueError):
                pass
        # Reuse already measured raw, EQ-off input from legacy v1 cache if present.
        for normalize in (True, False):
            legacy_key = cache_key(signature, AudioProfile(normalize, 'off'), track)
            path = self.legacy_root / (legacy_key + '.json')
            if path.is_symlink():
                continue
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                prof = record.get('profile')
                if (
                    not isinstance(record, dict)
                    or record.get('owner') != OWNER_MARKER
                    or record.get('key') != legacy_key
                    or record.get('source') != signature
                    or record.get('version') != 1
                    or record.get('track') != track
                    or not isinstance(prof, dict)
                    or prof.get('normalize') is not normalize
                    or prof.get('tone') != 'off'
                    or prof.get('restorer', 'off') != 'off'
                    or prof.get('output_mode', 'shared') != 'shared'
                    or prof.get('upsample', 'off') != 'off'
                    or prof.get('youtube_loudness', False) is not False
                ):
                    continue
                gain = record.get('gain', {})
                measured = {
                    'lufs': gain.get('input_lufs'),
                    'peak_db': gain.get('input_peak_db'),
                    'silent': gain.get('input_lufs') is None and gain.get('input_peak_db') is None,
                }
                if isinstance(gain, dict) and 'input_lufs' in gain and 'input_peak_db' in gain and valid_measurement(measured):
                    return {'measurement': measured, 'source_info': None}
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return None

    def lookup(self, signature, track):
        entry = self.lookup_full(signature, track)
        return None if entry is None else entry['measurement']

    def save(self, signature, track, measurement, source_info=None):
        self.root.mkdir(parents=True, exist_ok=True)
        key = self.key(signature, track, version=MEASUREMENT_VERSION)
        target = self.root / (key + '.json')
        if target.is_symlink():
            raise ValueError('Unowned loudness cache target')
        record = {
            'owner': MEASUREMENT_OWNER,
            'key': key,
            'source': signature,
            'track': track,
            'version': MEASUREMENT_VERSION,
            'measurement': measurement,
        }
        if _valid_source_info(source_info):
            record['source_info'] = source_info
        if target.exists():
            old = json.loads(target.read_text(encoding='utf-8'))
            if not isinstance(old, dict) or old.get('owner') != MEASUREMENT_OWNER or old.get('key') != key:
                raise ValueError('Unowned loudness cache target')
        atomic_bytes(target, json.dumps(record).encode('utf-8'))
        candidates = [
            path for path in self.root.glob('*.json')
            if not path.is_symlink() and re.fullmatch(r'[0-9a-f]{64}\.json', path.name)
        ]
        if len(candidates) <= self.limit:
            return
        owned = []
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(data, dict) and data.get('owner') == MEASUREMENT_OWNER and data.get('key') == path.stem:
                    owned.append((path.stat().st_mtime_ns, path.name, path))
            except (OSError, ValueError):
                pass
        for _, _, path in sorted(owned)[:max(0, len(owned) - self.limit)]:
            if path != target:
                path.unlink()


def probe_audio_stream(source_path, track, processes, cancelled):
    """Inspect source audio codec, sample rate, channels, bitrate, and duration (read-only)."""
    ffprobe = find_tool('ffprobe')
    stdout, _ = run_tool(
        [
            ffprobe, '-v', 'error', '-probesize', '262144', '-analyzeduration', '500000',
            '-show_streams', '-show_format', '-of', 'json', str(source_path),
        ],
        processes,
        cancelled,
        timeout=8,
    )
    info = json.loads(stdout)
    all_streams = info.get('streams', [])
    audio_streams = [s for s in all_streams if s.get('codec_type') == 'audio']
    if not audio_streams:
        raise ValueError('Bài này không có luồng âm thanh.')
    actual_track = track if 0 <= track < len(audio_streams) else 0
    audio = audio_streams[actual_track]
    fmt = info.get('format', {})
    has_video = any(s.get('codec_type') == 'video' and not (s.get('disposition') or {}).get('attached_pic') for s in all_streams)

    bit_rate = 0
    try:
        if audio.get('bit_rate') and int(audio['bit_rate']) > 0:
            bit_rate = int(audio['bit_rate'])
    except (TypeError, ValueError):
        pass
    if not bit_rate and not has_video:
        try:
            if fmt.get('bit_rate') and int(fmt['bit_rate']) > 0:
                bit_rate = int(fmt['bit_rate'])
        except (TypeError, ValueError):
            pass
    if not bit_rate:
        tags = audio.get('tags') or {}
        for key in ('BPS', 'BPS-eng', 'bps'):
            try:
                if tags.get(key) and int(tags[key]) > 0:
                    bit_rate = int(tags[key])
                    break
            except (TypeError, ValueError):
                pass

    try:
        sample_rate = max(8000, int(audio.get('sample_rate') or 48000))
    except (TypeError, ValueError):
        sample_rate = 48000
    try:
        channels = max(1, int(audio.get('channels') or 2))
    except (TypeError, ValueError):
        channels = 2
    try:
        duration = max(0.0, float(audio.get('duration') or fmt.get('duration') or 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    try:
        bits_raw = int(audio.get('bits_per_raw_sample') or audio.get('bits_per_sample') or 0)
    except (TypeError, ValueError):
        bits_raw = 0

    return {
        'codec_name': str(audio.get('codec_name') or 'unknown').lower(),
        'sample_rate': sample_rate,
        'channels': channels,
        'bit_rate': bit_rate,
        'duration': duration,
        'bits_per_raw_sample': bits_raw,
        'track': actual_track,
    }


def _parse_ebur128_stderr(stderr):
    i_matches = re.findall(rb'I:\s*(-?\d+(?:\.\d+)?|-inf)\s*LUFS', stderr)
    p_matches = re.findall(rb'Peak:\s*(-?\d+(?:\.\d+)?|-inf)\s*dBFS', stderr)
    if not i_matches or not p_matches:
        return None
    raw_i, raw_p = i_matches[-1], p_matches[-1]
    level = -math.inf if raw_i == b'-inf' else float(raw_i)
    peak = -math.inf if raw_p == b'-inf' else float(raw_p)
    silent = level == -math.inf or (level <= -70.0 and peak <= -70.0)
    measured = {'lufs': None if silent else level, 'peak_db': None if silent else peak, 'silent': silent}
    return measured if valid_measurement(measured) else None


def _parse_loudnorm_stderr(stderr):
    blocks = re.findall(rb'\{\s*"input_i".*?\}', stderr, flags=re.DOTALL)
    if not blocks:
        return None
    data = json.loads(blocks[-1])
    level, peak = float(data['input_i']), float(data['input_tp'])
    silent = level == peak == -math.inf
    measured = {'lufs': None if silent else level, 'peak_db': None if silent else peak, 'silent': silent}
    return measured if valid_measurement(measured) else None


def measure_quick_loudness(source_path, track, duration, processes, cancelled):
    """Measure a representative 12s window (~70ms) on long videos/movies."""
    start_s = min(max(0.0, float(duration) * 0.22), 25.0) if float(duration or 0.0) > 16.0 else 0.0
    ffmpeg = find_tool('ffmpeg')
    _, stderr = run_tool(
        [
            ffmpeg, '-nostdin', '-hide_banner', '-threads', '4',
            '-ss', f'{start_s:.2f}', '-t', '12.0',
            '-i', str(source_path), '-map', f'0:a:{track}', '-vn', '-sn', '-dn',
            '-af', 'ebur128=peak=true', '-f', 'null', '-',
        ],
        processes,
        cancelled,
        timeout=15,
    )
    measured = _parse_ebur128_stderr(stderr)
    if measured is None:
        _, stderr2 = run_tool(
            [
                ffmpeg, '-nostdin', '-hide_banner', '-threads', '2',
                '-ss', f'{start_s:.2f}', '-t', '12.0',
                '-i', str(source_path), '-map', f'0:a:{track}', '-vn', '-sn', '-dn',
                '-af', 'loudnorm=I=-16:TP=-1.5:LRA=50:print_format=json', '-f', 'null', '-',
            ],
            processes,
            cancelled,
            timeout=15,
        )
        measured = _parse_loudnorm_stderr(stderr2)
    if measured is None:
        return None
    measured['provisional'] = True
    return measured


def measure_loudness(source, track, cache, processes, cancelled, progress=lambda text: None, source_info=None):
    signature = source_signature(source)
    entry = cache.lookup_full(signature, track)
    if entry is not None:
        return {
            'measurement': entry['measurement'],
            'source_info': entry['source_info'] or source_info,
            'cache_hit': True,
        }
    progress('Đang đo độ lớn EBU R128 trong RAM…')
    ffmpeg = find_tool('ffmpeg')
    _, stderr = run_tool(
        [
            ffmpeg, '-nostdin', '-hide_banner', '-threads', '4',
            '-i', signature['path'], '-map', f'0:a:{track}',
            '-vn', '-sn', '-dn', '-af', 'ebur128=peak=true', '-f', 'null', '-',
        ],
        processes,
        cancelled,
    )
    measured = _parse_ebur128_stderr(stderr)
    if measured is None:
        # Ultra-short clips (<0.4s) may lack ebur128 gated blocks -> fall back to loudnorm.
        _, stderr2 = run_tool(
            [
                ffmpeg, '-nostdin', '-hide_banner', '-threads', '1',
                '-filter_threads', '1', '-i', signature['path'], '-map', f'0:a:{track}',
                '-vn', '-sn', '-dn', '-af',
                'loudnorm=I=-16:TP=-1.5:LRA=50:print_format=json', '-f', 'null', '-',
            ],
            processes,
            cancelled,
        )
        measured = _parse_loudnorm_stderr(stderr2)
    if measured is None:
        raise ValueError('Không đo được âm lượng; giữ âm gốc.')
    if source_signature(source) != signature:
        raise ValueError('Số đo chưa hợp lệ hoặc nguồn vừa thay đổi; giữ âm gốc.')
    try:
        cache.save(signature, track, measured, source_info=source_info)
    except (OSError, ValueError):
        return {'measurement': measured, 'source_info': source_info, 'cache_hit': False, 'cache_saved': False}
    return {'measurement': measured, 'source_info': source_info, 'cache_hit': False, 'cache_saved': True}
