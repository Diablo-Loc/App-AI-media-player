"""Read-only local Qt decoder/GUI-delivery comparison; not native screen FPS."""
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from tools.ui_preview import APPLICATION, ROOT, pump
from tools.foryou_search_probe import wait_ready
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QImage, QColor
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink, QAudioOutput
import PySide6


def probe(media, before):
    if before:
        spec = importlib.util.spec_from_file_location('ui.pages.foryou_before', ROOT / 'docs/foryou-search/original/for_you.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        from ui.pages import for_you as module
    with tempfile.TemporaryDirectory(prefix='botube-playlist-probe-') as directory:
        cover = str(Path(directory) / 'cover.jpg')
        image = QImage(1280, 720, QImage.Format_RGB32)
        image.fill(QColor('#359976'))
        image.save(cover, 'JPEG')
        items = [SimpleNamespace(id=str(i), title=f'Track {i:05d}', artist='Artist',
                                 thumbnail=cover, mtime=i) for i in range(1000)]
        p = module.ForYouPage()
        player, sink, audio = QMediaPlayer(), QVideoSink(), QAudioOutput()
        audio.setVolume(0)
        player.setAudioOutput(audio)
        player.setVideoSink(sink)
        frames, beats = [], []
        sink.videoFrameChanged.connect(lambda frame: frames.append(time.perf_counter()) if frame.isValid() else None)
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: beats.append(time.perf_counter()))
        heartbeat.start()
        with patch.object(p, 'showEvent', lambda e: None):
            p.resize(1280, 820)
            p.show()
            pump(100)
            p.load_playlist(items)
            pump(300)
            player.setSource(QUrl.fromLocalFile(str(media)))
            player.play()
            for _ in range(40):
                pump(100)
                if frames:
                    break
            if not frames:
                raise RuntimeError('No decoded frame: ' + player.errorString())
            pump(1000)
            frames.clear()
            beats.clear()
            operations = []
            def search(text):
                p.search_input.setText(text)
                p.search_timer.stop()
                # Force one filter, then include asynchronous preparation/image
                # completion while still letting GUI/video events run.
                p.execute_filter()
                wait_ready(p)
            actions = [lambda: p.mark_playing_item('999'),
                       lambda: search('Track 00999'),
                       lambda: search(''),
                       lambda: p.playlist_scroll.verticalScrollBar().setValue(0),
                       lambda: p.playlist_scroll.verticalScrollBar().setValue(p.playlist_scroll.verticalScrollBar().maximum() // 2),
                       lambda: p.playlist_scroll.verticalScrollBar().setValue(p.playlist_scroll.verticalScrollBar().maximum()),
                       lambda: search('Track 00'),
                       lambda: search('')]
            start = time.perf_counter()
            for action in actions:
                op = time.perf_counter()
                action()
                operations.append((time.perf_counter() - op) * 1000)
                pump(300)
            pump(300)
            elapsed = time.perf_counter() - start
            def max_gap(values):
                return max([b - a for a, b in zip(values, values[1:])] or [0]) * 1000
            result = dict(before=before, python=platform.python_version(), pyside=PySide6.__version__,
                          qt_platform=APPLICATION.platformName(), media=media.name,
                          media_bytes=media.stat().st_size, items=1000, cover_pixels=[1280, 720],
                          decoded_frames=len(frames), elapsed_s=elapsed,
                          max_decoded_frame_delivery_gap_ms=max_gap(frames),
                          max_gui_heartbeat_gap_ms=max_gap(beats),
                          operation_ms=operations, live_cards=len(p.cards_map), player_error=player.errorString())
        heartbeat.stop()
        p.search_timer.stop()
        player.stop()
        player.setSource(QUrl())
        p.close()
        p.deleteLater()
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(3000)
        if not before:
            from ui.playlist_thumbnail_queue import thumbnail_queue
            thumbnail_queue().pool.waitForDone(3000)
        pump(100)
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--media', type=Path, required=True)
    parser.add_argument('--before', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.media.resolve(strict=True), args.before)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
