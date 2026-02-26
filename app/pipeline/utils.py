import shutil
import uuid
import re
from pathlib import Path
from paths import storage_dir
import socket

class TempFileManager:
    # 📁 Đường dẫn lưu trữ: use centralized storage_dir()/temp_cache
    TEMP_DIR = storage_dir() / "temp_cache"

    @staticmethod
    def initialize():
        """
        🔥 GỌI 1 LẦN DUY NHẤT LÚC KHỞI ĐỘNG APP (trong main.py).
        Mục đích: Xóa sạch rác của lần chạy trước (do crash, tắt máy đột ngột...).
        """
        if TempFileManager.TEMP_DIR.exists():
            try:
                # Xóa toàn bộ thư mục và file bên trong
                shutil.rmtree(TempFileManager.TEMP_DIR)
                print(f"🧹 Startup: Đã dọn sạch thư mục rác: {TempFileManager.TEMP_DIR}")
            except Exception as e:
                # Có thể file đang bị khóa bởi tiến trình khác, bỏ qua để tránh crash app
                print(f"⚠️ Startup: Không thể xóa rác cũ: {e}")

        # Tạo lại thư mục sạch sẽ (tự tạo cả folder cha 'storage' nếu thiếu)
        TempFileManager.TEMP_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def create_unique_path(extension=".wav") -> Path:
        """
        Sinh ra đường dẫn file DUY NHẤT.
        Ví dụ: storage/temp_cache/audio_a1b2c3d4.wav
        -> Giúp chạy nhiều tab/thread cùng lúc mà không bị lỗi ghi đè file.
        """
        # Đảm bảo thư mục luôn tồn tại (phòng trường hợp người dùng xóa tay khi app đang chạy)
        if not TempFileManager.TEMP_DIR.exists():
            TempFileManager.TEMP_DIR.mkdir(parents=True, exist_ok=True)

        # Tạo tên file ngẫu nhiên dùng UUID
        filename = f"audio_{uuid.uuid4().hex[:8]}{extension}"
        return TempFileManager.TEMP_DIR / filename

    @staticmethod
    def safe_delete(path):
        """
        Xóa file an toàn (dùng trong khối finally).
        Không bao giờ gây crash app dù file không tồn tại hoặc bị khóa.
        """
        if not path: return
        
        target = Path(path)
        if target.exists():
            try:
                target.unlink() # Lệnh xóa file
                # print(f"♻️ Đã dọn dẹp file tạm: {target.name}")
            except PermissionError:
                print(f"🔒 File đang bị khóa (Windows sẽ tự xóa sau): {target.name}")
            except Exception as e:
                print(f"❌ Lỗi khi xóa file tạm: {e}")

#kiểm tra kết nối mạng
def is_connected():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except OSError:
        return False

import re

import re

def clean_song_title(title):
    if not title: return ""

    # 1. Xóa toàn bộ nội dung trong ngoặc (kể cả ngoặc Nhật 【】)
    # Đây là bước quan trọng nhất để xóa chữ "歌ってみた"
    title = re.sub(r'[【\[\(\{\].*?[】\]\)\}]', '', title)

    # 2. Danh sách các từ khóa rác (Thêm các biến thể tiếng Nhật)
    garbage = [
        r'covered\s+by.*', r'cv[:.].*', r'official', r'video', r'music',
        r'歌ってみた', r'ver\.', r'full', r'version', r'lyrics', r'feat\.', r'ft\.'
    ]
    for kw in garbage:
        title = re.sub(kw, '', title, flags=re.IGNORECASE)

    # 3. Chỉ giữ lại chữ cái, số, khoảng trắng và dấu gạch ngang ngăn cách
    # Giữ lại dải ký tự tiếng Nhật (Hiragana, Katakana, Kanji)
    title = re.sub(r'[^\w\s\-\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', ' ', title)

    # 4. Dọn dẹp dấu gạch ngang thừa ở đầu/cuối và khoảng trắng
    title = title.strip().strip('-').strip()
    title = " ".join(title.split())

    return title
    