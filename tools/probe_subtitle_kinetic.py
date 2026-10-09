"""Measure each entry phase and verify old data, no native FPS inference."""
import hashlib
import json
from pathlib import Path
import statistics
import time

from tools.ui_preview import APPLICATION
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subtitle_effects import PRESETS
from ui.subtitle_kinetic import KINETIC_MODES
from subtitle.mode import SubtitleMode
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT/'docs/subtitle-kinetic'
    label = SubtitleLayer(SubtitleMode.JP_EN_VI)
    label.set_fade_enabled(False)
    label.load_subtitles([dict(start=0, end=5000, orig='優しい歌とメロディー '*5,
        en='A gentle song beneath the stars '*3, vi='Một câu hát dịu dàng trong đêm '*3)])
    label.update_position(0)
    label.resize(900, 240)
    image = QImage(label.size(), QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    results = []
    for key, title, options in PRESETS:
        if options.get('entrance') not in KINETIC_MODES:
            continue
        effect = label._subtitle_effects
        effect.configure(dict(enabled=True, **options))
        samples, tiles, paths, max_draw = [], set(), set(), 0
        cold = None
        for frame in range(132):
            pts = 24+(frame % 24)*18
            label.update_position(pts)
            effect.animation.stop()
            effect.progress = pts/480
            image.fill(Qt.GlobalColor.transparent)
            start = time.perf_counter()
            label.render(painter, QPoint())
            cost = (time.perf_counter()-start)*1000
            if frame == 0:
                cold = cost
            if frame >= 12:
                samples.append(cost)
            tiles.add(id(effect.kinetic.tiles))
            paths.add(id(label._cached_path))
            max_draw = max(max_draw, effect.kinetic.last_draw_count)
        results.append(dict(style=key, frames=len(samples), cold_ms=round(cold, 3),
            median_ms=round(statistics.median(samples), 3),
            p95_ms=round(sorted(samples)[int(len(samples)*.95)], 3), max_tiles=max_draw,
            unique_plans=len(tiles), unique_paths=len(paths)))
    painter.end()
    label.hide()
    label.deleteLater()
    report = dict(environment='Windows / Python 3.11 / Qt offscreen / DPR 1',
        logical_size=[900, 240], rows='Long wrapped JP+EN+VI, preset entry frames 24–438ms',
        results=results, limitation='Raster entry fixture, not full-app CPU/FPS/native GPU/EXE.')
    (folder/'render-probe.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    baseline = json.loads((folder/'saved-before.json').read_text(encoding='utf-8-sig'))
    checks = []
    for entry in baseline:
        path = ROOT/entry['path']
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        checks.append(dict(path=entry['path'], unchanged=current == entry['sha256']))
    saved = dict(count=len(checks), all_unchanged=all(x['unchanged'] for x in checks), files=checks)
    (folder/'saved-check.json').write_text(json.dumps(saved, indent=2), encoding='utf-8')
    print(json.dumps(results))
    print('Saved data', len(checks), saved['all_unchanged'])


if __name__ == '__main__':
    main()
