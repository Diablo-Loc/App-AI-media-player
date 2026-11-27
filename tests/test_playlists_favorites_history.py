"""Comprehensive unit and headless Qt UI tests for:
- Watch History ('Lịch sử') grouped by date, bounded by max_days & max_items, deduplicated re-watches
- Favorites ('Yêu thích' ❤️) O(1) lookup, PlaybackBar toggle, synchronization
- Personal Playlists CRUD, track ordering, multi-add, queue playback
- Multi-Folder Media Sources & background deduplicated scanning
- Smart Resume / Last-Played Session state & viewport virtualization bounds
"""
from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from tools.ui_preview import isolated_window, populate, pump
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QMediaPlayer

from control.library_scan import LibraryScanQueue
from core.media_library import MediaLibrary, MediaMetadata
from core.user_collections import UserCollectionsStore
from ui.icons import HEART_COLOR, TEXT, icon


class UserCollectionsStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="botube-collections-test-")
        self.root = Path(self._tmp.name)
        self.store_file = self.root / "user_collections.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _item(self, idx: int, title: str = "", artist: str = "Artist", duration: float = 180.0) -> MediaMetadata:
        fpath = self.root / f"song_{idx}.mp4"
        if not fpath.exists():
            fpath.write_bytes(b"fake-media-bytes-" + str(idx).encode("ascii"))
        return MediaMetadata(
            id=f"id_{idx}",
            path=str(fpath),
            title=title or f"Song {idx}",
            artist=artist,
            thumbnail=None,
            duration=duration,
            mtime=1700000000.0 + idx,
        )

    def test_watch_history_date_grouping_rewatch_dedup_and_search(self):
        store = UserCollectionsStore(store_path=self.store_file)
        now_dt = datetime(2026, 11, 27, 15, 30, 0)
        today_ts = now_dt.timestamp()
        yesterday_ts = (now_dt - timedelta(days=1)).replace(hour=20, minute=15).timestamp()
        older_ts = (now_dt - timedelta(days=4)).replace(hour=9, minute=5).timestamp()

        s1 = self._item(1, "Mưa Tháng Sáu", "Văn Mai Hương")
        s2 = self._item(2, "Golden Hour", "JVKE")
        s3 = self._item(3, "Midnight City", "M83")

        store.record_history(s3, watched_at=older_ts)
        store.record_history(s2, watched_at=yesterday_ts)
        store.record_history(s1, watched_at=today_ts - 3600)

        grouped = store.get_history_grouped(today=now_dt.date())
        self.assertEqual(len(grouped), 3)
        self.assertTrue(grouped[0][0].startswith("Hôm nay — 27/11/2026"))
        self.assertTrue(grouped[1][0].startswith("Hôm qua — 26/11/2026"))
        self.assertIn("23/11/2026", grouped[2][0])

        # Re-watching s3 today moves it to top of Today and increments watch_count to 2
        s3_no_dur = MediaMetadata(id="id_3", path=s3.path, title=s3.title, artist=s3.artist, duration=0.0)
        store.record_history(s3_no_dur, watched_at=today_ts)
        self.assertEqual(store.history_count(), 3)

        grouped_after = store.get_history_grouped(today=now_dt.date())
        self.assertEqual(len(grouped_after), 2)  # Today (s3, s1) and Yesterday (s2)
        today_items = grouped_after[0][2]
        self.assertEqual([iv.media.id for iv in today_items], ["id_3", "id_1"])
        self.assertEqual(today_items[0].watch_count, 2)
        self.assertEqual(today_items[0].media.duration, 180.0)  # preserved known duration!

        # Search by title, artist, and date string
        by_artist = store.get_history_grouped(query="jvke", today=now_dt.date())
        self.assertEqual(len(by_artist), 1)
        self.assertEqual(by_artist[0][2][0].media.id, "id_2")

        by_date = store.get_history_grouped(query="26/11/2026", today=now_dt.date())
        self.assertEqual(len(by_date), 1)
        self.assertEqual(by_date[0][2][0].media.id, "id_2")

        # Remove single item & clear all
        self.assertTrue(store.remove_history_item("id_1"))
        self.assertEqual(store.history_count(), 2)
        self.assertTrue(store.clear_history())
        self.assertEqual(store.history_count(), 0)
        store.shutdown()

    def test_watch_history_dual_cap_pruning_by_days_and_items(self):
        store = UserCollectionsStore(store_path=self.store_file)
        base_ts = datetime(2026, 11, 27, 12, 0, 0).timestamp()

        # Insert 40 items spanning 40 days (1 per day)
        for day_ago in range(39, -1, -1):
            ts = base_ts - day_ago * 86400.0
            store.record_history(self._item(100 + day_ago), watched_at=ts)

        # Default cap is 30 days -> items from 31..39 days ago are pruned automatically
        self.assertLessEqual(store.history_count(), 31)

        # Tighten to 7 days and max 5 items
        store.set_history_limits(max_days=7, max_items=5, now=base_ts)
        self.assertEqual(store.history_count(), 5)
        kept_ids = [m.id for m in store.get_history_items()]
        self.assertEqual(kept_ids, ["id_100", "id_101", "id_102", "id_103", "id_104"])

        # Reload from disk preserves retention limits and pruned list
        reloaded = UserCollectionsStore(store_path=self.store_file)
        self.assertEqual(reloaded.history_max_days, 7)
        self.assertEqual(reloaded.history_max_items, 5)
        self.assertEqual([m.id for m in reloaded.get_history_items()], kept_ids)
        store.shutdown()
        reloaded.shutdown()

    def test_favorites_and_playlists_crud_and_atomic_persistence(self):
        store = UserCollectionsStore(store_path=self.store_file)
        a = self._item(1, "Track A", "Artist 1")
        b = self._item(2, "Track B", "Artist 2")
        c = self._item(3, "Track C", "Artist 3")

        # Favorites
        self.assertFalse(store.is_favorite(a.id))
        self.assertTrue(store.toggle_favorite(a))
        self.assertTrue(store.toggle_favorite(b))
        self.assertTrue(store.is_favorite(a.id))
        self.assertEqual([x.id for x in store.get_favorites()], ["id_2", "id_1"])
        self.assertFalse(store.toggle_favorite(a))
        self.assertEqual([x.id for x in store.get_favorites()], ["id_2"])

        # Playlists CRUD
        pl = store.create_playlist("  Nhạc Đêm Khuya  ")
        self.assertIsNotNone(pl)
        pid = pl["id"]
        self.assertEqual(pl["name"], "Nhạc Đêm Khuya")

        self.assertTrue(store.add_to_playlist(pid, a))
        self.assertFalse(store.add_to_playlist(pid, a))  # deduplicated
        added_bulk = store.add_many_to_playlist(pid, [a, b, c])
        self.assertEqual(added_bulk, 2)
        self.assertEqual([x.id for x in store.get_playlist_items(pid)], ["id_1", "id_2", "id_3"])

        self.assertTrue(store.move_playlist_item(pid, 2, 0))
        self.assertEqual([x.id for x in store.get_playlist_items(pid)], ["id_3", "id_1", "id_2"])

        self.assertTrue(store.rename_playlist(pid, "Chill Mix 2026"))
        self.assertEqual(store.get_playlist(pid)["name"], "Chill Mix 2026")

        self.assertTrue(store.remove_from_playlist(pid, "id_1"))
        self.assertEqual([x.id for x in store.get_playlist_items(pid)], ["id_3", "id_2"])

        # Reload from disk
        reloaded = UserCollectionsStore(store_path=self.store_file)
        self.assertTrue(reloaded.is_favorite("id_2"))
        self.assertEqual(len(reloaded.get_playlists()), 1)
        self.assertEqual(reloaded.get_playlists()[0]["name"], "Chill Mix 2026")
        self.assertEqual([x.id for x in reloaded.get_playlist_items(pid)], ["id_3", "id_2"])

        self.assertTrue(reloaded.delete_playlist(pid))
        self.assertEqual(reloaded.get_playlists(), [])
        store.shutdown()
        reloaded.shutdown()

    def test_multi_folder_dedup_legacy_sync_and_background_scan(self):
        dir_a = self.root / "FolderA"
        dir_b = self.root / "FolderB"
        dir_a.mkdir()
        dir_b.mkdir()
        f1 = dir_a / "alpha.mp3"
        f2 = dir_b / "beta.mp4"
        f1.write_bytes(b"dummy-audio-alpha-content-12345")
        f2.write_bytes(b"dummy-video-beta-content-67890")

        store = UserCollectionsStore(store_path=self.store_file)
        synced = store.sync_legacy_last_folder(str(dir_a))
        self.assertEqual(len(synced), 1)
        # Adding same folder with different casing/slashes does not duplicate
        self.assertFalse(store.add_folder(str(dir_a).upper()))
        self.assertTrue(store.add_folder(str(dir_b)))
        self.assertEqual(len(store.get_folders()), 2)

        lib = MediaLibrary(str(self.root / "lib_cache.json"))
        with patch("core.media_library.get_raw_metadata", side_effect=lambda p: (Path(p).stem, "Tester", 120.0)):
            queue = LibraryScanQueue(lib)
            results_holder = []
            queue.completed.connect(lambda items: results_holder.append(items))
            queue.request(store.get_folders())
            deadline = time.monotonic() + 5.0
            while not results_holder and time.monotonic() < deadline:
                pump(25)
            queue.shutdown()

        self.assertEqual(len(results_holder), 1)
        titles = sorted(item.title for item in results_holder[0])
        self.assertEqual(titles, ["alpha", "beta"])

        self.assertTrue(store.remove_folder(str(dir_a)))
        self.assertEqual(len(store.get_folders()), 1)
        store.shutdown()

    def test_last_played_coalesced_position_and_corrupt_file_recovery(self):
        # Corrupt file does not crash startup
        self.store_file.write_text("{corrupt-json!!", encoding="utf-8")
        store = UserCollectionsStore(store_path=self.store_file)
        self.assertEqual(store.history_count(), 0)

        track = self._item(9, "Resume Track", " Haru ")
        store.record_last_played_track(track, position_ms=0)
        store.update_last_played_position(64500)
        store.shutdown()  # flushes coalesced position immediately

        reloaded = UserCollectionsStore(store_path=self.store_file)
        lp = reloaded.get_last_played()
        self.assertIsNotNone(lp)
        self.assertEqual(lp[0].id, "id_9")
        self.assertEqual(lp[1], 64500)
        reloaded.shutdown()

    def test_top_most_played_ranking_timeframes_listen_seconds_and_history_independence(self):
        store = UserCollectionsStore(store_path=self.store_file)
        now_dt = datetime(2026, 11, 27, 16, 0, 0)
        today_ts = now_dt.timestamp()
        ten_days_ago = (now_dt - timedelta(days=10)).timestamp()
        forty_days_ago = (now_dt - timedelta(days=40)).timestamp()

        a = self._item(1, "Champion Song", "Artist A")
        b = self._item(2, "Recent Hit", "Artist B")
        c = self._item(3, "Classic Track", "Artist A")

        # Song A: 4 plays (2 forty days ago, 1 ten days ago, 1 today)
        store.record_play_stat(a, played_at=forty_days_ago)
        store.record_play_stat(a, played_at=forty_days_ago + 300)
        store.record_play_stat(a, played_at=ten_days_ago)
        store.record_play_stat(a, played_at=today_ts)
        # Song B: 3 plays all today
        for offset in (0, 60, 120):
            store.record_play_stat(b, played_at=today_ts + offset)
        # Song C: 2 plays ten days ago
        store.record_play_stat(c, played_at=ten_days_ago)
        store.record_play_stat(c, played_at=ten_days_ago + 60)

        # Accumulate real listening seconds; seek jump (>5s) must be rejected
        store.add_listen_seconds(a.id, 2.5)
        store.add_listen_seconds(a.id, 3.0)
        store.add_listen_seconds(a.id, 120.0)  # jump ignored!
        store.add_listen_seconds(b.id, 4.0)

        # All-time ranking: A (4) -> B (3) -> C (2)
        top_all = store.get_top_tracks(period="all", today=now_dt.date())
        self.assertEqual([t.media.id for t in top_all], ["id_1", "id_2", "id_3"])
        self.assertEqual([t.play_count for t in top_all], [4, 3, 2])
        self.assertEqual([t.rank for t in top_all], [1, 2, 3])
        self.assertAlmostEqual(top_all[0].total_listen_sec, 5.5, places=1)
        self.assertAlmostEqual(top_all[0].share_ratio, 1.0, places=2)
        self.assertAlmostEqual(top_all[2].share_ratio, 0.5, places=2)

        # 30-day ranking: B (3) -> A (2: today+10d) -> C (2: 10d, lower listen_sec than A)
        top_30d = store.get_top_tracks(period="30d", today=now_dt.date())
        self.assertEqual([t.media.id for t in top_30d], ["id_2", "id_1", "id_3"])
        self.assertEqual([t.play_count for t in top_30d], [3, 2, 2])

        # 7-day ranking: B (3) -> A (1), C excluded
        top_7d = store.get_top_tracks(period="7d", today=now_dt.date())
        self.assertEqual([t.media.id for t in top_7d], ["id_2", "id_1"])
        self.assertEqual([t.play_count for t in top_7d], [3, 1])

        # Summary KPIs (Artist A has 4+2=6 plays all-time, Artist B has 3)
        summary_all = store.get_listening_summary(period="all", today=now_dt.date())
        self.assertEqual(summary_all["total_plays"], 9)
        self.assertAlmostEqual(summary_all["total_listen_sec"], 9.5, places=1)
        self.assertEqual(summary_all["top_artist"], "Artist A")
        self.assertEqual(summary_all["top_artist_plays"], 6)

        # Clearing Watch History MUST NOT wipe Top Most Played stats
        store.record_history(a, watched_at=today_ts)
        store.clear_history()
        self.assertEqual(store.history_count(), 0)
        self.assertEqual(store.play_stats_count(), 3)

        # Single removal, disk reload, and reset
        self.assertTrue(store.remove_play_stat(c.id))
        store.shutdown()
        reloaded = UserCollectionsStore(store_path=self.store_file)
        self.assertEqual([t.media.id for t in reloaded.get_top_tracks(period="all", today=now_dt.date())], ["id_1", "id_2"])
        self.assertTrue(reloaded.reset_play_stats())
        self.assertEqual(reloaded.play_stats_count(), 0)
        reloaded.shutdown()

    def test_legacy_collections_without_play_stats_auto_seeds_from_history(self):
        legacy_payload = {
            "version": 1,
            "favorites": [],
            "playlists": [],
            "history": [
                {
                    "id": "legacy_1",
                    "path": str(self.root / "legacy.mp4"),
                    "title": "Legacy Song",
                    "artist": "Legacy Artist",
                    "duration": 200.0,
                    "watched_at": time.time(),
                    "date_key": datetime.now().strftime("%Y-%m-%d"),
                    "watch_count": 5,
                }
            ],
            "folders": [],
            "last_played": None,
        }
        import json
        self.store_file.write_text(json.dumps(legacy_payload), encoding="utf-8")
        store = UserCollectionsStore(store_path=self.store_file)
        top = store.get_top_tracks(period="all")
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].media.id, "legacy_1")
        self.assertEqual(top[0].play_count, 5)
        store.shutdown()


class CollectionsAndHistoryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = isolated_window()
        cls.window, cls.root = cls.context.__enter__()
        cls.items = populate(cls.window, cls.root)
        # Create real files on disk so on_media_clicked accepts them
        for item in cls.items:
            Path(item.path).write_bytes(b"synthetic-media-" + item.id.encode("utf-8"))
        pump(200)

    @classmethod
    def tearDownClass(cls):
        from ui.media_card import MediaCard
        MediaCard.thread_pool.waitForDone(3000)
        cls.context.__exit__(None, None, None)

    def test_sidebar_seven_tabs_navigation_and_compact_mode(self):
        w = self.window
        sidebar = w.sidebar
        expected = [
            ("Trang chủ", "home", 0),
            ("For You", "for_you", 1),
            ("Thư viện", "library", 2),
            ("Bộ sưu tập", "collections", 5),
            ("Lịch sử", "history", 6),
            ("Download", "download", 3),
            ("Tùy chỉnh", "settings", 4),
        ]
        self.assertEqual(sidebar.count(), 7)
        for row, (label, key, stack_idx) in enumerate(expected):
            self.assertEqual(sidebar.item(row).text(), label)
            self.assertEqual(sidebar.page_key_at(row), key)
            self.assertEqual(sidebar.row_for_page(key), row)
            self.assertFalse(sidebar.item(row).icon().isNull())

            sidebar.setCurrentRow(row)
            w.handle_sidebar_click(sidebar.item(row))
            pump(40)
            self.assertEqual(w.content_stack.currentIndex(), stack_idx)
            if stack_idx in (0, 2):
                self.assertFalse(w.top_toolbar_container.isHidden())
            else:
                self.assertTrue(w.top_toolbar_container.isHidden())

        # Mini / full mode roundtrip
        sidebar.set_mini_mode()
        self.assertTrue(all(sidebar.item(i).text() == "" for i in range(7)))
        sidebar.set_full_mode()
        self.assertEqual([sidebar.item(i).text() for i in range(7)], [e[0] for e in expected])

        # Return to Home
        sidebar.setCurrentRow(0)
        w.handle_sidebar_click(sidebar.item(0))
        pump(30)

    def test_playback_records_history_toggles_favorite_and_plays_custom_playlist(self):
        w = self.window
        store = w.user_collections
        store.clear_history()

        with patch.object(w.audio_effects, "play_source"):
            w.on_media_clicked(self.items[0])
            pump(40)
            w.on_media_clicked(self.items[1])
            pump(40)

        # History automatically recorded both tracks in reverse chronological order
        self.assertEqual(store.history_count(), 2)
        self.assertEqual([m.id for m in store.get_history_items()], [self.items[1].id, self.items[0].id])

        # Switch to History tab and verify UI rendering
        hist_row = w.sidebar.row_for_page("history")
        w.sidebar.setCurrentRow(hist_row)
        w.handle_sidebar_click(w.sidebar.item(hist_row))
        pump(60)
        self.assertFalse(w.history_page.scroll_area.isHidden())
        self.assertTrue(w.history_page.empty_card.isHidden())
        self.assertEqual(w.history_page.lbl_total_badge.text(), "2 video")

        # Toggle Favorite via PlaybackBar heart button
        self.assertFalse(store.is_favorite(self.items[1].id))
        w.playback_bar.btn_favorite.click()
        pump(30)
        self.assertTrue(store.is_favorite(self.items[1].id))
        self.assertEqual(
            w.playback_bar.btn_favorite.icon().pixmap(24, 24, QIcon.Mode.Normal).toImage(),
            icon("heart-filled", HEART_COLOR).pixmap(24, 24, QIcon.Mode.Normal).toImage(),
        )

        # Unfavorite toggles back to outline icon
        w.playback_bar.btn_favorite.click()
        pump(30)
        self.assertFalse(store.is_favorite(self.items[1].id))
        self.assertEqual(
            w.playback_bar.btn_favorite.icon().pixmap(24, 24, QIcon.Mode.Normal).toImage(),
            icon("heart", TEXT).pixmap(24, 24, QIcon.Mode.Normal).toImage(),
        )

        # Create custom playlist, add 3 tracks, open Collections tab & Play All
        created = store.create_playlist("My Top Hits")
        pid = created["id"]
        store.add_many_to_playlist(pid, [self.items[3], self.items[5], self.items[7]])

        col_row = w.sidebar.row_for_page("collections")
        w.sidebar.setCurrentRow(col_row)
        w.handle_sidebar_click(w.sidebar.item(col_row))
        w.collections_page.select_collection(pid)
        pump(60)

        self.assertEqual(w.collections_page.lbl_collection_title.text(), "My Top Hits")
        with patch.object(w.audio_effects, "play_source"):
            w.collections_page.btn_play_all.click()
            pump(40)

        self.assertEqual(w.current_media_item.id, self.items[3].id)
        self.assertEqual([x.id for x in w.active_playlist], [self.items[3].id, self.items[5].id, self.items[7].id])
        # Playing a custom playlist updates ForYouPage queue header to the playlist's name!
        self.assertEqual(w.foryou_page.lbl_pl_title.text(), "My Top Hits")
        # Live rename updates ForYouPage queue header immediately
        store.rename_playlist(pid, "Wuthering waves")
        pump(20)
        self.assertEqual(w.foryou_page.lbl_pl_title.text(), "Wuthering waves")

        # Playing from Favorites updates ForYouPage queue header to "Bài hát Yêu thích"
        store.set_favorite(self.items[1], True)
        w.collections_page.select_collection("__favorites__")
        pump(20)
        with patch.object(w.audio_effects, "play_source"):
            w.collections_page.btn_play_all.click()
            pump(20)
        self.assertEqual(w.foryou_page.lbl_pl_title.text(), "Bài hát Yêu thích")
        # Editing an unrelated custom playlist must NOT wipe Favorites header
        store.rename_playlist(pid, "Wuthering Waves OST")
        pump(20)
        self.assertEqual(w.foryou_page.lbl_pl_title.text(), "Bài hát Yêu thích")

        # Playing from History or Home resets ForYouPage queue header back to "Danh sách phát"
        w.sidebar.setCurrentRow(0)
        w.handle_sidebar_click(w.sidebar.item(0))
        pump(20)
        with patch.object(w.audio_effects, "play_source"):
            w.on_media_clicked(self.items[0])
            pump(20)
        self.assertEqual(w.foryou_page.lbl_pl_title.text(), "Danh sách phát")

    def test_history_virtualization_bounds_widget_allocation_on_240_items(self):
        w = self.window
        store = w.user_collections
        store.clear_history()
        store.set_history_limits(max_days=90, max_items=300)

        base_ts = time.time()
        for i in range(240):
            fake = MediaMetadata(
                id=f"virt_{i}",
                path=str(self.root / f"virt_{i}.mp4"),
                title=f"Virtual Track {i}",
                artist="Perf Artist",
                duration=200.0,
            )
            store.record_history(fake, watched_at=base_ts - (i * 3600))

        hist_row = w.sidebar.row_for_page("history")
        w.sidebar.setCurrentRow(hist_row)
        w.handle_sidebar_click(w.sidebar.item(hist_row))
        pump(80)

        vp = w.history_page._viewport
        self.assertEqual(store.history_count(), 240)
        # Viewport pooling must allocate only visible rows (+small buffer), never 240 widgets!
        self.assertGreater(len(vp.row_pool), 0)
        self.assertLessEqual(len(vp.row_pool), 24)

        # Scroll to middle and bottom smoothly
        sb = w.history_page.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum() // 2)
        pump(40)
        sb.setValue(sb.maximum())
        pump(40)
        self.assertLessEqual(len(vp.row_pool), 24)

    def test_smart_resume_seeks_to_saved_millisecond_position(self):
        w = self.window
        # Verify test storage is strictly isolated inside temp directory, never real repo storage/
        self.assertTrue(str(w.user_collections.store_path.resolve()).startswith(str(self.root.resolve())))

        target_item = self.items[2]
        w.current_media_item = None
        w.user_collections.record_last_played_track(target_item, position_ms=78000)
        w._restore_passive_last_played_ui()
        self.assertEqual(w.playback_bar.time_slider.value(), 78000)

        # Simulate real FFmpeg sequence: premature LoadingMedia MUST NOT consume pending seek, BufferedMedia applies it!
        with patch.object(w.audio_effects, "play_source"), patch.object(
            w.audio_effects, "sync_resume_position"
        ) as mock_audio_seek, patch.object(
            w.media_player.player, "setPosition"
        ) as mock_set_pos:
            with patch.object(w.media_player.player, "duration", return_value=215000), patch.object(
                w.media_player.player, "mediaStatus", return_value=QMediaPlayer.MediaStatus.LoadingMedia
            ):
                w.playback_bar.btn_play.click()
                pump(20)
                mock_set_pos.assert_not_called()
                self.assertEqual(w._pending_resume_seek_ms, 78000)

            with patch.object(w.media_player.player, "duration", return_value=215000), patch.object(
                w.media_player.player, "mediaStatus", return_value=QMediaPlayer.MediaStatus.BufferedMedia
            ):
                w._apply_pending_resume_seek()
                pump(20)
                mock_set_pos.assert_called_once_with(78000)
                mock_audio_seek.assert_called_once_with(78000)
                self.assertIsNone(w._pending_resume_seek_ms)
                self.assertEqual(w.playback_bar.time_slider.value(), 78000)

    def test_mini_mode_restore_preserves_toolbar_visibility_and_id_navigation(self):
        w = self.window
        # On History tab, top_toolbar_container stays hidden even after Mini -> Normal roundtrip
        hist_row = w.sidebar.row_for_page("history")
        w.sidebar.setCurrentRow(hist_row)
        w.handle_sidebar_click(w.sidebar.item(hist_row))
        pump(30)
        self.assertTrue(w.top_toolbar_container.isHidden())
        w.switch_to_mini_mode()
        pump(20)
        w.switch_to_normal_mode()
        pump(30)
        self.assertTrue(w.top_toolbar_container.isHidden())

        # _navigate_active_playlist matches by media id even if snapshot metadata changed
        a, b = self.items[0], self.items[1]
        w.active_playlist = [a, b]
        w.current_media_item = MediaMetadata(
            id=a.id, path=a.path, title=a.title, artist=a.artist, thumbnail="updated.jpg", duration=a.duration
        )
        with patch.object(w, "on_media_clicked") as mock_play:
            w.play_next()
            mock_play.assert_called_once_with(b, update_playlist=False)

        # Return cleanly to Home
        w.sidebar.setCurrentRow(0)
        w.handle_sidebar_click(w.sidebar.item(0))
        pump(20)

    def test_top_most_played_collection_ui_renders_kpis_medals_and_plays_queue(self):
        from ui.pages.playlists_page import MOST_PLAYED_COLLECTION_ID

        w = self.window
        store = w.user_collections
        store.reset_play_stats()

        def simulate_listen(item, seconds_to_listen: float, dur_override_sec: float = 20.0):
            item.duration = dur_override_sec
            with patch.object(w.audio_effects, "play_source"), patch.object(
                w.media_player.player, "playbackState", return_value=QMediaPlayer.PlaybackState.PlayingState
            ), patch.object(
                w.media_player.player, "duration", return_value=int(dur_override_sec * 1000)
            ):
                w.on_media_clicked(item)
                pos_ms = 0
                remaining = seconds_to_listen
                while remaining > 0:
                    step = min(4.0, remaining)
                    pos_ms += int(round(step * 1000))
                    w.on_position_changed(pos_ms)
                    remaining -= step

        # 1) Skipping before 50% (e.g. 6s out of 20s = 30%) or seeking to 95% MUST NOT count a play!
        simulate_listen(self.items[0], seconds_to_listen=6.0, dur_override_sec=20.0)
        with patch.object(w.audio_effects, "play_source"), patch.object(
            w.media_player.player, "playbackState", return_value=QMediaPlayer.PlaybackState.PlayingState
        ), patch.object(w.media_player.player, "duration", return_value=20000):
            w.on_media_clicked(self.items[0])
            w.on_position_changed(19000)  # Huge jump (seek) > 5s must be ignored!
        self.assertEqual(store.play_stats_count(), 0)

        # 2) Real listening > 50% (> 10s out of 20s) qualifies as 1 play AND records full listened seconds!
        for _ in range(3):
            simulate_listen(self.items[4], seconds_to_listen=12.0, dur_override_sec=20.0)
        for _ in range(2):
            simulate_listen(self.items[2], seconds_to_listen=12.0, dur_override_sec=20.0)
        simulate_listen(self.items[6], seconds_to_listen=12.0, dur_override_sec=20.0)
        pump(40)

        col_row = w.sidebar.row_for_page("collections")
        w.sidebar.setCurrentRow(col_row)
        w.handle_sidebar_click(w.sidebar.item(col_row))
        w.collections_page.select_collection(MOST_PLAYED_COLLECTION_ID)
        pump(60)

        page = w.collections_page
        self.assertEqual(page.lbl_collection_title.text(), "Top bài hát nghe nhiều nhất")
        self.assertFalse(page.top_kpi_strip.isHidden())
        self.assertFalse(page.combo_top_period.isHidden())
        self.assertIn("6", page.lbl_kpi_plays.text())
        for kpi_lbl in (page.lbl_kpi_plays, page.lbl_kpi_time, page.lbl_kpi_artist):
            self.assertGreaterEqual(kpi_lbl.contentsRect().height(), 16)
        self.assertEqual(
            [m.id for m in page.get_playback_playlist()],
            [self.items[4].id, self.items[2].id, self.items[6].id],
        )

        # Verify first visible row displays Gold #1 rank badge and "3 lượt"
        row0 = page._viewport.active.get(0)
        self.assertIsNotNone(row0)
        self.assertEqual(row0.lbl_index.text(), "#1")
        self.assertEqual(row0.lbl_play_badge.text(), "3 lượt")
        self.assertFalse(row0.top_stats_box.isHidden())

        # Play Top pushes ranked order straight into active_playlist & shows "Nghe nhiều nhất" in ForYou
        with patch.object(w.audio_effects, "play_source"):
            page.btn_play_all.click()
            pump(30)
        self.assertEqual(w.current_media_item.id, self.items[4].id)
        self.assertEqual(w.foryou_page.lbl_pl_title.text(), "Nghe nhiều nhất")
        self.assertEqual(
            [m.id for m in w.active_playlist],
            [self.items[4].id, self.items[2].id, self.items[6].id],
        )

        # Return to Home
        w.sidebar.setCurrentRow(0)
        w.handle_sidebar_click(w.sidebar.item(0))
        pump(20)

    def test_missing_file_click_preserves_current_playback_and_hidden_tabs_defer_refresh(self):
        w = self.window
        # Stay on Home (Collections and History are hidden)
        w.sidebar.setCurrentRow(0)
        w.handle_sidebar_click(w.sidebar.item(0))
        pump(20)

        valid_item = self.items[0]
        missing_item = MediaMetadata(
            id="deleted_999",
            path=str(self.root / "nonexistent_deleted_file.mp4"),
            title="Deleted Song",
            artist="Ghost",
            duration=120.0,
        )
        with patch.object(w.audio_effects, "play_source") as mock_play:
            w.on_media_clicked(valid_item)
            self.assertEqual(mock_play.call_count, 1)
            self.assertIs(w.current_media_item, valid_item)

            # Hidden tabs defer UI work until shown
            self.assertTrue(w.history_page._needs_refresh)
            self.assertTrue(w.collections_page._needs_refresh)

            # Clicking a deleted file MUST NOT overwrite current_media_item or restart audio
            w.on_media_clicked(missing_item)
            self.assertEqual(mock_play.call_count, 1)
            self.assertIs(w.current_media_item, valid_item)

        # Switching to History flushes deferred refresh immediately
        hrow = w.sidebar.row_for_page("history")
        w.sidebar.setCurrentRow(hrow)
        w.handle_sidebar_click(w.sidebar.item(hrow))
        pump(40)
        self.assertFalse(w.history_page._needs_refresh)

        # Clicking a deleted file via _play_from_collection MUST preserve active_playlist and current_media_item
        prev_queue = list(w.active_playlist)
        with patch.object(w.audio_effects, "play_source") as mock_play2:
            w._play_from_collection(missing_item, [missing_item])
            self.assertEqual(mock_play2.call_count, 0)
            self.assertIs(w.current_media_item, valid_item)
            self.assertEqual([m.id for m in w.active_playlist], [m.id for m in prev_queue])

        # Opening Audio Benchmark from Settings MUST highlight Settings row (not History row 4!)
        w.audio_effects.open_benchmark_tab(auto_run=False)
        pump(20)
        self.assertEqual(w.sidebar.currentRow(), w.sidebar.row_for_page("settings"))
        self.assertNotEqual(w.sidebar.currentRow(), w.sidebar.row_for_page("history"))
        w.audio_effects.close_benchmark_tab()
        pump(20)

        # Completing a folder scan while on Collections stays on Collections (never yanks back to Home)
        col_row = w.sidebar.row_for_page("collections")
        w.sidebar.setCurrentRow(col_row)
        w.handle_sidebar_click(w.sidebar.item(col_row))
        pump(30)
        self.assertEqual(w.content_stack.currentIndex(), 5)
        w._folder_scan_completed(list(self.items))
        pump(30)
        self.assertEqual(w.content_stack.currentIndex(), 5)

        w.sidebar.setCurrentRow(0)
        w.handle_sidebar_click(w.sidebar.item(0))
        pump(20)
        self.assertFalse(w.top_toolbar_container.isHidden())


if __name__ == "__main__":
    unittest.main()
