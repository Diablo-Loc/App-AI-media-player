from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QUrl, Signal, Qt,QEvent

class MediaPlayer(QWidget):
    # Signal để đồng bộ với MainWindow và PlaybackBar
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    fullscreenRequested = Signal()
    playbackStateChanged = Signal(object) # Gửi trạng thái PlayingState, PausedState...

    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. Cấu hình Engine phát (Player + Audio)
        self.player = QMediaPlayer()
        self.audio = QAudioOutput()
        self.player.setAudioOutput(self.audio)
        
        # 2. Cấu hình màn hình hiển thị
        #self.video_widget = VideoWidgetWithSub(sub_layer) 
        # Cho phép chuột xuyên qua hoặc bắt sự kiện tùy vào yêu cầu subtitle layer
        self.video_widget.setMouseTracking(True)
        
        # Gắn đầu ra video vào máy phát
        self.player.setVideoOutput(self.video_widget)
        
        # 3. Giao diện chứa Video (Layout)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_widget)

        # 4. Chuyển tiếp (Forward) các Signal từ QMediaPlayer ra ngoài lớp này
        # Việc này giúp MainWindow không cần can thiệp sâu vào thuộc tính nội bộ .player
        self.player.positionChanged.connect(self.positionChanged.emit)
        self.player.durationChanged.connect(self.durationChanged.emit)
        self.player.playbackStateChanged.connect(self.playbackStateChanged.emit)
        # Cài đặt event filter để bắt sự kiện click trên video_widget
        self.video_widget.installEventFilter(self)
        
    # --- CÁC HÀM ĐIỀU KHIỂN (API cho MainWindow gọi) ---

    def play(self, file_path=None):
        """Phát video. Nếu có path thì load mới, nếu không thì resume."""
        if file_path:
            self.player.setSource(QUrl.fromLocalFile(str(file_path)))
        self.player.play()

    def pause(self):
        """Tạm dừng video"""
        self.player.pause()

    def stop(self):
        """Dừng hẳn video"""
        self.player.stop()

    def toggle_play(self):
        """Hàm tiện ích để đảo trạng thái Play/Pause"""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.pause()
        else:
            self.play()

    def set_position(self, ms):
        """Nhảy đến thời gian cụ thể (Seek)"""
        self.player.setPosition(ms)

    def set_volume(self, value):
        """
        Nhận giá trị từ 0.0 đến 1.0 từ PlaybackBar.
        Đảm bảo đồng bộ tuyệt đối với QAudioOutput.
        """
        self.audio.setVolume(value)

    def get_state(self):
        """Trả về trạng thái hiện tại (Playing, Paused, Stopped)"""
        return self.player.playbackState()

    def is_playing(self):
        """Kiểm tra nhanh xem có đang phát không"""
        return self.player.playbackState() == QMediaPlayer.PlayingState
    def eventFilter(self, watched, event):
        if watched == self.video_widget:
            # Bắt sự kiện Double Click chuột trái
            if event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self.fullscreenRequested.emit()
                    return True
        return super().eventFilter(watched, event)