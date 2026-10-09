"""Read-only QMediaPlayer clock probe using one existing video, no audio output."""
import hashlib
import json
from pathlib import Path
import time

from tools.ui_preview import APPLICATION, pump
from ui.subs_ui.subtitle_layer import SubtitleLayer
from subtitle.mode import SubtitleMode
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

ROOT = Path(__file__).resolve().parents[1]


def main(folder=None, erase_passed=False, effects=None):
    folder = Path(folder) if folder is not None else ROOT/'docs/subtitle-particles'
    candidates = sorted((ROOT/'video').glob('*.mp4'), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise RuntimeError('No existing MP4 for read-only probe')
    source = candidates[-1]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    player, sink = QMediaPlayer(), QVideoSink()
    player.setVideoOutput(sink)
    # No QAudioOutput: this diagnostic does not play sound to the user's device.
    label = SubtitleLayer(SubtitleMode.JP)
    label.set_fade_enabled(False)
    options = dict(enabled=True, trail='shuriken', intensity='normal', erase_passed=erase_passed)
    options.update(effects or {})
    label._subtitle_effects.configure(options)
    label._subtitle_effects.bind_player(player)
    label.load_subtitles([dict(start=0, end=1200, orig='One gentle song'),
                          dict(start=1201, end=8000, orig='One gentle song')])
    player.positionChanged.connect(label.update_position)
    frames = []
    sink.videoFrameChanged.connect(lambda frame: frames.append(frame.startTime()) if frame.isValid() else None)
    samples = []
    try:
        player.setSource(QUrl.fromLocalFile(str(source)))
        player.play()
        deadline = time.monotonic()+6
        while time.monotonic() < deadline and player.position() < 2100:
            pump(40)
            samples.append(dict(media_ms=player.position(), effect_phase=label._subtitle_effects.scan_progress,
                                timer_active=label._subtitle_effects._particle_timer.isActive()))
            if player.error() != QMediaPlayer.Error.NoError:
                raise RuntimeError(player.errorString())
        if not frames or player.position() < 1500:
            raise RuntimeError('Decoder/clock did not advance')
        player.pause()
        pump(80)
        frozen = label._subtitle_effects.scan_progress
        pump(180)
        paused_ok = (frozen == label._subtitle_effects.scan_progress
                     and not label._subtitle_effects._particle_timer.isActive())
        player.setPosition(400)
        pump(120)
        seek_ok = label._subtitle_effects.cue is not None and label._subtitle_effects.cue[0] == 0
        player.setPlaybackRate(2)
        player.play()
        pump(400)
        resumed_ok = label._subtitle_effects._particle_timer.isActive()
        player.stop()
        pump(60)
        stop_ok = not label._subtitle_effects._particle_timer.isActive()
        report = dict(source=source.name, source_hash_unchanged=hashlib.sha256(source.read_bytes()).hexdigest() == digest,
            decoded_frames=len(frames), paused_frozen=paused_ok, reverse_seek=seek_ok,
            resumed_at_rate_2=resumed_ok, stopped_cleanly=stop_ok, samples=samples,
            limitation='Actual QMediaPlayer/QVideoSink in offscreen process, no screen/native audio/GPU/EXE parity claim.')
        (folder/'media-probe.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print({key: value for key, value in report.items() if key != 'samples'})
        if not all((paused_ok, seek_ok, resumed_ok, stop_ok, report['source_hash_unchanged'])):
            raise RuntimeError('Media clock validation failed')
    finally:
        player.stop()
        player.setVideoOutput(None)
        label.hide()
        player.deleteLater()
        sink.deleteLater()
        label.deleteLater()
        pump(50)


if __name__ == '__main__':
    main()
