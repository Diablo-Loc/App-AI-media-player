"""Zero-disk Studio Hi-Fi audio controller around QMediaPlayer video/timeline."""
from collections import OrderedDict
from dataclasses import replace
import json
import logging
from pathlib import Path
import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal, QUrl, Qt
from PySide6.QtMultimedia import QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from core.audio_profile import (
    AudioProfile,
    SCHEMA_VERSION,
    TONE_PEAK_PAD_DB,
    adaptive_master_profile,
    compute_mastering_gain_db,
    custom_eq_peak_boost_db,
    effective_eq_preamp_db,
    is_external_usb_dac,
    preset_profile,
    normalize_peq_filters,
    resolve_profile_gain_db,
    resolve_restorer,
    tone_peak_pad_db,
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
from core.audio_stream_engine import (
    AudioStreamEngine,
    _device_matches,
    is_stream_engine_available,
    list_wasapi_output_devices,
)
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
            if (
                not self.profile.normalize
                and not self.profile.youtube_loudness
                and self.profile.output_mode != 'exclusive'
                and self.profile.tone == 'off'
                and not self.profile.eq_enabled
            ):
                # Unnormalized Shared Bit-Pure/Restorer mode only needs stream metadata!
                self.result = {
                    'measurement': None,
                    'source_info': source_info,
                    'cache_hit': False,
                }
                return

            if self.profile.normalize or self.profile.youtube_loudness:
                duration = float(source_info.get('duration') or 0.0)
                if duration > 240.0:
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
            sig = source_signature(self.source)
            cached = self.cache.lookup_full(sig, self.track)
            if cached and cached.get('source_info') and cached.get('measurement'):
                self.result = {
                    'measurement': cached['measurement'],
                    'source_info': cached['source_info'],
                    'cache_hit': True,
                }
                return
            info = cached['source_info'] if (cached and cached.get('source_info')) else probe_audio_stream(
                self.source, self.track, self.processes, self.isInterruptionRequested
            )
            if self.isInterruptionRequested():
                return
            need_meas = (
                self.profile.normalize
                or self.profile.youtube_loudness
                or self.profile.output_mode == 'exclusive'
                or self.profile.tone != 'off'
                or self.profile.eq_enabled
            )
            if not need_meas:
                self.result = {
                    'measurement': cached['measurement'] if cached else None,
                    'source_info': info,
                    'cache_hit': False,
                }
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
    _RAM_CACHE_LIMIT = 256

    def __init__(self, window, root):
        super().__init__(window)
        self.window = window
        self.player = window.media_player.player
        self.cache = AudioPlaybackCache(Path(root) / 'audio-playback-cache')
        self.loudness_cache = LoudnessCache(Path(root) / 'audio-loudness-cache', self.cache.root)
        self.settings_path = Path(root) / 'audio-effects.json'
        self.target_lufs = DEFAULT_TARGET
        self.prefetch_enabled = True
        self.per_device_memory = True
        self.device_profiles = {}
        self.user_eq_presets = {}
        self.eq_dialog = None
        self._migrated_v7 = False
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

        initial_avail = self._available_device_names()
        self._last_device_key = self._effective_device_key(initial_avail)

        self.panel = AudioEffectsPanel(window)
        self.panel.set_output_devices(initial_avail, self.profile.output_device)
        self.panel.set_per_device_memory(self.per_device_memory)
        self.panel.set_profile(
            self.profile.normalize,
            self.profile.tone,
            self.profile.restorer,
            self.profile.output_mode,
            self.profile.upsample,
            self.profile.youtube_loudness,
            target_lufs=self.target_lufs,
            eq_state=self.profile.as_dict(),
            output_device=self.profile.output_device,
            dac_phase=self.profile.dac_phase,
        )
        self.panel.set_target(self.target_lufs)
        self.panel.level_changed.connect(self.set_target)
        self.panel.open_eq_requested.connect(self.open_equalizer)
        self.panel.open_benchmark_requested.connect(self.open_benchmark_tab)
        self.panel.output_device_changed.connect(self.set_output_device)
        self.panel.per_device_changed.connect(self.set_per_device_memory)
        self.panel.dac_phase_changed.connect(self.set_dac_phase)
        self.panel.recommended_requested.connect(self.apply_unified_master_preset)

        self.benchmark_page = None
        self.btn_settings_benchmark = None
        self.settings_studio = None
        self._install_benchmark_tab()
        if self._migrated_v7:
            self._migrated_v7 = False
            self._save_profile()

        self.worker = None
        self._pending = False
        self._generation = 0
        self._closed = False
        self._original = self.player.source()
        self._track = 0
        self._failed_request = None
        self._last_pos_sample = None
        self._last_sync_at = 0.0
        self._ram_cache: OrderedDict[tuple, dict] = OrderedDict()

        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(80)
        self._request_timer.timeout.connect(self._prepare)

        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(90)
        self._seek_timer.timeout.connect(self._commit_seek)

        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(500)
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
        slider.sliderReleased.connect(lambda: self._seek_requested(slider.value()))

        if hasattr(window, 'audio_devices') and hasattr(window.audio_devices, 'audioOutputsChanged'):
            window.audio_devices.audioOutputsChanged.connect(lambda: self._device_timer.start())
        else:
            self._qt_devices = QMediaDevices(self)
            self._qt_devices.audioOutputsChanged.connect(lambda: self._device_timer.start())

        self.panel.settings_changed.connect(self.set_profile)
        window.playback_bar.btn_audio.clicked.connect(self.toggle_panel)

        self.prefetch = NextAudioPrefetch(self)
        self.panel.set_prefetch(self.prefetch_enabled)
        self.panel.prefetch_changed.connect(self.set_prefetch)
        self._update_button()
        self._update_signal_path()

    def _purge_legacy_disk_cache(self):
        try:
            if not self.cache.root.exists():
                return
            if (
                next(self.cache.root.glob('*.mkv'), None) is None
                and next(self.cache.root.glob('*.part.json'), None) is None
            ):
                return
            self.cache.clear_all_owned()
        except OSError:
            pass

    def _ram_cache_key(self, source_path: str, track: int):
        if not source_path:
            return None
        try:
            sig = source_signature(source_path)
            return sig, (sig['path'], sig['size'], sig['mtime_ns'], int(track))
        except OSError:
            return None

    def _store_ram_cache(self, source_path: str, track: int, source_info: dict | None, measurement: dict | None):
        parsed = self._ram_cache_key(source_path, track)
        if parsed is None:
            return
        _, key = parsed
        entry = self._ram_cache.get(key) or {}
        if source_info is not None:
            entry['source_info'] = source_info
        if (
            measurement is not None
            and not measurement.get('provisional')
            and valid_measurement(measurement)
        ):
            entry['measurement'] = measurement
        if not entry:
            return
        self._ram_cache[key] = entry
        self._ram_cache.move_to_end(key)
        while len(self._ram_cache) > self._RAM_CACHE_LIMIT:
            self._ram_cache.popitem(last=False)

    def _try_instant_cache_hit(self, local_path: str, track: int) -> bool:
        parsed = self._ram_cache_key(local_path, track)
        if parsed is None:
            return False
        sig, key = parsed
        entry = self._ram_cache.get(key)
        if entry is not None:
            self._ram_cache.move_to_end(key)
        else:
            disk = self.loudness_cache.lookup_full(sig, track)
            if disk and disk.get('source_info') is not None:
                entry = {
                    'source_info': disk['source_info'],
                    'measurement': disk.get('measurement'),
                }
                self._ram_cache[key] = entry
                self._ram_cache.move_to_end(key)
                while len(self._ram_cache) > self._RAM_CACHE_LIMIT:
                    self._ram_cache.popitem(last=False)
        if not entry or entry.get('source_info') is None:
            return False
        need_meas = (
            self.profile.normalize
            or self.profile.youtube_loudness
            or self.profile.output_mode == 'exclusive'
            or self.profile.tone != 'off'
            or self.profile.eq_enabled
        )
        meas = entry.get('measurement')
        if need_meas and (meas is None or not valid_measurement(meas)):
            return False

        self._generation += 1
        self._pending = False
        self._request_timer.stop()
        self.prefetch.invalidate(stop=True)
        if self.worker is not None:
            self.worker.stop()
        self._source_info = entry['source_info']
        self._measurement = meas
        self._start_or_reconfigure_stream()
        self.prefetch.schedule()
        return True

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
        dev_name = self._system_default_device_name()
        try:
            if not self.settings_path.exists():
                prof, lufs = adaptive_master_profile(dev_name)
                self.target_lufs = int(lufs)
                return prof
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('target_lufs') in TARGETS:
                self.target_lufs = int(data['target_lufs'])
            if isinstance(data, dict) and isinstance(data.get('prefetch_next'), bool):
                self.prefetch_enabled = data['prefetch_next']
            if isinstance(data, dict) and isinstance(data.get('per_device_memory'), bool):
                self.per_device_memory = data['per_device_memory']
            if isinstance(data, dict) and isinstance(data.get('device_profiles'), dict):
                self.device_profiles = {
                    str(k): dict(v) for k, v in data['device_profiles'].items() if isinstance(k, str) and isinstance(v, dict)
                }
            if isinstance(data, dict) and isinstance(data.get('user_eq_presets'), dict):
                self.user_eq_presets = dict(data['user_eq_presets'])

            schema = data.get('schema_version') if isinstance(data, dict) else None
            if isinstance(data, dict) and schema != SCHEMA_VERSION:
                changed = False
                for dev_k, snap in list(self.device_profiles.items()):
                    if (
                        not snap.get('eq_enabled')
                        and snap.get('tone', 'off') == 'off'
                        and snap.get('restorer', 'off') == 'off'
                        and snap.get('normalize') is True
                        and not snap.get('youtube_loudness')
                    ):
                        m_prof, m_lufs = adaptive_master_profile(dev_k)
                        upgraded = dict(m_prof.as_dict(), target_lufs=int(m_lufs))
                        upgraded.pop('output_device', None)
                        self.device_profiles[dev_k] = upgraded
                        changed = True
                is_legacy_auto = (schema not in (4, 5, 6, SCHEMA_VERSION) and data.get('tone') == 'aria2' and data.get('restorer') == 'auto')
                is_uncustomized_flat = (
                    not data.get('eq_enabled')
                    and data.get('tone', 'off') == 'off'
                    and data.get('restorer', 'off') == 'off'
                    and data.get('normalize') is True
                    and not data.get('youtube_loudness')
                )
                if is_legacy_auto or is_uncustomized_flat:
                    pin = str(data.get('output_device') or '').strip()
                    m_prof, m_lufs = adaptive_master_profile(pin or dev_name)
                    self.target_lufs = int(m_lufs)
                    self._migrated_v7 = True
                    return replace(m_prof, output_device=pin)
                if changed:
                    self._migrated_v7 = True
            return AudioProfile.from_dict(data)
        except (OSError, ValueError):
            prof, lufs = adaptive_master_profile(dev_name)
            self.target_lufs = int(lufs)
            return prof

    def _save_profile(self):
        data = dict(
            self.profile.as_dict(),
            schema_version=SCHEMA_VERSION,
            target_lufs=self.target_lufs,
            prefetch_next=self.prefetch_enabled,
            per_device_memory=self.per_device_memory,
            device_profiles=self.device_profiles,
            user_eq_presets=self.user_eq_presets,
        )
        try:
            atomic_bytes(self.settings_path, json.dumps(data).encode('utf-8'))
        except OSError:
            self.panel.set_status('Đã đổi cho phiên này; chưa lưu được tùy chọn.')

    def _available_device_names(self) -> list[str]:
        names = []
        seen = set()
        raw = []
        if self._stream_available:
            raw.extend(list_wasapi_output_devices())
        try:
            for dev in QMediaDevices.audioOutputs():
                raw.append(dev.description())
        except Exception:
            pass
        for item in raw:
            clean = str(item or '').strip()
            if clean and clean.lower() not in seen:
                seen.add(clean.lower())
                names.append(clean)
        return names

    @staticmethod
    def _system_default_device_name() -> str:
        try:
            return str(QMediaDevices.defaultAudioOutput().description() or '').strip()
        except Exception:
            return ''

    def _effective_device_key(self, available: list[str] | None = None) -> str:
        avail = available if available is not None else self._available_device_names()
        pin = str(self.profile.output_device or '').strip()
        if pin:
            for name in avail:
                if _device_matches(name, pin):
                    return name
        return self._system_default_device_name()

    def _find_device_profile(self, dev_key: str) -> dict | None:
        if not dev_key:
            return None
        if dev_key in self.device_profiles:
            return self.device_profiles[dev_key]
        for key, val in self.device_profiles.items():
            if _device_matches(key, dev_key):
                return val
        return None

    def _record_current_device_profile(self, dev_key: str | None = None):
        if not self.per_device_memory:
            return
        key = dev_key or self._last_device_key or self._effective_device_key()
        if not key:
            return
        snap = dict(self.profile.as_dict(), target_lufs=self.target_lufs)
        snap.pop('output_device', None)
        self.device_profiles[key] = snap

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
        if not hasattr(self.player, 'audioOutput') or not hasattr(self.player, 'setAudioOutput'):
            return
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
        self._record_current_device_profile()
        self._save_profile()
        self._refresh_gain_live()
        if getattr(self, 'settings_studio', None) is not None:
            self.settings_studio.sync_from_controller()

    def set_per_device_memory(self, enabled: bool):
        if self._closed:
            return
        self.per_device_memory = enabled is True
        self.panel.set_per_device_memory(self.per_device_memory)
        if self.per_device_memory:
            self._record_current_device_profile()
        self._save_profile()

    def set_output_device(self, device_name: str):
        if self._closed:
            return
        clean = str(device_name or '').strip()[:160]
        if clean == self.profile.output_device:
            return
        avail = self._available_device_names()
        new_key = clean or self._system_default_device_name()
        for name in avail:
            if clean and _device_matches(name, clean):
                new_key = name
                break
        next_prof = replace(self.profile, output_device=clean)
        if self.per_device_memory and new_key:
            saved = self._find_device_profile(new_key)
            if isinstance(saved, dict):
                if saved.get('target_lufs') in TARGETS:
                    self.target_lufs = int(saved['target_lufs'])
                    self.panel.set_target(self.target_lufs)
                next_prof = AudioProfile.from_dict({**saved, 'output_device': clean})
            elif clean and is_external_usb_dac(new_key):
                studio_prof, studio_lufs = adaptive_master_profile(new_key)
                self.target_lufs = int(studio_lufs)
                self.panel.set_target(self.target_lufs)
                next_prof = replace(studio_prof, output_device=clean)
            self._last_device_key = new_key
        self._apply_profile_change(next_prof, save_to_device=True)

    def apply_unified_master_preset(self):
        """Apply the adaptive Master Hi-Fi preset tailored for the current hardware endpoint."""
        if self._closed:
            return
        dev_key = self._effective_device_key()
        prof, lufs = adaptive_master_profile(dev_key)
        merged = dict(self.profile.as_dict())
        merged.update({
            'normalize': prof.normalize,
            'tone': prof.tone,
            'restorer': prof.restorer,
            'output_mode': prof.output_mode,
            'upsample': prof.upsample,
            'dac_phase': prof.dac_phase,
            'youtube_loudness': False,
            'eq_enabled': False,
        })
        self.target_lufs = int(lufs)
        self.panel.set_target(self.target_lufs)
        self._apply_profile_change(AudioProfile.from_dict(merged), save_to_device=True)

    def _resolve_current_gain(self):
        return resolve_profile_gain_db(
            self.profile,
            self._measurement,
            self.target_lufs,
            source_info=self._source_info,
        )

    def _refresh_gain_live(self):
        if self._closed:
            return
        if not self._use_stream_engine():
            self._apply_qt_normalization(ramp=True)
            return
        gain_db, limited = self._resolve_current_gain()
        self._applied_gain_db = gain_db
        self._gain_limited = limited
        if self.stream.is_active():
            self.stream.set_gain_db(gain_db)
        self._update_signal_path()

    def _apply_qt_normalization(self, ramp=True):
        if self._closed or (not self.profile.normalize and not self.profile.youtube_loudness) or self._measurement is None:
            self.volume_control.set_gain(0.0, ramp)
            return
        target = -14 if self.profile.youtube_loudness else self.target_lufs
        decision = native_gain(
            self._measurement['lufs'],
            self._measurement['peak_db'],
            target,
            self.volume(),
        )
        gain_db = min(0.0, decision.gain_db) if self.profile.youtube_loudness else decision.gain_db
        self.volume_control.set_gain(gain_db, ramp)

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
        button.setToolTip('Âm thanh · Đang bật' if self.profile.enabled else 'Âm thanh')

    def _active_status_text(self, info=None) -> str:
        if self.profile.youtube_loudness:
            return 'YouTube'
        st = info if isinstance(info, dict) else self.stream.status_info()
        if (
            st.get('output_mode') == 'exclusive'
            and not self.profile.normalize
            and not self.profile.youtube_loudness
            and self.profile.tone == 'off'
            and self.profile.upsample == 'off'
            and not self.profile.eq_enabled
        ):
            sr = int(st.get('sample_rate') or 0)
            return f'Bit-Perfect {sr / 1000.0:g} kHz' if sr > 0 else 'Bit-Perfect'
        if self.profile.upsample != 'off' and int(st.get('sample_rate') or 0) >= 88200:
            return f'Hi-Res {st["sample_rate"] / 1000.0:g} kHz'
        if st.get('output_mode') == 'exclusive':
            return 'Exclusive'
        return 'Đang bật'

    def open_equalizer(self):
        if self._closed:
            return None
        if self.eq_dialog is None:
            from ui.audio_equalizer_dialog import StudioEqualizerDialog
            dlg = StudioEqualizerDialog(self.window)
            dlg.eq_changed.connect(self.set_custom_eq)
            dlg.user_presets_changed.connect(self._set_user_eq_presets)
            self.eq_dialog = dlg
        self.eq_dialog.set_state(self.profile, self.user_eq_presets)
        if hasattr(self.window, 'frameGeometry'):
            screen = self.window.screen()
            if screen is not None:
                avail = screen.availableGeometry()
                center = self.window.frameGeometry().center()
                x = max(avail.left() + 8, min(center.x() - self.eq_dialog.width() // 2, avail.right() - self.eq_dialog.width() - 8))
                y = max(avail.top() + 8, min(center.y() - self.eq_dialog.height() // 2, avail.bottom() - self.eq_dialog.height() - 8))
                self.eq_dialog.move(x, y)
        self.eq_dialog.show()
        self.eq_dialog.raise_()
        self.eq_dialog.activateWindow()
        return self.eq_dialog

    def _install_benchmark_tab(self):
        stack = getattr(self.window, 'content_stack', None)
        settings_page = getattr(self.window, 'settings_page', None)
        if stack is None or settings_page is None:
            return
        from ui.audio_benchmark_page import AudioBenchmarkPage
        self.benchmark_page = AudioBenchmarkPage(self, self.window)
        self.benchmark_page.back_requested.connect(self.close_benchmark_tab)
        stack.addWidget(self.benchmark_page)

        from ui.settings_studio_view import install_settings_studio_view
        self.settings_studio = install_settings_studio_view(self)
        from ui.download_studio_view import install_download_studio_view
        self.download_studio = install_download_studio_view(self.window)
        self.btn_settings_benchmark = getattr(settings_page, 'btn_audio_benchmark', None)

    def open_benchmark_tab(self, auto_run: bool = True):
        if self._closed or self.benchmark_page is None:
            return None
        stack = getattr(self.window, 'content_stack', None)
        if stack is None:
            return None
        if hasattr(self.window, 'top_toolbar_container'):
            self.window.top_toolbar_container.hide()
        if hasattr(self.window, 'sidebar'):
            self.window.sidebar.blockSignals(True)
            try:
                if self.window.sidebar.count() > 4:
                    self.window.sidebar.setCurrentRow(4)
            finally:
                self.window.sidebar.blockSignals(False)
        stack.setCurrentWidget(self.benchmark_page)
        has_src = self.benchmark_page.sync_default_source()
        if auto_run and has_src:
            self.benchmark_page.run_benchmark()
        return self.benchmark_page

    def close_benchmark_tab(self):
        if self._closed:
            return
        stack = getattr(self.window, 'content_stack', None)
        settings_page = getattr(self.window, 'settings_page', None)
        if stack is not None and settings_page is not None:
            stack.setCurrentWidget(settings_page)
        if hasattr(self.window, 'top_toolbar_container'):
            self.window.top_toolbar_container.hide()

    def _set_user_eq_presets(self, presets: dict):
        if self._closed or not isinstance(presets, dict):
            return
        self.user_eq_presets = dict(presets)
        self._save_profile()

    def set_dac_phase(self, phase: str):
        if self._closed:
            return
        clean = 'minimum' if phase == 'minimum' else 'linear'
        if clean == getattr(self.profile, 'dac_phase', 'linear'):
            return
        self._apply_profile_change(replace(self.profile, dac_phase=clean))

    def set_custom_eq(self, eq_data: dict):
        if self._closed or not isinstance(eq_data, dict):
            return
        merged = dict(self.profile.as_dict())
        for k in ('eq_enabled', 'eq_bands', 'eq_peq_filters', 'eq_preamp_db', 'eq_auto_preamp', 'eq_bass_db', 'eq_treble_db', 'eq_crossfeed'):
            if k in eq_data:
                merged[k] = eq_data[k]
        self._apply_profile_change(AudioProfile.from_dict(merged))

    def set_profile(
        self,
        normalize,
        tone,
        restorer='off',
        output_mode='shared',
        upsample='off',
        youtube_loudness=False,
    ):
        if self._closed:
            return
        merged = dict(self.profile.as_dict())
        is_bypass = (
            not normalize
            and not youtube_loudness
            and tone == 'off'
            and restorer == 'off'
            and output_mode == 'shared'
            and upsample == 'off'
        )
        merged.update({
            'normalize': normalize,
            'tone': tone,
            'restorer': restorer,
            'output_mode': output_mode,
            'upsample': upsample,
            'youtube_loudness': youtube_loudness,
        })
        if is_bypass:
            merged['eq_enabled'] = False
        self._apply_profile_change(AudioProfile.from_dict(merged))

    def _apply_profile_change(self, profile: AudioProfile, save_to_device: bool = True):
        if profile == self.profile:
            return
        old = self.profile
        self.profile = profile
        self._failed_request = None
        self.panel.set_profile(
            profile.normalize,
            profile.tone,
            profile.restorer,
            profile.output_mode,
            profile.upsample,
            profile.youtube_loudness,
            target_lufs=self.target_lufs,
            eq_state=profile.as_dict(),
            output_device=profile.output_device,
            dac_phase=profile.dac_phase,
        )
        if self.eq_dialog is not None:
            self.eq_dialog.set_state(profile)
        if getattr(self, 'settings_studio', None) is not None:
            self.settings_studio.sync_from_controller()
        if save_to_device and profile.enabled:
            self._record_current_device_profile()
        self._save_profile()
        self._update_button()
        self.prefetch.refresh()

        self._sync_qt_audio_routing()
        if not self._use_stream_engine():
            self.stream.stop()
            self._sync_timer.stop()
            self._apply_qt_normalization(ramp=True)
            self.panel.set_status('Tắt')
            self._update_signal_path()
            return

        eq_filter_changed = (old.eq_enabled != profile.eq_enabled) or (
            profile.eq_enabled
            and (
                old.eq_bands != profile.eq_bands
                or old.eq_peq_filters != profile.eq_peq_filters
                or abs(old.eq_bass_db - profile.eq_bass_db) >= 0.05
                or abs(old.eq_treble_db - profile.eq_treble_db) >= 0.05
                or old.eq_crossfeed != profile.eq_crossfeed
            )
        )
        need_restart = (
            old.tone != profile.tone
            or old.restorer != profile.restorer
            or old.output_mode != profile.output_mode
            or old.upsample != profile.upsample
            or old.dac_phase != profile.dac_phase
            or old.output_device != profile.output_device
            or eq_filter_changed
            or not self.stream.is_active()
        )
        need_measure = (
            profile.normalize
            or profile.youtube_loudness
            or profile.output_mode == 'exclusive'
            or profile.tone != 'off'
            or profile.eq_enabled
        )
        if not need_restart:
            if need_measure and self._measurement is None:
                self._queue_latest()
            else:
                self._refresh_gain_live()
                if self.stream.is_active():
                    self.panel.set_status(self._active_status_text())
            return

        if self._source_info is not None:
            self._start_or_reconfigure_stream()
            if need_measure and self._measurement is None:
                self._queue_latest()
        else:
            if not self._try_instant_cache_hit(self._original.toLocalFile(), self._track):
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
        self._last_pos_sample = None

        self._sync_qt_audio_routing()
        if self._use_stream_engine():
            self.volume_control.set_gain(0.0, False)
            if not self._try_instant_cache_hit(self._original.toLocalFile(), self._track):
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
                if not self._try_instant_cache_hit(self._original.toLocalFile(), self._track):
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
        self.panel.set_status('Đang đo âm lượng…', busy=True)
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
        self._store_ram_cache(self._original.toLocalFile(), self._track, source_info, cached_meas)
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
        gain_db, limited = self._resolve_current_gain()
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
                self.panel.set_status('Sẵn sàng')
            else:
                self.panel.set_status(self._active_status_text(info))
        except Exception as err:
            logger.warning('Real-time WASAPI stream fallback to Qt native: %s', err)
            self.stream.stop()
            self._sync_timer.stop()
            if self.player.audioOutput() is not self.window.audio_output:
                self.player.setAudioOutput(self.window.audio_output)
            self._apply_qt_normalization(ramp=False)
            self.panel.set_status('Thiết bị bận · Dùng mặc định')
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
            if worker.result and not worker.isInterruptionRequested():
                self._store_ram_cache(
                    worker.source,
                    worker.track,
                    worker.result.get('source_info'),
                    worker.result.get('measurement'),
                )
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
            self._store_ram_cache(worker.source, worker.track, info, meas)
            if self._use_stream_engine():
                if not self.stream.is_active() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    self._start_or_reconfigure_stream()
                else:
                    self._refresh_gain_live()
                    self.panel.set_status(self._active_status_text())
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
        self._last_pos_sample = None
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
        self._last_pos_sample = (pos, time.monotonic())
        self._last_sync_at = time.monotonic()
        self.stream.seek(pos)

    def _position_changed(self, position):
        if self._closed or not self._use_stream_engine():
            return
        now = time.monotonic()
        prev = self._last_pos_sample
        self._last_pos_sample = (position, now)
        if prev is None or self.window.playback_bar.time_slider.isSliderDown():
            return
        if now - self._last_sync_at < 1.2:
            return
        expected = (now - prev[1]) * float(self.player.playbackRate() or 1.0) * 1000.0
        if abs((position - prev[0]) - expected) > 1800:
            self._seek_timer.start()

    def _sync_tick(self):
        if self._closed or not self._use_stream_engine() or not self.stream.is_active():
            return
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        if self.window.playback_bar.time_slider.isSliderDown():
            return
        if time.monotonic() - self._last_sync_at < 8.0:
            return
        drift = abs(self.player.position() - self.stream.position_ms())
        if drift > 2500 and self.player.position() > 2500:
            self._last_sync_at = time.monotonic()
            self.stream.seek(self.player.position())

    def _handle_device_change(self):
        if self._closed:
            return
        was_active = self.stream.is_active()
        avail = []
        seen = set()
        raw = []
        if self._stream_available:
            raw.extend(self.stream.refresh_devices())
        try:
            for dev in QMediaDevices.audioOutputs():
                raw.append(dev.description())
        except Exception:
            pass
        for item in raw:
            clean = str(item or '').strip()
            if clean and clean.lower() not in seen:
                seen.add(clean.lower())
                avail.append(clean)
        self.panel.set_output_devices(avail, self.profile.output_device)

        new_key = self._effective_device_key(avail)
        if self.per_device_memory and new_key and new_key != self._last_device_key:
            saved = self._find_device_profile(new_key)
            pinned = self.profile.output_device
            had_saved = isinstance(saved, dict)
            if had_saved:
                if saved.get('target_lufs') in TARGETS:
                    self.target_lufs = int(saved['target_lufs'])
                    self.panel.set_target(self.target_lufs)
                next_prof = AudioProfile.from_dict({**saved, 'output_device': pinned})
            elif is_external_usb_dac(new_key):
                studio_prof, studio_lufs = adaptive_master_profile(new_key)
                self.target_lufs = int(studio_lufs)
                self.panel.set_target(self.target_lufs)
                next_prof = replace(studio_prof, output_device=pinned)
            elif self.profile.output_mode == 'exclusive' or self.profile.tone in ('master_hifi', 'studio_aria2', 'aria2'):
                shared_prof, shared_lufs = adaptive_master_profile(new_key)
                self.target_lufs = int(shared_lufs)
                self.panel.set_target(self.target_lufs)
                next_prof = replace(shared_prof, output_device=pinned)
            else:
                next_prof = self.profile

            self._last_device_key = new_key
            if next_prof != self.profile:
                self._apply_profile_change(next_prof, save_to_device=(not had_saved))
                return
            if not had_saved and self.profile.enabled:
                self._record_current_device_profile(new_key)
                self._save_profile()
        elif new_key:
            self._last_device_key = new_key

        if not self._use_stream_engine():
            return
        if (was_active or self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState) and self._source_info is not None:
            self._start_or_reconfigure_stream()
        else:
            self._update_signal_path()

    def _update_signal_path(self):
        info = self._source_info
        if info:
            codec = str(info.get('codec_name') or '?').upper()
            sr_khz = info['sample_rate'] / 1000.0
            kbps = int(round((info.get('bit_rate') or 0) / 1000.0))
            rate_str = f'{kbps} kbps' if kbps > 0 else 'Lossless'
            src_text = f'{codec} {sr_khz:g} kHz'
            src_detail = f'{codec} · {rate_str} · {sr_khz:g} kHz'
        else:
            src_text = 'Chưa phát' if not self._original.isLocalFile() else 'Đang đọc…'
            src_detail = src_text

        if not self.profile.enabled:
            dsp_text = 'Nguyên gốc'
            dsp_detail = 'Nguyên gốc (Bypass)'
            out_text = 'Mặc định'
            out_detail = 'Mặc định hệ thống'
        else:
            short_parts = ['64-bit']
            detail_parts = ['64-bit Float']
            rest = resolve_restorer(self.profile, info)
            if rest is not None:
                short_parts.append('Restorer')
                detail_parts.append(f'Restorer {rest["mode"]}')
            elif self.profile.restorer == 'auto' and info:
                detail_parts.append('Restorer Bypass')
            if self.profile.tone != 'off':
                tone_short = {
                    'master_hifi': 'Hi-Fi',
                    'studio_aria2': 'Aria 2',
                    'studio_room': 'Loa 30°',
                    'walkman_vivid': 'Sống động',
                    'aria2': 'Aria 2',
                    'vocal_clear': 'Vocal',
                    'warm': 'Ấm',
                    'headphones': 'Crossfeed',
                }
                tone_labels = {
                    'master_hifi': 'Master Hi-Fi + Studio 30°',
                    'studio_aria2': 'Aria 2 Lab + Studio 30°',
                    'studio_room': 'Studio Monitor 30°',
                    'walkman_vivid': 'Walkman/Poweramp EQ',
                    'aria2': 'Aria 2 PEQ',
                    'vocal_clear': 'Vocal Clear',
                    'warm': 'Warm',
                    'headphones': 'IEM Crossfeed',
                }
                short_parts.append(tone_short.get(self.profile.tone, self.profile.tone))
                detail_parts.append(tone_labels.get(self.profile.tone, f'EQ {self.profile.tone}'))
            if self.profile.eq_enabled:
                peq_list = normalize_peq_filters(getattr(self.profile, 'eq_peq_filters', ()))
                if peq_list:
                    short_parts.append(f'PEQ {len(peq_list)}')
                    eq_tag = f'PEQ {len(peq_list)} dải'
                else:
                    short_parts.append('EQ')
                    eq_tag = 'EQ 10 dải'
                if self.profile.eq_crossfeed > 0:
                    eq_tag += f' · Crossfeed {self.profile.eq_crossfeed}%'
                detail_parts.append(eq_tag)
            if self.profile.youtube_loudness:
                short_parts.append(f'{self._applied_gain_db:+.1f} dB')
                detail_parts.append(f'YouTube −14 LUFS ({self._applied_gain_db:+.1f} dB)')
            elif self.profile.normalize:
                short_parts.append(f'{self._applied_gain_db:+.1f} dB')
                detail_parts.append(f'{self.target_lufs} LUFS ({self._applied_gain_db:+.1f} dB)')
            elif abs(self._applied_gain_db) >= 0.05:
                short_parts.append(f'{self._applied_gain_db:+.1f} dB')
                detail_parts.append(f'Headroom {self._applied_gain_db:+.1f} dB')
            elif (
                self.profile.output_mode == 'exclusive'
                and self.profile.tone == 'off'
                and self.profile.upsample == 'off'
                and not self.profile.eq_enabled
            ):
                detail_parts.append('Bit-Perfect 0 dB')
            dsp_text = ' · '.join(short_parts)
            dsp_detail = ' · '.join(detail_parts)

            st = self.stream.status_info()
            if st.get('active'):
                mode_short = 'Exclusive' if st['output_mode'] == 'exclusive' else 'Shared'
                mode_label = f'WASAPI {mode_short}'
                if st['output_mode'] == 'shared_fallback':
                    mode_label = 'WASAPI Shared (Fallback)'
                bits = {'float32': '32-bit Float', 'int32': '32-bit', 'int24': '24-bit', 'int16': '16-bit'}.get(
                    st['dtype'], st['dtype']
                )
                resampled = st.get('filter_summary', {}).get('resampled', False)
                phase_tag = 'Min-Phase' if getattr(self.profile, 'dac_phase', 'linear') == 'minimum' else 'SoXR 33-bit'
                if resampled and int(st.get('sample_rate') or 0) >= 88200:
                    sr_tag = f'{phase_tag} Hi-Res'
                elif resampled:
                    sr_tag = 'SoXR 33-bit'
                else:
                    sr_tag = 'Bit-Pure Native'
                lat = st.get('latency_ms')
                lat_tag = f' · {lat:g} ms' if isinstance(lat, (int, float)) and lat > 0 else ''
                out_text = f'{mode_short} {st["sample_rate"] / 1000.0:g} kHz'
                out_detail = f'{st["device_name"]} · {mode_label} · {bits}/{st["sample_rate"] / 1000.0:g} kHz · {sr_tag}{lat_tag}'
            else:
                mode_short = 'Exclusive' if self.profile.output_mode == 'exclusive' else 'Shared'
                mode_label = f'WASAPI {mode_short}'
                dev_label = self.profile.output_device or 'Mặc định hệ thống'
                out_text = self.profile.output_device or mode_short
                out_detail = f'{dev_label} · {mode_label}'

        detail_tip = f'Nguồn: {src_detail}\nXử lý: {dsp_detail}\nĐầu ra: {out_detail}'
        self.panel.set_signal_path(src_text, dsp_text, out_text, tooltip=detail_tip)
        if getattr(self, 'settings_studio', None) is not None:
            self.settings_studio.sync_from_controller()

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
        if self.benchmark_page is not None:
            self.benchmark_page.shutdown()
        if self.eq_dialog is not None:
            self.eq_dialog.close()
            self.eq_dialog.deleteLater()
            self.eq_dialog = None
        self.volume_control.shutdown()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()
            self.worker = None


def install_audio_effects(window):
    from paths import storage_dir
    return AudioEffectsController(window, storage_dir())
