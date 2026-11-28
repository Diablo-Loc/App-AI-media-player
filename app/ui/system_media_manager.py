import sys
import ctypes
import gc
import threading
import time
from collections import deque

from PySide6.QtCore import QObject, Signal, Qt

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

    # Minimum interval between identical hardware media button deliveries so
    # mechanical/Bluetooth AVRCP key bounce or queued bursts never flood the UI.
    _MEDIA_DEBOUNCE_SEC = 0.28

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
        # PCM delivery is optional.  The app currently has no visualizer or
        # other consumer (MainWindow.process_realtime_audio is a no-op), so do
        # not copy every native audio buffer into Python/NumPy by default.
        # Keeping the callback registered preserves the native engine/SMTC ABI;
        # a future real consumer can opt in explicitly.
        self._capture_audio = False
        self._capture_running = False
        self._numpy = None
        self._last_title = ""
        self._last_artist = ""
        self._last_playing = None

        self._cb_count = 0
        self._emit_count = 0

        self._media_lock = threading.Lock()
        self._pending_media = deque(maxlen=2)
        self._last_media_ts = {}
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

            # InitEngine already activates WinRT SMTC on this HWND and registers
            # the single ButtonPressed delegate.  StartEngine only runs the
            # WASAPI loopback polling thread, so keep it stopped unless a real
            # beat/visualizer consumer opts in via set_audio_capture_enabled(True).
            if self._capture_audio:
                ok = self.lib.StartEngine(self.engine)
                if not ok:
                    print("❌ StartEngine failed")
                    return
                self._capture_running = True

            self.enabled = True

            self.engine_started.emit()

            print("✅ Native SMTC initialized.")

        except Exception as e:
            print("SYSTEM MEDIA ERROR:", e)

    def set_audio_capture_enabled(self, enabled):
        """Opt in to PCM copies only when a real Python consumer needs them."""
        enabled = bool(enabled)
        if enabled and self._numpy is None:
            try:
                import numpy as np
            except Exception as error:
                print("AUDIO CAPTURE ERROR:", error)
                self._capture_audio = False
                return False
            self._numpy = np
        self._capture_audio = enabled
        if enabled:
            if self.engine and self.lib and not self._capture_running and not self._closing:
                try:
                    if self.lib.StartEngine(self.engine):
                        self._capture_running = True
                except Exception as error:
                    print("START CAPTURE ERROR:", error)
        else:
            with self._media_lock:
                self._pending_audio.clear()
            if self._capture_running:
                self.stop()
        return self._capture_audio

    def _schedule_pending_events(self):
        with self._media_lock:
            if self._closing or self._flush_scheduled:
                return
            self._flush_scheduled = True
        self._flush_signal.emit()

    def _flush_pending_events(self):
        media_btn = None
        audio_data = None
        log_text = None
        has_more = False

        with self._media_lock:
            self._flush_scheduled = False
            if self._closing:
                self._pending_media.clear()
                self._pending_audio.clear()
                self._pending_logs.clear()
                return
            if self._pending_media:
                media_btn = self._pending_media.popleft()
            if self._pending_audio:
                audio_data = self._pending_audio.popleft()
            if self._pending_logs:
                log_text = self._pending_logs.popleft()
            has_more = bool(
                self._pending_media or self._pending_audio or self._pending_logs
            )

        if media_btn == 1:
            self.media_play.emit()
        elif media_btn == 2:
            self.media_pause.emit()
        elif media_btn == 3:
            self.media_next.emit()
        elif media_btn == 4:
            self.media_prev.emit()

        if audio_data is not None:
            self._emit_audio(audio_data)

        if log_text is not None:
            self.log_message.emit(log_text)

        if has_more and not self._closing:
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
        if self._closing or not self._capture_audio:
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
            np = self._numpy
            if np is None:
                return
            audio = np.frombuffer(
                (ctypes.c_float * total_samples).from_address(address),
                dtype=np.float32
            ).reshape(frames, channels).copy()

            with self._media_lock:
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

            with self._media_lock:
                self._pending_logs.append(text)

            self._schedule_pending_events()

        except Exception:
            pass

    # =====================================================
    # MEDIA CALLBACK
    # =====================================================

    def _native_media_callback(self, button):
        """WinRT SMTC callback thread: debounce, enqueue, and return immediately.

        Never emit playback signals directly on the WinRT callback thread; doing
        so can re-enter WinRT/COM or stall the OS media dispatcher while the UI
        switches tracks or stops WASAPI Exclusive output.
        """
        if self._closing:
            return
        try:
            btn = int(button)
        except Exception:
            return
        if btn not in (1, 2, 3, 4):
            return

        now = time.monotonic()
        need_schedule = False
        with self._media_lock:
            if self._closing:
                return
            last_ts = self._last_media_ts.get(btn, 0.0)
            if (now - last_ts) < self._MEDIA_DEBOUNCE_SEC:
                return
            self._last_media_ts[btn] = now

            if btn in self._pending_media:
                return
            if btn in (1, 2):
                opposite = 2 if btn == 1 else 1
                try:
                    self._pending_media.remove(opposite)
                except ValueError:
                    pass
            self._pending_media.append(btn)
            if not self._flush_scheduled:
                self._flush_scheduled = True
                need_schedule = True

        if need_schedule:
            self._flush_signal.emit()

    # =====================================================
    # METADATA
    # =====================================================

    def update_metadata(self, title, artist):

        if self._closing:
            return

        title = str(title or "")
        artist = str(artist or "")

        if (
            title == self._last_title
            and artist == self._last_artist
        ):
            return

        self._last_title = title
        self._last_artist = artist

        if self.engine and self.lib:
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

        if self._closing or not self.engine or not self.lib:
            return

        state = bool(playing)
        if self._last_playing is state:
            return
        self._last_playing = state

        self.lib.SetPlaybackStatus(
            self.engine,
            state
        )

    def set_status(self, playing):
        self.set_playing(playing)
    
    # =====================================================
    # STOP
    # =====================================================

    def stop(self, force=False):

        try:

            if self.engine and self.lib and (self._capture_running or force):
                self.lib.StopEngine(
                    self.engine
                )
                self._capture_running = False
                self.engine_stopped.emit()

        except Exception as e:
            print("STOP ERROR:", e)
    
    def restart(self):
        """Safely restart WASAPI loopback capture ONLY when opted in.

        Never call native RestartEngine(): AudioEngineNative.dll's RestartEngine
        runs Cleanup + InitEngine without revoking the previous WinRT SMTC
        ButtonPressed event token on this HWND, which leaks duplicate SMTC
        listeners on every call and causes exponential skip/freeze storms.
        """
        if self._closing or not self.engine or not self.lib or not self._capture_audio:
            return
        try:
            if self._capture_running:
                self.lib.StopEngine(self.engine)
                self._capture_running = False
            ok = self.lib.StartEngine(self.engine)
            if ok:
                self._capture_running = True
                print("🔄 Audio loopback capture restarted.")
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

            with self._media_lock:
                self._pending_media.clear()
                self._pending_audio.clear()
                self._pending_logs.clear()
                self._last_media_ts.clear()
                self._flush_scheduled = False
            self._last_playing = None
            self.stop(force=True)

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
            gc.collect()
        except Exception as e:
            print("CLOSE ERROR:", e)

    def __del__(self):
        pass
