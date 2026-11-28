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
    has_cached_ai_subtitles,
    is_bo_ai_subtitle_available,
    load_cached_ai_subtitles,
    parse_chapters_from_description,
    parse_duration_text,
    parse_json3_subtitles,
    parse_vtt_subtitles,
    parse_youtube_input,
    save_cached_ai_subtitles,
    serialize_ai_segments_to_cues,
)
from core.youtube_online_player import (
    OnlineAudioStreamEngine,
    OnlineVideoSurface,
    YouTubeOnlinePlaybackController,
    pick_best_video_stream,
)
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
            self.assertTrue(store.toggle_watch_later(item))
            self.assertTrue(store.is_in_watch_later("dQw4w9WgXcQ"))

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
            self.assertTrue(reloaded.is_in_watch_later("dQw4w9WgXcQ"))
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
        self.assertIn("-probesize", cmd)
        self.assertNotIn("+nobuffer", cmd)

    def test_ai_subtitle_disk_cache_roundtrip_and_bilingual_formatting(self):
        from subtitle.model import Subtitle, SubtitleLine
        segments = [
            Subtitle(
                start=1.25,
                end=4.5,
                top=SubtitleLine(text="Stay with me", lang="en", style="EN"),
                middle=SubtitleLine(text="Stay with me", lang="en", style="EN"),
                bottom=SubtitleLine(text="Ở lại bên anh", lang="vi", style="VI"),
            ),
            {"start": 5.0, "end": 8.0, "text": "Forever tonight", "vi": "Mãi mãi đêm nay", "en": "Forever tonight"},
        ]
        cues = serialize_ai_segments_to_cues(segments)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].start_ms, 1250)
        self.assertEqual(cues[0].end_ms, 4500)
        self.assertEqual(cues[0].orig, "Stay with me")
        self.assertEqual(cues[0].vi, "Ở lại bên anh")
        self.assertEqual(cues[1].start_ms, 5000)

        with tempfile.TemporaryDirectory() as td:
            cache_root = Path(td)
            with patch("core.youtube_online_client.online_ai_sub_cache_dir", return_value=cache_root):
                self.assertFalse(has_cached_ai_subtitles("dQw4w9WgXcQ"))
                saved_path = save_cached_ai_subtitles("dQw4w9WgXcQ", cues, title="Demo Track")
                self.assertTrue(saved_path.is_file())
                self.assertTrue(has_cached_ai_subtitles("dQw4w9WgXcQ"))
                reloaded = load_cached_ai_subtitles("dQw4w9WgXcQ")
                self.assertEqual(len(reloaded), 2)
                self.assertEqual(reloaded[0].orig, "Stay with me")
                self.assertEqual(reloaded[0].vi, "Ở lại bên anh")
                self.assertEqual(reloaded[1].en, "Forever tonight")

                # Broken legacy cache (every cue stuck at 0..200ms) is rejected cleanly
                broken = [
                    OnlineSubtitleCue(start_ms=0, end_ms=200, text="Line 1"),
                    OnlineSubtitleCue(start_ms=0, end_ms=200, text="Line 2"),
                ]
                save_cached_ai_subtitles("5d0lbdl58ME", broken, title="Broken Legacy")
                self.assertEqual(load_cached_ai_subtitles("5d0lbdl58ME"), [])

        # Verify bilingual normal + fullscreen HTML formatting
        surface = OnlineVideoSurface()
        ctrl = YouTubeOnlinePlaybackController(surface)
        try:
            ctrl._sub_display_mode = "bilingual"
            ctrl._sub_fullscreen = False
            html_norm = ctrl._format_cue_html(cues[0])
            self.assertIn("Stay with me", html_norm)
            self.assertIn("Ở lại bên anh", html_norm)
            self.assertIn("font-size:15px", html_norm)

            ctrl._sub_fullscreen = True
            html_fs = ctrl._format_cue_html(cues[0])
            self.assertIn("font-size:21px", html_fs)

            ctrl._sub_display_mode = "vi_only"
            self.assertEqual(ctrl._format_cue_html(cues[0]), "Ở lại bên anh")
            ctrl._sub_display_mode = "en_only"
            self.assertEqual(ctrl._format_cue_html(cues[0]), "Stay with me")
        finally:
            ctrl.shutdown()
            surface.deleteLater()

    def test_innertube_ios_fast_path_and_rdem_mix_playlist(self):
        client = YouTubeOnlineClient()
        fake_ios_resp = {
            "playabilityStatus": {"status": "OK"},
            "videoDetails": {
                "title": "IOS Fast MV",
                "author": "Studio Artist",
                "channelId": "UCfast123",
                "lengthSeconds": "210",
            },
            "streamingData": {
                "adaptiveFormats": [
                    {
                        "url": "https://cdn/opus_251",
                        "mimeType": 'audio/webm; codecs="opus"',
                        "bitrate": 160000,
                        "audioSampleRate": "48000",
                    },
                    {
                        "url": "https://cdn/vid_1080",
                        "mimeType": 'video/mp4; codecs="avc1.640028"',
                        "width": 1920,
                        "height": 1080,
                        "fps": 60,
                    },
                ]
            },
            "captions": {
                "playerCaptionsTracklistRenderer": {
                    "captionTracks": [
                        {
                            "languageCode": "vi",
                            "baseUrl": "https://www.youtube.com/api/timedtext?v=abc&lang=vi",
                            "name": {"simpleText": "Tiếng Việt"},
                        }
                    ]
                }
            },
        }
        fake_http = MagicMock()
        fake_http.status_code = 200
        fake_http.json.return_value = fake_ios_resp
        fake_sess = MagicMock()
        fake_sess.post.return_value = fake_http
        with patch.object(client, "_get_session", return_value=fake_sess), \
             patch.object(client, "_ensure_visitor_session", return_value="fake-visitor-id"):
            resolved = client._resolve_stream_innertube_visionos("dQw4w9WgXcQ")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.audio_url, "https://cdn/opus_251")
        self.assertEqual(resolved.video_streams["1080p"]["url"], "https://cdn/vid_1080")
        self.assertEqual(resolved.subtitles[0].lang_code, "vi")

        fake_mix_resp = {
            "contents": {
                "twoColumnWatchNextResults": {
                    "playlist": {
                        "playlist": {
                            "title": "Tổng hợp - BTS",
                            "contents": [
                                {
                                    "playlistPanelVideoRenderer": {
                                        "videoId": "_gyultVTesk",
                                        "title": {"simpleText": "BTS - Dynamite"},
                                        "lengthText": {"simpleText": "3:44"},
                                        "shortBylineText": {"runs": [{"text": "HYBE LABELS"}]},
                                    }
                                }
                            ],
                        }
                    }
                }
            }
        }
        with patch.object(client, "_innertube_post", return_value=fake_mix_resp):
            mix_title, mix_items = client._fetch_mix_via_innertube(
                "RDEMI0V0e34vA6znf4KLMCIbbQ", seed_video_id="_gyultVTesk"
            )
        self.assertEqual(mix_title, "Tổng hợp - BTS")
        self.assertEqual(len(mix_items), 1)
        self.assertEqual(mix_items[0].video_id, "_gyultVTesk")

    def test_instant_speed_and_audio_profile_reconfigure_without_video_reload(self):
        surface = OnlineVideoSurface()
        ctrl = YouTubeOnlinePlaybackController(surface)
        try:
            ctrl._stream = ResolvedStream(
                video_id="dQw4w9WgXcQ",
                title="Test",
                audio_url="https://cdn/opus",
                audio_codec="opus",
                audio_sr=48000,
                audio_abr=142.0,
                duration_sec=200.0,
            )
            ctrl._using_hifi = True
            ctrl._is_playing = True
            ctrl._is_paused = False
            mock_engine = MagicMock()
            mock_engine.position_ms.return_value = 15000
            mock_engine.start_or_reconfigure.return_value = {"output_mode": "shared", "sample_rate": 48000, "dtype": "float32"}
            ctrl._hifi_engine = mock_engine

            with patch.object(ctrl._qt_player, "setSource") as mock_set_source, \
                 patch.object(ctrl._qt_player, "setPlaybackRate") as mock_set_rate:
                ctrl.set_playback_rate(1.5)
                mock_set_source.assert_not_called()
                mock_set_rate.assert_called_once_with(1.5)
                self.assertEqual(mock_engine.start_or_reconfigure.call_count, 1)

                ctrl.reapply_audio_profile()
                mock_set_source.assert_not_called()
                self.assertEqual(mock_engine.start_or_reconfigure.call_count, 2)
        finally:
            ctrl._hifi_engine = None
            ctrl.shutdown()
            surface.deleteLater()


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
            self.assertTrue(window.sidebar_container.isHidden())
            self.assertTrue(window.playback_bar.isHidden())

            # 1b. Standalone Back-to-BoTube button restores offline sidebar & playback bar cleanly
            yt.btn_back_botube.click()
            pump(60)
            self.assertEqual(window.content_stack.currentIndex(), 0)
            self.assertFalse(window.sidebar_container.isHidden())
            self.assertFalse(window.playback_bar.isHidden())

            # Return to YouTube tab for remaining checks
            with patch.object(yt, "_load_home_feed"):
                window.sidebar.setCurrentRow(yt_row)
                window.handle_sidebar_click(window.sidebar.item(yt_row))
                pump(60)
            self.assertEqual(window.content_stack.currentIndex(), 7)
            self.assertTrue(window.sidebar_container.isHidden())

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

            # 6. True Edge-to-Edge Video Fullscreen overlays ctrl_box, blocks offline playback_bar & keeps clean cursor!
            with patch.object(yt, "_load_home_feed"):
                window.sidebar.setCurrentRow(yt_row)
                window.handle_sidebar_click(window.sidebar.item(yt_row))
                pump(40)
            yt._show_view(yt.VIEW_WATCH)
            yt._current_item = sample_item
            yt.player._stream = ResolvedStream(video_id=sample_item.video_id, title=sample_item.title)
            with patch.object(window, "showFullScreen"), patch.object(window, "showNormal"):
                yt._toggle_fullscreen_stage()
                pump(30)
                self.assertTrue(yt._is_fullscreen_stage)
                self.assertEqual(yt.stack.currentIndex(), yt.VIEW_FULLSCREEN)
                self.assertEqual(yt.ctrl_box.objectName(), "ytWatchControlsFS")
                self.assertEqual(yt.lbl_sub_overlay.objectName(), "ytSubOverlayFS")
                self.assertTrue(yt.player._sub_fullscreen)
                # Offline MainWindow show_controls/hide_controls must NEVER leak playback_bar or BlankCursor!
                window.show_controls()
                self.assertTrue(window.playback_bar.isHidden())
                window.hide_controls()
                self.assertNotEqual(window.cursor().shape(), window.cursor().shape().BlankCursor)
                yt._update_mini_bar_visibility()
                self.assertTrue(yt.mini_bar.isHidden())

                yt.exit_fullscreen_stage()
                pump(30)
                self.assertFalse(yt._is_fullscreen_stage)
                self.assertEqual(yt.stack.currentIndex(), yt.VIEW_WATCH)
                self.assertEqual(yt.ctrl_box.objectName(), "ytWatchControls")
                self.assertEqual(yt._watch_left_lay.indexOf(yt.stage_frame), 0)
                self.assertEqual(yt._watch_left_lay.indexOf(yt.ctrl_box), 1)
                self.assertEqual(yt.lbl_sub_overlay.objectName(), "ytSubOverlay")
                self.assertFalse(yt.player._sub_fullscreen)

            # 6b. Isolated Floating PiP Mini-Player + BoTube Signature Dynamic Island Pill
            yt.toggle_mini_player()
            pump(30)
            self.assertTrue(yt._is_pip_mode)
            self.assertIsNotNone(yt._pip_window)
            self.assertEqual(yt._pip_window.stage_lay.indexOf(yt.stage_frame), 0)
            yt.exit_mini_player()
            pump(30)
            self.assertFalse(yt._is_pip_mode)
            self.assertEqual(yt._watch_left_lay.indexOf(yt.stage_frame), 0)

            yt.toggle_pill_mode()
            pump(30)
            self.assertTrue(yt._is_pill_mode)
            self.assertIsNotNone(yt._pill_window)
            yt.exit_pill_mode()
            pump(30)
            self.assertFalse(yt._is_pill_mode)

            # 6c. 3-mode Subtitle dropdown (Off / YouTube CC / ✨ AI BoTube) + conditional BoTube Subtitle Style button
            self.assertEqual(yt.combo_sub_mode.count(), 3)
            self.assertEqual(yt.combo_sub_mode.itemData(0), "off")
            self.assertEqual(yt.combo_sub_mode.itemData(1), "youtube_cc")
            self.assertEqual(yt.combo_sub_mode.itemData(2), "ai_botube")
            yt.combo_sub_mode.setCurrentIndex(yt.combo_sub_mode.findData("off"))
            pump(15)
            self.assertTrue(yt.btn_sub_style.isHidden())
            yt.combo_sub_mode.setCurrentIndex(yt.combo_sub_mode.findData("youtube_cc"))
            pump(15)
            self.assertTrue(yt.btn_sub_style.isHidden())

            # 6d. AI-disabled gray-out & auto-run ✨ AI BoTube on new uncached video when enabled
            yt.profile.set_pref("allow_ai_sub", False)
            yt.refresh_ai_availability()
            self.assertFalse(yt.btn_ai_sub_gen.isEnabled())
            self.assertFalse(yt.combo_sub_mode.model().item(2).isEnabled())
            self.assertTrue(yt.btn_sub_style.isHidden())
            yt.profile.set_pref("allow_ai_sub", True)
            with patch("core.youtube_online_client.is_bo_ai_subtitle_available", return_value=(True, "ready")), \
                 patch("ui.pages.youtube_online_page.is_bo_ai_subtitle_available", return_value=(True, "ready")):
                yt.refresh_ai_availability()
                self.assertTrue(yt.btn_ai_sub_gen.isEnabled())
                self.assertTrue(yt.combo_sub_mode.model().item(2).isEnabled())
                idx_ai = yt.combo_sub_mode.findData("ai_botube")
                yt.combo_sub_mode.blockSignals(True)
                yt.combo_sub_mode.setCurrentIndex(idx_ai)
                yt.combo_sub_mode.blockSignals(False)
                with patch.object(yt.player, "load_and_play"), \
                     patch("ui.pages.youtube_online_page.load_cached_ai_subtitles", return_value=[]), \
                     patch.object(yt, "_start_ai_subtitle_generation") as mock_auto_ai:
                    yt._on_stream_resolved(ResolvedStream(video_id=sample_item.video_id, title=sample_item.title))
                    mock_auto_ai.assert_called_once_with(force_regen=False)
                self.assertFalse(yt.btn_sub_style.isHidden())

            # 6e. Real BoTube SubtitleLayer sync + Audio Panel live status + Benchmark handoff AFTER stack switch!
            from subtitle.mode import SubtitleMode
            yt.apply_subtitle_style({
                "mode": "jp_vi",
                "font_size": 28,
                "font_color": "#FEF08A",
                "bg_color": "#000000",
                "bg_opacity": 0.6,
                "phonetic_enabled": True,
                "outline_enabled": True,
                "outline_width": 3,
            })
            self.assertEqual(yt.yt_sub_layer.mode, SubtitleMode.JP_VI)
            self.assertEqual(yt.yt_sub_layer.current_color, "#FEF08A")
            self.assertTrue(yt.yt_sub_layer.phonetic_enabled)
            yt.sync_to_audio_panel(window.audio_effects.panel)
            self.assertIn("YouTube", window.audio_effects.panel.signal_path.text())
            # Simulate real click order: panel opens on YouTube -> open_benchmark_tab switches stack FIRST -> _on_open_benchmark_from_youtube fires SECOND!
            yt._current_stream = ResolvedStream(video_id=sample_item.video_id, title=sample_item.title, audio_url="https://example.invalid/a.opus")
            window._yt_benchmark_armed = True
            window.content_stack.setCurrentWidget(window.audio_effects.benchmark_page)
            with patch.object(yt, "prepare_benchmark_audio_for") as mock_prep_bench:
                window._on_open_benchmark_from_youtube()
                mock_prep_bench.assert_called_once_with(window.audio_effects.benchmark_page)
            self.assertFalse(window.sidebar_container.isHidden())
            self.assertFalse(window.playback_bar.isHidden())

            # 6e2. Workspace Mode selector (Offline / Online / Both) hides irrelevant sidebar tabs cleanly
            window.apply_workspace_mode("offline", navigate=False)
            self.assertTrue(window.sidebar.isRowHidden(window.sidebar.row_for_page("youtube_online")))
            self.assertFalse(window.sidebar.isRowHidden(window.sidebar.row_for_page("home")))
            window.apply_workspace_mode("online", navigate=False)
            self.assertFalse(window.sidebar.isRowHidden(window.sidebar.row_for_page("youtube_online")))
            self.assertFalse(window.sidebar.isRowHidden(window.sidebar.row_for_page("download")))
            self.assertFalse(window.sidebar.isRowHidden(window.sidebar.row_for_page("settings")))
            self.assertTrue(window.sidebar.isRowHidden(window.sidebar.row_for_page("home")))
            self.assertTrue(window.sidebar.isRowHidden(window.sidebar.row_for_page("library")))
            window.apply_workspace_mode("both", navigate=False)
            self.assertFalse(window.sidebar.isRowHidden(window.sidebar.row_for_page("home")))
            self.assertFalse(window.sidebar.isRowHidden(window.sidebar.row_for_page("youtube_online")))

            # 6e3. Account Dialog has scrollable layout, Cookie guide, and AI Whisper + Translate toggles
            acc_dlg = _YouTubeAccountDialog(yt.profile, client=yt.client, parent=yt)
            self.assertTrue(hasattr(acc_dlg, "chk_allow_ai_sub"))
            self.assertTrue(hasattr(acc_dlg, "chk_allow_ai_translate"))
            acc_dlg.deleteLater()

            # 6e4. Liked library section shows Play All / Shuffle / Sync YouTube Liked buttons
            yt._render_library_section("liked")
            self.assertFalse(yt.btn_lib_sync_yt_liked.isHidden())
            self.assertFalse(yt.btn_lib_play_all.isHidden())
            self.assertFalse(yt.btn_lib_shuffle.isHidden())

            # 6f. Smooth Seek Slider drag preview -> commit ONCE on release
            from PySide6.QtCore import QPointF, Qt as _Qt
            from PySide6.QtGui import QMouseEvent
            previews, commits = [], []
            yt.seek_slider.setRange(0, 100000)
            yt.seek_slider.resize(200, 20)
            yt.seek_slider.drag_preview.connect(previews.append)
            yt.seek_slider.seek_requested.connect(commits.append)
            ev_p = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(40, 10), QPointF(40, 10), _Qt.MouseButton.LeftButton, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier)
            ev_m = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(120, 10), QPointF(120, 10), _Qt.MouseButton.NoButton, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier)
            ev_r = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(120, 10), QPointF(120, 10), _Qt.MouseButton.LeftButton, _Qt.MouseButton.NoButton, _Qt.KeyboardModifier.NoModifier)
            yt.seek_slider.mousePressEvent(ev_p)
            yt.seek_slider.mouseMoveEvent(ev_m)
            self.assertEqual(len(commits), 0)
            self.assertGreaterEqual(len(previews), 2)
            yt.seek_slider.mouseReleaseEvent(ev_r)
            self.assertEqual(len(commits), 1)
            self.assertAlmostEqual(commits[0], 60000, delta=1000)

            # 7. Audio Studio live sync wiring & panel opener
            with patch.object(yt, "on_audio_profile_changed") as mock_reapply:
                window.audio_effects.panel.dac_phase_changed.emit("minimum")
                pump(90)
                mock_reapply.assert_called()

            # 8. In-tab AI Subtitle finish saves isolated disk cache & deletes temp audio directory
            with tempfile.TemporaryDirectory() as td:
                cache_root = Path(td) / "subs_cache"
                fake_tmp = Path(td) / "temp_audio_job"
                fake_tmp.mkdir()
                (fake_tmp / "song.opus").write_bytes(b"fake-audio")
                yt._ai_temp_dir = str(fake_tmp)
                yt._current_item = sample_item
                with patch("core.youtube_online_client.online_ai_sub_cache_dir", return_value=cache_root):
                    yt._on_ai_sub_finished(
                        sample_item.video_id,
                        sample_item.title,
                        [{"start": 0.5, "end": 3.0, "orig": "Never gonna give you up", "vi": "Không bao giờ từ bỏ em"}],
                    )
                    pump(30)
                    self.assertFalse(fake_tmp.exists())
                    self.assertTrue(has_cached_ai_subtitles(sample_item.video_id))
                    self.assertEqual(len(yt._ai_cues), 1)


if __name__ == "__main__":
    unittest.main()
