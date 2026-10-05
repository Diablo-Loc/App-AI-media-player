import os
import sys
import ctypes
import time
import gc
import tracemalloc
import numpy as np
import psutil
from collections import deque

from PySide6.QtCore import QObject, Signal, QTimer, QMetaObject, Qt

# =========================================================
# CALLBACK TYPES
# =========================================================

AUDIO_CALLBACK = ctypes.WINFUNCTYPE(
    None,
    ctypes.POINTER(ctypes.c_float),
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int
)

LOG_CALLBACK = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_char_p
)

MEDIA_BUTTON_CALLBACK = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_int
)

# =========================================================
# SYSTEM MEDIA MANAGER
# =========================================================

class SystemMediaManager(QObject):

    audio_received = Signal(object)

    media_play = Signal()
    media_pause = Signal()
    media_next = Signal()
    media_prev = Signal()

    log_message = Signal(str)

    engine_started = Signal()
    engine_stopped = Signal()
    _flush_signal = Signal()
    
    def __init__(self, parent_window=None):
        super().__init__(parent_window)
        self._flush_signal.connect(
            self._flush_pending_events,
            Qt.ConnectionType.QueuedConnection
        )
        self.enabled = False

        self.engine = None
        self.lib = None

        self._audio_cb = None
        self._log_cb = None
        self._media_cb = None
        self._last_title = ""
        self._last_artist = ""

        self._cb_count = 0
        self._emit_count = 0

        self._pending_audio = deque(maxlen=2)
        self._pending_logs = deque(maxlen=8)
        self._flush_scheduled = False
        self._closing = False

        
        if sys.platform != "win32":
            return

        try:

            # 🎯 TRỎ CHÍNH XÁC VÀO TRONG THƯ MỤC APP/NATIVE
            from paths import asset_dir
            dll_path = asset_dir("app/native/AudioEngineNative.dll")

            print("=========================================")
            print("🎯 [Hệ thống SMTC] DLL PATH CHUẨN HÓA:", str(dll_path))
            print("=========================================")

            if not dll_path.exists():
                print(f"❌ [Lỗi] Không tìm thấy DLL tại vị trí cấu trúc: {dll_path}")
                return

            self.lib = ctypes.CDLL(str(dll_path))
            
            # =================================================
            # EXPORT TYPES
            # =================================================

            self.lib.CreateEngine.restype = ctypes.c_void_p

            self.lib.InitEngine.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                AUDIO_CALLBACK,
                LOG_CALLBACK,
                MEDIA_BUTTON_CALLBACK
            ]

            self.lib.InitEngine.restype = ctypes.c_bool

            self.lib.StartEngine.argtypes = [
                ctypes.c_void_p
            ]

            self.lib.StartEngine.restype = ctypes.c_bool

            self.lib.StopEngine.argtypes = [
                ctypes.c_void_p
            ]

            self.lib.ReleaseEngine.argtypes = [
                ctypes.c_void_p
            ]

            self.lib.UpdateMetadata.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p
            ]

            self.lib.SetPlaybackStatus.argtypes = [
                ctypes.c_void_p,
                ctypes.c_bool
            ]

            self.lib.RestartEngine.argtypes = [
                ctypes.c_void_p
            ]

            self.lib.RestartEngine.restype = ctypes.c_bool

            # =================================================
            # CREATE ENGINE
            # =================================================

            self.engine = self.lib.CreateEngine()

            if not self.engine:
                print("❌ CreateEngine failed")
                return

            hwnd = int(parent_window.winId())

            print("HWND:", hwnd)

            self._audio_cb = AUDIO_CALLBACK(
                self._native_audio_callback
            )

            self._log_cb = LOG_CALLBACK(
                self._native_log_callback
            )

            self._media_cb = MEDIA_BUTTON_CALLBACK(
                self._native_media_callback
            )

            ok = self.lib.InitEngine(
                self.engine,
                ctypes.c_void_p(hwnd),
                self._audio_cb,
                self._log_cb,
                self._media_cb
            )

            if not ok:
                print("❌ InitEngine failed")
                return

            ok = self.lib.StartEngine(self.engine)

            if not ok:
                print("❌ StartEngine failed")
                return

            self.enabled = True

            self.engine_started.emit()

            print("✅ Native SMTC initialized.")

        except Exception as e:
            print("SYSTEM MEDIA ERROR:", e)

    def _schedule_pending_events(self):

        if self._flush_scheduled:
            return

        self._flush_scheduled = True
        self._flush_signal.emit()

    def _flush_pending_events(self):

        self._flush_scheduled = False

        if self._pending_audio:
            audio_data = self._pending_audio.popleft()
            self._emit_audio(audio_data)

        if self._pending_logs:
            log_text = self._pending_logs.popleft()
            self.log_message.emit(log_text)

        if self._pending_audio or self._pending_logs:
            self._schedule_pending_events()
            
    # =====================================================
    # AUDIO CALLBACK
    # =====================================================

    def _native_audio_callback(
        self,
        buffer_ptr,
        frames,
        channels,
        sample_rate
    ):
        if self._closing:
            return
    
        try:
            self._cb_count += 1
            total_samples = frames * channels

            if total_samples <= 0 or buffer_ptr is None:
                return

            if len(self._pending_audio) == self._pending_audio.maxlen:
                return

            # 🎯 GIẢI PHÁP AN TOÀN TUYỆT ĐỐI:
            # Lấy địa chỉ vùng nhớ C++ thô (dạng số nguyên) để tránh tạo wrapper ctypes
            address = ctypes.addressof(buffer_ptr.contents)
            
            # Khởi tạo mảng NumPy trực tiếp từ địa chỉ bộ nhớ thô này
            audio = np.frombuffer(
                (ctypes.c_float * total_samples).from_address(address),
                dtype=np.float32
            ).reshape(frames, channels).copy()

            self._pending_audio.append(audio)
            self._schedule_pending_events()

        except Exception:
            pass
        finally:
            # Giải phóng tham chiếu local của con trỏ ngay lập tức
            if buffer_ptr is not None:
                try:
                    buffer_ptr.contents = None
                except Exception:
                    pass
                del buffer_ptr
    
    def _emit_audio(self, data):

        self._emit_count += 1

        self.audio_received.emit(data)
        del data 
    # =====================================================
    # LOG CALLBACK
    # =====================================================

    def _native_log_callback(self, msg):
        if self._closing:
            return
    
        try:

            text = msg.decode(
                "utf-8",
                errors="ignore"
            )

            self._pending_logs.append(text)
            if len(self._pending_logs) > 8:
                self._pending_logs.pop(0)

            self._schedule_pending_events()

        except Exception:
            pass

    # =====================================================
    # MEDIA CALLBACK
    # =====================================================

    def _native_media_callback(self, button):
        if self._closing:
            return
        print("MEDIA BUTTON:", button)

        if button == 1:
            self.media_play.emit()

        elif button == 2:
            self.media_pause.emit()

        elif button == 3:
            self.media_next.emit()

        elif button == 4:
            self.media_prev.emit()

    # =====================================================
    # METADATA
    # =====================================================

    def update_metadata(self, title, artist):

        title = str(title or "")
        artist = str(artist or "")

        if (
            title == self._last_title
            and artist == self._last_artist
        ):
            return

        self._last_title = title
        self._last_artist = artist

        #print(f"SMTC UPDATE: {title} - {artist}")

        if self.engine:
            self.lib.UpdateMetadata(
                self.engine,
                title,
                artist
            )
    def update_meta(self, title, artist):
        self.update_metadata(title, artist)
    
    # =====================================================
    # PLAYBACK STATE
    # =====================================================

    def set_playing(self, playing):

        if not self.engine:
            return

        self.lib.SetPlaybackStatus(
            self.engine,
            bool(playing)
        )

    def set_status(self, playing):
        self.set_playing(playing)
    
    # =====================================================
    # STOP
    # =====================================================

    def stop(self):

        try:

            if self.engine:
                self.lib.StopEngine(
                    self.engine
                )
                self.engine_stopped.emit()

        except Exception as e:
            print("STOP ERROR:", e)
    
    def restart(self):

        try:

            if self.engine:

                ok = self.lib.RestartEngine(
                    self.engine
                )

                if ok:

                    print("🔄 Audio Engine restarted.")

                    self.update_metadata(
                        self._last_title,
                        self._last_artist
                    )

        except Exception as e:
            print("RESTART ERROR:", e)
            
    # =====================================================
    # CLOSE
    # =====================================================

    def close(self):
        self._closing = True
        try:
            if hasattr(self, "_debug_timer"):
                self._debug_timer.stop()

            gc.collect()
            current, peak = tracemalloc.get_traced_memory()
            print("\n========== FINAL ==========")
            print("Python Current:", current/1024/1024)
            print("Python Peak   :", peak/1024/1024)
            print("===========================")

            self._pending_audio.clear()
            self._pending_logs.clear()
            self._flush_scheduled = False
            self.stop()

            if self.engine and self.lib:
                try:
                    self.lib.ReleaseEngine(self.engine)
                except Exception:
                    pass

                self.engine = None

            self._audio_cb = None
            self._log_cb = None
            self._media_cb = None
            self.lib = None
            if tracemalloc.is_tracing():
                tracemalloc.stop()
        except Exception as e:
            print("CLOSE ERROR:", e)

    def __del__(self):
        pass