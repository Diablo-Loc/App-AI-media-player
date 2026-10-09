"""Read-only eight-video listening probe; all derived audio/cache are temporary."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time

from tools.probe_audio_effects import ResourceProcesses, video_contract, audio_bounds
from core.audio_profile import AudioProfile
from core.audio_effects import AudioPlaybackCache, prepare_audio, run_tool

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / 'docs/audio-listening/media-probe.json'
    results = {'python': sys.version, 'mode': 'read-only real media; no listening ground truth', 'files': []}
    with tempfile.TemporaryDirectory(prefix='botube-listening-probe-') as directory:
        cache = AudioPlaybackCache(Path(directory) / 'cache')
        for source in sorted((ROOT / 'video').glob('*.mp4')):
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            video, points = video_contract(source)
            bounds = audio_bounds(source)
            for tone in ('warm', 'headphones'):
                processes = ResourceProcesses()
                try:
                    started = time.perf_counter()
                    output = prepare_audio(str(source), AudioProfile(False, tone), 0, cache, processes, lambda: False)
                    seconds = time.perf_counter() - started
                    peak_rss = processes.max_rss / 1048576
                    prepared_video, prepared_points = video_contract(output['path'])
                    prepared_bounds = audio_bounds(output['path'])
                    _, stderr = run_tool([str(ROOT / 'bin/ffmpeg.exe'), '-nostdin', '-hide_banner',
                        '-threads', '1', '-filter_threads', '1', '-i', output['path'], '-map', '0:a:0',
                        '-af', 'loudnorm=I=-18:TP=-1.5:LRA=50:print_format=json', '-f', 'null', '-'],
                        processes, lambda: False)
                    actual = json.loads(re.findall(rb'\{\s*"input_i".*?\}', stderr, re.DOTALL)[-1])
                    started = time.perf_counter()
                    hit = prepare_audio(str(source), AudioProfile(False, tone), 0, cache, processes, lambda: False)
                    hit_ms = (time.perf_counter() - started) * 1000
                    row = {'name': source.name, 'tone': tone, 'prepare_seconds': seconds,
                        'prepare_child_peak_rss_mib': peak_rss, 'max_owned_processes': processes.max_owned,
                        'source_unchanged': before == hashlib.sha256(source.read_bytes()).hexdigest(),
                        'video_packets_identical': video == prepared_video,
                        'video_packet_count_equal': len(points) == len(prepared_points),
                        'max_video_pts_delta_ms': max(abs(a-b)*1000 for a,b in zip(points, prepared_points)),
                        'audio_bounds': [bounds, prepared_bounds], 'gain': output['record']['gain'],
                        'actual_lufs': float(actual['input_i']), 'actual_true_peak_dbtp': float(actual['input_tp']),
                        'cache_hit': hit['cache_hit'], 'cache_hit_ms': hit_ms}
                    assert row['source_unchanged'] and row['video_packets_identical'] and row['video_packet_count_equal']
                    assert row['max_video_pts_delta_ms'] <= 0.51 and row['cache_hit']
                    assert row['actual_true_peak_dbtp'] <= -1.5
                    assert abs(bounds[0]-prepared_bounds[0]) <= .002 and abs(bounds[1]-prepared_bounds[1]) <= .002
                    results['files'].append(row)
                    destination.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(source.name, tone, round(seconds, 3), 's', row['actual_true_peak_dbtp'], 'dBTP', flush=True)
                finally:
                    processes.finish()


if __name__ == '__main__':
    main()
