"""Native painter snapshots/animation of all decorative presets, synthetic cues."""
from pathlib import Path
import subprocess

from tools.ui_preview import APPLICATION, isolated_window, pump
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subtitle_effects import PRESETS, normalize_options
from subtitle.mode import SubtitleMode
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase

ROOT = Path(__file__).resolve().parents[1]


def main(output=None):
    output = Path(output) if output is not None else ROOT/'docs/subtitle-particles/screenshots'
    output.mkdir(parents=True, exist_ok=True)
    for filename in ('msgothic.ttc', 'malgun.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+filename)
    layers = []
    for name, title, options in PRESETS[1:]:
        layer = SubtitleLayer(SubtitleMode.JP_EN_VI)
        layer.set_fade_enabled(False)
        layer.current_bg_opacity = .12
        layer.update_style()
        layer.load_subtitles([dict(start=0, end=3200, orig='優しいメロディー',
                                   en='Fly with the stars', vi='Một câu hát dịu dàng')])
        layer._subtitle_effects.configure(dict(enabled=True, **options))
        layers.append((title, layer))
    frame_folder = output/'frames'
    frame_folder.mkdir(exist_ok=True)
    for frame in range(32):
        image = QImage(1200, 600, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#0D121A'))
        painter = QPainter(image)
        painter.setFont(QFont('Segoe UI', 12))
        pts = frame*100
        for index, (title, layer) in enumerate(layers):
            col, row = index % 3, index // 3
            painter.setPen(QColor('#A8B8CA'))
            painter.drawText(20+col*400, 30+row*200, title)
            layer.update_position(pts)
            layer._subtitle_effects.animation.setCurrentTime(min(pts, layer._subtitle_effects.animation.duration()))
            layer.render(painter, QPoint(20+col*400, 65+row*200))
        painter.end()
        if frame == 12:
            image.save(str(output/'presets.png'))
        image.save(str(frame_folder/f'frame-{frame:03d}.png'))
    subprocess.run([str(ROOT/'bin/ffmpeg.exe'), '-v', 'error', '-y', '-framerate', '10',
        '-i', str(frame_folder/'frame-%03d.png'), '-filter_complex',
        '[0:v]split[a][b];[a]palettegen[p];[b][p]paletteuse', str(output/'presets.gif')],
        capture_output=True, check=True, timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _, layer in layers:
        layer.hide()
        layer.deleteLater()
    with isolated_window() as (window, root):
        window.toggle_subsettings_panel()
        panel = window.subsettings_panel
        options = normalize_options(dict(enabled=True, **PRESETS[1][2]))
        panel.effects_panel.sync_options(options)
        panel.settings_scroll.ensureWidgetVisible(panel.effects_panel.intensity)
        pump(20)
        panel.grab().save(str(output/'settings-particles.png'))
        panel.hide()


if __name__ == '__main__':
    main()
