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

def storage_dir() -> Path:
    """Bản Portable: Lưu mọi thứ vào thư mục storage ngay tại gốc App"""
    p = project_root() / "storage"
    p.mkdir(exist_ok=True)
    return p

def asset_dir(asset_name: str = None) -> Path:
    """
    Lấy đường dẫn ASSET (icon, hình ảnh, DLL) tự động co giãn thông minh.
    Ưu tiên tìm trong bundle nội bộ, nếu không thấy (do script build ném ra ngoài) 
    thì tự động bẻ lái ra ngoài cạnh file EXE.
    """
    import sys
    
    if getattr(sys, 'frozen', False):
        # 1. Nếu có sys._MEIPASS (Môi trường EXE thật của PyInstaller)
        if hasattr(sys, "_MEIPASS"):
            base_path = Path(sys._MEIPASS)
        else:
            # Dự phòng khi bác chạy file giả lập test.py / run_app.py ép sys.frozen = True
            base_path = Path(sys.executable).parent
            
        # 🎯 CHIÊU ĐỘC: Nếu có asset_name truyền vào (ví dụ: 'icon/app_icon.ico' hoặc 'native/AudioEngineNative.dll')
        if asset_name:
            target_path = base_path / asset_name
            # Nếu tìm trong kén nội bộ _internal KHÔNG CÓ file này
            if not target_path.exists():
                # Tự động bẻ lái đường dẫn ra thư mục ngoài nằm ngang hàng file BoTube.exe
                exe_dir = Path(sys.executable).parent
                return exe_dir / asset_name
    else:
        # Chạy từ Python thô (Dev trong VS Code) - Asset nằm ở project root
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
        storage_dir()
    except Exception as e:
        # Safe print for PyInstaller (sys.stdout might be None)
        try:
            print(f"⚠️ Lỗi khởi tạo thư mục: {e}")
        except:
            pass  # Silently ignore if printing fails

# Chạy khởi tạo ngay khi App nạp file này
init_folders()