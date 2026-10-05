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
        self._sweep_cells = []
        self._sweep_prefix = []
        self.last_draw_count = 0

    def prepare(self, duration_ms):
        key = (self.label.text(), self.label.font().key(),
               self.label.contentsRect().getRect(), duration_ms)
        if key != self.key:
            self.key = key
            self.rows = build_regions(self.label, duration_ms)
            self._sweep_cells, self._sweep_prefix = [], []

    def _prepare_sweep(self):
        # Partition the existing text viewport, including outline/shadow space.
        # Logical region order stays intact for RTL; physical cells never overlap,
        # so hiding an earlier word cannot redraw or dim a neighbouring cell.
        self._sweep_cells, self._sweep_prefix = [], []
        viewport = QRectF(self.label.contentsRect())
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
            prefix = [QRegion()]
            for cell in cells:
                prefix.append(prefix[-1].united(cell))
            self._sweep_cells.append(cells)
            self._sweep_prefix.append(prefix)

    def sweep_masks(self, progress):
        """Pure media-time mask: passed words stay hidden until a new cue/seek."""
        progress = min(1.0, max(0.0, progress))
        if not self._sweep_cells and self.rows:
            self._prepare_sweep()
        if progress >= 1:
            return QRegion(self.label.contentsRect()), []
        hidden, active = QRegion(), []
        for cells, prefix in zip(self._sweep_cells, self._sweep_prefix):
            position = progress * len(cells)
            index = min(len(cells)-1, int(position))
            local = min(1.0, position-index)
            hidden = hidden.united(prefix[index])
            # Smoothly dissolve the current word into its emitter; no hard blink.
            alpha = 1-local*local*(3-2*local)
            active.append((cells[index], alpha))
        return hidden, active

    def targets(self, progress):
        result = []
        for row in self.rows:
            position = min(1.0, max(0.0, progress)) * len(row)
            index = min(len(row)-1, int(position))
            region = row[index]
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
