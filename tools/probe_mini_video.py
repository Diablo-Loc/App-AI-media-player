"""Read-only local-media probe; no AI, downloads or user settings writes.

Run: python -m tools.probe_mini_video --media <existing file> --output <report>
Uses actual Qt decoding with muted output and an isolated MainWindow.
"""
import argparse
import json
import platform
from pathlib import Path
from unittest.mock import Mock

from tools.ui_preview import isolated_window, pump
from core.media_library import MediaMetadata
from PySide6.QtCore import QPoint, QUrl
from PySide6.QtTest import QSignalSpy
import PySide6


def probe(path):
    with isolated_window() as (window, root):
        window.app_controller = Mock()
        window.audio_output.setVolume(0)
        player = window.media_player.player
        sink = player.videoSink()
        frames = QSignalSpy(sink.videoFrameChanged)
        item = MediaMetadata(id="local-read-only-probe", path=str(path), title="Local video probe", artist="")
        window.on_media_clicked(item)
        # An event-loop deadline bounds local decoding; it is not a speed test.
        for _ in range(30):
            if sink.videoFrame().isValid():
                break
            pump(100)
        player.pause()
        decoded = sink.videoFrame()
        video = window.video_display
        mini = window.playback_bar.video_mini_placeholder
        result = {
            "python": platform.python_version(), "pyside": PySide6.__version__,
            "platform": "Qt offscreen / Windows", "media": path.name,
            "bytes": path.stat().st_size,
            "decoded_frames": frames.count(), "first_frame_valid": decoded.isValid(),
            "video_size": list(sink.videoSize().toTuple()),
            "initial_mini_geometry": list(video.geometry().getRect()),
            "initial_surface_visible": video.isVisible(),
            "error": player.errorString(), "stale_stage_checks": [],
        }
        # Build the SAME ownership history that formerly left the stage holding
        # the shared video, then let its pending timer run after leaving For You.
        window.update_video_location("normal")
        stage = window.foryou_page.video_container
        for width, height in ((1920, 1080), (1080, 1080), (1080, 1920)):
            stage.video_width, stage.video_height = width, height
            stage.update_layout()
            window.update_video_location("mini")
            pump(30)
            stage.update_layout()
            pump(30)
            result["stale_stage_checks"].append({
                "aspect": [width, height], "geometry": list(video.geometry().getRect()),
                "contained": mini.rect().contains(video.geometry()),
                "owner_is_mini": video.parentWidget() is mini,
            })
            window.update_video_location("normal")
        window.update_video_location("mini")
        player.stop()
        player.setSource(QUrl())
        if not result["first_frame_valid"] or result["error"] or not all(
            row["contained"] and row["owner_is_mini"] for row in result["stale_stage_checks"]
        ):
            raise RuntimeError(json.dumps(result))
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    path = args.media.resolve(strict=True)
    report = probe(path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
