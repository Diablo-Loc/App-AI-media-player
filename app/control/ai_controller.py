import os
from PySide6.QtCore import QObject, Signal, Slot
# Không cần import gc hay torch ở đây nữa vì Worker xử lý ở Process riêng
# from worker import AIWorker # <--- Đảm bảo import đúng đường dẫn worker của bạn
from worker import AIWorker # Ví dụ nếu bạn để file worker trong control

class AIController(QObject):
    """
    AIController
    - Quản lý vòng đời của AIWorker.
    - Đảm bảo Worker cũ tắt hẳn trước khi chạy cái mới.
    """

    # =========================
    # SIGNALS
    # =========================
    status_changed = Signal(str, str)      # media_id, message
    progress_updated = Signal(int)         # percent
    job_finished = Signal(str, list)       # media_id, segments
    job_failed = Signal(str, str)          # media_id, error_msg

    def __init__(self, output_dir: str, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self._worker: AIWorker | None = None
        self._current_media_id: str | None = None

    # =========================
    # PUBLIC API
    # =========================
    def start(self, media_id: str, input_path: str):
        """
        Bắt đầu job mới. Nếu có job cũ đang chạy, nó sẽ bị HUỶ và CHỜ TẮT.
        """
        # 1. Xử lý Worker cũ (QUAN TRỌNG ĐỂ SỬA LỖI CRASH)
        if self._worker is not None:
            if self._worker.isRunning():
                self.status_changed.emit(
                    self._current_media_id, 
                    "⚠️ Đang dừng tác vụ cũ..."
                )
                # Gọi hàm stop() (có wait()) để đảm bảo Thread cũ thoát vòng lặp
                self._worker.stop() 
            
            # Xóa object cũ
            self._worker.deleteLater()
            self._worker = None

        # 2. Thiết lập trạng thái mới
        self._current_media_id = media_id

        # 3. Khởi tạo Worker mới
        # (Lưu ý: Truyền đúng tham số như bạn đã định nghĩa bên Worker)
        self._worker = AIWorker(
            media_id=media_id,
            input_path=input_path,
            output_dir=self.output_dir
        )

        # 4. Kết nối tín hiệu
        self._worker.started.connect(self._on_started)
        self._worker.progress.connect(self._on_progress)
        self._worker.data_ready.connect(self._on_data_ready)
        self._worker.failed.connect(self._on_failed)

        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(self._on_thread_stopped)
        # 5. Chạy
        self._worker.start()

    def cancel(self):
        """Huỷ job hiện tại (dùng nút Cancel trên UI)"""
        if self._worker and self._worker.isRunning():
            self.status_changed.emit(
                self._current_media_id,
                "⛔ Đang huỷ xử lý AI..."
            )
            self._worker.cancel() # Đánh dấu hủy
            # Không cần gọi stop() ở đây để UI không bị đơ, 
            # worker sẽ tự emit failed/finished sau khi cleanup.

    def cancel_and_wait(self):
        """
        Dùng cho MainWindow khi đóng App (closeEvent).
        Bắt buộc phải đợi thread tắt hẳn để không crash.
        """
        if self._worker and self._worker.isRunning():
            self._worker.stop() # Block cho đến khi xong

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def abort_all_jobs(self):
        """Hàm này được gọi khi tắt App"""
        # Nếu bạn đang giữ biến thread, hãy stop nó
        if hasattr(self, "worker_thread") and self.worker_thread.isRunning():
            print("🛑 Controller: Đang yêu cầu dừng Worker Thread...")
            
            # 1. Yêu cầu dừng nhẹ nhàng (kiểm tra cờ isInterruptionRequested)
            self.worker_thread.requestInterruption()
            
            # 2. Ép dừng (Nếu cần thiết - Thread AI thường cứng đầu)
            self.worker_thread.quit()
            self.worker_thread.wait(100) # Chờ 100ms
            
            # Nếu vẫn lỳ không chịu tắt -> Force Kill bằng code đóng App
    # =========================
    # WORKER CALLBACKS
    # =========================
    @Slot(str)
    def _on_started(self, media_id: str):
        if media_id != self._current_media_id: return
        self.status_changed.emit(media_id, "🤖 AI đang khởi động...")

    @Slot(int, str)
    def _on_progress(self, percent: int, message: str):
        if media_id := self._current_media_id: # Python 3.8+ walrus operator
            self.progress_updated.emit(percent)
            self.status_changed.emit(media_id, message)

    @Slot(str, list)
    def _on_data_ready(self, media_id: str, segments: list):
        if media_id != self._current_media_id: return
        self.job_finished.emit(media_id, segments)
        #self._cleanup_ref()

    @Slot()
    def _on_thread_stopped(self):
        """Hàm này được gọi khi Worker đã thực sự tắt hẳn"""
        if self._worker and not self._worker.isRunning():
            self._worker = None
            self._current_media_id = None
            # print("✅ Worker đã được dọn dẹp an toàn.")
            
    @Slot(str, str)
    def _on_failed(self, media_id: str, error_msg: str):
        if media_id != self._current_media_id: return
        self.job_failed.emit(media_id, error_msg)
        #self._cleanup_ref()

    # =========================
    # INTERNAL CLEANUP
    # =========================
    def _cleanup_ref(self):
        """Chỉ xóa tham chiếu, không cần logic Torch phức tạp nữa"""
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        
        self._current_media_id = None
        
        # Vì dùng Multiprocessing, Process con chết là VRAM tự sạch.
        # Main process không load torch nên không cần empty_cache().