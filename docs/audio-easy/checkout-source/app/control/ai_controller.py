import os
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox
# Không cần import gc hay torch ở đây nữa vì Worker xử lý ở Process riêng
# from worker import AIWorker # <--- Đảm bảo import đúng đường dẫn worker của bạn
from worker import AIWorker # Ví dụ nếu bạn để file worker trong control

_RESOURCE_CHECK_CACHE = {"checked": False, "ready": False}


def _set_resource_cache_state(checked: bool, ready: bool):
    _RESOURCE_CHECK_CACHE["checked"] = checked
    _RESOURCE_CHECK_CACHE["ready"] = ready
    AIWorker._is_ai_cached_ready = ready


def _get_resource_cache_state() -> dict:
    return _RESOURCE_CHECK_CACHE


class AIController(QObject):
    """
    AIController
    - Quản lý vòng đời của AIWorker.
    - Đảm bảo Worker cũ tắt hẳn trước khi chạy cái mới.
    - CHẶN ĐẦU ĐẦU LÒNG: Tự động phát hiện thiếu thư viện và gọi UI cài đặt,
      bất kể là do bấm nút hay do hệ thống tự động chuyển bài gọi tới.
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
        self._resource_checked = _RESOURCE_CHECK_CACHE["checked"]
        self._resource_ready = _RESOURCE_CHECK_CACHE["ready"]
        self._pending_start = None
        self._closing = False
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._start_pending)

    # =========================
    # PUBLIC API
    # =========================
    def start(self, media_id: str, input_path: str):
        """
        Bắt đầu job mới. Cửa ngõ trung tâm kiểm soát an toàn hệ thống.
        """
        if self._closing:
            return
        # 🌟 Luồng check nhẹ theo cờ + cache đúng 1 lần cho mỗi phiên chạy.
        from download_core.download_source_app import check_resource_status, _set_resource_ready_flag, _get_resource_ready_flag

        self._resource_checked = _RESOURCE_CHECK_CACHE["checked"]
        self._resource_ready = _RESOURCE_CHECK_CACHE["ready"]

        if not self._resource_checked:
            status = check_resource_status()
            self._resource_ready = bool(status.get("ready", False))
            self._resource_checked = True

            if self._resource_ready:
                _set_resource_ready_flag(True)
                _set_resource_cache_state(True, True)
            else:
                flag_ready = _get_resource_ready_flag()
                if flag_ready:
                    _set_resource_ready_flag(False)
                _set_resource_cache_state(True, False)
                QMessageBox.warning(
                    None, "Chưa cài đặt Core AI",
                    "Hệ thống phát hiện thiết bị chưa cài đặt cấu hình AI xử lý phụ đề (Torch/Whisper).\n\n"
                    "Ứng dụng sẽ tự động kích hoạt Trình cấu hình di động ngay bây giờ!"
                )
                try:
                    from download_core.download_source_app import ResourceDownloadDialog
                    dialog = ResourceDownloadDialog()
                    if dialog.exec() != QDialog.Accepted:
                        self._resource_checked = False
                        self._resource_ready = False
                        _set_resource_cache_state(False, False)
                        self.job_failed.emit(media_id, "Yêu cầu xử lý bị hủy do thiếu thư viện Core AI.")
                        return
                except Exception as e:
                    self._resource_checked = False
                    self._resource_ready = False
                    _set_resource_cache_state(False, False)
                    QMessageBox.critical(None, "Lỗi khởi tạo", f"Không thể nạp giao diện cài đặt: {str(e)}")
                    return
        elif not self._resource_ready:
            self.job_failed.emit(media_id, "Yêu cầu xử lý bị hủy do thiếu thư viện Core AI.")
            return

        # ---------------------------------------------------------
        # KHU VỰC CHẠY AN TOÀN (CHỈ ĐẾN ĐƯỢC ĐÂY KHI LIBS ĐÃ ĐẦY ĐỦ)
        # ---------------------------------------------------------
        # 1. Xử lý Worker cũ (QUAN TRỌNG ĐỂ SỬA LỖI CRASH)
        if self._worker is not None:
            try:
                if self._worker.isRunning():
                    self.status_changed.emit(
                        self._current_media_id or self._worker.media_id,
                        "⚠️ Đang dừng tác vụ cũ..."
                    )
                    self._pending_start = (media_id, input_path)
                    self._current_media_id = None
                    self._worker.cancel()
                    return
            except RuntimeError:
                pass

            try:
                self._worker.disconnect()
            except Exception:
                pass

            try:
                self._worker.deleteLater()
            except Exception:
                pass
            self._worker = None

        # 2. Thiết lập trạng thái mới
        self._pending_start = None
        self._restart_timer.stop()
        self._current_media_id = media_id

        # 3. Khởi tạo Worker mới
        # (Lưu ý: Truyền đúng tham số như bạn đã định nghĩa bên Worker)
        self._worker = AIWorker(
            media_id=media_id,
            input_path=input_path,
            output_dir=self.output_dir
        )

        # 4. Kết nối tín hiệu
        try:
            self._worker.started.connect(self._on_started)
            self._worker.progress.connect(self._on_progress)
            self._worker.data_ready.connect(self._on_data_ready)
            self._worker.failed.connect(self._on_failed)
            self._worker.finished.connect(self._on_thread_stopped)
            self._worker.finished.connect(self._worker.deleteLater)
        except RuntimeError:
            pass
        # 5. Chạy
        self._worker.start()

    def cancel(self):
        """Huỷ job hiện tại (dùng nút Cancel trên UI)"""
        self._pending_start = None
        self._restart_timer.stop()
        if self._worker and self._worker.isRunning():
            self.status_changed.emit(
                self._current_media_id or self._worker.media_id,
                "⛔ Đang huỷ xử lý AI..."
            )
            self._worker.cancel() # Đánh dấu hủy
            self._current_media_id = None
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
        """Hàm này được gọi khi tắt App để dừng worker AI một cách an toàn."""
        self._closing = True
        self._pending_start = None
        self._restart_timer.stop()
        if self._worker and self._worker.isRunning():
            print("🛑 Controller: Đang yêu cầu dừng Worker Thread...")
            self._worker.cancel()
            self._worker.stop()

        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

        self._current_media_id = None
    # =========================
    # WORKER CALLBACKS
    # =========================
    @Slot(str)
    def _on_started(self, media_id: str):
        if not self._accept_worker(): return
        if media_id != self._current_media_id: return
        self.status_changed.emit(media_id, "🤖 AI đang khởi động...")

    @Slot(int, str)
    def _on_progress(self, percent: int, message: str):
        if not self._accept_worker(): return
        if media_id := self._current_media_id: # Python 3.8+ walrus operator
            self.progress_updated.emit(percent)
            self.status_changed.emit(media_id, message)

    @Slot(str, list)
    def _on_data_ready(self, media_id: str, segments: list):
        if not self._accept_worker(): return
        if media_id != self._current_media_id: return
        self.job_finished.emit(media_id, segments)
        #self._cleanup_ref()

    @Slot()
    def _on_thread_stopped(self):
        """Hàm này được gọi khi Worker đã thực sự tắt hẳn"""
        if self.sender() is not None and self.sender() is not self._worker:
            return
        if self._worker and not self._worker.isRunning():
            self._worker = None
            self._current_media_id = None
            if self._pending_start and not self._closing:
                self._restart_timer.start(0)
            # print("✅ Worker đã được dọn dẹp an toàn.")
            
    @Slot(str, str)
    def _on_failed(self, media_id: str, error_msg: str):
        if not self._accept_worker(): return
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

    def _accept_worker(self):
        sender = self.sender()
        return (not self._closing and self._pending_start is None
                and (sender is None or sender is self._worker)
                and not getattr(self._worker, '_cancelled', False))

    def _start_pending(self):
        pending = self._pending_start
        if pending and not self._closing:
            self.start(*pending)
