import sys
from pathlib import Path
import os

# Xóa bỏ QStandardPaths vì mình làm bản Portable, không cần lưu vào AppData của Windows
def project_root() -> Path:
    """Lấy đường dẫn gốc của App, dù là chạy code hay chạy EXE"""
    if getattr(sys, 'frozen', False):
        # Nếu đã đóng gói thành file .exe bằng PyInstaller
        # sys._MEIPASS là thư mục _internal của PyInstaller
        # Nhưng storage cần ở cạnh EXE, không trong _internal
        # Nên trả về thư mục chứa EXE
        return Path(sys.executable).parent
    
    # Nếu đang code, lùi lại 1 cấp từ folder 'app' ra thư mục gốc dự án
    return Path(__file__).resolve().parents[1]


def input_dir() -> Path:
    p = project_root() / "input"
    p.mkdir(exist_ok=True)
    return p


def temp_dir() -> Path:
    p = project_root() / "temp_test_ai"
    p.mkdir(exist_ok=True)
    return p


def storage_dir() -> Path:
    """Bản Portable: Lưu mọi thứ vào thư mục storage ngay tại gốc App"""
    p = project_root() / "storage"
    p.mkdir(exist_ok=True)
    return p


def models_dir() -> Path:
    """Thêm hàm này để quản lý folder Model cho chuẩn bác nhé"""
    p = project_root() / "models"
    p.mkdir(exist_ok=True)
    return p


def asset_dir(asset_name: str = None) -> Path:
    """
    Lấy đường dẫn ASSET (icon, hình ảnh, DLL) từ Bundle của PyInstaller hoặc Dev folder.
    
    Khi PyInstaller bundle app:
    - Asset được đặt trong _internal/ (sys._MEIPASS)
    
    Khi chạy từ Python:
    - Asset nằm ở project_root()
    
    Args:
        asset_name: Tên asset (e.g., 'icon/app_icon.ico', 'image.png')
        
    Returns:
        Path đến asset
    """
    if getattr(sys, 'frozen', False):
        # Chạy từ EXE - Asset nằm trong _internal/
        base_path = Path(sys._MEIPASS)
    else:
        # Chạy từ Python - Asset nằm ở project root
        base_path = project_root()
    
    if asset_name:
        return base_path / asset_name
    return base_path


def get_icon_path(icon_name: str = "app_icon.ico") -> Path:
    """Trả về đúng đường dẫn icon dù chạy từ Python hay EXE"""
    return asset_dir(f"icon/{icon_name}")


def get_input_path(filename: str) -> Path:
    return input_dir() / filename


def init_folders() -> None:
    """Khởi tạo tất cả các thư mục cần thiết"""
    try:
        input_dir()
        temp_dir()
        storage_dir()
        models_dir()
    except Exception as e:
        # Safe print for PyInstaller (sys.stdout might be None)
        try:
            print(f"⚠️ Lỗi khởi tạo thư mục: {e}")
        except:
            pass  # Silently ignore if printing fails

# Chạy khởi tạo ngay khi App nạp file này
init_folders()