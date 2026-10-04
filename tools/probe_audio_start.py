"""Read-only eight-media cold/cache Qt start probe; isolated settings and cache."""
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

from tools.ui_preview import isolated_window, pump
from PySide6.QtCore import QUrl, qVersion
from PySide6.QtMultimedia import QMediaPlayer
from core.audio_profile import AudioProfile
from core.audio_effects import run_tool
from tests.test_audio_effects import wait_until, FFMPEG, FFPROBE

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    report = {'python': sys.version, 'qt': qVersion(), 'mode': 'offscreen Qt decoder, muted', 'files': []}
    with isolated_window() as (window, root):
        controller, player = window.audio_effects, window.media_player.player
        window.audio_output.setMuted(True)
        controller.profile = AudioProfile(True, 'gentle')
        requests = []
        source_changes = []
        playing_sources = []
        player.sourceChanged.connect(source_changes.append)
        player.playbackStateChanged.connect(lambda state: playing_sources.append(player.source())
            if state == QMediaPlayer.PlaybackState.PlayingState else None)
        def observe(*args, **kwargs):
            requests.append(args[0])
            return run_tool(*args, **kwargs)
        with patch('core.audio_effects.find_tool', side_effect=lambda name: FFMPEG if name == 'ffmpeg' else FFPROBE), \
                patch('core.audio_effects.run_tool', side_effect=observe):
            for source in sorted((ROOT / 'video').glob('*.mp4')):
                before = hashlib.sha256(source.read_bytes()).hexdigest()
                row = {'name': source.name, 'source_bytes': source.stat().st_size, 'runs': []}
                for phase in ('cold', 'cache'):
                    source_changes.clear()
                    playing_sources.clear()
                    requests.clear()
                    started = time.perf_counter()
                    controller.play_source(QUrl.fromLocalFile(str(source)))
                    assert player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
                    wait_until(lambda: not controller.switching and player.position() > 50, timeout=20)
                    elapsed = time.perf_counter() - started
                    assert playing_sources == [player.source()]
                    assert player.source() != QUrl.fromLocalFile(str(source))
                    assert player.activeVideoTrack() == 0
                    assert window.audio_output.isMuted()
                    if phase == 'cache':
                        assert requests == []
                    row['runs'].append({'phase': phase, 'wait_to_position_50ms_seconds': elapsed,
                        'source_changes': len(source_changes), 'playing_transitions': len(playing_sources),
                        'original_played': QUrl.fromLocalFile(str(source)) in playing_sources,
                        'tool_processes': len(requests), 'video_track': player.activeVideoTrack()})
                    player.stop()
                row['source_unchanged'] = before == hashlib.sha256(source.read_bytes()).hexdigest()
                assert row['source_unchanged']
                report['files'].append(row)
                print(source.name, 'cold', round(row['runs'][0]['wait_to_position_50ms_seconds'], 3),
                      'cache', round(row['runs'][1]['wait_to_position_50ms_seconds'], 3), flush=True)
                (ROOT / 'docs/audio-start/media-probe.json').write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert len(report['files']) == 8


if __name__ == '__main__':
    main()
