"""Resource bounds and compatibility using real Qt cards and temp-only caches."""
import ast
import hashlib
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.ui_preview import APPLICATION, pump
from PySide6.QtCore import QThread, QSize
from PySide6.QtGui import QImage, QColor, QPixmapCache
from PySide6.QtWidgets import QWidget
from core.media_library import MediaLibrary, MediaMetadata
from thumbnail.cache_batch import ThumbnailCacheBatch
from thumbnail.thumbnail_workers import ThumbnailWorker
from ui.pages.mode_manager import LibraryPage
from ui.library_grid_view import library_grid
from ui.library_thumbnail_queue import library_thumbnail_queue
from ui.media_card import MediaCard, ImageLoader
from ui.main_window import MainWindow  # Keep Qt wrapper modules resident across preview path patches.
from tests.resource_performance_contracts import before_resource_changes

ROOT = Path(__file__).resolve().parents[1]


def items(count):
    return [MediaMetadata(str(i), 'absent-resource-fixture.mp4', f'Track {i}', mtime=float(i)) for i in range(count)]


def bare_library(path, count):
    library = MediaLibrary.__new__(MediaLibrary)
    library.db_path = path
    library.lock = threading.RLock()
    library._save_lock = threading.Lock()
    library.items = {item.id: item for item in items(count)}
    return library


def extracted(relative, method):
    tree = ast.parse((ROOT/relative).read_bytes())
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
    node = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == method)
    namespace = {'os': os}
    exec(compile(ast.Module(body=[node], type_ignores=[]), relative, 'exec'), namespace)
    return namespace[method]


def settle_filter(view):
    import time
    deadline = time.monotonic()+2
    while (view.job is not None or view.queries) and time.monotonic() < deadline:
        pump(5)
    if view.job is not None or view.queries:
        raise AssertionError('Library filter did not complete')


class ResourceSourceGates(unittest.TestCase):
    def test_removing_only_grid_adapters_restores_entire_main_window_ast(self):
        class Restore(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                return None if node.module == 'ui.library_grid_view' else node
            def visit_Assign(self, node):
                if any(isinstance(target, ast.Name) and target.id == 'virtual' for target in node.targets):
                    return None
                return self.generic_visit(node)
            def visit_If(self, node):
                test = ast.unparse(node.test)
                if test in ('virtual is not None', "virtual is not None and getattr(self, 'grid_layout', None) is virtual.layout"):
                    return [self.visit(child) for child in node.orelse]
                if test == 'current_page is self.library_page':
                    return None
                return self.generic_visit(node)
        relative = 'app/ui/main_window.py'
        before = ast.parse((ROOT/'docs/resource-performance/original'/relative).read_bytes())
        after = Restore().visit(ast.parse((ROOT/relative).read_bytes()))
        self.assertEqual(ast.dump(after), ast.dump(before))

    def test_only_reviewed_resource_modules_change_and_helpers_are_pinned(self):
        # Derived from verified original bytes at capture time; only Git's
        # CRLF/LF conversion is accepted on checkout, never content changes.
        baseline = json.loads((ROOT/'docs/resource-performance/app-before-normalized.json').read_text())
        for relative, digest in baseline.items():
            original = before_resource_changes(relative, raw=True)
            self.assertEqual(hashlib.sha256(original.replace(b'\r\n', b'\n')).hexdigest(), digest, relative)
        helpers = json.loads((ROOT/'docs/resource-performance/helper-hash.json').read_text())
        self.assertEqual(set(helpers), {'app/thumbnail/cache_batch.py', 'app/ui/library_grid_view.py',
                                       'app/ui/library_thumbnail_queue.py'})
        for relative, digest in helpers.items():
            self.assertEqual(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(), digest, relative)

    def test_all_non_resource_main_window_and_card_methods_remain_identical(self):
        allowed = {
            'app/ui/main_window.py': {'refresh_grid', 'on_media_clicked', 'update_media_grid', 'clear_grid', 'filter_grid'},
            'app/ui/media_card.py': {'__init__', '_update_cache_key', 'paintEvent', 'update_thumbnail',
                '_start_async_loading', '_on_thumbnail_loaded', 'run'},
            'app/core/media_library.py': {'save'},
            'app/thumbnail/thumbnail_workers.py': {'run'},
        }
        for relative, methods in allowed.items():
            def functions(raw):
                tree = ast.parse(raw)
                return {(owner.name, fn.name): fn for owner in tree.body if isinstance(owner, ast.ClassDef)
                        for fn in owner.body if isinstance(fn, ast.FunctionDef)}
            before = functions((ROOT/'docs/resource-performance/original'/relative).read_bytes())
            after = functions((ROOT/relative).read_bytes())
            for key, method in before.items():
                self.assertIn(key, after)
                self.assertEqual(ast.dump(method.args), ast.dump(after[key].args), (relative, key))
                if key[1] not in methods:
                    self.assertEqual(ast.dump(method), ast.dump(after[key]), (relative, key))


class CacheBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.library = bare_library(Path(self.temp.name)/'library.json', 50)

    def tearDown(self):
        self.temp.cleanup()

    def test_fifty_changes_three_saves_and_identical_json(self):
        batch = ThumbnailCacheBatch(self.library, clock=lambda: 0)
        with patch.object(self.library, 'save', wraps=self.library.save) as save:
            for i in range(50):
                batch.stage(str(i), f'images/{i}.jpg')
            batch.flush()
            self.assertEqual(save.call_count, 3)
        expected = json.dumps({key: asdict(value) for key, value in self.library.items.items()},
                              ensure_ascii=False, indent=2).encode('utf-8')
        self.assertEqual(self.library.db_path.read_bytes(), expected.replace(b'\n', os.linesep.encode()))

    def test_old_synchronous_update_still_saves_immediately(self):
        self.library.update_thumbnail_in_db('0', 'old-api.jpg')
        self.assertEqual(json.loads(self.library.db_path.read_text())['0']['thumbnail'], 'old-api.jpg')

    def test_missing_and_unchanged_ids_do_not_make_cache_dirty(self):
        batch = ThumbnailCacheBatch(self.library)
        batch.stage('missing', 'no.jpg')
        batch.stage('0', None)
        batch.flush()
        self.assertEqual(batch.dirty, 0)
        self.assertFalse(self.library.db_path.exists())

    def test_elapsed_checkpoint_and_final_flush(self):
        clock = [0]
        batch = ThumbnailCacheBatch(self.library, clock=lambda: clock[0])
        batch.stage('0', 'a.jpg')
        clock[0] = 2.1
        batch.stage('1', 'b.jpg')
        self.assertEqual(batch.dirty, 0)
        batch.stage('2', 'c.jpg')
        batch.flush()
        self.assertEqual(json.loads(self.library.db_path.read_text())['2']['thumbnail'], 'c.jpg')

    def test_write_failure_keeps_dirty_then_retry_preserves_old_cache(self):
        self.library.save()
        before = self.library.db_path.read_bytes()
        batch = ThumbnailCacheBatch(self.library)
        batch.stage('0', 'changed.jpg')
        with patch('core.media_library.json.dump', side_effect=OSError('fixture disk error')):
            batch.flush()
        self.assertEqual(batch.dirty, 1)
        self.assertEqual(self.library.db_path.read_bytes(), before)
        batch.flush()
        self.assertEqual(batch.dirty, 0)
        self.assertEqual(json.loads(self.library.db_path.read_text())['0']['thumbnail'], 'changed.jpg')

    def test_worker_finally_flushes_on_error_and_cancel(self):
        worker = ThumbnailWorker(self.library)
        def generate(item):
            if item.id == '2':
                raise ValueError('fixture extraction error')
            return f'{item.id}.jpg'
        with patch('thumbnail.thumbnail_workers.ThumbnailManager.get_thumbnail', side_effect=generate), \
             patch.object(worker, 'msleep'):
            with self.assertRaises(ValueError):
                worker.run()
        data = json.loads(self.library.db_path.read_text())
        self.assertEqual(data['0']['thumbnail'], '0.jpg')
        self.assertEqual(data['1']['thumbnail'], '1.jpg')
        worker = ThumbnailWorker(self.library)
        def cancel_after_one(item):
            worker.cancel()
            return 'cancelled.jpg'
        with patch('thumbnail.thumbnail_workers.ThumbnailManager.get_thumbnail', side_effect=cancel_after_one), \
             patch.object(worker, 'msleep'):
            worker.run()
        self.assertEqual(json.loads(self.library.db_path.read_text())['0']['thumbnail'], 'cancelled.jpg')

    def test_parallel_snapshot_save_cannot_drop_staged_records(self):
        batch = ThumbnailCacheBatch(self.library, clock=lambda: 0)
        thread = threading.Thread(target=lambda: [self.library.save() for _ in range(8)])
        thread.start()
        for i in range(50):
            batch.stage(str(i), f'{i}.jpg')
        thread.join()
        batch.flush()
        self.assertEqual(json.loads(self.library.db_path.read_text()),
                         {key: asdict(value) for key, value in self.library.items.items()})


class LibraryGridTests(unittest.TestCase):
    def setUp(self):
        self.page = LibraryPage()
        self.page.resize(1280, 820)
        self.window = SimpleNamespace(grid_layout=self.page.grid_layout, grid_widgets=[], card_map={},
            on_media_clicked=Mock(), sync_to_foryou=Mock(), content_stack=SimpleNamespace(currentWidget=lambda: self.page))
        self.view = library_grid(self.window, self.page)
        self.page.show()
        pump(40)
        self.data = items(10000)
        self.view.load(self.data)
        pump(50)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        MediaCard.thread_pool.waitForDone()
        pump(20)

    def test_ten_thousand_metadata_only_viewport_widgets(self):
        self.assertEqual(self.view.get_playback_playlist(), self.data)
        self.assertLess(len(self.view.cards), 50)
        self.assertEqual(len(self.page.grid_container.findChildren(MediaCard)), len(self.view.cards))
        self.assertEqual(self.window.card_map, {card.id: card for card in self.window.grid_widgets})

    def test_scroll_rebinds_click_metadata_and_preserves_queue(self):
        bar = self.page.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        pump(60)
        card = self.window.grid_widgets[-1]
        self.assertIs(card.metadata, self.data[-1])
        card.clicked.emit(card.metadata)
        self.window.on_media_clicked.assert_called_once_with(self.data[-1])
        self.window.sync_to_foryou.assert_called_once_with(self.data[-1])
        self.assertEqual(self.view.get_playback_playlist(), self.data)
        self.assertLess(len(self.view.cards), 50)

    def test_search_latest_query_empty_clear_and_full_queue(self):
        self.view.filter('Track 1')
        self.view.filter('Track 987')
        settle_filter(self.view)
        self.assertEqual(self.view.visible, [item for item in self.data if 'track 987' in item.title.lower()])
        first = [item for item in self.data if 'track 1' not in item.title.lower()] + [item for item in self.data if 'track 1' in item.title.lower()]
        expected = [item for item in first if 'track 987' not in item.title.lower()] + [item for item in first if 'track 987' in item.title.lower()]
        self.assertEqual(self.view.get_playback_playlist(), expected)
        self.view.filter('not present')
        settle_filter(self.view)
        self.assertEqual(self.window.card_map, {})
        self.assertEqual(len(self.view.cards), 0)
        self.view.filter('')
        pump(40)
        self.assertEqual(self.view.visible, expected)
        self.assertLess(len(self.view.cards), 50)

    def test_hidden_resize_reload_clear_do_not_leave_old_cards(self):
        self.page.hide()
        pump(20)
        self.assertFalse(self.view.timer.isActive())
        self.page.resize(600, 500)
        self.page.show()
        pump(50)
        self.assertLess(len(self.view.cards), 20)
        new = items(3)
        self.view.load(new)
        pump(40)
        self.assertEqual([card.metadata for card in self.view.cards], new)
        self.assertTrue(all(card.width() >= 200 and card.height() == 210 for card in self.view.cards))
        self.view.clear()
        self.assertEqual(self.view.get_playback_playlist(), [])
        self.assertEqual(self.window.card_map, {})

    def test_main_window_queue_uses_all_metadata_after_search(self):
        self.view.filter('Track 987')
        settle_filter(self.view)
        MainWindow.on_media_clicked(self.window, self.view.visible[0])
        self.assertEqual(self.window.active_playlist, self.view.get_playback_playlist())
        self.assertEqual(len(self.window.active_playlist), len(self.data))

    def test_queue_order_matches_legacy_grid_with_and_without_search(self):
        page = LibraryPage()
        data = items(20)
        holder = SimpleNamespace(content_stack=SimpleNamespace(currentWidget=lambda: page), width=lambda: 1280)
        for i, item in enumerate(data):
            page.grid_layout.addWidget(MediaCard(item), i//5, i%5)
        legacy = 'docs/resource-performance/original/app/ui/main_window.py'
        extracted(legacy, 'on_media_clicked')(holder, data[0])
        self.assertEqual(holder.active_playlist, data)
        extracted(legacy, 'filter_grid')(holder, 'Track 1')
        extracted(legacy, 'on_media_clicked')(holder, data[1])
        self.view.load(data)
        self.view.filter('Track 1')
        settle_filter(self.view)
        self.assertEqual(self.view.get_playback_playlist(), holder.active_playlist)
        extracted(legacy, 'filter_grid')(holder, '')
        extracted(legacy, 'on_media_clicked')(holder, data[1])
        self.view.filter('')
        pump(50)
        self.assertEqual(self.view.visible, holder.active_playlist)
        page.deleteLater()
        pump(20)


class LibraryDecoderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.host = QWidget()
        self.host.resize(500, 300)
        self.image = QImage(640, 360, QImage.Format.Format_RGB32)
        self.image.fill(QColor('red'))
        self.path = Path(self.temp.name)/'cover.png'
        self.assertTrue(self.image.save(str(self.path)))
        item = MediaMetadata('image', '', 'Image', thumbnail=str(self.path))
        self.card = MediaCard(item, self.host)
        self.card.resize(250, 210)

    def tearDown(self):
        self.host.close()
        queue = getattr(APPLICATION, '_library_thumbnail_queue', None)
        if queue:
            queue.shutdown()
        self.host.deleteLater()
        pump(20)
        self.temp.cleanup()

    def test_qimage_worker_qpixmap_gui_and_fractional_dpr_context(self):
        with patch.object(self.card, 'devicePixelRatioF', return_value=1.5):
            self.host.show()
            pump(100)
            self.assertTrue(self.card._is_loaded)
            pixmap = QPixmapCache.find(self.card.cache_key)
            self.assertAlmostEqual(pixmap.devicePixelRatioF(), 1.5)
            self.assertIn('::1.5', self.card.cache_key)
        self.assertEqual(MediaCard.thread_pool.maxThreadCount(), 2)
        loader = ImageLoader('check', str(self.path), 100, 100)
        received = []
        loader.signals.finished.connect(lambda key, image: received.append(image))
        loader.run()
        self.assertIsInstance(received[0], QImage)
        self.assertTrue(loader._completed)

    def test_failed_decode_does_not_retry_on_each_paint_and_update_recovers(self):
        self.path.write_bytes(b'broken fixture image')
        # Count submissions instead; the real reader reports failure and completion.
        queue = library_thumbnail_queue(MediaCard.thread_pool)
        with patch.object(queue, 'submit', wraps=queue.submit) as submitted:
            self.host.show()
            pump(80)
            for _ in range(5):
                self.card.update()
                pump(10)
            self.assertEqual(submitted.call_count, 1)
            self.assertTrue(self.image.save(str(self.path)))
            self.card.update_thumbnail(str(self.path))
            pump(80)
            self.assertTrue(self.card._is_loaded)
            self.assertEqual(submitted.call_count, 2)

    def test_recycle_rejects_stale_image_and_cancel_is_nonblocking(self):
        self.host.show()
        pump(80)
        old_key = self.card.cache_key
        self.card.bind_media(MediaMetadata('new', '', 'New track'))
        self.card._on_thumbnail_loaded(old_key, self.image)
        self.assertFalse(self.card._is_loaded)
        self.assertEqual(self.card.metadata.id, 'new')
        self.card.hide()
        self.assertIsNone(self.card._current_worker)

    def test_only_two_decoders_and_shutdown_reaps_cancelled_jobs(self):
        release = threading.Event()
        lock = threading.Lock()
        counts = dict(active=0, peak=0, read=0)
        image = self.image
        class Reader:
            def __init__(self, path):
                pass
            def setAutoTransform(self, value):
                pass
            def size(self):
                return QSize(640, 360)
            def setScaledSize(self, size):
                self.target = size
            def read(self):
                with lock:
                    counts['active'] += 1
                    counts['read'] += 1
                    counts['peak'] = max(counts['peak'], counts['active'])
                release.wait(3)
                with lock:
                    counts['active'] -= 1
                return image.scaled(self.target)
        cards = [self.card]
        for i in range(7):
            card = MediaCard(MediaMetadata(str(i), '', str(i), thumbnail=str(self.path)), self.host)
            card.resize(250, 210)
            cards.append(card)
        with patch('ui.media_card.QImageReader', Reader), patch('ui.media_card.QPixmapCache.find', return_value=None):
            self.host.show()
            pump(60)
            queue = library_thumbnail_queue(MediaCard.thread_pool)
            self.assertEqual(len(queue.active), 2)
            self.assertEqual(counts['peak'], 2)
            self.assertGreater(len(queue.pending), 0)
            for card in cards:
                card.hide()
            release.set()
            queue.shutdown()
            self.assertFalse(queue.active)
            self.assertFalse(queue.pending)
            self.assertEqual(MediaCard.thread_pool.activeThreadCount(), 0)
            self.assertEqual(counts['read'], 2)

    def test_resize_invalidates_old_image_before_queued_result(self):
        self.host.show()
        pump(80)
        old_key = self.card.cache_key
        self.card.resize(350, 210)
        self.assertNotEqual(self.card.cache_key, old_key)
        self.card._on_thumbnail_loaded(old_key, self.image)
        self.assertFalse(self.card._is_loaded)
        pump(80)
        self.assertTrue(self.card._is_loaded)
        cached = QPixmapCache.find(self.card.cache_key)
        self.assertGreaterEqual(cached.width(), int(self.card.thumb_label.width()*self.card.devicePixelRatioF()))


if __name__ == '__main__':
    unittest.main()
