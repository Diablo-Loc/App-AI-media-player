"""Optional painter-only lyric effects; cue data and window geometry stay owned."""
import math
import time

try:
    import numpy as _np
except Exception:
    _np = None

from PySide6.QtCore import (
    QObject,
    QEvent,
    QVariantAnimation,
    QEasingCurve,
    QAbstractAnimation,
    Qt,
    QPointF,
    QRectF,
    QTimer,
    QElapsedTimer,
)
from PySide6.QtGui import QColor, QLinearGradient, QPen, QTransform, QImage, QPainter, QRegion
from ui.subtitle_particles import ParticlePainter, TRAILS, INTENSITIES
from ui.subtitle_kinetic import (
    KineticPainter,
    KINETIC_ENTRANCES,
    KINETIC_MODES,
    PER_CHAR_MODES,
    EDITOR_KINETIC_MODES,
    CHOREO_EXIT_MODES,
    STRENGTHS,
    PARTS,
)
from ui.subtitle_studio import (
    build_typography_plan,
    draw_studio_text_layers,
    make_blurred_qimage,
    primary_brush,
    rasterize_studio_sprite,
    rasterize_unlit_karaoke_sprite,
)
from ui.subtitle_vfx import (
    VFX_MODES,
    VFX_TRAIL_KEYS,
    _tinted_rgb_sprites,
    clear_vfx_caches,
    paint_blackhole_singularity,
    paint_choreo_accent,
    paint_supernova_shockwave,
    paint_vfx_optical_entrance,
    paint_vfx_optical_exit,
    sprite_vfx_style_for,
)

STUDIO_TRAILS = (
    ('karaoke_pro', 'AMLL · Lướt chữ lụa & nâng nhịp'),
    ('supernova_embers', 'Mưa sao băng & tàn lửa Supernova'),
    ('thunder_chain', 'Chuỗi sét điện từ phân nhánh'),
    ('bass_visualizer', 'Thanh sóng nhạc Equalizer Bass'),
    ('cyber_laser', 'Tia Laser quét dọc từng dòng'),
    ('nebula_orbit', 'Tinh vân quỹ đạo Ngân Hà'),
    ('star_confetti', 'Pháo sao 4 cánh đa sắc'),
    ('phoenix_embers', 'Tàn lửa bay ngược'),
    ('prism_flare', 'Tia lóe lăng kính'),
    ('meteor_shower', 'Mưa sao băng'),
    ('electric_arc', 'Tia chớp điện từ'),
    ('neon_pulse', 'Neon · Xung ánh sáng mượt'),
    ('spotlight', 'Aegisub · Vệt sáng dịu mắt'),
    ('lyric_bar', 'Thanh nhịp ánh sáng'),
)
ALL_TRAILS = (TRAILS[0],) + STUDIO_TRAILS + TRAILS[1:]

ENTRANCES = (
    ('none', 'Không chuyển động'),
    ('vfx_beat_char_pop', 'Nhịp Từng Chữ · Bay theo beat'),
    ('vfx_char_orbit_snap', 'Xoáy Từng Chữ · Quỹ đạo & khóa'),
    ('vfx_char_cascade_drop', 'Mưa Từng Chữ · Rơi nảy từng chữ'),
    ('vfx_scatter_leap', 'Bung Tung Tóe · Nổ & nhảy ghép'),
    ('vfx_supernova_shatter', 'Siêu Tân Tinh · Bung nổ 360°'),
    ('vfx_saber_slash', 'Nhất Kiếm Sét · Chém xéo ánh thép'),
    ('vfx_bass_drop_3d', 'Đập Bass 3D · Rung chấn & sóng âm RGB'),
    ('vfx_cyber_glitch_pro', 'Cyber Glitch · Xé dải RGB & Laser'),
    ('vfx_blackhole_warp', 'Hố Đen · Xoáy hút kỳ dị & bung quỹ đạo'),
    ('vfx_magnet_assemble', 'Từ Tính Ghép · Tách & hút khóa'),
    ('vfx_cyclone_sweep', 'Cơn Lốc Cuốn · Gió cuốn & đáp'),
    ('vfx_firework_bloom', 'Pháo Hoa Rơi · Nở bung từ tâm'),
    ('vfx_glass_shatter', 'Gương Vỡ 3D · Mảnh kính phẳng'),
    ('vfx_amll_silk_pro', 'AMLL Sing · Tan mờ quang học mượt'),
    ('vfx_elastic_bounce_pro', 'CapCut · Bật nảy co giãn đàn hồi'),
    ('vfx_liquid_fire', 'Hỏa Diễm · Sóng lửa bay ngược'),
    ('vfx_3d_domino_flip', 'Domino 3D · Lật thẻ ánh kim'),
    ('vfx_cinema_clean', 'Điện Ảnh · Focus Blur & Lens Flare'),
    ('editor_shatter_rebirth', 'MV · Bung mảnh & nhảy ghép câu'),
    ('editor_trampoline', 'CapCut · Nảy lò xo đàn hồi'),
    ('editor_tornado_magnet', 'AE · Xoáy lốc & nam châm hút chữ'),
    ('editor_katana_slice', 'Anime · Chém đôi tia sáng'),
    ('editor_flip_cascade', '3D · Lật thẻ Domino sân khấu'),
    ('editor_matrix_decode', 'Cyber · Giải mã Matrix'),
    ('editor_blur_in', 'AMLL · Tan mờ vào nét (Focus)'),
    ('editor_pop', 'CapCut · Bật nảy từng từ'),
    ('editor_whip', 'MV · Vút ngang tốc độ (Whip)'),
    ('editor_wave', 'MV · Sóng lượn từng từ (Wave)'),
    ('editor_glitch', 'Cyber · Nháy RGB lệch màu'),
    ('editor_slam', 'Bass · Đập nhịp chấn động (Slam)'),
    ('silk_rise', 'Trượt êm Apple Music'),
    ('cinema_focus', 'Hội tụ điện ảnh'),
    ('drop', 'Chữ rơi nhẹ'),
    ('rise', 'Trượt lên'),
    ('left', 'Trượt từ trái'),
    ('right', 'Trượt từ phải'),
    ('zoom', 'Thu phóng nhẹ'),
    ('bounce', 'Nảy nhẹ'),
    ('reveal', 'Mở từ giữa'),
    ('burst', 'Bừng sao khi vào câu'),
    ('swing', 'Lắc nhẹ rồi ổn định'),
    ('flutter', 'Lượn nhẹ khi vào câu'),
) + KINETIC_ENTRANCES

COLORS = (
    ('original', 'Màu chữ gốc'),
    ('fire_gold', 'Lửa vàng rực rỡ'),
    ('sakura_neon', 'Anh đào Neon'),
    ('matrix_lime', 'Lục bảo Cyber'),
    ('cyber_neon', 'Neon Cyberpunk'),
    ('sunset_fire', 'Hoàng hôn rực lửa'),
    ('pearl', 'Trắng ngọc điện ảnh'),
    ('gold', 'Vàng kim sân khấu'),
    ('rose_ice', 'Pha lê hồng băng'),
    ('shift', 'Chuyển sang ngọc lam'),
    ('mint', 'Gradient ngọc lam'),
    ('sunset', 'Gradient hoàng hôn'),
    ('ocean', 'Gradient đại dương'),
    ('pastel', 'Cầu vồng pastel'),
)

STUDIO_ONLY_COLORS = frozenset({
    'fire_gold', 'sakura_neon', 'matrix_lime',
    'cyber_neon', 'sunset_fire', 'pearl', 'gold', 'rose_ice',
})
STUDIO_ONLY_ENTRANCES = frozenset({
    'editor_shatter_rebirth', 'editor_trampoline', 'editor_tornado_magnet',
    'editor_katana_slice', 'editor_flip_cascade', 'editor_matrix_decode',
    'editor_pop', 'editor_blur_in', 'editor_whip', 'editor_wave',
    'editor_glitch', 'editor_slam', 'silk_rise', 'cinema_focus',
}) | VFX_MODES
STUDIO_TRAIL_KEYS = frozenset({
    'karaoke_pro', 'meteor_shower', 'electric_arc',
    'neon_pulse', 'spotlight', 'lyric_bar',
}) | VFX_TRAIL_KEYS

DEFAULTS = dict(
    enabled=False,
    entrance='drop',
    color='original',
    soft_fade=True,
    glow=False,
    shimmer=False,
    duration=320,
    trail='none',
    intensity='gentle',
    erase_passed=False,
    kinetic_strength='normal',
    kinetic_parts='auto',
)

PRESETS = (
    ('custom', 'Tùy chỉnh', {}),
    ('ninja', 'Phi tiêu ánh bạc', dict(entrance='burst', color='ocean', trail='shuriken', intensity='normal', erase_passed=True)),
    ('stars', 'Bầu trời sao', dict(entrance='burst', color='mint', trail='sparkles', intensity='normal', erase_passed=True)),
    ('comet', 'Sao băng xanh', dict(entrance='rise', color='ocean', trail='comet', intensity='normal', erase_passed=True)),
    ('garden', 'Vườn đom đóm', dict(entrance='flutter', color='mint', trail='fireflies', intensity='gentle')),
    ('sakura', 'Cánh hoa hoàng hôn', dict(entrance='flutter', color='sunset', trail='petals', intensity='normal')),
    ('winter', 'Tuyết pha lê', dict(entrance='drop', color='ocean', trail='snow', intensity='gentle')),
    ('bubble', 'Bong bóng mơ màng', dict(entrance='zoom', color='pastel', trail='bubbles', intensity='gentle')),
    ('crystal', 'Tinh thể tím', dict(entrance='swing', color='pastel', trail='diamonds', intensity='normal', erase_passed=True)),
    ('aurora', 'Cực quang', dict(entrance='rise', color='mint', trail='ribbon', intensity='normal')),
    ('rain', 'Mưa chữ mạnh', dict(entrance='kinetic_drop', color='ocean', trail='sparkles',
        intensity='normal', kinetic_strength='bold', kinetic_parts='glyph', duration=480, soft_fade=False)),
    ('domino', 'Domino bật nảy', dict(entrance='kinetic_spring', color='mint', trail='diamonds',
        intensity='gentle', kinetic_strength='bold', kinetic_parts='word', duration=480, soft_fade=False)),
    ('explosion', 'Bùng nổ typography', dict(entrance='kinetic_scatter', color='sunset', trail='sparkles',
        intensity='normal', kinetic_strength='bold', kinetic_parts='auto', duration=480, soft_fade=False)),
    ('galaxy', 'Xoáy ngân hà', dict(entrance='kinetic_vortex', color='pastel', trail='ribbon',
        intensity='normal', kinetic_strength='normal', kinetic_parts='word', duration=480, soft_fade=False)),
    ('cinema', 'Lật chữ điện ảnh', dict(entrance='kinetic_flip', color='ocean', trail='diamonds',
        intensity='gentle', kinetic_strength='normal', kinetic_parts='word', duration=480, soft_fade=False)),
    ('waves', 'Sóng chữ neon', dict(entrance='kinetic_wave', color='mint', trail='comet',
        intensity='gentle', kinetic_strength='bold', kinetic_parts='auto', duration=480, soft_fade=False)),
    ('typewriter', 'Máy chữ ánh sáng', dict(entrance='kinetic_type', color='pastel', trail='fireflies',
        intensity='gentle', kinetic_strength='normal', kinetic_parts='glyph', duration=480, soft_fade=False)),
    ('impact', 'Nhịp chữ mạnh', dict(entrance='kinetic_slam', color='sunset', trail='sparkles',
        intensity='normal', kinetic_strength='bold', kinetic_parts='word', duration=480, soft_fade=False)),
    ('editor_capcut', 'CapCut · Karaoke lướt sáng', dict(entrance='editor_pop', color='cyber_neon', trail='karaoke_pro',
        intensity='normal', duration=360, glow=True, soft_fade=True)),
    ('editor_ae_focus', 'AE · Mờ nét điện ảnh', dict(entrance='editor_blur_in', color='pearl', trail='spotlight',
        intensity='normal', duration=360, glow=True, shimmer=True, soft_fade=True)),
    ('editor_cyber_glitch', 'Cyber · Nháy RGB Glitch', dict(entrance='editor_glitch', color='cyber_neon', trail='sparkles',
        intensity='normal', duration=280, glow=True, soft_fade=True)),
    ('editor_whip_mv', 'MV · Vút ngang Neon', dict(entrance='editor_whip', color='sunset_fire', trail='neon_pulse',
        intensity='normal', duration=320, glow=True, soft_fade=True)),
    ('editor_shatter', 'MV · Bung mảnh & nhảy ghép', dict(entrance='editor_shatter_rebirth', color='fire_gold', trail='meteor_shower',
        intensity='normal', duration=520, glow=True, soft_fade=False)),
    ('editor_trampoline', 'CapCut · Nảy lò xo đàn hồi', dict(entrance='editor_trampoline', color='sakura_neon', trail='sparkles',
        intensity='normal', duration=500, glow=True, soft_fade=False)),
    ('editor_tornado', 'AE · Xoáy lốc nam châm', dict(entrance='editor_tornado_magnet', color='cyber_neon', trail='neon_pulse',
        intensity='normal', duration=520, glow=True, soft_fade=False)),
    ('editor_katana', 'Anime · Chém đôi Katana', dict(entrance='editor_katana_slice', color='matrix_lime', trail='electric_arc',
        intensity='normal', duration=400, glow=True, soft_fade=False)),
    ('editor_domino3d', '3D · Lật Domino sân khấu', dict(entrance='editor_flip_cascade', color='sunset_fire', trail='diamonds',
        intensity='normal', duration=480, glow=True, soft_fade=False)),
    ('vfx_supernova', 'Siêu Tân Tinh · Bung nổ & sao băng', dict(entrance='vfx_supernova_shatter', color='fire_gold', trail='supernova_embers',
        intensity='normal', duration=540, glow=True, soft_fade=False)),
    ('vfx_saber', 'Nhất Kiếm Sét · Chém xéo & sét nhánh', dict(entrance='vfx_saber_slash', color='matrix_lime', trail='thunder_chain',
        intensity='normal', duration=440, glow=True, soft_fade=False)),
    ('vfx_bass3d', 'Đập Bass 3D · Rung chấn & sóng nhạc', dict(entrance='vfx_bass_drop_3d', color='cyber_neon', trail='bass_visualizer',
        intensity='normal', duration=460, glow=True, soft_fade=False)),
    ('vfx_glitch2077', 'Cyber Glitch · Xé RGB & Laser', dict(entrance='vfx_cyber_glitch_pro', color='cyber_neon', trail='cyber_laser',
        intensity='normal', duration=420, glow=True, soft_fade=False)),
    ('vfx_blackhole', 'Hố Đen · Xoáy kỳ dị & tinh vân', dict(entrance='vfx_blackhole_warp', color='sakura_neon', trail='nebula_orbit',
        intensity='normal', duration=540, glow=True, soft_fade=False)),
    ('vfx_amll_pro', 'AMLL Sing · Lướt lụa Apple Music', dict(entrance='vfx_amll_silk_pro', color='gold', trail='karaoke_pro',
        intensity='normal', duration=440, glow=True, soft_fade=True)),
    ('vfx_beat_char', 'Nhịp Từng Chữ · Bay & nảy theo beat', dict(entrance='vfx_beat_char_pop', color='cyber_neon', trail='bass_visualizer',
        intensity='normal', duration=540, glow=True, soft_fade=False)),
    ('vfx_char_orbit', 'Xoáy Từng Chữ · Quỹ đạo & sao', dict(entrance='vfx_char_orbit_snap', color='mint', trail='star_confetti',
        intensity='normal', duration=520, glow=True, soft_fade=False)),
    ('vfx_char_drop', 'Mưa Từng Chữ · Rơi nảy từng chữ', dict(entrance='vfx_char_cascade_drop', color='fire_gold', trail='supernova_embers',
        intensity='normal', duration=540, glow=True, soft_fade=False)),
    ('vfx_scatter_leap', 'Bung Tung Tóe · Nổ & nhảy vào vị trí', dict(entrance='vfx_scatter_leap', color='fire_gold', trail='supernova_embers',
        intensity='normal', duration=520, glow=True, soft_fade=False)),
    ('vfx_magnet', 'Từ Tính Ghép · Tách 4 phía & hút khóa', dict(entrance='vfx_magnet_assemble', color='mint', trail='prism_flare',
        intensity='normal', duration=480, glow=True, soft_fade=False)),
    ('vfx_cyclone', 'Cơn Lốc Cuốn · Gió xoáy & đáp mượt', dict(entrance='vfx_cyclone_sweep', color='ocean', trail='neon_pulse',
        intensity='normal', duration=480, glow=True, soft_fade=False)),
    ('vfx_firework', 'Pháo Hoa Rơi · Nở bung & sao đa sắc', dict(entrance='vfx_firework_bloom', color='sunset_fire', trail='star_confetti',
        intensity='normal', duration=500, glow=True, soft_fade=False)),
    ('vfx_glass', 'Gương Vỡ 3D · Mảnh kính & tia điện', dict(entrance='vfx_glass_shatter', color='rose_ice', trail='electric_arc',
        intensity='normal', duration=480, glow=True, soft_fade=False)),
    ('vfx_capcut_bounce', 'Nảy CapCut · Bật nảy & pháo sao', dict(entrance='vfx_elastic_bounce_pro', color='sakura_neon', trail='star_confetti',
        intensity='normal', duration=520, glow=True, soft_fade=False)),
    ('vfx_domino3d', 'Lật 3D · Thẻ ánh kim & lăng kính', dict(entrance='vfx_3d_domino_flip', color='sunset_fire', trail='prism_flare',
        intensity='normal', duration=480, glow=True, soft_fade=False)),
    ('vfx_cinema', 'Điện Ảnh · Focus Blur & Lens Flare', dict(entrance='vfx_cinema_clean', color='ocean', trail='spotlight',
        intensity='gentle', duration=440, glow=True, soft_fade=True)),
    ('vfx_phoenix', 'Hỏa Diễm · Sóng lửa & tàn lửa bay', dict(entrance='vfx_liquid_fire', color='fire_gold', trail='phoenix_embers',
        intensity='normal', duration=500, glow=True, soft_fade=False)),
)


def normalize_options(value):
    """Validate one new preference subtree without rewriting legacy settings."""
    value = value if isinstance(value, dict) else {}
    result = dict(DEFAULTS)
    for key in ('enabled', 'soft_fade', 'glow', 'shimmer', 'erase_passed'):
        if isinstance(value.get(key), bool):
            result[key] = value[key]
    for key, choices in (('entrance', ENTRANCES), ('color', COLORS),
                         ('trail', ALL_TRAILS), ('intensity', INTENSITIES),
                         ('kinetic_strength', STRENGTHS), ('kinetic_parts', PARTS)):
        if isinstance(value.get(key), str) and value[key] in {choice[0] for choice in choices}:
            result[key] = value[key]
    duration = value.get('duration')
    if isinstance(duration, int) and not isinstance(duration, bool):
        result['duration'] = min(600, max(160, duration))
    return result


class SubtitleEffects(QObject):
    """One finite 60 FPS animation per cue, with pre-warmed cached paths & sprites."""
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
        self._blur_sprite_key = None
        self._blur_sprite = None
        self._unlit_sprite_key = None
        self._unlit_sprite = None
        self._unlit_origin = QPointF()
        self._prewarm_sprite_key = None
        self._prewarm_sprite = None
        self._prewarm_origin = QPointF()
        self._prewarm_blur_sprite = None
        self._prewarm_unlit_key = None
        self._prewarm_unlit_sprite = None
        self._prewarm_unlit_origin = QPointF()
        self._exit_ghost = None
        self._audio_ema = 0.0
        self._audio_beat = 0.0
        self._audio_beat_phase = 0.0
        self._audio_last_t = 0.0
        self.particles = ParticlePainter(label)
        self.kinetic = KineticPainter(label)
        self.scan_progress = 1.0
        self._scan_ms = None
        self._native_raw = None
        self._smooth_pts_ms = None
        self._scan_clock = QElapsedTimer()
        self._paint_throttle = QElapsedTimer()
        self._paint_throttle.start()
        self._particle_timer = QTimer(self)
        self._particle_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._particle_timer.setInterval(16)
        self._particle_timer.timeout.connect(self._tick_particles)
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._frame)
        label.installEventFilter(self)

    def _release_sprites(self):
        self._sprite_key = None
        self._sprite = None
        self._blur_sprite_key = None
        self._blur_sprite = None
        self._unlit_sprite_key = None
        self._unlit_sprite = None
        self._prewarm_sprite_key = None
        self._prewarm_sprite = None
        self._prewarm_blur_sprite = None
        self._prewarm_unlit_key = None
        self._prewarm_unlit_sprite = None
        self._exit_ghost = None
        clear_vfx_caches()

    def configure(self, value):
        self.options = normalize_options(value)
        self._release_sprites()
        self.clear()
        self.cue = None
        self.last_ms = None
        self.label.update()

    def _frame(self, value):
        self.progress = float(value)
        if self.label.isVisible():
            self._paint_throttle.restart()
            self.label.update()

    def settle(self):
        anim = getattr(self, 'animation', None)
        if anim is not None:
            try:
                anim.stop()
            except RuntimeError:
                pass
        changed = getattr(self, 'progress', 1.0) != 1.0
        self.progress = 1.0
        if changed:
            lbl = getattr(self, 'label', None)
            if lbl is not None:
                try:
                    lbl.update()
                except RuntimeError:
                    pass

    def freeze_for_fade(self):
        """Hold the settled cue sprite/particles steady while SubtitleLayer fades out."""
        timer = getattr(self, '_particle_timer', None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        self._scan_ms = None
        self._native_raw = None
        self._smooth_pts_ms = None
        self.scan_progress = 1.0
        self.settle()

    def clear(self):
        self.settle()
        timer = getattr(self, '_particle_timer', None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        if hasattr(self, 'particles'):
            self.particles.clear()
        if hasattr(self, 'kinetic'):
            self.kinetic.clear()
        self.scan_progress = 1.0
        self._scan_ms = None
        self._native_raw = None
        self._smooth_pts_ms = None
        self._exit_ghost = None
        self._audio_beat = 0.0
        self.cue = None
        self.last_ms = None

    def wants_audio_beat(self) -> bool:
        """True only when active subtitle VFX consumes passive read-only beat energy."""
        return bool(
            self.options.get('enabled')
            and (
                self.options.get('entrance') in PER_CHAR_MODES
                or self.options.get('trail') == 'bass_visualizer'
            )
        )

    def feed_audio_samples(self, audio_data) -> None:
        """Passive read-only WASAPI energy detector (~4 us, zero audio path impact)."""
        if not self.wants_audio_beat() or not self.label.isVisible() or audio_data is None:
            return
        try:
            if _np is not None:
                arr = _np.asarray(audio_data)
                if arr.size == 0:
                    return
                sample = arr[::8] if arr.shape[0] > 16 else arr
                energy = float(_np.mean(_np.abs(sample)))
            else:
                energy = 0.0
        except Exception:
            return
        now = time.monotonic()
        self._audio_last_t = now
        prev_ema = self._audio_ema
        self._audio_ema = energy if prev_ema <= 1e-6 else (prev_ema * 0.86 + energy * 0.14)
        ratio = energy / max(0.015, self._audio_ema)
        if ratio > 1.18 and energy > 0.02:
            strength = min(1.0, (ratio - 1.12) * 1.35)
            if strength > self._audio_beat:
                self._audio_beat = strength
                self._audio_beat_phase = (self._audio_beat_phase + 0.27) % 1.0
        else:
            # Keep soft continuous breath on sustained vocals/synths
            floor = min(0.32, energy * 1.4)
            self._audio_beat = max(floor, self._audio_beat * 0.90)

    def current_beat_pulse(self) -> tuple[float, float]:
        """Return (pulse 0..1, wave_phase 0..1) from live WASAPI audio or 120 BPM preview fallback."""
        now = time.monotonic()
        if self._audio_last_t > 0.0 and (now - self._audio_last_t) < 0.45:
            return min(1.0, max(0.0, self._audio_beat)), self._audio_beat_phase
        # Deterministic 120 BPM musical beat pulse for preview box & offline video export
        pts = self._smooth_pts_ms
        if pts is None:
            pts = float(self.last_ms if self.last_ms is not None else 0.0)
        beat_pos = (pts / 480.0) % 1.0
        pulse = (1.0 - beat_pos) ** 2.6 if beat_pos < 0.55 else 0.0
        wave_phase = (pts / 1440.0) % 1.0
        return float(pulse), float(wave_phase)

    def finish_erase_sweep_for_fade(self):
        """Freeze the completed sweep while SubtitleLayer fades the cue out."""
        if (not self.options['enabled'] or self.options['trail'] == 'none'
                or not self.options['erase_passed'] or self.cue is None
                or self.cue[2] - self.cue[1] < 160):
            return False
        changed = self.scan_progress != 1.0
        self._particle_timer.stop()
        self._scan_ms = None
        self._native_raw = None
        self.scan_progress = 1.0
        self.settle()
        if changed:
            self.label.update()
        return True

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
            self.clear()
        elif event.type() == QEvent.Type.Show:
            self._arm_particles()
        return False

    def bind_player(self, player):
        self.player = player
        player.playbackStateChanged.connect(self._state_changed)
        player.playbackRateChanged.connect(self._rate_changed)
        player.mediaStatusChanged.connect(self._media_status_changed)
        player.sourceChanged.connect(self._source_changed)

    def _source_changed(self, source):
        self._release_sprites()
        self.clear()

    def _media_status_changed(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status in (QMediaPlayer.MediaStatus.StalledMedia, QMediaPlayer.MediaStatus.LoadingMedia,
                      QMediaPlayer.MediaStatus.NoMedia, QMediaPlayer.MediaStatus.InvalidMedia,
                      QMediaPlayer.MediaStatus.EndOfMedia):
            self._particle_timer.stop()
        elif self.cue is not None:
            self._arm_particles()

    def _state_changed(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.PlaybackState.PlayingState:
            if self.label.isVisible() and self.animation.state() == QAbstractAnimation.State.Paused:
                self.animation.resume()
            self._arm_particles()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            if self.animation.state() == QAbstractAnimation.State.Running:
                self.animation.pause()
            self._particle_timer.stop()
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
        if changed and not seek and self.cue is not None and self._sprite is not None and self.options['entrance'] in CHOREO_EXIT_MODES and self.label.isVisible():
            sp = self._sprite
            origin = QPointF(self._sprite_origin)
            dpr = max(1.0, float(sp.devicePixelRatio()))
            sp_bounds = QRectF(origin.x(), origin.y(), sp.width() / dpr, sp.height() / dpr)
            ent_mode = self.options['entrance']
            if ent_mode in ('vfx_saber_slash', 'vfx_cyber_glitch_pro', 'editor_katana_slice'):
                self._exit_ghost = {
                    'sprite': sp,
                    'origin': origin,
                    'mode': ent_mode,
                    'tiles': [],
                    'bounds': sp_bounds,
                }
            else:
                tiles = self.kinetic.snapshot_tiles(sp, origin, ent_mode, self.options['duration'], prefer_cached=True)
                if tiles:
                    self._exit_ghost = {
                        'sprite': sp,
                        'origin': origin,
                        'mode': ent_mode,
                        'tiles': tiles,
                        'bounds': sp_bounds,
                    }
        elif seek:
            self._exit_ghost = None
        self.cue, self.last_ms = cue, pts_ms
        self._sync_particles(pts_ms, reset_smooth=(changed or seek or force))
        # Static gradients/glow need no timer. Never animate across a short cue.
        cue_len = max(0, cue[2] - cue[1])
        if self.options['entrance'] in PER_CHAR_MODES and cue_len >= 900:
            eff_dur = min(900, max(self.options['duration'], int(self.options['duration'] * 1.55)))
            duration = max(1, min(eff_dur, int(cue_len * 0.56)))
        else:
            duration = max(1, min(self.options['duration'], int(cue_len / 2)))
        elapsed = max(0, pts_ms - cue[1])
        moving = (self.options['entrance'] != 'none' or self.options['soft_fade']
                  or self.options['shimmer'] or self.options['color'] == 'shift')
        if elapsed >= duration or not moving:
            self._exit_ghost = None
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

    def replay_preview_with_exit(self, text: str, next_text: str | None = None):
        """Play dual-cue outgoing explosion + incoming rebuild inside preview box."""
        old_txt = (text or '').strip()
        new_txt = (next_text if next_text is not None else old_txt).strip()
        if not old_txt or self.options['entrance'] not in CHOREO_EXIT_MODES:
            if new_txt and new_txt != self.label.text():
                self.label.setText(new_txt)
            self.clear()
            self.sync((0, 0, 3000, new_txt), 0)
            return
        if self._sprite is None and hasattr(self.label, 'contentsRect'):
            plan = build_typography_plan(
                old_txt,
                self.label.font(),
                self.label.contentsRect(),
                tuple(getattr(self.label, 'sweep_row_groups', ()) or ()),
                False,
            )
            self._static_sprite(plan.full_path, plan.full_bounds)
        if self._sprite is not None:
            sp = self._sprite
            origin = QPointF(self._sprite_origin)
            dpr = max(1.0, float(sp.devicePixelRatio()))
            sp_bounds = QRectF(origin.x(), origin.y(), sp.width() / dpr, sp.height() / dpr)
            tiles = self.kinetic.snapshot_tiles(sp, origin, self.options['entrance'], self.options['duration'])
            self._exit_ghost = {
                'sprite': sp,
                'origin': origin,
                'mode': self.options['entrance'],
                'tiles': tiles,
                'bounds': sp_bounds,
            } if tiles else None
        prev_ghost = self._exit_ghost
        self.clear()
        if new_txt and new_txt != self.label.text():
            self.label.setText(new_txt)
        self._exit_ghost = prev_ghost
        next_id = 1 if (self.cue is None or self.cue[0] == 0) else 0
        self.sync((next_id, 0, 3000, new_txt), 0)

    def _sync_particles(self, pts_ms, reset_smooth=False):
        self._scan_ms = pts_ms
        self._native_raw = pts_ms
        if reset_smooth or self._smooth_pts_ms is None or pts_ms < self._smooth_pts_ms - 250 or pts_ms > self._smooth_pts_ms + 300:
            self._smooth_pts_ms = float(pts_ms)
        else:
            self._smooth_pts_ms = max(self._smooth_pts_ms, float(pts_ms))
        self._scan_clock.restart()
        self.scan_progress = min(1.0, max(0.0, (self._smooth_pts_ms - self.cue[1]) / max(1, self.cue[2] - self.cue[1])))
        self._arm_particles()

    def _arm_particles(self):
        if (not self.options['enabled'] or self.options['trail'] == 'none'
                or self.cue is None or not self.label.isVisible()
                or self.cue[2] - self.cue[1] < 160 or self.scan_progress >= 1.0):
            self._particle_timer.stop()
            return
        if self.player:
            from PySide6.QtMultimedia import QMediaPlayer
            if (self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
                    or self.player.mediaStatus() in (QMediaPlayer.MediaStatus.StalledMedia,
                        QMediaPlayer.MediaStatus.LoadingMedia, QMediaPlayer.MediaStatus.NoMedia,
                        QMediaPlayer.MediaStatus.InvalidMedia, QMediaPlayer.MediaStatus.EndOfMedia)):
                self._particle_timer.stop()
                return
        if not self._particle_timer.isActive():
            self._scan_clock.restart()
            self._particle_timer.start()

    def _tick_particles(self):
        if not self.label.isVisible() or self.cue is None:
            self._particle_timer.stop()
            return
        if self.player:
            from PySide6.QtMultimedia import QMediaPlayer
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self._particle_timer.stop()
                return
            native_ms = self.player.position()
            if native_ms < self.cue[1] or native_ms > self.cue[2]:
                self.scan_progress = 1.0
                self._particle_timer.stop()
                self.label.update()
                return
            if native_ms != self._native_raw:
                self._native_raw = native_ms
                self._scan_clock.restart()
            rate = max(0.1, float(self.player.playbackRate()))
            est_ms = native_ms + min(90, self._scan_clock.elapsed()) * rate
            # Never snap backward on coarse Windows WMF/FFmpeg position ticks, and never end before native_ms reaches cue[2]
            if self._smooth_pts_ms is not None and abs(est_ms - self._smooth_pts_ms) < 250.0:
                pts_ms = max(self._smooth_pts_ms, est_ms)
            else:
                pts_ms = est_ms
            pts_ms = min(float(self.cue[2]), pts_ms)
            self._smooth_pts_ms = pts_ms
        else:
            pts_ms = (self._scan_ms or 0) + self._scan_clock.elapsed()
            if pts_ms < self.cue[1] or pts_ms > self.cue[2]:
                self.scan_progress = 1.0
                self._particle_timer.stop()
                self.label.update()
                return
            self._smooth_pts_ms = float(pts_ms)
        progress = min(1.0, max(0.0, (pts_ms - self.cue[1]) / max(1, self.cue[2] - self.cue[1])))
        if self._audio_beat > 0.005:
            self._audio_beat *= 0.86
        if progress != self.scan_progress and (abs(progress - self.scan_progress) >= 0.0012 or progress >= 1.0):
            self.scan_progress = progress
            anim_running = self.animation.state() == QAbstractAnimation.State.Running
            if not anim_running and (progress >= 1.0 or not self._paint_throttle.isValid() or self._paint_throttle.elapsed() >= 11):
                self._paint_throttle.restart()
                self.label.update()
        if progress >= 1.0 and (not self.player or self._native_raw is None or self._native_raw >= self.cue[2]):
            self._particle_timer.stop()

    def _use_studio_rendering(self) -> bool:
        return bool(
            self.options['color'] in STUDIO_ONLY_COLORS
            or self.options['entrance'] in STUDIO_ONLY_ENTRANCES
            or self.options['trail'] in STUDIO_TRAIL_KEYS
        )

    def _brush(self, bounds, original):
        return primary_brush(self.options['color'], bounds, original, self.progress)

    def _draw_static(self, painter, path, bounds, plan=None):
        if self._use_studio_rendering():
            if plan is None:
                plan = build_typography_plan(
                    self.label.text(),
                    self.label.font(),
                    self.label.contentsRect(),
                    tuple(getattr(self.label, 'sweep_row_groups', ()) or ()),
                    False,
                    bottom_align=getattr(self.label, '_song_stage_size', None) is not None,
                )
            draw_studio_text_layers(
                painter,
                plan,
                font_color=self.label.current_color,
                color_mode=self.options['color'],
                progress=1.0,
                use_shadow=self.label.use_shadow,
                shadow_alpha=self.label.shadow_alpha,
                use_outline=self.label.use_outline,
                outline_width=self.label.outline_width,
                outline_color=self.label.outline_color,
                glow=self.options['glow'],
                draw_fill=(self.options['color'] != 'shift'),
            )
            return
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

    def _sprite_cache_key(self, text, width, height, row_groups, dpr):
        vfx_style = sprite_vfx_style_for(self.options['entrance'], self.options['glow'])
        return (
            text,
            self.label.font().key(),
            width,
            height,
            self.label.current_color,
            self.label.use_shadow,
            self.label.shadow_alpha,
            self.label.use_outline,
            self.label.outline_width,
            self.label.outline_color,
            self.options['color'],
            self.options['glow'],
            vfx_style,
            row_groups,
            False,
            round(float(dpr), 3),
        )

    def prewarm_plan(self, plan, text, size, dpr):
        """Pre-render the next upcoming cue's static DPR sprite without mutating active state."""
        if not self.options['enabled']:
            return
        row_groups = tuple(line.group for line in plan.lines)
        key = self._sprite_cache_key(text, size.width(), size.height(), row_groups, dpr)
        if key == self._sprite_key or key == self._prewarm_sprite_key:
            return
        studio_mode = self._use_studio_rendering()
        vfx_style = sprite_vfx_style_for(self.options['entrance'], self.options['glow'])
        sprite, origin = rasterize_studio_sprite(
            plan,
            dpr=dpr,
            font_color=self.label.current_color,
            color_mode=self.options['color'],
            use_shadow=self.label.use_shadow,
            shadow_alpha=self.label.shadow_alpha,
            use_outline=self.label.use_outline,
            outline_width=self.label.outline_width,
            outline_color=self.label.outline_color,
            glow=self.options['glow'],
            studio_mode=studio_mode,
            vfx_style=vfx_style,
        )
        if sprite is not None:
            self._prewarm_sprite_key = key
            self._prewarm_sprite = sprite
            self._prewarm_origin = origin
            need_blur = (
                self.options['entrance'] in (
                    'editor_blur_in', 'editor_whip', 'editor_slam', 'editor_pop', 'editor_wave',
                    'vfx_amll_silk_pro', 'vfx_cinema_clean', 'vfx_saber_slash', 'vfx_bass_drop_3d',
                )
                or getattr(self.label, 'use_fade_effect', False)
            )
            self._prewarm_blur_sprite = make_blurred_qimage(sprite, 2, 3) if need_blur else None
        if self.options['trail'] == 'karaoke_pro':
            u_key = (
                text,
                self.label.font().key(),
                size.width(),
                size.height(),
                self.label.use_shadow,
                self.label.shadow_alpha,
                self.label.use_outline,
                self.label.outline_width,
                self.label.outline_color,
                round(float(dpr), 3),
            )
            if u_key != self._unlit_sprite_key and u_key != self._prewarm_unlit_key:
                u_sprite, u_origin = rasterize_unlit_karaoke_sprite(
                    plan,
                    dpr=dpr,
                    use_shadow=self.label.use_shadow,
                    shadow_alpha=self.label.shadow_alpha,
                    use_outline=self.label.use_outline,
                    outline_width=self.label.outline_width,
                    outline_color=self.label.outline_color,
                )
                if u_sprite is not None:
                    self._prewarm_unlit_key = u_key
                    self._prewarm_unlit_sprite = u_sprite
                    self._prewarm_unlit_origin = u_origin

    def _ensure_blur_sprite(self, sprite):
        if sprite is None:
            return None
        if self._blur_sprite_key == self._sprite_key and self._blur_sprite is not None:
            return self._blur_sprite
        blur = make_blurred_qimage(sprite, 2, 3)
        self._blur_sprite_key = self._sprite_key
        self._blur_sprite = blur
        return blur

    def _ensure_unlit_sprite(self, path):
        dpr = self.label.devicePixelRatioF()
        key = (
            self.label.text(),
            self.label.font().key(),
            self.label.size().width(),
            self.label.size().height(),
            self.label.use_shadow,
            self.label.shadow_alpha,
            self.label.use_outline,
            self.label.outline_width,
            self.label.outline_color,
            round(float(dpr), 3),
        )
        if key == self._unlit_sprite_key and self._unlit_sprite is not None:
            return self._unlit_sprite, self._unlit_origin
        if key == self._prewarm_unlit_key and self._prewarm_unlit_sprite is not None:
            self._unlit_sprite_key = key
            self._unlit_sprite = self._prewarm_unlit_sprite
            self._unlit_origin = self._prewarm_unlit_origin
            self._prewarm_unlit_key = None
            self._prewarm_unlit_sprite = None
            return self._unlit_sprite, self._unlit_origin
        plan = getattr(self.label, '_cached_plan', None)
        if plan is None:
            plan = build_typography_plan(
                self.label.text(),
                self.label.font(),
                self.label.contentsRect(),
                tuple(getattr(self.label, 'sweep_row_groups', ()) or ()),
                False,
                bottom_align=getattr(self.label, '_song_stage_size', None) is not None,
            )
        sprite, origin = rasterize_unlit_karaoke_sprite(
            plan,
            dpr=dpr,
            use_shadow=self.label.use_shadow,
            shadow_alpha=self.label.shadow_alpha,
            use_outline=self.label.use_outline,
            outline_width=self.label.outline_width,
            outline_color=self.label.outline_color,
        )
        self._unlit_sprite_key = key
        self._unlit_sprite = sprite
        self._unlit_origin = origin
        return sprite, origin

    def _static_sprite(self, path, bounds):
        dpr = self.label.devicePixelRatioF()
        row_groups = tuple(getattr(self.label, 'sweep_row_groups', ()) or ())
        key = self._sprite_cache_key(
            self.label.text(),
            self.label.size().width(),
            self.label.size().height(),
            row_groups,
            dpr,
        )
        if key == self._sprite_key:
            return self._sprite
        if key == self._prewarm_sprite_key and self._prewarm_sprite is not None:
            self._sprite_key = key
            self._sprite = self._prewarm_sprite
            self._sprite_origin = self._prewarm_origin
            if self._prewarm_blur_sprite is not None:
                self._blur_sprite_key = key
                self._blur_sprite = self._prewarm_blur_sprite
            self._prewarm_sprite_key = None
            self._prewarm_sprite = None
            self._prewarm_blur_sprite = None
            return self._sprite

        self._sprite_key, self._sprite = key, None
        plan = getattr(self.label, '_cached_plan', None)
        if self._use_studio_rendering() and plan is not None:
            vfx_style = sprite_vfx_style_for(self.options['entrance'], self.options['glow'])
            sprite, origin = rasterize_studio_sprite(
                plan,
                dpr=dpr,
                font_color=self.label.current_color,
                color_mode=self.options['color'],
                use_shadow=self.label.use_shadow,
                shadow_alpha=self.label.shadow_alpha,
                use_outline=self.label.use_outline,
                outline_width=self.label.outline_width,
                outline_color=self.label.outline_color,
                glow=self.options['glow'],
                studio_mode=True,
                vfx_style=vfx_style,
            )
            if sprite is not None:
                self._sprite, self._sprite_origin = sprite, origin
            return self._sprite

        rect = bounds.adjusted(-10, -10, 10, 10)
        width, height = max(1, math.ceil(rect.width() * dpr)), max(1, math.ceil(rect.height() * dpr))
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
        self._draw_static(painter, path, bounds, plan=plan)
        painter.end()
        self._sprite, self._sprite_origin = image, rect.topLeft()
        return self._sprite

    def _draw_sprite_crop(self, painter, img, origin, crop=None):
        if img is None:
            return False
        if crop is None:
            painter.drawImage(origin, img)
            return True
        dpr = img.devicePixelRatio()
        target = crop.intersected(QRectF(origin.x(), origin.y(), img.width() / dpr, img.height() / dpr))
        if target.isEmpty():
            return True
        source = QRectF(
            (target.left() - origin.x()) * dpr,
            (target.top() - origin.y()) * dpr,
            target.width() * dpr,
            target.height() * dpr,
        )
        painter.drawImage(target, img, source)
        return True

    def _draw_editor_optical_layers(self, painter, sprite, path, bounds, mode, p):
        """Render AMLL / AE optical Gaussian focus blur, directional whip wake, RGB glitch, or bass slam."""
        if sprite is None or p >= 1.0:
            return False
        base_op = painter.opacity()
        quint = 1.0 - (1.0 - p) ** 4
        remain = 1.0 - quint
        blur_img = self._ensure_blur_sprite(sprite)
        dpr = max(1.0, float(sprite.devicePixelRatio()))
        dest = QRectF(
            self._sprite_origin.x(),
            self._sprite_origin.y(),
            sprite.width() / dpr,
            sprite.height() / dpr,
        )

        if mode == 'editor_blur_in':
            if blur_img is not None and remain > 0.01:
                painter.save()
                painter.setOpacity(base_op * (0.92 * remain))
                painter.drawImage(dest, blur_img)
                painter.restore()
            painter.save()
            painter.setOpacity(base_op * (0.38 + 0.62 * quint))
            painter.drawImage(self._sprite_origin, sprite)
            painter.restore()
            return True

        if mode == 'editor_whip':
            trail_dx = -44.0 * remain
            if blur_img is not None and abs(trail_dx) > 0.4:
                painter.save()
                painter.setOpacity(base_op * (0.58 * remain))
                painter.drawImage(dest.translated(trail_dx * 0.55, 0.0), blur_img)
                painter.restore()
            painter.drawImage(self._sprite_origin, sprite)
            return True

        if mode == 'editor_glitch':
            jitter = math.sin(p * math.pi * 11.0) * 6.5 * remain
            split = 7.0 * remain
            pair = _tinted_rgb_sprites(sprite)
            if pair is not None:
                painter.save()
                painter.setOpacity(base_op * 0.44 * remain)
                painter.drawImage(self._sprite_origin + QPointF(-split + jitter, -0.8), pair[0])
                painter.drawImage(self._sprite_origin + QPointF(split - jitter, 0.8), pair[1])
                painter.restore()
            painter.drawImage(self._sprite_origin + QPointF(jitter * 0.4, 0.0), sprite)
            return True

        if mode == 'editor_slam':
            if p < 0.72:
                shock_scale = 1.0 + 0.30 * p
                center = bounds.center()
                painter.save()
                painter.setOpacity(base_op * 0.50 * (1.0 - p / 0.72))
                painter.translate(center.x(), center.y())
                painter.scale(shock_scale, shock_scale)
                painter.translate(-center.x(), -center.y())
                if blur_img is not None:
                    painter.drawImage(dest, blur_img)
                else:
                    painter.drawImage(self._sprite_origin, sprite)
                painter.restore()
            painter.drawImage(self._sprite_origin, sprite)
            return True

        if mode == 'editor_katana_slice':
            shear = 52.0 * remain
            mid_y = bounds.center().y()
            top_clip = QRectF(dest.left() - 64.0, dest.top() - 24.0, dest.width() + 128.0, (mid_y - dest.top()) + 24.0)
            bot_clip = QRectF(dest.left() - 64.0, mid_y, dest.width() + 128.0, (dest.bottom() - mid_y) + 24.0)
            for clip_r, shift_x in ((top_clip, shear), (bot_clip, -shear)):
                painter.save()
                painter.setClipRect(clip_r, Qt.ClipOperation.IntersectClip)
                painter.setOpacity(base_op * min(1.0, p * 3.8))
                if blur_img is not None and p < 0.38:
                    painter.drawImage(dest.translated(shift_x, 0.0), blur_img)
                painter.drawImage(self._sprite_origin + QPointF(shift_x, 0.0), sprite)
                painter.restore()
            if p < 0.65:
                flash_a = math.sin((p / 0.65) * math.pi)
                slash_grad = QLinearGradient(bounds.left() - 28.0, mid_y, bounds.right() + 28.0, mid_y)
                slash_grad.setColorAt(0.0, QColor(34, 211, 238, 0))
                slash_grad.setColorAt(0.5, QColor(255, 255, 255, int(235 * flash_a)))
                slash_grad.setColorAt(1.0, QColor(52, 211, 153, 0))
                painter.save()
                painter.setPen(QPen(slash_grad, 2.2 * (1.0 - p / 0.65) + 0.8))
                painter.drawLine(QPointF(bounds.left() - 24.0, mid_y), QPointF(bounds.right() + 24.0, mid_y))
                painter.restore()
            return True

        return False

    def paint(self, painter, path):
        if not self.options['enabled']:
            return False
        painter.save()
        bounds = path.boundingRect()
        p = self.progress
        eased = 1 - (1 - p) ** 3
        remaining = 1 - eased
        mode = self.options['entrance']
        drew_blackhole_portal = False
        if self._exit_ghost is not None:
            if p < 0.60:
                out_p = p / 0.60
                ghost = self._exit_ghost
                g_mode = ghost.get('mode')
                if g_mode == 'vfx_supernova_shatter':
                    paint_supernova_shockwave(painter, ghost['bounds'].center(), ghost['bounds'], out_p, is_exit=True)
                elif g_mode == 'vfx_blackhole_warp':
                    # Single unified portal across the entire dual-cue warp transition (no overlapping double vortex)
                    portal_center = QPointF(
                        (ghost['bounds'].center().x() + bounds.center().x()) * 0.5,
                        (ghost['bounds'].center().y() + bounds.center().y()) * 0.5,
                    )
                    paint_blackhole_singularity(painter, portal_center, bounds, p, is_exit=False)
                    drew_blackhole_portal = True
                elif g_mode in ('vfx_firework_bloom', 'vfx_glass_shatter'):
                    paint_choreo_accent(painter, ghost['bounds'].center(), ghost['bounds'], g_mode, out_p, is_exit=True)
                if g_mode in ('vfx_saber_slash', 'vfx_cyber_glitch_pro'):
                    paint_vfx_optical_exit(painter, ghost, out_p)
                elif g_mode == 'editor_katana_slice':
                    g_sp = ghost['sprite']
                    g_org = ghost['origin']
                    g_b = ghost['bounds']
                    g_dpr = max(1.0, float(g_sp.devicePixelRatio()))
                    g_dest = QRectF(g_org.x(), g_org.y(), g_sp.width() / g_dpr, g_sp.height() / g_dpr)
                    g_mid = g_b.center().y()
                    out_op = max(0.0, 1.0 - out_p)
                    for clip_r, sh in (
                        (QRectF(g_dest.left() - 80, g_dest.top() - 20, g_dest.width() + 160, g_mid - g_dest.top() + 20), -46.0 * out_p),
                        (QRectF(g_dest.left() - 80, g_mid, g_dest.width() + 160, g_dest.bottom() - g_mid + 20), 46.0 * out_p),
                    ):
                        painter.save()
                        painter.setClipRect(clip_r, Qt.ClipOperation.IntersectClip)
                        painter.setOpacity(painter.opacity() * out_op)
                        painter.drawImage(g_org + QPointF(sh, 0.0), g_sp)
                        painter.restore()
                else:
                    painter.save()
                    self.kinetic.paint_exit_ghost(painter, ghost, out_p)
                    painter.restore()
            else:
                self._exit_ghost = None
        if p < 1.0:
            if mode == 'vfx_supernova_shatter' and p >= 0.14:
                paint_supernova_shockwave(painter, bounds.center(), bounds, (p - 0.14) / 0.86, is_exit=False)
            elif mode == 'vfx_blackhole_warp' and not drew_blackhole_portal:
                paint_blackhole_singularity(painter, bounds.center(), bounds, p, is_exit=False)
            elif mode in ('vfx_firework_bloom', 'vfx_glass_shatter', 'vfx_magnet_assemble'):
                paint_choreo_accent(painter, bounds.center(), bounds, mode, p, is_exit=False)
        travel = min(18.0, max(5.0, self.label.current_font_size * .45))
        dx = dy = 0.0
        scale = 1.0
        if mode in ('editor_blur_in', 'vfx_amll_silk_pro', 'vfx_cinema_clean'):
            quint = 1 - (1 - p) ** 4
            scale = (1.06 if mode == 'vfx_amll_silk_pro' else 1.12) - (0.06 if mode == 'vfx_amll_silk_pro' else 0.12) * quint
            dy = (10.0 * (1.0 - quint)) if mode == 'vfx_amll_silk_pro' else 0.0
            eased = quint
        elif mode == 'editor_whip':
            quint = 1 - (1 - p) ** 5
            dx = -54.0 * (1.0 - quint)
            eased = quint
        elif mode == 'editor_slam':
            quint = 1 - (1 - p) ** 4
            scale = 1.44 - 0.44 * quint
            eased = quint
        elif mode == 'editor_glitch':
            eased = min(1.0, p * 2.5)
        elif mode == 'silk_rise':
            quint = 1 - (1 - p) ** 5
            dy = min(12.0, max(5.0, self.label.current_font_size * .35)) * (1.0 - quint)
            scale = 0.97 + 0.03 * quint
            eased = quint
        elif mode == 'cinema_focus':
            quint = 1 - (1 - p) ** 4
            scale = 0.96 + 0.04 * quint
            eased = quint
        elif mode == 'drop':
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
        elif mode == 'burst':
            scale = .94 + .06 * eased
        elif mode == 'swing':
            dx = travel * remaining * math.sin(p * math.pi * 3)
        elif mode == 'flutter':
            dx = travel * remaining * math.sin(p * math.pi * 2)
            dy = -travel * remaining * .5
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
        if self.options['soft_fade'] and mode not in ('editor_blur_in', 'vfx_amll_silk_pro', 'vfx_cinema_clean'):
            painter.setOpacity(painter.opacity() * (.35 + .65 * eased))
        painter.setTransform(transform, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        sprite = self._static_sprite(path, bounds)
        trail = self.options['trail']
        decorative = ((trail != 'none' or mode == 'burst') and self.cue is not None
                      and self.cue[2] - self.cue[1] >= 160)
        if decorative and self.cue is not None:
            self.particles.prepare(max(0, self.cue[2] - self.cue[1]))
        regions = [(QRegion(rect.toAlignedRect()), alpha) for rect, alpha in
            self.particles.morph_regions(self.scan_progress, trail,
            self.options['intensity'])] if decorative else []
        hidden = QRegion()
        erase_sweep = decorative and trail != 'none' and self.options['erase_passed']
        if erase_sweep:
            hidden, regions = self.particles.sweep_masks(self.scan_progress)

        karaoke_sweep = (
            decorative and trail == 'karaoke_pro' and not erase_sweep
            and self.scan_progress < 1.0 and bool(self.particles.rows)
        )
        unlit_sprite = None
        unlit_origin = QPointF()
        if karaoke_sweep:
            unlit_sprite, unlit_origin = self._ensure_unlit_sprite(path)
            if unlit_sprite is None:
                karaoke_sweep = False

        def draw_shimmer():
            if self.options['shimmer'] and p < 1.0:
                x = bounds.left() + (bounds.width() + 60) * p - 30
                gradient = QLinearGradient(x - 24, 0, x + 24, 0)
                gradient.setColorAt(0, QColor(255, 255, 255, 0))
                gradient.setColorAt(.5, QColor(255, 255, 255, 135))
                gradient.setColorAt(1, QColor(255, 255, 255, 0))
                painter.fillPath(path, gradient)

        def _paint_karaoke_split(crop=None):
            rows = self.particles.rows
            row_groups = self.particles._row_group_ids
            targets = self.particles.targets(self.scan_progress)
            w_full = float(self.label.size().width())
            h_full = float(self.label.size().height())
            track_order = []
            for g in row_groups:
                if g not in track_order:
                    track_order.append(g)

            for r_idx, row in enumerate(rows):
                if not row:
                    continue
                top = 0.0 if r_idx == 0 else (rows[r_idx - 1][0].rect.bottom() + row[0].rect.top()) / 2.0
                bottom = h_full if r_idx == len(rows) - 1 else (row[0].rect.bottom() + rows[r_idx + 1][0].rect.top()) / 2.0
                band = QRectF(0.0, top, w_full, max(1.0, bottom - top))
                if crop is not None:
                    band = band.intersected(crop)
                    if band.isEmpty():
                        continue

                g_id = row_groups[r_idx] if r_idx < len(row_groups) else r_idx
                active_tuple = None
                if g_id in track_order:
                    t_i = track_order.index(g_id)
                    if t_i < len(targets):
                        active_tuple = targets[t_i]

                if active_tuple is None:
                    self._draw_sprite_crop(painter, sprite, self._sprite_origin, band)
                    continue

                active_reg, local_p, split_x = active_tuple
                if active_reg not in row:
                    if row[0].rect.center().y() < active_reg.rect.center().y():
                        self._draw_sprite_crop(painter, sprite, self._sprite_origin, band)
                    else:
                        self._draw_sprite_crop(painter, unlit_sprite, unlit_origin, band)
                    continue

                act_idx = row.index(active_reg)
                word_left = (
                    band.left() if act_idx == 0
                    else (row[act_idx - 1].rect.right() + active_reg.rect.left()) * 0.5
                )
                word_right = (
                    band.right() if act_idx == len(row) - 1
                    else (active_reg.rect.right() + row[act_idx + 1].rect.left()) * 0.5
                )
                word_left = max(band.left(), min(band.right(), word_left))
                word_right = max(word_left, min(band.right(), word_right))

                if word_left > band.left():
                    pre_rect = QRectF(band.left(), band.top(), word_left - band.left(), band.height())
                    painter.save()
                    painter.setClipRect(pre_rect, Qt.ClipOperation.IntersectClip)
                    self._draw_sprite_crop(painter, sprite, self._sprite_origin, pre_rect)
                    painter.restore()

                if band.right() > word_right:
                    post_rect = QRectF(word_right, band.top(), band.right() - word_right, band.height())
                    painter.save()
                    painter.setClipRect(post_rect, Qt.ClipOperation.IntersectClip)
                    self._draw_sprite_crop(painter, unlit_sprite, unlit_origin, post_rect)
                    painter.restore()

                word_band = QRectF(word_left, band.top(), word_right - word_left, band.height())
                if not word_band.isEmpty():
                    base_op = painter.opacity()
                    clamped_p = min(1.0, max(0.0, float(local_p)))
                    lift_env = math.sin(clamped_p * math.pi)
                    lift_dy = -3.4 * (lift_env ** 0.78)
                    lift_s = 1.0 + 0.042 * lift_env
                    w_center = active_reg.rect.center()

                    painter.save()
                    painter.translate(w_center.x(), w_center.y() + lift_dy)
                    painter.scale(lift_s, lift_s)
                    painter.translate(-w_center.x(), -w_center.y())
                    painter.setClipRect(word_band.adjusted(-3.0, -6.0, 3.0, 6.0), Qt.ClipOperation.IntersectClip)

                    self._draw_sprite_crop(painter, unlit_sprite, unlit_origin, word_band)

                    feather = min(32.0, max(12.0, active_reg.rect.width() * 0.45))
                    f_start = max(word_left, min(word_right, split_x - feather * 0.5))
                    f_end = max(f_start, min(word_right, split_x + feather * 0.5))

                    if f_start > word_left:
                        lit_solid = QRectF(word_left, word_band.top(), f_start - word_left, word_band.height())
                        self._draw_sprite_crop(painter, sprite, self._sprite_origin, lit_solid)

                    steps = 5
                    step_w = (f_end - f_start) / steps
                    if step_w > 0.25:
                        for s_i in range(steps):
                            sx0 = f_start + s_i * step_w
                            strip = QRectF(sx0, word_band.top(), step_w + 0.4, word_band.height())
                            alpha_t = 1.0 - (s_i + 0.5) / steps
                            painter.setOpacity(base_op * (alpha_t ** 1.15))
                            self._draw_sprite_crop(painter, sprite, self._sprite_origin, strip)
                    painter.restore()

        def draw_blurred_crop(crop=None):
            blur_img = self._ensure_blur_sprite(sprite)
            if blur_img is None or sprite is None:
                return
            dpr = max(1.0, float(sprite.devicePixelRatio()))
            dest = QRectF(
                self._sprite_origin.x(),
                self._sprite_origin.y(),
                sprite.width() / dpr,
                sprite.height() / dpr,
            )
            if crop is None:
                painter.drawImage(dest, blur_img)
                return
            target = crop.intersected(dest)
            if target.isEmpty():
                return
            sx_s = blur_img.width() / max(1e-3, dest.width())
            sy_s = blur_img.height() / max(1e-3, dest.height())
            src = QRectF(
                (target.left() - dest.left()) * sx_s,
                (target.top() - dest.top()) * sy_s,
                target.width() * sx_s,
                target.height() * sy_s,
            )
            painter.drawImage(target, blur_img, src)

        def draw_letters(crop=None):
            if karaoke_sweep and sprite is not None:
                if crop is None and p < 1.0 and mode in ('editor_blur_in', 'vfx_amll_silk_pro'):
                    blur_img = self._ensure_blur_sprite(sprite)
                    if blur_img is not None:
                        quint_b = 1.0 - (1.0 - p) ** 4
                        remain_b = 1.0 - quint_b
                        if remain_b > 0.01:
                            base_op = painter.opacity()
                            dpr_b = max(1.0, float(sprite.devicePixelRatio()))
                            dest_b = QRectF(
                                self._sprite_origin.x(),
                                self._sprite_origin.y(),
                                sprite.width() / dpr_b,
                                sprite.height() / dpr_b,
                            )
                            painter.save()
                            painter.setOpacity(base_op * (0.72 * remain_b))
                            painter.drawImage(dest_b, blur_img)
                            painter.restore()
                _paint_karaoke_split(crop)
                return
            if sprite is not None:
                if crop is None and p < 1.0 and mode in ('vfx_saber_slash', 'vfx_bass_drop_3d', 'vfx_cyber_glitch_pro', 'vfx_amll_silk_pro', 'vfx_cinema_clean'):
                    blur_img = self._ensure_blur_sprite(sprite)
                    if paint_vfx_optical_entrance(painter, sprite, self._sprite_origin, blur_img, path, bounds, mode, p):
                        if erase_sweep:
                            draw_shimmer()
                        return
                if crop is None and p < 1.0 and mode in ('editor_blur_in', 'editor_whip', 'editor_glitch', 'editor_slam', 'editor_katana_slice'):
                    if self._draw_editor_optical_layers(painter, sprite, path, bounds, mode, p):
                        if self.options['color'] == 'shift':
                            painter.fillPath(path, self._brush(bounds, QColor(self.label.current_color)))
                        if erase_sweep:
                            draw_shimmer()
                        return
                fade_anim = getattr(self.label, 'fade_anim', None)
                fade_out_op = float(getattr(self.label, '_opacity', 1.0))
                exiting_choreo = (
                    crop is None
                    and p >= 1.0
                    and not erase_sweep
                    and fade_anim is not None
                    and fade_anim.state() == QAbstractAnimation.State.Running
                    and fade_anim.endValue() == 0.0
                    and fade_out_op < 0.98
                    and mode in CHOREO_EXIT_MODES
                )
                if exiting_choreo:
                    out_p = min(1.0, max(0.0, 1.0 - fade_out_op))
                    # Hold full legibility briefly after cue end so lyrics never feel cut short, then play crisp full-opacity exit VFX
                    choreo_p = max(0.0, (out_p - 0.14) / 0.86)
                    painter.save()
                    painter.setOpacity(1.0)
                    if choreo_p <= 0.005:
                        self._draw_sprite_crop(painter, sprite, self._sprite_origin, crop)
                        painter.restore()
                        return
                    if mode == 'vfx_supernova_shatter':
                        paint_supernova_shockwave(painter, bounds.center(), bounds, choreo_p, is_exit=True)
                    elif mode == 'vfx_blackhole_warp':
                        paint_blackhole_singularity(painter, bounds.center(), bounds, choreo_p, is_exit=True)
                    elif mode in ('vfx_firework_bloom', 'vfx_glass_shatter'):
                        paint_choreo_accent(painter, bounds.center(), bounds, mode, choreo_p, is_exit=True)
                    if mode in ('vfx_saber_slash', 'vfx_cyber_glitch_pro'):
                        paint_vfx_optical_exit(
                            painter,
                            {'sprite': sprite, 'origin': self._sprite_origin, 'mode': mode, 'bounds': bounds},
                            choreo_p,
                        )
                        painter.restore()
                        return
                    tiles = self.kinetic.snapshot_tiles(sprite, self._sprite_origin, mode, self.options['duration'])
                    if tiles:
                        self.kinetic.paint_exit_ghost(
                            painter,
                            {'sprite': sprite, 'origin': self._sprite_origin, 'mode': mode, 'tiles': tiles, 'bounds': bounds},
                            choreo_p,
                        )
                        painter.restore()
                        return
                    painter.restore()
                exiting_blur = (
                    crop is None
                    and p >= 1.0
                    and fade_anim is not None
                    and fade_anim.state() == QAbstractAnimation.State.Running
                    and fade_anim.endValue() == 0.0
                    and fade_out_op < 0.98
                    and self._use_studio_rendering()
                )
                if exiting_blur:
                    blur_img = self._ensure_blur_sprite(sprite)
                    if blur_img is not None:
                        dpr = max(1.0, float(sprite.devicePixelRatio()))
                        dest = QRectF(
                            self._sprite_origin.x(),
                            self._sprite_origin.y(),
                            sprite.width() / dpr,
                            sprite.height() / dpr,
                        )
                        dissolve = max(0.0, (1.0 - fade_out_op - 0.12) / 0.88)
                        vis = max(0.0, 1.0 - dissolve * dissolve)
                        painter.save()
                        painter.setOpacity(vis * 0.65 * dissolve)
                        painter.drawImage(dest, blur_img)
                        painter.setOpacity(vis)
                        painter.drawImage(self._sprite_origin, sprite)
                        painter.restore()
                        if erase_sweep:
                            draw_shimmer()
                        return
                self._draw_sprite_crop(painter, sprite, self._sprite_origin, crop)
            else:
                self._draw_static(painter, path, bounds)
            if self.options['color'] == 'shift':
                painter.fillPath(path, self._brush(bounds, QColor(self.label.current_color)))
            if erase_sweep:
                draw_shimmer()

        def draw_masked_letters(crop=None):
            if regions or not hidden.isEmpty():
                painter.save()
                visible = QRegion(self.label.rect()).subtracted(hidden)
                for mask, alpha in regions:
                    visible = visible.subtracted(mask)
                painter.setClipRegion(visible, Qt.ClipOperation.IntersectClip)
                draw_letters(crop)
                painter.restore()
                for mask, alpha in regions:
                    painter.save()
                    painter.setClipRegion(mask, Qt.ClipOperation.IntersectClip)
                    painter.setOpacity(painter.opacity() * alpha)
                    draw_letters(crop)
                    painter.restore()
            else:
                draw_letters(crop)
            if not erase_sweep:
                draw_shimmer()

        self.kinetic.last_draw_count = 0
        cue_span = max(0, self.cue[2] - self.cue[1]) if self.cue else 0
        if mode in PER_CHAR_MODES and cue_span >= 900:
            entry_ms = min(900, max(self.options['duration'], int(self.options['duration'] * 1.55)), int(cue_span * 0.56))
        else:
            entry_ms = min(self.options['duration'], cue_span / 2)
        beat_pulse, beat_phase = self.current_beat_pulse() if (mode in PER_CHAR_MODES or trail == 'bass_visualizer') else (0.0, 0.0)
        fade_anim = getattr(self.label, 'fade_anim', None)
        is_fading_out = bool(
            fade_anim is not None
            and fade_anim.state() == QAbstractAnimation.State.Running
            and fade_anim.endValue() == 0.0
            and float(getattr(self.label, '_opacity', 1.0)) < 0.98
        )
        if mode in PER_CHAR_MODES and sprite is not None and not karaoke_sweep and not erase_sweep:
            if p < 1.0:
                animated = self.kinetic.paint_per_char(
                    painter, sprite, self._sprite_origin, mode, p, entry_ms,
                    blur_img=self._ensure_blur_sprite(sprite),
                )
            elif decorative and not is_fading_out and self.scan_progress < 0.99 and beat_pulse > 0.02:
                animated = self.kinetic.paint_per_char_beat(
                    painter, sprite, self._sprite_origin, self.scan_progress, beat_pulse, beat_phase,
                )
            else:
                animated = False
        elif mode in EDITOR_KINETIC_MODES and not karaoke_sweep:
            use_tile_blur = mode in ('editor_pop', 'editor_wave')
            animated = self.kinetic.paint_editor(
                painter, sprite, self._sprite_origin, mode, p, entry_ms,
                draw_masked_letters,
                draw_blurred=draw_blurred_crop if (use_tile_blur and self._ensure_blur_sprite(sprite) is not None) else None,
            )
        else:
            animated = (mode in KINETIC_MODES and self.kinetic.paint(
                painter, sprite, self._sprite_origin, mode, p,
                self.options['kinetic_strength'], self.options['kinetic_parts'],
                entry_ms, draw_masked_letters,
                limit=6 if (erase_sweep or self.options['color'] == 'shift' or self.options['shimmer']) else 16))
        if not animated:
            draw_masked_letters()
        if decorative:
            self.particles.paint(painter, self.scan_progress, trail, self.options['intensity'],
                                 p, burst=mode == 'burst', beat_pulse=beat_pulse)
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
