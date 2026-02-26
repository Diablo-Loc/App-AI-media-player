import os
import sys
import json
import requests
import subprocess
from pathlib import Path
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import Qt
from paths import storage_dir, project_root, project_root


# URL mặc định trỏ tới file version.json trên GitHub
DEFAULT_VERSION_URL = "https://raw.githubusercontent.com/Diablo-Loc/App-AI-media-player/main/version.json"


def download_and_install(parent):
    """
    Tải và cài đặt bản cập nhật.

    Quy trình mới (bắt đầu từ v1.0.2):
    - Đọc URL metadata (version.json) từ config.json nếu có,
      ngược lại dùng DEFAULT_VERSION_URL.
    - Tải metadata, so sánh phiên bản với file version.json tại project.
    - Nếu metadata.version > local.version → tải download_url (zip/patch) và
      áp cập nhật giống như trước.
    """
    # --- 1. Khởi tạo đường dẫn config ---
    config_path = storage_dir() / "config.json"
    if not config_path.exists():
        config_path = project_root() / "config.json"

    metadata_url = None
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                # có thể cấu hình cả phiên bản metadata hoặc trực tiếp url zip
                metadata_url = config.get("version_url") or config.get("update_url")
        except Exception:
            config = {}
    else:
        config = {}

    if not metadata_url:
        metadata_url = DEFAULT_VERSION_URL

    # --- 2. Tải metadata version.json ---
    try:
        resp = requests.get(metadata_url, timeout=10)
        resp.raise_for_status()
        metadata = resp.json()
    except Exception as e:
        QMessageBox.critical(parent, "Cập nhật", f"Không thể tải thông tin cập nhật: {e}")
        return

    # --- 3. So sánh phiên bản ---
    remote_ver = metadata.get("version")
    local_ver = None
    try:
        with open(project_root() / "version.json", "r", encoding="utf-8") as f:
            local_ver = json.load(f).get("version")
    except Exception:
        local_ver = None

    if local_ver and remote_ver:
        try:
            from packaging.version import Version
            if Version(remote_ver) <= Version(local_ver):
                QMessageBox.information(parent, "Cập nhật", "Bạn đang sử dụng phiên bản mới nhất.")
                return
        except ImportError:
            # nếu không cài packaging, so sánh chuỗi đơn giản
            if remote_ver <= local_ver:
                QMessageBox.information(parent, "Cập nhật", "Bạn đang sử dụng phiên bản mới nhất.")
                return

    # --- 4. Lấy download URL từ metadata ---
    update_url = metadata.get("download_url")
    if not update_url:
        QMessageBox.information(parent, "Cập nhật", "Không có đường dẫn tải về trong metadata.")
        return

    # Save update inside storage dir managed by `paths` helper
    storage = storage_dir()
    save_path = str(storage / "update.zip")

    # Hiển thị thanh tiến trình cho user yên tâm
    progress = QProgressDialog("Đang tải bản cập nhật...", "Hủy", 0, 100, parent)
    progress.setWindowModality(Qt.WindowModal)
    progress.show()

    try:
        response = requests.get(update_url, stream=True)
        total_length = int(response.headers.get('content-length', 0))
        
        with open(save_path, "wb") as f:
            dl = 0
            for data in response.iter_content(chunk_size=4096):
                dl += len(data)
                f.write(data)
                if total_length:
                    done = int(100 * dl / total_length)
                    progress.setValue(done)
                if progress.wasCanceled(): return

        progress.setValue(100)
        
        # --- VERIFY ZIP INTEGRITY ---
        import zipfile
        try:
            with zipfile.ZipFile(save_path, 'r') as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise zipfile.BadZipFile(f"Corrupted entry: {bad}")
        except Exception as ex:
            QMessageBox.critical(parent, "Lỗi cập nhật", f"File cập nhật không hợp lệ: {ex}")
            # remove the bad file and abort without exiting application
            try:
                os.remove(save_path)
            except:
                pass
            return

        # --- BƯỚC QUAN TRỌNG: Kích hoạt file cập nhật theo nền tảng và tắt App ---
        QMessageBox.information(parent, "Xong!", "Tải xong! App sẽ tự khởi động lại để cập nhật.")
        try:
            if sys.platform.startswith("win"):
                # xác định đường dẫn tuyệt đối (cùng cấp với EXE khi đóng gói)
                current_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
                bat_path = current_dir / "update_helper.bat"
                # chạy trong cửa sổ mới để không bị đóng cùng App
                subprocess.Popen([str(bat_path)], shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
            elif sys.platform.startswith("linux") or sys.platform.startswith("darwin"):
                # POSIX script
                current_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
                sh_path = current_dir / "update_helper.sh"
                subprocess.Popen(["/bin/sh", str(sh_path)], shell=False)
            else:
                QMessageBox.information(parent, "Cập nhật", "Không hỗ trợ tự cập nhật trên nền tảng này.")
        except Exception:
            pass
        os._exit(0) # Tắt ngay App để script làm việc

    except Exception as e:
        QMessageBox.critical(parent, "Lỗi", f"Không thể tải bản cập nhật: {e}")