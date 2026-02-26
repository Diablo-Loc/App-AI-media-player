import sys
import os
from pathlib import Path
from paths import get_input_path, temp_dir
from PySide6.QtCore import QObject, QCoreApplication, Signal

# =========================================================
# 1. FIX DLL NVIDIA (Bắt buộc để chạy CUDA)
# =========================================================
def fix_nvidia_dlls():
    for path in sys.path:
        if "site-packages" in path:
            nvidia_path = os.path.join(path, "nvidia")
            if os.path.exists(nvidia_path):
                bins = [
                    os.path.join(nvidia_path, "cublas", "bin"),
                    os.path.join(nvidia_path, "cudnn", "bin"),
                ]
                for b in bins:
                    if os.path.exists(b):
                        try:
                            os.add_dll_directory(b)
                        except Exception: pass
                        # SỬA DÒNG NÀY: os.pathsep thay vì os.environ.pathsep
                        os.environ["PATH"] = b + os.pathsep + os.environ["PATH"]

fix_nvidia_dlls()

# Thử import AIWorker sau khi đã fix DLL
try:
    from worker import AIWorker
except ImportError:
    from app.worker import AIWorker

# =========================================================
# 2. MOCK CLASSES (Dựa trên bản test UI đã chạy ngon của bác)
# =========================================================
class MockSubtitleManager:
    def __init__(self):
        # Tạo folder temp để AI có chỗ xuất file .ass
        self.dirs = {"temp": temp_dir()}
        self.dirs["temp"].mkdir(parents=True, exist_ok=True)

    def get_path(self, media_id, ext):
        return self.dirs["temp"] / f"{media_id}.{ext}"
    
    def get_reliable_id(self, path):
        return Path(path).stem

    def save_data(self, media_id, data):
        """Hàm này AIWorker sẽ gọi khi hoàn thành dịch"""
        path = self.get_path(media_id, "ass")
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        print(f"\n💾 [Mock] Đã lưu phụ đề vào: {path}")

# Biến toàn cục để tránh Garbage Collector xóa Worker khi đang chạy
global_worker = None

# =========================================================
# 3. CHƯƠNG TRÌNH CHÍNH
# =========================================================
def test_run():
    global global_worker
    app = QCoreApplication(sys.argv)

    # ĐƯỜNG DẪN VIDEO: ưu tiên env override, fallback sang `app.paths` input dir
    video_path = os.environ.get("TEST_VIDEO_PATH") or str(get_input_path("【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！.mp4"))

    if not os.path.exists(video_path):
        print(f"❌ LỖI: Không tìm thấy file tại: {video_path}")
        return

    media_id = Path(video_path).stem
    sub_manager = MockSubtitleManager()

    print(f"🚀 --- BẮT ĐẦU TEST AI (CUDA MODE) ---")
    print(f"🎬 Video: {media_id}")
    print(f"📂 Thư mục tạm: {sub_manager.dirs['temp']}")

    # Khởi tạo Worker thực tế
    global_worker = AIWorker(video_path, media_id, sub_manager)

    # Kết nối tín hiệu để theo dõi quá trình
    global_worker.progress_signal.connect(lambda p: print(f"📊 Tiến độ: {p}%"))
    global_worker.log_signal.connect(lambda l: print(f"📝 Log AI: {l}"))
    
    def on_finished(m_id, ass_path):
        print(f"\n" + "="*30)
        print(f"✅ THÀNH CÔNG RỒI BÁC ƠI!")
        print(f"📍 File ASS thực tế: {ass_path}")
        print("="*30)
        
        # Đọc thử vài dòng cuối để kiểm tra kết quả dịch
        try:
            with open(ass_path, "r", encoding="utf-8") as f:
                content = f.readlines()
                print("\n👀 Xem thử nội dung cuối file:")
                print("".join(content[-5:])) 
        except Exception as e:
            print(f"Không thể đọc file: {e}")
            
        app.quit()

    def on_error(err):
        print(f"\n❌ LỖI TRONG QUÁ TRÌNH CHẠY AI:")
        print(f"⚠️ Chi tiết: {err}")
        app.quit()

    global_worker.finished_signal.connect(on_finished)
    global_worker.error_signal.connect(on_error)

    # Bắt đầu chạy Thread AI
    global_worker.start()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    test_run()