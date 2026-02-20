from PySide6.QtCore import QCoreApplication
import sys
import os

# Import các module cần thiết
from core.subtitle_manager import SubtitleManager 
from control.ai_controller import AIController

def main():
    # 1. Cấu hình môi trường (quan trọng để Qt không báo lỗi plugin khi chạy không giao diện)
    os.environ["QT_QPA_PLATFORM"] = "offscreen" 
    
    app = QCoreApplication(sys.argv)

    # 2. Khởi tạo
    # Tạo thư mục output nếu chưa có
    output_folder = "output"
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # ✅ SỬA LỖI: Truyền chuỗi "output" vào tham số output_dir
    # (Vì AIController cần đường dẫn này để bảo Worker lưu file tạm/file kết quả vào đó)
    ai = AIController(output_dir=output_folder) 
    
    # SubtitleManager dùng để lưu file vào kho dữ liệu chính (storage_test)
    sub_mgr = SubtitleManager(storage_root="storage_test") 

    # 3. Định nghĩa hàm xử lý khi xong
    def on_done(media_id, segments):
        print(f"✅ [AI DONE] ID: {media_id} - Số lượng câu: {len(segments)}")
        
        # Gọi Manager lưu xuống đĩa (vào thư mục storage_test/subtitles/...)
        ass_path = sub_mgr.save_segments(media_id, segments)
        
        if ass_path:
            print(f"💾 [SAVED] File đã lưu vào kho tại: {ass_path}")
        else:
            print("❌ [ERROR] Không lưu được file vào kho!")
            
        # Thoát app sau khi xong
        app.quit()

    # 4. Kết nối tín hiệu
    ai.status_changed.connect(
        lambda mid, msg: print(f"[STATUS] {msg}")
    )
    
    # Kết nối tín hiệu xong việc vào hàm on_done
    ai.job_finished.connect(on_done)
    
    ai.job_failed.connect(
        lambda mid, err: print(f"[ERROR] {err}")
    )

    # 5. Chạy test
    print("🚀 Đang khởi động AI Test...")
    
    # --- CẤU HÌNH FILE INPUT ---
    # Bạn hãy chắc chắn file này tồn tại, hoặc đổi tên thành file có thật trên máy bạn
    test_video = "input/【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！.mp4" 
    # Nếu file tên dài quá có thể gây lỗi đường dẫn trên Windows, hãy thử rename ngắn lại nếu lỗi.
    
    # Kiểm tra file input tồn tại không
    if not os.path.exists(test_video):
        print(f"⚠️ Không tìm thấy file: {test_video}")
        print("👉 Vui lòng sửa biến 'test_video' trong file test_ai_controller.py thành đường dẫn đúng.")
        # Tạo folder input để nhắc nhở
        os.makedirs("input", exist_ok=True)
        sys.exit(1)

    # Bắt đầu chạy
    ai.start(
        media_id="test_001",
        input_path=test_video 
    )

    sys.exit(app.exec())

if __name__ == "__main__":
    main()