import os
import subprocess
from PySide6.QtCore import QThread, Signal
from .yt_dlp import ensure_ytdlp_exists
from control.worker_lifecycle import OwnedProcesses
from download_core.download_options import ORIGINAL, build_download_command, download_options, quality_note

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
            "quality": ORIGINAL,
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

            # Keep the existing batch/worker lifecycle; only command policy changes.
            dl_opts = download_options(self.options)
            fmt_choice = dl_opts.get("format", "Video MP4")
            res_choice = dl_opts.get("resolution", "1080p")
            quality_choice = dl_opts.get("quality", ORIGINAL)
            self.log_signal.emit(f"⚙️ Cấu hình: {fmt_choice} | {res_choice} | {quality_choice}")
            self.log_signal.emit(quality_note(fmt_choice, quality_choice))
            cmd = build_download_command(self.ytdlp_exe, self.save_path, name, link, self.options)

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
                    self.log_signal.emit(f"✅ THÀNH CÔNG: Đã lưu {name} ({fmt_choice}; định dạng theo nguồn/chất lượng đã chọn)")
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
        """Retain resumable files; this job does not own other folder contents."""
        self.log_signal.emit("ℹ️ Giữ file tải dở để có thể tiếp tục; không xóa file tạm của tác vụ khác.")
