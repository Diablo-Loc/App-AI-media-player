from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QTabWidget, QWidget, QScrollArea, 
                             QGridLayout, QApplication, QTextEdit)
from PySide6.QtCore import Qt
from .icons import icon
from .design_system import DIALOG_STYLE
from .media_info_probe import MediaInfoRequests, item_snapshot, read_media_info, UNKNOWN

class VideoInfoPopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Thông Tin Tệp Tin Chi Tiết (Media Info)")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowStaysOnTopHint)
        self.resize(550, 420)
        self.init_ui()
        self.setStyleSheet(DIALOG_STYLE)
        self._info_requests = MediaInfoRequests(self)
        self._info_requests.ready.connect(self._apply_info)
        self.finished.connect(self._info_requests.cancel)

    def init_ui(self):

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        self.lbl_main_title = QLabel("🎵 Tên bài hát đang phát")
        self.lbl_main_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #3ea6ff;")
        self.lbl_main_title.setWordWrap(True)
        main_layout.addWidget(self.lbl_main_title)

        self.tabs = QTabWidget()
        
        self.tab_general = QWidget()
        self.tab_general.setObjectName("detailTab")
        self.tab_general.setAttribute(Qt.WA_StyledBackground, True)
        self.init_general_tab()
        self.tabs.addTab(self.tab_general, icon("info"), "Tổng Quan")

        self.tab_stream = QWidget()
        self.tab_stream.setObjectName("detailTab")
        self.tab_stream.setAttribute(Qt.WA_StyledBackground, True)
        self.init_stream_tab()
        self.tabs.addTab(self.tab_stream, icon("settings"), "Kỹ Thuật (Codec)")

        self.tab_meta = QWidget()
        self.tab_meta.setObjectName("detailTab")
        self.tab_meta.setAttribute(Qt.WA_StyledBackground, True)
        self.init_meta_tab()
        self.tabs.addTab(self.tab_meta, "Description (Meta)")
        main_layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_close = QPushButton("Đóng Tâm Bảo")
        btn_close.setFixedSize(110, 32)
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)

    def init_general_tab(self):
        layout = QVBoxLayout(self.tab_general)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("detailContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
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
        content.setObjectName("detailContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
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
        self._last_item_data = item_data
        self._info_requests.cancel()
        if not item_data:
            self.lbl_main_title.setText("Không có bài hát")
            for label in (*self.fields_gen.values(), *self.fields_stream.values()):
                label.setText(UNKNOWN)
            self.description_edit.setPlainText("Không có mô tả")
            return
        item = item_snapshot(item_data)
        self.lbl_main_title.setText(f"🎬 {item['title'] or 'Không có tiêu đề'}")
        for label in (*self.fields_gen.values(), *self.fields_stream.values()):
            label.setText("Đang đọc…")
            label.setToolTip("")
        for key in ('path', 'artist', 'id'):
            self.fields_gen[key].setText(str(item[key] or UNKNOWN))
        self.description_edit.setPlainText(item['description'] or "Đang đọc mô tả…")
        self._info_requests.request(item)

    def _apply_info(self, result):
        for key, label in self.fields_stream.items():
            label.setText(result['stream'].get(key, UNKNOWN))
            label.setToolTip(result['error'])
        for key in ('filename', 'ext', 'size', 'duration', 'mtime'):
            self.fields_gen[key].setText(result['general'].get(key, UNKNOWN))
            self.fields_gen[key].setToolTip(result['error'])
        self.description_edit.setPlainText(result['description'] or "Không có mô tả")

    def get_description_for_item(self, item):
        """Synchronous compatibility API; popup updates use the owned worker instead."""
        if item is None:
            return ""
        from collections import OrderedDict
        from control.worker_lifecycle import OwnedProcesses
        snapshot = item_snapshot(item)
        if snapshot['description'].strip():
            return snapshot['description']
        return read_media_info(snapshot, OrderedDict(), OwnedProcesses(), lambda: False)['description']

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
