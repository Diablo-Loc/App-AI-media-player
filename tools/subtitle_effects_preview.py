"""Render real Qt settings and subtitle frames with isolated synthetic data."""
from pathlib import Path

from tools.ui_preview import APPLICATION, isolated_window, pump
from ui.subs_ui.subtitle_layer import SubtitleLayer
from subtitle.mode import SubtitleMode
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontDatabase

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Offscreen does not enumerate OS fallback fonts; production uses native Qt.
    for filename in ('msgothic.ttc', 'malgun.ttf'):
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / filename))
    output = ROOT / 'docs/subtitle-effects/screenshots'
    output.mkdir(parents=True, exist_ok=True)
    with isolated_window() as (window, root):
        window.toggle_subsettings_panel()
        panel = window.subsettings_panel
        panel.effects_panel.sync_options(dict(enabled=True, entrance='drop', color='mint',
                                               shimmer=True, glow=True))
        pump(20)
        panel.grab().save(str(output / 'settings-top.png'))
        panel.settings_scroll.ensureWidgetVisible(panel.effects_panel.preview_button)
        pump(20)
        panel.grab().save(str(output / 'settings-effects.png'))
        panel.hide()
    image = QImage(1120, 560, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#0D121A'))
    painter = QPainter(image)
    painter.setPen(QColor('#A8B8CA'))
    painter.setFont(QFont('Segoe UI', 12))
    presets = [('drop', 'mint'), ('rise', 'sunset'), ('zoom', 'ocean'), ('reveal', 'pastel')]
    layer = SubtitleLayer(SubtitleMode.JP)
    layer.set_fade_enabled(False)
    layer.load_subtitles([dict(start=0, end=3000, orig='Dịu dàng · 優しい歌')])
    for row, (entrance, color) in enumerate(presets):
        layer._subtitle_effects.configure(dict(enabled=True, entrance=entrance, color=color,
                                               glow=True, shimmer=True))
        layer.update_position(0)
        for col, offset in enumerate((80, 200, 320)):
            painter.drawText(20 + col*370, 25 + row*140, f'{entrance} / {color} · {offset} ms')
            layer._subtitle_effects.animation.setCurrentTime(offset)
            layer.render(painter, QPoint(18 + col*370, 50 + row*140))
    layer.hide()
    layer.deleteLater()
    painter.end()
    image.save(str(output / 'effect-frames.png'))


if __name__ == '__main__':
    main()
