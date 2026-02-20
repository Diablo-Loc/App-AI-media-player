import sys
import time
import traceback
import multiprocessing 
from PySide6.QtCore import QThread, Signal

# =========================================================================
# HÀM WRAPPER (CHẠY TRONG PROCESS CON)
# =========================================================================
def _ai_process_wrapper(input_path, output_dir, media_id, queue):
    """
    Process con: Load Torch -> Chạy -> Trả về -> Tự hủy -> GPU được giải phóng.
    """
    try:
        # --- CÁC HÀM CALLBACK ---
        def proxy_progress_cb(percent, message):
            queue.put(("progress", percent, message))

        def proxy_cancel_cb():
            return False

        # --- LAZY IMPORT (CHỈ LOAD KHI PROCESS NÀY CHẠY) ---
        import torch
        from ai.pipeline import run_ai_pipeline

        # --- CHẠY PIPELINE ---
        result = run_ai_pipeline(
            input_path=input_path,
            output_dir=output_dir,
            media_id=media_id,
            progress_cb=proxy_progress_cb,
            cancel_cb=proxy_cancel_cb,
            device_policy="auto",
        )
        
        # --- GỬI KẾT QUẢ VỀ ---
        queue.put(("finished", result))
        time.sleep(1.0)
        
    except Exception as e:
        # Bắt lỗi chi tiết
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        queue.put(("failed", tb))

# =========================================================================
# CLASS AIWORKER (MAIN PROCESS)
# =========================================================================
class AIWorker(QThread):
    started = Signal(str)           
    progress = Signal(int, str)     
    data_ready = Signal(str, list)    
    failed = Signal(str, str)       

    def __init__(self, media_id: str, input_path: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.media_id = media_id
        self.input_path = input_path
        self.output_dir = output_dir 
        self._cancelled = False
        self._process = None 

    def run(self):
        self.started.emit(self.media_id)
        
        queue = multiprocessing.Queue()
        ctx = multiprocessing.get_context('spawn') # Bắt buộc cho PyTorch/Windows

        # Khởi tạo Process con
        self._process = ctx.Process(
            target=_ai_process_wrapper,
            kwargs={
                "input_path": self.input_path,
                "output_dir": self.output_dir,
                "media_id": self.media_id,
                "queue": queue
            }
        )
        self._process.start()

        # Vòng lặp chính: Chạy cho đến khi xong việc hoặc bị dừng
        # Thêm isInterruptionRequested() để hỗ trợ hàm stop()
        while not self.isInterruptionRequested():
            
            # 1. Kiểm tra Cancel thủ công
            if self._cancelled:
                break 

            # 2. Kiểm tra nếu Process con chết đột ngột
            if not self._process.is_alive() and queue.empty():
                self.failed.emit(self.media_id, "Lỗi: AI Process bị dừng đột ngột.")
                break

            # 3. Đọc tin nhắn từ Queue
            try:
                # Timeout 0.1s để vòng lặp quay lại check điều kiện dừng
                msg = queue.get(timeout=0.1) 
                msg_type = msg[0]

                if msg_type == "progress":
                    self.progress.emit(msg[1], msg[2])

                elif msg_type == "finished":
                    result = msg[1]
                    segments = result.get("segments", []) if result else []
                    self.data_ready.emit(self.media_id, segments)
                    break 

                elif msg_type == "failed":
                    error_trace = msg[1]
                    self.failed.emit(self.media_id, error_trace)
                    break 

            except multiprocessing.queues.Empty:
                pass # Không có tin, tiếp tục vòng lặp

        # Cleanup khi thoát vòng lặp
        self._cleanup_process()

    # =========================
    # CONTROL
    # =========================
    def cancel(self):
        """Hủy nhẹ nhàng (đặt cờ)"""
        self._cancelled = True

    def stop(self):
        """
        🛑 QUAN TRỌNG: Dừng Thread an toàn.
        Gọi hàm này trước khi đóng App hoặc chuyển bài để tránh lỗi QThread Destroyed.
        """
        if self.isRunning():
            self._cancelled = True      # 1. Đặt cờ hủy
            self.requestInterruption()  # 2. Yêu cầu Qt ngắt
            self.wait()                 # 3. CHỜ (Block) cho đến khi run() thoát hẳn
            
    def _cleanup_process(self):
        """Giết process con và thu hồi tài nguyên"""
        if self._process:
            if self._process.is_alive():
                self._process.terminate() # Kill process con
            self._process.join()          # Chờ OS dọn dẹp
            self._process = None