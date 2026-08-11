import os
from winsdk.windows.media import (SystemMediaTransportControls, 
                                 SystemMediaTransportControlsButton as Button,
                                 MediaPlaybackStatus, MediaPlaybackType)
from winsdk.windows.storage.streams import RandomAccessStreamReference

class WindowsMediaManager:
    def __init__(self, player_owner):
        # player_owner chính là cái class InternalMediaPlayer nằm trong MainWindow của bác
        self.owner = player_owner
        
        # Khởi tạo bộ điều khiển hệ thống
        self.controls = SystemMediaTransportControls.get_for_current_view()
        
        # Bật các nút bấm trên giao diện Windows
        self.controls.is_play_enabled = True
        self.controls.is_pause_enabled = True
        self.controls.is_next_enabled = True
        self.controls.is_previous_enabled = True
        
        # Lắng nghe khi người dùng bấm nút trên bảng điều khiển Windows
        self.controls.add_button_pressed(self._handle_buttons)

    def _handle_buttons(self, sender, args):
        btn = args.button
        if btn == Button.PLAY:
            self.owner.play()
        elif btn == Button.PAUSE:
            self.owner.pause()
        elif btn == Button.NEXT:
            # Gọi hàm qua bài trong MainWindow (bác cần có hàm này)
            if hasattr(self.owner.parent(), 'next_song'): 
                self.owner.parent().next_song()
        elif btn == Button.PREVIOUS:
            # Gọi hàm lùi bài trong MainWindow
            if hasattr(self.owner.parent(), 'prev_song'):
                self.owner.parent().prev_song()

    def update_track(self, title, artist, thumb_path):
        """Đẩy thông tin bài hát lên Windows"""
        updater = self.controls.display_updater
        updater.type = MediaPlaybackType.MUSIC
        updater.music_properties.title = title
        updater.music_properties.artist = artist
        
        # Xử lý ảnh thumbnail
        if thumb_path and os.path.exists(thumb_path):
            try:
                abs_path = os.path.abspath(thumb_path)
                uri = "file:///" + abs_path.replace("\\", "/")
                updater.thumbnail = RandomAccessStreamReference.create_from_uri(uri)
            except: pass
        updater.update()

    def set_state(self, is_playing):
        """Đổi trạng thái nút Play/Pause trên Windows"""
        self.controls.playback_status = (MediaPlaybackStatus.PLAYING 
                                        if is_playing else MediaPlaybackStatus.PAUSED)