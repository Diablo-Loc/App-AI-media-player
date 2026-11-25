"""Studio-grade download engine helpers: Hi-Fi Opus stream sorting, smart cooldown, cookies & live title/download workers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from PySide6.QtCore import QThread, Signal

from control.worker_lifecycle import OwnedProcesses
from download_core.download_options import ORIGINAL, QUALITIES, build_download_command, download_options
from download_core.utils import sanitize_folder_name
from download_core.yt_dlp import ensure_ytdlp_exists
from paths import project_root, storage_dir

VALID_COOKIE_BROWSERS = ("", "edge", "chrome", "brave", "firefox")
DEFAULT_UPDATE_COOLDOWN_SEC = 12 * 3600
FILE_PRINT_PREFIX = "BOTUBE_SAVED_FILE:"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def normalize_quality_choice(quality: str) -> str:
    """Repair legacy UTF-8/latin1 mojibake quality labels and return canonical QUALITIES value."""
    raw = str(quality or "").strip()
    if not raw:
        return ORIGINAL
    if raw in QUALITIES:
        return raw
    for attempt in (raw,):
        cur = attempt
        for _ in range(2):
            try:
                cur = cur.encode("latin1").decode("utf-8")
                if cur in QUALITIES:
                    return cur
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
    low = raw.lower()
    if low.startswith("original"):
        return ORIGINAL
    if "opus" in low:
        return "High (Opus)"
    if "standard" in low or "m4a" in low or "acc" in low or "aac" in low:
        return "Standard (M4A-ACC)"
    if "extreme" in low or "320" in low:
        return "Extreme (320k)"
    if "low" in low or "128" in low:
        return "Low (128k)"
    return ORIGINAL


def normalize_cookies_browser(browser: str) -> str:
    clean = str(browser or "").strip().lower()
    return clean if clean in VALID_COOKIE_BROWSERS else ""


def resolve_ytdlp_executable() -> Path:
    """Resolve portable writable yt-dlp.exe path for both dev and frozen EXE layouts."""
    if getattr(sys, "frozen", False):
        portable_exe = Path(sys.executable).resolve().parent / "yt-dlp.exe"
        if portable_exe.is_file() and portable_exe.stat().st_size > 1024 * 1024:
            return portable_exe
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            for candidate in (
                Path(meipass) / "yt-dlp.exe",
                Path(meipass) / "app" / "download_core" / "yt-dlp.exe",
            ):
                if candidate.is_file() and candidate.stat().st_size > 1024 * 1024:
                    try:
                        portable_exe.parent.mkdir(parents=True, exist_ok=True)
                        tmp = portable_exe.with_suffix(".exe.tmp")
                        shutil.copy2(candidate, tmp)
                        os.replace(tmp, portable_exe)
                        return portable_exe
                    except OSError:
                        return candidate
        return portable_exe
    return Path(__file__).resolve().parent / "yt-dlp.exe"


def resolve_ffmpeg_dir() -> str:
    """Return directory containing ffmpeg.exe so yt-dlp merges/remuxes cleanly without PATH assumptions."""
    candidates = [
        project_root() / "bin",
        project_root() / "app_resources" / "bin",
    ]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).resolve().parent / "bin")
    for folder in candidates:
        if (folder / "ffmpeg.exe").is_file():
            return str(folder)
    return ""


def _update_stamp_path() -> Path:
    return Path(storage_dir()) / "ytdlp-update-state.json"


def should_check_ytdlp_update(
    stamp_path: Path | str | None = None,
    *,
    exe_path: Path | str | None = None,
    cooldown_sec: float = DEFAULT_UPDATE_COOLDOWN_SEC,
    now_ts: float | None = None,
) -> bool:
    if exe_path is not None:
        p_exe = Path(exe_path)
        if not p_exe.is_file() or p_exe.stat().st_size <= 1024 * 1024:
            return True
    target = Path(stamp_path) if stamp_path is not None else _update_stamp_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        last_ts = float(data.get("last_checked_ts", 0.0))
    except (OSError, ValueError, TypeError):
        return True
    now = time.time() if now_ts is None else float(now_ts)
    if last_ts <= 0 or now < last_ts:
        return True
    return (now - last_ts) >= float(cooldown_sec)


def mark_ytdlp_updated(
    stamp_path: Path | str | None = None,
    *,
    now_ts: float | None = None,
) -> None:
    target = Path(stamp_path) if stamp_path is not None else _update_stamp_path()
    now = time.time() if now_ts is None else float(now_ts)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"last_checked_ts": now}), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def audio_advice_text(format_choice: str, quality_choice: str) -> str:
    """Return accurate Studio guidance for audio fidelity and compatibility."""
    q = normalize_quality_choice(quality_choice)
    fmt = str(format_choice or "Video MP4")
    if "Video MKV" in fmt:
        if "Opus" in q:
            return (
                "Chế độ ưu tiên Opus: chọn video sắc nét kèm luồng Opus 48 kHz và đóng gói thẳng MKV "
                "(0% chuyển mã lại — giữ trọn vẹn chi tiết nguồn)."
            )
        return (
            "Chuẩn Hi-Fi khuyên dùng cho BoTube + USB DAC: ưu tiên Opus 48 kHz cao nhất và "
            "đóng gói thẳng MKV (0% nén lại, tối ưu cho giải mã DSP 64-bit)."
        )
    if "Audio" in fmt:
        if q == ORIGINAL:
            return (
                "Tải thẳng tệp âm thanh gốc từ nguồn (ưu tiên Opus .webm/.opus hoặc AAC .m4a), "
                "0% chuyển mã — nghe hay nhất và giữ đúng phổ tần số gốc."
            )
        if "Opus" in q:
            return "Chỉ nhận luồng Opus 48 kHz nguyên bản (không tự chuyển mã). Nếu nguồn thiếu Opus, hãy chọn Original."
        if "Standard" in q:
            return "Chỉ nhận AAC gốc và đóng gói M4A, có ảnh bìa nhúng. Không tự chuyển mã."
        rate = "320 kbps" if "Extreme" in q else "128 kbps"
        return (
            f"Chuyển mã sang MP3 {rate} để phát trên thiết bị cũ. "
            "Lưu ý: tăng lên 320k không khôi phục chi tiết đã mất từ nguồn lossy."
        )
    if q == ORIGINAL:
        return (
            "MP4 ưu tiên âm thanh chất lượng cao nhất (Opus 48 kHz / Premium / Lossless) và hình gốc. "
            "Nếu mở bằng Windows Media Player đời cũ bị mất tiếng, hãy chọn Standard (M4A-ACC)."
        )
    if "Opus" in q:
        return "MP4 ưu tiên luồng Opus 48 kHz nguyên bản (không chuyển sang AAC), thiếu Opus mới dùng luồng khác."
    if "Low" in q:
        return "MP4 chuyển mã audio xuống AAC 128 kbps để tiết kiệm dung lượng; video giữ nguyên bản."
    return (
        "MP4 ưu tiên AAC (M4A) nguyên bản để tương thích mọi thiết bị (TV, điện thoại, xe hơi) "
        "mà không mã hóa lại gây mất chi tiết."
    )


def _format_sort_arg(format_choice: str, quality_choice: str) -> str:
    q = normalize_quality_choice(quality_choice)
    fmt = str(format_choice or "Video MP4")
    if "Audio" in fmt:
        if q == ORIGINAL:
            return "quality,acodec,asr,abr"
        return ""
    if "Opus" in q:
        return "res,acodec:opus,asr,abr"
    if q == ORIGINAL:
        return "res,quality,acodec,asr,abr"
    return ""


def build_studio_download_command(
    executable: str,
    save_path: str,
    name: str,
    link: str,
    options: dict | None = None,
    *,
    auto_title: bool = False,
    cookies_browser: str = "",
    ffmpeg_dir: str = "",
) -> list[str]:
    """Build yt-dlp CLI command on top of DownloadOptions policy with Hi-Fi Opus sorting and safe auto-title."""
    raw_opts = dict(options) if isinstance(options, dict) else {}
    dl = dict(download_options(raw_opts))
    fmt = str(dl.get("format", "Video MP4"))
    quality = normalize_quality_choice(dl.get("quality", ORIGINAL))
    res = str(dl.get("resolution", "1080p"))
    normalized_payload = {"download": {"format": fmt, "quality": quality, "resolution": res}}

    base_name = "download" if auto_title else sanitize_folder_name(str(name or "").strip() or "download")
    cmd = list(build_download_command(executable, save_path, base_name, link, normalized_payload))

    out_idx = cmd.index("-o")
    prefix = cmd[:out_idx]
    out_tmpl = cmd[out_idx + 1]
    suffix = cmd[out_idx + 2:]

    extras: list[str] = []
    if ffmpeg_dir:
        extras += ["--ffmpeg-location", str(ffmpeg_dir)]
    extras += ["--concurrent-fragments", "4", "--retries", "3", "--fragment-retries", "3", "--newline"]

    sort_spec = _format_sort_arg(fmt, quality)
    if sort_spec:
        extras += ["-S", sort_spec]

    browser = normalize_cookies_browser(cookies_browser)
    if browser:
        extras += ["--cookies-from-browser", browser]

    if auto_title:
        extras += [
            "--no-simulate",
            "--no-quiet",
            "--progress",
            "--windows-filenames",
            "--encoding",
            "utf-8",
            "--print",
            f"after_move:{FILE_PRINT_PREFIX}%(filepath)s",
        ]
        out_tmpl = os.path.join(save_path, "%(title).150B.%(ext)s")

    return prefix + extras + ["-o", out_tmpl] + suffix


def _run_ytdlp_update_step(
    ytdlp_exe: Path,
    processes: OwnedProcesses,
    status_signal,
    log_signal,
    *,
    force: bool = False,
    is_running_cb=lambda: True,
    cooldown_sec: float = DEFAULT_UPDATE_COOLDOWN_SEC,
) -> bool:
    if not force and not should_check_ytdlp_update(exe_path=ytdlp_exe, cooldown_sec=cooldown_sec):
        log_signal.emit("ℹ️ Bộ máy yt-dlp đã kiểm tra cập nhật gần đây; bỏ qua bước chờ mạng.")
        return True

    status_signal.emit("Đang kiểm tra cập nhật yt-dlp...")
    log_signal.emit("🔄 [HỆ THỐNG] Đang kiểm tra cập nhật yt-dlp...")
    try:
        proc = processes.track(
            subprocess.Popen(
                [str(ytdlp_exe), "-U"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_NO_WINDOW,
            )
        )
        for line in iter(proc.stdout.readline, ""):
            if not is_running_cb():
                proc.terminate()
                break
            clean = line.strip()
            if clean:
                log_signal.emit(clean)
        proc.stdout.close()
        rc = proc.wait()
        processes.release(proc)
        if rc == 0 and is_running_cb():
            mark_ytdlp_updated()
        return rc == 0
    except Exception as exc:
        log_signal.emit(f"⚠️ [LỖI CẬP NHẬT] {exc}")
        return False


class StudioTitleWorker(QThread):
    """Fetch clean Windows-safe titles via standalone yt-dlp.exe + optional browser cookies."""

    title_ready_signal = Signal(str)
    row_title_signal = Signal(int, str, bool)
    finished_signal = Signal(int, int)
    status_signal = Signal(str)
    log_signal = Signal(str)
    progress_signal = Signal(int, int)

    def __init__(self, links: list[str], cookies_browser: str = "", force_update: bool = False):
        super().__init__()
        self._processes = OwnedProcesses()
        self.links = list(links)
        self.cookies_browser = normalize_cookies_browser(cookies_browser)
        self.force_update = bool(force_update)
        self.is_running = True
        self.ytdlp_exe = resolve_ytdlp_executable()

    def run(self):
        try:
            self._run_titles()
        finally:
            self._processes.stop()
            self._processes.wait()

    def _run_titles(self):
        if not ensure_ytdlp_exists(
            str(self.ytdlp_exe),
            self.status_signal,
            self.log_signal,
            self.progress_signal,
            cancel_cb=lambda: not self.is_running,
        ):
            self.status_signal.emit("❌ Không thể khởi tạo bộ máy yt-dlp!")
            self.finished_signal.emit(0, len(self.links))
            return

        if self.is_running:
            _run_ytdlp_update_step(
                self.ytdlp_exe,
                self._processes,
                self.status_signal,
                self.log_signal,
                force=self.force_update,
                is_running_cb=lambda: self.is_running,
            )

        ok_count = 0
        total = len(self.links)
        for idx, link in enumerate(self.links):
            if not self.is_running:
                break
            self.status_signal.emit(f"🔍 Đang lấy tên video {idx + 1}/{total}...")
            cmd = [
                str(self.ytdlp_exe),
                "--no-playlist",
                "--no-warnings",
                "--flat-playlist",
                "--encoding",
                "utf-8",
                "--print",
                "%(title)s",
            ]
            if self.cookies_browser:
                cmd += ["--cookies-from-browser", self.cookies_browser]
            cmd += ["--", link]

            try:
                proc = self._processes.track(
                    subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=_NO_WINDOW,
                    )
                )
                stdout_txt, stderr_txt = proc.communicate()
                self._processes.release(proc)
                if proc.returncode == 0 and self.is_running:
                    raw_line = next((l.strip() for l in stdout_txt.splitlines() if l.strip()), "")
                    if raw_line:
                        safe_title = sanitize_folder_name(raw_line)
                        self.row_title_signal.emit(idx, safe_title, True)
                        self.title_ready_signal.emit(safe_title)
                        self.log_signal.emit(f"✅ {safe_title}")
                        ok_count += 1
                        continue
                err_line = next((l.strip() for l in (stderr_txt or stdout_txt).splitlines() if l.strip()), "Không lấy được tiêu đề")
                self.row_title_signal.emit(idx, "", False)
                self.log_signal.emit(f"❌ Lỗi lấy tên link {idx + 1}: {err_line}")
            except Exception as exc:
                self.row_title_signal.emit(idx, "", False)
                self.log_signal.emit(f"❌ Lỗi lấy tên link {idx + 1}: {exc}")

        if self.is_running:
            if ok_count == total:
                self.status_signal.emit(f"✅ Đã lấy xong {ok_count}/{total} tên video.")
            else:
                self.status_signal.emit(f"⚠️ Lấy được {ok_count}/{total} tên (bỏ qua link lỗi — hãy kiểm tra URL hoặc bật Cookie).")
        self.finished_signal.emit(ok_count, total)

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        self._processes.stop()


class StudioDownloadWorker(QThread):
    """Multi-fragment, audio-preserving downloader with auto-title support & deterministic cancellation."""

    progress_signal = Signal(int, int)
    fail_signal = Signal(int, int)
    row_result_signal = Signal(int, bool)
    resolved_title_signal = Signal(int, str)
    status_signal = Signal(str)
    finished_signal = Signal(int)
    log_signal = Signal(str)

    def __init__(
        self,
        links: list[str],
        names: list[str] | None,
        save_path: str,
        options: dict | None = None,
        *,
        auto_title: bool = False,
        cookies_browser: str = "",
        force_update: bool = False,
    ):
        super().__init__()
        self._processes = OwnedProcesses()
        self.links = list(links)
        self.names = list(names or [])
        self.save_path = save_path
        self.options = options if isinstance(options, dict) else {}
        self.auto_title = bool(auto_title or not self.names)
        self.cookies_browser = normalize_cookies_browser(cookies_browser or download_options(self.options).get("cookies_browser", ""))
        self.force_update = bool(force_update)
        self.is_running = True
        self.ytdlp_exe = resolve_ytdlp_executable()
        self.ffmpeg_dir = resolve_ffmpeg_dir()

    def run(self):
        try:
            self._run_download()
        finally:
            self._processes.stop()
            self._processes.wait()

    def _run_download(self):
        if not ensure_ytdlp_exists(
            str(self.ytdlp_exe),
            self.status_signal,
            self.log_signal,
            self.progress_signal,
            cancel_cb=lambda: not self.is_running,
        ):
            self.status_signal.emit("❌ Không thể tải bộ máy yt-dlp!")
            self.finished_signal.emit(0)
            return

        self.progress_signal.emit(0, max(1, len(self.links)))
        _run_ytdlp_update_step(
            self.ytdlp_exe,
            self._processes,
            self.status_signal,
            self.log_signal,
            force=self.force_update,
            is_running_cb=lambda: self.is_running,
        )
        if not self.is_running:
            self.finished_signal.emit(0)
            return

        dl_opts = download_options(self.options)
        fmt_choice = str(dl_opts.get("format", "Video MP4"))
        res_choice = str(dl_opts.get("resolution", "1080p"))
        quality_choice = normalize_quality_choice(dl_opts.get("quality", ORIGINAL))

        success_count = 0
        fail_count = 0
        total = len(self.links)
        seen_names: dict[str, int] = {}

        for idx, link in enumerate(self.links):
            if not self.is_running:
                break
            raw_name = "" if self.auto_title else (self.names[idx].strip() if idx < len(self.names) else "")
            item_auto_title = self.auto_title or not raw_name
            custom_name = ""
            if not item_auto_title:
                sanitized = sanitize_folder_name(raw_name)
                key = sanitized.casefold()
                count = seen_names.get(key, 0) + 1
                seen_names[key] = count
                custom_name = f"{sanitized} ({count})" if count > 1 else sanitized

            display_name = custom_name or f"Link #{idx + 1} (Tự lấy tiêu đề gốc)"
            self.status_signal.emit(f"Đang tải ({idx + 1}/{total}): {display_name}")
            self.log_signal.emit(f"\n📥 BẮT ĐẦU TẢI {idx + 1}/{total}: {display_name}")
            self.log_signal.emit(f"⚙️ Cấu hình: {fmt_choice} | {res_choice} | {quality_choice}")

            cmd = build_studio_download_command(
                str(self.ytdlp_exe),
                self.save_path,
                custom_name,
                link,
                self.options,
                auto_title=item_auto_title,
                cookies_browser=self.cookies_browser,
                ffmpeg_dir=self.ffmpeg_dir,
            )

            try:
                proc = self._processes.track(
                    subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=_NO_WINDOW,
                    )
                )
                for line in iter(proc.stdout.readline, ""):
                    if not self.is_running:
                        proc.terminate()
                        break
                    clean = line.strip()
                    if not clean:
                        continue
                    if clean.startswith(FILE_PRINT_PREFIX):
                        saved_path = clean[len(FILE_PRINT_PREFIX):].strip()
                        if saved_path:
                            self.resolved_title_signal.emit(idx, Path(saved_path).stem)
                        continue
                    self.log_signal.emit(clean)
                proc.stdout.close()
                rc = proc.wait()
                self._processes.release(proc)

                if rc == 0 and self.is_running:
                    success_count += 1
                    self.progress_signal.emit(success_count, total)
                    self.row_result_signal.emit(idx, True)
                    self.log_signal.emit(f"✅ THÀNH CÔNG: {display_name}")
                elif self.is_running:
                    fail_count += 1
                    self.fail_signal.emit(fail_count, total)
                    self.row_result_signal.emit(idx, False)
                    self.log_signal.emit(f"❌ THẤT BẠI: Lỗi khi tải {display_name}")
            except Exception as exc:
                fail_count += 1
                self.fail_signal.emit(fail_count, total)
                self.row_result_signal.emit(idx, False)
                self.log_signal.emit(f"🧨 NGOẠI LỆ: {exc}")

        self.finished_signal.emit(success_count)

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        self._processes.stop()
