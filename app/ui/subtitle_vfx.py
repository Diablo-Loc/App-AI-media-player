"""High-impact painter-only VFX layers (shockwaves, saber slashes, glitch tears, equalizers, embers).

All coordinates derive strictly from TypographyPlan bounds and WordRegion targets so every VFX
element stays pixel-locked to rendered glyphs at 60 FPS with <= 24 draw primitives per frame.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

try:
    import numpy as _np
except Exception:
    _np = None

_RGB_TINT_CACHE: dict[int, tuple[QImage, QImage]] = {}


def clear_vfx_caches() -> None:
    """Release cached chromatic-split sprites when subtitles stop or reset."""
    _RGB_TINT_CACHE.clear()


def _tinted_rgb_sprites(sprite: QImage) -> tuple[QImage, QImage] | None:
    """Cache cyan & magenta chromatic-split QImages derived from sprite alpha (zero Bezier rasterization)."""
    if sprite is None or sprite.isNull():
        return None
    key = int(sprite.cacheKey())
    cached = _RGB_TINT_CACHE.get(key)
    if cached is not None:
        return cached
    dpr = max(1.0, float(sprite.devicePixelRatio()))
    if _np is not None:
        src = sprite.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        w, h = src.width(), src.height()
        bpl = src.bytesPerLine()
        buf = _np.frombuffer(src.constBits(), dtype=_np.uint8).reshape((h, bpl))
        alpha = buf[:, 3:w * 4:4]
        out_imgs = []
        for r_c, g_c, b_c in ((34, 211, 238), (244, 63, 94)):
            img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            dst = _np.frombuffer(img.bits(), dtype=_np.uint8).reshape((h, img.bytesPerLine()))
            dst.fill(0)
            a_f = alpha.astype(_np.uint16)
            dst[:, 0:w * 4:4] = ((a_f * b_c) // 255).astype(_np.uint8)
            dst[:, 1:w * 4:4] = ((a_f * g_c) // 255).astype(_np.uint8)
            dst[:, 2:w * 4:4] = ((a_f * r_c) // 255).astype(_np.uint8)
            dst[:, 3:w * 4:4] = alpha
            out_imgs.append(img)
        pair = (out_imgs[0], out_imgs[1])
    else:
        out_imgs = []
        for col in (QColor('#22D3EE'), QColor('#F43F5E')):
            img = QImage(sprite.size(), QImage.Format.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.drawImage(0, 0, sprite)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            p.fillRect(img.rect(), col)
            p.end()
            out_imgs.append(img)
        pair = (out_imgs[0], out_imgs[1])
    if len(_RGB_TINT_CACHE) >= 2:
        _RGB_TINT_CACHE.clear()
    _RGB_TINT_CACHE[key] = pair
    return pair

VFX_MODES = frozenset({
    'vfx_beat_char_pop',
    'vfx_char_orbit_snap',
    'vfx_char_cascade_drop',
    'vfx_scatter_leap',
    'vfx_supernova_shatter',
    'vfx_saber_slash',
    'vfx_bass_drop_3d',
    'vfx_cyber_glitch_pro',
    'vfx_blackhole_warp',
    'vfx_magnet_assemble',
    'vfx_cyclone_sweep',
    'vfx_firework_bloom',
    'vfx_glass_shatter',
    'vfx_elastic_bounce_pro',
    'vfx_amll_silk_pro',
    'vfx_3d_domino_flip',
    'vfx_liquid_fire',
    'vfx_cinema_clean',
})

VFX_TILE_MODES = frozenset({
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

VFX_EXIT_MODES = frozenset({
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

VFX_TRAIL_KEYS = frozenset({
    'supernova_embers',
    'thunder_chain',
    'bass_visualizer',
    'cyber_laser',
    'nebula_orbit',
    'star_confetti',
    'phoenix_embers',
    'prism_flare',
})

SPRITE_VFX_STYLE_FOR_MODE = {
    'vfx_beat_char_pop': 'neon_tube',
    'vfx_char_orbit_snap': 'cyber_holo',
    'vfx_char_cascade_drop': 'fire_ember',
    'vfx_scatter_leap': 'fire_ember',
    'vfx_supernova_shatter': 'fire_ember',
    'vfx_saber_slash': 'neon_tube',
    'vfx_bass_drop_3d': 'metallic_3d',
    'vfx_cyber_glitch_pro': 'cyber_holo',
    'vfx_blackhole_warp': 'neon_tube',
    'vfx_magnet_assemble': 'metallic_3d',
    'vfx_cyclone_sweep': 'neon_tube',
    'vfx_firework_bloom': 'fire_ember',
    'vfx_glass_shatter': 'cyber_holo',
    'vfx_elastic_bounce_pro': 'deep_glow',
    'vfx_amll_silk_pro': 'deep_glow',
    'vfx_3d_domino_flip': 'metallic_3d',
    'vfx_liquid_fire': 'fire_ember',
    'vfx_cinema_clean': 'deep_glow',
}


def sprite_vfx_style_for(entrance: str, glow: bool) -> str:
    if not glow and entrance not in SPRITE_VFX_STYLE_FOR_MODE:
        return 'standard'
    return SPRITE_VFX_STYLE_FOR_MODE.get(entrance, 'deep_glow' if glow else 'standard')


def _make_unit_star(inner_ratio: float = 0.20) -> QPainterPath:
    path = QPainterPath()
    for idx in range(8):
        ang = -math.pi / 2.0 + idx * (math.pi / 4.0)
        r = 1.0 if idx % 2 == 0 else inner_ratio
        px, py = math.cos(ang) * r, math.sin(ang) * r
        if idx == 0:
            path.moveTo(px, py)
        else:
            path.lineTo(px, py)
    path.closeSubpath()
    return path


_UNIT_STAR_SHARP = _make_unit_star(0.16)
_UNIT_STAR_SOFT = _make_unit_star(0.24)


def _draw_four_point_star(painter: QPainter, cx: float, cy: float, radius: float, color: QColor, inner_ratio: float = 0.22) -> None:
    if radius <= 0.5 or color.alpha() <= 2:
        return
    star = _UNIT_STAR_SHARP if inner_ratio <= 0.19 else _UNIT_STAR_SOFT
    painter.save()
    painter.translate(cx, cy)
    painter.scale(radius, radius)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(star)
    painter.restore()


def paint_choreo_accent(painter: QPainter, center: QPointF, bounds: QRectF, mode: str, phase: float, is_exit: bool = False) -> None:
    """Lightweight optical accent flash for Firework Bloom, Glass Shatter, and Magnet Assemble."""
    p = min(1.0, max(0.0, float(phase)))
    if p <= 0.02 or p >= 0.94:
        return
    base_op = painter.opacity()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setOpacity(base_op)

    if mode == 'vfx_firework_bloom':
        ease = 1.0 - (1.0 - p) ** 2.4
        fade = (1.0 - p) ** 1.4
        max_rx = max(68.0, bounds.width() * 0.52)
        max_ry = max(32.0, bounds.height() * 0.88)
        palette = (QColor(254, 240, 138, int(235 * fade)), QColor(244, 114, 182, int(215 * fade)), QColor(56, 189, 248, int(215 * fade)))
        count = 12 if is_exit else 8
        for idx in range(count):
            ang = idx * (2.0 * math.pi / count) + (0.25 if is_exit else 0.65)
            d1 = (0.20 + 0.78 * ease)
            d0 = max(0.05, d1 - 0.22 * (1.0 - p * 0.5))
            p0 = QPointF(center.x() + math.cos(ang) * max_rx * d0, center.y() + math.sin(ang) * max_ry * d0)
            p1 = QPointF(center.x() + math.cos(ang) * max_rx * d1, center.y() + math.sin(ang) * max_ry * d1 + (10.0 * p * p if is_exit else 0.0))
            painter.setPen(QPen(palette[idx % 3], 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(p0, p1)
            if idx % 2 == 0:
                _draw_four_point_star(painter, p1.x(), p1.y(), 4.5 * fade + 1.2, palette[idx % 3], 0.24)
    elif mode == 'vfx_glass_shatter':
        env = math.sin(min(1.0, p / 0.85) * math.pi)
        if env > 0.02:
            # Crisp icy refraction shards radiating briefly on fracture / fuse
            max_rx = max(56.0, bounds.width() * 0.44)
            max_ry = max(24.0, bounds.height() * 0.68)
            for idx in range(6):
                ang = idx * 1.0472 + (0.3 if is_exit else 0.8)
                x1 = center.x() + math.cos(ang) * max_rx * (0.25 + 0.75 * p)
                y1 = center.y() + math.sin(ang) * max_ry * (0.25 + 0.75 * p)
                x0 = center.x() + math.cos(ang) * max_rx * 0.12
                y0 = center.y() + math.sin(ang) * max_ry * 0.12
                painter.setPen(QPen(QColor(186, 230, 253, int(175 * env)), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    elif mode == 'vfx_magnet_assemble' and not is_exit and 0.45 <= p <= 0.90:
        env = math.sin(((p - 0.45) / 0.45) * math.pi)
        span = min(bounds.width() * 0.85, 280.0)
        y = center.y()
        grad = QLinearGradient(center.x() - span * 0.5, y, center.x() + span * 0.5, y)
        grad.setColorAt(0.0, QColor(119, 224, 190, 0))
        grad.setColorAt(0.5, QColor(236, 253, 245, int(215 * env)))
        grad.setColorAt(1.0, QColor(119, 224, 190, 0))
        painter.setPen(QPen(grad, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(center.x() - span * 0.5, y), QPointF(center.x() + span * 0.5, y))
        _draw_four_point_star(painter, center.x(), y, 9.5 * env, QColor(236, 253, 245, int(225 * env)), 0.16)
    painter.restore()


def paint_supernova_shockwave(painter: QPainter, center: QPointF, bounds: QRectF, phase: float, is_exit: bool = False) -> None:
    """Expanding radial supernova shockwave bloom + blazing plasma rings + sparks."""
    p = min(1.0, max(0.0, float(phase)))
    if p <= 0.01 or p >= 0.99:
        return
    base_op = painter.opacity()
    ease = 1.0 - (1.0 - p) ** 2.6
    max_rx = max(72.0, bounds.width() * 0.56)
    max_ry = max(36.0, bounds.height() * 1.02)
    rx = max_rx * (0.24 + 0.90 * ease)
    ry = max_ry * (0.30 + 0.92 * ease)
    fade = (1.0 - p) ** 1.35

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setOpacity(base_op)

    # Soft compact radial bloom (capped radius keeps software fill fast <0.4ms)
    bloom_rx = min(145.0, rx * 0.85)
    bloom_ry = min(72.0, ry * 0.85)
    bloom = QRadialGradient(center, max(bloom_rx, bloom_ry))
    bloom.setColorAt(0.0, QColor(255, 251, 235, int(105 * fade)))
    bloom.setColorAt(0.50, QColor(251, 146, 60, int(65 * fade)))
    bloom.setColorAt(1.0, QColor(244, 63, 94, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bloom)
    painter.drawEllipse(center, bloom_rx, bloom_ry)

    # Outer glowing plasma shockwave ring + inner white-gold flash ring
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(251, 165, 36, int(210 * fade)), max(1.2, 4.4 * (1.0 - p))))
    painter.drawEllipse(center, rx, ry)
    painter.setPen(QPen(QColor(255, 251, 235, int(235 * fade)), max(0.9, 1.8 * (1.0 - p))))
    painter.drawEllipse(center, rx * 0.86, ry * 0.86)

    # Radial sparks blasting outward (12/8 sparks keeps P95 well under 2ms)
    spark_count = 12 if is_exit else 8
    pen_gold = QPen(QColor(254, 240, 138, int(235 * fade)), 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    pen_rose = QPen(QColor(251, 113, 133, int(215 * fade)), 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    for idx in range(spark_count):
        ang = idx * 2.399963 + (0.4 if is_exit else 1.7)
        dist = (0.32 + 0.90 * ease) * (0.65 + 0.35 * ((idx % 3) / 2.0))
        sx = center.x() + math.cos(ang) * max_rx * dist
        sy = center.y() + math.sin(ang) * max_ry * dist + (16.0 * p * p if is_exit else 0.0)
        tx = sx - math.cos(ang) * (12.0 + 13.0 * (1.0 - p))
        ty = sy - math.sin(ang) * (7.0 + 8.0 * (1.0 - p))
        painter.setPen(pen_gold if idx % 2 == 0 else pen_rose)
        painter.drawLine(QPointF(tx, ty), QPointF(sx, sy))

    # Peak center flare on rebirth lock-in
    if not is_exit and 0.42 <= p <= 0.90:
        flare_env = math.sin(((p - 0.42) / 0.48) * math.pi)
        _draw_four_point_star(
            painter,
            center.x(),
            center.y(),
            min(48.0, bounds.height() * 0.72) * flare_env,
            QColor(255, 251, 235, int(225 * flare_env)),
            inner_ratio=0.15,
        )
    painter.restore()


def paint_blackhole_singularity(
    painter: QPainter,
    center: QPointF,
    bounds: QRectF,
    phase: float,
    is_exit: bool = False,
) -> None:
    """Smooth violet-cyan singularity vortex that opens cleanly, pulls words in, and collapses into a star pinpoint."""
    p = min(1.0, max(0.0, float(phase)))
    if p <= 0.01 or p >= 0.99:
        return
    base_op = painter.opacity()
    if is_exit:
        # Smooth ramp in (0..0.22), steady gravity well (0.22..0.68), smooth collapse to starlight pinpoint (0.68..0.99)
        open_env = min(1.0, p / 0.22)
        open_ease = 1.0 - (1.0 - open_env) ** 2.2
        if p <= 0.68:
            collapse = 1.0
            env = open_ease
        else:
            c_u = min(1.0, (p - 0.68) / 0.31)
            collapse = max(0.0, 1.0 - c_u * c_u)
            env = open_ease * max(0.0, (1.0 - c_u) ** 1.35)
        r = max(24.0, min(68.0, bounds.height() * 0.72)) * (0.38 + 0.62 * open_ease) * max(0.04, collapse)
    else:
        if p >= 0.88:
            return
        u = p / 0.88
        env = math.sin(u * math.pi)
        collapse = 1.0 - max(0.0, (u - 0.55) / 0.45) ** 1.8
        r = max(24.0, min(68.0, bounds.height() * 0.70)) * (0.45 + 0.65 * env) * max(0.08, collapse)

    if env <= 0.01 or r <= 1.0:
        return

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setOpacity(base_op)

    halo = QRadialGradient(center, max(2.0, r * 1.50))
    halo.setColorAt(0.0, QColor(4, 6, 16, int(230 * env)))
    halo.setColorAt(0.32, QColor(15, 23, 42, int(205 * env)))
    halo.setColorAt(0.56, QColor(168, 85, 247, int(160 * env)))
    halo.setColorAt(0.78, QColor(56, 189, 248, int(105 * env)))
    halo.setColorAt(1.0, QColor(56, 189, 248, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(halo)
    painter.drawEllipse(center, r * 1.50, r * 0.88)

    # Photon ring around event horizon
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(224, 242, 254, int(195 * env)), max(0.8, 1.6 * min(1.0, r / 30.0))))
    painter.drawEllipse(center, r * 0.54, r * 0.32)

    # Coherent clockwise rotating plasma accretion spiral arcs
    for idx in range(4):
        start_deg = int((-p * 520.0 + idx * 90.0) * 16)
        span_deg = int(68 * 16)
        col = QColor(103, 232, 249, int(225 * env)) if idx % 2 == 0 else QColor(232, 121, 249, int(210 * env))
        painter.setPen(QPen(col, max(0.9, 2.3 * min(1.0, r / 32.0)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        scale_r = 0.84 + (idx % 2) * 0.24
        arc_rect = QRectF(center.x() - r * scale_r, center.y() - r * scale_r * 0.56, r * scale_r * 2.0, r * scale_r * 1.12)
        painter.drawArc(arc_rect, start_deg, span_deg)

    # Smooth closing starlight pinpoint flash as exit singularity seals shut
    if is_exit and 0.66 <= p <= 0.96:
        pin_u = (p - 0.66) / 0.30
        pin_env = math.sin(pin_u * math.pi)
        _draw_four_point_star(
            painter,
            center.x(),
            center.y(),
            16.0 * pin_env,
            QColor(224, 242, 254, int(235 * pin_env)),
            inner_ratio=0.16,
        )
    painter.restore()


def paint_vfx_optical_entrance(
    painter: QPainter,
    sprite,
    origin: QPointF,
    blur_img,
    path: QPainterPath,
    bounds: QRectF,
    mode: str,
    p: float,
) -> bool:
    """High-impact full-sprite VFX entrances: Saber Slash, Bass Drop 3D, Cyber Glitch Pro, Cinema Flare."""
    if sprite is None or p >= 1.0:
        return False
    base_op = painter.opacity()
    dpr = max(1.0, float(sprite.devicePixelRatio()))
    dest = QRectF(origin.x(), origin.y(), sprite.width() / dpr, sprite.height() / dpr)
    center = bounds.center()

    if mode == 'vfx_saber_slash':
        quint = 1.0 - (1.0 - p) ** 4.2
        remain = 1.0 - quint
        shear = 62.0 * remain
        mid_y = center.y()
        # Split top & bottom halves along blade cut + chromatic echo
        top_clip = QRectF(dest.left() - 90.0, dest.top() - 32.0, dest.width() + 180.0, (mid_y - dest.top()) + 32.0)
        bot_clip = QRectF(dest.left() - 90.0, mid_y, dest.width() + 180.0, (dest.bottom() - mid_y) + 32.0)
        for clip_r, sx_off, sy_off in ((top_clip, shear, -3.5 * remain), (bot_clip, -shear, 3.5 * remain)):
            painter.save()
            painter.setClipRect(clip_r, Qt.ClipOperation.IntersectClip)
            if blur_img is not None and p < 0.45:
                painter.setOpacity(base_op * 0.55 * remain)
                painter.drawImage(dest.translated(sx_off * 1.25, sy_off), blur_img)
            painter.setOpacity(base_op * min(1.0, p * 4.5))
            painter.drawImage(origin + QPointF(sx_off, sy_off), sprite)
            painter.restore()

        # Blazing diagonal Anime Katana Cross-Slash beam + sparks
        if p < 0.72:
            env = math.sin((p / 0.72) * math.pi)
            p1 = QPointF(bounds.left() - 42.0, mid_y + 11.0)
            p2 = QPointF(bounds.right() + 42.0, mid_y - 11.0)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for col, width in (
                (QColor(34, 211, 238, int(115 * env)), 11.0 * env + 1.5),
                (QColor(52, 211, 153, int(185 * env)), 4.6 * env + 1.0),
                (QColor(255, 255, 255, int(250 * env)), 1.9 * env + 0.6),
            ):
                grad = QLinearGradient(p1, p2)
                grad.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), 0))
                grad.setColorAt(0.25, col)
                grad.setColorAt(0.5, QColor(255, 255, 255, col.alpha()))
                grad.setColorAt(0.75, col)
                grad.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 0))
                painter.setPen(QPen(grad, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(p1, p2)
            # Sparks scattering off the cut line
            for idx in range(8):
                u = (idx + 0.5) / 8.0
                bx = p1.x() + (p2.x() - p1.x()) * u
                by = p1.y() + (p2.y() - p1.y()) * u
                ang = idx * 2.1 + 0.6
                dx = math.cos(ang) * 26.0 * (p / 0.72)
                dy = math.sin(ang) * 18.0 * (p / 0.72)
                painter.setPen(QPen(QColor(165, 243, 252, int(225 * env)), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(QPointF(bx + dx * 0.35, by + dy * 0.35), QPointF(bx + dx, by + dy))
            painter.restore()
        return True

    if mode == 'vfx_bass_drop_3d':
        # Rocket slam: 2.05x -> 0.94x -> 1.0x + camera micro-shake + dual shockwave rings + RGB blast
        if p < 0.28:
            u = p / 0.28
            scale = 2.05 - 1.11 * (u * u * u)
            shake_x = shake_y = 0.0
        else:
            u = (p - 0.28) / 0.72
            rebound = math.exp(-6.2 * u) * math.cos(u * math.pi * 2.4)
            scale = 1.0 - 0.07 * rebound
            shake_env = math.exp(-7.5 * u)
            shake_x = math.sin(u * 44.0) * 6.5 * shake_env
            shake_y = math.cos(u * 52.0) * 4.5 * shake_env

        # Impact shockwave rings + RGB aberration after drop impact (p >= 0.22)
        if p >= 0.20:
            imp_p = min(1.0, (p - 0.20) / 0.80)
            imp_fade = (1.0 - imp_p) ** 1.6
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rx1 = max(48.0, bounds.width() * 0.48) * (0.30 + 0.95 * (1.0 - (1.0 - imp_p) ** 2.4))
            ry1 = max(24.0, bounds.height() * 0.78) * (0.35 + 1.05 * (1.0 - (1.0 - imp_p) ** 2.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(56, 189, 248, int(210 * imp_fade)), max(1.0, 4.5 * imp_fade)))
            painter.drawEllipse(center, rx1, ry1)
            painter.setPen(QPen(QColor(244, 114, 182, int(175 * imp_fade)), max(0.8, 2.6 * imp_fade)))
            painter.drawEllipse(center, rx1 * 0.76, ry1 * 0.76)
            painter.restore()

        painter.save()
        painter.translate(center.x() + shake_x, center.y() + shake_y)
        painter.scale(scale, scale)
        painter.translate(-center.x(), -center.y())

        # Vivid RGB split echo via cached SIMD sprites (zero per-frame Bezier fillPath stall)
        split = 9.5 * max(0.0, 1.0 - p * 1.15)
        if split > 0.4:
            pair = _tinted_rgb_sprites(sprite)
            if pair is not None:
                painter.save()
                painter.setOpacity(base_op * 0.52 * (1.0 - p))
                painter.drawImage(origin + QPointF(-split, -1.2), pair[0])
                painter.drawImage(origin + QPointF(split, 1.2), pair[1])
                painter.restore()
        if blur_img is not None and p < 0.36:
            painter.save()
            painter.setOpacity(base_op * 0.60 * (1.0 - p / 0.36))
            painter.drawImage(dest, blur_img)
            painter.restore()
        painter.setOpacity(base_op * min(1.0, p * 4.2))
        painter.drawImage(origin, sprite)
        painter.restore()
        return True

    if mode == 'vfx_cyber_glitch_pro':
        remain = (1.0 - p) ** 1.5
        # 6 horizontal glitch tear strips with deterministic pseudo-random displacement
        slices = 6
        slice_h = dest.height() / slices
        tick = int(p * 24.0)
        # RGB split ghost via cached SIMD sprites (zero per-frame Bezier fillPath stall)
        split = 10.5 * remain
        if split > 0.4:
            pair = _tinted_rgb_sprites(sprite)
            if pair is not None:
                painter.save()
                painter.setOpacity(base_op * 0.56 * remain)
                painter.drawImage(origin + QPointF(-split, 0.0), pair[0])
                painter.drawImage(origin + QPointF(split, 0.0), pair[1])
                painter.restore()

        for idx in range(slices):
            y0 = dest.top() + idx * slice_h
            band = QRectF(dest.left() - 60.0, y0, dest.width() + 120.0, slice_h + 0.6)
            seed = math.sin(tick * 12.7 + idx * 4.3)
            dx = seed * 24.0 * remain if abs(seed) > 0.32 else 0.0
            painter.save()
            painter.setClipRect(band, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(base_op * (0.75 + 0.25 * p))
            painter.drawImage(origin + QPointF(dx, 0.0), sprite)
            painter.restore()

        # Vertical neon decode laser sweep
        if p < 0.88:
            lx = bounds.left() + bounds.width() * (p / 0.88)
            env = math.sin((p / 0.88) * math.pi)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            glow_r = QRectF(lx - 14.0, bounds.top() - 10.0, 28.0, bounds.height() + 20.0)
            g = QLinearGradient(glow_r.left(), 0.0, glow_r.right(), 0.0)
            g.setColorAt(0.0, QColor(52, 211, 153, 0))
            g.setColorAt(0.5, QColor(52, 211, 153, int(170 * env)))
            g.setColorAt(1.0, QColor(52, 211, 153, 0))
            painter.fillRect(glow_r, g)
            painter.setPen(QPen(QColor(236, 253, 245, int(245 * env)), 1.8))
            painter.drawLine(QPointF(lx, bounds.top() - 8.0), QPointF(lx, bounds.bottom() + 8.0))
            painter.restore()
        return True

    if mode in ('vfx_amll_silk_pro', 'vfx_cinema_clean'):
        quint = 1.0 - (1.0 - p) ** 4.0
        remain = 1.0 - quint
        if blur_img is not None and remain > 0.01:
            painter.save()
            painter.setOpacity(base_op * (0.90 * remain))
            painter.drawImage(dest, blur_img)
            painter.restore()
        painter.save()
        painter.setOpacity(base_op * (0.36 + 0.64 * quint))
        painter.drawImage(origin, sprite)
        painter.restore()

        # Anamorphic ice-blue horizontal cinema lens flare sweep
        if mode == 'vfx_cinema_clean' and 0.12 <= p <= 0.88:
            u = (p - 0.12) / 0.76
            env = math.sin(u * math.pi)
            fx = bounds.left() + bounds.width() * u
            fy = center.y()
            flare_w = min(220.0, bounds.width() * 0.65)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            beam = QLinearGradient(fx - flare_w * 0.5, fy, fx + flare_w * 0.5, fy)
            beam.setColorAt(0.0, QColor(125, 211, 252, 0))
            beam.setColorAt(0.42, QColor(186, 230, 253, int(130 * env)))
            beam.setColorAt(0.50, QColor(255, 255, 255, int(225 * env)))
            beam.setColorAt(0.58, QColor(186, 230, 253, int(130 * env)))
            beam.setColorAt(1.0, QColor(125, 211, 252, 0))
            painter.setPen(QPen(beam, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(fx - flare_w * 0.5, fy), QPointF(fx + flare_w * 0.5, fy))
            _draw_four_point_star(painter, fx, fy, 11.0 * env, QColor(240, 249, 255, int(215 * env)), 0.16)
            painter.restore()
        return True

    return False


def paint_vfx_optical_exit(painter: QPainter, ghost: dict, out_p: float) -> bool:
    """Outgoing exit VFX for Saber Slash & Cyber Glitch Pro."""
    mode = ghost.get('mode')
    sp = ghost.get('sprite')
    org = ghost.get('origin')
    bounds = ghost.get('bounds')
    if sp is None or org is None or bounds is None:
        return False
    p = min(1.0, max(0.0, float(out_p)))
    base_op = painter.opacity()
    dpr = max(1.0, float(sp.devicePixelRatio()))
    dest = QRectF(org.x(), org.y(), sp.width() / dpr, sp.height() / dpr)

    if mode == 'vfx_saber_slash':
        mid_y = bounds.center().y()
        fade = max(0.0, (1.0 - p) ** 1.3)
        for clip_r, sh, sv in (
            (QRectF(dest.left() - 90, dest.top() - 24, dest.width() + 180, mid_y - dest.top() + 24), -58.0 * p, -6.0 * p),
            (QRectF(dest.left() - 90, mid_y, dest.width() + 180, dest.bottom() - mid_y + 24), 58.0 * p, 6.0 * p),
        ):
            painter.save()
            painter.setClipRect(clip_r, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(base_op * fade)
            painter.drawImage(org + QPointF(sh, sv), sp)
            painter.restore()
        return True

    if mode == 'vfx_cyber_glitch_pro':
        fade = max(0.0, (1.0 - p) ** 1.4)
        slices = 5
        sh = dest.height() / slices
        for idx in range(slices):
            band = QRectF(dest.left() - 80, dest.top() + idx * sh, dest.width() + 160, sh + 0.5)
            dx = (1.0 if idx % 2 == 0 else -1.0) * (18.0 + idx * 7.0) * p
            painter.save()
            painter.setClipRect(band, Qt.ClipOperation.IntersectClip)
            painter.setOpacity(base_op * fade)
            painter.drawImage(org + QPointF(dx, 0.0), sp)
            painter.restore()
        return True

    return False


def paint_vfx_trail(
    painter: QPainter,
    style: str,
    rows: list,
    row_group_ids: tuple,
    targets: list,
    progress: float,
    envelope: float,
    intensity: str,
    max_particles: int = 24,
    beat_pulse: float = 0.0,
) -> int:
    """Render pixel-aligned high-impact VFX trails directly anchored to WordRegion targets."""
    drawn = 0
    if not targets or envelope <= 0.0:
        return 0
    density_scale = {'gentle': 0.7, 'normal': 1.0, 'rich': 1.35}[intensity]

    if style == 'supernova_embers':
        # Fast diagonal fire meteors + prebuilt unit stars floating around active words
        count = max(4, min(max_particles, int(round(10 * density_scale))))
        per_t = max(1, count // len(targets))
        tail_pen = QPen(QColor(251, 146, 60, int(185 * envelope)), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        star_col = QColor(255, 251, 235, int(240 * envelope))
        for r_idx, (region, _loc, front) in enumerate(targets):
            rect = region.rect
            for i in range(per_t):
                if drawn >= max_particles:
                    break
                ph = (progress * 2.2 + i * 0.27 + r_idx * 0.41) % 1.0
                sx = front + (i - per_t * 0.5) * 32.0 + ph * 34.0
                sy = rect.top() - 16.0 + ph * (rect.height() + 20.0)
                ex, ey = sx - 20.0, sy - 13.0
                painter.setPen(tail_pen)
                painter.drawLine(QPointF(ex, ey), QPointF(sx, sy))
                _draw_four_point_star(painter, sx, sy, 3.6, star_col, 0.18)
                drawn += 1
        return drawn

    if style == 'thunder_chain':
        # Forked 2-branch neon plasma lightning crackling along active word
        segs = {'gentle': 4, 'normal': 6, 'rich': 7}[intensity]
        for r_idx, (region, _loc, front) in enumerate(targets):
            if drawn >= max_particles:
                break
            rect = region.rect
            x0 = max(rect.left() - 10.0, front - max(42.0, rect.width() * 0.65))
            x1 = min(rect.right() + 12.0, front + 14.0)
            y_base = rect.bottom() + 2.0
            phase_t = progress * 46.0 + r_idx * 3.1
            pts = []
            for k in range(segs + 1):
                u = k / segs
                px = x0 + (x1 - x0) * u
                jit = (math.sin(phase_t + k * 2.35) * 0.65 + math.sin(phase_t * 2.3 + k * 4.1) * 0.35) * (6.2 if 0 < k < segs else 0.0)
                pts.append(QPointF(px, y_base + jit))
            # Secondary upward lightning fork from middle node
            mid_pt = pts[segs // 2]
            fork_pts = [
                mid_pt,
                QPointF(mid_pt.x() + math.cos(phase_t * 0.85) * 9.0, mid_pt.y() - rect.height() * 0.42),
                QPointF(mid_pt.x() + math.sin(phase_t * 1.25) * 16.0, rect.top() - 4.0),
            ]
            for col, width in (
                (QColor(52, 211, 153, int(145 * envelope)), 4.2),
                (QColor(34, 211, 238, int(225 * envelope)), 2.0),
                (QColor(255, 255, 255, int(250 * envelope)), 1.0),
            ):
                if drawn >= max_particles:
                    break
                painter.setPen(QPen(col, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                for i in range(len(pts) - 1):
                    painter.drawLine(pts[i], pts[i + 1])
                for i in range(len(fork_pts) - 1):
                    painter.drawLine(fork_pts[i], fork_pts[i + 1])
                drawn += 1
        painter.setPen(Qt.PenStyle.NoPen)
        return drawn

    if style == 'bass_visualizer':
        # Clean Monstercat-style rhythmic Neon Equalizer reacting to live WASAPI beat pulse or smooth musical cadence
        bars_total = {'gentle': 12, 'normal': 18, 'rich': 22}[intensity]
        non_empty = [r for r in rows if r]
        if not non_empty:
            return 0
        left_x = min(r[0].rect.left() for r in non_empty)
        right_x = max(r[-1].rect.right() for r in non_empty)
        bottom_y = max(r[0].rect.bottom() for r in non_empty)
        span = max(64.0, right_x - left_x)
        base_y = bottom_y + 12.0
        front = targets[-1][2]
        n_bars = min(bars_total, max(6, max_particles - drawn))
        step = span / n_bars
        bar_w = max(3.0, min(8.0, step * 0.56))
        beat_boost = 1.0 + 0.78 * max(0.0, min(1.0, float(beat_pulse)))
        for b_i in range(n_bars):
            if drawn >= max_particles:
                break
            bx = left_x + (b_i + 0.5) * step
            dist = abs(bx - front) / max(44.0, span * 0.34)
            focus = math.exp(-dist * dist * 1.35)
            beat = 0.35 + 0.65 * abs(math.sin(progress * 28.0 + b_i * 0.78))
            bh = min(18.0, max(2.2, (2.6 + 8.6 * focus) * beat * beat_boost * envelope))
            u = b_i / max(1, n_bars - 1)
            r_c = int(56 + (244 - 56) * u)
            g_c = int(189 + (114 - 189) * u)
            b_c = int(248 + (182 - 248) * u)
            alpha = int((155 + 95 * focus) * envelope)
            bar_rect = QRectF(bx - bar_w * 0.5, base_y - bh, bar_w, bh)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(r_c, g_c, b_c, alpha))
            painter.drawRoundedRect(bar_rect, 1.5, 1.5)
            painter.setBrush(QColor(255, 255, 255, min(255, int(alpha * 0.95))))
            painter.drawRoundedRect(QRectF(bar_rect.left(), bar_rect.top() - 1.8, bar_w, 1.4), 0.7, 0.7)
            drawn += 1
        return drawn

    if style == 'cyber_laser':
        # Vertical cyber scanner beam tightly locked to each line height + glowing matrix sparks
        for r_idx, (region, _loc, front) in enumerate(targets):
            if drawn >= max_particles:
                break
            rect = region.rect
            beam = QRectF(front - 7.0, rect.top() - 1.5, 14.0, rect.height() + 3.0)
            g = QLinearGradient(beam.left(), 0.0, beam.right(), 0.0)
            g.setColorAt(0.0, QColor(34, 211, 238, 0))
            g.setColorAt(0.5, QColor(52, 211, 153, int(150 * envelope)))
            g.setColorAt(1.0, QColor(34, 211, 238, 0))
            painter.fillRect(beam, g)
            painter.setPen(QPen(QColor(236, 253, 245, int(240 * envelope)), 1.5))
            painter.drawLine(QPointF(front, rect.top() - 1.5), QPointF(front, rect.bottom() + 1.5))
            drawn += 1
            painter.setPen(Qt.PenStyle.NoPen)
            for k in range(4):
                if drawn >= max_particles:
                    break
                px = front + math.cos(progress * 14.0 + k * 1.9 + r_idx) * 20.0
                py = rect.top() + ((progress * 2.5 + k * 0.28) % 1.0) * rect.height()
                painter.setBrush(QColor(110, 231, 183, int(215 * envelope)))
                painter.drawRect(QRectF(px - 1.6, py - 1.6, 3.2, 3.2))
                drawn += 1
        return drawn

    if style == 'nebula_orbit':
        # Glowing violet/cyan orbital particles + galaxy halo around active word
        count = max(4, min(max_particles, int(round(12 * density_scale))))
        per_t = max(2, count // len(targets))
        for r_idx, (region, _loc, front) in enumerate(targets):
            rect = region.rect
            cy = rect.center().y()
            rx = max(20.0, rect.width() * 0.55)
            ry = max(10.0, rect.height() * 0.55)
            for k in range(per_t):
                if drawn >= max_particles:
                    break
                ang = progress * 12.0 + k * (2.0 * math.pi / per_t) + r_idx
                ox = front + math.cos(ang) * rx
                oy = cy + math.sin(ang) * ry
                rad = 2.2 + 1.8 * (0.5 + 0.5 * math.sin(ang))
                col = QColor(103, 232, 249, int(215 * envelope)) if k % 2 == 0 else QColor(217, 70, 239, int(205 * envelope))
                glow = QRadialGradient(QPointF(ox, oy), rad * 2.4)
                glow.setColorAt(0.0, QColor(255, 255, 255, int(235 * envelope)))
                glow.setColorAt(0.45, col)
                glow.setColorAt(1.0, QColor(col.red(), col.green(), col.blue(), 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(QPointF(ox, oy), rad * 2.2, rad * 2.2)
                drawn += 1
        return drawn

    if style == 'star_confetti':
        # Joyful multi-color glowing 4-point stars popping around active words
        palette = (QColor('#FDE047'), QColor('#F472B6'), QColor('#38BDF8'), QColor('#A78BFA'))
        count = max(6, min(max_particles, int(round(14 * density_scale))))
        per_t = max(2, count // len(targets))
        for r_idx, (region, local, front) in enumerate(targets):
            rect = region.rect
            for k in range(per_t):
                if drawn >= max_particles:
                    break
                seed = k * 2.399963 + r_idx * 1.9
                life = (progress * 3.2 + k * 0.21) % 1.0
                sx = front + math.cos(seed) * (12.0 + 26.0 * life)
                sy = rect.center().y() + math.sin(seed) * (10.0 + 18.0 * life) - 10.0 * life
                c = QColor(palette[k % len(palette)])
                c.setAlpha(int(235 * envelope * (1.0 - life * 0.7)))
                _draw_four_point_star(painter, sx, sy, 4.5 + 3.0 * (1.0 - life), c, 0.24)
                drawn += 1
        return drawn

    if style == 'phoenix_embers':
        # Rising blazing golden-crimson embers curling upward from text bottom
        count = max(6, min(max_particles, int(round(16 * density_scale))))
        per_t = max(3, count // len(targets))
        for r_idx, (region, _loc, front) in enumerate(targets):
            rect = region.rect
            for k in range(per_t):
                if drawn >= max_particles:
                    break
                rise = (progress * 2.4 + k * 0.19 + r_idx * 0.37) % 1.0
                ex = front + (k - per_t * 0.5) * 20.0 + math.sin(rise * 7.5 + k) * 9.0
                ey = rect.bottom() + 2.0 - rise * (rect.height() + 28.0)
                rad = (1.6 + 2.2 * (1.0 - rise))
                col = QColor(254, 240, 138, int(235 * envelope * (1.0 - rise * 0.85))) if k % 2 == 0 else QColor(249, 115, 22, int(220 * envelope * (1.0 - rise * 0.85)))
                glow = QRadialGradient(QPointF(ex, ey), rad * 2.6)
                glow.setColorAt(0.0, QColor(255, 255, 255, col.alpha()))
                glow.setColorAt(0.45, col)
                glow.setColorAt(1.0, QColor(239, 68, 68, 0))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(QPointF(ex, ey), rad * 2.4, rad * 2.4)
                drawn += 1
        return drawn

    if style == 'prism_flare':
        # Shimmering diamond prism cross-flare gliding cleanly along active word
        for r_idx, (region, _loc, front) in enumerate(targets):
            if drawn >= max_particles:
                break
            rect = region.rect
            cy = rect.center().y()
            flare_w = max(28.0, rect.height() * 1.35)
            beam = QLinearGradient(front - flare_w, cy, front + flare_w, cy)
            beam.setColorAt(0.0, QColor(165, 243, 252, 0))
            beam.setColorAt(0.4, QColor(244, 114, 182, int(110 * envelope)))
            beam.setColorAt(0.5, QColor(255, 255, 255, int(235 * envelope)))
            beam.setColorAt(0.6, QColor(125, 211, 252, int(110 * envelope)))
            beam.setColorAt(1.0, QColor(165, 243, 252, 0))
            painter.setPen(QPen(beam, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(front - flare_w, cy), QPointF(front + flare_w, cy))
            _draw_four_point_star(painter, front, cy, rect.height() * 0.36, QColor(255, 255, 255, int(225 * envelope)), 0.16)
            drawn += 1
        painter.setPen(Qt.PenStyle.NoPen)
        return drawn

    return drawn
