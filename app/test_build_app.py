import sys
import os
from pathlib import Path

# Đánh lừa toàn bộ hệ thống là app đang chạy dạng EXE
sys.frozen = True
# Trỏ executable về thư mục gốc dự án để test đường dẫn
sys.executable = r"D:\HocTap\11_MusicApp\BoTube_Virtual.exe"

print("=========================================")
print("🧪 ĐANG CHẠY APP TRONG CHẾ ĐỘ GIẢ LẬP EXE HOÀN CHỈNH...")
print("=========================================")

# Thêm thư mục gốc vào sys.path để tránh lỗi ModuleNotFoundError: No module named 'app'
current_dir = Path(__file__).resolve().parent
if str(current_dir.parent) not in sys.path:
    sys.path.insert(0, str(current_dir.parent))

from app.run_app import main

if __name__ == "__main__":
    main()