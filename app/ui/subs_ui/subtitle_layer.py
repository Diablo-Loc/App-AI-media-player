import re
import textwrap
from bisect import bisect_right
from PySide6.QtWidgets import QLabel, QSizePolicy
from PySide6.QtCore import Qt, QPoint,QRect 
from PySide6.QtGui import QColor, QPainter
from subtitle.mode import SubtitleMode 

class DraggableSubtitle(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # --- Cấu hình cơ bản của Label ---
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        #self.setWordWrap(True)
        self.setWordWrap(False)
        # Policy giúp label co giãn tốt theo nội dung
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        # --- QUAN TRỌNG: Cho phép chuột tương tác để kéo ---
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False) 
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # Biến lưu trạng thái
        self._drag_offset = QPoint() 
        self._user_moved = False 
        self.is_locked = False
        self._anchor_rect_global = None

        self._rel_x_offset = 0        # Khoảng cách từ TÂM sub đến TÂM video
        self._rel_y_from_bottom = 0   # Khoảng cách từ ĐÁY sub đến ĐÁY video
        
        # --- STYLE DEFAULT (Lưu giá trị mặc định) ---
        self.current_font_size = 24
        self.current_color = "#FFFF00"
        self.current_bg_color = "#000000"  # Mặc định nền đen
        self.current_bg_opacity = 0.5      # Mặc định mờ 50%
        self._current_margin = 40
        
        self.use_outline = True
        self.outline_width = 4
        self.outline_color = "#000000"
        self.use_shadow = True
        self.shadow_alpha = 160
               
        # Áp dụng style lần đầu
        self.update_style() 
    
    # --- LOGIC KHÓA / MỞ KHÓA ---
    def set_locked(self, locked: bool):
        self.is_locked = locked
        if locked:
            # KHI KHÓA: Chỉ tắt chuột, vị trí giữ nguyên (đã được lưu trong mouseMove)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            # KHI MỞ KHÓA: Reset trạng thái user_moved về False
            # Để nó tự động nhảy về vị trí gốc (Auto Center + Auto Margin)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            
            self._user_moved = False # [QUAN TRỌNG] Đánh dấu là chưa kéo để reset
            self.recalc_position()   # Ép nhảy về vị trí gốc ngay lập tức
        
        self.update_style()

    def _anchor_geometry(self):
        """
        Anchor geometry (GLOBAL):
        - Nếu có anchor rect được set từ ngoài → dùng rect đó
        - Nếu không → bám theo WINDOW CHA (KHÔNG PHẢI self)
        """
        if self._anchor_rect_global is not None:
            return self._anchor_rect_global

        win = self.parent()
        if win:
            return win.frameGeometry()

        return None

    def reset_anchor_state(self):
        self._anchor_rect = None
        self._cached_render_rect = None
        self._last_parent_size = None
        self._last_mode = None


    def set_anchor_rect(self, rect_global: QRect | None):
        """
        rect_global: QRect theo GLOBAL COORD
        None → reset về window
        """
        self._anchor_rect_global = rect_global
        self.recalc_position()


    def recalc_position(self):
        if not self.parent():
            return

        self.adjustSize()
        anchor = self._anchor_geometry()
        if not anchor:
            return

        if self._user_moved:
            parent_center_x = anchor.x() + anchor.width() // 2
            target_x = parent_center_x + self._rel_x_offset - self.width() // 2

            target_y = (
                anchor.y() + anchor.height()
                - self._rel_y_from_bottom
                - self.height()
            )
        else:
            target_x = anchor.x() + (anchor.width() - self.width()) // 2
            target_y = (
                anchor.y() + anchor.height()
                - self.height()
                - self._current_margin
            )

        self.move(int(target_x), int(target_y))
        """
        print(
    "ANCHOR:",
    "video" if self.parent() is not self.parent().window() else "window",
    self._anchor_geometry()
)
        """

        
    def update_style(self):
        """Cập nhật giao diện (Nền, Font size) - Logic cũ giữ nguyên"""
        
        # --- XỬ LÝ MÀU NỀN + ĐỘ MỜ (Logic cũ) ---
        c = QColor(self.current_bg_color)
        if not c.isValid(): c = QColor("#000000")
        alpha = int(self.current_bg_opacity * 255)
        rgba_bg = f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

        # --- CẬP NHẬT STYLESHEET ---
        self.setStyleSheet(f"""
            QLabel {{
                /* color: transparent; */ /* Để paintEvent tự vẽ màu chữ giúp viền đẹp hơn */
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: {self.current_font_size}px;
                font-weight: bold;
                background-color: {rgba_bg};
                padding: 6px 12px;
                border-radius: 6px;
            }}
        """)
        
        # Logic co giãn và vị trí cũ
        self.adjustSize()
        if not self._user_moved:
            self.center_at_bottom()
    
    def set_font_size(self, size):
        self.current_font_size = size
        self.update_style()

    def set_text_color(self, color_hex):
        self.current_color = color_hex
        self.update_style()

    # --- KHẮC PHỤC LỖI NỀN KHÔNG HIỂN THỊ ---
    def paintEvent(self, event):
        from PySide6.QtGui import QPainterPath, QPen, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        # Vẽ nền cũ
        from PySide6.QtWidgets import QStyleOption, QStyle
        opt = QStyleOption(); opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

        if not self.text(): return

        path = QPainterPath()
        metrics = self.fontMetrics()
        rect = self.contentsRect()
        lines = self.text().split('\n')
        line_height = metrics.lineSpacing()
        total_h = line_height * len(lines)
        
        for i, line in enumerate(lines):
            x = rect.x() + (rect.width() - metrics.horizontalAdvance(line)) / 2
            y = rect.y() + (rect.height() - total_h) / 2 + metrics.ascent() + (i * line_height)
            path.addText(x, y, self.font(), line)

        # 1. Vẽ Bóng (Shadow)
        if getattr(self, 'use_shadow', True):
            alpha = getattr(self, 'shadow_alpha', 160)
            painter.fillPath(path.translated(2,2), QColor(0, 0, 0, alpha))

        # 2. Vẽ Viền (Outline)
        if getattr(self, 'use_outline', True):
            w = getattr(self, 'outline_width', 4)
            c = getattr(self, 'outline_color', "#000000")
            pen = QPen(QColor(c), w)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)

        # 3. Vẽ chữ chính
        painter.fillPath(path, QColor(self.current_color))
        painter.end()
        
    # --- Các hàm logic vị trí giữ nguyên ---
    def center_at_bottom(self):
        anchor = self._anchor_geometry()
        if not anchor:
            return

        self.adjustSize()
        x = anchor.x() + (anchor.width() - self.width()) // 2
        y = anchor.y() + anchor.height() - self.height() - self._current_margin
        self.move(x, y)

    def _ensure_within_bounds_global(self):
        if self.parent() and self.parent().isVisible():
            p_geom = self.parent().geometry()
            curr_pos = self.pos()
            
            min_x = p_geom.x()
            max_x = p_geom.x() + p_geom.width() - self.width()
            min_y = p_geom.y()
            
            # SỬ DỤNG BIẾN ĐỘNG self._current_margin
            max_y = p_geom.y() + p_geom.height() - self.height() - self._current_margin

            x = max(min_x, min(curr_pos.x(), max_x))
            y = max(min_y, min(curr_pos.y(), max_y))
            
            self.move(x, y)

    # --- SỰ KIỆN KÉO THẢ ---
    def mousePressEvent(self, event):
        if self.is_locked: return
        if event.button() == Qt.MouseButton.LeftButton:
            # Lưu vị trí tương đối của chuột so với widget
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_locked:
            return

        if event.buttons() == Qt.MouseButton.LeftButton and self.parent():
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)

            anchor = self._anchor_geometry()
            if not anchor:
                return

            sub_geom = self.geometry()

            # Lệch tâm X
            self._rel_x_offset = (
                sub_geom.center().x()
                - (anchor.x() + anchor.width() // 2)
            )

            # Lệch đáy Y
            self._rel_y_from_bottom = (
                (anchor.y() + anchor.height())
                - (sub_geom.y() + sub_geom.height())
            )

            self._user_moved = True
            event.accept()

    def mouseReleaseEvent(self, event):
        if not self.is_locked and event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def reset_to_default(self):
        """Reset dứt khoát và ép hiển thị lên lớp trên cùng"""
        self._user_moved = False
        self._rel_x_offset = 0
        self._rel_y_from_bottom = 0
        
        if hasattr(self, '_custom_rect'):
            self._custom_rect = None

        # Ép buộc hiển thị và nổi lên trên
        self.setVisible(True)
        self.raise_() 
        
        # Tính lại vị trí
        self.recalc_position()
        
        # Debug nhanh (Bác bật cái này lên xem nó in ra tọa độ bao nhiêu)
        # print(f"DEBUG SUB: Pos={self.pos()}, Parent={self.parent()}")

class SubtitleLayer(DraggableSubtitle):
    # Thêm tham số initial_mode để đồng bộ ngay khi khởi tạo
    def __init__(self, initial_mode=SubtitleMode.EN_VI, parent=None):
        super().__init__(parent)
        self.enable_render = True
        self.subtitles = [] 
        self._start_times = []
        self.mode = initial_mode
        self._current_ms_cache = 0
        
        # --- CẤU HÌNH CỬA SỔ QUAN TRỌNG ĐỂ NỔI LÊN TRÊN ---
        """  self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |  # Luôn nổi trên cùng
            Qt.WindowType.Tool 
        )
        """
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Tool 
        )
        # Đặt tên object để dễ debug CSS nếu cần
        self.setObjectName("SubtitleLayer")
        self.hide() 

    def load_subtitles(self, segments): 
        self.subtitles = []
        for seg in segments:
            self.subtitles.append({
                'start': seg.get('start', 0),
                'end': seg.get('end', 0),
                'jp': self.clean_ass_tags(seg.get('jp', '')),
                'en': self.clean_ass_tags(seg.get('en', '')),
                'vi': self.clean_ass_tags(seg.get('vi', ''))
            })
        
        self.subtitles.sort(key=lambda x: x['start'])
        self._start_times = [s['start'] for s in self.subtitles]
        print(f"✨ UI Layer: Đã sẵn sàng hiển thị {len(self.subtitles)} câu sub.")

    def clean_ass_tags(self, text):
        if not text: return ""
        # Xóa các thẻ định dạng {}
        clean_text = re.sub(r'\{.*?\}', '', text)
        
        # 🔴 SỬA Ở ĐÂY:
        # Thay thế '\N' và '\n' thành dấu cách ' ' (thay vì '\n')
        clean_text = clean_text.replace(r'\N', ' ').replace(r'\n', ' ')
        
        # (Tùy chọn) Xóa khoảng trắng thừa nếu có 2 dấu cách dính nhau
        clean_text = re.sub(r'\s+', ' ', clean_text)
        
        return clean_text.strip()

    def set_mode(self, mode):
        """Hàm nhận Enum SubtitleMode từ SettingsPanel"""
        self.mode = mode
        self.update_position(self._current_ms_cache)

    def build_text(self, sub_dict):
        if self.mode == SubtitleMode.OFF: 
            return ""

        lines = []
        m = self.mode

        # ==========================================================
        # 🟢 CẤU HÌNH BẢO HIỂM ĐỘ DÀI
        # ==========================================================
        # Ngưỡng an toàn: Nếu dài hơn số này thì mới cắt.
        # Câu mẫu của bác dài khoảng 65 ký tự. 
        # Em để 70 là đẹp (dài hơn câu mẫu xíu mới cắt).
        SAFE_LIMIT = 70

        def smart_wrap(text):
            if not text: return ""
            length = len(text)
            
            # TRƯỜNG HỢP 1: Câu ngắn -> Giữ nguyên 1 dòng thẳng tắp
            if length <= SAFE_LIMIT:
                return text
            
            # TRƯỜNG HỢP 2: Câu dài -> Tính toán chia đôi
            # Công thức: (Tổng độ dài / 2) + khoảng dư an toàn (để không cắt quá sát)
            balanced_width = int(length / 2) + 6
            
            # Đảm bảo chiều rộng tối thiểu là 40 (để tránh bị bóp quá hẹp)
            final_width = max(40, balanced_width)
            
            # Xử lý cắt dòng
            # break_long_words=False: Không cắt giữa chừng từ đơn
            # break_on_hyphens=False: [QUAN TRỌNG] Không cắt từ nối (anti-gravity sẽ đi cùng nhau)
            return textwrap.fill(text, width=final_width, break_long_words=False, break_on_hyphens=False)

        # 1. Tiếng Nhật (Thường không cần cắt vì chữ Kanji gọn)
        if m in (SubtitleMode.JP, SubtitleMode.JP_VI, SubtitleMode.JP_EN, SubtitleMode.JP_EN_VI):
            if sub_dict.get('jp'): lines.append(sub_dict['jp'])

        # 2. Tiếng Anh
        if m in (SubtitleMode.EN, SubtitleMode.EN_VI, SubtitleMode.JP_EN, SubtitleMode.JP_EN_VI):
            raw_en = sub_dict.get('en', '')
            if raw_en:
                lines.append(smart_wrap(raw_en))

        # 3. Tiếng Việt
        if m in (SubtitleMode.VI, SubtitleMode.JP_VI, SubtitleMode.EN_VI, SubtitleMode.JP_EN_VI):
            raw_vi = sub_dict.get('vi', '')
            if raw_vi:
                lines.append(smart_wrap(raw_vi))

        return "\n".join(lines)

    def update_position(self, pts_ms: int):
        """
        PTS-DRIVEN subtitle update
        pts_ms: thời gian PTS của video (ms)
        """

        # ===============================
        # 0. Cache PTS (cho resize / redraw)
        # ===============================
        self._current_ms_cache = pts_ms

        # ===============================
        # 1. Điều kiện không render
        # ===============================
        if not self.enable_render or self.mode == SubtitleMode.OFF:
            if self.isVisible():
                self.hide()
            return

        if not self.subtitles:
            if self.isVisible():
                self.hide()
            return

        # ===============================
        # 2. Tìm subtitle active theo PTS (O(log n))
        # ===============================
        idx = bisect_right(self._start_times, pts_ms) - 1
        active_sub = None

        if idx >= 0:
            sub = self.subtitles[idx]
            if sub['start'] <= pts_ms <= sub['end']:
                active_sub = sub

        # ===============================
        # 3. Không có sub → ẩn
        # ===============================
        if not active_sub:
            if self.isVisible():
                self.hide()
            return

        # ===============================
        # 4. Build text theo mode
        # ===============================
        new_text = self.build_text(active_sub).strip()

        if not new_text:
            if self.isVisible():
                self.hide()
            return

        # ===============================
        # 5. Text KHÔNG đổi → KHÔNG làm gì
        # ===============================
        if (
            self.isVisible()
            and self.text() == new_text
        ):
            return

        # ===============================
        # 6. Text đổi → update 1 lần DUY NHẤT
        # ===============================
        self.setText(new_text)
        self.adjustSize()

        # Tính vị trí (tôn trọng user kéo / lock)
        self.recalc_position()

        # ===============================
        # 7. Show an toàn (KHÔNG raise liên tục)
        # ===============================
        if not self.isVisible():
            self.show()


    def update_after_resize(self):
        """Khi window resize"""
        if self.isHidden() and self._current_ms_cache == 0: return
        # [GỌI HÀM CHUẨN HÓA] -> Nó sẽ tự check _user_moved để giữ vị trí hoặc reset
        self.recalc_position()

    def apply_style(self, font_size=None, color=None, bg_color=None, bg_opacity=None, **kwargs):
        """Nhận style từ Editor và áp dụng xuống DraggableSubtitle"""
        changed = False
        
        # --- PHẦN THÊM MỚI: Tùy chỉnh Viền & Bóng (Không đổi logic cũ) ---
        if 'outline_enabled' in kwargs: 
            self.use_outline = kwargs['outline_enabled']
            changed = True
        if 'outline_width' in kwargs: 
            self.outline_width = kwargs['outline_width']
            changed = True
        if 'outline_color' in kwargs: 
            self.outline_color = kwargs['outline_color']
            changed = True
        if 'shadow_enabled' in kwargs: 
            self.use_shadow = kwargs['shadow_enabled']
            changed = True
        if 'shadow_alpha' in kwargs: 
            self.shadow_alpha = kwargs['shadow_alpha']
            changed = True
        
        # --- LOGIC CŨ: Giữ nguyên hoàn toàn ---
        if font_size is not None:
            self.current_font_size = font_size
            changed = True
            
        if color is not None:
            self.current_color = color
            changed = True
            
        if bg_color is not None:
            self.current_bg_color = bg_color
            changed = True
            
        if bg_opacity is not None:
            self.current_bg_opacity = bg_opacity
            changed = True
            
        # Nếu có bất kỳ thay đổi nào (cũ hoặc mới)
        if changed:
            self.update_style()
            # Gọi self.update() để ép paintEvent vẽ lại Viền/Bóng ngay lập tức
            self.update() 

            if self.isVisible():
                self.recalc_position()
                
    def set_bottom_margin(self, margin):
        """Khi thanh Playback ẩn/hiện"""
        if self._current_margin != margin:
            self._current_margin = margin
            
            # Nếu đang khóa hoặc người dùng đã kéo đi chỗ khác -> KHÔNG NHẢY (giữ nguyên vị trí)
            # Nếu đang ở chế độ mặc định -> NHẢY (cập nhật theo margin mới)
            if self.isVisible():
                self.recalc_position()