"""Comprehensive tests for BoTube isolated YouTube Online Studio (v6.1.0)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.ui_preview import isolated_window, pump  # Must precede MainWindow for clean Shiboken isolation

from core.youtube_online_client import (
    OnlineSubtitleCue,
    OnlineSubtitleTrack,
    OnlineVideoItem,
    OnlineWatchInfo,
    ResolvedStream,
    YouTubeOnlineClient,
    YouTubeOnlineProfileStore,
    _extract_items_from_payload,
    parse_chapters_from_description,
    parse_duration_text,
    parse_json3_subtitles,
    parse_vtt_subtitles,
    parse_youtube_input,
)
from core.youtube_online_player import OnlineAudioStreamEngine, pick_best_video_stream
from tests.test_ui_settings_and_i18n import _collect_leftover_vietnamese
from ui.i18n import set_language
from ui.pages.youtube_online_page import _YouTubeAccountDialog


class YouTubeOnlineCoreTests(unittest.TestCase):
    def test_parse_youtube_input_urls_and_ids(self):
        self.assertEqual(
            parse_youtube_input("dQw4w9WgXcQ"),
            {"kind": "video", "video_id": "dQw4w9WgXcQ"},
        )
        self.assertEqual(
            parse_youtube_input("https://youtu.be/dQw4w9WgXcQ?t=42"),
            {"kind": "video", "video_id": "dQw4w9WgXcQ", "playlist_id": ""},
        )
        self.assertEqual(
            parse_youtube_input("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ"),
            {"kind": "video", "video_id": "dQw4w9WgXcQ", "playlist_id": "RDdQw4w9WgXcQ"},
        )
        self.assertEqual(
            parse_youtube_input("https://music.youtube.com/playlist?list=PL123456"),
            {"kind": "playlist", "playlist_id": "PL123456", "url": "https://music.youtube.com/playlist?list=PL123456"},
        )
        self.assertEqual(
            parse_youtube_input("https://www.youtube.com/channel/UC-9-kyTW8ZkZNDHQJ6FgpwQ"),
            {"kind": "channel", "channel_id": "UC-9-kyTW8ZkZNDHQJ6FgpwQ", "url": "https://www.youtube.com/channel/UC-9-kyTW8ZkZNDHQJ6FgpwQ"},
        )
        self.assertIsNone(parse_youtube_input("lofi hip hop radio"))
        self.assertIsNone(parse_youtube_input("https://example.com/watch?v=dQw4w9WgXcQ"))

    def test_subtitle_parsers_json3_and_vtt(self):
        json3_payload = json.dumps({
            "events": [
                {"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "Hello &amp; world"}]},
                {"tStartMs": 2500, "dDurationMs": 2000, "segs": [{"utf8": "Second line"}]},
            ]
        })
        cues = parse_json3_subtitles(json3_payload)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "Hello & world")
        self.assertEqual(cues[0].end_ms, 2500)  # Trimmed cleanly against overlapping next cue
        self.assertEqual(cues[1].text, "Second line")

        vtt_text = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.500\n"
            "<i>Xin chào</i> BoTube\n\n"
            "00:00:04.000 --> 00:00:06.200\n"
            "Hi-Fi Online\n"
        )
        vtt_cues = parse_vtt_subtitles(vtt_text)
        self.assertEqual(len(vtt_cues), 2)
        self.assertEqual(vtt_cues[0].start_ms, 1000)
        self.assertEqual(vtt_cues[0].text, "Xin chào BoTube")
        self.assertEqual(vtt_cues[1].end_ms, 6200)

    def test_chapters_extraction_and_duration_parsing(self):
        self.assertEqual(parse_duration_text("3:45"), 225)
        self.assertEqual(parse_duration_text("1:02:05"), 3725)
        desc = "Tracklist:\n0:00 Intro\n01:30 Chorus Drop\n03:15 Acoustic Outro\n"
        chapters = parse_chapters_from_description(desc, duration_sec=240.0)
        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0].title, "Intro")
        self.assertEqual(chapters[0].end_sec, 90.0)
        self.assertEqual(chapters[2].start_sec, 195.0)
        self.assertEqual(chapters[2].end_sec, 240.0)

    def test_innertube_2026_lockup_and_video_renderer_parser(self):
        payload = {
            "contents": [
                {
                    "videoRenderer": {
                        "videoId": "488ceQWoGGw",
                        "title": {"runs": [{"text": "Nắng Ấm Xa Dần"}]},
                        "ownerText": {"runs": [{"text": "Sơn Tùng M-TP", "navigationEndpoint": {"browseEndpoint": {"browseId": "UC123"}}}]},
                        "lengthText": {"simpleText": "3:12"},
                        "shortViewCountText": {"simpleText": "60M views"},
                    }
                },
                {
                    "lockupViewModel": {
                        "contentId": "eNvUS-6PTbs",
                        "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                        "contentImage": {
                            "thumbnailViewModel": {
                                "image": {"sources": [{"url": "https://i.ytimg.com/vi/eNvUS-6PTbs/hqdefault.jpg", "width": 336}]},
                                "overlays": [{"thumbnailBottomOverlayViewModel": {"badges": [{"thumbnailBadgeViewModel": {"text": "3:46"}}]}}],
                            }
                        },
                        "metadata": {
                            "lockupMetadataViewModel": {
                                "title": {"content": "Cheri Cheri Lady"},
                                "metadata": {
                                    "contentMetadataViewModel": {
                                        "metadataRows": [
                                            {"metadataParts": [{"text": {"content": "Modern Talking"}}]},
                                            {"metadataParts": [{"text": {"content": "500M views"}}, {"text": {"content": "10 years ago"}}]},
                                        ]
                                    }
                                },
                            }
                        },
                    }
                },
            ]
        }
        items = _extract_items_from_payload(payload, limit=10)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].video_id, "488ceQWoGGw")
        self.assertEqual(items[0].duration_sec, 192)
        self.assertEqual(items[1].video_id, "eNvUS-6PTbs")
        self.assertEqual(items[1].channel_name, "Modern Talking")
        self.assertEqual(items[1].duration_text, "3:46")

    def test_stream_format_selection_prefers_opus_hifi_and_h264_mp4(self):
        fake_info = {
            "title": "Hi-Fi Demo",
            "channel": "Demo Channel",
            "channel_id": "UCdemo",
            "duration": 215,
            "formats": [
                {"url": "https://cdn/audio_aac", "acodec": "mp4a.40.2", "vcodec": "none", "abr": 128, "asr": 44100, "protocol": "https"},
                {"url": "https://cdn/audio_opus", "acodec": "opus", "vcodec": "none", "abr": 160, "asr": 48000, "protocol": "https"},
                {"url": "https://cdn/vid_1080_av1", "acodec": "none", "vcodec": "av01.0.08M", "ext": "mp4", "height": 1080, "fps": 30, "protocol": "https"},
                {"url": "https://cdn/vid_1080_h264", "acodec": "none", "vcodec": "avc1.640028", "ext": "mp4", "height": 1080, "fps": 60, "protocol": "https"},
                {"url": "https://cdn/vid_2160_vp9", "acodec": "none", "vcodec": "vp9", "ext": "webm", "height": 2160, "fps": 60, "protocol": "https"},
                {"url": "https://cdn/prog_360", "acodec": "mp4a.40.2", "vcodec": "avc1.42001E", "ext": "mp4", "height": 360, "fps": 30, "protocol": "https"},
            ],
            "subtitles": {
                "vi": [{"ext": "json3", "url": "https://cdn/sub_vi.json3", "name": "Tiếng Việt"}],
                "en": [{"ext": "vtt", "url": "https://cdn/sub_en.vtt", "name": "English"}],
            },
        }
        resolved = YouTubeOnlineClient._build_resolved_stream("dQw4w9WgXcQ", fake_info)
        self.assertEqual(resolved.audio_url, "https://cdn/audio_opus")
        self.assertEqual(resolved.audio_codec, "opus")
        self.assertEqual(resolved.audio_sr, 48000)
        self.assertEqual(resolved.video_streams["1080p"]["url"], "https://cdn/vid_1080_h264")
        self.assertEqual(resolved.video_streams["2160p"]["url"], "https://cdn/vid_2160_vp9")
        self.assertEqual([t.lang_code for t in resolved.subtitles], ["vi", "en"])

        # Closest lower quality fallback when 1440p missing
        picked_label, picked_info = pick_best_video_stream(resolved, "1440p")
        self.assertEqual(picked_label, "1080p")
        self.assertEqual(picked_info["url"], "https://cdn/vid_1080_h264")

    def test_local_profile_store_persistence_and_takeout_csv(self):
        with tempfile.TemporaryDirectory() as td:
            prof_path = Path(td) / "youtube-online-profile.json"
            store = YouTubeOnlineProfileStore(prof_path)

            self.assertTrue(store.toggle_subscription("UC1234567890", "Studio Artist"))
            self.assertTrue(store.is_subscribed("UC1234567890"))

            item = OnlineVideoItem(video_id="dQw4w9WgXcQ", title="Song A", channel_name="Studio Artist", channel_id="UC1234567890")
            self.assertTrue(store.toggle_like(item))
            self.assertTrue(store.is_liked("dQw4w9WgXcQ"))

            pl = store.create_playlist("Chill Mix", items=[item])
            self.assertEqual(len(store.list_playlists()), 1)
            self.assertFalse(store.add_item_to_playlist(pl["id"], item))  # Deduplicated

            store.record_watch(item, position_sec=42.0)
            store.record_search("hi-res acoustic")
            store.set_pref("subtitle_mode", "youtube_cc")

            csv_file = Path(td) / "subscriptions.csv"
            csv_file.write_text(
                "Channel Id,Channel Url,Channel Title\n"
                "UC1234567890,https://youtube.com/channel/UC1234567890,Studio Artist\n"
                "UC9999999999,https://youtube.com/channel/UC9999999999,New Jazz Channel\n",
                encoding="utf-8",
            )
            added = store.import_subscriptions_csv(csv_file)
            self.assertEqual(added, 1)

            # Reload from disk and verify exact atomic persistence
            reloaded = YouTubeOnlineProfileStore(prof_path)
            self.assertEqual(len(reloaded.list_subscriptions()), 2)
            self.assertTrue(reloaded.is_liked("dQw4w9WgXcQ"))
            self.assertEqual(reloaded.list_watch_history()[0].video_id, "dQw4w9WgXcQ")
            self.assertEqual(reloaded.list_search_history(), ["hi-res acoustic"])
            self.assertEqual(reloaded.get_pref("subtitle_mode"), "youtube_cc")

    def test_online_audio_engine_spawns_http_reconnect_ffmpeg(self):
        eng = OnlineAudioStreamEngine()
        eng.set_http_headers({"User-Agent": "BoTube-Test/1.0", "Referer": "https://www.youtube.com/"})
        captured = {}

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock()

        with patch("core.youtube_online_player.find_tool", return_value="ffmpeg.exe"), \
             patch("core.youtube_online_player.subprocess.Popen", side_effect=_fake_popen):
            eng._spawn_ffmpeg("https://rr1.googlevideo.com/videoplayback?id=1", 12500, 0, "anull", out_sr=48000)

        cmd = captured["cmd"]
        self.assertIn("-reconnect", cmd)
        self.assertIn("-reconnect_streamed", cmd)
        self.assertIn("-user_agent", cmd)
        self.assertIn("-ss", cmd)
        self.assertLess(cmd.index("-ss"), cmd.index("-i"))


class YouTubeOnlineUiIntegrationTests(unittest.TestCase):
    def tearDown(self):
        set_language("vi", persist=False)

    def test_isolated_tab_i18n_subtitles_download_handoff_and_mutual_exclusion(self):
        with isolated_window() as (window, _root):
            yt = window.youtube_online_page
            self.assertIsNotNone(yt)

            # 1. Navigate to YouTube tab via sidebar without disturbing offline pages (0..6)
            yt_row = window.sidebar.row_for_page("youtube_online")
            self.assertGreaterEqual(yt_row, 0)
            with patch.object(yt, "_load_home_feed"):
                window.sidebar.setCurrentRow(yt_row)
                window.handle_sidebar_click(window.sidebar.item(yt_row))
                pump(100)
            self.assertEqual(window.content_stack.currentIndex(), 7)
            self.assertTrue(window.top_toolbar_container.isHidden())

            # 2. 100% VI/EN i18n check (zero leftover Vietnamese in English mode)
            set_language("en", persist=False)
            pump(40)
            self.assertEqual(_collect_leftover_vietnamese(yt), [])
            dlg = _YouTubeAccountDialog(yt.profile, parent=yt)
            self.addCleanup(dlg.deleteLater)
            self.assertEqual(_collect_leftover_vietnamese(dlg), [])
            set_language("vi", persist=False)
            pump(30)

            # 3. Subtitle 3-mode toggle & live cue overlay (Off -> YouTube CC -> Off)
            cues = [OnlineSubtitleCue(start_ms=0, end_ms=5000, text="Hello Hi-Fi YouTube")]
            idx_cc = yt.combo_sub_mode.findData("youtube_cc")
            yt.combo_sub_mode.blockSignals(True)
            yt.combo_sub_mode.setCurrentIndex(idx_cc)
            yt.combo_sub_mode.blockSignals(False)
            yt.player.set_subtitles(cues, enabled=True)
            yt.player._sync_subtitle_for_pos(1200)
            pump(20)
            self.assertEqual(yt.lbl_sub_overlay.text(), "Hello Hi-Fi YouTube")

            idx_off = yt.combo_sub_mode.findData("off")
            yt.combo_sub_mode.setCurrentIndex(idx_off)
            pump(20)
            self.assertEqual(yt.lbl_sub_overlay.text(), "")
            self.assertTrue(yt.lbl_sub_overlay.isHidden())

            # 4. 1-Click Download Handoff populates DownloadPage cleanly with matching link/name count
            sample_item = OnlineVideoItem(
                video_id="dQw4w9WgXcQ",
                title="Rick Astley - Never Gonna Give You Up",
                channel_name="Rick Astley",
            )
            window.download_page.clear_inputs()
            yt._emit_download_item(sample_item)
            pump(40)
            self.assertEqual(window.content_stack.currentIndex(), 3)
            self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ", window.download_page.txt_links.toPlainText())
            self.assertIn("Rick Astley - Never Gonna Give You Up", window.download_page.txt_names.toPlainText())

            # 5. Mutual exclusion + hardware key routing when YouTube Online controls media
            with patch.object(yt, "is_playing_active", return_value=True), \
                 patch.object(yt, "play_next") as mock_yt_next, \
                 patch.object(window, "play_next") as mock_off_next:
                window._hw_last_skip_mono = 0.0
                window._hardware_next()
                mock_yt_next.assert_called_once()
                mock_off_next.assert_not_called()

            # Starting YouTube Online pauses offline stream
            with patch.object(window.audio_effects.stream, "pause") as mock_off_pause:
                yt.playback_starting.emit()
                mock_off_pause.assert_called_once()


if __name__ == "__main__":
    unittest.main()
