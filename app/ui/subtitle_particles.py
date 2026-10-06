"""Bounded decorative word sweeps; never inferred vocal/word timestamps."""
import math
from typing import NamedTuple

from PySide6.QtCore import QTextBoundaryFinder, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QTextLayout, QTextOption, QRegion

TRAILS = (
    ('none', 'Không'), ('sparkles', 'Sao lấp lánh theo câu'),
    ('shuriken', 'Từ → phi tiêu → chữ'), ('comet', 'Sao băng & đuôi sáng'),
    ('fireflies', 'Đom đóm ngọc lam'), ('snow', 'Tuyết pha lê'),
    ('petals', 'Cánh hoa bay'), ('bubbles', 'Bong bóng ánh sáng'),
    ('diamonds', 'Tinh thể xoay'), ('ribbon', 'Dải cực quang'),
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
    """Map physical display rows back to logical subtitle-language phrases.

    SubtitleLayer may wrap one language phrase into multiple QLabel rows.  A
    decorative sweep should traverse those rows sequentially as one phrase,
    while separate displayed languages keep independent simultaneous sweeps.
    Ambiguous/custom text falls back to the historical one-track-per-row plan.
    """
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
                groups.extend([group_id] * (cursor-start))
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
    """UTF-16 grapheme boundaries, preserving accents, emoji ZWJ and shaping.

    Whitespace languages group words; CJK/emoji use complete graphemes.
    Pathological lines use one band instead of allocating unlimited units.
    """
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
        cluster = encoded[start*2:end*2].decode('utf-16-le', errors='surrogatepass')
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


def build_regions(label, duration_ms):
    """Use the same font/baselines as DraggableSubtitle; keep cached glyphs whole."""
    metrics = label.fontMetrics()
    viewport = QRectF(label.contentsRect())
    lines = label.text().split('\n')
    spacing = metrics.lineSpacing()
    top = viewport.top() + (viewport.height() - spacing * len(lines)) / 2
    # At least 90ms per decorative slot. Dense/short cues merge regions rather
    # than flashing hundreds of words. This does not touch subtitle text/timing.
    slots = max(1, min(96, int(max(0, duration_ms) / 90)))
    rows, total = [], 0
    for index, text in enumerate(lines):
        baseline = top + metrics.ascent() + index * spacing
        band = QRectF(viewport.left(), baseline-metrics.ascent(), viewport.width(), spacing)
        if not band.intersects(viewport) or not text.strip():
            continue
        units = word_units(text)
        if not units or total >= MAX_REGIONS:
            continue
        available = min(slots, MAX_REGIONS-total)
        chunk = max(1, math.ceil(len(units) / available))
        x = viewport.left() + (viewport.width() - metrics.horizontalAdvance(text)) / 2
        # QTextLayout retains bidi shaping, while cursor positions match the
        # UTF-16 indices returned by QTextBoundaryFinder (not Python len()).
        layout = QTextLayout(text, label.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(max(1, metrics.horizontalAdvance(text)))
        layout.endLayout()
        row = []
        for offset in range(0, len(units), chunk):
            part = units[offset:offset+chunk]
            start, end = part[0][0], part[-1][1]
            leading, trailing = x + line.cursorToX(start)[0], x + line.cursorToX(end)[0]
            rect = QRectF(min(leading, trailing), baseline-metrics.ascent(),
                          max(1, abs(trailing-leading)), spacing).intersected(viewport)
            if not rect.isEmpty():
                row.append(WordRegion(rect, leading, trailing, start, end, len(part)))
        if row:
            rows.append(row)
            total += len(row)
    return rows


def _star(points, inner):
    path = QPainterPath()
    for i in range(points * 2):
        angle = -math.pi/2 + i * math.pi/points
        radius = 1 if i % 2 == 0 else inner
        x, y = math.cos(angle)*radius, math.sin(angle)*radius
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
        self._row_group_ids = ()
        self._sweep_cells = []
        self._sweep_prefix = []
        self.last_draw_count = 0

    def prepare(self, duration_ms):
        row_groups = _label_row_groups(self.label)
        key = (self.label.text(), self.label.font().key(),
               self.label.contentsRect().getRect(), duration_ms, row_groups)
        if key != self.key:
            self.key = key
            self.rows = build_regions(self.label, duration_ms)
            visible_groups = tuple(group for line, group in zip(
                self.label.text().split('\n'), row_groups) if line.strip())
            if len(visible_groups) != len(self.rows):
                visible_groups = tuple(range(len(self.rows)))
            self._row_group_ids = visible_groups
            order = []
            for group in visible_groups:
                if group not in order:
                    order.append(group)
            self.tracks = []
            for group in order:
                track = []
                for row_index, row in enumerate(self.rows):
                    if visible_groups[row_index] == group:
                        track.extend(row)
                if track:
                    self.tracks.append(track)
            self._sweep_cells, self._sweep_prefix = [], []

    def _prepare_sweep(self):
        # Partition the existing text viewport, including outline/shadow space.
        # Logical region order stays intact for RTL; physical cells never overlap,
        # so hiding an earlier word cannot redraw or dim a neighbouring cell.
        self._sweep_cells, self._sweep_prefix = [], []
        viewport = QRectF(self.label.contentsRect())
        row_cells = []
        for row_index, row in enumerate(self.rows):
            top = viewport.top() if row_index == 0 else (
                self.rows[row_index-1][0].rect.bottom()+row[0].rect.top()) / 2
            bottom = viewport.bottom() if row_index == len(self.rows)-1 else (
                row[0].rect.bottom()+self.rows[row_index+1][0].rect.top()) / 2
            visual = sorted(range(len(row)), key=lambda i: row[i].rect.center().x())
            edges = [viewport.left()]
            edges.extend((row[a].rect.right()+row[b].rect.left())/2
                         for a, b in zip(visual, visual[1:]))
            edges.append(viewport.right())
            # Degenerate bidi/ligature positions still have monotonic cell edges.
            edges = [min(viewport.right(), max(viewport.left(), edge)) for edge in edges]
            for i in range(1, len(edges)):
                edges[i] = max(edges[i], edges[i-1])
            cells = [QRegion() for _ in row]
            for position, logical in enumerate(visual):
                left, right = math.floor(edges[position]), math.floor(edges[position+1])
                band_top, band_bottom = math.floor(top), math.floor(bottom)
                cells[logical] = QRegion(left, band_top, max(0, right-left),
                                        max(0, band_bottom-band_top))
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

    def sweep_masks(self, progress):
        """Pure media-time mask with the final cell handed to cue fade-out.

        Passed cells stay hidden, but the last cell of each language/row group
        remains visible until SubtitleLayer owns the cue-end fade.  This keeps
        erase-sweep presets on the same visible cue lifetime as effects-off and
        avoids a blank 220 ms fade after the sweep reaches 100%.
        """
        progress = min(1.0, max(0.0, progress))
        if not self._sweep_cells and self.rows:
            self._prepare_sweep()
        hidden, active = QRegion(), []
        for cells, prefix in zip(self._sweep_cells, self._sweep_prefix):
            if not cells:
                continue
            if progress >= 1:
                hidden = hidden.united(prefix[len(cells)-1])
                active.append((cells[-1], 1.0))
                continue
            position = progress * len(cells)
            index = min(len(cells)-1, int(position))
            local = min(1.0, position-index)
            hidden = hidden.united(prefix[index])
            # Smoothly dissolve the current word into its emitter; no hard blink.
            # The final cell is the visual hand-off to SubtitleLayer's existing
            # 220 ms fade-out, so do not dissolve it before the cue really ends.
            alpha = 1.0 if index == len(cells)-1 else 1-local*local*(3-2*local)
            active.append((cells[index], alpha))
        return hidden, active

    def targets(self, progress):
        result = []
        for track in self.tracks:
            position = min(1.0, max(0.0, progress)) * len(track)
            index = min(len(track)-1, int(position))
            region = track[index]
            local = min(1.0, position-index)
            visible_left, visible_right = region.rect.left(), region.rect.right()
            x = region.leading + (region.trailing-region.leading) * local
            result.append((region, local, min(visible_right, max(visible_left, x))))
        return result

    def morph_regions(self, progress, style, intensity):
        if style != 'shuriken' or progress <= 0 or progress >= 1:
            return []
        strength = {'gentle': .3, 'normal': .5, 'rich': .65}[intensity]
        return [(region.rect, 1-strength * math.sin(local*math.pi))
                for region, local, _ in self.targets(progress)]

    def paint(self, painter, progress, style, intensity, entry_progress=1.0, burst=False):
        self.last_draw_count = 0
        if (style == 'none' and not burst) or not self.rows:
            return
        progress = min(1.0, max(0.0, progress))
        # No particles remain at cue end; the renderer owns optional glyph hiding.
        envelope = min(1.0, progress*12, (1-progress)*12)
        if burst and entry_progress < 1:
            envelope = max(envelope, math.sin(entry_progress*math.pi))
        if envelope <= 0:
            return
        budget = {'gentle': 8, 'normal': 16, 'rich': MAX_PARTICLES}[intensity]
        targets = self.targets(progress)
        per_row = max(1, budget // len(targets))
        painter.save()
        painter.setClipRect(self.label.contentsRect(), Qt.ClipOperation.IntersectClip)
        painter.setPen(Qt.PenStyle.NoPen)
        for row_index, (region, local, front) in enumerate(targets):
            rect = region.rect
            size = min(12.0, max(3.5, rect.height() * .25))
            count = min(per_row, budget-self.last_draw_count)
            for i in range(count):
                seed = i * 2.399963 + row_index * 1.713
                age = progress * 18 + seed
                wave = math.sin(age)
                x = front + math.cos(seed) * size * (1 + i*.28)
                y = rect.center().y() + math.sin(seed+progress*9) * rect.height()*.28
                alpha = envelope * (.45 + .55*abs(wave))
                radius = size * (.35 + .35*abs(math.cos(age*.7)))
                color = QColor('#DBFFF4')
                shape = self.star
                angle = age * 45
                if style == 'shuriken':
                    shape = self.shuriken
                    color = QColor('#EDF3FF' if i % 2 == 0 else '#91A8FF')
                    if i == 0:
                        x, y = rect.center().x(), rect.center().y()
                        radius = min(rect.width()*.45, max(size*1.2, rect.height()*.5))
                        alpha = envelope * (.3 + .7*math.sin(local*math.pi))
                    angle = progress * 1440 + i*57
                elif style == 'comet':
                    x = front - i * size * .55 * (1 if region.trailing >= region.leading else -1)
                    y = rect.center().y() + math.sin(seed)*2
                    radius = size * max(.12, .8-i*.05)
                    alpha *= 1-i/(count+1)
                    color = QColor('#B2E8FF')
                elif style == 'fireflies':
                    shape = None
                    x = rect.left() + rect.width() * ((i*.618033 + progress*.3) % 1)
                    color = QColor('#B7FFD5')
                    radius *= .6
                elif style == 'snow':
                    x = rect.left() + rect.width() * ((i*.618033 + progress*.08) % 1)
                    y = rect.top() + rect.height() * ((i*.371 + progress*1.7) % 1)
                    color = QColor('#DBF6FF')
                    radius *= .65
                elif style == 'petals':
                    shape = self.petal
                    color = QColor('#FFB6D9' if i % 2 == 0 else '#D7BAFF')
                    x = rect.left() + rect.width() * ((i*.618033 + progress*.5) % 1)
                elif style == 'bubbles':
                    shape = None
                    color = QColor('#BCEAFF')
                    y = rect.bottom() - rect.height() * ((progress*2+i*.317) % 1)
                elif style == 'diamonds':
                    shape = self.diamond
                    color = QColor('#CDB8FF' if i % 2 else '#AFFFE8')
                elif style == 'ribbon':
                    shape = None
                    x = rect.left() + rect.width() * i / max(1, count-1)
                    y = rect.center().y() + math.sin(progress*math.pi*4+i*.6)*rect.height()*.2
                    color = QColor('#82E5DD' if i % 2 else '#CBADFF')
                    radius *= .55
                color.setAlphaF(min(1.0, max(0.0, alpha*.8)))
                painter.save()
                painter.translate(x, y)
                if shape is None:
                    if style == 'bubbles':
                        painter.setPen(QPen(color, 1))
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                    else:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(color)
                    painter.drawEllipse(QRectF(-radius, -radius, radius*2, radius*2))
                else:
                    painter.rotate(angle)
                    painter.scale(radius, radius)
                    painter.fillPath(shape, color)
                painter.restore()
                self.last_draw_count += 1
                if self.last_draw_count >= budget:
                    break
        painter.restore()
