from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QGraphicsDropShadowEffect, QApplication
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QColor, QFont, QCursor, QGuiApplication,QPixmap,QPainter, QPainterPath
from ..icons import button_icon, label_icon, ACCENT

class MiniPlayer(QWidget):
    play_req = Signal()
    next_req = Signal()
    prev_req = Signal()
    restore_req = Signal()
    focus_changed = Signal(bool)  # True = focus in, False = focus out

    def __init__(self, parent=None):
        super().__init__(parent)
        # Kích thước tổng thể (bao gồm cả vùng bóng đổ trong suốt)
        self.setFixedSize(420, 64)
        
        # --- UI SETUP ---
        # Widget con này phải trong suốt để hiện bóng đổ lên nền cha
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground, True) # Để CSS hoạt động

        # Container (Viên thuốc)
        self.container = QWidget(self)
        # Cách lề: Left=10, Top=2 để chừa chỗ cho bóng đổ
        self.container.setGeometry(10, 2, 400, 60) 
        self.container.setObjectName("MiniContainer")
        # ⚠️ CẬP NHẬT NGAY: Set WA_StyledBackground để CSS hoạt động đúng (cần khi là window độc lập)
        self.container.setAttribute(Qt.WA_StyledBackground, True)

        # CSS Neon & Bo tròn
        self.setStyleSheet("""
            QWidget {
                background: transparent;
            }
            QWidget#MiniContainer {
                background-color: #111823;
                border: 1px solid #405267;
                border-radius: 30px; /* Bo tròn hoàn toàn */
            }
            QLabel { color: white; font-family: "Segoe UI"; border: none; background: transparent; }
            QPushButton {
                background: transparent; border: none; border-radius: 15px;
                color: #77E0BE; font-size: 18px; font-weight: bold;
            }
            QPushButton:hover { background-color: #253243; }
            QPushButton:pressed { background-color: #304052; }
        """)

        # Hiệu ứng Glow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 110))
        shadow.setOffset(0, 0)
        self.container.setGraphicsEffect(shadow)

        # Layout
        self.layout = QHBoxLayout(self.container)
        self.layout.setContentsMargins(15, 5, 15, 5)
        self.layout.setSpacing(10)

        # Components
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(40, 40) # Kích thước ảnh bìa
        self.lbl_icon.setStyleSheet("""
            border-radius: 20px; 
            background-color: #222222; 
            border: 1px solid #333333;
        """)
        self.lbl_icon.setScaledContents(True) # Để ảnh tự co dãn vừa khít Label
        
        self.info_layout = QVBoxLayout()
        self.info_layout.setSpacing(0)
        self.info_layout.setAlignment(Qt.AlignVCenter)
        
        self.lbl_title = QLabel("Ready")
        self.lbl_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.lbl_title.setFixedWidth(160)
        
        self.lbl_artist = QLabel("Unknown")
        self.lbl_artist.setStyleSheet("color: #aaaaaa; font-size: 9px;")
        
        self.info_layout.addWidget(self.lbl_title)
        self.info_layout.addWidget(self.lbl_artist)

        self.btn_prev = QPushButton()
        self.btn_play = QPushButton()
        self.btn_next = QPushButton()
        self.btn_prev.setFixedSize(28, 28)
        self.btn_play.setFixedSize(28, 28)
        self.btn_next.setFixedSize(28, 28)
        button_icon(self.btn_prev, "skip-back", "Bài trước", size=16)
        button_icon(self.btn_play, "play", "Phát / Tạm dừng", size=16, color=ACCENT)
        button_icon(self.btn_next, "skip-forward", "Bài tiếp theo", size=16)

        self.btn_prev.clicked.connect(self.prev_req.emit)
        self.btn_play.clicked.connect(self.play_req.emit)
        self.btn_next.clicked.connect(self.next_req.emit)

        self.layout.addWidget(self.lbl_icon)
        self.layout.addLayout(self.info_layout)
        self.layout.addStretch()
        self.layout.addWidget(self.btn_prev)
        self.layout.addWidget(self.btn_play)
        self.layout.addWidget(self.btn_next)

        # --- LOGIC KÉO THẢ ---
        self.drag_start_pos = None
        self.drag_threshold = 5
        self.is_dragging = False
        self.click_count = 0
        self.click_timer = QTimer()
        self.click_timer.setSingleShot(True)
        self.click_timer.setInterval(400) # 400ms để phân biệt click và drag(tốc độ nhấn chuột)
        self.click_timer.timeout.connect(self.handle_click_logic)
        
        # Bật mouse tracking
        self.setMouseTracking(True)
        self.container.setMouseTracking(True)
        
        # Bật focus để có thể bắt phím
        self.setFocus()
        self.setFocusPolicy(Qt.StrongFocus)

    def update_info(self, title, artist, is_playing, cover_path=None):
        display_title = (title[:20] + '..') if len(title) > 20 else title
        self.lbl_title.setText(display_title)
        self.lbl_artist.setText(artist)
        button_icon(self.btn_play, "pause" if is_playing else "play", size=16, color=ACCENT)
        
        # Sử dụng hàm bo tròn để cập nhật thumbnail
        if cover_path:
            # Gọi hàm xử lý bo tròn thay vì setPixmap trực tiếp
            self.set_rounded_pixmap(self.lbl_icon, cover_path)
        else:
            self.lbl_icon.clear() # Xóa ảnh cũ
            label_icon(self.lbl_icon, "disc-3", size=24)
            self.lbl_icon.setAlignment(Qt.AlignCenter) # Căn giữa icon đĩa nhạc
            self.lbl_icon.setStyleSheet("""
                border-radius: 20px; 
                background-color: #222222; 
                border: 1px solid #333333;
                font-size: 20px;
            """)
    
    def set_rounded_pixmap(self, label, image_path):
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            label_icon(label, "disc-3", size=24)
            return

        # Size của label
        target_size = 40
        
        # 1. Scale ảnh với giữ aspect ratio (quality cao)
        scaled_pixmap = pixmap.scaledToWidth(target_size, Qt.SmoothTransformation)
        
        # 2. Nếu ảnh bị cao hơn rộng, scale theo height thay vì width
        if scaled_pixmap.height() < target_size:
            scaled_pixmap = pixmap.scaledToHeight(target_size, Qt.SmoothTransformation)
        
        # 3. Crop thành hình vuông ở giữa
        x = (scaled_pixmap.width() - target_size) // 2
        y = (scaled_pixmap.height() - target_size) // 2
        cropped_pixmap = scaled_pixmap.copy(x, y, target_size, target_size)
        
        # 4. Tạo pixmap bo tròn với nền transparent
        rounded_pixmap = QPixmap(target_size, target_size)
        rounded_pixmap.fill(Qt.transparent)

        painter = QPainter(rounded_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        # Tạo path hình tròn
        path = QPainterPath()
        path.addEllipse(0, 0, target_size, target_size)
        painter.setClipPath(path)
        
        # Vẽ ảnh đã crop vào
        painter.drawPixmap(0, 0, cropped_pixmap)
        painter.end()

        label.setPixmap(rounded_pixmap)
                
    # Kéo thả di chuyển window
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            try:
                # Set focus để MiniPlayer có thể bắt keyboard events
                self.setFocus()
                
                # Lưu vị trí cursor toàn cầu khi nhấn
                self.drag_start_pos = event.globalPosition().toPoint()
                # Lưu vị trí window toàn cầu (tính cả frame)
                self.drag_start_window_pos = self.frameGeometry().topLeft()
                self.is_dragging = False
                event.accept()
            except Exception as e:
                print(f"Error in mousePressEvent: {e}")
                self.drag_start_pos = None

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_start_pos is not None:
            try:
                current_pos = event.globalPosition().toPoint()
                delta = current_pos - self.drag_start_pos
                
                # Kiểm tra xem đã vượt qua ngưỡng drag chưa
                if not self.is_dragging:
                    distance = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
                    if distance >= self.drag_threshold:
                        self.is_dragging = True
                        self.click_timer.stop()
                        self.click_count = 0
                
                # Nếu đang drag, di chuyển window
                if self.is_dragging:
                    new_x = self.drag_start_window_pos.x() + delta.x()
                    new_y = self.drag_start_window_pos.y() + delta.y()
                    self.move(new_x, new_y)
                    # print(f"Moving to ({new_x}, {new_y})")
                event.accept()
            except Exception as e:
                print(f"Error in mouseMoveEvent: {e}")
                pass

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Nếu không drag được (chỉ click), đếm click
            if not self.is_dragging and self.drag_start_pos is not None:
                self.click_count += 1
                self.click_timer.start()
            
            # Reset drag state
            self.drag_start_pos = None
            self.is_dragging = False
            event.accept()

    def handle_click_logic(self):
        if self.click_count == 2:
            self.restore_req.emit()
        elif self.click_count >= 3:
            self.reset_position()
        self.click_count = 0

    # Reset position về giữa màn hình
    def reset_position(self):
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos)
        if not screen: 
            screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        
        # Di chuyển MiniPlayer về giữa màn hình
        x = geo.x() + (geo.width() - 420) // 2
        y = geo.y() + 10
        
        self.move(x, y)
    
    def keyPressEvent(self, event):
        """Xử lý phím spacebar để play/pause"""
        if event.key() == Qt.Key_Space:
            if not event.isAutoRepeat():  # Tránh lặp lại khi giữ phím
                self.play_req.emit()
            event.accept()
        else:
            super().keyPressEvent(event)
    
    def focusInEvent(self, event):
        """Khi MiniPlayer nhận focus"""
        super().focusInEvent(event)
        self.focus_changed.emit(True)
        
    def focusOutEvent(self, event):
        """Khi MiniPlayer mất focus"""
        super().focusOutEvent(event)
        self.focus_changed.emit(False)
