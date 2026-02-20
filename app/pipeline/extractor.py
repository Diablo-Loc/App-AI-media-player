import subprocess
import os
from pathlib import Path

def extract_audio(input_path: str, output_path: str):
    """
    Trích audio chuẩn hóa cho Whisper: Mono, 16kHz, WAV.
    """
    input_p = Path(input_path)
    output_p = Path(output_path)

    if not input_p.exists():
        raise FileNotFoundError(f"Không tìm thấy file đầu vào: {input_p}")

    # Đảm bảo thư mục lưu trữ tồn tại
    output_p.parent.mkdir(parents=True, exist_ok=True)

    # Lệnh FFmpeg tối ưu
    cmd = [
        "ffmpeg",
        "-y",                   # Ghi đè file cũ
        "-i", str(input_p.absolute()), # Dùng đường dẫn tuyệt đối cho chắc chắn
        "-vn",                  # Loại bỏ video
        "-acodec", "pcm_s16le", # Codec wav chuẩn
        "-ac", "1",             # Chuyển về Mono
        "-ar", "16000",         # Tần số lấy mẫu 16kHz
        "-loglevel", "error",   # Chỉ hiện lỗi, ẩn log rác
        str(output_p.absolute())
    ]

    try:
        print(f"🎵 Đang trích xuất âm thanh: {input_p.name}...")
        # Sử dụng shell=True trên Windows đôi khi giúp tránh lỗi đường dẫn có khoảng trắng
        # nhưng ở đây list cmd là đủ an toàn.
        # Cấu hình ẩn cửa sổ CMD trên Windows
        startupinfo = None
        if os.name == 'nt': # Nếu là Windows
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE # Ẩn cửa sổ

        subprocess.run(
            cmd, 
            check=True, 
            capture_output=True, 
            startupinfo=startupinfo
        )
        return True
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode()
        print(f"❌ Lỗi FFmpeg: {error_msg}")
        return False

    except Exception as e:
        # Lỗi lạ khác
        print(f"❌ Lỗi không xác định khi tách âm thanh: {e}")
        return False