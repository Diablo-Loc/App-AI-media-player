"""Read-only source inventory and isolated resource workloads, not an FPS test.

Never instantiate the real application, AI, downloaders or persisted managers.
Each card workload uses a fresh offscreen process and the actual grid method.
Reports are new audit artifacts; previous phase manifests stay frozen.
"""
import argparse
import ast
from collections import deque
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs/performance-audit-2026-10-05'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def inventory():
    rows = []
    for path in sorted((ROOT / 'app').rglob('*.py')):
        raw = path.read_bytes()
        tree = ast.parse(raw, filename=str(path))
        compile(tree, str(path), 'exec')
        imports, candidates = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append('.' * node.level + (node.module or ''))
            elif isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if any(word in name for word in ('Timer', 'Thread', 'subprocess', 'sleep',
                        'read_bytes', 'read_text', 'save', 'collect', 'Cache', 'processEvents')):
                    candidates.append({'line': node.lineno, 'call': ast.unparse(node)[:400]})
        rows.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(),
                     'lines': len(raw.splitlines()), 'functions': sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         for n in ast.walk(tree)), 'imports': imports, 'review_candidates': candidates})
    return rows


def saved_hashes():
    paths = set()
    for folder in ('storage', 'output', 'video'):
        directory = ROOT / folder
        if directory.exists():
            paths.update(path for path in directory.rglob('*') if path.is_file())
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(paths)}


def card_workload(count):
    from tools.ui_preview import APPLICATION
    import psutil
    from PySide6.QtCore import QThread
    from PySide6.QtGui import QPixmapCache
    from PySide6.QtWidgets import QWidget, QScrollArea, QGridLayout
    from core.media_library import MediaMetadata
    from ui.media_card import MediaCard

    # Extract exactly the production method, avoiding shell/decoder construction.
    tree = ast.parse((ROOT / 'app/ui/main_window.py').read_bytes())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
    method = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'load_next_batch')
    callbacks = []
    class Scheduled:
        @staticmethod
        def singleShot(delay, callback):
            callbacks.append(callback)
    namespace = {'MediaCard': MediaCard, 'QTimer': Scheduled, 'os': os}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'actual-grid-method', 'exec'), namespace)
    class Grid(QWidget):
        load_next_batch = namespace['load_next_batch']
        def on_media_clicked(self, item):
            pass
        def sync_to_foryou(self, item):
            pass

    warm = MediaCard(MediaMetadata('warm', '', 'Warmup', thumbnail=None))
    warm.deleteLater()
    APPLICATION.processEvents()
    grid = Grid()
    grid.scroll_area = QScrollArea(grid)
    grid.scroll_area.resize(1200, 800)
    container = QWidget()
    grid.scroll_area.setWidget(container)
    grid.grid_layout = QGridLayout(container)
    grid.grid_widgets = []
    grid.pending_items = [MediaMetadata(str(i), '', f'Track {i}', thumbnail=None) for i in range(count)]
    process = psutil.Process()
    before = process.memory_info().rss
    cpu, started = time.process_time(), time.perf_counter()
    grid.load_next_batch()
    while callbacks:
        callbacks.pop(0)()
    row = {'items': count, 'cards': len(grid.grid_widgets),
           'qwidgets': len(container.findChildren(QWidget)),
           'construction_cpu_ms': (time.process_time() - cpu) * 1000,
           'construction_wall_ms': (time.perf_counter() - started) * 1000,
           'rss_delta_mib': (process.memory_info().rss - before) / (1024 * 1024),
           'rss_total_mib': process.memory_info().rss / (1024 * 1024),
           'media_card_decoder_limit': MediaCard.thread_pool.maxThreadCount(),
           'qt_ideal_threads': QThread.idealThreadCount(),
           'card_module_pixmap_cache_limit_kib': QPixmapCache.cacheLimit()}
    assert row['cards'] == count
    print(json.dumps(row))


def cache_workload():
    sys.path.insert(0, str(ROOT / 'app'))
    from core.media_library import MediaLibrary, MediaMetadata
    samples = []
    with tempfile.TemporaryDirectory(prefix='botube-perf-cache-') as temporary:
        for run in range(3):
            library = MediaLibrary.__new__(MediaLibrary)
            library.db_path = Path(temporary) / 'library.json'
            library.lock = threading.RLock()
            library._save_lock = threading.Lock()
            library.items = {str(i): MediaMetadata(str(i), f'video/{i}.mp4', f'Track {i}') for i in range(1000)}
            calls, written = [], []
            original = library.save
            def tracked():
                original()
                calls.append(1)
                written.append(library.db_path.stat().st_size)
            library.save = tracked
            cpu, start = time.process_time(), time.perf_counter()
            for index in range(50):
                library.update_thumbnail_in_db(str(index), f'thumbnails/{index}.jpg')
            old_ms, old_cpu = (time.perf_counter()-start)*1000, (time.process_time()-cpu)*1000
            expected = library.db_path.read_bytes()
            # Reference workload only: not a shipped implementation or durability test.
            for item in library.items.values():
                item.thumbnail = None
            cpu, start = time.process_time(), time.perf_counter()
            with patch.object(library, 'save', return_value=None):
                for index in range(50):
                    library.update_thumbnail_in_db(str(index), f'thumbnails/{index}.jpg')
            original()
            replay_ms, replay_cpu = (time.perf_counter()-start)*1000, (time.process_time()-cpu)*1000
            assert library.db_path.read_bytes() == expected
            samples.append({'run': run, 'library_items': 1000, 'new_thumbnails': 50,
                            'current_save_calls': len(calls), 'current_serialized_records': len(calls)*1000,
                            'current_bytes_written': sum(written), 'current_ms': old_ms, 'current_cpu_ms': old_cpu,
                            'single_final_save_reference_ms': replay_ms, 'single_final_save_reference_cpu_ms': replay_cpu,
                            'same_final_json_bytes': True})
    return samples


def native_copy_workload():
    # Importing the class does not construct/start the native DLL.
    from tools.ui_preview import APPLICATION
    from ui.system_media_manager import SystemMediaManager
    raw = (ctypes.c_float * 960)()
    pointer = ctypes.cast(raw, ctypes.POINTER(ctypes.c_float))
    owner = SimpleNamespace(_closing=False, _cb_count=0, _pending_audio=deque(maxlen=2),
                            _schedule_pending_events=lambda: None)
    samples = []
    for run in range(3):
        cpu, started = time.process_time(), time.perf_counter()
        for _ in range(10000):
            SystemMediaManager._native_audio_callback(owner, pointer, 480, 2, 48000)
            assert owner._pending_audio
            owner._pending_audio.popleft()
        samples.append({'run': run, 'callbacks': 10000, 'frames': 480, 'channels': 2,
                        'sample_rate': 48000, 'copied_bytes': 10000 * 480 * 2 * 4,
                        'cpu_ms': (time.process_time()-cpu)*1000,
                        'wall_ms': (time.perf_counter()-started)*1000})
    return {'samples': samples, 'limitations':
            'Synthetic pointer/callback only; no DLL, WASAPI capture, Qt signal dispatch or native CPU measurement.'}


def playlist_workload(count):
    from tools.ui_preview import APPLICATION, pump
    import psutil
    from PySide6.QtGui import QPixmapCache
    from ui.pages.for_you import ForYouPage
    from core.media_library import MediaMetadata
    page = ForYouPage()
    page.resize(1280, 820)
    page.show()
    pump(50)
    items = [MediaMetadata(str(i), '', f'Track {i}', thumbnail=None) for i in range(count)]
    process = psutil.Process()
    before = process.memory_info().rss
    cpu, started = time.process_time(), time.perf_counter()
    page.load_playlist(items)
    row = {'items': count, 'load_cpu_ms': (time.process_time()-cpu)*1000,
           'load_submission_ms': (time.perf_counter()-started)*1000}
    pump(50)
    row.update(realized_rows=len(page.cards_map),
               rss_delta_mib=(process.memory_info().rss-before)/(1024*1024),
               global_pixmap_cache_limit_kib=QPixmapCache.cacheLimit())
    view = page._playlist_view
    page.search_input.setText('Track 123')
    started = time.perf_counter()
    end = time.monotonic() + 5
    while view.is_busy and time.monotonic() < end:
        pump(5)
    assert not view.is_busy
    assert [item.id for item in page.all_items_data] == [item.id for item in items if 'Track 123' in item.title]
    assert len(view.playback_order) == count
    row['search_completion_ms_after_submission'] = (time.perf_counter()-started)*1000
    row['search_matches'] = len(page.all_items_data)
    row['playback_queue_items'] = len(view.playback_order)
    page.search_input.clear()
    end = time.monotonic() + 5
    while view.is_busy and time.monotonic() < end:
        pump(5)
    assert not view.is_busy and page.all_items_data == items
    row['clear_restores_full_list'] = True
    page.close()
    print(json.dumps(row))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cards', type=int)
    parser.add_argument('--native-copy', action='store_true')
    parser.add_argument('--playlist', action='store_true')
    parser.add_argument('--playlist-count', type=int)
    options = parser.parse_args()
    if options.playlist_count is not None:
        playlist_workload(options.playlist_count)
        return
    if options.playlist:
        target = DEST / 'playlist-reference.json'
        if target.exists():
            raise SystemExit('Playlist report already exists; do not overwrite.')
        samples = []
        for run in range(3):
            result = subprocess.run([sys.executable, '-B', '-m', 'tools.audit_app_performance', '--playlist-count', '10000'],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1'), timeout=20)
            samples.append(dict(json.loads(result.stdout.strip().splitlines()[-1]), run=run))
        target.write_text(json.dumps({'samples': samples,
            'limitations': 'Offscreen Qt, synthetic metadata, no images/video/audio/FPS measurement.'}, indent=2), encoding='utf-8')
        print(json.dumps(samples))
        return
    if options.native_copy:
        report = native_copy_workload()
        target = DEST / 'native-copy-reference.json'
        if target.exists():
            raise SystemExit('Reference report already exists; do not overwrite.')
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
        return
    if options.cards is not None:
        card_workload(options.cards)
        return
    if DEST.exists():
        raise SystemExit('Audit destination already exists; do not overwrite snapshots.')
    DEST.mkdir(parents=True)
    sources, saved = inventory(), saved_hashes()
    (DEST / 'sources-before.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf-8')
    (DEST / 'saved-before.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = []
    for count in (100, 500, 1000):
        for run in range(3):
            result = subprocess.run([sys.executable, '-B', '-m', 'tools.audit_app_performance', '--cards', str(count)],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1'), timeout=45)
            row = json.loads(result.stdout.strip().splitlines()[-1])
            rows.append(dict(row, run=run))
    cache = cache_workload()
    after_sources, after_saved = inventory(), saved_hashes()
    unchanged_source = sources == after_sources
    unchanged_saved = saved == after_saved
    report = {'date': '2026-10-05', 'python': sys.version, 'platform': platform.platform(),
              'logical_cpus': os.cpu_count(), 'source_count': len(sources),
              'source_lines': sum(row['lines'] for row in sources),
              'functions': sum(row['functions'] for row in sources),
              'saved_files': len(saved), 'production_sources_unchanged': unchanged_source,
              'saved_files_unchanged': unchanged_saved, 'grid_samples': rows, 'cache_samples': cache,
              'limitations': ['Synthetic metadata; no images/native video/AI/network/EXE.',
                  'Real card/grid construction, but 10ms scheduling delays skipped; not UI completion latency.',
                  'RSS delta excludes metadata setup and decoder/cache allocations.',
                  'Single-save reference is an experiment, not implemented coalescing or proof of crash durability.']}
    (DEST / 'measurements.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert unchanged_source and unchanged_saved
    print(f"{len(sources)} Python sources; {report['source_lines']} lines; {report['functions']} functions; syntax valid")
    print(f"Production unchanged; {len(saved)}/{len(saved)} saved file hashes unchanged")
    for count in (100, 500, 1000):
        samples = [row for row in rows if row['items'] == count]
        print(f"Grid {count}: median RSS delta {statistics.median(row['rss_delta_mib'] for row in samples):.2f} MiB; "
              f"construction CPU {statistics.median(row['construction_cpu_ms'] for row in samples):.2f} ms; "
              f"widgets {samples[0]['qwidgets']}; decoder threads {samples[0]['media_card_decoder_limit']}")
    print(f"Cache: 50 updates / 1000 items = 50 saves / 50000 serialized records; "
          f"median CPU {statistics.median(row['current_cpu_ms'] for row in cache):.2f} ms")


if __name__ == '__main__':
    main()
