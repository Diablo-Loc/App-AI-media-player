"""Optional audio preparation around the unchanged QMediaPlayer/video owners."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from core.audio_profile import AudioProfile
from core.audio_effects import AudioPlaybackCache, AudioPreparationCancelled, prepare_audio
from core.audio_loudness import LoudnessCache, measure_loudness, native_gain, valid_measurement, DEFAULT_TARGET, TARGETS
from core.subtitle_persistence import atomic_bytes
from control.audio_volume import AudioVolumeControl
from control.worker_lifecycle import OwnedProcesses
from ui.audio_effects_panel import AudioEffectsPanel
from ui.icons import button_icon, TEXT, ACCENT


class AudioPreparationWorker(QThread):
    progress = Signal(str)

    def __init__(self, source, profile, track, cache, protected, parent=None):
        super().__init__(parent)
        self.source, self.profile, self.track = source, profile, track
        self.cache, self.protected = cache, protected
        self.processes = OwnedProcesses()
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = prepare_audio(self.source, self.profile, self.track, self.cache, self.processes,
                                        self.isInterruptionRequested, self.protected, self.progress.emit)
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


class LoudnessMeasurementWorker(AudioPreparationWorker):
    def run(self):
        try:
            self.result = measure_loudness(self.source, self.track, self.cache, self.processes,
                                          self.isInterruptionRequested, self.progress.emit)
        except AudioPreparationCancelled:
            pass
        except Exception as error:
            self.error = str(error)
        finally:
            self.processes.stop()
            self.processes.wait()


class AudioEffectsController(QObject):
    def __init__(self, window, root):
        super().__init__(window)
        self.window = window
        self.player = window.media_player.player
        self.cache = AudioPlaybackCache(Path(root) / 'audio-playback-cache')
        self.loudness_cache = LoudnessCache(Path(root) / 'audio-loudness-cache', self.cache.root)
        self.settings_path = Path(root) / 'audio-effects.json'
        self.target_lufs = DEFAULT_TARGET
        self.profile = self._load_profile()
        self._measurement = None
        self._applied_tone = 'off'
        self._tone_gain = 0.0
        self.volume_control = AudioVolumeControl(window.audio_output, self)
        self.volume_control.user_changed.connect(lambda value: self._apply_normalization(ramp=False))
        self.panel = AudioEffectsPanel(window)
        self.panel.set_profile(self.profile.normalize, self.profile.tone)
        self.panel.set_target(self.target_lufs)
        self.panel.level_changed.connect(self.set_target)
        self.worker = None
        self._pending = False
        self._generation = 0
        self._closed = False
        self._internal = False
        self._original = self.player.source()
        self._transition = None
        self._track = 0
        self._applied_key = None
        self._failed_request = None
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.setInterval(180)
        self._request_timer.timeout.connect(self._prepare)
        self._transition_timer = QTimer(self)
        self._transition_timer.setSingleShot(True)
        self._transition_timer.setInterval(8000)
        self._transition_timer.timeout.connect(self._transition_failed)
        self.player.sourceChanged.connect(self._source_changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.activeTracksChanged.connect(self._tracks_changed)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.errorOccurred.connect(self._player_error)
        self.player.playbackRateChanged.connect(self._rate_changed)
        self.player.positionChanged.connect(self._position_changed)
        window.playback_bar.time_slider.sliderMoved.connect(self._seek_requested)
        window.playback_bar.time_slider.sliderReleased.connect(
            lambda: self._seek_requested(window.playback_bar.time_slider.value()))
        self.panel.settings_changed.connect(self.set_profile)
        window.playback_bar.btn_audio.clicked.connect(self.toggle_panel)
        self._update_button()
        if self.profile.enabled:
            self._request_timer.start()

    def _load_profile(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('target_lufs') in TARGETS:
                self.target_lufs = int(data['target_lufs'])
            return AudioProfile.from_dict(data)
        except (OSError, ValueError):
            return AudioProfile()

    def volume(self):
        return self.volume_control.volume()

    def set_volume(self, value):
        self.volume_control.set_volume(value)

    def _save_profile(self):
        data = dict(self.profile.as_dict(), target_lufs=self.target_lufs)
        try:
            atomic_bytes(self.settings_path, json.dumps(data).encode('utf-8'))
        except OSError:
            self.panel.set_status('Đã đổi cho phiên này; chưa lưu được tùy chọn.')

    def set_target(self, target):
        if self._closed or target not in TARGETS:
            return
        self.target_lufs = target
        self.panel.set_target(target)
        self._save_profile()
        self._apply_normalization()

    def _apply_normalization(self, ramp=True):
        if self._closed:
            return
        if not self.profile.normalize or self._measurement is None:
            self.volume_control.set_gain(0.0, ramp)
            return
        level, peak = self._measurement['lufs'], self._measurement['peak_db']
        if level is not None:
            level, peak = level + self._tone_gain, peak + self._tone_gain
        decision = native_gain(level, peak, self.target_lufs, self.volume())
        self.volume_control.set_gain(decision.gain_db, ramp)
        suffix = ' · Giới hạn đầu ra: một số bài có thể chưa đạt độ lớn mục tiêu' if decision.limited else ''
        self.panel.set_status(f'Cân bằng trực tiếp · {self.target_lufs} LUFS{suffix}')

    @property
    def switching(self):
        return self._transition is not None

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
            self.panel.open_at(self.window.playback_bar.btn_audio)

    def _update_button(self):
        button = self.window.playback_bar.btn_audio
        button.setProperty('audioEnabled', self.profile.enabled)
        button_icon(button, 'sliders-horizontal', color=ACCENT if self.profile.enabled else TEXT)
        button.setToolTip('Âm thanh — đang bật' if self.profile.enabled else 'Âm thanh — nguyên bản')

    def set_profile(self, normalize, tone):
        if self._closed:
            return
        profile = AudioProfile.from_dict({'normalize': normalize, 'tone': tone})
        if profile == self.profile:
            return
        old_tone = self.profile.tone
        self.profile = profile
        self._failed_request = None
        self.panel.set_profile(profile.normalize, profile.tone)
        self._save_profile()
        self._update_button()
        self._apply_normalization()
        if old_tone == profile.tone and self._measurement is not None:
            if not profile.normalize:
                self.panel.set_status('Đang dùng âm thanh gốc' if profile.tone == 'off' else 'Đang dùng EQ đã chọn')
            return
        if old_tone != profile.tone:
            self._measurement = None
            self._apply_normalization()
        self._queue_latest()
        if profile.tone == 'off' and self._applied_tone != 'off':
            self._applied_tone = 'off'
            self._tone_gain = 0.0
            self._switch(self._original)
        if not profile.enabled:
            self._request_timer.stop()
            self._applied_key = None
            self._switch(self._original)
            self.panel.set_status('Đang dùng âm thanh gốc')

    def _queue_latest(self):
        self._generation += 1
        self._pending = True
        if self.worker is not None:
            self.worker.stop()
        self._request_timer.start()

    def _source_changed(self, source):
        if self._closed:
            return
        if self._transition and source == self._transition['target']:
            return
        self._transition_timer.stop()
        self._transition = None
        self._refresh_subtitles()
        self._original = source
        self._applied_key = None
        self._failed_request = None
        self._track = 0
        self._measurement = None
        self._applied_tone = 'off'
        self._tone_gain = 0.0
        self._apply_normalization(ramp=False)
        self._queue_latest()
        if self.profile.enabled:
            # A cached measurement can apply as the new file starts. Keep
            # analysis off the GUI thread and let rapid source edits supersede it.
            self._request_timer.start(0)

    def _tracks_changed(self):
        if self._closed or self._internal or self._transition:
            return
        track = self.player.activeAudioTrack()
        if track >= 0 and track != self._track:
            self._track = track
            self._measurement = None
            self._apply_normalization(ramp=False)
            self._queue_latest()

    def _prepare(self):
        if self._closed:
            return
        if self.worker is not None:
            self._pending = True
            return
        self._pending = False
        if not self.profile.enabled:
            return
        if not self._original.isLocalFile() or not self._original.toLocalFile():
            self.panel.set_status('Chọn bài trên máy để xử lý âm thanh.')
            return
        request = (self._original.toLocalFile(), self.profile, self._track)
        if request == self._failed_request:
            return
        self.panel.set_status('Chuẩn bị nền; bài vẫn đang phát âm thanh hiện tại…', busy=True)
        protected = (self.player.source().toLocalFile(),)
        if self.profile.tone == 'off':
            worker = LoudnessMeasurementWorker(*request, self.loudness_cache, protected, self)
        else:
            worker = AudioPreparationWorker(request[0], AudioProfile(False, self.profile.tone), self._track,
                                            self.cache, protected, self)
        worker.requested_profile = self.profile
        worker.generation = self._generation
        self.worker = worker
        worker.progress.connect(self._progress)
        worker.finished.connect(self._prepared)
        worker.finished.connect(worker.deleteLater)
        worker.start()

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
        current = worker.generation == self._generation and not worker.isInterruptionRequested()
        if current and worker.result:
            try:
                if 'measurement' in worker.result:
                    measured = worker.result['measurement']
                else:
                    gain = worker.result['record']['gain']
                    measured = {'lufs': gain['input_lufs'], 'peak_db': gain['input_peak_db'],
                                'silent': gain['input_lufs'] is None and gain['input_peak_db'] is None}
                if not valid_measurement(measured):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                worker.result = None
                worker.error = 'Số đo trong cache chưa hợp lệ; giữ âm thanh hiện tại.'
        if current and worker.result:
            if 'measurement' in worker.result:
                self._measurement = worker.result['measurement']
            else:
                self._applied_key = worker.result['record']['key']
                gain = worker.result['record']['gain']
                self._tone_gain = gain['gain_db']
                self._measurement = {'lufs': gain['input_lufs'], 'peak_db': gain['input_peak_db']}
                self._applied_tone = self.profile.tone
                self._switch(QUrl.fromLocalFile(worker.result['path']))
            self._apply_normalization()
            if not self.profile.normalize:
                self.panel.set_status('Đang dùng EQ đã chọn')
        elif current and worker.error:
            self._failed_request = (worker.source, worker.requested_profile, worker.track)
            self.panel.set_status('Chưa áp dụng cho bài này; giữ âm thanh hiện tại. ' + worker.error[:220])
        if self._pending:
            self._request_timer.start()

    def _switch(self, target):
        if self._closed or target.isEmpty() or target == self.player.source():
            return
        old = self._transition
        state = old['state'] if old else self.player.playbackState()
        position = old['position'] if old else self.player.position()
        self._transition = {'target': target, 'position': position, 'state': state,
                            'rate': old['rate'] if old else self.player.playbackRate(), 'track': self._track,
                            'video': old['video'] if old else self.player.activeVideoTrack(),
                            'subtitle': old['subtitle'] if old else self.player.activeSubtitleTrack(),
                            'loops': old['loops'] if old else self.player.loops()}
        self._transition_timer.start()
        self._refresh_subtitles()
        self._internal = True
        try:
            self.player.setSource(target)
        finally:
            self._internal = False

    def _media_status(self, status):
        if self._closed:
            return
        if self._transition:
            if self._transition.get('restoring'):
                return
            if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
                transition = self._transition
                if self.player.source() != transition['target']:
                    return
                transition['restoring'] = True
                self._transition_timer.stop()
                self._internal = True
                try:
                    self.player.setActiveAudioTrack(transition['track'])
                    self.player.setActiveVideoTrack(transition['video'])
                    self.player.setActiveSubtitleTrack(transition['subtitle'])
                    self.player.setLoops(transition['loops'])
                    self.player.setPlaybackRate(transition['rate'])
                    if self._transition is not transition:
                        return
                    self.player.setPosition(transition['position'])
                    if transition['state'] == QMediaPlayer.PlaybackState.PlayingState:
                        self.player.play()
                    elif transition['state'] == QMediaPlayer.PlaybackState.PausedState:
                        self.player.pause()
                finally:
                    self._internal = False
                    if self._transition is transition:
                        self._transition = None
                        self._refresh_subtitles(transition['position'])
            elif status == QMediaPlayer.MediaStatus.InvalidMedia:
                self._transition_failed()

    def _playback_state(self, state):
        if self._transition and not self._internal and state != QMediaPlayer.PlaybackState.StoppedState:
            self._transition['state'] = state

    def _rate_changed(self, rate):
        if self._transition and not self._internal:
            self._transition['rate'] = rate

    def _seek_requested(self, position):
        if self._transition and not self._internal:
            self._transition['position'] = position

    def _position_changed(self, position):
        # Backend zero during source loading is a reset, not a user seek.
        if position > 0:
            self._seek_requested(position)

    def _player_error(self, *_):
        if self._transition:
            self._transition_failed()

    def _transition_failed(self):
        if not self._transition:
            return
        failed = self._transition['target']
        self._transition_timer.stop()
        if failed != self._original:
            self._measurement = None
            self._tone_gain = 0.0
            self._applied_tone = 'off'
            self._apply_normalization(ramp=False)
            self._switch(self._original)
        else:
            self._transition = None
            self._refresh_subtitles()
        self.panel.set_status('Không nạp được bản xử lý; đã yêu cầu trở về âm thanh gốc.')

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._request_timer.stop()
        self._transition_timer.stop()
        self.panel.hide()
        self.volume_control.shutdown()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()
            self.worker = None


def install_audio_effects(window):
    from paths import storage_dir
    return AudioEffectsController(window, storage_dir())
