"""Offscreen render cost and saved-data hashes; no native FPS claims."""
import hashlib
import json
from pathlib import Path
import statistics
import time

from tools.ui_preview import APPLICATION
from ui.subs_ui.subtitle_layer import SubtitleLayer
from subtitle.mode import SubtitleMode
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt, QPoint

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'docs/subtitle-effects'
    layer = SubtitleLayer(SubtitleMode.JP)
    layer.set_fade_enabled(False)
    layer.load_subtitles([dict(start=0, end=10000,
        orig='Một câu hát dịu dàng, giữ trọn từng dấu và nhịp.\n優しいメロディー')])
    layer.update_position(0)
    image = QImage(layer.size(), QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    measurements = []
    for name, options in (('off', {}), ('drop_mint', dict(enabled=True, color='mint')),
            ('all_optional', dict(enabled=True, entrance='bounce', color='pastel', glow=True, shimmer=True))):
        effect = layer._subtitle_effects
        effect.configure(options)
        layer.update_position(0)
        samples, paths = [], set()
        for frame in range(520):
            effect.animation.setCurrentTime((frame % 20) * 16)
            image.fill(Qt.GlobalColor.transparent)
            started = time.perf_counter()
            layer.render(painter, QPoint())
            elapsed = (time.perf_counter()-started)*1000
            paths.add(id(layer._cached_path))
            if frame >= 20:
                samples.append(elapsed)
        measurements.append(dict(preset=name, frames=len(samples),
            median_ms=round(statistics.median(samples), 4),
            p95_ms=round(sorted(samples)[int(len(samples)*.95)], 4),
            unique_cached_paths=len(paths), animation_loop_count=effect.animation.loopCount()))
    painter.end()
    layer.hide()
    layer.deleteLater()
    (target / 'render-probe.json').write_text(json.dumps(dict(
        environment='Windows / Python 3.11 / Qt offscreen / logical DPR 1',
        logical_size=[image.width(), image.height()], results=measurements,
        limitation='Isolated raster render call only; not playback/GPU/native FPS or total CPU.'), indent=2), encoding='utf-8')
    before = json.loads((target / 'saved-before.json').read_text())
    checks = []
    for entry in before:
        path = ROOT / entry['path']
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        checks.append(dict(path=entry['path'], unchanged=current == entry['sha256']))
    (target / 'saved-check.json').write_text(json.dumps(dict(count=len(checks),
        all_unchanged=all(x['unchanged'] for x in checks), files=checks), indent=2), encoding='utf-8')
    print(json.dumps(measurements))
    print('Saved data:', len(checks), all(x['unchanged'] for x in checks))


if __name__ == '__main__':
    main()
