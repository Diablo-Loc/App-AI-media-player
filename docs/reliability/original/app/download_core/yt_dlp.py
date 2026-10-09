import os
import urllib.request
import ssl

def ensure_ytdlp_exists(exe_path, status_signal=None, log_signal=None, progress_signal=None):
    if os.path.exists(exe_path):
        # Kiểm tra thêm: nếu file quá nhỏ (ví dụ < 1MB) thì coi như lỗi, tải lại
        if os.path.getsize(exe_path) > 1024 * 1024:
            return True

    tmp_path = exe_path + ".tmp" # Tải vào file tạm
    try:
        if status_signal: status_signal.emit("🚀 Đang khởi tạo tải yt-dlp...")
        if log_signal: log_signal.emit("🌐 [HỆ THỐNG] Đang kết nối GitHub...")

        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

        with urllib.request.urlopen(req, context=context) as response:
            total_size = int(response.getheader('Content-Length', 0))
            downloaded = 0
            block_size = 8192 

            if log_signal: log_signal.emit(f"📦 Dung lượng: {total_size / (1024*1024):.2f} MB")

            with open(tmp_path, 'wb') as out_file:
                while True:
                    buffer = response.read(block_size)
                    if not buffer: break
                    
                    downloaded += len(buffer)
                    out_file.write(buffer)
                    
                    if progress_signal and total_size > 0:
                        progress_signal.emit(downloaded, total_size)
                    
                    if status_signal and total_size > 0:
                        percent = int(downloaded * 100 / total_size)
                        status_signal.emit(f"📥 Đang tải bộ máy: {percent}%")

        # TẢI XONG MỚI ĐỔI TÊN: Đảm bảo file không bị lỗi nửa chừng
        if os.path.exists(exe_path):
            os.remove(exe_path)
        os.rename(tmp_path, exe_path)

        if log_signal: log_signal.emit("✅ Tải hoàn tất!")
        return True
    except Exception as e:
        if os.path.exists(tmp_path): os.remove(tmp_path)
        if log_signal: log_signal.emit(f"❌ Lỗi tải: {e}")
        return False