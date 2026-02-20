from PySide6.QtCore import QObject, Signal, Slot
import gc
import torch
from worker import AIWorker

class AIProcessManager(QObject):
    # =========================
    # SIGNALS (Cập nhật cho khớp với AIController/Worker mới)
    # =========================
    status_changed = Signal(str, str)    # media_id, message
    progress_updated = Signal(int)       # percent
    job_finished = Signal(str, list)     # ✅ Sửa thành list để trả segments về
    job_failed = Signal(str, str)        # media_id, error_msg

    def __init__(self, output_dir: str = "output"):
        super().__init__()
        # Worker mới không cần subtitle_manager, nhưng cần output_dir
        self.output_dir = output_dir 
        self._current_worker = None
        self._current_media_id = None

    def start_process(self, video_path: str, media_id: str):
        if self.is_running():
            self.status_changed.emit(
                media_id,
                "⚠️ Hệ thống đang xử lý bài khác, vui lòng đợi..."
            )
            return

        self._current_media_id = media_id

        # ✅ KHỞI TẠO WORKER VỚI SIGNATURE MỚI
        self._current_worker = AIWorker(
            media_id=media_id,
            input_path=video_path,
            output_dir=self.output_dir # Truyền output_dir xuống
        )

        # ✅ KẾT NỐI SIGNAL MỚI (Tên signal trong worker.py đã đổi)
        self._current_worker.started.connect(self._on_started)
        self._current_worker.progress.connect(self._on_progress)
        self._current_worker.finished.connect(self._on_worker_finished)
        self._current_worker.failed.connect(self._on_worker_error)
        
        # Cleanup khi thread kết thúc
        self._current_worker.finished.connect(self._cleanup_after_worker)
        self._current_worker.failed.connect(self._cleanup_after_worker)

        self._current_worker.start()

    def is_running(self):
        return self._current_worker is not None and self._current_worker.isRunning()

    # =========================
    # HANDLERS
    # =========================
    @Slot(str)
    def _on_started(self, media_id):
        self.status_changed.emit(media_id, "🚀 Bắt đầu xử lý AI...")

    @Slot(int, str)
    def _on_progress(self, percent, msg):
        self.progress_updated.emit(percent)
        self.status_changed.emit(self._current_media_id, msg)

    @Slot(str, list)
    def _on_worker_finished(self, media_id, segments):
        # Phát tín hiệu ra ngoài để AppController bắt lấy và lưu file
        self.job_finished.emit(media_id, segments)

    @Slot(str, str)
    def _on_worker_error(self, media_id, error_msg):
        self.job_failed.emit(media_id, error_msg)

    # =========================
    # CLEANUP
    # =========================
    @Slot()
    def _cleanup_after_worker(self):
        # Hàm này được gọi tự động khi signal finished/failed kích hoạt
        # (Lưu ý: tham số của signal sẽ bị bỏ qua vì Slot này không nhận tham số)
        pass 

    def stop_process(self):
        """Hàm hủy chủ động từ UI"""
        if self._current_worker and self._current_worker.isRunning():
            self.status_changed.emit(self._current_media_id, "⛔ Đang hủy...")
            self._current_worker.cancel()
            # Việc dọn dẹp sẽ diễn ra ở _cleanup_manual
            self._cleanup_manual()

    def _cleanup_manual(self):
        if self._current_worker:
            self._current_worker.quit()
            self._current_worker.wait() # Đợi thread tắt hẳn
            self._current_worker.deleteLater()
            self._current_worker = None

        self._current_media_id = None

        print("🧹 Giải phóng tài nguyên AI")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()