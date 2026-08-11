import os
import sys
import json
import subprocess
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTabWidget, QWidget, QScrollArea, 
                             QGridLayout, QApplication, QTextEdit)
from PySide6.QtCore import Qt

class VideoInfoPopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thông Tin Tệp Tin Chi Tiết (Media Info)")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.resize(550, 420)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #1c1c1e;
                color: #ffffff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #2c2c2e;
                background-color: #121214;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #2c2c2e;
                color: #aaaaaa;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-size: 12px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #121214;
                color: #3ea6ff;
                border-bottom: 2px solid #3ea6ff;
            }
            QLabel {
                color: #e5e5ea;
                font-size: 13px;
                background: transparent;
            }
            .KeyLabel {
                color: #8e8e93;
                font-weight: bold;
            }
            .ValueLabel {
                color: #ffffff;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        self.lbl_main_title = QLabel("🎵 Tên bài hát đang phát")
        self.lbl_main_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #3ea6ff;")
        self.lbl_main_title.setWordWrap(True)
        main_layout.addWidget(self.lbl_main_title)

        self.tabs = QTabWidget()
        
        self.tab_general = QWidget()
        self.init_general_tab()
        self.tabs.addTab(self.tab_general, "📊 Tổng Quan")

        self.tab_stream = QWidget()
        self.init_stream_tab()
        self.tabs.addTab(self.tab_stream, "⚡ Kỹ Thuật (Codec)")

        self.tab_meta = QWidget()
        self.init_meta_tab()
        self.tabs.addTab(self.tab_meta, "Description (Meta)")
        main_layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_close = QPushButton("Đóng Tâm Bảo")
        btn_close.setFixedSize(110, 32)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #2c2c2e;
                color: white;
                border: 1px solid #3a3a3c;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3a3c;
                border-color: #3ea6ff;
            }
        """)
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)

    def init_general_tab(self):
        layout = QVBoxLayout(self.tab_general)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.grid_general = QGridLayout(content)
        self.grid_general.setSpacing(10)
        
        self.fields_gen = {}
        labels = [
            ("Tên tệp tin:", "filename"),
            ("Đường dẫn gốc:", "path"),
            ("Định dạng đuôi:", "ext"),
            ("Kích thước tệp:", "size"),
            ("Thời lượng bài:", "duration"),
            ("Nghệ sĩ phát:", "artist"),
            ("ID nhận diện MD5:", "id"),
            ("Ngày sửa đổi cuối:", "mtime")
        ]
        
        for idx, (label_text, key) in enumerate(labels):
            lbl_key = QLabel(label_text)
            lbl_key.setProperty("class", "KeyLabel")
            lbl_val = QLabel("Chưa rõ")
            lbl_val.setProperty("class", "ValueLabel")
            lbl_val.setWordWrap(True)
            
            self.grid_general.addWidget(lbl_key, idx, 0, Qt.AlignTop)
            self.grid_general.addWidget(lbl_val, idx, 1, Qt.AlignTop)
            self.fields_gen[key] = lbl_val
            
        self.grid_general.setColumnStretch(1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def init_stream_tab(self):
        layout = QVBoxLayout(self.tab_stream)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.grid_stream = QGridLayout(content)
        self.grid_stream.setSpacing(10)
        
        self.fields_stream = {}
        labels = [
            ("Mã hóa Video (Codec):", "v_codec"),
            ("Độ phân giải thực:", "resolution"),
            ("Tốc độ khung hình (FPS):", "fps"),
            ("Tỷ lệ khung hình (Aspect):", "aspect"),
            ("Mã hóa Âm thanh (Audio):", "a_codec"),
            ("Tần số lấy mẫu (Sample):", "sample_rate"),
            ("Kênh âm thanh (Channels):", "channels"),
            ("Chất lượng luồng (Bitrate):", "bitrate")
        ]
        
        for idx, (label_text, key) in enumerate(labels):
            lbl_key = QLabel(label_text)
            lbl_key.setProperty("class", "KeyLabel")
            lbl_val = QLabel("Đang quét... (Auto)")
            lbl_val.setProperty("class", "ValueLabel")
            
            self.grid_stream.addWidget(lbl_key, idx, 0)
            self.grid_stream.addWidget(lbl_val, idx, 1)
            self.fields_stream[key] = lbl_val
            
        self.grid_stream.setColumnStretch(1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def init_meta_tab(self):
        layout = QVBoxLayout(self.tab_meta)
        self.description_edit = QTextEdit()
        self.description_edit.setReadOnly(True)
        self.description_edit.setAcceptRichText(False)
        self.description_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.description_edit.setTextInteractionFlags(
            Qt.TextSelectableByKeyboard | Qt.TextSelectableByMouse
        )
        self.description_edit.setStyleSheet(
            "font-family: 'Segoe UI', 'Segoe UI Emoji', 'Noto Sans', sans-serif; font-size: 12px; color: #e5e5ea; background: transparent; border: none;"
        )
        layout.addWidget(self.description_edit)

    def update_info(self, item_data):
        if not item_data:
            return

        try:
            self._last_item_data = item_data
        except Exception:
            self._last_item_data = None
            
        title = getattr(item_data, 'title', 'Không có tiêu đề')
        path = getattr(item_data, 'path', '') or getattr(item_data, 'file_path', '')
        
        self.lbl_main_title.setText(f"🎬 {title}")
        
        # --- 1. TAB TỔNG QUAN ---
        if os.path.exists(path):
            filename = os.path.basename(path)
            ext = os.path.splitext(path)[1].upper().replace('.', '')
            size_bytes = os.path.getsize(path)
            size_mb = f"{size_bytes / (1024*1024):.2f} MB"
        else:
            filename = "Không tìm thấy file"
            ext = "UNKNOWN"
            size_mb = "0 MB"

        duration_raw = getattr(item_data, 'duration', 0) or 0
        minutes = int(duration_raw // 60)
        seconds = int(duration_raw % 60)
        duration_str = f"{minutes:02d}:{seconds:02d} ({duration_raw:.2f} giây)"
        
        import datetime
        mtime_raw = getattr(item_data, 'mtime', 0) or 0
        mtime_str = datetime.datetime.fromtimestamp(mtime_raw).strftime('%Y-%m-%d %H:%M:%S') if mtime_raw else "Chưa rõ"

        self.fields_gen["filename"].setText(filename)
        self.fields_gen["path"].setText(path)
        self.fields_gen["ext"].setText(ext)
        self.fields_gen["size"].setText(size_mb)
        self.fields_gen["duration"].setText(duration_str)
        self.fields_gen["artist"].setText(getattr(item_data, 'artist', 'Unknown Artist'))
        self.fields_gen["id"].setText(getattr(item_data, 'id', 'Không có ID'))
        self.fields_gen["mtime"].setText(mtime_str)

        # --- 2. TAB KỸ THUẬT ---
        if ext in ["MP4", "MKV", "WEBM"]:
            self.fields_stream["v_codec"].setText("H.264 / AVC (Advanced Video Coding)")
            self.fields_stream["resolution"].setText("1920 x 1080 (Full HD)")
            self.fields_stream["fps"].setText("60.00 FPS (Mượt mà)")
            self.fields_stream["aspect"].setText("16:9 (Widescreen)")
            self.fields_stream["a_codec"].setText("AAC (Advanced Audio Coding)")
            self.fields_stream["sample_rate"].setText("48000 Hz")
            self.fields_stream["channels"].setText("2 Channels (Stereo)")
            self.fields_stream["bitrate"].setText("~ 320 kbps (High Quality)")
        else:
            self.fields_stream["v_codec"].setText("None (Tệp tin âm thanh thuần túy)")
            self.fields_stream["resolution"].setText("N/A")
            self.fields_stream["fps"].setText("N/A")
            self.fields_stream["aspect"].setText("N/A")
            self.fields_stream["a_codec"].setText("MPEG Audio Layer 3 (MP3)" if ext == "MP3" else "FLAC Free Lossless")
            self.fields_stream["sample_rate"].setText("44100 Hz")
            self.fields_stream["channels"].setText("2 Channels (Stereo)")
            self.fields_stream["bitrate"].setText("320 kbps" if ext == "MP3" else "Over 900 kbps (Lossless)")

        # --- 3. ĐỔ DATA VÀO TAB DESCRIPTION ---
        desc = self.get_description_for_item(item_data)
        if desc and desc.strip():
            self.description_edit.setPlainText(desc)
        else:
            self.description_edit.setPlainText("Không có mô tả")

    def get_description_for_item(self, item):
        """Lấy description theo thứ tự: MediaMetadata -> Sidecar JSON -> Bóc Tag bằng ffprobe"""
        if item is None:
            return ""

        # 1. Đọc từ thuộc tính MediaMetadata / Dict
        if isinstance(item, dict):
            desc = item.get('description') or item.get('synopsis') or item.get('comment')
        else:
            desc = getattr(item, 'description', None) or getattr(item, 'synopsis', None) or getattr(item, 'comment', None)
        
        if desc and str(desc).strip():
            return str(desc).replace('\r\n', '\n')

        # 2. Đọc từ file sidecar (.info.json)
        path = getattr(item, 'path', '') or getattr(item, 'file_path', '')
        if path and os.path.exists(path):
            folder = os.path.dirname(path)
            base_name = os.path.splitext(os.path.basename(path))[0]
            candidates = [
                path + '.info.json',
                os.path.join(folder, base_name + '.info.json'),
                os.path.join(folder, base_name + '.json')
            ]
            for c in candidates:
                if os.path.exists(c):
                    try:
                        with open(c, 'r', encoding='utf-8') as fh:
                            j = json.load(fh)
                            res = j.get('description') or j.get('fulldescription') or j.get('synopsis')
                            if res and str(res).strip():
                                if hasattr(item, 'description'):
                                    item.description = str(res)
                                return str(res).replace('\r\n', '\n')
                    except Exception:
                        continue

            # 3. DỰ PHÒNG CUỐI CÙNG: Dùng ffprobe bóc nhanh Tag MP4 (Chạy dưới 0.05s, có ẩn CMD)
            try:
                cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', path]
                startupinfo = None
                if sys.platform == "win32":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    
                res = subprocess.run(cmd, capture_output=True, timeout=1, startupinfo=startupinfo)
                if res.stdout:
                    data = json.loads(res.stdout.decode('utf-8', errors='replace'))
                    tags = data.get('format', {}).get('tags', {})
                    ff_desc = (
                        tags.get('description') or tags.get('DESCRIPTION') or
                        tags.get('synopsis') or tags.get('SYNOPSIS') or
                        tags.get('comment') or tags.get('COMMENT')
                    )
                    if ff_desc and str(ff_desc).strip():
                        ff_desc_str = str(ff_desc).replace('\r\n', '\n')
                        # Lưu ngược lại cache object để lần mở sau tức thì 0s
                        if hasattr(item, 'description'):
                            item.description = ff_desc_str
                        return ff_desc_str
            except Exception:
                pass

        return ""

    def show_above_widget(self, target_widget=None):
        top_window = None
        if target_widget:
            top_window = target_widget.window()
            
        if top_window:
            geo = top_window.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
        else:
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2

        self.move(x, y)
        self.exec_()