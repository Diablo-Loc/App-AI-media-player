"""Bounded 2D kinetic typography from whole-shaped, cached glyphs."""
import math
import unicodedata
from typing import NamedTuple

from PySide6.QtCore import QRectF, Qt, QTextBoundaryFinder
from PySide6.QtGui import QTextLayout, QTextOption
from ui.subtitle_particles import word_units

KINETIC_ENTRANCES = (
    ('kinetic_drop', 'Mưa chữ · rơi mạnh'),
    ('kinetic_spring', 'Domino · bật nảy'),
    ('kinetic_scatter', 'Bung chữ từ nhiều hướng'),
    ('kinetic_vortex', 'Xoáy chữ vào câu'),
    ('kinetic_flip', 'Lật chữ điện ảnh · 2D'),
    ('kinetic_wave', 'Sóng chữ nối tiếp'),
    ('kinetic_type', 'Máy chữ · hiện từng cụm'),
    ('kinetic_slam', 'Nhịp chữ · phóng lớn'),
)
KINETIC_MODES = frozenset(key for key, _ in KINETIC_ENTRANCES)
STRENGTHS = (('gentle', 'Nhẹ'), ('normal', 'Rõ'), ('bold', 'Mạnh'))
PARTS = (('auto', 'Tự động'), ('word', 'Theo từ'), ('glyph', 'Theo cụm ký tự'))
MAX_TILES = 16


class Tile(NamedTuple):
    rect: QRectF
    center_x: float
    center_y: float


def _units(text, parts):
    # Keep cursive/RTL words shaped together, even when glyph mode is requested.
    if len(text) > 8192 or any(unicodedata.bidirectional(c) in ('R', 'AL') for c in text):
        return word_units(text)
    if parts == 'word' or (parts == 'auto' and len(text) > 32):
        return word_units(text)
    encoded = text.encode('utf-16-le', errors='surrogatepass')
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    result, start = [], 0
    end = finder.toNextBoundary()
    while end >= 0:
        cluster = encoded[start*2:end*2].decode('utf-16-le', errors='surrogatepass')
        if not cluster.isspace():
            result.append((start, end))
        start, end = end, finder.toNextBoundary()
    return result


def make_tiles(label, bounds, parts, duration_ms, limit=MAX_TILES):
    metrics, viewport = label.fontMetrics(), QRectF(label.contentsRect())
    lines = label.text().split('\n')
    spacing = metrics.lineSpacing()
    top = viewport.top() + (viewport.height()-spacing*len(lines))/2
    visible = []
    for index, text in enumerate(lines):
        y = top+index*spacing
        if text.strip() and QRectF(viewport.left(), y, viewport.width(), spacing).intersects(viewport):
            visible.append((text, y))
    if not visible:
        return []
    budget = max(1, min(MAX_TILES, limit, int(max(0, duration_ms)/30)))
    if len(visible) > budget:
        return [Tile(QRectF(bounds), bounds.center().x(), bounds.center().y())]
    result = []
    for row_index, (text, y) in enumerate(visible):
        units = _units(text, parts)
        if not units:
            continue
        allowance = max(1, (budget-len(result))//(len(visible)-row_index))
        chunk = max(1, math.ceil(len(units)/allowance))
        layout = QTextLayout(text, label.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(max(1, metrics.horizontalAdvance(text)))
        layout.endLayout()
        x = viewport.left()+(viewport.width()-metrics.horizontalAdvance(text))/2
        positions = []
        for offset in range(0, len(units), chunk):
            start, end = units[offset][0], units[min(len(units)-1, offset+chunk-1)][1]
            a, b = x+line.cursorToX(start)[0], x+line.cursorToX(end)[0]
            positions.append((min(a, b), max(a, b)))
        visual = sorted(range(len(positions)), key=lambda i: sum(positions[i])/2)
        edges = [bounds.left()]
        edges.extend(min(bounds.right(), max(bounds.left(), (positions[a][1]+positions[b][0])/2))
                     for a, b in zip(visual, visual[1:]))
        edges.append(bounds.right())
        for i in range(1, len(edges)):
            edges[i] = max(edges[i], edges[i-1])
        band_top = bounds.top() if row_index == 0 else (visible[row_index-1][1]+spacing+y)/2
        band_bottom = bounds.bottom() if row_index == len(visible)-1 else (y+spacing+visible[row_index+1][1])/2
        row = [None]*len(positions)
        for position, logical in enumerate(visual):
            left, right = edges[position], max(edges[position], edges[position+1])
            rect = QRectF(left, band_top, max(0, right-left), max(0, band_bottom-band_top))
            center = rect.center()
            row[logical] = Tile(rect, center.x(), center.y())
        result.extend(tile for tile in row if not tile.rect.isEmpty())
    return result


def _bounce(t):
    n, d = 7.5625, 2.75
    if t < 1/d:
        return n*t*t
    if t < 2/d:
        return n*(t-1.5/d)**2+.75
    if t < 2.5/d:
        return n*(t-2.25/d)**2+.9375
    return n*(t-2.625/d)**2+.984375


def motion(mode, phase, index, count, tile, bounds, strength):
    """Absolute entry phase only; no mutable physics or per-glyph animations."""
    if phase >= 1:
        return (0.0, 0.0, 1.0, 1.0, 0.0, 1.0)
    delay = (.82 if mode == 'kinetic_type' else .32)*index/max(1, count-1)
    t = min(1.0, max(0.0, (phase-delay)/(1-delay)))
    if t >= 1:
        return (0.0, 0.0, 1.0, 1.0, 0.0, 1.0)
    amount = {'gentle': .55, 'normal': 1.0, 'bold': 1.65}[strength]
    height = max(10.0, min(100.0, tile.rect.height()))
    travel = min(180.0, max(36.0, height*1.6))*amount
    eased = 1-(1-t)**3
    remain = 1-eased
    dx = dy = angle = 0.0
    sx = sy = 1.0
    alpha = min(1.0, t*5)
    side = -1 if index % 2 else 1
    if mode == 'kinetic_drop':
        dy = -travel*(1-_bounce(t))
        angle = side*18*amount*remain
    elif mode == 'kinetic_spring':
        spring = math.exp(-6*t)*math.cos(t*math.pi*3.5)
        dy = travel*spring
        sx = sy = max(.3, 1-.35*amount*spring)
        angle = side*12*amount*remain
    elif mode == 'kinetic_scatter':
        dx = ((tile.center_x-bounds.center().x())*.7+side*travel)*remain
        dy = (tile.center_y-bounds.center().y()-travel)*remain
        angle = side*85*amount*remain
        sx = sy = .45+.55*eased
    elif mode == 'kinetic_vortex':
        theta = remain*math.pi*1.4*amount
        vx, vy = tile.center_x-bounds.center().x(), tile.center_y-bounds.center().y()
        radius = 1+remain*.8
        dx = (vx*math.cos(theta)-vy*math.sin(theta))*radius-vx
        dy = (vx*math.sin(theta)+vy*math.cos(theta))*radius-vy-travel*.3*remain
        angle = math.degrees(theta)
        sx = sy = .65+.35*eased
    elif mode == 'kinetic_flip':
        # Avoid an almost singular raster transform while keeping a clear flip.
        sy = max(.12, math.cos((1-t)*math.pi/2))
        dy = -travel*.35*remain
        angle = side*10*amount*remain
    elif mode == 'kinetic_wave':
        dy = -travel*.65*remain*math.cos(t*math.pi*2)
        angle = 18*amount*remain*math.sin(index*.8+t*math.pi*2)
    elif mode == 'kinetic_type':
        dy = height*.3*amount*remain
        alpha = min(1.0, t*7)
    elif mode == 'kinetic_slam':
        overshoot = 1+2.7*(t-1)**3+1.7*(t-1)**2
        sx = sy = max(.5, 1+1.1*amount*(1-overshoot))
        dy = height*.12*remain*math.sin(t*math.pi*5)
    return dx, dy, sx, sy, angle, alpha


class KineticPainter:
    """A cached <=16-cell plan; reuse the existing glyph sprite with clipping."""
    def __init__(self, label):
        self.label = label
        self.key = None
        self.tiles = []
        self.last_draw_count = 0

    def clear(self):
        self.key, self.tiles, self.last_draw_count = None, [], 0

    def paint(self, painter, sprite, origin, mode, progress, strength, parts, duration_ms, draw_glyphs,
              limit=MAX_TILES):
        self.last_draw_count = 0
        if sprite is None or progress >= 1 or duration_ms < 80:
            return False
        bounds = QRectF(origin.x(), origin.y(), sprite.width()/sprite.devicePixelRatio(),
                        sprite.height()/sprite.devicePixelRatio())
        key = (self.label.text(), self.label.font().key(), self.label.contentsRect().getRect(),
               bounds.getRect(), parts, duration_ms, limit)
        if key != self.key:
            self.key = key
            self.tiles = make_tiles(self.label, bounds, parts, duration_ms, limit)
        if not self.tiles:
            return False
        for index, tile in enumerate(self.tiles):
            dx, dy, sx, sy, angle, alpha = motion(mode, progress, index, len(self.tiles),
                                                 tile, bounds, strength)
            if alpha <= 0:
                continue
            painter.save()
            painter.translate(tile.center_x+dx, tile.center_y+dy)
            painter.rotate(angle)
            painter.scale(sx, sy)
            painter.translate(-tile.center_x, -tile.center_y)
            painter.setClipRect(tile.rect, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(painter.opacity()*alpha)
            draw_glyphs(tile.rect)
            painter.restore()
            self.last_draw_count += 1
        return True
