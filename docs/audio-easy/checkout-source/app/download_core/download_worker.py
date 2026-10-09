import os
import subprocess
from PySide6.QtCore import QThread, Signal
from .yt_dlp import ensure_ytdlp_exists
from control.worker_lifecycle import OwnedProcesses

class DownloadWorker(QThread):
    progress_signal = Signal(int, int)   # Báo cáo số lượng thành công
    fail_signal = Signal(int, int)       # Báo cáo số lượng thất bại
    status_signal = Signal(str)          # Đổi text trạng thái ngắn
    finished_signal = Signal(int)        # Báo cáo khi xong tất cả
    log_signal = Signal(str)             # [MỚI] Bắn log của yt-dlp lên Console UI

    def __init__(self, links, names, save_path, options=None):
        super().__init__()
        self._processes = OwnedProcesses()
        self.links = links
        self.names = names
        self.save_path = save_path
        self.options = options if options else {
            "quality": "Extreme (320k)", 
            "format": "Video MP4", 
            "resolution": "1080p",
            "auto_update": True
        }
        self.is_running = True
        
        import sys
        
        # Đường dẫn yt-dlp.exe - tương thích PyInstaller bundle
        if getattr(sys, 'frozen', False):
            self.ytdlp_exe = os.path.join(sys._MEIPASS, "yt-dlp.exe")
        else:
            self.ytdlp_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt-dlp.exe")
            
    def run(self):
        try:
            self._run_download()
        finally:
            self._processes.stop()
            self._processes.wait()

    def _run_download(self):
        if not ensure_ytdlp_exists(
            self.ytdlp_exe, 
            self.status_signal, 
            self.log_signal, 
            self.progress_signal, # Tận dụng luôn progress_signal bác đã có
            cancel_cb=lambda: not self.is_running
        ):
            self.status_signal.emit("❌ Không thể tải bộ máy yt-dlp!")
            self.finished_signal.emit(0)
            return

        # Reset lại thanh progress về 0 sau khi tải xong exe để chuẩn bị tải video
        self.progress_signal.emit(0, 100)
        # ----------------------------------------------------
        # 1. CẬP NHẬT YT-DLP (-U) TRƯỚC KHI TẢI
        # ----------------------------------------------------
        self.status_signal.emit("Đang kiểm tra cập nhật yt-dlp...")
        self.log_signal.emit("🔄 [HỆ THỐNG] Đang kiểm tra cập nhật yt-dlp...")
        
        try:
            update_proc = self._processes.track(subprocess.Popen(
                [self.ytdlp_exe, "-U"],
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW # Ẩn cửa sổ đen của Windows
            ))
            # Đọc log update theo thời gian thực
            for line in iter(update_proc.stdout.readline, ''):
                if line:
                    self.log_signal.emit(line.strip())
            update_proc.stdout.close()
            update_proc.wait()
            self._processes.release(update_proc)
        except Exception as e:
            self.log_signal.emit(f"⚠️ [LỖI CẬP NHẬT] {e}")

        if not self.is_running:
            return

        # ----------------------------------------------------
        # 2. VÒNG LẶP TẢI VIDEO THEO LOGIC FILE .BAT CŨ
        # ----------------------------------------------------
        success_count = 0
        fail_count = 0
        total = len(self.links)

        for i, (link, name) in enumerate(zip(self.links, self.names)):
            if not self.is_running: break

            # --- [GIỮ NGUYÊN LOGIC LOG CỦA BÁC] ---
            self.status_signal.emit(f"Đang tải: {name} ({i+1}/{total})")
            self.log_signal.emit(f"\n==========================================")
            self.log_signal.emit(f"📥 BẮT ĐẦU TẢI {i+1}/{total}: {name}")
            self.log_signal.emit(f"==========================================")

            # 1. Lấy thông số từ UI
            dl_opts = self.options.get("download", self.options)
            fmt_choice = dl_opts.get("format", "Video MP4")
            res_choice = dl_opts.get("resolution", "1080p")
            quality_choice = dl_opts.get("quality", "Extreme (320k)")
            # --------------------

            self.log_signal.emit(f"⚙️ Cấu hình: {fmt_choice} | {res_choice} | {quality_choice}")

            # 2. Xử lý các biến cơ bản (Chỉ giữ lại biến đường dẫn và độ phân giải Video)
            res_map = {"4K": "2160", "2K": "1440", "1080p": "1080", "720p": "720"}
            target_res = res_map.get(res_choice, "1080")
            out_path = os.path.join(self.save_path, f"{name}.%(ext)s")
            
            cmd = []
            
            # 3. PHÂN NHÁNH CMD THEO LỰA CHỌN ĐỊNH DẠNG
            
            # 🔥 Đưa biến format lên TRƯỚC chuỗi if-elif để tránh lỗi SyntaxError của Python
            video_fmt_any = f"bv*[height<={target_res}]+ba/b"
            video_fmt_safe_mp4 = f"bv*[height<={target_res}]+ba[ext=m4a]/b[ext=mp4]/b"

            # =========================================================
            # NHÓM A: TẢI ÂM THANH (AUDIO)
            # =========================================================
            if "Audio" in fmt_choice and "Opus" in quality_choice:
                # Nhánh A1: Audio Opus gốc (Không convert)
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-metadata", 
                    "-f", "ba",
                    "-x", "--audio-format", "opus", 
                    "--no-keep-video",
                    "-o", out_path, link
                ]
            elif "Audio" in fmt_choice and "Extreme" in quality_choice:
                # Nhánh A2: Nhạc 320k (Ghi cứng 320k)
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata",
                    "-f", "ba",
                    "-x", "--audio-format", "mp3", "--audio-quality", "320K",
                    "--postprocessor-args", "ExtractAudio:-b:a 320k", # Lệnh bài ép cứng
                    "--no-keep-video",
                    "-o", out_path, link
                ]
            elif "Audio" in fmt_choice and "Standard" in quality_choice:
                # Nhánh A3: Nhạc 192k (Ghi cứng 192k)
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata",
                    "-f", "ba[ext=m4a]", # Chỉ định lấy luôn bản m4a của YouTube
                    "-x", "--audio-format", "m4a",
                    "--no-keep-video",
                    "-o", out_path, link
                ]
            elif "Audio" in fmt_choice:
                # Nhánh A4: Nhạc 128k (Cơ bản)
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata",
                    "-f", "ba",
                    "-x", "--audio-format", "mp3", "--audio-quality", "128K",
                    "--postprocessor-args", "ExtractAudio:-b:a 128k", # Lệnh bài ép cứng
                    "--no-keep-video",
                    "-o", out_path, link
                ]
            
            # =========================================================
            # NHÓM B: TẢI VIDEO MKV (GIỮ NGUYÊN BẢN 100% TỪ YOUTUBE) - [MỚI THÊM]
            # =========================================================
            elif "Video MKV" in fmt_choice:
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata", "--parse-metadata", "playlist_index:%(n)s",
                    "-f", video_fmt_any, 
                    "--merge-output-format", "mkv",
                    "-o", out_path, link
                ]
              
            # =========================================================
            # NHÓM C: TẢI VIDEO MP4 (TƯƠNG THÍCH MỌI THIẾT BỊ)
            # =========================================================            
            elif "Video MP4" in fmt_choice and "Opus" in quality_choice:
                # 🎧 B1: BEST (AAC 320k)
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata", "--parse-metadata", "playlist_index:%(n)s",
                    "-f", video_fmt_safe_mp4,
                    "--merge-output-format", "mp4",
                    "--postprocessor-args", "ffmpeg:-c:a aac -b:a 160k",
                    "-o", out_path, link
                ]

            elif "Video MP4" in fmt_choice and "Extreme" in quality_choice:
                # 🔥 B2: EXTREME (AAC ~192k)
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata", "--parse-metadata", "playlist_index:%(n)s",
                    "-f", video_fmt_safe_mp4,
                    "--merge-output-format", "mp4",
                    "--postprocessor-args", "ffmpeg:-c:a aac -b:a 320k",
                    "-o", out_path, link
                ]

            # ⚖ B3: STANDARD (MP4 + M4A Gốc - KHÔNG CONVERT)
            elif "Video MP4" in fmt_choice and "Standard" in quality_choice:
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata", "--parse-metadata", "playlist_index:%(n)s",
                    "-f", video_fmt_safe_mp4,
                    "--merge-output-format", "mp4",
                    "-o", out_path, link
                ]

            elif "Video MP4" in fmt_choice and "Low" in quality_choice:
                # 📉 B4: LOW (AAC ~128k)
                cmd = [
                    self.ytdlp_exe,
                    "--no-mtime", "--no-playlist", "--clean-infojson",
                    "--embed-thumbnail", "--embed-metadata", "--parse-metadata", "playlist_index:%(n)s",
                    "-f", video_fmt_any,
                    "--merge-output-format", "mp4",
                    "--postprocessor-args", "ffmpeg:-c:a aac -b:a 128k",
                    "-o", out_path, link
                ]
            
            # 5. Đường dẫn lưu file
            cmd += ["-o", os.path.join(self.save_path, f"{name}.%(ext)s"), link]
            
            try:
                process = self._processes.track(subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW
                ))

                # Đọc log yt-dlp (tiến trình %, MB, Tốc độ) đẩy lên UI
                for line in iter(process.stdout.readline, ''):
                    if not self.is_running: # Nếu user bấm Dừng
                        process.terminate()
                        break
                    
                    if line:
                        # Gửi từng dòng text lên UI
                        self.log_signal.emit(line.strip())

                process.stdout.close()
                return_code = process.wait()
                self._processes.release(process)

                # Kiểm tra kết quả
                if return_code == 0 and self.is_running:
                    success_count += 1
                    self.progress_signal.emit(success_count, total)
                    self.log_signal.emit(f"✅ THÀNH CÔNG: Đã lưu {name}.mp4")
                elif self.is_running:
                    fail_count += 1
                    self.fail_signal.emit(fail_count, total)
                    self.log_signal.emit(f"❌ THẤT BẠI: Lỗi khi tải {name}")

            except Exception as e:
                fail_count += 1
                self.fail_signal.emit(fail_count, total)
                self.log_signal.emit(f"🧨 NGOẠI LỆ: {e}")

        self.cleanup_temp_files()
        self.finished_signal.emit(success_count)

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        self._processes.stop()
        try:
            # Nếu đang có tiến trình chạy, ép nó dừng luôn để dọn dẹp cho nhanh
            if hasattr(self, 'process') and self.process.poll() is None:
                self.process.terminate() 
        except:
            pass
    
    def cleanup_temp_files(self):
        """Quét thư mục lưu trữ và xóa các file tạm dở dang"""
        self.log_signal.emit("🧹 [HỆ THỐNG] Đang dọn dẹp file tạm...")
        temp_extensions = (".part", ".ytdl", ".temp")
        try:
            for file in os.listdir(self.save_path):
                if file.endswith(temp_extensions):
                    file_path = os.path.join(self.save_path, file)
                    try:
                        os.remove(file_path)
                        self.log_signal.emit(f"🗑️ Đã xóa file tạm: {file}")
                    except Exception as e:
                        # File có thể đang bị tiến trình khác chiếm dụng, bỏ qua
                        continue
        except Exception as e:
            self.log_signal.emit(f"⚠️ Lỗi khi dọn dẹp: {e}")
