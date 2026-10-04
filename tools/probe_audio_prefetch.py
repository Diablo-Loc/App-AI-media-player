"""Eight-media prefetch/Next probe, muted Qt; media and saved user data read-only."""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from tools.ui_preview import isolated_window
from PySide6.QtCore import QTimer, QUrl, qVersion
from PySide6.QtMultimedia import QMediaPlayer
from core.audio_profile import AudioProfile
from core.audio_effects import prepare_audio
from tests.test_audio_effects import wait_until, FFMPEG, FFPROBE
from tools.probe_audio_effects import ResourceProcesses

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    sources = sorted((ROOT / 'video').glob('*.mp4'))
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    report = {'python': sys.version, 'qt': qVersion(), 'mode': 'offscreen decoder, audio muted', 'files': []}
    records, active, max_active = [], 0, 0
    lock = threading.Lock()

    def measured(source, profile, track, cache, processes, cancelled, protected, progress):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        started = time.perf_counter()
        try:
            result = prepare_audio(source, profile, track, cache, processes, cancelled, protected, progress)
            records.append({'source': source, 'seconds': time.perf_counter() - started,
                'cache_hit': result['cache_hit'], 'max_child_rss_mib': processes.max_rss / 1048576,
                'child_cpu_seconds': processes.cpu, 'max_owned_processes': processes.max_owned,
                'protected': list(protected)})
            return result
        finally:
            processes.finish()
            with lock:
                active -= 1

    with isolated_window() as (window, root), \
            patch('control.audio_effects.prepare_audio', side_effect=measured), \
            patch('control.audio_effects.OwnedProcesses', side_effect=ResourceProcesses), \
            patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE):
        c, player = window.audio_effects, window.media_player.player
        window.audio_output.setMuted(True)
        items = [SimpleNamespace(id=str(i), path=source, title=source.stem, artist='', thumbnail=None)
                 for i, source in enumerate(sources)]
        window.active_playlist = items
        window.current_media_item = items[0]
        c.profile = AudioProfile(True, 'gentle')
        c.set_prefetch(False)
        c.play_source(QUrl.fromLocalFile(str(sources[0])))
        wait_until(lambda: not c.switching and player.position() > 50, timeout=20)
        c.set_prefetch(True)
        heartbeat = QTimer(window)
        heartbeat.setInterval(16)
        gaps, stamp = [], [time.perf_counter()]
        def beat():
            now = time.perf_counter()
            gaps.append((now - stamp[0]) * 1000)
            stamp[0] = now
        heartbeat.timeout.connect(beat)
        frames, source_changes, states = [], [], []
        player.videoSink().videoFrameChanged.connect(lambda frame: frames.append(time.perf_counter()) if frame.isValid() else None)
        player.sourceChanged.connect(source_changes.append)
        player.playbackStateChanged.connect(states.append)

        for index in range(1, len(items) + 1):
            next_item = items[index % len(items)]
            current_source = player.source()
            current_volume = window.audio_output.volume()
            starting_records = len(records)
            frames.clear()
            source_changes.clear()
            states.clear()
            gaps.clear()
            stamp[0] = time.perf_counter()
            started = stamp[0]
            heartbeat.start()
            wait_until(lambda: len(records) > starting_records and c.worker is None, timeout=35)
            observed_seconds = time.perf_counter() - started
            heartbeat.stop()
            preparation = records[-1]
            assert Path(preparation['source']) == next_item.path
            assert player.source() == current_source and not source_changes and not states
            assert abs(window.audio_output.volume() - current_volume) < 1e-6
            assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            assert current_source.toLocalFile() in preparation['protected']
            frame_rate = len(frames) / observed_seconds
            gui_max = max(gaps, default=0)
            before_next_records = len(records)
            window.current_media_item = next_item
            started = time.perf_counter()
            c.play_source(QUrl.fromLocalFile(str(next_item.path)))
            wait_until(lambda: not c.switching and player.position() > 50 and c.worker is None, timeout=10)
            next_seconds = time.perf_counter() - started
            assert len(records) == before_next_records + 1 and records[-1]['cache_hit']
            assert player.activeVideoTrack() == 0 and window.audio_output.isMuted()
            row = {'name': next_item.path.name, 'prefetch': preparation,
                'prefetch_observation_seconds_including_settle': observed_seconds,
                'next_wait_to_position_50ms_seconds': next_seconds,
                'current_source_state_volume_unchanged': True,
                'decoded_frame_signals_per_second_during_prefetch': frame_rate,
                'max_gui_heartbeat_gap_ms_during_prefetch': gui_max}
            report['files'].append(row)
            print(next_item.path.name, 'prepared', round(preparation['seconds'], 3),
                  'Next', round(next_seconds, 3), 's', flush=True)
            (ROOT / 'docs/audio-prefetch/media-probe.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        c.set_prefetch(False)
        report['max_active_audio_jobs'] = max_active
    report['all_source_hashes_unchanged'] = all(hashlib.sha256(path.read_bytes()).hexdigest() == before[path] for path in sources)
    assert max_active == 1 and report['all_source_hashes_unchanged']
    (ROOT / 'docs/audio-prefetch/media-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
