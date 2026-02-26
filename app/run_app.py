import ctypes
import multiprocessing
import os
import sys
import logging
import shutil
from pathlib import Path

# 🔥 FIX PyInstaller issue: sys.stdout can be None
# This must be before any imports that use print()
if sys.stdout is None:
    import io
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from pipeline.utils import TempFileManager
from paths import storage_dir, input_dir, temp_dir, get_icon_path, asset_dir, project_root

# ===== CORE =====
from core.media_library import MediaLibrary
from core.subtitle_manager import SubtitleManager

# ===== CONTROLLERS =====
from control.ai_controller import AIController
from control.app_controller import AppController

# ===== UI =====
from ui.main_window import MainWindow

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

def check_system_dependencies():
    """
    Kiểm tra xem máy có FFmpeg/FFprobe chưa.
    Trả về True nếu OK, False nếu thiếu.
    """
    # 1. Kiểm tra lệnh trong PATH của Windows
    ffmpeg_in_path = shutil.which("ffmpeg") is not None
    ffprobe_in_path = shutil.which("ffprobe") is not None

    # 2. Kiểm tra trong Asset folder (sys._MEIPASS khi chạy từ EXE)
    asset_folder = asset_dir()
    ffmpeg_in_bundle = (asset_folder / "ffmpeg.exe").exists()
    ffprobe_in_bundle = (asset_folder / "ffprobe.exe").exists()

    # 3. Kiểm tra trong bin/ folder (dev mode - FFmpeg được lưu ở bin/)
    bin_folder = project_root() / "bin"
    ffmpeg_in_bin = (bin_folder / "ffmpeg.exe").exists()
    ffprobe_in_bin = (bin_folder / "ffprobe.exe").exists()

    # 4. Tùy chọn: Kiểm tra cạnh file chạy (cwd relative)
    local_ffmpeg = Path("ffmpeg.exe").exists()
    local_ffprobe = Path("ffprobe.exe").exists()

    ffmpeg_ok = ffmpeg_in_path or ffmpeg_in_bundle or ffmpeg_in_bin or local_ffmpeg
    ffprobe_ok = ffprobe_in_path or ffprobe_in_bundle or ffprobe_in_bin or local_ffprobe

    if ffmpeg_ok and ffprobe_ok:
        return True
    
    return False
def main():
    setup_logging()

    # ✅ 1. Tạo QApplication TẠI ĐÂY (chỉ 1 lần duy nhất)
    app = QApplication(sys.argv)
    
    # 🔥 Thiết lập AppUserModelID để Windows hiển thị icon ở taskbar
    # (Phải làm trước khi tạo window)
    if sys.platform == 'win32':
        try:
            # Sử dụng ctypes để set AppUserModelID (AppID cần match với EXE)
            app_id = 'BoTube.MediaPlayer.1'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception as e:
            print(f"⚠️ Không thể set AppUserModelID: {e}")
    
    # Set app icon (for taskbar, dialogs, etc)
    icon_path = get_icon_path("app_icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
        print(f"✅ Icon loaded from: {icon_path}")
    else:
        print(f"⚠️ Icon not found at: {icon_path}")

    # 2. Kiểm tra FFmpeg
    if not check_system_dependencies():
        bin_folder = project_root() / "bin"
        asset_folder = asset_dir()
        
        error_msg = (
            "❌ Lỗi: Không tìm thấy FFmpeg hoặc FFprobe!\n\n"
            "Ứng dụng cần FFmpeg để xử lý video và âm thanh.\n\n"
            "Cách khắc phục:\n"
            "1️⃣ Cài đặt FFmpeg vào biến môi trường PATH\n"
            "   (Download từ https://ffmpeg.org/download.html)\n\n"
            "2️⃣ Hoặc copy file 'ffmpeg.exe' và 'ffprobe.exe':\n"
        )
        
        # Hiển thị path khác nhau tùy theo mode
        if getattr(sys, 'frozen', False):
            error_msg += f"   Cho EXE: vào thư mục {asset_folder}"
        else:
            error_msg += f"   Cho Dev: vào thư mục {bin_folder}"
            error_msg += f"\n   Hoặc: vào thư mục {asset_folder}"
        
        error_msg += "\n\n3️⃣ Hoặc copy vào cạnh file EXE BoTube.exe"
        
        QMessageBox.critical(
            None, 
            "Thiếu thư viện quan trọng",
            error_msg
        )
        sys.exit(1)  # Thoát ngay lập tức
    
    # ==================================================
    # 🔥 STORAGE
    # ==================================================
    storage_root = storage_dir()
    
    app.setOrganizationName("MyMediaPlayerGroup")
    app.setOrganizationDomain("myvideoplayer.com")
    app.setApplicationName("MyVideoPlayer")
    
    output_folder = str(storage_root)

    # ==================================================
    # CORE
    # ==================================================
    media_library = MediaLibrary()
    subtitle_manager = SubtitleManager(storage_root=output_folder)
    
    # AI Controller nhận output_dir để truyền xuống worker
    ai_controller = AIController(output_dir=output_folder)

    # ==================================================
    # UI
    # ==================================================
    window = MainWindow(
        media_library=media_library,
        job_manager=ai_controller,
        subtitle_manager=subtitle_manager
    )

    # ==================================================
    # APP CONTROLLER
    # ==================================================
    app_controller = AppController(
        window=window,
        media_library=media_library,
        job_manager=ai_controller,
        subtitle_manager=subtitle_manager
    )

    # Gắn ngược controller cho UI
    window.set_app_controller(app_controller)

    window.show()
    
    # ✅ 2. Chạy Event Loop
    sys.exit(app.exec())

if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        TempFileManager.initialize()
    except Exception as e:
        print(f"⚠️ Lỗi khởi tạo TempFileManager: {e}")
    main()