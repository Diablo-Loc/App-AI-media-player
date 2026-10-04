"""Optional painter-only lyric effects; cue data and window geometry stay owned."""
import math

from PySide6.QtCore import QObject, QEvent, QVariantAnimation, QEasingCurve, QAbstractAnimation, Qt, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPen, QTransform, QImage, QPainter

ENTRANCES = (
    ('none', 'Không chuyển động'), ('drop', 'Chữ rơi nhẹ'),
    ('rise', 'Trượt lên'), ('left', 'Trượt từ trái'),
    ('right', 'Trượt từ phải'), ('zoom', 'Thu phóng nhẹ'),
    ('bounce', 'Nảy nhẹ'), ('reveal', 'Mở từ giữa'),
)
COLORS = (
    ('original', 'Màu chữ gốc'), ('shift', 'Chuyển sang ngọc lam'),
    ('mint', 'Gradient ngọc lam'), ('sunset', 'Gradient hoàng hôn'),
    ('ocean', 'Gradient đại dương'), ('pastel', 'Cầu vồng pastel'),
)
DEFAULTS = dict(enabled=False, entrance='drop', color='original',
                soft_fade=True, glow=False, shimmer=False, duration=320)


def normalize_options(value):
    """Validate one new preference subtree without rewriting legacy settings."""
    value = value if isinstance(value, dict) else {}
    result = dict(DEFAULTS)
    for key in ('enabled', 'soft_fade', 'glow', 'shimmer'):
        if isinstance(value.get(key), bool):
            result[key] = value[key]
    for key, choices in (('entrance', ENTRANCES), ('color', COLORS)):
        if isinstance(value.get(key), str) and value[key] in {choice[0] for choice in choices}:
            result[key] = value[key]
    duration = value.get('duration')
    if isinstance(duration, int) and not isinstance(duration, bool):
        result['duration'] = min(600, max(160, duration))
    return result


class SubtitleEffects(QObject):
    """One finite animation per cue, with cached paths supplied by the label."""
    def __init__(self, label):
        super().__init__(label)
        self.label = label
        self.options = dict(DEFAULTS)
        self.progress = 1.0
        self.cue = None
        self.last_ms = None
        self.player = None
        self._sprite_key = None
        self._sprite = None
        self._sprite_origin = QPointF()
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._frame)
        label.installEventFilter(self)

    def configure(self, value):
        self.options = normalize_options(value)
        self._sprite_key = None
        self._sprite = None
        self.settle()
        self.cue = None
        self.last_ms = None
        self.label.update()

    def _frame(self, value):
        self.progress = float(value)
        if self.label.isVisible():
            self.label.update()

    def settle(self):
        self.animation.stop()
        changed = self.progress != 1.0
        self.progress = 1.0
        if changed:
            self.label.update()

    def clear(self):
        self.settle()
        self.cue = None
        self.last_ms = None

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.settle()
        return False

    def bind_player(self, player):
        self.player = player
        player.playbackStateChanged.connect(self._state_changed)
        player.playbackRateChanged.connect(self._rate_changed)

    def _state_changed(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.PlaybackState.PlayingState:
            if self.label.isVisible() and self.animation.state() == QAbstractAnimation.State.Paused:
                self.animation.resume()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            if self.animation.state() == QAbstractAnimation.State.Running:
                self.animation.pause()
        else:
            self.clear()

    def _rate_changed(self, rate):
        if self.cue is not None and self.last_ms is not None:
            self.sync(self.cue, self.last_ms, force=True)

    def sync(self, cue, pts_ms, force=False):
        """Cue identity includes its index, so identical consecutive lyrics work."""
        if not self.options['enabled']:
            return
        changed = cue != self.cue
        seek = self.last_ms is not None and (pts_ms < self.last_ms or pts_ms - self.last_ms > 500)
        self.cue, self.last_ms = cue, pts_ms
        # Static gradients/glow need no timer. Never animate across a short cue.
        duration = max(1, min(self.options['duration'], int((cue[2] - cue[1]) / 2)))
        elapsed = max(0, pts_ms - cue[1])
        moving = (self.options['entrance'] != 'none' or self.options['soft_fade']
                  or self.options['shimmer'] or self.options['color'] == 'shift')
        if elapsed >= duration or not moving:
            self.settle()
        elif changed or seek or force:
            rate = max(0.1, float(self.player.playbackRate())) if self.player else 1.0
            self.animation.stop()
            self.animation.setDuration(max(1, round(duration / rate)))
            self.animation.start()
            self.animation.setCurrentTime(round(elapsed / rate))
            if self.player:
                from PySide6.QtMultimedia import QMediaPlayer
                if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self.animation.pause()

    def _brush(self, bounds, original):
        mode = self.options['color']
        if mode == 'original':
            return original
        if mode == 'shift':
            target = QColor('#74DFC2')
            p = self.progress
            return QColor.fromRgbF(*(original.redF() * (1-p) + target.redF() * p,
                                    original.greenF() * (1-p) + target.greenF() * p,
                                    original.blueF() * (1-p) + target.blueF() * p))
        palettes = {
            'mint': ('#D4FFF1', '#74DFC2', '#48B7BC'),
            'sunset': ('#FFD89B', '#FFAFBD', '#CBABFF'),
            'ocean': ('#B8F4FF', '#7CBFFF', '#C7B9FF'),
            'pastel': ('#FFB8D0', '#FFDFA1', '#B8F3D8', '#9EDFFF', '#CFBAFF'),
        }
        gradient = QLinearGradient(bounds.left(), bounds.top(), bounds.right(), bounds.top())
        palette = palettes[mode]
        for i, color in enumerate(palette):
            gradient.setColorAt(i / (len(palette)-1), QColor(color))
        return gradient

    def _draw_static(self, painter, path, bounds):
        if self.label.use_shadow:
            painter.fillPath(path.translated(2, 2), QColor(0, 0, 0, self.label.shadow_alpha))
        if self.options['glow']:
            for width, alpha in ((7, 25), (4, 45)):
                pen = QPen(QColor(116, 223, 194, alpha), width)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawPath(path)
        if self.label.use_outline:
            pen = QPen(QColor(self.label.outline_color), self.label.outline_width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)
        if self.options['color'] != 'shift':
            painter.fillPath(path, self._brush(bounds, QColor(self.label.current_color)))

    def _static_sprite(self, path, bounds):
        # Cache expensive outline/glow rasterization once, at native DPR. Only
        # one bounded sprite per label; never an unbounded frame/phrase cache.
        dpr = self.label.devicePixelRatioF()
        key = (id(path), self.label.text(), self.label.font().key(), self.label.size().width(),
               self.label.size().height(), self.label.current_color, self.label.use_shadow,
               self.label.shadow_alpha, self.label.use_outline, self.label.outline_width,
               self.label.outline_color, self.options['color'], self.options['glow'], dpr)
        if key != self._sprite_key:
            self._sprite_key, self._sprite = key, None
            rect = bounds.adjusted(-10, -10, 10, 10)
            width, height = max(1, math.ceil(rect.width()*dpr)), max(1, math.ceil(rect.height()*dpr))
            if width * height > 2_000_000:
                return None
            image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            if image.isNull():
                return None
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.translate(-rect.left(), -rect.top())
            self._draw_static(painter, path, bounds)
            painter.end()
            self._sprite, self._sprite_origin = image, rect.topLeft()
        return self._sprite

    def paint(self, painter, path):
        if not self.options['enabled']:
            return False
        painter.save()
        bounds = path.boundingRect()
        p = self.progress
        eased = 1 - (1-p)**3
        remaining = 1 - eased
        mode = self.options['entrance']
        travel = min(18.0, max(5.0, self.label.current_font_size * .45))
        dx = dy = 0.0
        scale = 1.0
        if mode == 'drop':
            dy = -travel * remaining
        elif mode == 'rise':
            dy = travel * remaining
        elif mode == 'left':
            dx = -travel * remaining
        elif mode == 'right':
            dx = travel * remaining
        elif mode == 'zoom':
            scale = .88 + .12 * eased
        elif mode == 'bounce':
            dy = -travel * remaining * math.cos(p * math.pi * 2)
            scale = .96 + .04 * eased
        transform = QTransform()
        center = bounds.center()
        transform.translate(center.x() + dx, center.y() + dy)
        transform.scale(scale, scale)
        transform.translate(-center.x(), -center.y())
        if mode == 'reveal' and p < 1.0:
            clip = bounds.adjusted(-6, -6, 6, 6)
            clip.setLeft(center.x() - clip.width() * eased / 2)
            clip.setRight(center.x() + (bounds.width() + 12) * eased / 2)
            painter.setClipRect(clip)
        if self.options['soft_fade']:
            painter.setOpacity(painter.opacity() * (.35 + .65 * eased))
        painter.setTransform(transform, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sprite = self._static_sprite(path, bounds)
        if sprite is not None:
            painter.drawImage(self._sprite_origin, sprite)
        else:
            self._draw_static(painter, path, bounds)
        if self.options['color'] == 'shift':
            painter.fillPath(path, self._brush(bounds, QColor(self.label.current_color)))
        if self.options['shimmer'] and p < 1.0:
            x = bounds.left() + (bounds.width() + 60) * p - 30
            gradient = QLinearGradient(x-24, 0, x+24, 0)
            gradient.setColorAt(0, QColor(255, 255, 255, 0))
            gradient.setColorAt(.5, QColor(255, 255, 255, 125))
            gradient.setColorAt(1, QColor(255, 255, 255, 0))
            painter.fillPath(path, gradient)
        painter.restore()
        return True


def install_subtitle_effects(owner):
    """One shell adapter; use existing appearance persistence and reset signal."""
    panel = owner.subsettings_panel.effects_panel
    effect = owner.sub_layer._subtitle_effects
    effect.configure(owner.config.get('subtitle_effects'))
    effect.bind_player(owner.media_player.player)

    def changed(options):
        effect.configure(options)
        owner._save_setting('subtitle_effects', options)
        owner.sub_layer.update_position(owner.sub_layer._current_ms_cache)

    def reset():
        effect.configure(None)
        panel.sync_options(None)

    panel.changed.connect(changed)
    owner.subsettings_panel.reset_requested.connect(reset)
