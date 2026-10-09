# app/control/app_controller.py
from PySide6.QtCore import QObject, Slot, Signal, QUrl, QSettings, QFileInfo, QStandardPaths, QUrl, QTimer
from PySide6.QtMultimedia import QMediaPlayer
import logging
import gc
#import torch
import os

from core.subtitle_manager import SubtitleStatus
from thumbnail.thumbnail_workers import ThumbnailWorker
logger = logging.getLogger(__name__)


class AppController(QObject):
    """
    AppController
    - Điều phối UI ↔ MediaPlayer ↔ SubtitleManager ↔ AIController
    - UI TUYỆT ĐỐI không chạy AI
    """

    # Forward thumbnail cho UI
    thumbnail_ready = Signal(str, str)  # media_id, thumb_path

    def __init__(self, window, media_library, job_manager, subtitle_manager):
        super().__init__()

        # ==============================
        # DEPENDENCIES
        # ==============================
        self.window = window
        self.media_lib = media_library
        self.ai = job_manager
        self.subtitle_mgr = subtitle_manager

        # ==============================
        # PLAYER
        # ==============================
        self.player: QMediaPlayer = self.window.media_player.player

        # ==============================
        # STATE
        # ==============================
        self.current_media_id: str | None = None
        self.current_media_item = None 

        # THUMBNAIL WORKER
        self.thumb_worker = None
        self._thumb_pending = False
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self.start_thumbnail_scan)
        
        # ==============================
        # AI SIGNALS
        # ==============================
        self.ai.job_finished.connect(self._on_ai_done)
        self.ai.job_failed.connect(self._on_ai_failed)
        self.ai.status_changed.connect(self._on_ai_status)

        logger.info("✅ AppController initialized")
    
    # =========================================================
    # QUẢN LÝ THUMBNAIL
    # =========================================================
    def start_thumbnail_scan(self):
        """
        Bắt đầu chạy quét thumbnail ngầm cho toàn bộ danh sách.
        Hàm này nên được gọi từ MainWindow sau khi refresh_grid().
        """
        # Nếu đang chạy thì dừng cái cũ
        if self.thumb_worker and self.thumb_worker.isRunning():
            self._thumb_pending = True
            self.thumb_worker.cancel()
            return

        self._thumb_pending = False

        if not self.media_lib.items:
            return

        logger.info("🚀 Starting background thumbnail scan...")
        
        # Khởi tạo Worker với danh sách item hiện tại
        self.thumb_worker = ThumbnailWorker(self.media_lib)
        
        # Nối dây tín hiệu: Worker tìm thấy -> Báo cho Controller -> Controller báo cho UI
        # (Cách này giúp UI không cần biết Worker là ai, chỉ cần nghe Controller)
        self.thumb_worker.thumbnail_ready.connect(self.thumbnail_ready.emit)
        self.thumb_worker.finished.connect(self._thumbnail_scan_finished)
        self.thumb_worker.finished.connect(self.thumb_worker.deleteLater)
        
        self.thumb_worker.start()

    def stop_thumbnail_scan(self):
        self._thumb_pending = False
        self._thumb_timer.stop()
        if self.thumb_worker:
            self.thumb_worker.stop()
            self.thumb_worker.wait()
            self.thumb_worker = None

    @Slot()
    def _thumbnail_scan_finished(self):
        if self.sender() is not self.thumb_worker:
            return
        self.thumb_worker = None
        if self._thumb_pending:
            self._thumb_timer.start(0)
    
    # =========================================================
    # UI → CONTROLLER
    # =========================================================
    def on_media_item_clicked(self, media_item, force_gen=False):
        """
        Xử lý khi chọn video.
        :param media_item: Object chứa thông tin video
        :param force_gen: True = Bắt buộc chạy lại AI (Ghi đè), False = Ưu tiên cache
        """
        # 1. Kiểm tra đầu vào
        if not media_item:
            print("❌ Media Item is None")
            return
            
        video_path = str(media_item.path)

        if not os.path.isfile(video_path):
            logger.error(f"❌ File không tồn tại: {video_path}")
            return

        # ===== CACHE MEDIA ITEM =====
        self.current_media_item = media_item

        # ===== CẬP NHẬT GIAO DIỆN PLAYBACK BAR (MỚI THÊM) =====
        # Cập nhật Title và Artist lên thanh điều khiển
        # (Giả sử playback_bar nằm trong self.window)
        if hasattr(self.window, "playback_bar"):
            self.window.playback_bar.set_media_info(media_item.title, media_item.artist,item_data=self.current_media_item)

        # ===== HỦY AI CŨ =====
        self.ai.cancel()

        # ===== PLAYER (muốn controller điều khiển play thì bỏ comment)=====
        #self.player.stop()
        #self.player.setSource(QUrl.fromLocalFile(video_path))
        #self.player.play()

        # ===== RESET SUB UI =====
        sub = getattr(self.window, "sub_layer", None)
        if sub:
            sub.load_subtitles([])
            sub.clear()
            sub.hide()

        # ===== MEDIA ID =====
        # Lấy ID trực tiếp từ metadata (nhanh hơn tính lại)
        media_id = media_item.id 
        self.current_media_id = media_id

        logger.info(f"▶️ Playing: {media_item.title} (Force Mode: {force_gen})")

        # =================================================
        # CHỈ SubtitleManager ĐƯỢC QUYẾT ĐỊNH
        # =================================================
        # TRƯỜNG HỢP 1: Bị ép chạy lại (Reload Button)
        if force_gen:
            logger.info(f"⚡ FORCE GEN: Bỏ qua cache, bắt buộc chạy lại AI cho {media_id}")
            self._show_status("🤖 Đang tạo lại phụ đề (Force Mode)...")
            self.ai.start(
                media_id=media_id,
                input_path=video_path
            )
            return
        
        # TRƯỜNG HỢP 2: Chạy bình thường (Kiểm tra file cũ trước)
        result = self.subtitle_mgr.request_subtitle(media_item)

        if result.status == SubtitleStatus.READY:
            logger.info("📄 Subtitle READY → load")
            if self._load_subtitle_to_ui(media_id) is False:
                self._show_status("ℹ️ Chưa nhận diện được lời (có thể là nhạc không lời).")
            else:
                self._show_status("📄 Phụ đề có sẵn")
            return

        if result.status == SubtitleStatus.NEED_AI:
            self._show_status("🤖 Đang tạo phụ đề AI...")
            self.ai.start(
                media_id=media_id,
                input_path=video_path
            )

    # =========================================================
    # AI CALLBACKS
    # =========================================================
    @Slot(str, list)
    def _on_ai_done(self, media_id: str, segments: list):
        if media_id != self.current_media_id:
            logger.warning("⚠️ AI xong nhưng media đã đổi → bỏ qua")
            return

        logger.info("✅ AI subtitle hoàn tất")

        # ===== 1. LƯU SUBTITLE (CẬP NHẬT MỚI) =====
        # Lấy lại đường dẫn gốc từ biến đã cache
        source_path = str(self.current_media_item.path) if self.current_media_item else None
        
        # ===== 2. LƯU JSON (CỰC QUAN TRỌNG) =====
        saved_path = self.subtitle_mgr.save_segments(
            media_id=media_id,
            segments=segments,
            source_path=source_path 
        )
        if not saved_path:
            self._show_status("❌ Không lưu được phụ đề. Vui lòng kiểm tra thư mục lưu.")
            return

        # ===== 3. RENDER ASS =====
       #success = self.subtitle_mgr.render_ass_from_json(media_id)
        """ if not success:
            logger.error("❌ Render ASS thất bại")
            self._show_status("❌ Lỗi tạo file phụ đề")
            return
        """
        # ===== 3. LOAD VÀO UI =====
        self._load_subtitle_to_ui(media_id)
        if segments:
            self._show_status("✨ Phụ đề AI sẵn sàng")
        else:
            self._show_status("ℹ️ Đã lưu kết quả rỗng: chưa nhận diện được lời.")

        # ===== CLEAN GPU =====
        gc.collect()
        #if torch.cuda.is_available():
        #    torch.cuda.empty_cache()
        #os.environ["CUDA_VISIBLE_DEVICES"] = ""


    @Slot(str, str)
    def _on_ai_failed(self, media_id, error):
        if media_id != self.current_media_id:
            return
        logger.error(f"❌ AI lỗi: {error}")
        self._show_status(f"❌ AI lỗi: {error}")

    @Slot(str, str)
    def _on_ai_status(self, media_id, message):
        if media_id == self.current_media_id:
            self._show_status(message)

    # =========================================================
    # SUBTITLE → UI
    # =========================================================
    def _load_subtitle_to_ui(self, media_id):
        segments = self.subtitle_mgr.get_segments_for_ui(media_id)

        sub = getattr(self.window, "sub_layer", None)
        if not sub:
            logger.warning("⚠️ Không có sub_layer")
            return

        sub.load_subtitles(segments)
        if not segments:
            sub.clear()
            sub._smart_hide(instant=True)
            return False
        sub.show()
        sub.raise_()
        sub.center_at_bottom()
        return True

    # =========================================================
    # STATUS BAR
    # =========================================================
    def _show_status(self, message):
        if self.window.statusBar():
            self.window.statusBar().showMessage(message, 5000)
        logger.info(f"📢 {message}")

    # =========================================================
    # CONTROL
    # =========================================================
    def cancel_current_job(self):
        self.ai.cancel()

    # =========================================================
    # CLEAN EXIT
    # =========================================================
    def cleanup_on_exit(self):
        logger.info("🧹 AppController cleanup")
        self.ai.cancel()
        self.player.stop()

        self.stop_thumbnail_scan()
        gc.collect()
        #if torch.cuda.is_available():
        #    torch.cuda.empty_cache()
    
    def set_playlist(self, new_list):
        """Đồng bộ danh sách từ giao diện vào hệ thống điều hướng ngầm"""
        self.active_playlist = list(new_list) # Khớp với tên biến trong _navigate_active_playlist
        logger.info(f"📋 Đã chốt Playlist mới: {len(self.active_playlist)} bài")
