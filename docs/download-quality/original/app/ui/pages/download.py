from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QFrame, QTextEdit, QProgressBar, 
                             QComboBox, QSpacerItem, QSizePolicy, QFileDialog, QGridLayout)
import os 
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor

from download_core.download_worker import DownloadWorker
from download_core.get_title_worker import GetTitleWorker
import json
from paths import storage_dir
from .settings_dialog import SettingMenu
from config import ConfigManager
from ..icons import button_icon, INK
from ..design_system import FORM_STYLE, DOWNLOAD_PANEL_STYLE, ICON_BUTTON_STYLE

class SmartLinkPasteTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)

    def insertFromMimeData(self, source):
        if source.hasText():
            raw_text = source.text()
            # Tách và làm sạch link
            parts = raw_text.split()
            clean_links = [p.strip() for p in parts if p.strip()]
            
            if not clean_links:
                return

            processed_text = "\n".join(clean_links)
            current_content = self.toPlainText().strip()
            
            if current_content:
                # Thêm dòng mới nếu đã có dữ liệu
                self.append(processed_text)
            else:
                self.setPlainText(processed_text)
                
            # --- SỬA DÒNG LỖI Ở ĐÂY ---
            self.moveCursor(QTextCursor.End) 
            # --------------------------
        else:
            super().insertFromMimeData(source)
            
class DownloadPage(QWidget):
    download_started_signal = Signal()
    manual_refresh_signal = Signal()
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.settings_file = str(storage_dir() / "setting.json")
        self.full_config = self.load_full_config()
        # Tạo Menu cài đặt và đặt nó làm con của DownloadPage
        self.setting_menu = SettingMenu(self, self.full_config)
        self.setting_menu.settings_saved.connect(self.update_status_label)
        # Chiều cao theo layout/font, tránh ép nhỏ làm cắt chữ trong combobox.
        self.setting_menu.ensurePolished()
        self.setting_menu.adjustSize()
        
        # --- 1. SETUP MAIN LAYOUT ---
        self.setStyleSheet(FORM_STYLE)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # --- 2. HEADER ---
        header_layout = self._header_layout = QGridLayout()
        
        # Tiêu đề
        lbl_title = QLabel("Tải video & âm nhạc")
        lbl_title.setStyleSheet("""
            font-size: 25px;
            font-weight: 700;
            font-family: 'Segoe UI';
            color: #FFFFFF;
        """)
        
        # --- NÚT SETTING 
        self.btn_settings = QPushButton()
        self.btn_settings.setFixedSize(35, 35)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.setToolTip("Cài đặt chất lượng & Hệ thống")
        # Kết nối sự kiện mở Dialog
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        button_icon(self.btn_settings, "settings", "Cài đặt tải xuống")
        
        # Nút chấm tròn (Toggle lưu thư mục)
        self.btn_toggle_path = QPushButton()
        self.btn_toggle_path.setFixedSize(24, 24)
        self.btn_toggle_path.setCheckable(True)
        self.btn_toggle_path.setChecked(False)
        self.btn_toggle_path.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_path.setStyleSheet("""
            QPushButton {
                border-radius: 12px;
                background-color: #444444; 
            }
            QPushButton:checked {
                background-color: #1DB954; /* Màu xanh lá Spotify */
            }
        """)
        self.btn_toggle_path.setToolTip("Bật: Dùng đường dẫn bên cạnh | Tắt: Lưu tại thư mục video")

        # ComboBox chứa đường dẫn lưu
        self.combo_path = QComboBox()
        self.combo_path.setEditable(True)
        self.combo_path.lineEdit().setPlaceholderText("Chọn thư mục lưu video...")
        self.combo_path.setMinimumWidth(160)
        self.combo_path.setMaximumWidth(250)
        self.combo_path.setFixedHeight(36)
        self.combo_path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_path.setStyleSheet("""
            QComboBox {
                background-color: #282828;
                color: white;
                border: 1px solid #555555;
                border-radius: 4px;
                padding-left: 5px;
            }
            QLineEdit {
                background-color: transparent;
                color: white;
            }
        """)

        # Nút mở thư mục
        self.btn_browse = QPushButton()
        button_icon(self.btn_browse, "folder-open", "Chọn thư mục lưu")
        self.btn_browse.setFixedSize(30, 30)
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Sắp xếp Header
        self._path_controls = QWidget()
        path_layout = QHBoxLayout(self._path_controls)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addStretch()
        path_layout.addWidget(self.btn_toggle_path)
        path_layout.addWidget(self.combo_path)
        path_layout.addWidget(self.btn_browse)
        header_layout.addWidget(lbl_title, 0, 0)
        header_layout.addWidget(self.btn_settings, 0, 1)
        header_layout.addWidget(self._path_controls, 0, 2)
        header_layout.setColumnStretch(2, 1)
        
        main_layout.addLayout(header_layout)

        # --- 3. BODY: 2 CỘT TEXT AREA ---
        body_layout = QHBoxLayout()
        body_layout.setSpacing(15)

        # Định dạng chung cho 2 khung

        # Cột trái: Danh sách link
        frame_left = QFrame()
        frame_left.setStyleSheet(DOWNLOAD_PANEL_STYLE)
        layout_left = QVBoxLayout(frame_left)
        layout_left.setContentsMargins(15, 10, 15, 15)
        
        lbl_link = QLabel("Danh sách link")
        lbl_link.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        self.txt_links = SmartLinkPasteTextEdit()
        self.txt_links.setAcceptRichText(False)
        self.txt_links.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        
        layout_left.addWidget(lbl_link)
        layout_left.addWidget(self.txt_links)

        # Cột phải: Tên video
        frame_right = QFrame()
        frame_right.setStyleSheet(DOWNLOAD_PANEL_STYLE)
        layout_right = QVBoxLayout(frame_right)
        layout_right.setContentsMargins(15, 10, 15, 15)
        
        lbl_name = QLabel("Tên video")
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        
        self.txt_names = QTextEdit()
        self.txt_names.setAcceptRichText(False)
        self.txt_names.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        
        layout_right.addWidget(lbl_name)
        layout_right.addWidget(self.txt_names)

        body_layout.addWidget(frame_left)
        body_layout.addWidget(frame_right)
        
        main_layout.addLayout(body_layout, stretch=1) 

        # --- 4. FOOTER: PROGRESS VÀ NÚT BẤM ---
        footer_layout = self._footer_layout = QGridLayout()
        footer_layout.setContentsMargins(0, 10, 0, 0)
        
        # === BÊN TRÁI (THÀNH CÔNG & STATUS) ===
        self._left_footer = QWidget()
        left_footer_layout = QVBoxLayout(self._left_footer)
        left_footer_layout.setContentsMargins(0, 0, 0, 0)
        left_footer_layout.setSpacing(10)
        
        progress_layout = QHBoxLayout()
        lbl_progress_text = QLabel("Thành công:")
        lbl_progress_text.setStyleSheet("color: #B3B3B3; font-size: 14px;")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumWidth(80)
        self.progress_bar.setMaximumWidth(300)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("--/--")
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #444444; background-color: #282828; color: white; font-weight: bold; font-size: 12px; border-radius: 10px; text-align: center; }
            QProgressBar::chunk { background-color: #1DB954; border-radius: 10px; }
        """)
        
        progress_layout.addWidget(lbl_progress_text)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addStretch()
        
        self.lbl_status = QLabel("Đã sẵn sàng.")
        self.lbl_status.setMinimumWidth(0)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #1DB954; font-size: 13px; font-weight: bold; font-family: Consolas;")
        
        left_footer_layout.addLayout(progress_layout)
        left_footer_layout.addWidget(self.lbl_status)
        
        # === BÊN PHẢI (THẤT BẠI & NÚT BẤM) ===
        self._right_footer = QWidget()
        right_footer_layout = QVBoxLayout(self._right_footer)
        right_footer_layout.setContentsMargins(0, 0, 0, 0)
        right_footer_layout.setSpacing(10)
        
        fail_progress_layout = QHBoxLayout()
        lbl_fail_text = QLabel("Thất bại:")
        lbl_fail_text.setStyleSheet("color: #B3B3B3; font-size: 14px;")
        
        self.fail_bar = QProgressBar()
        self.fail_bar.setMinimumWidth(80)
        self.fail_bar.setMaximumWidth(300)
        self.fail_bar.setFixedHeight(20)
        self.fail_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fail_bar.setValue(0)
        self.fail_bar.setFormat("--/--")
        self.fail_bar.setStyleSheet("""
            QProgressBar { border: 1px solid #444444; background-color: #282828; color: #E22134; font-weight: bold; font-size: 12px; border-radius: 10px; text-align: center; }
            QProgressBar::chunk { background-color: #E22134; border-radius: 10px; }
        """)
        
        fail_progress_layout.addStretch()
        fail_progress_layout.addWidget(lbl_fail_text)
        fail_progress_layout.addWidget(self.fail_bar)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        # Style chuẩn cho các nút
                
        # 1. Nút Lấy tên (Xanh dương đậm / Tối)
        self.btn_get_name = QPushButton("Lấy tên")
        self.btn_get_name.setFixedSize(90, 35)
        self.btn_get_name.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 2. Nút Bắt đầu (Trắng)
        self.btn_start = QPushButton("Bắt đầu")
        self.btn_start.setFixedSize(90, 35)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 3. Nút Dừng (Đỏ) - Mặc định ẩn/disable khi chưa tải
        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setFixedSize(90, 35)
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setEnabled(False) 

        # 4. Nút Clear (Xám)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedSize(90, 35)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 5. Nút Cập nhật (Xanh lá - Chỉ hiện/enable khi tải xong)
        self.btn_refresh_all = QPushButton("Cập nhật")
        self.btn_refresh_all.setFixedSize(90, 35)
        self.btn_refresh_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_all.setEnabled(False) # Mặc định khóa
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_get_name)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_refresh_all)
        
        right_footer_layout.addLayout(fail_progress_layout)
        right_footer_layout.addLayout(btn_layout)

        footer_layout.addWidget(self._left_footer, 0, 0)
        footer_layout.addWidget(self._right_footer, 0, 1)
        footer_layout.setColumnStretch(0, 1)
        
        main_layout.addLayout(footer_layout)
        self.btn_settings.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_browse.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_start.setProperty("role", "primary")
        self.btn_refresh_all.setProperty("role", "secondary")
        
        
        # --- KẾT NỐI TÍN HIỆU ---
        self.btn_start.clicked.connect(self.start_download)
        self.btn_clear.clicked.connect(self.clear_inputs)
        self.btn_toggle_path.toggled.connect(self.on_toggle_path)
        self.btn_browse.clicked.connect(self.browse_folder)
        self.btn_stop.clicked.connect(self.stop_download)      # Kết nối nút Stop
        self.btn_get_name.clicked.connect(self.get_video_names) # Kết nối nút Lấy tên
        self.btn_refresh_all.clicked.connect(self.trigger_manual_refresh) # Kết nối nút Cập nhật
        self.txt_links.textChanged.connect(self.update_link_count)
        
        self.download_thread = None
        from control.worker_lifecycle import WorkerOwner
        self._worker_owner = WorkerOwner(self)
        self.on_toggle_path(False)
        self._compact_layout = None
        self._arrange_controls(self.width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_compact_layout"):
            self._arrange_controls(event.size().width())

    def _arrange_controls(self, width):
        compact = width < 850
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        self._header_layout.removeWidget(self._path_controls)
        self._footer_layout.removeWidget(self._right_footer)
        if compact:
            self._header_layout.addWidget(self._path_controls, 1, 0, 1, 3)
            self._footer_layout.addWidget(self._right_footer, 1, 0, 1, 2)
        else:
            self._header_layout.addWidget(self._path_controls, 0, 2)
            self._footer_layout.addWidget(self._right_footer, 0, 1)

    # ==========================================
    # CÁC HÀM XỬ LÝ LOGIC GIAO DIỆN
    # ==========================================
    def highlight_completed_row(self, index, success=True):
        """Nhuộm màu bằng QTextCursor - Cách chuẩn nhất để không bị nhảy giao diện"""
        color = "#1DB954" if success else "#E22134"
        
        for text_edit in [self.txt_links, self.txt_names]:
            # Đảm bảo TextEdit đang hiển thị dưới dạng văn bản có thể định dạng
            doc = text_edit.document()
            cursor = QTextCursor(doc)
            
            # Di chuyển đến dòng thứ 'index'
            cursor.movePosition(QTextCursor.Start)
            for _ in range(index):
                cursor.movePosition(QTextCursor.NextBlock)
            
            # Chọn dòng hiện tại
            cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            
            # Áp dụng màu sắc
            fmt = cursor.charFormat()
            fmt.setForeground(Qt.GlobalColor.green if success else Qt.GlobalColor.red)
            # Nếu bác muốn dùng mã màu hex chính xác của bác:
            from PySide6.QtGui import QColor
            fmt.setForeground(QColor(color))
            
            cursor.setCharFormat(fmt)
            
    def update_link_count(self):
        """ Tự động đếm số lượng link khi người dùng dán vào txt_links """
        links_text = self.txt_links.toPlainText().strip()
        links = links_text.split()
        count = len(links)
        
        if count == 0:
            self.progress_bar.setFormat("--/--")
            self.fail_bar.setFormat("--/--")
            self.progress_bar.setMaximum(1) # Tránh lỗi đồ họa chia cho 0
            self.fail_bar.setMaximum(1)
        else:
            self.progress_bar.setMaximum(count)
            self.fail_bar.setMaximum(count)
            self.progress_bar.setFormat(f"%v/{count}")
            self.fail_bar.setFormat(f"%v/{count}")

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video")
        if folder:
            self.combo_path.setCurrentText(folder)
            if not self.btn_toggle_path.isChecked():
                self.btn_toggle_path.setChecked(True)
                
    def on_toggle_path(self, checked):
        if checked:
            self.combo_path.setEnabled(True)
            self.btn_browse.setEnabled(True)
            self.combo_path.setStyleSheet("""
                QComboBox { background-color: #282828; color: white; border: 1px solid #555; border-radius: 4px; }
                QLineEdit { background-color: transparent; color: white; }
            """)
            self.lbl_status.setText("Chế độ: Lưu theo đường dẫn tùy chỉnh.")
        else:
            self.combo_path.setEnabled(False)
            self.btn_browse.setEnabled(False)
            self.combo_path.setStyleSheet("""
                QComboBox { background-color: #121212; color: #555; border: 1px solid #333; border-radius: 4px; }
                QLineEdit { background-color: transparent; color: #555; }
            """)
            self.lbl_status.setText("Chế độ: Lưu tại thư mục của App.")

    def clear_inputs(self):
        print("\n[DEBUG] >>> ĐÃ BẤM NÚT 'CLEAR'")
        # Reset bằng chuỗi rỗng để xóa sạch vết tích HTML cũ
        self.txt_links.clear() 
        self.txt_names.clear()
        
        self.progress_bar.setValue(0)
        self.fail_bar.setValue(0)
        self.lbl_status.setText("Đã dọn dẹp sẵn sàng.")
        self.lbl_status.setStyleSheet("color: #1DB954; font-size: 14px; font-weight: bold;")

    def start_download(self):
        print("\n[DEBUG] >>> ĐÃ BẤM NÚT 'BẮT ĐẦU'") # <--- Thêm dòng này
        links_text = self.txt_links.toPlainText().strip()
        names_text = self.txt_names.toPlainText().strip()
        
        print(f"[DEBUG] Số link đã nhập: {len(links_text.split())}")

        links = [line.strip() for line in self.txt_links.toPlainText().split('\n') if line.strip()]
        names = [line.strip() for line in self.txt_names.toPlainText().split('\n') if line.strip()]

        if not links or not names:
            self.lbl_status.setText("Lỗi: Vui lòng nhập link và tên video!")
            self.lbl_status.setStyleSheet("color: #E22134; font-size: 14px; font-weight: bold;") 
            return
            
        if len(links) != len(names):
            self.lbl_status.setText(f"Lỗi: Số link ({len(links)}) và số tên ({len(names)}) không khớp!")
            self.lbl_status.setStyleSheet("color: #E22134; font-size: 14px; font-weight: bold;")
            return

        self.lbl_status.setStyleSheet("color: #1DB954; font-size: 14px; font-weight: bold;") 

        if self.btn_toggle_path.isChecked():
            # Chế độ bật tích xanh: Lấy đường dẫn từ ComboBox
            save_path = self.combo_path.currentText().strip()
            if not save_path:
                self.lbl_status.setText("Lỗi: Vui lòng nhập đường dẫn thư mục!")
                self.lbl_status.setStyleSheet("color: #E22134; font-size: 14px; font-weight: bold;")
                return
            if not os.path.exists(save_path):
                try:
                    os.makedirs(save_path)
                except:
                    self.lbl_status.setText("Lỗi: Đường dẫn không hợp lệ!")
                    self.lbl_status.setStyleSheet("color: #E22134; font-size: 14px; font-weight: bold;")
                    return
        else:
            # TẮT TÍCH XANH: Lấy lại 'last_folder' từ ConfigManager
            from config import ConfigManager
            
            # Gọi thẳng hàm của bác luôn
            save_path = ConfigManager.get_last_folder()

            # Kiểm tra xem app đã từng chọn thư mục gốc chưa (nếu trống hoặc thư mục bị xóa mất)
            if not save_path or not os.path.exists(save_path):
                self.lbl_status.setText("Lỗi: Chưa có thư mục gốc! Hãy qua tab video chọn thư mục trước.")
                self.lbl_status.setStyleSheet("color: #E22134; font-size: 14px; font-weight: bold;")
                return

        # Lưu lại save_path vào biến class để hàm download_finished in ra được
        self.current_save_path = save_path
        self.btn_start.setEnabled(False)
        self.btn_get_name.setEnabled(False) # Khóa nút lấy tên khi đang tải
        self.btn_clear.setEnabled(False)    # Khóa nút clear
        self.btn_stop.setEnabled(True)
        self.btn_start.setText("Đang tải...")
        self.progress_bar.setValue(0)
        self.fail_bar.setValue(0)
        print(f"[DEBUG] Chuẩn bị khởi chạy Thread với {len(links)} video")
        self.download_thread = DownloadWorker(links, names, save_path, self.full_config)
        self._worker_owner.own(self.download_thread)

        self.download_thread.progress_signal.connect(self.update_progress)
        self.download_thread.fail_signal.connect(self.update_fail_progress)
        self.download_thread.status_signal.connect(self.update_status)
        self.download_thread.finished_signal.connect(self.download_finished)
        self.download_thread.log_signal.connect(self.parse_live_log)
        self.download_started_signal.emit()
        # CHẠY!
        print("[DEBUG] Gọi lệnh .start() ngay bây giờ...")
        self.download_thread.start()
    
    def update_progress(self, current, total):
        self.progress_bar.setValue(current)
        self.highlight_completed_row(current - 1, success=True)
        
    # Nếu sau này trong downloadworker.py có bắn tín hiệu lỗi, bạn dùng hàm này:
    def update_fail_progress(self, current_fail, total):
        self.fail_bar.setValue(current_fail)
        # Tính toán index để nhuộm đỏ dòng bị lỗi
        total_processed = self.progress_bar.value() + current_fail
        self.highlight_completed_row(total_processed - 1, success=False)
        
    def update_status(self, text):
        self.lbl_status.setText(text)

    def download_finished(self, success_count):
        self.btn_start.setEnabled(True)
        self.btn_get_name.setEnabled(True) # Mở lại
        self.btn_clear.setEnabled(True)    # Mở lại
        self.btn_stop.setEnabled(False)    # Khóa lại nút Dừng
        self.btn_start.setText("Bắt đầu")
        self.lbl_status.setText(f"🎉 Hoàn tất! Tải thành công {success_count} video.")
        self.btn_refresh_all.setEnabled(True)
        
    def stop_download(self):
        print("\n[DEBUG] >>> ĐÃ BẤM NÚT 'DỪNG'")
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.stop() # Gọi lệnh dừng bên worker
            self.lbl_status.setText("Đang hủy quá trình tải...")
            self.lbl_status.setStyleSheet("color: #E22134; font-size: 14px; font-weight: bold;")
            self.btn_stop.setEnabled(False) # Ấn 1 lần là khóa tránh spam
            self.btn_refresh_all.setEnabled(True)

    def parse_live_log(self, text):
        """Hàm này lọc log từ yt-dlp để chỉ in ra các dòng chứa % và tốc độ"""
        if "[download]" in text and "%" in text:
            # text gốc của yt-dlp thường là: [download]  15.3% of 10.00MiB at 3.00MiB/s ETA 00:05
            clean_text = text.replace("[download]", "⏬ Tốc độ:").strip()
            self.lbl_status.setText(clean_text)
            self.lbl_status.setStyleSheet("color: #00FFFF; font-size: 13px; font-weight: bold; font-family: Consolas;")
        elif "Đang cập nhật" in text or "Cập nhật" in text:
            self.lbl_status.setText(text)
            self.lbl_status.setStyleSheet("color: #F1C40F; font-size: 13px; font-weight: bold; font-family: Consolas;")
    
    def load_full_config(self):
        try:
            with open(self.settings_file, "r") as f:
                return json.load(f)
        except:
            return {}

    def update_status_label(self, message):
        self.lbl_status.setText(message)
        self.full_config = self.load_full_config()

    def trigger_manual_refresh(self):
        self.manual_refresh_signal.emit()
        self.btn_refresh_all.setEnabled(False) # Bấm xong thì khóa lại
        self.lbl_status.setText("🔄 Đã cập nhật danh sách video mới.")
          
    def get_video_names(self):
        links_text = self.txt_links.toPlainText().strip()
        if not links_text:
            self.lbl_status.setText("Lỗi: Vui lòng dán link trước khi lấy tên!")
            self.lbl_status.setStyleSheet("color: #E22134; font-weight: bold;")
            return

        links = [line.strip() for line in links_text.split('\n') if line.strip()]
        
        self.btn_get_name.setEnabled(False)
        self.btn_get_name.setText("Đang chạy...") # Đổi tên cho bao quát cả việc update
        self.txt_names.clear() 
        
        self.title_thread = GetTitleWorker(links)
        self._worker_owner.own(self.title_thread)
        
        # Kết nối các tín hiệu cũ
        self.title_thread.title_ready_signal.connect(self.append_title_to_ui)
        self.title_thread.status_signal.connect(self.update_status)
        self.title_thread.finished_signal.connect(self.get_names_finished)

        self.title_thread.log_signal.connect(self.parse_live_log) 
        
        self.title_thread.start()

    def append_title_to_ui(self, title):
        current_text = self.txt_names.toPlainText()
        new_text = (current_text + "\n" + title) if current_text else title
        self.txt_names.setPlainText(new_text)
        
        self.txt_names.verticalScrollBar().setValue(self.txt_names.verticalScrollBar().maximum())

    def shutdown_workers(self):
        self._worker_owner.shutdown()

    def get_names_finished(self):
        self.btn_get_name.setEnabled(True)
        self.btn_get_name.setText("Lấy tên")
        self.lbl_status.setText("✅ Đã lấy xong danh sách tên video.")
        self.lbl_status.setStyleSheet("color: #1DB954; font-weight: bold;")
    
    def open_settings_dialog(self):
        # Tính toán vị trí để nó hiện ngay dưới nút ⚙️ hoặc ở giữa màn hình
        # Ở đây tôi cho nó hiện ở giữa trang Download cho đẹp
        pos_x = (self.width() - self.setting_menu.width()) // 2
        pos_y = (self.height() - self.setting_menu.height()) // 2
        self.setting_menu.move(pos_x, pos_y)
        
        # Hiện/Ẩn menu (Toggle)
        if self.setting_menu.isVisible():
            self.setting_menu.hide()
        else:
            self.setting_menu.show()
            self.setting_menu.raise_() # Đảm bảo nó nằm trên cùng
