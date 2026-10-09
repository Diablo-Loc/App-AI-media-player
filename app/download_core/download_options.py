"""Source-preserving download policy; no player, settings or process ownership."""
import os

ORIGINAL = "Original (Giữ nguồn)"
QUALITIES = (ORIGINAL, "Extreme (320k)", "High (Opus)",
             "Standard (M4A-ACC)", "Low (128k)")
RESOLUTIONS = {"4K": 2160, "2K": 1440, "1080p": 1080, "720p": 720}


def download_options(options):
    """Accept the existing flat and nested settings, without modifying either."""
    data = options.get("download", options) if isinstance(options, dict) else {}
    return data if isinstance(data, dict) else {}


def quality_note(format_choice, quality_choice):
    if "Video MKV" in format_choice:
        return "MKV giữ audio nguồn tốt nhất yt-dlp chọn; không ép Opus hoặc mã hóa lại."
    if "Audio" in format_choice:
        if "Extreme" in quality_choice or "Low" in quality_choice:
            rate = "320" if "Extreme" in quality_choice else "128"
            return f"Chuyển mã MP3 {rate} kbps để tương thích; không tăng chi tiết so với nguồn."
        if "Opus" in quality_choice:
            return "Chỉ lấy Opus gốc. Nguồn không có Opus: chọn Original; không tự chuyển mã."
        if "Standard" in quality_choice:
            return "Chỉ lấy AAC gốc và đóng gói M4A. Không có AAC: chọn Original."
        return "Giữ file audio nguồn (ví dụ WebM/Opus hoặc M4A/AAC), không chuyển mã."
    if "Low" in quality_choice:
        return "MP4: chuyển mã audio AAC 128 kbps; video giữ nguồn. Có giảm chất lượng audio."
    if "Extreme" in quality_choice or "Standard" in quality_choice:
        return "MP4: ưu tiên AAC gốc, thiếu AAC lấy audio nguồn khác. Không ép bitrate 320k."
    if "Opus" in quality_choice:
        return "MP4: ưu tiên Opus gốc, thiếu Opus lấy audio nguồn khác; không chuyển thành AAC."
    return "Giữ audio nguồn tốt nhất yt-dlp chọn. MP4 có Opus/VP9/AV1 cần thiết bị hỗ trợ codec."


def video_selector(height, audio_candidates):
    # Keep the resolution cap in EVERY fallback. Prefer a separate video track
    # to avoid silently retaining its bundled, lower-quality audio.
    video = f"bv[height<={height}]"
    return "/".join([f"{video}+{audio}" for audio in audio_candidates]
                    + [f"b[height<={height}]"])


def build_download_command(executable, save_path, name, link, options=None):
    data = download_options(options)
    format_choice = data.get("format", "Video MP4")
    quality = data.get("quality", ORIGINAL)
    height = RESOLUTIONS.get(data.get("resolution", "1080p"), 1080)
    cmd = [executable, "--no-mtime", "--no-playlist",
           "--clean-infojson", "--embed-metadata"]
    if "Audio" in format_choice:
        if "Extreme" in quality or "Low" in quality:
            rate = "320K" if "Extreme" in quality else "128K"
            cmd += ["--embed-thumbnail", "-f", "ba/b", "-x",
                    "--audio-format", "mp3", "--audio-quality", rate,
                    "--no-keep-video"]
        elif "Opus" in quality:
            cmd += ["-f", "ba[acodec=opus]/b[acodec=opus]", "-x",
                    "--audio-format", "opus", "--no-keep-video"]
        elif "Standard" in quality:
            cmd += ["--embed-thumbnail", "-f",
                    "ba[acodec^=mp4a]/ba[acodec=aac]/b[acodec^=mp4a]/b[acodec=aac]",
                    "-x", "--audio-format", "m4a", "--no-keep-video"]
        else:
            # No ExtractAudio "best": unsupported source codecs can otherwise
            # silently fall back to MP3 in that postprocessor.
            cmd += ["-f", "ba"]
    else:
        container = "mkv" if "Video MKV" in format_choice else "mp4"
        candidates = ["ba"]
        if container == "mp4" and ("Standard" in quality or "Extreme" in quality):
            candidates = ["ba[acodec^=mp4a]", "ba[acodec=aac]", "ba"]
        elif container == "mp4" and "Opus" in quality:
            candidates = ["ba[acodec=opus]", "ba"]
        cmd += ["--embed-thumbnail", "--parse-metadata", "playlist_index:%(n)s",
                "-f", video_selector(height, candidates),
                "--merge-output-format", container, "--remux-video", container]
        if container == "mp4" and "Low" in quality:
            # Encode ONLY once, in the metadata step (also present for a single
            # progressive MP4). Never attach lossy args to every FFmpeg step.
            cmd += ["--postprocessor-args", "Metadata+ffmpeg_o:-c:a aac -b:a 128k"]
    # URL and output template each appear exactly once. Literal percent signs
    # in a user-provided filename are escaped for yt-dlp's output template.
    filename = name.replace("%", "%%") + ".%(ext)s"
    return cmd + ["-o", os.path.join(save_path, filename), "--", link]
