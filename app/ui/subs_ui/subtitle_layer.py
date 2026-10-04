import re
import textwrap
from bisect import bisect_right
from PySide6.QtWidgets import QLabel, QSizePolicy, QStyleOption, QStyle
from PySide6.QtCore import Qt, QPoint, QRect, QPropertyAnimation, QEasingCurve, QAbstractAnimation, Property
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from subtitle.mode import SubtitleMode 
from ui.subtitle_presentation import SubtitlePresentationGuard

class DraggableSubtitle(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # --- Cấu hình cơ bản ---
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False) 
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # CHỐNG CHỚP NHÁY (Anti-flicker attributes)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        # Biến trạng thái kéo thả & vị trí
        self._drag_offset = QPoint() 
        self._user_moved = False 
        self.is_locked = False
        self._anchor_rect_global = None

        self._rel_x_offset = 0        
        self._rel_y_from_bottom = 0   
        
        # --- Style Default ---
        self.current_font_size = 24
        self.current_color = "#FFFF00"
        self.current_bg_color = "#000000"
        self.current_bg_opacity = 0.5
        self._current_margin = 40
        
        self.use_outline = True
        self.outline_width = 4
        self.outline_color = "#000000"
        self.use_shadow = True
        self.shadow_alpha = 160
        
        # Custom Opacity (Tránh dùng QGraphicsOpacityEffect gây chớp frame)
        self._opacity = 1.0
        
        # Cache Path vẽ chữ để tối ưu FPS
        self._cached_path = None
        self._cached_text = ""
        self._cached_size = None
                
        self.update_style() 

    # --- Property Opacity cho QPropertyAnimation ---
    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, val: float):
        self._opacity = max(0.0, min(1.0, val))
        self.update() # Trigger paintEvent vẽ lại với Opacity mới

    opacity = Property(float, get_opacity, set_opacity)
    
    def set_locked(self, locked: bool):
        self.is_locked = locked
        if locked:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._user_moved = False 
            self.recalc_position()
        
        self.update_style()

    def _anchor_geometry(self):
        if self._anchor_rect_global is not None:
            return self._anchor_rect_global
        win = self.parent()
        if win:
            return win.frameGeometry()
        return None

    def reset_anchor_state(self):
        self._anchor_rect_global = None

    def set_anchor_rect(self, rect_global: QRect | None):
        self._anchor_rect_global = rect_global
        self.recalc_position()

    def recalc_position(self):
        if not self.parent():
            return

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

        new_x, new_y = int(target_x), int(target_y)
        if self.x() != new_x or self.y() != new_y:
            self.move(new_x, new_y)
        
    def update_style(self):
        c = QColor(self.current_bg_color)
        if not c.isValid(): 
            c = QColor("#000000")
        alpha = int(self.current_bg_opacity * 255)
        rgba_bg = f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"

        self.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: {self.current_font_size}px;
                font-weight: bold;
                background-color: {rgba_bg};
                padding: 6px 12px;
                border-radius: 6px;
            }}
        """)
        self._cached_text = "" # Invalidate Cache
        self.adjustSize()
        if not self._user_moved:
            self.center_at_bottom()

    def paintEvent(self, event):
        if not self.text() or self._opacity <= 0.0: 
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        # Áp dụng Opacity trực tiếp vào QPainter (Khắc phục chớp nháy tuyệt đối)
        painter.setOpacity(self._opacity)
        
        # 1. Vẽ Nền Widget
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

        # 2. Re-use Path cache
        curr_text = self.text()
        if self._cached_text != curr_text or self._cached_size != self.size():
            path = QPainterPath()
            metrics = self.fontMetrics()
            rect = self.contentsRect()
            lines = curr_text.split('\n')
            line_height = metrics.lineSpacing()
            total_h = line_height * len(lines)
            
            for i, line in enumerate(lines):
                x = rect.x() + (rect.width() - metrics.horizontalAdvance(line)) / 2
                y = rect.y() + (rect.height() - total_h) / 2 + metrics.ascent() + (i * line_height)
                path.addText(x, y, self.font(), line)
            
            self._cached_path = path
            self._cached_text = curr_text
            self._cached_size = self.size()
        else:
            path = self._cached_path

        # 3. Vẽ Bóng (Shadow)
        if getattr(self, 'use_shadow', True):
            alpha = getattr(self, 'shadow_alpha', 160)
            painter.fillPath(path.translated(2, 2), QColor(0, 0, 0, alpha))

        # 4. Vẽ Viền (Outline)
        if getattr(self, 'use_outline', True):
            w = getattr(self, 'outline_width', 4)
            c = getattr(self, 'outline_color', "#000000")
            pen = QPen(QColor(c), w)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)

        # 5. Vẽ Chữ chính
        painter.fillPath(path, QColor(self.current_color))
        painter.end()
        
    def center_at_bottom(self):
        anchor = self._anchor_geometry()
        if not anchor:
            return

        self.adjustSize()
        x = anchor.x() + (anchor.width() - self.width()) // 2
        y = anchor.y() + anchor.height() - self.height() - self._current_margin
        if self.x() != x or self.y() != y:
            self.move(x, y)

    # --- SỰ KIỆN KÉO THẢ ---
    def mousePressEvent(self, event):
        if self.is_locked: 
            return
        if event.button() == Qt.MouseButton.LeftButton:
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
            self._rel_x_offset = sub_geom.center().x() - (anchor.x() + anchor.width() // 2)
            self._rel_y_from_bottom = (anchor.y() + anchor.height()) - (sub_geom.y() + sub_geom.height())

            self._user_moved = True
            event.accept()

    def mouseReleaseEvent(self, event):
        if not self.is_locked and event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def reset_to_default(self):
        self._user_moved = False
        self._rel_x_offset = 0
        self._rel_y_from_bottom = 0
        self.setVisible(True)
        self.raise_() 
        self.recalc_position()


class SubtitleLayer(DraggableSubtitle):
    def __init__(self, initial_mode=SubtitleMode.EN_VI, parent=None):
        super().__init__(parent)
        self.enable_render = True
        self.subtitles = [] 
        self._start_times = []
        self.mode = initial_mode
        self._current_ms_cache = -1
        
        # --- CẤU HÌNH CÔNG TẮC FADE IN / OUT ---
        self.use_fade_effect = True
        
        # Anim tác động trực tiếp vào property 'opacity' đã tạo ở trên
        self.fade_anim = QPropertyAnimation(self, b"opacity")
        self.fade_anim.setDuration(220) 
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_anim.finished.connect(self._finish_fade)
        self._presentation_guard = (
            SubtitlePresentationGuard(parent, self)
            if parent is not None and hasattr(parent, 'video_display') else None
        )

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Tool 
        )
        self.set_opacity(1.0)
        self.setObjectName("SubtitleLayer")
        self.hide() 

    def show(self):
        self.setVisible(True)

    def setVisible(self, visible):
        guard = getattr(self, '_presentation_guard', None)
        if visible and guard is not None and not guard.allows():
            self.fade_anim.stop()
            self.set_opacity(0.0)
            visible = False
        super().setVisible(visible)

    def _finish_fade(self):
        if self.fade_anim.endValue() == 0.0 and self._opacity <= 0.0:
            self.hide()

    def set_fade_enabled(self, enabled: bool):
        """Hàm công khai để giao diện Setting gọi bật/tắt Fade"""
        self.use_fade_effect = bool(enabled)
        if not self.use_fade_effect:
            self.fade_anim.stop()
            self.set_opacity(1.0)

    def load_subtitles(self, segments): 
        self.subtitles = []
        for seg in segments:
            orig_text = seg.get('orig', '') or seg.get('jp', '') or seg.get('text', '')
            
            self.subtitles.append({
                'start': seg.get('start', 0),
                'end': seg.get('end', 0),
                'orig': self.clean_ass_tags(orig_text),
                'en': self.clean_ass_tags(seg.get('en', '')),
                'vi': self.clean_ass_tags(seg.get('vi', ''))
            })
        
        self.subtitles.sort(key=lambda x: x['start'])
        self._start_times = [s['start'] for s in self.subtitles]

    def clean_ass_tags(self, text):
        if not text: 
            return ""
        clean_text = re.sub(r'\{.*?\}', '', text)
        clean_text = clean_text.replace(r'\N', ' ').replace(r'\n', ' ')
        clean_text = re.sub(r'\s+', ' ', clean_text)
        return clean_text.strip()

    def set_mode(self, mode):
        self.mode = mode
        self._current_ms_cache = -1 # Ép refresh
        self.update_position(self._current_ms_cache)

    def build_text(self, sub_dict):
        if self.mode == SubtitleMode.OFF: 
            return ""

        lines = []
        m = self.mode
        SAFE_LIMIT = 70

        def smart_wrap(text):
            if not text: 
                return ""
            length = len(text)
            if length <= SAFE_LIMIT:
                return text
            
            balanced_width = int(length / 2) + 6
            final_width = max(40, balanced_width)
            return textwrap.fill(text, width=final_width, break_long_words=False, break_on_hyphens=False)

        raw_orig = sub_dict.get('orig', '').strip()
        raw_en = sub_dict.get('en', '').strip()
        raw_vi = sub_dict.get('vi', '').strip()

        effective_en = raw_en if raw_en else raw_orig

        # 1. Lời Gốc
        if m in (SubtitleMode.JP, SubtitleMode.JP_VI, SubtitleMode.JP_EN, SubtitleMode.JP_EN_VI):
            if raw_orig: 
                lines.append(smart_wrap(raw_orig))

        # 2. Tiếng Anh
        if m in (SubtitleMode.EN, SubtitleMode.EN_VI, SubtitleMode.JP_EN, SubtitleMode.JP_EN_VI):
            if effective_en:
                already_printed_orig = (m in (SubtitleMode.JP, SubtitleMode.JP_VI, SubtitleMode.JP_EN, SubtitleMode.JP_EN_VI)) and bool(raw_orig)
                is_same_as_orig = (effective_en.lower() == raw_orig.lower())
                
                if not (already_printed_orig and is_same_as_orig):
                    lines.append(smart_wrap(effective_en))

        # 3. Tiếng Việt
        if m in (SubtitleMode.VI, SubtitleMode.JP_VI, SubtitleMode.EN_VI, SubtitleMode.JP_EN_VI):
            if raw_vi:
                lines.append(smart_wrap(raw_vi))

        return "\n".join(lines)

    def update_position(self, pts_ms: int):
        self._current_ms_cache = pts_ms

        guard = self._presentation_guard
        if (not self.enable_render or self.mode == SubtitleMode.OFF or not self.subtitles
                or (guard is not None and not guard.context_allows())):
            self._smart_hide(instant=True)
            return

        # Tìm câu sub active bằng Nhị Phân
        idx = bisect_right(self._start_times, pts_ms) - 1
        active_sub = None

        if idx >= 0:
            sub = self.subtitles[idx]
            if sub['start'] <= pts_ms <= sub['end']:
                active_sub = sub

        # Trường hợp không có sub
        if not active_sub:
            self._smart_hide(instant=False)
            return

        new_text = self.build_text(active_sub).strip()

        if not new_text:
            self._smart_hide(instant=False)
            return

        # Nếu chữ giống hệt đang hiển thị -> Giữ nguyên
        if not self.isHidden() and self.text() == new_text:
            if (self.fade_anim.state() == QAbstractAnimation.State.Running
                    and self.fade_anim.endValue() == 0.0):
                self._smart_show(instant=False)
            return

        prev_sub_end = self.subtitles[idx - 1]['end'] if idx > 0 else 0
        gap_from_prev = active_sub['start'] - prev_sub_end

        # Cập nhật chữ mới + Vị trí chuẩn TRƯỚC KHI hiển thị
        self.setText(new_text)
        self.adjustSize()
        self.recalc_position()
        if guard is not None:
            guard.prepare_geometry()

        if self.isHidden():
            if gap_from_prev > 400 or idx == 0:
                self._smart_show(instant=False)
            else:
                self._smart_show(instant=True)
        else:
            self.fade_anim.stop()
            self.set_opacity(1.0)

    def _smart_show(self, instant=False):
        """Hiển thị sub chuẩn mượt không chớp nháy"""
        if (self.use_fade_effect and not instant
                and self.fade_anim.state() == QAbstractAnimation.State.Running
                and self.fade_anim.endValue() == 1.0):
            return
        self.fade_anim.stop()

        if not self.use_fade_effect or instant:
            self.set_opacity(1.0)
            self.show()
            return

        # Đặt Opacity từ giá trị hiện tại (hoặc 0.0) TRƯỚC KHI show()
        start_op = self._opacity if not self.isHidden() else 0.0
        self.set_opacity(start_op)
        self.show()
        
        self.fade_anim.setStartValue(start_op)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

    def _smart_hide(self, instant=False):
        """Ẩn sub an toàn"""
        if self.isHidden():
            if instant:
                self.fade_anim.stop()
                self.set_opacity(0.0)
            return

        if not self.use_fade_effect or instant:
            self.fade_anim.stop()
            self.set_opacity(0.0)
            self.hide()
            return

        if self.fade_anim.state() == QAbstractAnimation.State.Running and self.fade_anim.endValue() == 0.0:
            return

        self.fade_anim.stop()
        self.fade_anim.setStartValue(self._opacity)
        self.fade_anim.setEndValue(0.0)
        
        self.fade_anim.start()

    def update_after_resize(self):
        if self.isHidden(): 
            return
        self.recalc_position()

    def apply_style(self, font_size=None, color=None, bg_color=None, bg_opacity=None, **kwargs):
        changed = False
        
        if 'fade_enabled' in kwargs:
            self.set_fade_enabled(kwargs['fade_enabled'])

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
            
        if changed:
            self.update_style()
            self.update() 
            if not self.isHidden():
                self.recalc_position()
                
    def set_bottom_margin(self, margin):
        if self._current_margin != margin:
            self._current_margin = margin
            if not self.isHidden():
                self.recalc_position()
