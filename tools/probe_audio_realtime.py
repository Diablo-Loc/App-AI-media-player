"""Read-only eight-video measurement probe for source-preserving normalization."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.stdout.reconfigure(encoding='utf-8')
from PySide6.QtCore import qVersion
from core.audio_loudness import LoudnessCache, measure_loudness, native_gain, DEFAULT_TARGET
from tools.probe_audio_effects import ResourceProcesses


def main():
    destination = ROOT / 'docs/audio-realtime/media-probe.json'
    results = {'python': sys.version, 'qt': qVersion(), 'target_lufs': DEFAULT_TARGET,
               'user_volume': 0.5, 'files': []}
    with tempfile.TemporaryDirectory(prefix='botube-native-gain-probe-') as directory:
        cache = LoudnessCache(Path(directory) / 'cache', Path(directory) / 'legacy')
        for source in sorted((ROOT / 'video').glob('*.mp4')):
            original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            processes = ResourceProcesses()
            try:
                started = time.perf_counter()
                result = measure_loudness(str(source), 0, cache, processes, lambda: False)
                elapsed = time.perf_counter() - started
                started = time.perf_counter()
                with patch('core.audio_loudness.run_tool', side_effect=AssertionError('hit must not start FFmpeg')):
                    hit = measure_loudness(str(source), 0, cache, processes, lambda: False)
                hit_ms = (time.perf_counter() - started) * 1000
                level = result['measurement']
                gain = native_gain(level['lufs'], level['peak_db'], DEFAULT_TARGET, 0.5)
                row = {'name': source.name, 'source_bytes': source.stat().st_size,
                       'source_unchanged': original_hash == hashlib.sha256(source.read_bytes()).hexdigest(),
                       'measure_seconds': elapsed, 'cache_hit_ms': hit_ms, 'cache_hit': hit['cache_hit'],
                       'measurement': level, 'native_gain_db': gain.gain_db,
                       'effective_volume': gain.effective_volume, 'limited': gain.limited,
                       'max_child_rss_mib': processes.max_rss / 1048576,
                       'max_owned_processes': processes.max_owned}
                results['files'].append(row)
                results['cache_bytes'] = sum(p.stat().st_size for p in cache.root.glob('*.json'))
                results['derived_media_files'] = len(list(Path(directory).rglob('*.mkv')))
                destination.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                print(source.name, round(elapsed, 3), 's', 'cache', round(hit_ms, 3), 'ms', flush=True)
            finally:
                processes.finish()
    assert len(results['files']) == 8
    assert all(row['source_unchanged'] and row['cache_hit'] for row in results['files'])
    assert results['derived_media_files'] == 0


if __name__ == '__main__':
    main()
