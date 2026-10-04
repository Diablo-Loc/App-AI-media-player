"""Explicit read-only local media probe; derived files live in temporary storage."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.stdout.reconfigure(encoding='utf-8')
import av
import psutil
from PySide6.QtCore import qVersion
from core.audio_profile import AudioProfile
from core.audio_effects import AudioPlaybackCache, prepare_audio
from control.worker_lifecycle import OwnedProcesses


def video_contract(path):
    digest = hashlib.sha256()
    points = []
    with av.open(str(path)) as container:
        for packet in container.demux(video=0):
            digest.update(bytes(packet))
            if packet.pts is not None:
                points.append(float(packet.pts * packet.time_base))
    return digest.hexdigest(), points


def audio_bounds(path):
    first = end = None
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            if frame.pts is not None:
                start = float(frame.pts * frame.time_base)
                if first is None:
                    first = start
                end = start + frame.samples / frame.sample_rate
    return [first, end]


class ResourceProcesses(OwnedProcesses):
    def __init__(self):
        super().__init__()
        self.max_rss = self.cpu = self.max_owned = 0
        self.cpu_samples = {}
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.sample)
        self.thread.start()

    def sample(self):
        while not self.done.wait(0.02):
            with self.lock:
                processes = tuple(self.processes)
            self.max_owned = max(self.max_owned, len(processes))
            for process in processes:
                try:
                    child = psutil.Process(process.pid)
                    self.max_rss = max(self.max_rss, child.memory_info().rss)
                    times = child.cpu_times()
                    self.cpu_samples[process.pid] = max(self.cpu_samples.get(process.pid, 0), times.user + times.system)
                except psutil.Error:
                    pass

    def release(self, process):
        try:
            times = psutil.Process(process.pid).cpu_times()
            self.cpu_samples[process.pid] = max(self.cpu_samples.get(process.pid, 0), times.user + times.system)
        except psutil.Error:
            pass
        self.cpu = sum(self.cpu_samples.values())
        super().release(process)

    def finish(self):
        self.stop()
        self.wait()
        self.done.set()
        self.thread.join()


def main():
    destination = ROOT / 'docs/audio-effects/media-probe.json'
    results = {'python': sys.version, 'qt': qVersion(), 'logical_cpus': psutil.cpu_count(),
               'profile': AudioProfile(True, 'gentle').as_dict(), 'files': []}
    with tempfile.TemporaryDirectory(prefix='botube-audio-probe-') as directory:
        cache = AudioPlaybackCache(Path(directory) / 'cache')
        for source in sorted((ROOT / 'video').glob('*.mp4')):
            processes = ResourceProcesses()
            try:
                original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                started = time.perf_counter()
                output = prepare_audio(str(source), AudioProfile(True, 'gentle'), 0, cache, processes, lambda: False)
                elapsed = time.perf_counter() - started
                original_video, original_pts = video_contract(source)
                output_video, output_pts = video_contract(output['path'])
                original_audio, output_audio = audio_bounds(source), audio_bounds(output['path'])
                started = time.perf_counter()
                hit = prepare_audio(str(source), AudioProfile(True, 'gentle'), 0, cache, processes, lambda: False)
                hit_ms = (time.perf_counter() - started) * 1000
                measurement = subprocess.run([str(ROOT / 'bin/ffmpeg.exe'), '-nostdin', '-hide_banner',
                    '-threads', '1', '-filter_threads', '1', '-i', output['path'], '-map', '0:a:0',
                    '-af', 'loudnorm=I=-18:TP=-1.5:LRA=50:print_format=json', '-f', 'null', '-'],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
                import re
                actual = json.loads(re.findall(rb'\{\s*"input_i".*?\}', measurement.stderr, re.DOTALL)[-1])
                row = {'name': source.name, 'source_bytes': source.stat().st_size,
                       'source_unchanged': original_hash == hashlib.sha256(source.read_bytes()).hexdigest(),
                       'video_packets_identical': original_video == output_video,
                       'video_packet_count_equal': len(original_pts) == len(output_pts),
                       'max_video_pts_delta_ms': max(abs(a-b)*1000 for a,b in zip(original_pts, output_pts)),
                       'video_first_pts': [original_pts[0], output_pts[0]],
                       'decoded_audio_bounds_seconds': [original_audio, output_audio],
                       'prepare_seconds': elapsed, 'ffmpeg_cpu_seconds': processes.cpu,
                       'max_child_rss_mib': processes.max_rss / 1048576, 'max_owned_processes': processes.max_owned,
                       'cache_hit': hit['cache_hit'], 'cache_hit_ms': hit_ms,
                       'output_bytes': output['record']['output_bytes'], 'gain': output['record']['gain'],
                       'actual_lufs': float(actual['input_i']), 'actual_true_peak_dbtp': float(actual['input_tp'])}
                results['files'].append(row)
                destination.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
                print(source.name, round(elapsed, 2), 's', 'video delta', round(row['max_video_pts_delta_ms'], 3), 'ms', flush=True)
            finally:
                processes.finish()


if __name__ == '__main__':
    main()
