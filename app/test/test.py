import sys
import os
import re
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget


# ===== IMPORT MODULE APP =====
from ui.main_window import MainWindow
from subtitle.mode import SubtitleMode 

# =========================================================
# CẤU HÌNH ĐƯỜNG DẪN: ưu tiên env vars, fallback sang `app.paths`
# =========================================================
from paths import get_input_path, temp_dir

# Environment overrides (convenient for CI / other machines)
VIDEO_PATH = os.environ.get("TEST_VIDEO_PATH") or str(get_input_path("【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！.mp4"))
ASS_PATH = os.environ.get("TEST_ASS_PATH") or str(temp_dir() / "【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！.ass")

# =========================================================
# BỘ GIẢI MÃ FILE .ASS THỰC THỤ
# =========================================================
class ASSParser:
    @staticmethod
    def time_to_ms(time_str):
        try:
            h, m, s = time_str.split(':')
            return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
        except:
            return 0

    @classmethod
    def parse_file(cls, file_path):
        if not os.path.exists(file_path):
            print(f"❌ KHÔNG TÌM THẤY FILE TẠI: {file_path}")
            return []
        
        # Thử đọc với utf-8, nếu lỗi thì dùng utf-8-sig (cho file ASS có BOM)
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()

        segments_map = {}
        # Regex bắt Dialogue: Start, End, Style, Text
        pattern = re.compile(r"Dialogue: \d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),([^,]+),.*?,.*?,.*?,.*?,.*?,(.*)")
        
        for line in content.split('\n'):
            match = pattern.match(line)
            if match:
                start_str, end_str, style, raw_text = match.groups()
                start_ms = cls.time_to_ms(start_str)
                end_ms = cls.time_to_ms(end_str)
                
                # Làm sạch tag định dạng {\...} và xuống dòng \N
                clean_text = re.sub(r'\{.*?\}', '', raw_text).replace(r'\N', '\n').strip()
                
                time_key = (start_ms, end_ms)
                if time_key not in segments_map:
                    segments_map[time_key] = {'start': start_ms, 'end': end_ms, 'jp': '', 'vi': ''}
                
                style_upper = style.upper()
                if "JP" in style_upper:
                    segments_map[time_key]['jp'] = clean_text
                elif "VI" in style_upper:
                    segments_map[time_key]['vi'] = clean_text
                else:
                    # Nếu là các style khác (EN, v.v.) thì cho vào VI nếu VI đang trống
                    if not segments_map[time_key]['vi']:
                        segments_map[time_key]['vi'] = clean_text

        return sorted(segments_map.values(), key=lambda x: x['start'])

# ===== MEDIA PLAYER WRAPPER =====
class MediaPlayerWrapper(QObject):
    def __init__(self):
        super().__init__()
        self.video_widget = QVideoWidget()
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

    def play(self, path):
        if os.path.exists(path):
            self.player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
            self.player.play()
            print(f"🎬 Đang phát video: {os.path.basename(path)}")
        else:
            print(f"❌ Không tìm thấy file video tại: {path}")

# ===== MOCK CLASSES =====
class MockMediaLibrary:
    def scan_folder(self, _): return []
class MockJobManager(QObject):
    thumbnail_done = Signal(str, object) 
    def extract_thumbnail_async(self, *args, **kwargs): pass
class MockSubtitleManager:
    def __init__(self): self.dirs = {'temp': os.getcwd()}
    def get_reliable_id(self, _): return "test_id"

def main():
    app = QApplication(sys.argv)
    media_player = MediaPlayerWrapper()

    # 1. Giải mã file từ đường dẫn bác cung cấp
    print(f"🔍 Đang kiểm tra file ASS...")
    segments = ASSParser.parse_file(ASS_PATH)

    # 2. Khởi tạo giao diện
    window = MainWindow(
        subtitle_manager=MockSubtitleManager(),
        job_manager=MockJobManager(),
        media_library=MockMediaLibrary(),
        media_player=media_player
    )

    if hasattr(window, 'sub_layer'):
        if segments:
            window.sub_layer.load_subtitles(segments)
            window.sub_layer.set_mode(SubtitleMode.JP_EN_VI)
            print(f"✅ Đã nạp {len(segments)} cụm phụ đề.")
        
        # Kết nối đồng bộ position
        media_player.player.positionChanged.connect(window.sub_layer.update_position)

    window.resize(1280, 720)
    window.show()

    # 3. Play video ngay lập tức
    media_player.play(VIDEO_PATH)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()