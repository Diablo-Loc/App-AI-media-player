"""Matched archived/current Qt grid and real cache-write workloads, temp-only."""
import argparse
import ast
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs/resource-performance'


def grid(mode, count, screenshot):
    from tools.ui_preview import APPLICATION, pump
    import psutil
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit
    from ui.pages.mode_manager import LibraryPage
    from core.media_library import MediaMetadata
    from ui.library_grid_view import library_grid
    from ui.media_card import MediaCard
    namespace = dict(os=os, QTimer=QTimer, QApplication=APPLICATION,
                     MediaCard=MediaCard, library_grid=library_grid)
    if mode == 'before':
        card_namespace = dict(__name__='ui._resource_baseline', __package__='ui')
        exec(compile((DEST/'original/app/ui/media_card.py').read_bytes(), 'baseline-card', 'exec'), card_namespace)
        namespace['MediaCard'] = card_namespace['MediaCard']
    source = ROOT/'app/ui/main_window.py' if mode == 'after' else DEST/'original/app/ui/main_window.py'
    tree = ast.parse(source.read_bytes())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
    for name in ('clear_grid', 'load_next_batch', 'update_media_grid'):
        method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    class Window(QWidget):
        clear_grid = namespace['clear_grid']
        load_next_batch = namespace['load_next_batch']
        update_media_grid = namespace['update_media_grid']
        def on_media_clicked(self, item):
            pass
        def sync_to_foryou(self, item):
            pass
    warm = namespace['MediaCard'](MediaMetadata('warm', '', 'Warmup'))
    warm.deleteLater()
    APPLICATION.processEvents()
    window = Window()
    window.resize(1280, 820)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    page = window.library_page = LibraryPage()
    layout.addWidget(page)
    window.content_stack = SimpleNamespace(currentWidget=lambda: page)
    window.grid_widgets = []
    window.pending_items = []
    window.search_input = QLineEdit(window)
    window.search_input.hide()
    window.show()
    pump(50)
    data = [MediaMetadata(str(i), 'absent.mp4', f'Track {i}', mtime=float(i)) for i in range(count)]
    process = psutil.Process()
    before = process.memory_info().rss
    cpu, started = time.process_time(), time.perf_counter()
    window.update_media_grid(data)
    submitted = time.perf_counter()
    end = time.monotonic()+20
    while window.pending_items and time.monotonic() < end:
        pump(5)
    assert not window.pending_items
    pump(100)
    result = dict(mode=mode, items=count, submission_ms=(submitted-started)*1000,
                  completion_ms=(time.perf_counter()-started)*1000,
                  cpu_ms=(time.process_time()-cpu)*1000,
                  rss_delta_mib=(process.memory_info().rss-before)/1048576,
                  resident_cards=len(page.grid_container.findChildren(namespace['MediaCard'])))
    if mode == 'after':
        view = page._library_grid_view
        assert view.get_playback_playlist() == data
        result['metadata_queue_items'] = len(view.get_playback_playlist())
        result['resident_cards'] = len(view.cards)
        card_ids = [card.id for card in view.cards]
        bar = page.scroll_area.verticalScrollBar()
        scroll_samples = []
        for fraction in (.25, .5, .75, 1):
            cpu, started = time.process_time(), time.perf_counter()
            bar.setValue(int(bar.maximum()*fraction))
            pump(40)
            scroll_samples.append(dict(fraction=fraction, cpu_ms=(time.process_time()-cpu)*1000,
                                       wall_ms=(time.perf_counter()-started)*1000, cards=len(view.cards)))
        assert view.cards[-1].metadata is data[-1]
        assert view.get_playback_playlist() == data
        result['scroll_samples'] = scroll_samples
        bar.setValue(0)
        pump(50)
    if screenshot:
        assert page.grab().save(str(DEST/f'library-{mode}.png'))
    window.close()
    window.deleteLater()
    pump(20)
    print(json.dumps(result))


def cache():
    sys.path.insert(0, str(ROOT/'app'))
    from core.media_library import MediaLibrary, MediaMetadata
    from thumbnail.cache_batch import ThumbnailCacheBatch
    samples = []
    with tempfile.TemporaryDirectory(prefix='botube-resource-probe-') as temporary:
        for run in range(3):
            for mode in ('before', 'after'):
                library = MediaLibrary.__new__(MediaLibrary)
                library.db_path = Path(temporary)/f'{mode}.json'
                library.lock = threading.RLock()
                library._save_lock = threading.Lock()
                library.items = {str(i): MediaMetadata(str(i), f'video/{i}.mp4', f'Track {i}') for i in range(1000)}
                writes = []
                original = library.save
                def saved():
                    original()
                    assert library._last_save_succeeded
                    writes.append(library.db_path.stat().st_size)
                batch = ThumbnailCacheBatch(library, clock=lambda: 0)
                cpu, started = time.process_time(), time.perf_counter()
                with patch.object(library, 'save', side_effect=saved):
                    for i in range(50):
                        path = f'thumbnails/{i}.jpg'
                        if mode == 'before':
                            library.update_thumbnail_in_db(str(i), path)
                        else:
                            batch.stage(str(i), path)
                    if mode == 'after':
                        batch.flush()
                samples.append(dict(mode=mode, run=run, library_items=1000, thumbnails=50,
                    saves=len(writes), serialized_records=1000*len(writes), written_bytes=sum(writes),
                    wall_ms=(time.perf_counter()-started)*1000, cpu_ms=(time.process_time()-cpu)*1000,
                    json_sha256=hashlib.sha256(library.db_path.read_bytes()).hexdigest()))
            assert (Path(temporary)/'before.json').read_bytes() == (Path(temporary)/'after.json').read_bytes()
    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--grid', choices=('before', 'after'))
    parser.add_argument('--count', type=int, default=1000)
    parser.add_argument('--screenshot', action='store_true')
    parser.add_argument('--report', default='measurements.json')
    args = parser.parse_args()
    if args.grid:
        grid(args.grid, args.count, args.screenshot)
        return
    if Path(args.report).name != args.report or not args.report.endswith('.json'):
        raise SystemExit('Report must be a JSON filename within the phase directory.')
    target = DEST/args.report
    if target.exists():
        raise SystemExit('Resource measurements already exist; do not overwrite.')
    samples = []
    for run in range(3):
        for mode in ('before', 'after'):
            command = [sys.executable, '-B', '-m', 'tools.probe_resource_performance', '--grid', mode]
            if run == 0:
                command.append('--screenshot')
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, encoding='utf-8', text=True,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1'), timeout=30, check=True)
            samples.append(dict(json.loads(completed.stdout.strip().splitlines()[-1]), run=run))
    cache_samples = cache()
    report = {'python': sys.version, 'logical_cpus': os.cpu_count(), 'grid': samples, 'cache': cache_samples,
              'production_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                  ('app/core/media_library.py', 'app/thumbnail/thumbnail_workers.py', 'app/ui/media_card.py',
                   'app/ui/main_window.py', 'app/thumbnail/cache_batch.py', 'app/ui/library_thumbnail_queue.py',
                   'app/ui/library_grid_view.py')},
              'limitations': 'Offscreen Qt, synthetic metadata, no images/native video/AI/GPU/network/EXE; CPU timer quantized.'}
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for mode in ('before', 'after'):
        rows = [row for row in samples if row['mode'] == mode]
        records = [row for row in cache_samples if row['mode'] == mode]
        print(mode, 'cards', rows[0]['resident_cards'], 'median RSS MiB', statistics.median(row['rss_delta_mib'] for row in rows),
              'median grid CPU ms', statistics.median(row['cpu_ms'] for row in rows),
              'cache saves', records[0]['saves'], 'median cache CPU ms', statistics.median(row['cpu_ms'] for row in records))


if __name__ == '__main__':
    main()
