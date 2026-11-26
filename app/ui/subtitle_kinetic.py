"""Bounded 2D kinetic typography from whole-shaped, cached glyphs."""
import math
import unicodedata
from typing import NamedTuple

from PySide6.QtCore import QRectF, Qt, QTextBoundaryFinder
from PySide6.QtGui import QColor, QTextLayout, QTextOption
from ui.subtitle_particles import word_units
from ui.subtitle_studio import iter_visual_lines
from ui.subtitle_vfx import _draw_four_point_star

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
PER_CHAR_MODES = frozenset({
    'vfx_beat_char_pop',
    'vfx_char_orbit_snap',
    'vfx_char_cascade_drop',
})
EDITOR_KINETIC_MODES = frozenset({
    'editor_pop',
    'editor_wave',
    'editor_shatter_rebirth',
    'editor_tornado_magnet',
    'editor_trampoline',
    'editor_flip_cascade',
    'editor_matrix_decode',
    'vfx_beat_char_pop',
    'vfx_char_orbit_snap',
    'vfx_char_cascade_drop',
    'vfx_scatter_leap',
    'vfx_supernova_shatter',
    'vfx_blackhole_warp',
    'vfx_magnet_assemble',
    'vfx_cyclone_sweep',
    'vfx_firework_bloom',
    'vfx_glass_shatter',
    'vfx_elastic_bounce_pro',
    'vfx_3d_domino_flip',
    'vfx_liquid_fire',
})
CHOREO_EXIT_MODES = frozenset({
    'editor_shatter_rebirth',
    'editor_tornado_magnet',
    'editor_trampoline',
    'editor_flip_cascade',
    'editor_katana_slice',
    'vfx_beat_char_pop',
    'vfx_char_orbit_snap',
    'vfx_char_cascade_drop',
    'vfx_scatter_leap',
    'vfx_supernova_shatter',
    'vfx_saber_slash',
    'vfx_cyber_glitch_pro',
    'vfx_blackhole_warp',
    'vfx_magnet_assemble',
    'vfx_cyclone_sweep',
    'vfx_firework_bloom',
    'vfx_glass_shatter',
    'vfx_elastic_bounce_pro',
    'vfx_3d_domino_flip',
    'vfx_liquid_fire',
})
STRENGTHS = (('gentle', 'Nhẹ'), ('normal', 'Rõ'), ('bold', 'Mạnh'))
PARTS = (('auto', 'Tự động'), ('word', 'Theo từ'), ('glyph', 'Theo cụm ký tự'))
MAX_TILES = 16
MAX_CHAR_TILES = 96


class Tile(NamedTuple):
    rect: QRectF
    center_x: float
    center_y: float


class CharTile(NamedTuple):
    rect: QRectF
    center_x: float
    center_y: float
    row_index: int
    col_index: int
    row_count: int
    char_index: int


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
        cluster = encoded[start * 2:end * 2].decode('utf-16-le', errors='surrogatepass')
        if not cluster.isspace():
            result.append((start, end))
        start, end = end, finder.toNextBoundary()
    return result


def make_tiles(label, bounds, parts, duration_ms, limit=MAX_TILES):
    viewport = QRectF(label.contentsRect())
    visual_lines = iter_visual_lines(label)
    visible = []
    for vline in visual_lines:
        if vline.text and vline.text.strip():
            line_band = QRectF(viewport.left(), vline.y_top, viewport.width(), vline.line_height)
            if line_band.intersects(viewport):
                visible.append((vline.text, vline.y_top, vline.line_height, vline.font, vline.x, vline.width))
    if not visible:
        return []
    budget = max(1, min(MAX_TILES, limit, int(max(0, duration_ms) / 30)))
    if len(visible) > budget:
        return [Tile(QRectF(bounds), bounds.center().x(), bounds.center().y())]
    result = []
    for row_index, (text, y, spacing, line_font, x, adv) in enumerate(visible):
        units = _units(text, parts)
        if not units:
            continue
        allowance = max(1, (budget - len(result)) // (len(visible) - row_index))
        chunk = max(1, math.ceil(len(units) / allowance))
        layout = QTextLayout(text, line_font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(max(1.0, adv))
        layout.endLayout()
        positions = []
        for offset in range(0, len(units), chunk):
            start, end = units[offset][0], units[min(len(units) - 1, offset + chunk - 1)][1]
            a, b = x + line.cursorToX(start)[0], x + line.cursorToX(end)[0]
            positions.append((min(a, b), max(a, b)))
        visual = sorted(range(len(positions)), key=lambda i: sum(positions[i]) / 2)
        edges = [bounds.left()]
        edges.extend(min(bounds.right(), max(bounds.left(), (positions[a][1] + positions[b][0]) / 2))
                     for a, b in zip(visual, visual[1:]))
        edges.append(bounds.right())
        for i in range(1, len(edges)):
            edges[i] = max(edges[i], edges[i - 1])
        band_top = bounds.top() if row_index == 0 else (visible[row_index - 1][1] + visible[row_index - 1][2] + y) / 2
        band_bottom = bounds.bottom() if row_index == len(visible) - 1 else (y + spacing + visible[row_index + 1][1]) / 2
        row = [None] * len(positions)
        for position, logical in enumerate(visual):
            left, right = edges[position], max(edges[position], edges[position + 1])
            rect = QRectF(left, band_top, max(0, right - left), max(0, band_bottom - band_top))
            center = rect.center()
            row[logical] = Tile(rect, center.x(), center.y())
        result.extend(tile for tile in row if not tile.rect.isEmpty())
    return result


def make_char_tiles(label, bounds, max_chars=MAX_CHAR_TILES):
    """Slice whole-shaped subtitle lines into individual UTF-16 grapheme tiles (preserving Vietnamese accents)."""
    viewport = QRectF(label.contentsRect())
    visual_lines = iter_visual_lines(label)
    visible = []
    for vline in visual_lines:
        if vline.text and vline.text.strip():
            line_band = QRectF(viewport.left(), vline.y_top, viewport.width(), vline.line_height)
            if line_band.intersects(viewport):
                visible.append((vline.text, vline.y_top, vline.line_height, vline.font, vline.x, vline.width))
    if not visible:
        return []
    row_units = [_units(text, 'glyph') for text, *_ in visible]
    total_units = sum(len(u) for u in row_units)
    if total_units <= 0:
        return []
    cap = max(16, int(max_chars))
    chunk = max(1, math.ceil(total_units / cap))

    result = []
    char_idx = 0
    for row_index, ((text, y, spacing, line_font, x, adv), units) in enumerate(zip(visible, row_units)):
        if not units:
            continue
        layout = QTextLayout(text, line_font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        layout.setTextOption(option)
        layout.beginLayout()
        line = layout.createLine()
        line.setLineWidth(max(1.0, adv))
        layout.endLayout()

        positions = []
        for offset in range(0, len(units), chunk):
            start, end = units[offset][0], units[min(len(units) - 1, offset + chunk - 1)][1]
            a, b = x + line.cursorToX(start)[0], x + line.cursorToX(end)[0]
            positions.append((min(a, b), max(a, b)))
        if not positions:
            continue

        visual = sorted(range(len(positions)), key=lambda i: (positions[i][0] + positions[i][1]) * 0.5)
        pad_lr = 18.0
        first_l = max(bounds.left(), positions[visual[0]][0] - pad_lr)
        last_r = min(bounds.right(), positions[visual[-1]][1] + pad_lr)
        edges = [first_l]
        edges.extend(
            min(bounds.right(), max(bounds.left(), (positions[a][1] + positions[b][0]) * 0.5))
            for a, b in zip(visual, visual[1:])
        )
        edges.append(last_r)
        for i in range(1, len(edges)):
            edges[i] = max(edges[i], edges[i - 1])

        band_top = bounds.top() if row_index == 0 else (visible[row_index - 1][1] + visible[row_index - 1][2] + y) * 0.5
        band_bottom = bounds.bottom() if row_index == len(visible) - 1 else (y + spacing + visible[row_index + 1][1]) * 0.5
        cy = y + spacing * 0.5

        row_tiles = [None] * len(positions)
        for pos_i, logical in enumerate(visual):
            left, right = edges[pos_i], max(edges[pos_i], edges[pos_i + 1])
            rect = QRectF(left, band_top, max(0.0, right - left), max(0.0, band_bottom - band_top))
            gl, gr = positions[logical]
            cx = (gl + gr) * 0.5
            row_tiles[logical] = (rect, cx, cy)

        valid = [item for item in row_tiles if item is not None and not item[0].isEmpty()]
        row_count = len(valid)
        for col_index, (rect, cx, cy_val) in enumerate(valid):
            result.append(CharTile(rect, cx, cy_val, row_index, col_index, row_count, char_idx))
            char_idx += 1
    return result


def _per_char_exit_motion(mode, out_phase, tile, total, bounds):
    """Sequential per-character launch outward: A -> N -> H -> V -> A -> N firing one-by-one."""
    p = min(1.0, max(0.0, float(out_phase)))
    row_i = getattr(tile, 'row_index', 0)
    col_i = getattr(tile, 'col_index', 0)
    row_n = max(1, getattr(tile, 'row_count', total))
    c_idx = getattr(tile, 'char_index', col_i)
    row_norm = col_i / max(1, row_n - 1)
    # Fixed per-char launch window so characters peel off sequentially in a crisp visible wave
    char_win = 0.42
    row_off = min(0.08, row_i * 0.04)
    delay = row_off + (1.0 - char_win - row_off) * row_norm
    lp = min(1.0, max(0.0, (p - delay) / char_win))
    if lp <= 0.0:
        return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0
    le = lp * lp * (1.65 - 0.65 * lp)
    side = -1.0 if (c_idx % 2 == 0) else 1.0

    if mode == 'vfx_char_orbit_snap':
        ang = c_idx * 1.92 + row_i * 0.85 + lp * 2.1 * side
        rad = (66.0 + (c_idx % 4) * 16.0) * le
        dx = math.cos(ang) * rad * 1.25
        dy = math.sin(ang) * rad * 0.65 - 12.0 * lp
        sx = sy = max(0.20, 1.0 - 0.72 * le)
        return dx, dy, sx, sy, side * 125.0 * le, max(0.0, 1.0 - (lp ** 1.45))

    if mode == 'vfx_char_cascade_drop':
        dx = side * (16.0 + (c_idx % 4) * 10.0) * le
        dy = -22.0 * math.sin(lp * math.pi * 0.55) + 78.0 * (lp * lp)
        sx = max(0.42, 1.0 - 0.35 * le)
        sy = max(0.35, 1.0 + 0.20 * lp - 0.55 * le)
        return dx, dy, sx, sy, side * (48.0 + (c_idx % 3) * 22.0) * le, max(0.0, 1.0 - (lp ** 1.5))

    # vfx_beat_char_pop: sequential kinetic fireworks outward per character with spin & gravity
    ang = c_idx * 2.399963 + row_i * 1.15 + 1.25
    rad = (74.0 + (c_idx % 5) * 16.0) * le
    dx = math.cos(ang) * rad * 1.18
    dy = (math.sin(ang) * rad * 0.58 - 18.0 * lp) + 38.0 * (lp * lp)
    angle = side * (72.0 + (c_idx % 4) * 26.0) * le
    sx = sy = max(0.22, 1.0 - 0.68 * le)
    return dx, dy, sx, sy, angle, max(0.0, 1.0 - (lp ** 1.55))


def _per_char_enter_motion(mode, phase, tile, total, bounds):
    """Beat-synced per-character entrance: A -> N -> H -> V -> A -> N assembling letter-by-letter."""
    if phase >= 1.0:
        return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
    row_i = getattr(tile, 'row_index', 0)
    col_i = getattr(tile, 'col_index', 0)
    row_n = max(1, getattr(tile, 'row_count', total))
    c_idx = getattr(tile, 'char_index', col_i)
    row_norm = col_i / max(1, row_n - 1)
    # Crisp fixed per-char flight window (0.34) so early letters land & lock while later letters fly in!
    base_p = max(0.0, (phase - 0.04) / 0.96)
    char_win = 0.34
    row_off = min(0.10, row_i * 0.05)
    delay = row_off + (1.0 - char_win - row_off) * row_norm
    t = min(1.0, max(0.0, (base_p - delay) / char_win))
    if t <= 0.0:
        return 0.0, 0.0, 0.3, 0.3, 0.0, 0.0, 0.0
    if t >= 1.0:
        return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0

    rem = (1.0 - t) ** 2.6
    side = -1.0 if (c_idx % 2 == 0) else 1.0

    if mode == 'vfx_char_orbit_snap':
        theta = rem * math.pi * 1.45 * side + c_idx * 0.55
        rad = (52.0 + (c_idx % 4) * 14.0) * rem
        dx = math.cos(theta) * rad * 1.20
        dy = math.sin(theta) * rad * 0.66
        pop = 1.0 + 0.17 * math.exp(-5.8 * t) * math.sin(t * math.pi * 2.6)
        sc = max(0.24, (0.36 + 0.64 * (1.0 - rem)) * pop)
        return dx, dy, sc, sc, side * 92.0 * rem, min(1.0, t * 5.2), t

    if mode == 'vfx_char_cascade_drop':
        drop_h = 68.0 + (c_idx % 5) * 11.0
        b = _bounce(t)
        dx = side * (16.0 + (c_idx % 3) * 10.0) * rem
        dy = -drop_h * (1.0 - b)
        impact = math.exp(-5.0 * t) * math.cos(t * math.pi * 3.0)
        sx = max(0.40, 1.0 + 0.22 * impact)
        sy = max(0.40, 1.0 - 0.18 * impact)
        return dx, dy, sx, sy, side * 34.0 * rem, min(1.0, t * 5.5), t

    # vfx_beat_char_pop: multi-directional flight + rotation + elastic bounce into exact seat
    ang = c_idx * 2.399963 + row_i * 1.35 + 0.42
    dist = 60.0 + (c_idx % 5) * 13.0
    dx = math.cos(ang) * dist * 1.15 * rem
    dy = math.sin(ang) * dist * 0.65 * rem - 10.0 * math.sin(t * math.pi) * (1.0 - t)
    spring = math.exp(-5.2 * t) * math.cos(t * math.pi * 2.7)
    settle = min(1.0, t * 2.5)
    sx = max(0.28, 1.0 - 0.52 * rem + 0.22 * spring * settle)
    sy = max(0.28, 1.0 - 0.52 * rem - 0.18 * spring * settle)
    angle = side * (60.0 + (c_idx % 4) * 24.0) * rem
    return dx, dy, sx, sy, angle, min(1.0, t * 5.6), t


def _bounce(t):
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        return n * (t - 1.5 / d) ** 2 + .75
    if t < 2.5 / d:
        return n * (t - 2.25 / d) ** 2 + .9375
    return n * (t - 2.625 / d) ** 2 + .984375


def motion(mode, phase, index, count, tile, bounds, strength):
    """Absolute entry phase only; no mutable physics or per-glyph animations."""
    if phase >= 1:
        return (0.0, 0.0, 1.0, 1.0, 0.0, 1.0)
    delay = (.82 if mode == 'kinetic_type' else .32) * index / max(1, count - 1)
    t = min(1.0, max(0.0, (phase - delay) / (1 - delay)))
    if t >= 1:
        return (0.0, 0.0, 1.0, 1.0, 0.0, 1.0)
    amount = {'gentle': .55, 'normal': 1.0, 'bold': 1.65}[strength]
    height = max(10.0, min(100.0, tile.rect.height()))
    travel = min(180.0, max(36.0, height * 1.6)) * amount
    eased = 1 - (1 - t) ** 3
    remain = 1 - eased
    dx = dy = angle = 0.0
    sx = sy = 1.0
    alpha = min(1.0, t * 5)
    side = -1 if index % 2 else 1
    if mode == 'kinetic_drop':
        dy = -travel * (1 - _bounce(t))
        angle = side * 18 * amount * remain
    elif mode == 'kinetic_spring':
        spring = math.exp(-6 * t) * math.cos(t * math.pi * 3.5)
        dy = travel * spring
        sx = sy = max(.3, 1 - .35 * amount * spring)
        angle = side * 12 * amount * remain
    elif mode == 'kinetic_scatter':
        dx = ((tile.center_x - bounds.center().x()) * .7 + side * travel) * remain
        dy = (tile.center_y - bounds.center().y() - travel) * remain
        angle = side * 85 * amount * remain
        sx = sy = .45 + .55 * eased
    elif mode == 'kinetic_vortex':
        theta = remain * math.pi * 1.4 * amount
        vx, vy = tile.center_x - bounds.center().x(), tile.center_y - bounds.center().y()
        radius = 1 + remain * .8
        dx = (vx * math.cos(theta) - vy * math.sin(theta)) * radius - vx
        dy = (vx * math.sin(theta) + vy * math.cos(theta)) * radius - vy - travel * .3 * remain
        angle = math.degrees(theta)
        sx = sy = .65 + .35 * eased
    elif mode == 'kinetic_flip':
        sy = max(.12, math.cos((1 - t) * math.pi / 2))
        dy = -travel * .35 * remain
        angle = side * 10 * amount * remain
    elif mode == 'kinetic_wave':
        dy = -travel * .65 * remain * math.cos(t * math.pi * 2)
        angle = 18 * amount * remain * math.sin(index * .8 + t * math.pi * 2)
    elif mode == 'kinetic_type':
        dy = height * .3 * amount * remain
        alpha = min(1.0, t * 7)
    elif mode == 'kinetic_slam':
        overshoot = 1 + 2.7 * (t - 1) ** 3 + 1.7 * (t - 1) ** 2
        sx = sy = max(.5, 1 + 1.1 * amount * (1 - overshoot))
        dy = height * .12 * remain * math.sin(t * math.pi * 5)
    return dx, dy, sx, sy, angle, alpha


def _editor_exit_motion(mode, out_phase, index, count, tile, bounds):
    """Physics explosion / exit choreography for outgoing cue shards."""
    p = min(1.0, max(0.0, float(out_phase)))
    if p <= 0.0:
        return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0
    ease = 1.0 - (1.0 - p) ** 2
    side = -1.0 if index % 2 == 0 else 1.0
    if mode == 'vfx_scatter_leap':
        # Signature scatter explosion: words blast outward in every direction with spin & gravity arc
        ang = index * 2.399963 + 0.45
        radial = 46.0 + (index % 4) * 18.0
        cx_spread = (tile.center_x - bounds.center().x()) * 0.46 * ease if bounds is not None else 0.0
        dx = math.cos(ang) * radial * 1.55 * ease + cx_spread
        dy = (math.sin(ang) * radial * 0.55 - 30.0) * p + 62.0 * p * p
        angle = side * (48.0 + (index % 3) * 28.0) * ease
        sx = sy = max(0.28, 1.0 - 0.58 * ease)
        alpha = max(0.0, 1.0 - (p ** 1.65))
        return dx, dy, sx, sy, angle, alpha
    if mode == 'vfx_magnet_assemble':
        # Snap apart cleanly along 4 alternating cardinal/diagonal rails
        dir_x = (-1.0, 1.0, -0.65, 0.65)[index % 4]
        dir_y = (-0.55, 0.55, 0.85, -0.85)[index % 4]
        dx = dir_x * (58.0 + (index % 3) * 18.0) * ease
        dy = dir_y * 34.0 * ease
        sx = sy = max(0.32, 1.0 - 0.52 * ease)
        return dx, dy, sx, sy, side * 12.0 * ease, max(0.0, 1.0 - (p ** 1.5))
    if mode == 'vfx_cyclone_sweep':
        # Rightmost words peel away first on the wind gust so trailing words never cross over
        rev = max(0, count - 1 - index)
        delay = 0.28 * rev / max(1, count - 1)
        lp = min(1.0, max(0.0, (p - delay) / max(0.20, 1.0 - delay)))
        le = lp * lp
        dx = (115.0 + (index % 3) * 18.0) * le
        dy = -24.0 * math.sin(lp * math.pi * 0.85) - 10.0 * le
        return dx, dy, max(0.45, 1.0 - 0.42 * le), max(0.55, 1.0 - 0.32 * le), 18.0 * le, max(0.0, 1.0 - (lp ** 1.4))
    if mode == 'vfx_firework_bloom':
        # Words bloom outward like firework petals with soft deceleration
        ang = index * (2.0 * math.pi / max(1, count)) + 0.35
        vx = (tile.center_x - bounds.center().x()) if bounds is not None else 0.0
        dx = math.cos(ang) * 64.0 * ease + vx * 0.30 * ease
        dy = math.sin(ang) * 34.0 * ease - 18.0 * ease + 24.0 * p * p
        sx = sy = max(0.22, 1.0 - 0.68 * ease)
        return dx, dy, sx, sy, side * 32.0 * ease, max(0.0, 1.0 - (p ** 1.7))
    if mode == 'vfx_glass_shatter':
        # Fracture into sharp tilted glass shards shearing & dropping down
        ang = index * 1.9 + 0.4
        dx = side * (22.0 + (index % 4) * 14.0) * ease + math.cos(ang) * 18.0 * ease
        dy = 48.0 * (p * p) + (index % 3 - 1) * 10.0 * ease
        sx = max(0.30, 1.0 - 0.45 * ease)
        sy = max(0.25, 1.0 - 0.55 * ease)
        return dx, dy, sx, sy, side * (26.0 + (index % 3) * 14.0) * ease, max(0.0, 1.0 - (p ** 1.6))
    if mode in ('editor_shatter_rebirth', 'vfx_supernova_shatter'):
        ang = index * 2.399963 + 0.65
        radial = 34.0 + (index % 4) * 14.0
        cx_spread = (tile.center_x - bounds.center().x()) * 0.34 * ease if bounds is not None else 0.0
        dx = math.cos(ang) * radial * 1.45 * ease + cx_spread
        dy = (math.sin(ang) * radial * 0.62 - 22.0) * p + 48.0 * p * p
        angle = side * (38.0 + (index % 3) * 24.0) * ease
        sx = sy = max(0.24, 1.0 - 0.66 * ease)
        alpha = max(0.0, (1.0 - p) ** 1.35)
        return dx, dy, sx, sy, angle, alpha
    if mode in ('editor_tornado_magnet', 'vfx_blackhole_warp'):
        if mode == 'vfx_blackhole_warp':
            # Elliptical accretion-disk vortex pulling inner words slightly ahead of outer words (zero bottom clipping!)
            vx = (tile.center_x - bounds.center().x()) if bounds is not None else 0.0
            vy = (tile.center_y - bounds.center().y()) if bounds is not None else 0.0
            half_w = max(40.0, (bounds.width() * 0.5) if bounds is not None else 160.0)
            dist_norm = min(1.0, abs(vx) / half_w)
            # Inner words enter the event horizon slightly earlier -> graceful curved galaxy spiral arm
            local_p = min(1.0, max(0.0, (p - dist_norm * 0.14) / max(0.15, 1.0 - dist_norm * 0.14)))
            pull = local_p * local_p * (1.85 - 0.85 * local_p)
            theta = pull * math.pi * (1.45 - 0.35 * dist_norm)
            shrink = max(0.04, 1.0 - 0.96 * pull)
            # Compress vertical orbital swing to match the horizontal accretion disk (0.28) so lyrics never clip the bottom edge
            rx = (vx * math.cos(theta) - vy * math.sin(theta)) * shrink
            ry = (vx * math.sin(theta) * 0.26 + vy * math.cos(theta)) * shrink
            dx = rx - vx
            dy = ry - vy
            alpha = max(0.0, 1.0 - (local_p ** 2.3))
            return dx, dy, shrink, shrink, math.degrees(theta) * 0.38, alpha
        theta = ease * math.pi * 0.72 * side
        vx = (tile.center_x - bounds.center().x()) if bounds is not None else 0.0
        vy = (tile.center_y - bounds.center().y()) if bounds is not None else 0.0
        rad = 1.0 + 0.32 * ease
        dx = (vx * math.cos(theta) - vy * math.sin(theta)) * rad - vx
        dy = (vx * math.sin(theta) + vy * math.cos(theta)) * rad - vy - 14.0 * ease
        angle = math.degrees(theta) * 0.45
        sx = sy = max(0.34, 1.0 - 0.52 * ease)
        alpha = max(0.0, (1.0 - p) ** 1.3)
        return dx, dy, sx, sy, angle, alpha
    if mode in ('editor_trampoline', 'vfx_elastic_bounce_pro'):
        cx_spread = (tile.center_x - bounds.center().x()) * 0.14 * ease if bounds is not None else 0.0
        dy = -16.0 * math.sin(p * math.pi * 0.6) + 48.0 * p * p
        sx = max(0.55, 1.0 - 0.20 * ease)
        sy = 1.0 + 0.25 * p
        return cx_spread, dy, sx, sy, side * 8.0 * ease, max(0.0, (1.0 - p) ** 1.35)
    if mode == 'vfx_liquid_fire':
        # Evaporate upward like rising flame wisps
        dx = math.sin(p * 8.0 + index * 1.3) * 14.0 * ease
        dy = -38.0 * ease - 10.0 * (index % 3) * ease
        return dx, dy, max(0.35, 1.0 - 0.45 * ease), 1.0 + 0.35 * ease, side * 10.0 * ease, max(0.0, (1.0 - p) ** 1.3)
    # editor_flip_cascade / vfx_3d_domino_flip & fallback
    return 0.0, -14.0 * p, max(0.12, math.cos(p * math.pi * 0.5)), max(0.75, 1.0 - 0.15 * p), side * 6.0 * p, max(0.0, 1.0 - p)


def _editor_motion(mode, phase, index, count, tile=None, bounds=None):
    """Authentic CapCut/AE/Aegisub word-cascade physics with snappy spring overshoot."""
    if phase >= 1.0:
        return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
    if mode == 'vfx_scatter_leap':
        # Next cue leaps upward from below in a playful staggered arc and snaps cleanly into place!
        base_phase = max(0.0, (phase - 0.12) / 0.88)
        delay = 0.36 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (base_phase - delay) / max(0.05, 1.0 - delay)))
        if t <= 0.0:
            return 0.0, 38.0, 0.5, 0.5, 0.0, 0.0, 0.0
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        rem = (1.0 - t) ** 2.6
        side = -1.0 if index % 2 == 0 else 1.0
        dx = side * (20.0 + (index % 3) * 10.0) * rem
        # Leap upward above target line then settle with crisp elastic hop
        arc = math.sin(min(1.0, t * 1.15) * math.pi) * (1.0 - t) * 28.0
        dy = 36.0 * rem - arc
        squash = math.exp(-5.4 * t) * math.cos(t * math.pi * 2.8)
        sx = max(0.45, 1.0 + 0.18 * squash)
        sy = max(0.45, 1.0 - 0.14 * squash)
        angle = side * 16.0 * rem
        return dx, dy, sx, sy, angle, min(1.0, t * 4.8), t
    if mode == 'vfx_magnet_assemble':
        # Words rocket inward from 4 directions and click into magnetic alignment
        base_phase = max(0.0, (phase - 0.10) / 0.90)
        delay = 0.32 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (base_phase - delay) / max(0.05, 1.0 - delay)))
        if t <= 0.0:
            return 0.0, 0.0, 0.4, 0.4, 0.0, 0.0, 0.0
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        rem = (1.0 - t) ** 3.2
        dir_x = (-1.0, 1.0, -0.7, 0.7)[index % 4]
        dir_y = (-0.5, 0.5, 0.75, -0.75)[index % 4]
        snap = math.exp(-7.0 * t) * math.sin(t * math.pi * 2.5) * 4.0
        dx = dir_x * 68.0 * rem + snap * dir_x
        dy = dir_y * 32.0 * rem
        scale = 0.55 + 0.45 * (1.0 - rem)
        return dx, dy, scale, scale, dir_x * 10.0 * rem, min(1.0, t * 5.0), t
    if mode == 'vfx_cyclone_sweep':
        # Rightmost words lead from the left so the line unfurls smoothly without crossing
        base_phase = max(0.0, (phase - 0.08) / 0.92)
        rev = max(0, count - 1 - index)
        delay = 0.36 * rev / max(1, count - 1)
        t = min(1.0, max(0.0, (base_phase - delay) / max(0.05, 1.0 - delay)))
        if t <= 0.0:
            return -84.0, 12.0, 0.7, 0.7, -14.0, 0.0, 0.0
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        rem = (1.0 - t) ** 3.4
        dx = -88.0 * rem
        dy = 14.0 * rem - 10.0 * math.sin(t * math.pi) * (1.0 - t)
        angle = -15.0 * rem
        scale = 0.78 + 0.22 * (1.0 - rem)
        return dx, dy, scale, scale, angle, min(1.0, t * 4.5), t
    if mode == 'vfx_firework_bloom':
        # Blossom outward from center with springy bounce into place
        base_phase = max(0.0, (phase - 0.12) / 0.88)
        delay = 0.30 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (base_phase - delay) / max(0.05, 1.0 - delay)))
        if t <= 0.0:
            return 0.0, 0.0, 0.25, 0.25, 0.0, 0.0, 0.0
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        ease = 1.0 - (1.0 - t) ** 3.2
        rem = 1.0 - ease
        vx = (tile.center_x - bounds.center().x()) if (tile is not None and bounds is not None) else 0.0
        vy = (tile.center_y - bounds.center().y()) if (tile is not None and bounds is not None) else 0.0
        pop = 1.0 + 0.16 * math.exp(-5.0 * t) * math.sin(t * math.pi * 2.2)
        dx = -vx * 0.72 * rem
        dy = -vy * 0.72 * rem - 16.0 * math.sin(t * math.pi) * rem
        scale = max(0.22, (0.28 + 0.72 * ease) * pop)
        return dx, dy, scale, scale, (-1.0 if index % 2 == 0 else 1.0) * 20.0 * rem, min(1.0, t * 5.0), t
    if mode == 'vfx_glass_shatter':
        # Tilted glass shards rotate & fuse sharply back onto the flat subtitle plane
        base_phase = max(0.0, (phase - 0.10) / 0.90)
        delay = 0.34 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (base_phase - delay) / max(0.05, 1.0 - delay)))
        if t <= 0.0:
            return 0.0, -24.0, 0.35, 0.2, 22.0, 0.0, 0.0
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        rem = (1.0 - t) ** 3.0
        side = -1.0 if index % 2 == 0 else 1.0
        dx = side * (24.0 + (index % 3) * 12.0) * rem
        dy = (-22.0 if index % 2 == 0 else 22.0) * rem
        sx = max(0.28, 1.0 - 0.45 * rem)
        sy = max(0.18, math.cos(rem * math.pi * 0.44))
        angle = side * 26.0 * rem
        return dx, dy, sx, sy, angle, min(1.0, t * 4.8), t
    if mode in ('editor_shatter_rebirth', 'vfx_supernova_shatter'):
        base_phase = max(0.0, (phase - 0.12) / 0.88)
        delay = 0.34 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (base_phase - delay) / max(0.05, 1.0 - delay)))
        if t <= 0.0:
            return 0.0, 0.0, 0.4, 0.4, 0.0, 0.0, 0.0
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        ang = index * 2.399963 + 2.1
        rad_in = 34.0 + (index % 3) * 14.0
        scatter_rem = (1.0 - min(1.0, t * 1.35)) ** 2
        off_cx = (tile.center_x - bounds.center().x()) * 0.36 if (tile is not None and bounds is not None) else 0.0
        dx = (math.cos(ang) * rad_in + off_cx) * scatter_rem
        elastic_hop = abs(math.cos(t * math.pi * 2.5)) * math.exp(-4.4 * t)
        dy = (math.sin(ang) * rad_in * 0.52 - 16.0) * scatter_rem - 24.0 * elastic_hop
        angle = (-1.0 if index % 2 == 0 else 1.0) * 44.0 * scatter_rem
        squash = math.exp(-4.8 * t) * math.cos(t * math.pi * 3.0)
        sx = max(0.35, 1.0 + 0.16 * squash)
        sy = max(0.35, 1.0 - 0.12 * squash)
        return dx, dy, sx, sy, angle, min(1.0, t * 4.5), t
    if mode in ('editor_tornado_magnet', 'vfx_blackhole_warp'):
        base_phase = max(0.0, (phase - 0.10) / 0.90)
        delay = 0.38 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (base_phase - delay) / max(0.05, 1.0 - delay)))
        if t <= 0.0:
            return 0.0, 0.0, 0.35, 0.35, 0.0, 0.0, 0.0
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        ease_in = 1.0 - (1.0 - t) ** 4
        rem = 1.0 - ease_in
        vx = (tile.center_x - bounds.center().x()) if (tile is not None and bounds is not None) else ((index - count / 2.0) * 24.0)
        vy = (tile.center_y - bounds.center().y()) if (tile is not None and bounds is not None) else 0.0
        if mode == 'vfx_blackhole_warp':
            # Unfurl smoothly out from the central singularity along the elliptical accretion disk (zero bottom clipping)
            theta = -rem * math.radians(125.0)
            rad = 0.12 + 0.88 * ease_in
            recoil = math.exp(-6.5 * t) * math.sin(t * math.pi * 2.2) * 4.5
            dx = (vx * math.cos(theta) - vy * math.sin(theta)) * rad - vx + recoil
            dy = (vx * math.sin(theta) * 0.26 + vy * math.cos(theta)) * rad - vy
            scale = 0.20 + 0.80 * ease_in
            return dx, dy, scale, scale, math.degrees(theta) * 0.32, min(1.0, t * 4.2), t
        theta = rem * math.radians(82.0) * (1.0 if index % 2 == 0 else -1.0)
        recoil = math.exp(-6.0 * t) * math.cos(t * math.pi * 2.8) * 5.0
        dx = (vx * math.cos(theta) - vy * math.sin(theta)) * (1.0 + 0.30 * rem) - vx + recoil
        dy = (vx * math.sin(theta) + vy * math.cos(theta)) * (1.0 + 0.30 * rem) - vy - 12.0 * rem
        scale = 0.62 + 0.38 * ease_in
        return dx, dy, scale, scale, math.degrees(theta) * 0.45, min(1.0, t * 4.2), t
    if mode in ('editor_trampoline', 'vfx_elastic_bounce_pro'):
        delay = 0.40 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (phase - delay) / max(0.05, 1.0 - delay)))
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        amp = 46.0 if mode == 'vfx_elastic_bounce_pro' else 36.0
        dy_drop = -amp * abs(math.cos(t * math.pi * 2.8)) * ((1.0 - t) ** 1.55)
        impact = max(0.0, 1.0 - abs(math.cos(t * math.pi * 2.8))) * ((1.0 - t) ** 1.3)
        sx = 1.0 + (0.24 if mode == 'vfx_elastic_bounce_pro' else 0.18) * impact
        sy = max(0.72, 1.0 - (0.20 if mode == 'vfx_elastic_bounce_pro' else 0.15) * impact)
        angle = (-6.0 if index % 2 == 0 else 6.0) * (1.0 - t) * math.sin(t * math.pi * 2.2)
        return 0.0, dy_drop, sx, sy, angle, min(1.0, t * 5.0), t
    if mode in ('editor_flip_cascade', 'vfx_3d_domino_flip'):
        delay = 0.46 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (phase - delay) / max(0.05, 1.0 - delay)))
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        quint = 1.0 - (1.0 - t) ** 4
        sx = max(0.12, abs(math.cos((1.0 - quint) * math.pi * 0.5)))
        sy = 0.84 + 0.16 * quint
        return 0.0, 18.0 * (1.0 - quint), sx, sy, -12.0 * (1.0 - quint), min(1.0, t * 4.5), t
    if mode == 'vfx_liquid_fire':
        delay = 0.42 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (phase - delay) / max(0.05, 1.0 - delay)))
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        quint = 1.0 - (1.0 - t) ** 3.6
        rem = 1.0 - quint
        dx = math.sin(t * 10.0 + index * 1.1) * 9.0 * rem
        dy = 34.0 * rem - 8.0 * math.sin(t * math.pi)
        sx = 0.82 + 0.18 * quint
        sy = 1.24 - 0.24 * quint
        return dx, dy, sx, sy, math.sin(t * 8.0 + index) * 7.0 * rem, min(1.0, t * 4.2), t
    if mode == 'editor_matrix_decode':
        delay = 0.44 * index / max(1, count - 1)
        t = min(1.0, max(0.0, (phase - delay) / max(0.05, 1.0 - delay)))
        if t >= 1.0:
            return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
        quant = math.floor(t * 7.0) / 7.0 if t < 0.85 else t
        dy = (1.0 - quant) * (-18.0 if index % 2 == 0 else 18.0)
        flicker = 1.0 if t > 0.72 else (0.35 + 0.65 * ((int(t * 14) + index) & 1))
        return 0.0, dy, 0.92 + 0.08 * quant, 1.12 - 0.12 * quant, 0.0, min(1.0, t * 5.5) * flicker, t

    stagger = 0.46 if mode == 'editor_pop' else 0.42
    delay = stagger * index / max(1, count - 1)
    t = min(1.0, max(0.0, (phase - delay) / max(0.05, 1.0 - delay)))
    if t >= 1.0:
        return 0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0
    if mode == 'editor_pop':
        # Elastic CapCut/Apple pop: 0.72 -> 1.045 -> 0.99 -> 1.0 (no neighbor collision!)
        if t < 0.45:
            u = t / 0.45
            ease = 1.0 - (1.0 - u) ** 3
            scale = 0.72 + 0.325 * ease
            dy = 12.0 * (1.0 - ease) - 1.6 * ease
        else:
            u = (t - 0.45) / 0.55
            decay = math.exp(-5.5 * u) * math.cos(u * math.pi * 2.0)
            scale = 1.0 + 0.045 * decay
            dy = -1.6 * decay
        alpha = min(1.0, t * 4.5)
        s = max(0.2, scale)
        return 0.0, dy, s, s, 0.0, alpha, t
    # editor_wave: liquid upward flow with gentle angle settle
    quint = 1.0 - (1.0 - t) ** 4
    wave_damp = math.exp(-4.0 * t) * math.cos(t * math.pi * 1.5)
    dy = 18.0 * (1.0 - quint) + 6.0 * wave_damp
    scale = 0.85 + 0.15 * quint
    angle = -5.5 * (1.0 - quint) * math.sin(index * 0.7 + t * math.pi)
    alpha = min(1.0, t * 3.8)
    return 0.0, dy, scale, scale, angle, alpha, t


class KineticPainter:
    """A cached <=16-cell plan; reuse the existing glyph sprite with clipping."""
    def __init__(self, label):
        self.label = label
        self.key = None
        self.tiles = []
        self._char_key = None
        self._char_tiles = []
        self.last_draw_count = 0

    def clear(self):
        self.key, self.tiles, self.last_draw_count = None, [], 0
        self._char_key, self._char_tiles = None, []

    def _geom_signature(self):
        cached_plan = getattr(self.label, '_cached_plan', None)
        if (
            cached_plan is not None
            and getattr(self.label, '_cached_text', None) == self.label.text()
            and getattr(self.label, '_cached_size', None) == self.label.size()
        ):
            return id(cached_plan)
        visual_lines = iter_visual_lines(self.label)
        return tuple((round(l.x, 1), round(l.y_top, 1), round(l.width, 1)) for l in visual_lines)

    def _tiles_for(self, sprite, origin, parts, duration_ms, limit):
        bounds = QRectF(origin.x(), origin.y(), sprite.width() / sprite.devicePixelRatio(),
                        sprite.height() / sprite.devicePixelRatio())
        geom_sig = self._geom_signature()
        key = (self.label.text(), self.label.font().key(), self.label.contentsRect().getRect(),
               bounds.getRect(), parts, duration_ms, limit, geom_sig)
        if key != self.key:
            self.key = key
            self.tiles = make_tiles(self.label, bounds, parts, duration_ms, limit)
        return bounds, self.tiles

    def _char_tiles_for(self, sprite, origin):
        bounds = QRectF(origin.x(), origin.y(), sprite.width() / sprite.devicePixelRatio(),
                        sprite.height() / sprite.devicePixelRatio())
        geom_sig = self._geom_signature()
        key = (self.label.text(), self.label.font().key(), self.label.contentsRect().getRect(),
               bounds.getRect(), geom_sig)
        if key != self._char_key:
            self._char_key = key
            self._char_tiles = make_char_tiles(self.label, bounds, MAX_CHAR_TILES)
        return bounds, self._char_tiles

    def snapshot_tiles(self, sprite, origin, mode, duration_ms, prefer_cached=False):
        """Return bounded word/cluster or per-character tiles ready for outgoing exit explosion."""
        if sprite is None:
            return []
        if mode in PER_CHAR_MODES:
            if prefer_cached and self._char_tiles:
                return list(self._char_tiles)
            _bounds, c_tiles = self._char_tiles_for(sprite, origin)
            return list(c_tiles)
        if prefer_cached and self.tiles:
            return list(self.tiles)
        cluster_modes = (
            'editor_shatter_rebirth', 'editor_tornado_magnet',
            'vfx_supernova_shatter', 'vfx_blackhole_warp', 'vfx_glass_shatter',
        )
        parts = 'auto' if mode in cluster_modes else 'word'
        limit = 16 if mode in cluster_modes else 14
        _bounds, tiles = self._tiles_for(sprite, origin, parts, max(80, int(duration_ms)), limit)
        return list(tiles)

    def paint_exit_ghost(self, painter, ghost, out_phase):
        """Render the previous cue's shards or individual characters firing outward while Cue B enters."""
        sp = ghost.get('sprite')
        origin = ghost.get('origin')
        tiles = ghost.get('tiles') or ()
        bounds = ghost.get('bounds')
        mode = ghost.get('mode', 'editor_shatter_rebirth')
        if sp is None or origin is None or not tiles:
            return False
        dpr = max(1.0, float(sp.devicePixelRatio()))
        sp_bounds = QRectF(origin.x(), origin.y(), sp.width() / dpr, sp.height() / dpr)
        base_opacity = painter.opacity()
        count = len(tiles)
        is_per_char = mode in PER_CHAR_MODES
        for index, tile in enumerate(tiles):
            if is_per_char:
                dx, dy, sx, sy, angle, alpha = _per_char_exit_motion(mode, out_phase, tile, count, bounds)
            else:
                dx, dy, sx, sy, angle, alpha = _editor_exit_motion(mode, out_phase, index, count, tile, bounds)
            if alpha <= 0.01:
                continue
            target = tile.rect.intersected(sp_bounds)
            if target.isEmpty():
                continue
            source = QRectF(
                (target.left() - origin.x()) * dpr,
                (target.top() - origin.y()) * dpr,
                target.width() * dpr,
                target.height() * dpr,
            )
            if dx == 0.0 and dy == 0.0 and angle == 0.0 and sx == 1.0 and sy == 1.0 and alpha >= 0.99:
                painter.drawImage(target, sp, source)
            else:
                painter.save()
                painter.translate(tile.center_x + dx, tile.center_y + dy)
                if angle:
                    painter.rotate(angle)
                if sx != 1.0 or sy != 1.0:
                    painter.scale(sx, sy)
                painter.translate(-tile.center_x, -tile.center_y)
                painter.setOpacity(base_opacity * alpha)
                painter.drawImage(target, sp, source)
                painter.restore()
            self.last_draw_count += 1
        return True

    def paint_per_char(self, painter, sprite, origin, mode, progress, duration_ms, blur_img=None):
        """Fast direct-blit Beat-Synced Per-Character Kinetic Typography (0 clip rects, 1 cached sprite)."""
        self.last_draw_count = 0
        if sprite is None or progress >= 1.0 or duration_ms < 80:
            return False
        bounds, tiles = self._char_tiles_for(sprite, origin)
        if not tiles:
            return False
        dpr = max(1.0, float(sprite.devicePixelRatio()))
        sp_bounds = QRectF(origin.x(), origin.y(), sprite.width() / dpr, sprite.height() / dpr)
        base_opacity = painter.opacity()
        count = len(tiles)
        blur_sx = blur_img.width() / max(1e-3, sp_bounds.width()) if blur_img is not None else 0.0
        blur_sy = blur_img.height() / max(1e-3, sp_bounds.height()) if blur_img is not None else 0.0
        blur_draws = 0
        glint_draws = 0
        spark_palette = (
            QColor(119, 224, 190, 235),
            QColor(254, 240, 138, 235),
            QColor(103, 232, 249, 230),
        )
        for tile in tiles:
            dx, dy, sx, sy, angle, alpha, t = _per_char_enter_motion(mode, progress, tile, count, bounds)
            if alpha <= 0.01:
                continue
            target = tile.rect.intersected(sp_bounds)
            if target.isEmpty():
                continue
            source = QRectF(
                (target.left() - origin.x()) * dpr,
                (target.top() - origin.y()) * dpr,
                target.width() * dpr,
                target.height() * dpr,
            )
            if t >= 1.0:
                painter.drawImage(target, sprite, source)
                self.last_draw_count += 1
                continue
            if blur_img is not None and 0.04 < t < 0.34 and blur_draws < 10:
                b_alpha = base_opacity * alpha * 0.52 * (1.0 - t / 0.34)
                if b_alpha > 0.02:
                    b_src = QRectF(
                        (target.left() - sp_bounds.left()) * blur_sx,
                        (target.top() - sp_bounds.top()) * blur_sy,
                        target.width() * blur_sx,
                        target.height() * blur_sy,
                    )
                    painter.save()
                    painter.translate(tile.center_x + dx * 1.18, tile.center_y + dy * 1.18)
                    if angle:
                        painter.rotate(angle * 1.1)
                    painter.scale(sx, sy)
                    painter.translate(-tile.center_x, -tile.center_y)
                    painter.setOpacity(b_alpha)
                    painter.drawImage(target, blur_img, b_src)
                    painter.restore()
                    blur_draws += 1
            painter.save()
            painter.translate(tile.center_x + dx, tile.center_y + dy)
            if angle:
                painter.rotate(angle)
            if sx != 1.0 or sy != 1.0:
                painter.scale(sx, sy)
            painter.translate(-tile.center_x, -tile.center_y)
            painter.setOpacity(base_opacity * alpha)
            painter.drawImage(target, sprite, source)
            painter.restore()
            if 0.48 <= t <= 0.72 and glint_draws < 6:
                env = math.sin(((t - 0.48) / 0.24) * math.pi)
                col = QColor(spark_palette[tile.char_index % 3])
                col.setAlpha(int(col.alpha() * env))
                _draw_four_point_star(painter, tile.center_x, tile.center_y - tile.rect.height() * 0.24, 5.5 * env + 1.2, col, 0.20)
                glint_draws += 1
            self.last_draw_count += 1
        return True

    def paint_per_char_beat(self, painter, sprite, origin, scan_progress, beat_pulse, beat_phase):
        """Alive beat-synced micro-bounce ripple across assembled characters while music plays."""
        if sprite is None or beat_pulse <= 0.02:
            return False
        _bounds, tiles = self._char_tiles_for(sprite, origin)
        if not tiles:
            return False
        dpr = max(1.0, float(sprite.devicePixelRatio()))
        sp_bounds = QRectF(origin.x(), origin.y(), sprite.width() / dpr, sprite.height() / dpr)
        wave_pos = (beat_phase % 1.0)
        for tile in tiles:
            target = tile.rect.intersected(sp_bounds)
            if target.isEmpty():
                continue
            source = QRectF(
                (target.left() - origin.x()) * dpr,
                (target.top() - origin.y()) * dpr,
                target.width() * dpr,
                target.height() * dpr,
            )
            u = tile.col_index / max(1, tile.row_count - 1)
            dist = abs(u - wave_pos)
            dist = min(dist, 1.0 - dist)
            wave = math.exp(-(dist * dist) / 0.045)
            amp = beat_pulse * (0.28 + 0.72 * wave)
            if amp < 0.06:
                painter.drawImage(target, sprite, source)
                continue
            dy = -5.0 * amp
            sc = 1.0 + 0.062 * amp
            tilt = (-1.0 if tile.char_index % 2 == 0 else 1.0) * 2.4 * amp
            painter.save()
            painter.translate(tile.center_x, tile.center_y + dy)
            painter.rotate(tilt)
            painter.scale(sc, sc)
            painter.translate(-tile.center_x, -tile.center_y)
            painter.drawImage(target, sprite, source)
            painter.restore()
        return True

    def paint_editor(self, painter, sprite, origin, mode, progress, duration_ms, draw_glyphs, draw_blurred=None):
        self.last_draw_count = 0
        if sprite is None or progress >= 1.0 or duration_ms < 80:
            return False
        cluster_modes = (
            'editor_shatter_rebirth', 'editor_tornado_magnet',
            'vfx_supernova_shatter', 'vfx_blackhole_warp', 'vfx_glass_shatter',
        )
        parts = 'auto' if mode in cluster_modes else 'word'
        limit = 16 if mode in cluster_modes else 14
        bounds, tiles = self._tiles_for(sprite, origin, parts, duration_ms, limit)
        if not tiles:
            return False
        base_opacity = painter.opacity()
        count = len(tiles)
        for index, tile in enumerate(tiles):
            dx, dy, sx, sy, angle, alpha, t = _editor_motion(mode, progress, index, count, tile, bounds)
            if alpha <= 0.0:
                continue
            # True optical Gaussian blur wake cross-fading cleanly into crisp spring settlement
            if draw_blurred is not None and t < 0.40:
                blur_alpha = base_opacity * alpha * (0.72 * (1.0 - t / 0.40))
                if blur_alpha > 0.01:
                    painter.save()
                    painter.translate(tile.center_x + dx, tile.center_y + dy)
                    if angle:
                        painter.rotate(angle)
                    painter.scale(sx, sy)
                    painter.translate(-tile.center_x, -tile.center_y)
                    painter.setClipRect(tile.rect, Qt.ClipOperation.IntersectClip)
                    painter.setOpacity(blur_alpha)
                    draw_blurred(tile.rect)
                    painter.restore()
            painter.save()
            painter.translate(tile.center_x + dx, tile.center_y + dy)
            if angle:
                painter.rotate(angle)
            painter.scale(sx, sy)
            painter.translate(-tile.center_x, -tile.center_y)
            painter.setClipRect(tile.rect, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(base_opacity * alpha * (min(1.0, t / 0.35) if draw_blurred is not None else 1.0))
            draw_glyphs(tile.rect)
            painter.restore()
            self.last_draw_count += 1
        return True

    def paint(self, painter, sprite, origin, mode, progress, strength, parts, duration_ms, draw_glyphs,
              limit=MAX_TILES):
        self.last_draw_count = 0
        if sprite is None or progress >= 1 or duration_ms < 80:
            return False
        bounds, tiles = self._tiles_for(sprite, origin, parts, duration_ms, limit)
        if not tiles:
            return False
        for index, tile in enumerate(tiles):
            dx, dy, sx, sy, angle, alpha = motion(mode, progress, index, len(tiles),
                                                  tile, bounds, strength)
            if alpha <= 0:
                continue
            painter.save()
            painter.translate(tile.center_x + dx, tile.center_y + dy)
            painter.rotate(angle)
            painter.scale(sx, sy)
            painter.translate(-tile.center_x, -tile.center_y)
            painter.setClipRect(tile.rect, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(painter.opacity() * alpha)
            draw_glyphs(tile.rect)
            painter.restore()
            self.last_draw_count += 1
        return True
