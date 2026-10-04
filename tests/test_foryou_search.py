"""Actual Widgets tests for queue identity, virtual rows and decoder ownership."""
import ast
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from tools.ui_preview import APPLICATION, ROOT, isolated_window, populate, pump
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QSignalSpy, QTest
from ui.pages.for_you import ForYouPage
from ui.playlist_thumbnail import PlaylistThumbnailLoader
from ui.playlist_thumbnail_queue import thumbnail_queue


def settle_search(page, timeout_ms=3000):
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while page._playlist_view.is_busy and time.monotonic() < deadline:
        pump(10)
    if page._playlist_view.is_busy:
        raise AssertionError('Playlist loading did not complete')


class VirtualPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.page = ForYouPage()
        self.show_patch = patch.object(self.page, 'showEvent', lambda e: None)
        self.show_patch.start()
        self.page.resize(1280, 820)
        self.page.show()
        pump(30)
        self.items = [SimpleNamespace(id=str(i), title=f'Track {i:05d}', artist='Haru' if i % 2 else 'Luna',
                                      thumbnail=None, mtime=i) for i in range(10000)]
        self.page.load_playlist(self.items)
        pump(30)

    def tearDown(self):
        self.page.search_timer.stop()
        self.page.close()
        self.page.deleteLater()
        pump(30)
        self.show_patch.stop()

    def search(self, text):
        self.page.search_input.setText(text)
        self.page.execute_filter()
        settle_search(self.page)

    def test_search_clear_other_query_preserves_full_queue_identity_and_order(self):
        p = self.page
        self.search(self.items[9999].title)
        self.assertEqual(p.all_items_data, [self.items[9999]])
        p.mark_playing_item(self.items[9999].id)
        self.assertEqual(p.original_data, self.items)
        self.assertEqual(p.get_playback_playlist(), self.items)
        p.search_input.clear()  # no typing debounce; restores after preparation
        settle_search(p)
        self.assertEqual(p.all_items_data, self.items)
        self.assertEqual(p.current_playing_id, '9999')
        self.search('LUNA')
        self.assertEqual(p.all_items_data, self.items[::2])
        self.assertEqual(p.get_playback_playlist(), self.items)
        self.search('no match')
        self.assertEqual(p.all_items_data, [])
        self.assertEqual(p.master_data, self.items)

    def test_far_active_item_scroll_and_filter_keep_widget_count_bounded(self):
        p = self.page
        with patch.object(p, 'create_playlist_card', wraps=p.create_playlist_card) as create:
            p.mark_playing_item('9999')
            self.assertIn('9999', p.cards_map)
            self.assertLessEqual(len(p._playlist_view.rows), 16)
            self.assertEqual(create.call_count, 0)
            bar = p.playlist_scroll.verticalScrollBar()
            for fraction in (0, .25, .5, .75, 1, 0):
                bar.setValue(int(bar.maximum() * fraction))
                pump(30)
                self.assertLessEqual(len(p.cards_map), 16)
            self.search('Track 00001')
            p.search_input.clear()
            settle_search(p)
            self.assertEqual(create.call_count, 0)
            self.assertLessEqual(len(p._playlist_view.rows), 16)

    def test_recycled_card_click_emits_current_exact_object_and_active_style(self):
        p = self.page
        old_cards = set(p.cards_map.values())
        p.mark_playing_item('9999')
        card = p.cards_map['9999']
        self.assertIn(card, old_cards)
        spy = QSignalSpy(p.playlist_item_clicked)
        QTest.mouseClick(card, Qt.LeftButton)
        self.assertEqual(spy.count(), 1)
        self.assertIs(spy.at(0)[0], self.items[-1])
        self.assertEqual(card._playlist_title.text(), self.items[-1].title)
        self.assertIn('#19372F', card.styleSheet())

    def test_debounce_latest_query_and_empty_reload_have_no_stale_rows(self):
        p = self.page
        p.search_input.setText('Track 00001')
        p.search_input.setText('Track 00002')
        settle_search(p)
        self.assertEqual(p.all_items_data, [self.items[2]])
        p.load_playlist([])
        pump(30)
        self.assertEqual(p.master_data, [])
        self.assertEqual(p.cards_map, {})
        self.assertTrue(all(not c.isVisible() for c in p._playlist_view.rows))

    def test_reload_then_immediate_far_mark_and_viewport_resize_keep_rows_reachable(self):
        p = self.page
        p.load_playlist([])
        p.load_playlist(self.items)
        p.mark_playing_item('9999')
        pump(40)
        self.assertIn('9999', p.cards_map)
        self.assertTrue(p.cards_map['9999']._playlist_thumb.property('playlist_visible'))
        p.resize(1280, 480)
        pump(40)
        p.mark_playing_item('9999')
        self.assertTrue(p.cards_map['9999']._playlist_thumb.property('playlist_visible'))
        p.playlist_scroll.verticalScrollBar().setValue(0)
        pump(40)
        self.assertIn('0', p.cards_map)
        self.assertEqual(p.cards_map['0'].width(), p.playlist_scroll.viewport().width() - 20)

    def test_search_and_clear_show_spinner_before_work_and_swap_only_complete_results(self):
        p = self.page
        view = p._playlist_view
        old = p.all_items_data
        p.search_input.setText('Track 00002')
        self.assertTrue(view.is_busy)
        self.assertTrue(view.loading.isVisible())
        self.assertTrue(view.loading.timer.isActive())
        self.assertFalse(p.playlist_items_widget.isEnabled())
        self.assertEqual(view.loading.parentWidget(), p.playlist_scroll.viewport())
        self.assertEqual(view.loading.geometry(), p.playlist_scroll.viewport().rect())
        self.assertIs(p.all_items_data, old)
        view._check_ready()  # an obsolete readiness callback cannot reveal old rows
        self.assertTrue(view.loading.isVisible())
        p.execute_filter()
        view.chunk_timer.stop()
        view._filter_chunk()  # one chunk is not a partial result shown to the user
        self.assertIs(p.all_items_data, old)
        self.assertTrue(view.loading.isVisible())
        settle_search(p)
        self.assertEqual(p.all_items_data, [self.items[2]])
        self.assertFalse(view.loading.isVisible())
        self.assertFalse(view.loading.timer.isActive())
        self.assertTrue(p.playlist_items_widget.isEnabled())
        p.search_input.clear()
        self.assertTrue(view.is_busy)
        self.assertTrue(view.loading.isVisible())
        self.assertEqual(p.all_items_data, [self.items[2]])
        settle_search(p)
        self.assertEqual(p.all_items_data, self.items)
        self.assertEqual(p.get_playback_playlist(), self.items)
        self.assertFalse(view.loading.isVisible())
        for card in p.cards_map.values():
            self.assertEqual(card.x(), 10)
            self.assertEqual(card.width(), p.playlist_scroll.viewport().width() - 20)

    def test_superseded_preparation_and_clear_only_publish_latest_query(self):
        p = self.page
        view = p._playlist_view
        p.search_input.setText('Track 00001')
        p.execute_filter()
        generation = view.generation
        animation_start = view.loading.started
        view.chunk_timer.stop()
        view._filter_chunk()
        p.search_input.setText('Track 00003')
        self.assertGreater(view.generation, generation)
        self.assertEqual(view.loading.started, animation_start)
        p.search_input.clear()
        p.search_input.setText('Track 00004')
        settle_search(p)
        self.assertEqual(p.all_items_data, [self.items[4]])
        self.assertEqual(p.master_data, self.items)
        self.assertEqual(p.get_playback_playlist(), self.items)
        pump(60)
        self.assertEqual(p.all_items_data, [self.items[4]])
        self.assertFalse(view.is_busy)

    def test_spinner_resizes_and_stops_while_hidden_and_reload_cancels_search(self):
        p = self.page
        view = p._playlist_view
        p.search_input.setText('Track 00001')
        p.resize(1180, 500)
        pump(30)
        self.assertEqual(view.loading.geometry(), p.playlist_scroll.viewport().rect())
        self.assertTrue(view.loading.isVisible())
        p.hide()
        self.assertFalse(view.loading.timer.isActive())
        # A synchronous playlist update cancels the obsolete search transaction.
        p.load_playlist([self.items[1]])
        self.assertFalse(view.is_busy)
        pump(360)
        self.assertEqual(p.all_items_data, [self.items[1]])
        self.assertFalse(view.loading.timer.isActive())

    def test_filter_failure_keeps_old_rows_and_can_retry_without_stuck_spinner(self):
        p = self.page
        view = p._playlist_view
        old = p.all_items_data
        title = self.items[0].title
        self.items[0].title = None
        p.search_input.setText('Track 00001')
        p.execute_filter()
        settle_search(p)
        self.assertIs(p.all_items_data, old)
        self.assertFalse(view.loading.isVisible())
        self.assertIn('Không thể', p.search_input.toolTip())
        self.items[0].title = title
        p.execute_filter()
        settle_search(p)
        self.assertEqual(p.all_items_data, [self.items[1]])
        self.assertEqual(p.search_input.toolTip(), '')

    def test_loading_waits_for_visible_thumbnail_then_reveals_and_bad_image_does_not_stick(self):
        p = self.page
        view = p._playlist_view
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cover.png'
            image = QImage(640, 360, QImage.Format_RGB32)
            image.fill(QColor('#00AA00'))
            image.save(str(path))
            self.items[2].thumbnail = str(path)
            gate = threading.Event()
            original = PlaylistThumbnailLoader._decode
            def slow_decode(worker):
                gate.wait(2)
                original(worker)
            try:
                with patch.object(PlaylistThumbnailLoader, '_decode', slow_decode):
                    p.search_input.setText(self.items[2].title)
                    p.execute_filter()
                    for _ in range(40):
                        pump(10)
                        if view.job is None and view.ready_timer.isActive():
                            break
                    self.assertEqual(p.all_items_data, [self.items[2]])
                    self.assertTrue(view.loading.isVisible())
                    self.assertTrue(view.is_busy)
                    self.assertFalse(p.cards_map['2']._playlist_thumb._is_loaded)
                    gate.set()
                    settle_search(p)
                    self.assertTrue(p.cards_map['2']._playlist_thumb._is_loaded)
                    self.assertFalse(view.loading.isVisible())
            finally:
                gate.set()
                thumbnail_queue().pool.waitForDone(3000)
                pump(30)
            broken = Path(directory) / 'broken.png'
            broken.write_text('invalid image', encoding='utf-8')
            self.items[3].thumbnail = str(broken)
            p.search_input.setText(self.items[3].title)
            p.execute_filter()
            settle_search(p)
            thumb = p.cards_map['3']._playlist_thumb
            self.assertFalse(thumb._is_loaded)
            self.assertTrue(thumb._current_worker._gui_completed)
            self.assertFalse(view.loading.isVisible())


class MainWindowSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = isolated_window()
        cls.window, cls.root = cls.context.__enter__()
        cls.real_player = cls.window.media_player.player
        cls.window.media_player.player = Mock()
        cls.window.app_controller = Mock()

    @classmethod
    def tearDownClass(cls):
        cls.window.media_player.player = cls.real_player
        from ui.media_card import MediaCard
        MediaCard.thread_pool.waitForDone(3000)
        thumbnail_queue().pool.waitForDone(3000)
        pump(100)
        cls.context.__exit__(None, None, None)

    def test_search_play_clear_next_previous_use_full_playlist_without_reloading_master(self):
        window, root = self.window, self.root
        items = populate(window, root)
        for item in items:
            Path(item.path).touch()
        p = window.foryou_page
        window.content_stack.setCurrentIndex(1)
        window.app_controller = Mock()
        window.on_media_clicked(items[0])
        p.search_input.setText(items[5].title)
        p.execute_filter()
        settle_search(p)
        with patch.object(p, 'load_playlist', wraps=p.load_playlist) as reload:
            p.cards_map[items[5].id].click()
            self.assertEqual(window.active_playlist, items)
            self.assertIs(window.current_media_item, items[5])
            p.search_input.clear()
            settle_search(p)
            self.assertEqual(p.all_items_data, items)
            p.search_input.setText(items[8].title)
            p.execute_filter()
            settle_search(p)
            window.play_next()
            self.assertIs(window.current_media_item, items[6])
            window.play_previous()
            self.assertIs(window.current_media_item, items[5])
            reload.assert_not_called()
        self.assertEqual(p.master_data, items)

    def test_shuffle_while_searching_uses_full_queue_and_clear_does_not_reshuffle(self):
        window, root = self.window, self.root
        window.foryou_page.search_input.clear()
        items = populate(window, root)
        p = window.foryou_page
        window.content_stack.setCurrentIndex(1)
        p.current_playing_id = items[3].id
        p.search_input.setText('Haru')
        p.execute_filter()
        settle_search(p)
        window.toggle_global_shuffle()
        shuffled = list(window.active_playlist)
        self.assertEqual(set(i.id for i in shuffled), set(i.id for i in items))
        self.assertIs(shuffled[0], items[3])
        self.assertTrue(all(i.artist == 'Haru' for i in p.all_items_data))
        p.search_input.clear()
        settle_search(p)
        self.assertEqual(p.all_items_data, shuffled)
        self.assertEqual(window.active_playlist, shuffled)
        window.toggle_global_shuffle()
        self.assertEqual(window.active_playlist, items)
        self.assertEqual(p.all_items_data, items)


class ThumbnailBudgetTests(unittest.TestCase):
    def test_only_visible_thumbnails_decode_two_at_a_time_with_stale_scroll_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'cover.png')
            image = QImage(640, 360, QImage.Format_RGB32)
            image.fill(QColor('#00AA00'))
            image.save(path)
            p = ForYouPage()
            gate = threading.Event()
            starts = []
            original = PlaylistThumbnailLoader._decode
            def slow_decode(worker):
                starts.append(worker.cache_key)
                gate.wait(3)
                original(worker)
            try:
                with patch.object(p, 'showEvent', lambda e: None), patch.object(PlaylistThumbnailLoader, '_decode', slow_decode):
                    p.resize(1280, 820)
                    p.show()
                    pump(30)
                    items = [SimpleNamespace(id=str(i), title=str(i), artist='', thumbnail=path, mtime=i) for i in range(1000)]
                    p.load_playlist(items)
                    pump(60)
                    queue = thumbnail_queue()
                    self.assertEqual(queue.pool.maxThreadCount(), 2)
                    self.assertEqual(len(queue.active), 2)
                    self.assertEqual(len(starts), 2)
                    self.assertLessEqual(len(queue.pending), len(p.cards_map))
                    self.assertTrue(all(t.property('playlist_visible') for t in queue.pending))
                    p.playlist_scroll.verticalScrollBar().setValue(p.playlist_scroll.verticalScrollBar().maximum())
                    pump(40)
                    self.assertTrue(all(w._is_cancelled for w in queue.active))
                    gate.set()
                    queue.pool.waitForDone(3000)
                    for _ in range(20):
                        pump(20)
                        if not queue.active and not queue.pending:
                            break
                    self.assertFalse(queue.active)
                    self.assertFalse(queue.pending)
                    self.assertLess(len(starts), 20)
                    self.assertTrue(all('999' in t.cache_key or t._is_loaded
                                        for t in (c._playlist_thumb for c in p.cards_map.values())
                                        if t.property('playlist_visible')))
            finally:
                gate.set()
                p.close()
                p.deleteLater()
                thumbnail_queue().pool.waitForDone(3000)
                pump(40)

    def test_failed_cancelled_decode_always_completes_without_fake_image(self):
        for cancelled in (False, True):
            worker = PlaylistThumbnailLoader('key', 'missing.png', 140, 78, 1)
            if cancelled:
                worker.cancel()
            image_spy, done_spy = QSignalSpy(worker.signals.finished), QSignalSpy(worker.signals.done)
            worker.run()
            self.assertEqual(image_spy.count(), 0)
            self.assertEqual(done_spy.count(), 1)
            self.assertTrue(worker._completed)

    def test_decoder_quality_body_is_exactly_pre_phase(self):
        original = ast.parse((ROOT / 'docs/foryou-search/original/playlist_thumbnail.py').read_text(encoding='utf-8'))
        current = ast.parse((ROOT / 'app/ui/playlist_thumbnail.py').read_text(encoding='utf-8'))
        def method(tree, name):
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PlaylistThumbnailLoader')
            return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        old, new = method(original, 'run'), method(current, '_decode')
        self.assertEqual([ast.dump(n) for n in old.body], [ast.dump(n) for n in new.body])


if __name__ == '__main__':
    unittest.main()
