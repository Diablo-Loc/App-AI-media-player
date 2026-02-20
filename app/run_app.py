import multiprocessing
import sys
import logging
import shutil
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from pipeline.utils import TempFileManager

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
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None

    # 2. (Tùy chọn) Kiểm tra xem có file .exe để cạnh file chạy không
    # (Hữu ích khi đóng gói portable)
    local_ffmpeg = Path("ffmpeg.exe").exists()
    local_ffprobe = Path("ffprobe.exe").exists()

    if (ffmpeg_ok or local_ffmpeg) and (ffprobe_ok or local_ffprobe):
        return True
    
    return False
def main():
    setup_logging()

    # ✅ 1. Tạo QApplication TẠI ĐÂY (chỉ 1 lần duy nhất)
    app = QApplication(sys.argv)

    # 2. Kiểm tra FFmpeg
    if not check_system_dependencies():
        QMessageBox.critical(
            None, 
            "Thiếu thư viện quan trọng",
            "❌ Lỗi: Không tìm thấy FFmpeg hoặc FFprobe!\n\n"
            "Ứng dụng cần FFmpeg để xử lý video và âm thanh.\n"
            "Vui lòng cài đặt FFmpeg vào biến môi trường PATH hoặc copy file 'ffmpeg.exe' và 'ffprobe.exe' vào cùng thư mục với ứng dụng."
        )
        sys.exit(1) # Thoát ngay lập tức
    
    # ==================================================
    # 🔥 STORAGE
    # ==================================================
    storage_root = Path("storage")
    storage_root.mkdir(exist_ok=True)
    
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