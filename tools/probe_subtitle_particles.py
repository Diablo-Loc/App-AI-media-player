"""Bounded render probe and saved-data comparison; no native FPS claims."""
import hashlib
import json
from pathlib import Path
import statistics
import time

from tools.ui_preview import APPLICATION
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subtitle_particles import TRAILS
from subtitle.mode import SubtitleMode
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]


def main(folder=None, erase_passed=False):
    folder = Path(folder) if folder is not None else ROOT/'docs/subtitle-particles'
    label = SubtitleLayer(SubtitleMode.JP_EN_VI)
    label.set_fade_enabled(False)
    label.load_subtitles([dict(start=0, end=5000,
        orig='優しい歌とメロディー ' * 5,
        en='A gentle song beneath the stars ' * 3,
        vi='Một câu hát dịu dàng trong đêm ' * 3)])
    label.update_position(0)
    label.resize(900, 240)
    image = QImage(label.size(), QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    results = []
    for style, _ in TRAILS:
        effect = label._subtitle_effects
        effect.configure(dict(enabled=True, entrance='none', color='mint', soft_fade=False,
                              trail=style, intensity='rich', erase_passed=erase_passed))
        samples, layout_ids, path_ids, max_draw = [], set(), set(), 0
        cold = None
        for frame in range(132):
            label.update_position(1000 + frame*20)
            image.fill(Qt.GlobalColor.transparent)
            start = time.perf_counter()
            label.render(painter, QPoint())
            cost = (time.perf_counter()-start)*1000
            if frame == 0:
                cold = cost
            if frame >= 12:
                samples.append(cost)
            layout_ids.add(id(effect.particles.rows))
            path_ids.add(id(label._cached_path))
            max_draw = max(max_draw, effect.particles.last_draw_count)
        results.append(dict(style=style, frames=len(samples), cold_ms=round(cold, 3),
            median_ms=round(statistics.median(samples), 3),
            p95_ms=round(sorted(samples)[int(len(samples)*.95)], 3),
            max_marks=max_draw, unique_layouts=len(layout_ids), unique_paths=len(path_ids),
            interval_ms=effect._particle_timer.interval()))
    painter.end()
    label.hide()
    label.deleteLater()
    (folder/'render-probe.json').write_text(json.dumps(dict(environment='Windows / Python 3.11 / Qt offscreen / DPR 1',
        logical_size=[900, 240], rows='JP+EN+VI, wrapped long text, rich density',
        results=results, limitation='Raster render calls including cache/layout build, not native screen FPS/GPU or full CPU.'), indent=2), encoding='utf-8')
    baseline = json.loads((folder/'saved-before.json').read_text(encoding='utf-8-sig'))
    saved = []
    for entry in baseline:
        path = ROOT/entry['path']
        current = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        saved.append(dict(path=entry['path'], unchanged=current == entry['sha256']))
    report = dict(count=len(saved), all_unchanged=all(x['unchanged'] for x in saved), files=saved)
    (folder/'saved-check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(results))
    print('Saved data', len(saved), report['all_unchanged'])


if __name__ == '__main__':
    main()
