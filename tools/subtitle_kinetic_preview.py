"""Render all kinetic presets with the actual subtitle painter (GIF at 2x slow)."""
from pathlib import Path
import subprocess

from tools.ui_preview import APPLICATION, isolated_window, pump
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subtitle_effects import PRESETS
from ui.subtitle_kinetic import KINETIC_MODES
from subtitle.mode import SubtitleMode
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT/'docs/subtitle-kinetic/screenshots'
    frames = folder/'frames'
    frames.mkdir(parents=True, exist_ok=True)
    for filename in ('msgothic.ttc', 'malgun.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+filename)
    layers = []
    for key, title, options in PRESETS:
        if options.get('entrance') not in KINETIC_MODES:
            continue
        layer = SubtitleLayer(SubtitleMode.JP_EN_VI)
        layer.set_fade_enabled(False)
        layer.current_bg_opacity = .12
        layer.update_style()
        layer.load_subtitles([dict(start=0, end=3000, orig='星と踊るメロディー',
            en='Dancing with the stars', vi='Rơi cùng những vì sao')])
        layer._subtitle_effects.configure(dict(enabled=True, **options))
        layers.append((title, layer))
    for frame in range(48):
        image = QImage(1600, 440, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('#0D121A'))
        painter = QPainter(image)
        painter.setFont(QFont('Segoe UI', 12))
        for index, (title, layer) in enumerate(layers):
            col, row = index % 4, index // 4
            painter.setPen(QColor('#A8B8CA'))
            painter.drawText(16+col*400, 28+row*220, title)
            pts = frame*20
            layer.update_position(pts)
            effect = layer._subtitle_effects
            effect.animation.setCurrentTime(min(pts, effect.animation.duration()))
            layer.render(painter, QPoint(18+col*400, 70+row*220))
        painter.end()
        image.save(str(frames/f'frame-{frame:03d}.png'))
        if frame == 12:
            image.save(str(folder/'kinetic-mid.png'))
        if frame == 32:
            image.save(str(folder/'kinetic-settled.png'))
    subprocess.run([str(ROOT/'bin/ffmpeg.exe'), '-v', 'error', '-y', '-framerate', '25',
        '-i', str(frames/'frame-%03d.png'), '-filter_complex',
        '[0:v]split[a][b];[a]palettegen[p];[b][p]paletteuse', str(folder/'kinetic.gif')],
        capture_output=True, check=True, timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _, layer in layers:
        layer.hide()
        layer.deleteLater()
    with isolated_window() as (window, root):
        window.toggle_subsettings_panel()
        panel = window.subsettings_panel
        effects = panel.effects_panel
        effects.setChecked(True)
        effects.presets.setCurrentIndex(effects.presets.findData('rain'))
        panel.settings_scroll.ensureWidgetVisible(effects.kinetic_parts)
        pump(20)
        panel.grab().save(str(folder/'settings-kinetic.png'))
        panel.hide()


if __name__ == '__main__':
    main()
