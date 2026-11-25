"""Tests for Studio Download Engine & Lightweight DownloadPage Polish (preserving 1100x750 geometry)."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import PySide6.QtMultimedia  # noqa: F401  Keep QtMultimedia resident across ui_preview sys.modules patch.
import yt_dlp
from PySide6.QtWidgets import QPushButton

from tools.ui_preview import isolated_window, pump
from download_core.download_options import ORIGINAL, QUALITIES
from download_core.studio_download_engine import (
    FILE_PRINT_PREFIX,
    StudioDownloadWorker,
    StudioTitleWorker,
    audio_advice_text,
    build_studio_download_command,
    mark_ytdlp_updated,
    normalize_cookies_browser,
    normalize_quality_choice,
    resolve_ffmpeg_dir,
    resolve_ytdlp_executable,
    should_check_ytdlp_update,
)


class StudioDownloadEngineTests(unittest.TestCase):
    def test_mojibake_and_cookie_normalization(self):
        self.assertEqual(normalize_quality_choice("Original (Gi\u00e1\u00bb\u00af ngu\u00e1\u00bb\u201cn)"), ORIGINAL)
        self.assertEqual(normalize_quality_choice("original"), ORIGINAL)
        self.assertEqual(normalize_quality_choice("High (Opus)"), "High (Opus)")
        self.assertEqual(normalize_quality_choice("Standard (M4A-ACC)"), "Standard (M4A-ACC)")
        self.assertEqual(normalize_quality_choice("Extreme (320k)"), "Extreme (320k)")
        self.assertEqual(normalize_quality_choice("Low (128k)"), "Low (128k)")
        self.assertEqual(normalize_cookies_browser("EDGE"), "edge")
        self.assertEqual(normalize_cookies_browser("opera"), "")

    def test_command_builder_parses_all_combinations_and_prefers_opus_for_hifi(self):
        ff_dir = resolve_ffmpeg_dir()
        for fmt in ("Video MKV", "Video MP4", "Audio MP3"):
            for quality in QUALITIES:
                for auto_title in (False, True):
                    with self.subTest(fmt=fmt, quality=quality, auto_title=auto_title):
                        cmd = build_studio_download_command(
                            "yt-dlp.exe",
                            "downloads",
                            "100% Song",
                            "https://example.invalid/watch?v=x",
                            {"download": {"format": fmt, "quality": quality, "resolution": "2K"}},
                            auto_title=auto_title,
                            cookies_browser="edge",
                            ffmpeg_dir=ff_dir,
                        )
                        parsed = yt_dlp.parse_options(cmd[1:]).ydl_opts
                        self.assertEqual(cmd.count("https://example.invalid/watch?v=x"), 1)
                        self.assertEqual(cmd[-2], "--")
                        self.assertEqual(cmd.count("-o"), 1)
                        self.assertNotIn("--ignore-config", cmd)
                        self.assertEqual(parsed.get("cookiesfrombrowser"), ("edge", None, None, None))
                        if ff_dir:
                            self.assertEqual(parsed.get("ffmpeg_location"), ff_dir)
                        if auto_title:
                            self.assertIn("--windows-filenames", cmd)
                            self.assertTrue(cmd[cmd.index("-o") + 1].endswith("%(title).150B.%(ext)s"))
                        else:
                            self.assertTrue(cmd[cmd.index("-o") + 1].endswith("100%% Song.%(ext)s"))

        mkv_cmd = build_studio_download_command(
            "yt-dlp.exe", "downloads", "Track: Live?", "https://example.invalid/watch?v=a",
            {"download": {"format": "Video MKV", "quality": ORIGINAL, "resolution": "2K"}},
        )
        self.assertEqual(mkv_cmd[mkv_cmd.index("-S") + 1], "res,quality,acodec,asr,abr")
        self.assertTrue(mkv_cmd[mkv_cmd.index("-o") + 1].endswith("Track- Live-.%(ext)s"))

        mp4_orig = build_studio_download_command(
            "yt-dlp.exe", "downloads", "Track", "https://example.invalid/watch?v=a",
            {"download": {"format": "Video MP4", "quality": ORIGINAL, "resolution": "2K"}},
        )
        self.assertEqual(mp4_orig[mp4_orig.index("-S") + 1], "res,quality,acodec,asr,abr")

        mp4_std = build_studio_download_command(
            "yt-dlp.exe", "downloads", "Track", "https://example.invalid/watch?v=a",
            {"download": {"format": "Video MP4", "quality": "Standard (M4A-ACC)", "resolution": "1080p"}},
        )
        self.assertNotIn("-S", mp4_std)
        self.assertTrue(audio_advice_text("Video MKV", ORIGINAL))

        # Verify actual yt-dlp selector prefers VBR Opus 48 kHz over 128k AAC, Premium 256k, and lossless FLAC
        v_1440 = {"format_id": "v1440", "ext": "webm", "acodec": "none", "vcodec": "vp9", "height": 1440, "tbr": 8000, "url": "https://x/v", "protocol": "https"}
        a_140 = {"format_id": "140_aac", "ext": "m4a", "acodec": "mp4a.40.2", "vcodec": "none", "abr": 128.0, "asr": 44100, "quality": 3, "url": "https://x/140", "protocol": "https"}
        a_251 = {"format_id": "251_opus", "ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 112.1, "asr": 48000, "quality": 3, "url": "https://x/251", "protocol": "https"}
        a_141 = {"format_id": "141_premaac", "ext": "m4a", "acodec": "mp4a.40.2", "vcodec": "none", "abr": 256.0, "asr": 44100, "quality": 4, "url": "https://x/141", "protocol": "https"}
        a_774 = {"format_id": "774_premopus", "ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 256.0, "asr": 48000, "quality": 4, "url": "https://x/774", "protocol": "https"}
        a_flac = {"format_id": "flac", "ext": "flac", "acodec": "flac", "vcodec": "none", "abr": 950.0, "asr": 48000, "url": "https://x/flac", "protocol": "https"}

        def _pick(fmt, fmts):
            c = build_studio_download_command("yt-dlp.exe", "out", "S", "https://x/v", {"download": {"format": fmt, "quality": ORIGINAL, "resolution": "2K"}})
            opts = yt_dlp.parse_options(c[1:]).ydl_opts
            opts.update(quiet=True, no_warnings=True)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.process_ie_result({"id": "v", "title": "T", "formats": [dict(f) for f in fmts]}, download=False)
                return [s["format_id"] for s in (info.get("requested_formats") or [info])]

        a_opus_noq = {"format_id": "opus_128", "ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 128.0, "asr": 48000, "url": "https://x/op", "protocol": "https"}
        for fmt in ("Video MKV", "Video MP4"):
            self.assertEqual(_pick(fmt, [v_1440, a_140, a_251]), ["v1440", "251_opus"])
            self.assertEqual(_pick(fmt, [v_1440, a_140, a_251, a_141]), ["v1440", "141_premaac"])
            self.assertEqual(_pick(fmt, [v_1440, a_141, a_774]), ["v1440", "774_premopus"])
        self.assertEqual(_pick("Audio MP3", [a_opus_noq, a_flac]), ["flac"])

    def test_update_cooldown_and_frozen_ytdlp_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake_exe = root / "yt-dlp.exe"
            fake_exe.write_bytes(b"X" * (1024 * 1024 + 10))
            stamp = root / "state.json"

            self.assertTrue(should_check_ytdlp_update(stamp, exe_path=fake_exe, now_ts=1000.0))
            mark_ytdlp_updated(stamp, now_ts=1000.0)
            self.assertFalse(should_check_ytdlp_update(stamp, exe_path=fake_exe, cooldown_sec=43200, now_ts=5000.0))
            self.assertTrue(should_check_ytdlp_update(stamp, exe_path=fake_exe, cooldown_sec=43200, now_ts=50000.0))

            bundle = root / "_internal"
            bundle.mkdir()
            (bundle / "yt-dlp.exe").write_bytes(b"Y" * (1024 * 1024 + 20))
            app_exe = root / "dist" / "BoTube.exe"
            app_exe.parent.mkdir()
            app_exe.write_bytes(b"exe")
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", str(bundle), create=True), \
                 patch.object(sys, "executable", str(app_exe)):
                resolved = resolve_ytdlp_executable()
                self.assertEqual(resolved, app_exe.parent / "yt-dlp.exe")
                self.assertTrue(resolved.is_file())

    def test_studio_title_and_download_workers_handle_auto_title_and_errors(self):
        class FakeTitleProc:
            def __init__(self, rc, out, err=""):
                self.returncode = rc
                self._out = out
                self._err = err
            def communicate(self):
                return self._out, self._err
            def poll(self):
                return self.returncode
            def terminate(self):
                pass
            def wait(self, **kw):
                return self.returncode

        cmds = []
        def spawn_titles(cmd, **kw):
            cmds.append(cmd)
            if any("bad-link" in str(c) for c in cmd):
                return FakeTitleProc(1, "", "HTTP Error 403")
            return FakeTitleProc(0, "Artist: Song / Test\n")

        with tempfile.TemporaryDirectory() as td:
            fake_exe = Path(td) / "yt-dlp.exe"
            fake_exe.write_bytes(b"Z" * (1024 * 1024 + 5))
            worker = StudioTitleWorker(["https://example.invalid/ok", "https://example.invalid/bad-link"], cookies_browser="chrome")
            worker.ytdlp_exe = fake_exe
            titles, done = [], []
            worker.title_ready_signal.connect(titles.append)
            worker.finished_signal.connect(lambda ok, tot: done.append((ok, tot)))
            with patch("download_core.studio_download_engine.should_check_ytdlp_update", return_value=False), \
                 patch("download_core.studio_download_engine.subprocess.Popen", side_effect=spawn_titles):
                worker.run()
            self.assertEqual(titles, ["Artist- Song - Test"])
            self.assertEqual(done, [(1, 2)])
            self.assertIn("--cookies-from-browser", cmds[0])

            class FakeDlProc:
                def __init__(self, rc, out):
                    self.stdout = io.StringIO(out)
                    self.returncode = rc
                def wait(self):
                    return self.returncode
                def poll(self):
                    return self.returncode

            dl_cmds = []
            def spawn_dl(cmd, **kw):
                dl_cmds.append(cmd)
                if any("fail-item" in str(c) for c in cmd):
                    return FakeDlProc(1, "ERROR: blocked\n")
                return FakeDlProc(0, f"[download] 100% of 5.0MiB\n{FILE_PRINT_PREFIX}{td}/Resolved Song.mkv\n")

            dl = StudioDownloadWorker(
                ["https://example.invalid/fail-item", "https://example.invalid/good-item"],
                [],
                td,
                {"download": {"format": "Video MKV", "quality": ORIGINAL, "resolution": "2K"}},
                auto_title=True,
            )
            dl.ytdlp_exe = fake_exe
            rows, resolved_titles, finished = [], [], []
            dl.row_result_signal.connect(lambda idx, ok: rows.append((idx, ok)))
            dl.resolved_title_signal.connect(lambda idx, name: resolved_titles.append((idx, name)))
            dl.finished_signal.connect(finished.append)
            with patch("download_core.studio_download_engine.should_check_ytdlp_update", return_value=False), \
                 patch("download_core.studio_download_engine.subprocess.Popen", side_effect=spawn_dl):
                dl.run()
            self.assertEqual(rows, [(0, False), (1, True)])
            self.assertEqual(resolved_titles, [(1, "Resolved Song")])
            self.assertEqual(finished, [1])
            self.assertTrue(any("%(title).150B.%(ext)s" in c[c.index("-o") + 1] for c in dl_cmds))

            # Duplicate custom names disambiguation + mixed per-row auto_title
            dl_cmds.clear()
            dl2 = StudioDownloadWorker(
                ["https://example.invalid/1", "https://example.invalid/2", "https://example.invalid/3"],
                ["Track", "", "Track"],
                td,
                {"download": {"format": "Video MKV", "quality": ORIGINAL, "resolution": "2K"}},
                auto_title=False,
            )
            dl2.ytdlp_exe = fake_exe
            with patch("download_core.studio_download_engine.should_check_ytdlp_update", return_value=False), \
                 patch("download_core.studio_download_engine.subprocess.Popen", side_effect=spawn_dl):
                dl2.run()
            self.assertTrue(dl_cmds[0][dl_cmds[0].index("-o") + 1].endswith("Track.%(ext)s"))
            self.assertTrue(dl_cmds[1][dl_cmds[1].index("-o") + 1].endswith("%(title).150B.%(ext)s"))
            self.assertTrue(dl_cmds[2][dl_cmds[2].index("-o") + 1].endswith("Track (2).%(ext)s"))

    def test_real_ytdlp_exe_auto_title_progress_and_mkv_output(self):
        import http.server
        import socketserver
        import subprocess
        import threading
        exe = resolve_ytdlp_executable()
        ff_dir = resolve_ffmpeg_dir()
        if not exe.is_file() or not ff_dir:
            self.skipTest("Portable yt-dlp.exe + ffmpeg.exe required")
        ffmpeg = str(Path(ff_dir) / "ffmpeg.exe")
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source.mp4"
            out_dir = Path(td) / "out"
            out_dir.mkdir()
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=15:d=1",
                 "-f", "lavfi", "-i", "sine=f=440:r=48000:d=1", "-c:v", "libx264", "-c:a", "aac", str(src)],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            class QuietHandler(http.server.SimpleHTTPRequestHandler):
                def __init__(self, *a, **k):
                    super().__init__(*a, directory=td, **k)
                def log_message(self, *a):
                    pass

            with socketserver.TCPServer(("127.0.0.1", 0), QuietHandler) as httpd:
                port = httpd.server_address[1]
                threading.Thread(target=httpd.serve_forever, daemon=True).start()
                try:
                    url = f"http://127.0.0.1:{port}/source.mp4"
                    info_path = Path(td) / "info.json"
                    info_path.write_text(json.dumps({
                        "id": "e2e", "title": "Tiếng Việt: Song / 100%?", "webpage_url": url,
                        "extractor": "generic", "extractor_key": "Generic",
                        "formats": [{"format_id": "1", "ext": "mp4", "height": 720, "vcodec": "h264", "acodec": "aac", "url": url, "protocol": "http"}],
                    }), encoding="utf-8")
                    base = build_studio_download_command(
                        str(exe), str(out_dir), "", url,
                        {"download": {"format": "Video MKV", "quality": ORIGINAL, "resolution": "1080p"}},
                        auto_title=True, ffmpeg_dir=ff_dir,
                    )
                    res = subprocess.run(
                        [base[0], "--load-info-json", str(info_path)] + base[1:-2],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertIn("[download]", res.stdout)
                    self.assertIn(FILE_PRINT_PREFIX, res.stdout)
                    mkv_files = list(out_dir.glob("*.mkv"))
                    self.assertEqual(len(mkv_files), 1)
                finally:
                    httpd.shutdown()


class DownloadStudioUiTests(unittest.TestCase):
    def test_window_keeps_1100x750_geometry_and_original_download_layout_works(self):
        with isolated_window() as (window, root):
            page = window.download_page
            view = getattr(page, "studio_view", None)
            self.assertIsNotNone(view)

            # Original default window size 1100x750 MUST remain uninflated on every page
            window.resize(1100, 750)
            pump(40)
            self.assertEqual(window.size().width(), 1100)
            self.assertEqual(window.size().height(), 750)
            self.assertLessEqual(window.minimumSizeHint().height(), 680)
            self.assertLessEqual(page.minimumSizeHint().height(), 480)

            # Non-destructive on init
            before_cfg = copy.deepcopy(page.full_config)
            self.assertEqual(page.setting_menu.settings, before_cfg)

            window.content_stack.setCurrentWidget(page)
            pump(40)

            # One-click Hi-Fi pill in header selects Video MKV + Original
            view.btn_hifi_preset.click()
            pump(30)
            self.assertEqual(page.setting_menu.format_combo.currentText(), "Video MKV")
            self.assertEqual(page.setting_menu.quality_combo.currentText(), ORIGINAL)
            self.assertIn("MKV", view.btn_hifi_preset.text())

            # SettingMenu popup holds cookies selector & auto-refresh checkbox cleanly
            menu = page.setting_menu
            menu.show()
            pump(20)
            self.assertGreaterEqual(menu.height(), menu.minimumSizeHint().height())
            view.combo_cookies.setCurrentIndex(view.combo_cookies.findData("edge"))
            btn_save = menu.findChild(QPushButton, "btn_save")
            self.assertIsNotNone(btn_save)
            btn_save.click()
            pump(30)
            saved = json.loads(Path(page.settings_file).read_text(encoding="utf-8"))
            self.assertEqual(saved["download"]["cookies_browser"], "edge")
            self.assertTrue(saved["download"]["auto_refresh"])

            # 1-to-1 title alignment with middle failure + highlight persistence across multiple rows
            page.txt_links.setPlainText("https://example.invalid/1\nhttps://example.invalid/2\nhttps://example.invalid/3")
            page.txt_names.clear()
            save_dir = root / "dl-out"
            save_dir.mkdir()
            page.btn_toggle_path.setChecked(True)
            page.combo_path.setCurrentText(str(save_dir))
            pump(20)

            def fake_title_start(self_t):
                self_t.row_title_signal.emit(0, "Artist- Song 1", True)
                self_t.row_title_signal.emit(1, "", False)
                self_t.row_title_signal.emit(2, "Artist- Song 3", True)
                self_t.finished_signal.emit(2, 3)

            with patch.object(StudioTitleWorker, "start", fake_title_start):
                page.btn_get_name.click()
                pump(30)
            self.assertEqual(page.txt_names.toPlainText().splitlines(), ["Artist- Song 1", "", "Artist- Song 3"])

            started = []
            def fake_start(self_w):
                started.append((self_w.links, list(self_w.names), self_w.auto_title, self_w.cookies_browser))
                self_w.row_result_signal.emit(0, True)
                self_w.progress_signal.emit(1, 3)
                self_w.resolved_title_signal.emit(1, "Recovered Track 2")
                self_w.row_result_signal.emit(1, True)
                self_w.progress_signal.emit(2, 3)
                self_w.row_result_signal.emit(2, False)
                self_w.fail_signal.emit(1, 3)
                self_w.finished_signal.emit(2)

            spy_refresh = []
            page.manual_refresh_signal.connect(lambda: spy_refresh.append(True))
            with patch.object(StudioDownloadWorker, "start", fake_start):
                page.btn_start.click()
                pump(40)

            self.assertEqual(
                started,
                [(
                    ["https://example.invalid/1", "https://example.invalid/2", "https://example.invalid/3"],
                    ["Artist- Song 1", "", "Artist- Song 3"],
                    False,
                    "edge",
                )],
            )
            self.assertEqual(page.txt_names.toPlainText().splitlines(), ["Artist- Song 1", "Recovered Track 2", "Artist- Song 3"])
            self.assertEqual(spy_refresh, [True])
            self.assertFalse(getattr(window, "refresh_paused", False))

            # Row 0 highlight MUST survive subsequent setPlainText call from Row 1!
            from PySide6.QtGui import QTextCursor
            cur = QTextCursor(page.txt_names.document())
            cur.movePosition(QTextCursor.MoveOperation.Start)
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            self.assertEqual(cur.charFormat().foreground().color().name().lower(), "#77e0be")
            cur.movePosition(QTextCursor.MoveOperation.NextBlock)
            cur.movePosition(QTextCursor.MoveOperation.NextBlock)
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            self.assertEqual(cur.charFormat().foreground().color().name().lower(), "#f28b94")


if __name__ == "__main__":
    unittest.main()
