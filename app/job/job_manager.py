# app/job/job_manager.py

import os
import subprocess
import threading
import logging
from pathlib import Path
from queue import Queue, Empty
from typing import Dict, Any, Optional

from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool

from job.job_state import JobState
from core.subtitle_manager import SubtitleStatus
from paths import storage_dir

logger = logging.getLogger("JobManager")


# ============================================================
# 🔹 THUMBNAIL WORKER
# ============================================================

class WorkerSignals(QObject):
    finished = Signal(str)
    error = Signal(str)


class ThumbnailWorker(QRunnable):
    def __init__(self, video_path: str, output_path: str):
        super().__init__()
        self.setAutoDelete(True)
        self.video_path = video_path
        self.output_path = output_path
        self.signals = WorkerSignals()

    def run(self):
        try:
            if not os.path.exists(self.output_path):
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", "00:00:01",
                    "-i", self.video_path,
                    "-vframes", "1",
                    "-vf", "scale=320:-1",
                    "-q:v", "2",
                    self.output_path
                ]
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True
                )
            self.signals.finished.emit(self.output_path)
        except Exception as e:
            logger.error(f"Thumbnail error: {e}")
            self.signals.error.emit(str(e))


# ============================================================
# 🔹 JOB MANAGER (CORE)
# ============================================================

class JobManager(QObject):
    # ---- Signals cho UI / Controller ----
    job_updated = Signal(str, dict)          # media_id, job_data
    log_received = Signal(str)               # log text
    thumbnail_done = Signal(str, str)        # media_id, thumb_path

    def __init__(self, subtitle_manager):
        super().__init__()

        self.subtitle_mgr = subtitle_manager

        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        # ---- Thumbnail pool ----
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4)

        # ---- AI queue (GPU SAFE) ----
        self._running = True
        self._current_job_id: Optional[str] = None

        self.ai_queue: Queue = Queue()
        self.ai_thread = threading.Thread(
            target=self._ai_worker_loop,
            daemon=True
        )
        self.ai_thread.start()

    # ========================================================
    # 🔹 THUMBNAIL API
    # ========================================================

    def extract_thumbnail_async(self, media_id: str, video_path: str):
        output_dir = storage_dir() / "thumbnails"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{media_id}.jpg"

        if output_path.exists():
            self.thumbnail_done.emit(media_id, str(output_path))
            return

        worker = ThumbnailWorker(str(video_path), str(output_path))

        def on_finished(path: str):
            try:
                self.thumbnail_done.emit(media_id, path)
            except RuntimeError:
                pass
            finally:
                worker.signals.finished.disconnect(on_finished)

        worker.signals.finished.connect(on_finished)
        self.thread_pool.start(worker)

    # ========================================================
    # 🔹 JOB REQUEST
    # ========================================================

    def request_job(self, media_item):
        media_id = self.subtitle_mgr.get_reliable_id(media_item.path)
        if not media_id:
            return None

        with self._lock:
            if media_id in self.jobs:
                return self.jobs[media_id]

            res = self.subtitle_mgr.request_subtitle(media_item)

            job = {
                "media_id": media_id,
                "state": JobState.PENDING,
                "progress": 0.0,
                "path": None,
                "error": None
            }

            if res.status == SubtitleStatus.READY:
                job["state"] = JobState.DONE
                job["progress"] = 1.0
                job["path"] = str(res.ass_path)
            else:
                job["state"] = JobState.QUEUED
                self.ai_queue.put((media_id, media_item))

            self.jobs[media_id] = job
            self.job_updated.emit(media_id, job.copy())
            return job

    # ========================================================
    # 🔹 CANCEL JOB (KHI ĐỔI BÀI)
    # ========================================================

    def cancel_job(self, media_id: str):
        """
        Chỉ đánh dấu cancel.
        Không kill thread – AI sẽ tự bỏ kết quả.
        """
        with self._lock:
            if media_id in self.jobs:
                self.jobs[media_id]["state"] = JobState.CANCELLED
                self.job_updated.emit(media_id, self.jobs[media_id].copy())

        if self._current_job_id == media_id:
            logger.info(f"⛔ Cancel AI job: {media_id}")

    # ========================================================
    # 🔹 AI WORKER LOOP (GPU SAFE – 1 JOB)
    # ========================================================

    def _ai_worker_loop(self):
        while self._running:
            try:
                item = self.ai_queue.get(timeout=1)
                if item is None:
                    break

                media_id, media_item = item
                self._current_job_id = media_id

                # Bỏ nếu đã cancel trước khi chạy
                if self._is_cancelled(media_id):
                    self.ai_queue.task_done()
                    continue

                try:
                    from ai.whisper_engine import run_ai_pipeline
                    from core.subtitle_renderer import ASSRenderer

                    self._update_job(
                        media_id,
                        state=JobState.RUNNING,
                        progress=0.1
                    )
                    self.log_received.emit(
                        f"🤖 AI xử lý: {Path(media_item.path).name}"
                    )

                    # -------- HEAVY AI --------
                    raw_data = run_ai_pipeline(media_item.path)

                    if self._is_cancelled(media_id):
                        continue

                    self._update_job(media_id, progress=0.85)

                    # -------- SAVE & RENDER --------
                    self.subtitle_mgr.save_raw_data(media_id, raw_data)
                    ass_path = self.subtitle_mgr.get_path(media_id, "ass")

                    ASSRenderer.generate(
                        raw_data.get("segments", []),
                        ass_path
                    )

                    if self._is_cancelled(media_id):
                        continue

                    self._update_job(
                        media_id,
                        state=JobState.DONE,
                        progress=1.0,
                        path=str(ass_path)
                    )
                    self.log_received.emit("✅ AI hoàn tất")

                except Exception as e:
                    logger.exception("AI Error")
                    self._update_job(
                        media_id,
                        state=JobState.ERROR,
                        error=str(e)
                    )

                finally:
                    self._current_job_id = None
                    self.ai_queue.task_done()

            except Empty:
                continue

    # ========================================================
    # 🔹 INTERNAL HELPERS
    # ========================================================

    def _is_cancelled(self, media_id: str) -> bool:
        with self._lock:
            return (
                media_id in self.jobs and
                self.jobs[media_id]["state"] == JobState.CANCELLED
            )

    def _update_job(self, media_id: str, **kwargs):
        with self._lock:
            if media_id in self.jobs:
                self.jobs[media_id].update(kwargs)
                self.job_updated.emit(media_id, self.jobs[media_id].copy())

    # ========================================================
    # 🔹 SHUTDOWN
    # ========================================================

    def stop(self):
        self._running = False
        try:
            self.ai_queue.put_nowait(None)
        except Exception:
            pass
        if self.ai_thread.is_alive():
            self.ai_thread.join(timeout=2)

        try:
            self.ai_queue.put_nowait(None)
        except Exception:
            pass

        try:
            self.ai_queue.join()
        except Exception:
            pass
