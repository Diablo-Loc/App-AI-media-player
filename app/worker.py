import sys

# 🔥 FIX PyInstaller issue: sys.stdout/stderr can be None in subprocess
# Create a safe wrapper that implements isatty() for transformers library
class SafeStdout:
    def __init__(self, original=None):
        self.original = original or sys.stderr
    
    def write(self, msg):
        try:
            if self.original and hasattr(self.original, 'write'):
                self.original.write(msg)
        except:
            pass
    
    def flush(self):
        try:
            if self.original and hasattr(self.original, 'flush'):
                self.original.flush()
        except:
            pass
    
    def isatty(self):
        """transformers lib calls this - always return False for non-TTY"""
        return False

if sys.stdout is None or not hasattr(sys.stdout, 'isatty'):
    sys.stdout = SafeStdout(sys.stderr)
if sys.stderr is None or not hasattr(sys.stderr, 'isatty'):
    sys.stderr = SafeStdout()

import time
import traceback
import multiprocessing
import os
from PySide6.QtCore import QThread, Signal

# =========================================================================
# HÀM WRAPPER (CHẠY TRONG PROCESS CON)
# =========================================================================
def _ai_process_wrapper(input_path, output_dir, media_id, queue):
    """
    Process con: Load Torch -> Chạy -> Trả về -> Tự hủy -> GPU được giải phóng.
    """
    try:
        import os
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

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
        # Lấy traceback chi tiết
        error_msg = traceback.format_exc()
        
        # Ghi vào file log ngay tại thư mục chứa file EXE
        # Dùng mode "a" để ghi nối tiếp, không bị ghi đè
        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n--- ERROR AT {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            f.write(error_msg)
            f.write("-" * 30 + "\n")
            
        queue.put(("failed", error_msg))

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
        self._queue = None
                    
    def run(self):
        self.started.emit(self.media_id)
        
        queue = multiprocessing.Queue()
        self._queue = queue
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
        """Dừng process con an toàn và giải phóng queue/refs."""
        process = self._process
        queue = self._queue

        try:
            if process is not None:
                if getattr(process, "is_alive", lambda: False)():
                    try:
                        process.terminate()
                    except Exception:
                        try:
                            process.kill()
                        except Exception:
                            pass
                try:
                    process.join(timeout=3)
                except Exception:
                    pass
        finally:
            if queue is not None:
                try:
                    queue.close()
                except Exception:
                    pass
                try:
                    queue.join_thread()
                except Exception:
                    pass

            self._process = None
            self._queue = None
            self._cancelled = False