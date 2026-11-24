"""Zero-disk Studio Hi-Fi audio controller around QMediaPlayer video/timeline."""
import json
import logging
from pathlib import Path
import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal, QUrl
from PySide6.QtMultimedia import QMediaDevices, QMediaPlayer

from core.audio_profile import (
    AudioProfile,
    compute_mastering_gain_db,
    resolve_restorer,
)
from core.audio_effects import (
    AudioPlaybackCache,
    AudioPreparationCancelled,
    source_signature,
)
from core.audio_loudness import (
    LoudnessCache,
    measure_loudness,
    measure_quick_loudness,
    native_gain,
    probe_audio_stream,
    valid_measurement,
    DEFAULT_TARGET,
    TARGETS,
)
from core.audio_stream_engine import AudioStreamEngine, is_stream_engine_available
from core.subtitle_persistence import atomic_bytes
from control.audio_volume import AudioVolumeControl
from control.audio_prefetch import NextAudioPrefetch
from control.worker_lifecycle import OwnedProcesses
from ui.audio_effects_panel import AudioEffectsPanel
from ui.icons import button_icon, TEXT, ACCENT

logger = logging.getLogger(__name__)


class AudioAnalysisWorker(QThread):
    """Read-only background stream probe + two-phase EBU R128 loudness worker (zero audio disk files)."""
    probed = Signal(int, object, object)
    quick_measured = Signal(int, object)
    progress = Signal(str)

    def __init__(self, source, profile, track, loudness_cache, generation, parent=None):
        super().__init__(parent)
        self.source = source
        self.profile = profile
        self.requested_profile = profile
        self.track = track
        self.loudness_cache = loudness_cache
        self.generation = generation
        self.processes = OwnedProcesses()
        self.result = None
        self.error = None
        self.prefetch = False

    def run(self):
        try:
            sig = source_signature(self.source)
            cached = self.loudness_cache.lookup_full(sig, self.track)
            source_info = cached['source_info'] if cached else None
            if source_info is None:
                source_info = probe_audio_stream(self.source, self.track, self.processes, self.isInterruptionRequested)
            if self.isInterruptionRequested():
                return
            cached_meas = cached['measurement'] if cached else None
            self.probed.emit(self.generation, source_info, cached_meas)
            if cached_meas is not None:
                self.result = {
                    'measurement': cached_meas,
                    'source_info': source_info,
                    'cache_hit': True,
                }
                return
            if not self.profile.normalize and self.profile.output_mode != 'exclusive':
                # Unnormalized Shared mode only needs stream metadata for restorer/SoXR!
                self.result = {
                    'measurement': None,
                    'source_info': source_info,
                    'cache_hit': False,
                }
                return

            if self.profile.normalize:
                duration = float(source_info.get('duration') or 0.0)
                if duration > 16.0:
                    quick = measure_quick_loudness(
                        self.source, source_info['track'], duration, self.processes, self.isInterruptionRequested
                    )
                    if quick is not None and not self.isInterruptionRequested():
                        self.quick_measured.emit(self.generation, quick)

            self.result = measure_loudness(
                self.source,
                source_info['track'],
                self.loudness_cache,
                self.processes,
                self.isInterruptionRequested,
                self.progress.emit,
                source_info=source_info,
            )
        except AudioPreparationCancelled:
            pass
        except Exception as error:
            self.error = str(error)
        finally:
            self.processes.stop()
            self.processes.wait()

    def stop(self):
        self.requestInterruption()
        self.processes.stop()


class LoudnessMeasurementWorker(QThread):
    """Lightweight pre-measurement worker for the next queued track."""
    progress = Signal(str)

    def __init__(self, source, profile, track, cache, _protected=(), parent=None):
        super().__init__(parent)
        self.source = source
        self.profile = profile
        self.requested_profile = profile
        self.track = track
        self.cache = cache
        self.processes = OwnedProcesses()
        self.result = None
        self.error = None
        self.prefetch = True

    def run(self):
        try:
            info = probe_audio_stream(self.source, self.track, self.processes, self.isInterruptionRequested)
            if self.isInterruptionRequested():
                return
            self.result = measure_loudness(
                self.source,
                info['track'],
                self.cache,
                self.processes,
                self.isInterruptionRequested,
                self.progress.emit,
                source_info=info,
            )
        except AudioPreparationCancelled:
            pass
        except Exception as error:
            self.error = str(error)
        finally:
            self.processes.stop()
            self.processes.wait()

    def stop(self):
        self.requestInterruption()
        self.processes.stop()


class AudioEffectsController(QObject):
    def __init__(self, window, root):
        super().__init__(window)
        self.window = window
        self.player = window.media_player.player
        self.cache = AudioPlaybackCache(Path(root) / 'audio-playback-cache')
        self.loudness_cache = LoudnessCache(Path(root) / 'audio-loudness-cache', self.cache.root)
        self.settings_path = Path(root) / 'audio-effects.json'
        self.target_lufs = DEFAULT_TARGET
        self.prefetch_enabled = True
        self.profile = self._load_profile()
        self._stream_available = is_stream_engine_available()
        self._purge_legacy_disk_cache()

        self._measurement = None
        self._source_info = None
        self._initial_gain_db = 0.0
        self._applied_gain_db = 0.0
        self._gain_limited = False

        self.volume_control = AudioVolumeControl(window.audio_output, self)
        self.volume_control.user_changed.connect(self._on_user_volume_changed)
        window.audio_output.mutedChanged.connect(self._on_muted_changed)

        self.stream = AudioStreamEngine(
            on_before_exclusive=self._pause_smtc_for_exclusive,
            on_after_exclusive=self._resume_smtc_after_exclusive,
        )
        self.stream.set_user_volume(self.volume(), window.audio_output.isMuted())

        self.panel = AudioEffectsPanel(window)
        self.panel.set_profile(
            self.profile.normalize, self.profile.tone, self.profile.restorer, self.profile.output_mode
        )
        self.panel.set_target(self.target_lufs)
        self.panel.level_changed.connect(self.set_target)

        self.worker = None
        self._pending = False
        self._generation = 0
        self._closed = False
        self._original = self.player.source()
        self._track = 0
        self._failed_request = None
        self._last_player_pos = 0
        self._last_sync_at = 0.0

        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(80)
        self._request_timer.timeout.connect(self._prepare)

        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(90)
        self._seek_timer.timeout.connect(self._commit_seek)

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(250)
        self._sync_timer.timeout.connect(self._sync_tick)

        self._device_timer = QTimer(self)
        self._device_timer.setSingleShot(True)
        self._device_timer.setInterval(250)
        self._device_timer.timeout.connect(self._handle_device_change)

        self.player.sourceChanged.connect(self._source_changed)
        self.player.activeTracksChanged.connect(self._tracks_changed)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.playbackRateChanged.connect(self._rate_changed)
        self.player.positionChanged.connect(self._position_changed)

        slider = window.playback_bar.time_slider
        slider.sliderMoved.connect(self._seek_requested)
        slider.sliderReleased.connect(lambda: self._seek_requested(slider.value()))

        if hasattr(window, 'audio_devices') and hasattr(window.audio_devices, 'audioOutputsChanged'):
            window.audio_devices.audioOutputsChanged.connect(lambda: self._device_timer.start())

        self.panel.settings_changed.connect(self.set_profile)
        window.playback_bar.btn_audio.clicked.connect(self.toggle_panel)

        self.prefetch = NextAudioPrefetch(self)
        self.panel.set_prefetch(self.prefetch_enabled)
        self.panel.prefetch_changed.connect(self.set_prefetch)
        self._update_button()
        self._update_signal_path()

    def _purge_legacy_disk_cache(self):
        try:
            self.cache.clear_all_owned()
        except OSError:
            pass

    def _pause_smtc_for_exclusive(self):
        manager = getattr(self.window, 'media_manager', None)
        if manager is not None and getattr(manager, 'enabled', False):
            manager.stop()

    def _resume_smtc_after_exclusive(self):
        if self._closed:
            return
        manager = getattr(self.window, 'media_manager', None)
        if manager is not None and getattr(manager, 'enabled', False):
            manager.restart()

    def _load_profile(self):
        try:
            if not self.settings_path.exists():
                return AudioProfile.recommended()
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('target_lufs') in TARGETS:
                self.target_lufs = int(data['target_lufs'])
            if isinstance(data, dict) and isinstance(data.get('prefetch_next'), bool):
                self.prefetch_enabled = data['prefetch_next']
            return AudioProfile.from_dict(data)
        except (OSError, ValueError):
            return AudioProfile.recommended()

    def _save_profile(self):
        data = dict(self.profile.as_dict(), target_lufs=self.target_lufs, prefetch_next=self.prefetch_enabled)
        try:
            atomic_bytes(self.settings_path, json.dumps(data).encode('utf-8'))
        except OSError:
            self.panel.set_status('Đã đổi cho phiên này; chưa lưu được tùy chọn.')

    @property
    def switching(self):
        return False

    def volume(self):
        return self.volume_control.volume()

    def set_volume(self, value):
        self.volume_control.set_volume(value)

    def _on_user_volume_changed(self, value):
        self.stream.set_user_volume(value, self.window.audio_output.isMuted())
        if not self._use_stream_engine():
            self._apply_qt_normalization(ramp=False)

    def _on_muted_changed(self, muted):
        self.stream.set_user_volume(self.volume(), muted)

    def _use_stream_engine(self) -> bool:
        return (
            not self._closed
            and self._stream_available
            and self.profile.enabled
            and self._original.isLocalFile()
            and bool(self._original.toLocalFile())
        )

    def _sync_qt_audio_routing(self):
        """Detach QMediaPlayer audioOutput when RAM WASAPI engine owns output (prevents double audio)."""
        if self._use_stream_engine():
            if self.player.audioOutput() is not None:
                self.player.setAudioOutput(None)
        else:
            if self.player.audioOutput() is not self.window.audio_output:
                self.player.setAudioOutput(self.window.audio_output)

    def play_source(self, source):
        """Start playback instantaneously (0ms disk delay)."""
        if self._closed:
            return
        self.prefetch.stop_for_selection(source)
        self._original = source
        self._sync_qt_audio_routing()
        same_source = source == self.player.source()
        self.player.setSource(source)
        if same_source:
            self._source_changed(source)
        self.player.play()

    def toggle_pending_start(self):
        return False

    def pending_playback(self):
        return None

    def set_pending_playback(self, _playing):
        return False

    def set_prefetch(self, enabled):
        if self._closed:
            return
        self.prefetch_enabled = enabled is True
        self.panel.set_prefetch(self.prefetch_enabled)
        self._save_profile()
        self.prefetch.refresh()

    def playback_queue_changed(self):
        self.prefetch.refresh()

    def set_target(self, target):
        if self._closed or target not in TARGETS:
            return
        self.target_lufs = target
        self.panel.set_target(target)
        self._save_profile()
        self._refresh_gain_live()

    def _refresh_gain_live(self):
        if self._closed:
            return
        if not self._use_stream_engine():
            self._apply_qt_normalization(ramp=True)
            return
        gain_db, limited = compute_mastering_gain_db(
            self._measurement,
            self.target_lufs,
            self.profile.normalize,
            exclusive=(self.profile.output_mode == 'exclusive'),
        )
        self._applied_gain_db = gain_db
        self._gain_limited = limited
        if self.stream.is_active():
            self.stream.set_dynamic_trim_db(gain_db - self._initial_gain_db)
        self._update_signal_path()

    def _apply_qt_normalization(self, ramp=True):
        if self._closed or not self.profile.normalize or self._measurement is None:
            self.volume_control.set_gain(0.0, ramp)
            return
        decision = native_gain(
            self._measurement['lufs'],
            self._measurement['peak_db'],
            self.target_lufs,
            self.volume(),
        )
        self.volume_control.set_gain(decision.gain_db, ramp)

    def _refresh_subtitles(self, position=None):
        overlay = getattr(self.window, 'sub_layer', None)
        guard = getattr(overlay, '_presentation_guard', None)
        if guard is not None:
            if position is not None:
                overlay.update_position(position)
            guard.schedule_refresh()

    def toggle_panel(self):
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.window.vol_popup.hide()
            self._update_signal_path()
            self.panel.open_at(self.window.playback_bar.btn_audio)

    def _update_button(self):
        button = self.window.playback_bar.btn_audio
        button.setProperty('audioEnabled', self.profile.enabled)
        button_icon(button, 'sliders-horizontal', color=ACCENT if self.profile.enabled else TEXT)
        button.setToolTip('Âm thanh — Studio Engine đang bật' if self.profile.enabled else 'Âm thanh — nguyên bản')

    def set_profile(self, normalize, tone, restorer='off', output_mode='shared'):
        if self._closed:
            return
        profile = AudioProfile.from_dict({
            'normalize': normalize,
            'tone': tone,
            'restorer': restorer,
            'output_mode': output_mode,
        })
        if profile == self.profile:
            return
        old = self.profile
        self.profile = profile
        self._failed_request = None
        self.panel.set_profile(profile.normalize, profile.tone, profile.restorer, profile.output_mode)
        self._save_profile()
        self._update_button()
        self.prefetch.refresh()

        self._sync_qt_audio_routing()
        if not self._use_stream_engine():
            self.stream.stop()
            self._sync_timer.stop()
            self._apply_qt_normalization(ramp=True)
            self.panel.set_status('Đang dùng âm thanh gốc (Bypass)')
            self._update_signal_path()
            return

        need_restart = (
            old.tone != profile.tone
            or old.restorer != profile.restorer
            or old.output_mode != profile.output_mode
            or not self.stream.is_active()
        )
        if not need_restart and old.normalize != profile.normalize:
            if profile.normalize and self._measurement is None:
                self._queue_latest()
            else:
                self._refresh_gain_live()
            return

        if self._source_info is not None:
            self._start_or_reconfigure_stream()
            if profile.normalize and self._measurement is None:
                self._queue_latest()
        else:
            self._queue_latest()

    def _queue_latest(self):
        self._generation += 1
        self._pending = True
        self.prefetch.invalidate(stop=False)
        if self.worker is not None:
            if self.prefetch.promote(self.worker):
                self._pending = False
                self._request_timer.stop()
                return True
            self.worker.stop()
        self._request_timer.start(0)
        return False

    def _source_changed(self, source):
        if self._closed:
            return
        self._seek_timer.stop()
        self._sync_timer.stop()
        self.stream.stop()
        self._original = source
        self._failed_request = None
        self._track = 0
        self._measurement = None
        self._source_info = None
        self._initial_gain_db = 0.0
        self._applied_gain_db = 0.0
        self._gain_limited = False
        self._last_player_pos = 0

        self._sync_qt_audio_routing()
        if self._use_stream_engine():
            self.volume_control.set_gain(0.0, False)
            self._queue_latest()
        else:
            self._apply_qt_normalization(ramp=False)
            self._update_signal_path()

    def _tracks_changed(self):
        if self._closed:
            return
        track = self.player.activeAudioTrack()
        if track >= 0 and track != self._track:
            self._track = track
            self._measurement = None
            self._source_info = None
            if self._use_stream_engine():
                self._queue_latest()

    def _prepare(self):
        if self._closed:
            return
        if self.worker is not None:
            self._pending = True
            return
        self._pending = False
        if not self._use_stream_engine():
            return
        source_path = self._original.toLocalFile()
        request = (source_path, self.profile, self._track)
        if request == self._failed_request:
            return
        self.panel.set_status('Đang phân tích luồng âm thanh trong RAM…', busy=True)
        worker = AudioAnalysisWorker(
            source_path,
            self.profile,
            self._track,
            self.loudness_cache,
            self._generation,
            self,
        )
        worker.probed.connect(self._on_probed)
        worker.quick_measured.connect(self._on_quick_measured)
        worker.progress.connect(self._progress)
        worker.finished.connect(self._prepared)
        worker.finished.connect(worker.deleteLater)
        self.worker = worker
        worker.start()

    def _on_probed(self, generation, source_info, cached_meas):
        if self._closed or generation != self._generation or not self._use_stream_engine():
            return
        self._source_info = source_info
        if cached_meas is not None:
            self._measurement = cached_meas
        duration = float((source_info or {}).get('duration') or 0.0)
        # If normalized & uncached on a normal-length track, wait ~70ms for quick_measured so 0.0s is already balanced!
        if cached_meas is None and self.profile.normalize and duration > 16.0:
            self._update_signal_path()
            return
        self._start_or_reconfigure_stream()

    def _on_quick_measured(self, generation, quick_meas):
        if self._closed or generation != self._generation or not self._use_stream_engine():
            return
        if self._measurement is None:
            self._measurement = quick_meas
        if not self.stream.is_active():
            self._start_or_reconfigure_stream()
        else:
            self._refresh_gain_live()

    def _start_or_reconfigure_stream(self):
        if self._closed or not self._use_stream_engine():
            return
        source_path = self._original.toLocalFile()
        gain_db, limited = compute_mastering_gain_db(
            self._measurement,
            self.target_lufs,
            self.profile.normalize,
            exclusive=(self.profile.output_mode == 'exclusive'),
        )
        self._initial_gain_db = gain_db
        self._applied_gain_db = gain_db
        self._gain_limited = limited

        preferred = ''
        try:
            preferred = QMediaDevices.defaultAudioOutput().description()
        except Exception:
            pass
        paused = self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        try:
            self.stream.set_user_volume(self.volume(), self.window.audio_output.isMuted())
            info = self.stream.start_or_reconfigure(
                source_path=source_path,
                start_ms=self.player.position(),
                profile=self.profile,
                source_info=self._source_info,
                gain_db=gain_db,
                playback_rate=self.player.playbackRate(),
                track=int((self._source_info or {}).get('track', self._track)),
                preferred_device_name=preferred,
                paused=paused,
            )
            self._last_sync_at = time.monotonic()
            if not paused:
                self._sync_timer.start()
            if info.get('fallback_reason'):
                self.panel.set_status(info['fallback_reason'])
            elif not self.stream.is_active() and paused:
                self.panel.set_status('Sẵn sàng phát Studio Hi-Fi')
            else:
                self.panel.set_status('Đang phát Studio Hi-Fi (0 MB ổ cứng)')
        except Exception as err:
            logger.warning('Real-time WASAPI stream fallback to Qt native: %s', err)
            self.stream.stop()
            self._sync_timer.stop()
            if self.player.audioOutput() is not self.window.audio_output:
                self.player.setAudioOutput(self.window.audio_output)
            self._apply_qt_normalization(ramp=False)
            self.panel.set_status('Thiết bị bận; tự động phát qua luồng Qt chuẩn.')
        self._update_signal_path()

    def _progress(self, text):
        if not self._closed and self.sender() is self.worker and self.worker.generation == self._generation:
            self.panel.set_status(text, busy=True)

    def _prepared(self):
        worker = self.sender()
        if worker is not self.worker:
            return
        self.worker = None
        if self._closed:
            return
        if getattr(worker, 'prefetch', False):
            self.prefetch.finished(worker)
            if self._pending:
                self._request_timer.start(0)
            return

        current = worker.generation == self._generation and not worker.isInterruptionRequested()
        if current and worker.result:
            info = worker.result.get('source_info')
            if info:
                self._source_info = info
            meas = worker.result.get('measurement')
            if meas is not None and valid_measurement(meas):
                self._measurement = meas
            if self._use_stream_engine():
                if not self.stream.is_active() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._start_or_reconfigure_stream()
                else:
                    self._refresh_gain_live()
                    self.panel.set_status('Đang phát Studio Hi-Fi (0 MB ổ cứng)')
        elif current and worker.error:
            self._failed_request = (worker.source, worker.requested_profile, worker.track)
            if not self.stream.is_active() and self._use_stream_engine():
                self._start_or_reconfigure_stream()
            else:
                self.panel.set_status('Giữ luồng hiện tại: ' + worker.error[:140])

        self._update_signal_path()
        if self._pending:
            self._request_timer.start(0)
        else:
            self.prefetch.schedule()

    def _playback_state(self, state):
        if self._closed or not self._use_stream_engine():
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            if self._source_info is not None:
                if self.stream.status_info().get('paused'):
                    self.stream.resume(self.player.position())
                elif not self.stream.is_active():
                    self._start_or_reconfigure_stream()
                self._last_sync_at = time.monotonic()
                self._sync_timer.start()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._sync_timer.stop()
            self.stream.pause()
        elif state == QMediaPlayer.PlaybackState.StoppedState:
            self._sync_timer.stop()
            self.stream.stop()
        self._update_signal_path()

    def _rate_changed(self, _rate):
        if self._closed or not self._use_stream_engine():
            return
        if self.stream.is_active():
            self._start_or_reconfigure_stream()

    def _seek_requested(self, _position):
        if not self._closed and self._use_stream_engine():
            self._seek_timer.start()

    def _commit_seek(self):
        if self._closed or not self._use_stream_engine():
            return
        pos = self.player.position()
        self._last_player_pos = pos
        self._last_sync_at = time.monotonic()
        self.stream.seek(pos)

    def _position_changed(self, position):
        if self._closed or not self._use_stream_engine():
            return
        jump = abs(position - self._last_player_pos)
        self._last_player_pos = position
        if jump > 650 and not self.window.playback_bar.time_slider.isSliderDown():
            self._seek_timer.start()

    def _sync_tick(self):
        if self._closed or not self._use_stream_engine() or not self.stream.is_active():
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        if self.window.playback_bar.time_slider.isSliderDown():
            return
        if time.monotonic() - self._last_sync_at < 1.5:
            return
        drift = abs(self.player.position() - self.stream.position_ms())
        if drift > 85 and self.player.position() > 150:
            self._last_sync_at = time.monotonic()
            self.stream.seek(self.player.position())

    def _handle_device_change(self):
        if self._closed or not self._use_stream_engine():
            return
        if self._source_info is not None:
            self._start_or_reconfigure_stream()

    def _update_signal_path(self):
        info = self._source_info
        if info:
            codec = str(info.get('codec_name') or '?').upper()
            sr_khz = info['sample_rate'] / 1000.0
            kbps = int(round((info.get('bit_rate') or 0) / 1000.0))
            rate_str = f'{kbps} kbps' if kbps > 0 else 'Lossless / VBR'
            src_text = f'{codec} · {rate_str} · {sr_khz:g} kHz'
        else:
            src_text = 'Đang chờ bài phát' if not self._original.isLocalFile() else 'Đang nhận dạng…'

        if not self.profile.enabled:
            dsp_text = 'Bypass (Âm thanh gốc 100%)'
            out_text = 'Qt Multimedia mặc định'
        else:
            parts = ['64-bit Float']
            rest = resolve_restorer(self.profile, info)
            if rest is not None:
                parts.append(f'Restorer {rest["mode"]}')
            elif self.profile.restorer == 'auto' and info:
                parts.append('Restorer Bypass (Nguồn cao)')
            if self.profile.tone != 'off':
                parts.append('Aria 2 PEQ' if self.profile.tone == 'aria2' else f'EQ {self.profile.tone}')
            if self.profile.normalize:
                parts.append(f'{self.target_lufs} LUFS ({self._applied_gain_db:+.1f} dB)')
            dsp_text = ' · '.join(parts)

            st = self.stream.status_info()
            if st.get('active'):
                mode_label = 'WASAPI Exclusive' if st['output_mode'] == 'exclusive' else 'WASAPI Shared'
                if st['output_mode'] == 'shared_fallback':
                    mode_label = 'WASAPI Shared (Fallback)'
                bits = {'float32': '32-bit Float', 'int32': '32-bit', 'int24': '24-bit', 'int16': '16-bit'}.get(
                    st['dtype'], st['dtype']
                )
                out_text = f'{st["device_name"]} · {mode_label} · {bits}/{st["sample_rate"] / 1000.0:g} kHz · SoXR 28-bit'
            else:
                mode_label = 'WASAPI Exclusive' if self.profile.output_mode == 'exclusive' else 'WASAPI Shared'
                out_text = f'{mode_label} · SoXR 28-bit (Chờ phát)'

        self.panel.set_signal_path(src_text, dsp_text, out_text)

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._request_timer.stop()
        self._seek_timer.stop()
        self._sync_timer.stop()
        self._device_timer.stop()
        self.stream.shutdown()
        self.prefetch.shutdown()
        self.panel.hide()
        self.volume_control.shutdown()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()
            self.worker = None


def install_audio_effects(window):
    from paths import storage_dir
    return AudioEffectsController(window, storage_dir())
