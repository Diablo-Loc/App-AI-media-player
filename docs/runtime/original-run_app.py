import ctypes
import multiprocessing
import os
import io
import sys
import logging
import shutil
from pathlib import Path

if os.name == "nt":
    os.environ["PYTHONIOENCODING"] = "utf-8"

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# =====================================================================
# 🌟 CẤU HÌNH ĐƯỜNG DẪN BẤT BIẾN (TỰ CO GIÃN THEO MÔI TRƯỜNG)
# =====================================================================
if getattr(sys, 'frozen', False):
    # Khi đã đóng gói thành file EXE, app_resources nằm ngay cạnh file EXE
    APP_ROOT = os.path.dirname(sys.executable)
else:
    # Khi chạy code thô .py trong môi trường phát triển (VS Code)
    current_file_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(current_file_path)
    
    # BẪY TỰ ĐỘNG: Nếu file chạy nằm trong thư mục app/ thì lùi 2 cấp, nếu ở gốc thì lùi 1 cấp
    if os.path.basename(current_dir) == "app":
        APP_ROOT = os.path.dirname(current_dir)
    else:
        APP_ROOT = current_dir

# =====================================================================
# 🗃️ 1. ĐỒNG BỘ MÔI TRƯỜNG AI DI ĐỘNG (PYTHONPATH)
# =====================================================================
PORTABLE_LIBS_DIR = os.path.join(APP_ROOT, "app_resources", "libs")

if os.path.exists(PORTABLE_LIBS_DIR):
    if PORTABLE_LIBS_DIR not in sys.path:
        sys.path.insert(0, PORTABLE_LIBS_DIR)
    
    # CHỐT CHẶN CHO .EXE: Ép đường dẫn này để Process con tự động thừa kế
    os.environ["PYTHONPATH"] = PORTABLE_LIBS_DIR + os.pathsep + os.environ.get("PYTHONPATH", "")
    print(f"✅ [Hệ thống] Đã khóa mục tiêu môi trường AI di động: {PORTABLE_LIBS_DIR}")
else:
    print(f"⚠️ [Hệ thống] Chưa phát hiện thư mục libs di động tại: {PORTABLE_LIBS_DIR}")

# =====================================================================
# 🛠️ 2. ÉP GHIM THƯ MỤC BIN (FFMPEG) VÀO PATH HỆ THỐNG (SỬA LỖI WINERROR 2)
# =====================================================================
# Định vị thư mục bin chứa 3 file exe (ffmpeg, ffprobe, ffplay)
BIN_DIR = os.path.join(APP_ROOT, "bin")

if os.path.exists(BIN_DIR):
    # CƯỠNG ÉP nạp thư mục bin vào đầu biến PATH. 
    # Mẹo này giúp bất kỳ đoạn code nào gọi 'ffmpeg' đều chạy trực tiếp được luôn!
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")
    print(f"✅ [Hệ thống] Đã đồng bộ bộ công cụ xử lý âm thanh tự động: {BIN_DIR}")
else:
    # Thử quét thêm trường hợp nằm trong app_resources/bin phòng hờ
    ALT_BIN_DIR = os.path.join(APP_ROOT, "app_resources", "bin")
    if os.path.exists(ALT_BIN_DIR):
        os.environ["PATH"] = ALT_BIN_DIR + os.pathsep + os.environ.get("PATH", "")
        print(f"✅ [Hệ thống] Đã đồng bộ bộ công cụ xử lý âm thanh (Dự phòng): {ALT_BIN_DIR}")
    else:
        print(f"⚠️ [Hệ thống] Không tìm thấy thư mục bin chứa FFmpeg tại: {BIN_DIR}")

# =====================================================================
# 3. FIX PyInstaller issue & Exception Handling
# =====================================================================
if sys.stdout is None:
    import io
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

def global_exception_handler(exctype, value, traceback):
    logging.error("Unhandled Exception:", exc_info=(exctype, value, traceback))
    if QApplication.instance():
        QMessageBox.critical(None, "Lỗi Hệ Thống", f"Đã xảy ra lỗi:\n{value}")
    sys.__excepthook__(exctype, value, traceback)
    sys.exit(1)

sys.excepthook = global_exception_handler

# 4. Imports core (Bây giờ import cực kỳ an toàn vì PATH và PYTHONPATH đã setup xong)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from pipeline.utils import TempFileManager
from paths import storage_dir, get_icon_path, asset_dir, project_root

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
    """ Kiểm tra an toàn hệ thống dựa trên PATH đã được ghim động """
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    ffprobe_ok = shutil.which("ffprobe") is not None
    return ffmpeg_ok and ffprobe_ok

# --- Main Entry ---
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