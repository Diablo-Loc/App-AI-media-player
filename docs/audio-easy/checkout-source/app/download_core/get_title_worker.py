import os
import subprocess
import sys
import yt_dlp  # Thư viện nhúng
from PySide6.QtCore import QThread, Signal

from .utils import sanitize_folder_name
from .yt_dlp import ensure_ytdlp_exists
from control.worker_lifecycle import OwnedProcesses

class GetTitleWorker(QThread):
    title_ready_signal = Signal(str)
    finished_signal = Signal()
    status_signal = Signal(str)
    log_signal = Signal(str)
    progress_signal = Signal(int, int)

    def __init__(self, links):
        super().__init__()
        self._processes = OwnedProcesses()
        self.links = links
        self.is_running = True
        import sys
        
        # Đường dẫn yt-dlp.exe - tương thích PyInstaller bundle
        if getattr(sys, 'frozen', False):
            self.ytdlp_exe = os.path.join(sys._MEIPASS, "yt-dlp.exe")
        else:
            self.ytdlp_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "yt-dlp.exe")

    def run(self):
        try:
            self._run_titles()
        finally:
            self._processes.stop()
            self._processes.wait()

    def _run_titles(self):
        # 1. Kiểm tra sự tồn tại của file exe (đảm bảo bộ máy sẵn sàng)
        if not ensure_ytdlp_exists(
            self.ytdlp_exe, 
            self.status_signal, 
            self.log_signal, 
            self.progress_signal,
            cancel_cb=lambda: not self.is_running
        ):
            self.status_signal.emit("❌ Không thể khởi tạo bộ máy!")
            self.finished_signal.emit()
            return

        self.progress_signal.emit(0, 100)        

        # 2. Cập nhật file EXE
        if self.is_running:
            self.status_signal.emit("Đang kiểm tra cập nhật bộ máy...")
            try:
                startupinfo = None
                creationflags = 0
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                # Cập nhật nhân EXE chính
                process = self._processes.track(subprocess.Popen([self.ytdlp_exe, "-U"], startupinfo=startupinfo, creationflags=creationflags))
                process.wait()
                self._processes.release(process)
                self.log_signal.emit("✅ Bộ máy EXE đã được cập nhật.")
            except Exception as e:
                self.log_signal.emit(f"⚠️ Cập nhật EXE lỗi: {e}")

        # 3. Cấu hình ydl_opts (Gom lại 1 lần duy nhất)
        ydl_opts = {
            'socket_timeout': 10,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'nocheckcertificate': True,
            'encoding': 'utf-8', 
            # Mẹo: Ép thư viện Python dùng file EXE vừa update làm engine xử lý chính
            'ffmpeg_location': self.ytdlp_exe, 
        }

        for i, link in enumerate(self.links):
            if not self.is_running: break
            
            self.status_signal.emit(f"🔍 Đang lấy tên video {i+1}/{len(self.links)}...")
            
            # Trong vòng lặp lấy tên của GetTitleWorker
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(link, download=False)
                    raw_title = info_dict.get('title', 'Video_Untitled')

                # LỌC TÊN Ở ĐÂY
                safe_title = sanitize_folder_name(raw_title)

                if safe_title:
                    self.title_ready_signal.emit(safe_title) # Gửi tên đã sạch về UI
                    self.log_signal.emit(f"✅ {safe_title}")

            except Exception as e:
                msg = str(e).split('\n')[0]
                self.log_signal.emit(f"❌ Lỗi link {i+1}: {msg}")
                self.title_ready_signal.emit(f"Lỗi: {msg}")
        
        self.status_signal.emit("✅ Đã lấy xong danh sách tên.")
        self.finished_signal.emit()

    def stop(self):
        self.is_running = False
        self.requestInterruption()
        self._processes.stop()
