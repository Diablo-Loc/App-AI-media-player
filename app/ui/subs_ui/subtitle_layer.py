import re
import textwrap
from bisect import bisect_right
from PySide6.QtWidgets import QLabel, QSizePolicy
from PySide6.QtCore import (
    Qt,
    QPoint,
    QRect,
    QSize,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QAbstractAnimation,
    Property,
)
from PySide6.QtGui import QFont, QPainter
from subtitle.mode import SubtitleMode
from ui.subtitle_presentation import SubtitlePresentationGuard
from ui.subtitle_effects import SubtitleEffects
from ui.subtitle_kinetic import CHOREO_EXIT_MODES
from ui.subtitle_studio import (
    SubtitleRenderCache,
    build_typography_plan,
    draw_cinema_pill,
    draw_studio_text_layers,
    measure_box_size,
    rasterize_studio_sprite,
)


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
        self.bilingual_hierarchy = False

        # Custom Opacity (Tránh dùng QGraphicsOpacityEffect gây chớp frame)
        self._opacity = 1.0

        # Cache Path & Render Sprite để tối ưu 60 FPS
        self._cached_path = None
        self._cached_plan = None
        self._cached_text = ""
        self._cached_size = None
        self._cached_row_groups = ()
        self._render_cache = SubtitleRenderCache()
        self._song_stage_size: QSize | None = None
        self.sweep_row_groups = ()

        self.update_style()

    # --- Property Opacity cho QPropertyAnimation ---
    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, val: float):
        self._opacity = max(0.0, min(1.0, val))
        self.update()

    opacity = Property(float, get_opacity, set_opacity)

    def _effective_padding(self) -> tuple[int, int]:
        # Generous horizontal room for saber/glitch/shatter VFX; compact 6px bottom keeps sub grounded low.
        return (36, 6)

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
            if self.isWindow():
                tl = win.mapToGlobal(QPoint(0, 0))
                return QRect(tl.x(), tl.y(), win.width(), win.height())
            return win.rect()
        return None

    def reset_anchor_state(self):
        self._anchor_rect_global = None

    def set_anchor_rect(self, rect_global: QRect | None):
        self._anchor_rect_global = rect_global
        self.recalc_position()

    def _ensure_within_bounds_global(self):
        anchor = self._anchor_geometry()
        if not anchor:
            return
        min_x = anchor.x()
        max_x = max(min_x, anchor.x() + anchor.width() - self.width())
        min_y = anchor.y()
        max_y = max(min_y, anchor.y() + anchor.height() - self.height())
        clamped_x = max(min_x, min(self.x(), max_x))
        clamped_y = max(min_y, min(self.y(), max_y))
        if self.x() != clamped_x or self.y() != clamped_y:
            self.move(int(clamped_x), int(clamped_y))

    def _target_position(self, width: int, height: int) -> tuple[int, int] | None:
        if not self.parent() and self._anchor_rect_global is None:
            return None
        anchor = self._anchor_geometry()
        if not anchor:
            return None
        if self._user_moved:
            parent_center_x = anchor.x() + anchor.width() // 2
            target_x = parent_center_x + self._rel_x_offset - width // 2
            target_y = (
                anchor.y() + anchor.height()
                - self._rel_y_from_bottom
                - height
            )
        else:
            target_x = anchor.x() + (anchor.width() - width) // 2
            target_y = (
                anchor.y() + anchor.height()
                - height
                - self._current_margin
            )
        return int(target_x), int(target_y)

    def recalc_position(self):
        pos = self._target_position(self.width(), self.height())
        if pos is None:
            return
        if self.x() != pos[0] or self.y() != pos[1]:
            self.move(pos[0], pos[1])

    def sizeHint(self) -> QSize:
        txt = self.text()
        if not txt:
            return super().sizeHint()
        pad_x, pad_y = self._effective_padding()
        row_groups = tuple(getattr(self, 'sweep_row_groups', ()) or ())
        w, h = measure_box_size(
            txt,
            self.font(),
            row_groups,
            False,
            pad_left=pad_x,
            pad_right=pad_x,
            pad_top=pad_y,
            pad_bottom=pad_y,
        )
        return QSize(w, h)

    def update_style(self):
        pad_x, pad_y = self._effective_padding()
        f = QFont(self.font())
        f.setFamilies(['Segoe UI', 'Yu Gothic UI', 'Meiryo', 'Arial'])
        f.setPixelSize(int(self.current_font_size))
        f.setWeight(QFont.Weight.Bold)
        self.setFont(f)
        self.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', 'Yu Gothic UI', 'Meiryo', 'Arial', sans-serif;
                font-size: {self.current_font_size}px;
                font-weight: 700;
                background-color: transparent;
                padding: {pad_y}px {pad_x}px;
                border-radius: 10px;
            }}
        """)
        self._cached_text = ""  # Invalidate Cache
        self._cached_plan = None
        self._render_cache.clear()
        if getattr(self, '_song_stage_size', None) is None:
            self.adjustSize()
        if not self._user_moved:
            self.center_at_bottom()

    def _plan_for(self, curr_text: str, rect: QRect, size: QSize, row_groups: tuple[int, ...]):
        bottom_align = getattr(self, '_song_stage_size', None) is not None
        plan_key = (
            curr_text,
            row_groups,
            self.font().key(),
            size.width(),
            size.height(),
            rect.getRect(),
            bottom_align,
        )
        plan = self._render_cache.get_plan(plan_key)
        if plan is None:
            plan = build_typography_plan(curr_text, self.font(), rect, row_groups, False, bottom_align=bottom_align)
            self._render_cache.put_plan(plan_key, plan)
        return plan, plan_key

    def paintEvent(self, event):
        if not self.text() or self._opacity <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        painter.setOpacity(self._opacity)

        # Gentle vertical exit glide only for classic fade-out (skip during choreo VFX exits so portals stay centered).
        effects_ref = getattr(self, '_subtitle_effects', None)
        choreo_exiting = bool(
            effects_ref is not None
            and effects_ref.options.get('enabled')
            and effects_ref.options.get('entrance') in CHOREO_EXIT_MODES
        )
        if (
            not choreo_exiting
            and self._opacity < 1.0
            and getattr(self, 'use_fade_effect', False)
            and hasattr(self, 'fade_anim')
            and self.fade_anim.endValue() == 0.0
        ):
            painter.translate(0.0, -5.0 * (1.0 - self._opacity))

        # 1. Re-use Path & TypographyPlan cache (Pre-warmed hit < 0.2ms)
        curr_text = self.text()
        row_groups = tuple(getattr(self, 'sweep_row_groups', ()) or ())
        size = self.size()
        if (
            self._cached_plan is None
            or self._cached_text != curr_text
            or self._cached_size != size
            or self._cached_row_groups != row_groups
        ):
            plan, _ = self._plan_for(curr_text, self.contentsRect(), size, row_groups)
            self._cached_plan = plan
            self._cached_path = plan.full_path
            self._cached_text = curr_text
            self._cached_size = size
            self._cached_row_groups = row_groups
        else:
            plan = self._cached_plan

        # 2. Nền kính mờ bo tròn gọn theo vùng chữ (không phình theo stage cố định)
        if self.current_bg_opacity > 0.0:
            if getattr(self, '_song_stage_size', None) is not None and plan.lines and not plan.full_bounds.isNull() and self._cached_text == curr_text:
                pill_rect = plan.full_bounds.adjusted(-20.0, -8.0, 20.0, 8.0).intersected(self.rect())
            else:
                pill_rect = self.rect()
            draw_cinema_pill(painter, pill_rect, self.current_bg_color, self.current_bg_opacity)

        path = plan.full_path

        effects = getattr(self, '_subtitle_effects', None)
        if effects is not None and effects.paint(painter, path):
            painter.end()
            return

        # 3. Studio static rendering (khi effects đang Tắt) - đồng nhất cỡ chữ & bóng quang học
        dpr = max(1.0, float(self.devicePixelRatioF()))
        sprite_key = (
            'static',
            curr_text,
            row_groups,
            self.font().key(),
            size.width(),
            size.height(),
            self.current_color,
            self.use_shadow,
            self.shadow_alpha,
            self.use_outline,
            self.outline_width,
            self.outline_color,
            round(dpr, 3),
        )
        entry = self._render_cache.get_sprite(sprite_key)
        if entry is None:
            sprite, origin = rasterize_studio_sprite(
                plan,
                dpr=dpr,
                font_color=self.current_color,
                color_mode='original',
                use_shadow=self.use_shadow,
                shadow_alpha=self.shadow_alpha,
                use_outline=self.use_outline,
                outline_width=self.outline_width,
                outline_color=self.outline_color,
                glow=False,
                studio_mode=True,
            )
            if sprite is not None:
                self._render_cache.put_sprite(sprite_key, sprite, origin)
                entry = (sprite, origin)
        if entry is not None:
            painter.drawImage(entry[1], entry[0])
        else:
            draw_studio_text_layers(
                painter,
                plan,
                font_color=self.current_color,
                color_mode='original',
                progress=1.0,
                use_shadow=self.use_shadow,
                shadow_alpha=self.shadow_alpha,
                use_outline=self.use_outline,
                outline_width=self.outline_width,
                outline_color=self.outline_color,
                glow=False,
                draw_fill=True,
            )
        painter.end()

    def center_at_bottom(self):
        anchor = self._anchor_geometry()
        if not anchor:
            return

        stage = getattr(self, '_song_stage_size', None)
        if stage is not None:
            if self.size() != stage:
                self.resize(stage)
        else:
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

        if event.buttons() == Qt.MouseButton.LeftButton and (self.parent() or self._anchor_rect_global is not None):
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
        self._prewarmed_idx = -1
        self._subtitle_effects = SubtitleEffects(self)

        self._prewarm_timer = QTimer(self)
        self._prewarm_timer.setSingleShot(True)
        self._prewarm_timer.timeout.connect(self._prewarm_next_cue)

        # --- CẤU HÌNH CÔNG TẮC FADE IN / OUT ---
        self.use_fade_effect = True

        self.fade_anim = QPropertyAnimation(self, b"opacity")
        self.fade_anim.setDuration(240)
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
        if not visible and hasattr(self, '_prewarm_timer'):
            self._prewarm_timer.stop()
        super().setVisible(visible)

    def _finish_fade(self):
        if self.fade_anim.endValue() == 0.0 and self._opacity <= 0.0:
            self._subtitle_effects.clear()
            self.sweep_row_groups = ()
            self.hide()

    def set_fade_enabled(self, enabled: bool):
        """Hàm công khai để giao diện Setting gọi bật/tắt Fade"""
        self.use_fade_effect = bool(enabled)
        if not self.use_fade_effect:
            self.fade_anim.stop()
            self.set_opacity(1.0)

    def load_subtitles(self, segments):
        if hasattr(self, '_prewarm_timer'):
            self._prewarm_timer.stop()
        self._prewarmed_idx = -1
        self._song_stage_size = None
        self._render_cache.clear()
        self._subtitle_effects.clear()
        self.sweep_row_groups = ()
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
        if self._presentation_guard is not None and self.subtitles:
            self._song_stage_size = self._compute_song_stage_size()

    def clean_ass_tags(self, text):
        if not text:
            return ""
        clean_text = re.sub(r'\{.*?\}', '', text)
        clean_text = clean_text.replace(r'\N', ' ').replace(r'\n', ' ')
        clean_text = re.sub(r'\s+', ' ', clean_text)
        return clean_text.strip()

    def set_mode(self, mode):
        self.mode = mode
        self._prewarmed_idx = -1
        self._song_stage_size = (
            self._compute_song_stage_size()
            if (self._presentation_guard is not None and self.subtitles and mode != SubtitleMode.OFF)
            else None
        )
        self._render_cache.clear()
        self._current_ms_cache = -1  # Ép refresh
        self.update_position(self._current_ms_cache)

    def _mode_language_keys(self):
        """Return display language keys without imposing a fixed language count."""
        if self.mode == SubtitleMode.OFF:
            return ()
        explicit = getattr(self.mode, 'display_language_keys', None)
        if callable(explicit):
            explicit = explicit()
        if isinstance(explicit, (tuple, list)):
            return tuple(str(key).strip() for key in explicit if str(key).strip())
        value = str(getattr(self.mode, 'value', self.mode) or '')
        return tuple(part for part in value.split('_') if part and part != 'off')

    def build_text_plan(self, sub_dict):
        """Build display text and one stable sweep-group id per physical row."""
        if self.mode == SubtitleMode.OFF:
            return "", ()

        rows = []
        row_groups = []
        safe_limit = 70

        def smart_wrap(text):
            if not text:
                return ""
            length = len(text)
            if length <= safe_limit:
                return text
            balanced_width = int(length / 2) + 6
            final_width = max(40, balanced_width)
            return textwrap.fill(
                text, width=final_width, break_long_words=False, break_on_hyphens=False
            )

        raw_orig = str(sub_dict.get('orig', '') or '').strip()
        emitted_orig = False
        next_group = 0
        for requested_key in self._mode_language_keys():
            cue_key = 'orig' if requested_key in ('jp', 'ja') else requested_key
            if cue_key == 'en':
                raw_en = str(sub_dict.get('en', '') or '').strip()
                phrase = raw_en if raw_en else raw_orig
                if emitted_orig and phrase and phrase.lower() == raw_orig.lower():
                    continue
            else:
                phrase = str(sub_dict.get(cue_key, '') or '').strip()
            if not phrase:
                continue

            wrapped_rows = smart_wrap(phrase).split('\n')
            rows.extend(wrapped_rows)
            row_groups.extend([next_group] * len(wrapped_rows))
            next_group += 1
            if cue_key == 'orig':
                emitted_orig = True

        return "\n".join(rows), tuple(row_groups)

    def build_text(self, sub_dict):
        return self.build_text_plan(sub_dict)[0]

    def _compute_song_stage_size(self) -> QSize | None:
        """Compute one fixed per-song stage size so cue switches never reallocate Windows DWM HWND surfaces."""
        if not self.subtitles or self.mode == SubtitleMode.OFF:
            return None
        pad_x, pad_y = self._effective_padding()
        max_w, max_h = 0, 0
        for sub in self.subtitles[:240]:
            text, groups = self.build_text_plan(sub)
            text = text.strip()
            if not text:
                continue
            row_groups = tuple(groups) if len(groups) == len(text.split('\n')) else ()
            w, h = measure_box_size(
                text,
                self.font(),
                row_groups,
                False,
                pad_left=pad_x,
                pad_right=pad_x,
                pad_top=pad_y,
                pad_bottom=pad_y,
            )
            if w > max_w:
                max_w = w
            if h > max_h:
                max_h = h
        if max_w <= 0 or max_h <= 0:
            return None
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            cap_w = max(280, (avail.width() * 3) // 4)
            max_w = min(max_w + 64, cap_w)
        else:
            max_w = min(max_w + 64, 1040)
        return QSize(max_w, max_h + 76)

    def _schedule_prewarm(self, current_idx: int):
        next_idx = current_idx + 1
        if next_idx >= len(self.subtitles) or self._prewarmed_idx == next_idx:
            return
        self._prewarm_next_idx = next_idx
        self._prewarm_timer.start(520)

    def _prewarm_next_cue(self):
        """Build the next cue's TypographyPlan + DPR sprite during idle time so frame 0 is <0.5ms."""
        if self.mode == SubtitleMode.OFF or not self.subtitles:
            return
        target_idx = getattr(self, '_prewarm_next_idx', -1)
        while 0 <= target_idx < len(self.subtitles):
            sub = self.subtitles[target_idx]
            text, groups = self.build_text_plan(sub)
            text = text.strip()
            if text:
                row_groups = tuple(groups) if len(groups) == len(text.split('\n')) else ()
                pad_x, pad_y = self._effective_padding()
                w, h = measure_box_size(
                    text,
                    self.font(),
                    row_groups,
                    False,
                    pad_left=pad_x,
                    pad_right=pad_x,
                    pad_top=pad_y,
                    pad_bottom=pad_y,
                )
                screen = self.screen()
                max_w = None
                if screen is not None:
                    avail = screen.availableGeometry()
                    max_w = max(200, (avail.width() * 2) // 3)
                    w = min(w, max_w)
                stage = self._song_stage_size
                if self._presentation_guard is not None and stage is not None:
                    w = max(w, stage.width())
                    h = max(h, stage.height())
                    if max_w is not None:
                        w = min(w, max_w)
                size = QSize(w, h)
                contents = QRect(pad_x, pad_y, max(1, w - pad_x * 2), max(1, h - pad_y * 2))
                plan, _ = self._plan_for(text, contents, size, row_groups)
                dpr = max(1.0, float(self.devicePixelRatioF()))
                if self._subtitle_effects.options.get('enabled'):
                    self._subtitle_effects.prewarm_plan(plan, text, size, dpr)
                else:
                    sprite_key = (
                        'static',
                        text,
                        row_groups,
                        self.font().key(),
                        size.width(),
                        size.height(),
                        self.current_color,
                        self.use_shadow,
                        self.shadow_alpha,
                        self.use_outline,
                        self.outline_width,
                        self.outline_color,
                        round(dpr, 3),
                    )
                    if self._render_cache.get_sprite(sprite_key) is None:
                        sprite, origin = rasterize_studio_sprite(
                            plan,
                            dpr=dpr,
                            font_color=self.current_color,
                            color_mode='original',
                            use_shadow=self.use_shadow,
                            shadow_alpha=self.shadow_alpha,
                            use_outline=self.use_outline,
                            outline_width=self.outline_width,
                            outline_color=self.outline_color,
                            glow=False,
                            studio_mode=True,
                        )
                        if sprite is not None:
                            self._render_cache.put_sprite(sprite_key, sprite, origin)
                self._prewarmed_idx = target_idx
                return
            target_idx += 1

    def _apply_text_and_geometry_atomic(self, new_text: str):
        """Update text, size and global coordinates with zero DWM reallocations when stage is locked."""
        was_visible = not self.isHidden()
        self.setUpdatesEnabled(False)
        try:
            self.setText(new_text)
            hint = self.sizeHint()
            screen = self.screen()
            if screen is not None:
                avail = screen.availableGeometry()
                max_w = max(200, (avail.width() * 2) // 3)
                hint = QSize(min(hint.width(), max_w), hint.height())
            if self._presentation_guard is not None:
                if self._song_stage_size is None:
                    self._song_stage_size = self._compute_song_stage_size() or hint
                stage_w = max(self._song_stage_size.width(), hint.width())
                stage_h = max(self._song_stage_size.height(), hint.height())
                if screen is not None:
                    stage_w = min(stage_w, max_w)
                self._song_stage_size = QSize(stage_w, stage_h)
                hint = self._song_stage_size
            pos = self._target_position(hint.width(), hint.height())
            if pos is not None:
                target_rect = QRect(pos[0], pos[1], hint.width(), hint.height())
                if self.geometry() != target_rect:
                    self.setGeometry(target_rect)
            elif self.size() != hint:
                self.resize(hint)
        finally:
            self.setUpdatesEnabled(True)
        if was_visible:
            self.update()

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

        # Trường hợp không có sub: GIỮ NGUYÊN row_groups & effect sprite để fade-out mượt không chập!
        if not active_sub:
            self._smart_hide(instant=False)
            return

        new_text, row_groups = self.build_text_plan(active_sub)
        new_text = new_text.strip()

        if not new_text:
            self._smart_hide(instant=False)
            return

        self.sweep_row_groups = (
            tuple(row_groups) if len(row_groups) == len(new_text.split('\n')) else ()
        )

        self._subtitle_effects.sync((idx, active_sub['start'], active_sub['end'], new_text), pts_ms)
        self._schedule_prewarm(idx)

        # Nếu chữ giống hệt đang hiển thị -> Giữ nguyên
        if not self.isHidden() and self.text() == new_text:
            if (self.fade_anim.state() == QAbstractAnimation.State.Running
                    and self.fade_anim.endValue() == 0.0):
                self._smart_show(instant=False)
            return

        prev_sub_end = self.subtitles[idx - 1]['end'] if idx > 0 else 0
        gap_from_prev = active_sub['start'] - prev_sub_end

        # Cập nhật chữ mới + Vị trí chuẩn nguyên khối (Atomic)
        self._apply_text_and_geometry_atomic(new_text)
        if guard is not None:
            guard.prepare_geometry()

        if self.isHidden():
            if gap_from_prev >= 140 or idx == 0:
                self._smart_show(instant=False)
            else:
                self._smart_show(instant=True)
        elif (
            self.use_fade_effect
            and self.fade_anim.state() == QAbstractAnimation.State.Running
            and self.fade_anim.endValue() == 0.0
            and gap_from_prev >= 140
        ):
            self._opacity = min(self._opacity, 0.18)
            self._smart_show(instant=False)
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

        self.fade_anim.setDuration(200)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_anim.setStartValue(start_op)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

    def _smart_hide(self, instant=False):
        """Ẩn sub an toàn, giữ độ rõ tự nhiên cuối câu rồi mới tan/thoát mượt 380ms"""
        self._prewarm_timer.stop()
        if self.isHidden():
            if instant:
                self.fade_anim.stop()
                self.set_opacity(0.0)
                self._subtitle_effects.clear()
                self.sweep_row_groups = ()
            return

        if not self.use_fade_effect or instant:
            self.fade_anim.stop()
            self.set_opacity(0.0)
            self._subtitle_effects.clear()
            self.sweep_row_groups = ()
            self.hide()
            return

        if self.fade_anim.state() == QAbstractAnimation.State.Running and self.fade_anim.endValue() == 0.0:
            return

        keep_erased_sweep = self._subtitle_effects.finish_erase_sweep_for_fade()
        if not keep_erased_sweep:
            self._subtitle_effects.freeze_for_fade()

        self.fade_anim.stop()
        self.fade_anim.setDuration(380)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
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
            self._prewarmed_idx = -1
            self.update_style()
            self._song_stage_size = (
                self._compute_song_stage_size()
                if (self._presentation_guard is not None and self.subtitles and self.mode != SubtitleMode.OFF)
                else None
            )
            if not self.isHidden() and self.text():
                self._apply_text_and_geometry_atomic(self.text())
            elif not self.isHidden():
                self.recalc_position()
            self.update()

    def set_bottom_margin(self, margin):
        if self._current_margin != margin:
            self._current_margin = margin
            if not self.isHidden():
                self.recalc_position()
