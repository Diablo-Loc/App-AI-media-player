"""Bounded decorative word sweeps; never inferred vocal/word timestamps."""
import math
from typing import NamedTuple

from PySide6.QtCore import QTextBoundaryFinder, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainterPath, QPen, QRadialGradient, QTextLayout, QTextOption, QRegion
from ui.subtitle_studio import iter_visual_lines
from ui.subtitle_vfx import VFX_TRAIL_KEYS, paint_vfx_trail

TRAILS = (
    ('none', 'Không'),
    ('sparkles', 'Sao lấp lánh theo câu'),
    ('shuriken', 'Từ → phi tiêu → chữ'),
    ('comet', 'Sao băng & đuôi sáng'),
    ('fireflies', 'Đom đóm ngọc lam'),
    ('snow', 'Tuyết pha lê'),
    ('petals', 'Cánh hoa bay'),
    ('bubbles', 'Bong bóng ánh sáng'),
    ('diamonds', 'Tinh thể xoay'),
    ('ribbon', 'Dải cực quang'),
)
INTENSITIES = (('gentle', 'Nhẹ · ít hạt'), ('normal', 'Vừa'), ('rich', 'Rực rỡ'))
MAX_PARTICLES = 24
MAX_REGIONS = 256


class WordRegion(NamedTuple):
    rect: QRectF
    leading: float
    trailing: float
    start: int
    end: int
    merged: int


def _compact_text(text):
    return ' '.join(str(text or '').split())


def _logical_subtitle_texts(mode, cue):
    """Compatibility fallback for labels that do not provide explicit row groups."""
    if not isinstance(cue, dict):
        return []
    explicit = getattr(mode, 'display_language_keys', None)
    if callable(explicit):
        explicit = explicit()
    if isinstance(explicit, (tuple, list)):
        requested = tuple(str(key).strip() for key in explicit if str(key).strip())
    else:
        value = str(getattr(mode, 'value', mode) or '')
        requested = tuple(part for part in value.split('_') if part and part != 'off')
    raw_orig = str(cue.get('orig', '') or '').strip()
    result = []
    emitted_orig = False
    for requested_key in requested:
        cue_key = 'orig' if requested_key in ('jp', 'ja') else requested_key
        if cue_key == 'en':
            raw_en = str(cue.get('en', '') or '').strip()
            phrase = raw_en if raw_en else raw_orig
            if emitted_orig and phrase and phrase.lower() == raw_orig.lower():
                continue
        else:
            phrase = str(cue.get(cue_key, '') or '').strip()
        if phrase:
            result.append(phrase)
            if cue_key == 'orig':
                emitted_orig = True
    return result


def subtitle_row_groups(text, mode=None, cue=None):
    """Map physical display rows back to logical subtitle-language phrases."""
    lines = str(text or '').split('\n')
    fallback = tuple(range(len(lines)))
    logical = _logical_subtitle_texts(mode, cue)
    if not logical or len(lines) > MAX_REGIONS:
        return fallback

    groups = []
    cursor = 0
    for group_id, phrase in enumerate(logical):
        target = _compact_text(phrase)
        if not target:
            continue
        start = cursor
        matched = False
        while cursor < len(lines):
            cursor += 1
            candidate = _compact_text(' '.join(lines[start:cursor]))
            if candidate == target:
                groups.extend([group_id] * (cursor - start))
                matched = True
                break
            if len(candidate) > len(target):
                break
        if not matched:
            return fallback
    if cursor != len(lines) or len(groups) != len(lines):
        return fallback
    return tuple(groups)


def _label_row_groups(label):
    text = label.text()
    lines = text.split('\n')
    explicit = getattr(label, 'sweep_row_groups', None)
    if (isinstance(explicit, (tuple, list)) and len(explicit) == len(lines)
            and all(isinstance(value, int) and not isinstance(value, bool) for value in explicit)):
        return tuple(explicit)
    effect = getattr(label, '_subtitle_effects', None)
    cue_identity = getattr(effect, 'cue', None)
    subtitles = getattr(label, 'subtitles', None)
    if (isinstance(cue_identity, tuple) and cue_identity
            and isinstance(subtitles, (tuple, list))):
        index = cue_identity[0]
        if isinstance(index, int) and 0 <= index < len(subtitles):
            return subtitle_row_groups(text, getattr(label, 'mode', None), subtitles[index])
    return tuple(range(len(lines)))


def word_units(text):
    """UTF-16 grapheme boundaries, preserving accents, emoji ZWJ and shaping."""
    encoded = text.encode('utf-16-le', errors='surrogatepass')
    length = len(encoded) // 2
    if length > 8192:
        return [(0, length)] if text.strip() else []
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    units = []
    pending = None
    start = 0
    end = finder.toNextBoundary()
    while end >= 0:
        cluster = encoded[start * 2:end * 2].decode('utf-16-le', errors='surrogatepass')
        first = ord(cluster[0]) if cluster else 0
        separate = (0x2E80 <= first <= 0x9FFF or 0xF900 <= first <= 0xFAFF
                    or 0x20000 <= first <= 0x323AF or first >= 0x1F000)
        if cluster.isspace() or separate:
            if pending is not None:
                units.append((pending, start))
                pending = None
            if separate:
                units.append((start, end))
        elif pending is None:
            pending = start
        start = end
        end = finder.toNextBoundary()
    if pending is not None:
        units.append((pending, length))
    return units


def build_regions_with_groups(label, duration_ms):
    """Use the exact TypographyPlan visual lines so particles/karaoke stay 0.0px locked to glyphs."""
    viewport = QRectF(label.contentsRect())
    visual_lines = iter_visual_lines(label)
    slots = max(1, min(96, int(max(0, duration_ms) / 90)))
    rows, groups, total = [], [], 0
    for vline in visual_lines:
        text = vline.text
        if not text or not text.strip():
            continue
        band = QRectF(viewport.left(), vline.y_top, viewport.width(), vline.line_height)
        if not band.intersects(viewport):
            continue
        units = word_units(text)
        if not units or total >= MAX_REGIONS:
            continue
        available = min(slots, MAX_REGIONS - total)
        chunk = max(1, math.ceil(len(units) / available))
        layout = QTextLayout(text, vline.font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(max(1.0, vline.width))
        layout.endLayout()
        row = []
        for offset in range(0, len(units), chunk):
            part = units[offset:offset + chunk]
            start, end = part[0][0], part[-1][1]
            leading, trailing = vline.x + line.cursorToX(start)[0], vline.x + line.cursorToX(end)[0]
            rect = QRectF(
                min(leading, trailing),
                vline.y_top,
                max(1.0, abs(trailing - leading)),
                vline.line_height,
            ).intersected(viewport)
            if not rect.isEmpty():
                row.append(WordRegion(rect, leading, trailing, start, end, len(part)))
        if row:
            rows.append(row)
            groups.append(vline.group)
            total += len(row)
    return rows, tuple(groups)


def build_regions(label, duration_ms):
    return build_regions_with_groups(label, duration_ms)[0]


def _star(points, inner):
    path = QPainterPath()
    for i in range(points * 2):
        angle = -math.pi / 2 + i * math.pi / points
        radius = 1 if i % 2 == 0 else inner
        x, y = math.cos(angle) * radius, math.sin(angle) * radius
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


class ParticlePainter:
    """One cached layout, reusable vector shapes and at most 24 marks/frame."""
    def __init__(self, label):
        self.label = label
        self.key = None
        self.rows = []
        self.tracks = []
        self._track_group_ids = ()
        self._row_group_ids = ()
        self._sweep_cells = []
        self._sweep_prefix = []
        self.star = _star(4, .18)
        self.shuriken = _star(4, .38)
        self.diamond = _star(4, .62)
        self.petal = QPainterPath()
        self.petal.moveTo(0, -1)
        self.petal.cubicTo(1.5, -.3, .7, 1.1, 0, 1)
        self.petal.cubicTo(-.7, 1.1, -1.5, -.3, 0, -1)
        self.petal.closeSubpath()
        self.last_draw_count = 0

    def clear(self):
        self.key = None
        self.rows = []
        self.tracks = []
        self._track_group_ids = ()
        self._row_group_ids = ()
        self._sweep_cells = []
        self._sweep_prefix = []
        self.last_draw_count = 0

    def prepare(self, duration_ms):
        row_groups = _label_row_groups(self.label)
        cached_plan = getattr(self.label, '_cached_plan', None)
        if (
            cached_plan is not None
            and getattr(self.label, '_cached_text', None) == self.label.text()
            and getattr(self.label, '_cached_size', None) == self.label.size()
        ):
            geom_sig = id(cached_plan)
        else:
            visual_lines = iter_visual_lines(self.label)
            geom_sig = tuple((round(l.x, 1), round(l.y_top, 1), round(l.width, 1), l.group) for l in visual_lines)
        key = (
            self.label.text(),
            self.label.font().key(),
            self.label.contentsRect().getRect(),
            duration_ms,
            row_groups,
            getattr(self.label, 'phonetic_top_group', None),
            geom_sig,
        )
        if key != self.key:
            self.key = key
            self.rows, visible_groups = build_regions_with_groups(self.label, duration_ms)
            if len(visible_groups) != len(self.rows):
                visible_groups = tuple(range(len(self.rows)))
            self._row_group_ids = visible_groups
            order = []
            for group in visible_groups:
                if group not in order:
                    order.append(group)
            self.tracks = []
            track_groups = []
            for group in order:
                track = []
                for row_index, row in enumerate(self.rows):
                    if visible_groups[row_index] == group:
                        track.extend(row)
                if track:
                    self.tracks.append(track)
                    track_groups.append(group)
            self._track_group_ids = tuple(track_groups)
            self._sweep_cells, self._sweep_prefix = [], []

    def _prepare_sweep(self):
        self._sweep_cells, self._sweep_prefix = [], []
        viewport = QRectF(self.label.contentsRect())
        row_cells = []
        for row_index, row in enumerate(self.rows):
            top = viewport.top() if row_index == 0 else (
                self.rows[row_index - 1][0].rect.bottom() + row[0].rect.top()) / 2
            bottom = viewport.bottom() if row_index == len(self.rows) - 1 else (
                row[0].rect.bottom() + self.rows[row_index + 1][0].rect.top()) / 2
            visual = sorted(range(len(row)), key=lambda i: row[i].rect.center().x())
            edges = [viewport.left()]
            edges.extend((row[a].rect.right() + row[b].rect.left()) / 2
                         for a, b in zip(visual, visual[1:]))
            edges.append(viewport.right())
            edges = [min(viewport.right(), max(viewport.left(), edge)) for edge in edges]
            for i in range(1, len(edges)):
                edges[i] = max(edges[i], edges[i - 1])
            cells = [QRegion() for _ in row]
            for position, logical in enumerate(visual):
                left, right = math.floor(edges[position]), math.floor(edges[position + 1])
                band_top, band_bottom = math.floor(top), math.floor(bottom)
                cells[logical] = QRegion(left, band_top, max(0, right - left),
                                         max(0, band_bottom - band_top))
            row_cells.append(cells)
        order = []
        for group in self._row_group_ids:
            if group not in order:
                order.append(group)
        for group in order:
            cells = []
            for row_index, row in enumerate(row_cells):
                if self._row_group_ids[row_index] == group:
                    cells.extend(row)
            if not cells:
                continue
            prefix = [QRegion()]
            for cell in cells:
                prefix.append(prefix[-1].united(cell))
            self._sweep_cells.append(cells)
            self._sweep_prefix.append(prefix)

    def sweep_masks(self, progress, track_progresses=None):
        """Pure media-time mask with optional per-track word-level karaoke progress."""
        base_p = min(1.0, max(0.0, progress))
        if not self._sweep_cells and self.rows:
            self._prepare_sweep()
        hidden, active = QRegion(), []
        for idx_t, (cells, prefix) in enumerate(zip(self._sweep_cells, self._sweep_prefix)):
            if not cells:
                continue
            g_id = self._track_group_ids[idx_t] if idx_t < len(self._track_group_ids) else idx_t
            tp = (
                min(1.0, max(0.0, float(track_progresses[g_id])))
                if (isinstance(track_progresses, dict) and g_id in track_progresses)
                else base_p
            )
            if tp >= 1:
                hidden = hidden.united(prefix[len(cells) - 1])
                active.append((cells[-1], 1.0))
                continue
            position = tp * len(cells)
            index = min(len(cells) - 1, int(position))
            local = min(1.0, position - index)
            hidden = hidden.united(prefix[index])
            alpha = 1.0 if index == len(cells) - 1 else 1 - local * local * (3 - 2 * local)
            active.append((cells[index], alpha))
        return hidden, active

    def targets(self, progress, track_progresses=None):
        result = []
        base_p = min(1.0, max(0.0, progress))
        for idx_t, track in enumerate(self.tracks):
            g_id = self._track_group_ids[idx_t] if idx_t < len(self._track_group_ids) else idx_t
            tp = (
                min(1.0, max(0.0, float(track_progresses[g_id])))
                if (isinstance(track_progresses, dict) and g_id in track_progresses)
                else base_p
            )
            position = tp * len(track)
            index = min(len(track) - 1, int(position))
            region = track[index]
            local = min(1.0, position - index)
            visible_left, visible_right = region.rect.left(), region.rect.right()
            x = region.leading + (region.trailing - region.leading) * local
            result.append((region, local, min(visible_right, max(visible_left, x))))
        return result

    def morph_regions(self, progress, style, intensity, track_progresses=None):
        if style != 'shuriken' or progress <= 0 or progress >= 1:
            return []
        strength = {'gentle': .3, 'normal': .5, 'rich': .65}[intensity]
        return [(region.rect, 1 - strength * math.sin(local * math.pi))
                for region, local, _ in self.targets(progress, track_progresses)]

    def _paint_spotlight(self, painter, targets, envelope, intensity):
        radius_mul = {'gentle': 1.25, 'normal': 1.55, 'rich': 1.85}[intensity]
        for region, _local, front in targets:
            if self.last_draw_count >= MAX_PARTICLES:
                break
            rect = region.rect
            radius = max(20.0, rect.height() * 0.92 * radius_mul)
            center = QPointF(front, rect.center().y())
            bloom = QRadialGradient(center, radius)
            bloom.setColorAt(0.0, QColor(255, 255, 255, int(62 * envelope)))
            bloom.setColorAt(0.45, QColor(186, 230, 253, int(28 * envelope)))
            bloom.setColorAt(1.0, QColor(186, 230, 253, 0))
            painter.setBrush(bloom)
            painter.drawEllipse(center, radius * 1.45, radius * 0.75)
            self.last_draw_count += 1

    def _paint_karaoke_flare(self, painter, targets, envelope, intensity):
        # AMLL feathered karaoke sweep uses word spring lift instead of a heavy oval blob over glyphs
        return

    def _paint_neon_pulse(self, painter, progress, envelope, intensity, track_progresses=None):
        track_idx_map = {}
        for row_idx, r_group in enumerate(self._row_group_ids):
            track_idx_map.setdefault(r_group, []).extend(self.rows[row_idx])
        thickness = {'gentle': 2.0, 'normal': 2.4, 'rich': 3.0}[intensity]
        targets = self.targets(progress, track_progresses)
        for _group_id, row_regions in track_idx_map.items():
            if not row_regions or self.last_draw_count >= MAX_PARTICLES:
                continue
            target_front = None
            for region, _local, front in targets:
                if region in row_regions:
                    target_front = (region, front)
                    break
            if target_front is None:
                continue
            active_region, front = target_front
            left_x = min(r.rect.left() for r in row_regions)
            bar_y = active_region.rect.bottom() + 2.5
            span = max(3.0, front - left_x)
            # Soft neon aura underneath the energy beam
            aura = QLinearGradient(left_x, bar_y, front, bar_y)
            aura.setColorAt(0.0, QColor(251, 146, 60, int(18 * envelope)))
            aura.setColorAt(0.7, QColor(251, 113, 133, int(95 * envelope)))
            aura.setColorAt(1.0, QColor(254, 240, 138, int(155 * envelope)))
            painter.setBrush(aura)
            painter.drawRoundedRect(QRectF(left_x, bar_y - thickness * 1.4, span, thickness * 2.8), 3.0, 3.0)
            self.last_draw_count += 1
            if self.last_draw_count < MAX_PARTICLES:
                core = QLinearGradient(left_x, bar_y, front, bar_y)
                core.setColorAt(0.0, QColor(251, 146, 60, int(65 * envelope)))
                core.setColorAt(0.8, QColor(253, 224, 71, int(210 * envelope)))
                core.setColorAt(1.0, QColor(255, 255, 255, int(245 * envelope)))
                painter.setBrush(core)
                painter.drawRoundedRect(QRectF(left_x, bar_y - thickness * 0.5, span, thickness), 1.5, 1.5)
                self.last_draw_count += 1
            if self.last_draw_count < MAX_PARTICLES:
                head_r = thickness * 2.6
                glow = QRadialGradient(QPointF(front, bar_y), head_r)
                glow.setColorAt(0.0, QColor(255, 255, 255, int(235 * envelope)))
                glow.setColorAt(0.45, QColor(253, 186, 116, int(135 * envelope)))
                glow.setColorAt(1.0, QColor(251, 113, 133, 0))
                painter.setBrush(glow)
                painter.drawEllipse(QPointF(front, bar_y), head_r, head_r)
                self.last_draw_count += 1

    def _paint_lyric_bar(self, painter, progress, envelope, intensity, track_progresses=None):
        track_idx_map = {}
        for row_idx, r_group in enumerate(self._row_group_ids):
            track_idx_map.setdefault(r_group, []).extend(self.rows[row_idx])
        thickness = {'gentle': 2.0, 'normal': 2.6, 'rich': 3.2}[intensity]
        targets = self.targets(progress, track_progresses)
        for _group_id, row_regions in track_idx_map.items():
            if not row_regions or self.last_draw_count >= MAX_PARTICLES:
                continue
            target_front = None
            for region, _local, front in targets:
                if region in row_regions:
                    target_front = (region, front)
                    break
            if target_front is None:
                continue
            active_region, front = target_front
            left_x = min(r.rect.left() for r in row_regions)
            bar_y = active_region.rect.bottom() - 2.0
            span = max(2.0, front - left_x)
            grad = QLinearGradient(left_x, bar_y, front, bar_y)
            grad.setColorAt(0.0, QColor(56, 189, 248, int(45 * envelope)))
            grad.setColorAt(0.75, QColor(125, 211, 252, int(175 * envelope)))
            grad.setColorAt(1.0, QColor(255, 255, 255, int(235 * envelope)))
            painter.setBrush(grad)
            painter.drawRoundedRect(QRectF(left_x, bar_y - thickness / 2.0, span, thickness), 1.5, 1.5)
            self.last_draw_count += 1
            if self.last_draw_count < MAX_PARTICLES:
                head_r = thickness * 2.1
                glow = QRadialGradient(QPointF(front, bar_y), head_r)
                glow.setColorAt(0.0, QColor(255, 255, 255, int(215 * envelope)))
                glow.setColorAt(0.5, QColor(125, 211, 252, int(110 * envelope)))
                glow.setColorAt(1.0, QColor(125, 211, 252, 0))
                painter.setBrush(glow)
                painter.drawEllipse(QPointF(front, bar_y), head_r, head_r)
                self.last_draw_count += 1

    def _paint_meteor_shower(self, painter, targets, progress, envelope, intensity):
        budget = {'gentle': 6, 'normal': 10, 'rich': 16}[intensity]
        for row_idx, (region, _local, front) in enumerate(targets):
            rect = region.rect
            for i in range(budget // max(1, len(targets))):
                if self.last_draw_count >= MAX_PARTICLES:
                    break
                phase = (progress * 1.9 + i * 0.31 + row_idx * 0.47) % 1.0
                sx = front - 26.0 + (i - 2) * 38.0 + phase * 46.0
                sy = rect.top() - 18.0 + phase * (rect.height() + 26.0)
                ex = sx - 24.0
                ey = sy - 16.0
                tail_grad = QLinearGradient(ex, ey, sx, sy)
                tail_grad.setColorAt(0.0, QColor(251, 146, 60, 0))
                tail_grad.setColorAt(0.55, QColor(253, 224, 71, int(135 * envelope)))
                tail_grad.setColorAt(1.0, QColor(255, 255, 255, int(235 * envelope)))
                painter.setPen(QPen(tail_grad, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(QPointF(ex, ey), QPointF(sx, sy))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 251, 235, int(235 * envelope)))
                painter.drawEllipse(QPointF(sx, sy), 2.1, 2.1)
                self.last_draw_count += 1

    def _paint_electric_arc(self, painter, targets, progress, envelope, intensity):
        steps = {'gentle': 4, 'normal': 5, 'rich': 6}[intensity]
        for row_idx, (region, _local, front) in enumerate(targets):
            if self.last_draw_count >= MAX_PARTICLES:
                break
            rect = region.rect
            x0 = max(rect.left() - 6.0, front - max(28.0, rect.width() * 0.45))
            x1 = min(rect.right() + 6.0, front + 10.0)
            y_base = rect.bottom() + 2.0
            phase_t = progress * 42.0 + row_idx * 2.7
            pts = []
            for k in range(steps + 1):
                u = k / steps
                px = x0 + (x1 - x0) * u
                jitter = (math.sin(phase_t + k * 2.2) * 0.65 + math.sin(phase_t * 2.1 + k * 3.7) * 0.35) * (4.4 if 0 < k < steps else 0.0)
                pts.append(QPointF(px, y_base + jitter))
            # Soft neon cyan halo + crisp white electric core
            for col, width in ((QColor(52, 211, 153, int(145 * envelope)), 3.2),
                               (QColor(34, 211, 238, int(210 * envelope)), 1.6),
                               (QColor(255, 255, 255, int(245 * envelope)), 0.9)):
                if self.last_draw_count >= MAX_PARTICLES:
                    break
                painter.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                for idx in range(len(pts) - 1):
                    painter.drawLine(pts[idx], pts[idx + 1])
                self.last_draw_count += 1
        painter.setPen(Qt.PenStyle.NoPen)

    def paint(self, painter, progress, style, intensity, entry_progress=1.0, burst=False, beat_pulse=0.0, track_progresses=None):
        self.last_draw_count = 0
        if (style == 'none' and not burst) or not self.rows:
            return
        progress = min(1.0, max(0.0, progress))
        envelope = min(1.0, progress * 14, (1 - progress) * 24)
        if isinstance(track_progresses, dict) and track_progresses and progress < 0.996:
            if any(0.004 < float(v) < 0.996 for v in track_progresses.values()):
                envelope = max(envelope, min(1.0, (1.0 - progress) * 24.0))
        if burst and entry_progress < 1:
            envelope = max(envelope, math.sin(entry_progress * math.pi))
        if envelope <= 0:
            return
        budget = {'gentle': 8, 'normal': 16, 'rich': MAX_PARTICLES}[intensity]
        targets = self.targets(progress, track_progresses)
        per_row = max(1, budget // len(targets))
        painter.save()
        # Use full widget rect (with 16x24px canvas headroom) instead of tight contentsRect
        painter.setClipRect(self.label.rect(), Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)

        if style == 'karaoke_pro' and not burst:
            self._paint_karaoke_flare(painter, targets, envelope, intensity)
            painter.restore()
            return
        if style == 'neon_pulse' and not burst:
            self._paint_neon_pulse(painter, progress, envelope, intensity, track_progresses)
            painter.restore()
            return
        if style == 'spotlight' and not burst:
            self._paint_spotlight(painter, targets, envelope, intensity)
            painter.restore()
            return
        if style == 'lyric_bar' and not burst:
            self._paint_lyric_bar(painter, progress, envelope, intensity, track_progresses)
            painter.restore()
            return
        if style in VFX_TRAIL_KEYS and not burst:
            self.last_draw_count = paint_vfx_trail(
                painter,
                style,
                self.rows,
                self._row_group_ids,
                targets,
                progress,
                envelope,
                intensity,
                max_particles=MAX_PARTICLES,
                beat_pulse=beat_pulse,
            )
            painter.restore()
            return
        if style == 'meteor_shower' and not burst:
            self._paint_meteor_shower(painter, targets, progress, envelope, intensity)
            painter.restore()
            return
        if style == 'electric_arc' and not burst:
            self._paint_electric_arc(painter, targets, progress, envelope, intensity)
            painter.restore()
            return

        for row_index, (region, local, front) in enumerate(targets):
            rect = region.rect
            size = min(12.0, max(3.5, rect.height() * .25))
            count = min(per_row, budget - self.last_draw_count)
            for i in range(count):
                seed = i * 2.399963 + row_index * 1.713
                age = progress * 18 + seed
                wave = math.sin(age)
                x = front + math.cos(seed) * size * (1 + i * .28)
                y = rect.center().y() + math.sin(seed + progress * 9) * rect.height() * .28
                alpha = envelope * (.45 + .55 * abs(wave))
                radius = size * (.35 + .35 * abs(math.cos(age * .7)))
                color = QColor('#DBFFF4')
                shape = self.star
                angle = age * 45
                if style == 'shuriken':
                    shape = self.shuriken
                    color = QColor('#EDF3FF' if i % 2 == 0 else '#91A8FF')
                    if i == 0:
                        x, y = rect.center().x(), rect.center().y()
                        radius = min(rect.width() * .45, max(size * 1.2, rect.height() * .5))
                        alpha = envelope * (.3 + .7 * math.sin(local * math.pi))
                    angle = progress * 1440 + i * 57
                elif style == 'comet':
                    shape = None
                    x = front - i * size * .48 * (1 if region.trailing >= region.leading else -1)
                    y = rect.bottom() - rect.height() * 0.14 + math.sin(seed + progress * 6) * 1.4
                    radius = size * max(.16, .62 - i * .045)
                    alpha *= 0.85 * (1 - i / (count + 1))
                    color = QColor('#BAE6FD' if i < 2 else '#7DD3FC')
                elif style == 'fireflies':
                    shape = None
                    x = rect.left() + rect.width() * ((i * .618033 + progress * .3) % 1)
                    color = QColor('#B7FFD5')
                    radius *= .7
                elif style == 'snow':
                    x = rect.left() + rect.width() * ((i * .618033 + progress * .08) % 1)
                    y = rect.top() + rect.height() * ((i * .371 + progress * 1.7) % 1)
                    color = QColor('#DBF6FF')
                    radius *= .65
                elif style == 'petals':
                    shape = self.petal
                    color = QColor('#FFB6D9' if i % 2 == 0 else '#D7BAFF')
                    x = rect.left() + rect.width() * ((i * .618033 + progress * .5) % 1)
                elif style == 'bubbles':
                    shape = None
                    color = QColor('#BCEAFF')
                    y = rect.bottom() - rect.height() * ((progress * 2 + i * .317) % 1)
                elif style == 'diamonds':
                    shape = self.diamond
                    color = QColor('#CDB8FF' if i % 2 else '#AFFFE8')
                elif style == 'ribbon':
                    shape = None
                    x = rect.left() + rect.width() * i / max(1, count - 1)
                    y = rect.center().y() + math.sin(progress * math.pi * 4 + i * .6) * rect.height() * .2
                    color = QColor('#82E5DD' if i % 2 else '#CBADFF')
                    radius *= .65
                color.setAlphaF(min(1.0, max(0.0, alpha * .85)))
                painter.save()
                painter.translate(x, y)
                if shape is None:
                    if style == 'bubbles':
                        painter.setPen(QPen(color, 1))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
                    else:
                        halo = QRadialGradient(QPointF(0, 0), radius * 1.6)
                        core_c = QColor(color)
                        edge_c = QColor(color)
                        edge_c.setAlpha(0)
                        halo.setColorAt(0.0, core_c)
                        halo.setColorAt(0.55, core_c)
                        halo.setColorAt(1.0, edge_c)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(halo)
                        painter.drawEllipse(QRectF(-radius * 1.6, -radius * 1.6, radius * 3.2, radius * 3.2))
                else:
                    painter.rotate(angle)
                    painter.scale(radius, radius)
                    painter.fillPath(shape, color)
                painter.restore()
                self.last_draw_count += 1
                if self.last_draw_count >= budget:
                    break
        painter.restore()
