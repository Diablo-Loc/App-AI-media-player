"""Decode quality, GUI-thread conversion, fractional DPR and cache compatibility."""
import hashlib
from math import ceil
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tools.ui_preview import APPLICATION, pump
from tools.playlist_thumbnail_probe import compare, source_fixture
from PySide6.QtCore import QEvent, QObject, QThread, QThreadPool, Qt, Slot
from PySide6.QtGui import QColor, QImage, QImageReader, QPixmap, QPixmapCache
from PySide6.QtTest import QSignalSpy
from app.ui.playlist_thumbnail import PlaylistThumbnailLoader
from app.ui.pages.for_you import LazyThumb


class PlaylistThumbnailQualityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="botube-thumb-test-")
        self.root = Path(self.directory.name)
        self.path = self.root / "source.jpg"
        source_fixture(self.path)
        self.thumb = None

    def tearDown(self):
        QThreadPool.globalInstance().waitForDone(3000)
        if self.thumb:
            QPixmapCache.remove(self.thumb.cache_key)
            self.thumb.close()
            self.thumb.deleteLater()
        pump(20)
        self.directory.cleanup()

    def make_thumb(self):
        self.thumb = LazyThumb(SimpleNamespace(thumbnail=str(self.path), mtime=123), 140, 78)
        self.thumb.show()
        # These tests drive loading explicitly; avoid an unrelated show timer.
        self.thumb._is_loaded = True
        pump(60)
        return self.thumb

    def test_real_jpeg_downsampling_is_closer_to_full_source_reference(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        old, new, reference, report = compare(self.path)
        self.assertEqual(new.size(), old.size())
        self.assertLess(report["new_mean_absolute_rgb_error"],
                        report["original_mean_absolute_rgb_error"])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_decode_uses_background_qimage_and_delivers_on_gui_thread(self):
        decode_threads = []
        deliveries = []

        class Reader(QImageReader):
            def read(self):
                decode_threads.append(QThread.currentThread())
                return super().read()

        class Receiver(QObject):
            @Slot(str, QImage)
            def receive(self, key, image):
                deliveries.append((key, image, QThread.currentThread()))

        receiver = Receiver()
        loader = PlaylistThumbnailLoader("key", str(self.path), 175, 98, 1.25)
        loader.signals.finished.connect(receiver.receive)
        pool = QThreadPool()
        with patch("app.ui.playlist_thumbnail.QImageReader", Reader):
            pool.start(loader)
            self.assertTrue(pool.waitForDone(3000))
        pump()
        self.assertEqual(len(deliveries), 1)
        self.assertNotEqual(decode_threads[0], APPLICATION.thread())
        self.assertEqual(deliveries[0][2], APPLICATION.thread())
        self.assertIsInstance(deliveries[0][1], QImage)
        self.assertEqual(deliveries[0][1].devicePixelRatio(), 1.25)

    def test_fractional_dpr_keeps_full_pixel_canvas_and_center_crop(self):
        thumb = self.make_thumb()
        source = QImage(600, 200, QImage.Format_RGB32)
        source.fill(QColor("#E00000"))
        for x in range(200, 400):
            for y in range(200):
                source.setPixelColor(x, y, QColor("#00C000"))
        for dpr in (1, 1.25, 1.5, 2):
            with self.subTest(dpr=dpr), patch.object(thumb, "devicePixelRatioF", return_value=dpr):
                source.setDevicePixelRatio(dpr)
                thumb._on_loaded(thumb.cache_key, source)
                # QLabel may normalize its getter to the actual screen DPR;
                # validate the generated backing bitmap retained in the cache.
                pixmap = QPixmapCache.find(thumb.cache_key)
                self.assertFalse(pixmap.isNull())
                self.assertEqual(pixmap.size().toTuple(), (ceil(140 * dpr), ceil(78 * dpr)))
                self.assertEqual(pixmap.devicePixelRatioF(), dpr)
                image = pixmap.toImage()
                center = image.pixelColor(image.width() // 2, image.height() // 2)
                self.assertGreater(center.green(), 180)
                self.assertLess(center.red(), 20)
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                self.assertEqual(thumb.cache_key, f"lazy_rounded_{self.path}_140x78_123")

    def test_cache_reuses_correct_dpr_and_reloads_old_monitor_resolution(self):
        thumb = self.make_thumb()
        thumb._is_loaded = False
        cached = QPixmap(140, 78)
        cached.fill(QColor("#00C000"))
        QPixmapCache.insert(thumb.cache_key, cached)
        with patch.object(thumb, "devicePixelRatioF", return_value=1), \
                patch("app.ui.pages.for_you.PlaylistThumbnailLoader") as loader:
            thumb._start_async_loading()
            loader.assert_not_called()
        with patch.object(thumb, "devicePixelRatioF", return_value=1.25):
            with patch.object(QThreadPool.globalInstance(), "start") as start:
                thumb._start_async_loading()
                start.assert_called_once()
                self.assertEqual(thumb._current_worker.target.toTuple(), (175, 98))
                thumb._current_worker.cancel()

    def test_late_wrong_key_or_dpr_cannot_replace_visible_image(self):
        thumb = self.make_thumb()
        current = QPixmap(140, 78)
        current.fill(QColor("#0000FF"))
        thumb._apply_image(current)
        stale = QImage(280, 156, QImage.Format_RGB32)
        stale.fill(QColor("#FF0000"))
        stale.setDevicePixelRatio(2)
        with patch.object(thumb, "devicePixelRatioF", return_value=1):
            thumb._on_loaded(thumb.cache_key, stale)
            thumb._on_loaded("another-item", stale)
        self.assertEqual(thumb.pixmap().cacheKey(), current.cacheKey())

    def test_small_source_is_not_upscaled_before_filter_and_cancel_is_silent(self):
        small = self.root / "small.png"
        image = QImage(32, 18, QImage.Format_RGB32)
        image.fill(QColor("#77E0BE"))
        image.save(str(small))
        sizes = []

        class Reader(QImageReader):
            def read(self):
                sizes.append(self.scaledSize())
                return super().read()

        loader = PlaylistThumbnailLoader("small", str(small), 140, 78, 1)
        spy = QSignalSpy(loader.signals.finished)
        with patch("app.ui.playlist_thumbnail.QImageReader", Reader):
            loader.run()
        self.assertEqual(spy.count(), 1)
        self.assertFalse(sizes[0].isValid())
        cancelled = PlaylistThumbnailLoader("cancel", str(self.path), 140, 78, 1)
        spy = QSignalSpy(cancelled.signals.finished)
        cancelled.cancel()
        cancelled.run()
        self.assertEqual(spy.count(), 0)

    def test_actual_screen_load_keeps_physical_resolution_in_widget(self):
        thumb = self.make_thumb()
        thumb._is_loaded = False
        thumb._start_async_loading()
        QThreadPool.globalInstance().waitForDone(3000)
        pump(120)
        cached = QPixmapCache.find(thumb.cache_key)
        self.assertIsNotNone(cached)
        dpr = thumb.devicePixelRatioF()
        expected = (ceil(140 * dpr), ceil(78 * dpr))
        self.assertEqual(cached.size().toTuple(), expected)
        self.assertEqual(cached.devicePixelRatioF(), dpr)
        self.assertFalse(thumb.pixmap().isNull())
        self.assertLessEqual(abs(thumb.pixmap().width() - expected[0]), 1)
        self.assertLessEqual(abs(thumb.pixmap().height() - expected[1]), 1)

    def test_monitor_change_requests_refresh(self):
        thumb = self.make_thumb()
        with patch("app.ui.pages.for_you.QTimer.singleShot") as schedule:
            APPLICATION.sendEvent(thumb, QEvent(QEvent.DevicePixelRatioChange))
            schedule.assert_called_once_with(50, thumb._start_async_loading)


if __name__ == "__main__":
    unittest.main()
