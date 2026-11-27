"""Studio subtitle rendering engine with DirectWrite + Numpy SIMD pipeline."""
from __future__ import annotations

import math
import sys
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

MAX_SPRITE_PIXELS = 2_000_000
MAX_CACHE_ENTRIES = 4
_LITTLE_ENDIAN = sys.byteorder == 'little'

PALETTE_STOPS = {
    'cyber_neon': ('#67E8F9', '#38BDF8', '#C084FC', '#F472B6'),
    'sunset_fire': ('#FEF9C3', '#FDBA74', '#FB7185'),
    'fire_gold': ('#FFFFFF', '#FEF08A', '#FB923C', '#EF4444'),
    'sakura_neon': ('#FFF1F2', '#F9A8D4', '#E879F9', '#818CF8'),
    'matrix_lime': ('#ECFCCB', '#86EFAC', '#34D399', '#22D3EE'),
    'pearl': ('#FFFFFF', '#F8FAFC', '#E2E8F0'),
    'gold': ('#FFFBEB', '#FDE68A', '#FBBF24'),
    'rose_ice': ('#FFF1F2', '#FECDD3', '#BAE6FD'),
    'mint': ('#D4FFF1', '#74DFC2', '#48B7BC'),
    'sunset': ('#FFD89B', '#FFAFBD', '#CBABFF'),
    'ocean': ('#B8F4FF', '#7CBFFF', '#C7B9FF'),
}

STUDIO_PROFILES = {
    'beat_char_pop': {
        'label': 'Nhịp Từng Chữ',
        'tooltip': 'Từng ký tự bay từ nhiều hướng, xoay & nảy vào câu theo nhịp beat rồi lần lượt bắn ra khi đổi câu',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#050811',
        'shadow_enabled': True,
        'shadow_alpha': 210,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_beat_char_pop',
            'color': 'cyber_neon',
            'trail': 'bass_visualizer',
            'intensity': 'normal',
            'duration': 540,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'char_orbit_snap': {
        'label': 'Xoáy Từng Chữ',
        'tooltip': 'Từng ký tự xoay theo quỹ đạo rồi khóa sắc nét vào vị trí kèm pháo sao 4 cánh',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#050811',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_char_orbit_snap',
            'color': 'mint',
            'trail': 'star_confetti',
            'intensity': 'normal',
            'duration': 520,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'char_cascade_drop': {
        'label': 'Mưa Từng Chữ',
        'tooltip': 'Từng ký tự rơi lần lượt từ trên xuống nảy đàn hồi rồi bật tung khi chuyển câu',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_char_cascade_drop',
            'color': 'fire_gold',
            'trail': 'supernova_embers',
            'intensity': 'normal',
            'duration': 540,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'scatter_leap': {
        'label': 'Bung Tung Tóe',
        'tooltip': 'Câu cũ nổ vỡ bay tung tóe tứ phía, câu mới bật nhảy đàn hồi vào đúng vị trí',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_scatter_leap',
            'color': 'fire_gold',
            'trail': 'supernova_embers',
            'intensity': 'normal',
            'duration': 520,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'supernova_shatter': {
        'label': 'Siêu Tân Tinh',
        'tooltip': 'Bung mảnh 360° kèm sóng xung kích và mưa sao băng',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 210,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_supernova_shatter',
            'color': 'fire_gold',
            'trail': 'supernova_embers',
            'intensity': 'normal',
            'duration': 540,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'saber_slash': {
        'label': 'Nhất Kiếm Sét',
        'tooltip': 'Chém xéo ánh thép tách câu kèm chuỗi sét phân nhánh',
        'font_color': '#F8FAFC',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#050811',
        'shadow_enabled': True,
        'shadow_alpha': 210,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_saber_slash',
            'color': 'matrix_lime',
            'trail': 'thunder_chain',
            'intensity': 'normal',
            'duration': 440,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'bass_drop_3d': {
        'label': 'Đập Bass 3D',
        'tooltip': 'Đập nhịp rung chấn RGB kèm thanh sóng nhạc Equalizer',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 215,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_bass_drop_3d',
            'color': 'cyber_neon',
            'trail': 'bass_visualizer',
            'intensity': 'normal',
            'duration': 460,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'cyber_glitch_pro': {
        'label': 'Cyber Glitch',
        'tooltip': 'Xé dải nhiễu RGB kèm tia Laser quét dọc từng dòng',
        'font_color': '#F8FAFC',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#050811',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_cyber_glitch_pro',
            'color': 'cyber_neon',
            'trail': 'cyber_laser',
            'intensity': 'normal',
            'duration': 420,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'blackhole_warp': {
        'label': 'Hố Đen',
        'tooltip': 'Hút xoáy vào chân trời sự kiện và bung quỹ đạo tinh vân',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 210,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_blackhole_warp',
            'color': 'sakura_neon',
            'trail': 'nebula_orbit',
            'intensity': 'normal',
            'duration': 540,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'amll_silk_pro': {
        'label': 'AMLL Sing',
        'tooltip': 'Tan mờ quang học mượt kèm lướt chữ karaoke và nâng nhẹ từng từ',
        'font_color': '#FFFDF7',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 195,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_amll_silk_pro',
            'color': 'gold',
            'trail': 'karaoke_pro',
            'intensity': 'normal',
            'duration': 440,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'elastic_bounce_pro': {
        'label': 'Nảy CapCut',
        'tooltip': 'Bật nảy co giãn đàn hồi kèm pháo sao 4 cánh',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 200,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_elastic_bounce_pro',
            'color': 'sakura_neon',
            'trail': 'star_confetti',
            'intensity': 'normal',
            'duration': 520,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'liquid_fire': {
        'label': 'Hỏa Diễm',
        'tooltip': 'Sóng lửa rực kèm tàn lửa bay ngược',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#12080A',
        'shadow_enabled': True,
        'shadow_alpha': 210,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_liquid_fire',
            'color': 'fire_gold',
            'trail': 'phoenix_embers',
            'intensity': 'normal',
            'duration': 500,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'domino_3d': {
        'label': 'Lật 3D',
        'tooltip': 'Lật thẻ 3D ánh kim nổi khối kèm tia lăng kính',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 200,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_3d_domino_flip',
            'color': 'sunset_fire',
            'trail': 'prism_flare',
            'intensity': 'normal',
            'duration': 480,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'cinema_clean': {
        'label': 'Điện Ảnh',
        'tooltip': 'Focus Blur rạp hát kèm vệt sáng Lens Flare và nền kính nhẹ',
        'font_color': '#F8FAFC',
        'bg_color': '#090D16',
        'bg_opacity': 0.45,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 185,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_cinema_clean',
            'color': 'ocean',
            'trail': 'spotlight',
            'intensity': 'gentle',
            'duration': 440,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'magnet_assemble': {
        'label': 'Từ Tính Ghép',
        'tooltip': 'Câu cũ trượt tách 4 hướng, câu mới hút từ tính khóa thẳng hàng kèm tia lăng kính',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_magnet_assemble',
            'color': 'mint',
            'trail': 'prism_flare',
            'intensity': 'normal',
            'duration': 480,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'cyclone_sweep': {
        'label': 'Cơn Lốc Cuốn',
        'tooltip': 'Câu cũ cuốn gió xoáy bay vút sang phải, câu mới lướt gió từ trái đáp mượt',
        'font_color': '#F8FAFC',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 200,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_cyclone_sweep',
            'color': 'ocean',
            'trail': 'neon_pulse',
            'intensity': 'normal',
            'duration': 480,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'firework_bloom': {
        'label': 'Pháo Hoa Rơi',
        'tooltip': 'Câu cũ bung tỏa như pháo hoa, câu mới nở nhảy từ tâm kèm pháo sao đa sắc',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_firework_bloom',
            'color': 'sunset_fire',
            'trail': 'star_confetti',
            'intensity': 'normal',
            'duration': 500,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'glass_shatter': {
        'label': 'Gương Vỡ 3D',
        'tooltip': 'Câu cũ vỡ mảnh kính nghiêng rơi xuống, câu mới ghép phẳng 3D kèm tia điện từ',
        'font_color': '#F8FAFC',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#050811',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'vfx_glass_shatter',
            'color': 'rose_ice',
            'trail': 'electric_arc',
            'intensity': 'normal',
            'duration': 480,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    # Legacy aliases preserved for existing saved settings & backwards compatibility
    'shatter_rebirth': {
        'label': '💥 Bung Chữ Nhảy',
        'tooltip': 'Câu cũ nổ bung tung téo 360°, câu mới nhảy đàn hồi ghép lại + Mưa sao băng',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_shatter_rebirth',
            'color': 'fire_gold',
            'trail': 'meteor_shower',
            'intensity': 'normal',
            'duration': 520,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'amll_live': {
        'label': '🎵 AMLL Karaoke',
        'tooltip': 'Phong cách Apple Music mượt: tan mờ Focus Blur, lướt chữ êm & nảy từng từ không giật',
        'font_color': '#FFFDF7',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 195,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_blur_in',
            'color': 'gold',
            'trail': 'karaoke_pro',
            'intensity': 'normal',
            'duration': 420,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'trampoline_pop': {
        'label': '🏀 Lò Xò Boing',
        'tooltip': 'Chữ rơi nảy lò xò đàn hồi 3 nhịp kiểu CapCut Pro + Sao lấp lánh',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 200,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_trampoline',
            'color': 'sakura_neon',
            'trail': 'sparkles',
            'intensity': 'normal',
            'duration': 500,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'tornado_magnet': {
        'label': '🌪️ Xoáy Nam Châm',
        'tooltip': 'Câu cũ xoáy lốc bay đi, câu mới xoáy quỹ đạo hút chặt vào dòng + Xung Neon',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 200,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_tornado_magnet',
            'color': 'cyber_neon',
            'trail': 'neon_pulse',
            'intensity': 'normal',
            'duration': 520,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'katana_cyber': {
        'label': '⚔️ Chém Đôi Neon',
        'tooltip': 'Chém ngang tia sáng Katana Anime ghép khớp tốc độ cao + Tia điện từ',
        'font_color': '#F8FAFC',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#060913',
        'shadow_enabled': True,
        'shadow_alpha': 205,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_katana_slice',
            'color': 'matrix_lime',
            'trail': 'electric_arc',
            'intensity': 'normal',
            'duration': 400,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'flip_domino': {
        'label': '🎴 Lật Domino 3D',
        'tooltip': 'Lật thẻ 3D liên hoàn từng từ + Bụi kim cương sân khấu',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 195,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_flip_cascade',
            'color': 'sunset_fire',
            'trail': 'diamonds',
            'intensity': 'normal',
            'duration': 480,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': False,
        },
    },
    'aegisub_mv': {
        'label': '🎬 Điện Ảnh MV',
        'tooltip': 'Hội tụ Gaussian Focus Blur chuẩn MV ca nhạc · Viền sắc nét điện ảnh',
        'font_color': '#F8FAFC',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 190,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_blur_in',
            'color': 'ocean',
            'trail': 'spotlight',
            'intensity': 'normal',
            'duration': 440,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'classic_clean': {
        'label': '✨ Thanh Lịch',
        'tooltip': 'Nền mờ dịu mắt + hiện mượt siêu nhẹ tối đa CPU',
        'font_color': '#FEF08A',
        'bg_color': '#090D16',
        'bg_opacity': 0.65,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 175,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'none',
            'color': 'original',
            'trail': 'none',
            'intensity': 'gentle',
            'duration': 240,
            'glow': False,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    # Legacy profile aliases preserved for saved config / test compatibility
    'capcut_neon': {
        'label': 'CapCut Neon',
        'tooltip': 'Bật nảy từng từ kiểu MV + hào quang Neon Cyberpunk siêu mượt',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 200,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_pop',
            'color': 'cyber_neon',
            'trail': 'neon_pulse',
            'intensity': 'normal',
            'duration': 360,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'capcut_karaoke': {
        'label': 'Karaoke Lướt',
        'tooltip': 'Bật nảy từng từ kiểu CapCut + chữ lướt sáng Neon Cyber',
        'font_color': '#FFFFFF',
        'bg_color': '#0B1120',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 195,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_pop',
            'color': 'cyber_neon',
            'trail': 'karaoke_pro',
            'intensity': 'normal',
            'duration': 360,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'ae_focus': {
        'label': 'Mờ Nét AE',
        'tooltip': 'Hiệu ứng tan mờ vào nét chuẩn After Effects + viền phát sáng nhẹ',
        'font_color': '#F8FAFC',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 190,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_blur_in',
            'color': 'pearl',
            'trail': 'spotlight',
            'intensity': 'normal',
            'duration': 380,
            'glow': True,
            'shimmer': True,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'bass_whip': {
        'label': 'Nhịp Bass MV',
        'tooltip': 'Vút ngang theo nhịp trống EDM/Pop + viền sáng Sunset Rực Lửa',
        'font_color': '#FFFFFF',
        'bg_color': '#090D16',
        'bg_opacity': 0.0,
        'outline_enabled': True,
        'outline_width': 3,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 210,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_whip',
            'color': 'sunset_fire',
            'trail': 'neon_pulse',
            'intensity': 'normal',
            'duration': 320,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
    'clean_cinema': {
        'label': 'Rạp Hát',
        'tooltip': 'Nền mờ sang trọng, chữ vàng dịu chuẩn phim & ballad',
        'font_color': '#FEF08A',
        'bg_color': '#090D16',
        'bg_opacity': 0.65,
        'outline_enabled': True,
        'outline_width': 2,
        'outline_color': '#090D16',
        'shadow_enabled': True,
        'shadow_alpha': 185,
        'fade_enabled': True,
        'subtitle_effects': {
            'enabled': True,
            'entrance': 'editor_blur_in',
            'color': 'gold',
            'trail': 'none',
            'intensity': 'gentle',
            'duration': 340,
            'glow': True,
            'shimmer': False,
            'erase_passed': False,
            'soft_fade': True,
        },
    },
}

STUDIO_PROFILE_ORDER = (
    'amll_silk_pro',
    'beat_char_pop',
    'scatter_leap',
    'char_orbit_snap',
    'char_cascade_drop',
    'supernova_shatter',
    'saber_slash',
    'bass_drop_3d',
    'cyber_glitch_pro',
    'blackhole_warp',
    'elastic_bounce_pro',
    'liquid_fire',
    'domino_3d',
    'magnet_assemble',
    'cyclone_sweep',
    'firework_bloom',
    'glass_shatter',
    'cinema_clean',
)

KARAOKE_RECOMMENDED_PROFILES = (
    'amll_silk_pro',
    'beat_char_pop',
    'elastic_bounce_pro',
    'liquid_fire',
    'cyber_glitch_pro',
)

KARAOKE_RECOMMENDED_TRAILS = frozenset({
    'karaoke_pro',
    'neon_pulse',
    'lyric_bar',
    'spotlight',
    'cyber_laser',
})

KARAOKE_RECOMMENDED_COLORS = frozenset({
    'gold',
    'fire_gold',
    'cyber_neon',
    'sakura_neon',
})


def detect_studio_profile(subtitle_effects: dict | None) -> str | None:
    """Detect which quick Studio profile matches saved/active subtitle_effects without migrating config schema."""
    if not isinstance(subtitle_effects, dict) or not subtitle_effects.get('enabled'):
        return None
    ent = subtitle_effects.get('entrance')
    col = subtitle_effects.get('color')
    trl = subtitle_effects.get('trail')
    glw = bool(subtitle_effects.get('glow', False))
    er = bool(subtitle_effects.get('erase_passed', False))
    for key in STUDIO_PROFILE_ORDER:
        fx = STUDIO_PROFILES[key]['subtitle_effects']
        if (
            fx.get('entrance') == ent
            and fx.get('color') == col
            and fx.get('trail') == trl
            and bool(fx.get('glow', False)) == glw
            and bool(fx.get('erase_passed', False)) == er
        ):
            return key
    return None


class TypographyLine:
    """Single formatted visual subtitle line ready for fast DirectWrite drawing."""

    __slots__ = (
        'text',
        'group',
        'is_secondary',
        'font',
        'x',
        'y_top',
        'baseline',
        'line_height',
        'ascent',
        'width',
    )

    def __init__(
        self,
        text: str,
        group: int,
        is_secondary: bool,
        font: QFont,
        x: float,
        y_top: float,
        baseline: float,
        line_height: float,
        ascent: float,
        width: float,
    ):
        self.text = text
        self.group = group
        self.is_secondary = is_secondary
        self.font = font
        self.x = x
        self.y_top = y_top
        self.baseline = baseline
        self.line_height = line_height
        self.ascent = ascent
        self.width = width


class TypographyPlan:
    """Layout plan storing uniform lines, exact bounds, and lazy QPainterPaths."""

    __slots__ = (
        'lines',
        'primary_bounds',
        'secondary_bounds',
        'full_bounds',
        'hierarchical',
        '_primary_path',
        '_secondary_path',
        '_full_path',
    )

    def __init__(
        self,
        lines: tuple[TypographyLine, ...],
        primary_bounds: QRectF,
        secondary_bounds: QRectF,
        full_bounds: QRectF,
        hierarchical: bool = False,
        primary_path: QPainterPath | None = None,
        secondary_path: QPainterPath | None = None,
        full_path: QPainterPath | None = None,
    ):
        self.lines = lines
        self.primary_bounds = primary_bounds
        self.secondary_bounds = secondary_bounds
        self.full_bounds = full_bounds
        self.hierarchical = hierarchical
        self._primary_path = primary_path
        self._secondary_path = secondary_path
        self._full_path = full_path

    def _ensure_paths(self) -> None:
        if self._full_path is not None:
            return
        primary_path = QPainterPath()
        secondary_path = QPainterPath()
        full_path = QPainterPath()
        for line in self.lines:
            part = QPainterPath()
            part.addText(QPointF(line.x, line.baseline), line.font, line.text)
            if line.is_secondary:
                secondary_path.addPath(part)
            else:
                primary_path.addPath(part)
            full_path.addPath(part)
        self._primary_path = primary_path
        self._secondary_path = secondary_path
        self._full_path = full_path

    @property
    def primary_path(self) -> QPainterPath:
        self._ensure_paths()
        return self._primary_path

    @property
    def secondary_path(self) -> QPainterPath:
        self._ensure_paths()
        return self._secondary_path

    @property
    def full_path(self) -> QPainterPath:
        self._ensure_paths()
        return self._full_path


def _line_width(fm: QFontMetricsF, text: str) -> float:
    return max(fm.horizontalAdvance(text), fm.boundingRect(text).width())


def _wrap_line(line: str, fm: QFontMetricsF, max_width: float) -> list[str]:
    if not line or max_width <= 40.0 or _line_width(fm, line) <= max_width:
        return [line]
    words = line.split()
    if len(words) <= 1:
        return [line]
    wrapped: list[str] = []
    cur = words[0]
    for word in words[1:]:
        candidate = f'{cur} {word}'
        if _line_width(fm, candidate) <= max_width:
            cur = candidate
        else:
            wrapped.append(cur)
            cur = word
    wrapped.append(cur)
    return wrapped


def _wrap_paragraphs(
    text: str,
    base_font: QFont,
    row_groups: tuple[int, ...] | list[int],
    max_width: float,
) -> list[tuple[str, int]]:
    # SubtitleLayer.smart_wrap and video_subtitle_export._display_text already own explicit '\n' wrapping
    # and match measure_box_size; never invent extra line splits that overflow the fixed widget height.
    paragraphs = text.split('\n') if text else []
    rows: list[tuple[str, int]] = []
    for idx, raw in enumerate(paragraphs):
        group = row_groups[idx] if idx < len(row_groups) else idx
        rows.append((raw, group))
    return rows


def make_phonetic_top_font(base_font: QFont) -> QFont:
    """Build a crisp ~76% DemiBold font for the optional top-line Romaji/Pinyin/Hangul row."""
    pf = QFont(base_font)
    base_px = base_font.pixelSize()
    if base_px <= 0:
        pt = base_font.pointSizeF()
        base_px = max(16, int(round((pt if pt > 0 else 18.0) * 1.333)))
    pf.setPixelSize(max(13, int(round(base_px * 0.76))))
    pf.setWeight(QFont.Weight.DemiBold)
    return pf


def measure_box_size(
    text: str,
    base_font: QFont,
    row_groups: tuple[int, ...] | list[int] = (),
    bilingual_hierarchy: bool = False,
    pad_left: int = 24,
    pad_right: int = 24,
    pad_top: int = 16,
    pad_bottom: int = 16,
    phonetic_top_group: int | None = None,
) -> tuple[int, int]:
    """Compute tight widget size around multi-line typography (with optional 76% phonetic top row)."""
    if not text:
        return pad_left + pad_right + 16, pad_top + pad_bottom + 24
    fm = QFontMetricsF(base_font)
    paragraphs = text.split('\n')
    max_w = 0.0
    total_h = 0.0
    line_gap = max(4.0, fm.lineSpacing() * 0.14)
    line_h = fm.lineSpacing()
    if phonetic_top_group is None:
        for idx, line in enumerate(paragraphs):
            if line:
                max_w = max(max_w, _line_width(fm, line))
            total_h += line_h
            if idx + 1 < len(paragraphs):
                total_h += line_gap
    else:
        pf_fm = QFontMetricsF(make_phonetic_top_font(base_font))
        pf_line_h = pf_fm.lineSpacing()
        pf_gap = max(3.0, pf_line_h * 0.12)
        for idx, line in enumerate(paragraphs):
            grp = row_groups[idx] if idx < len(row_groups) else idx
            is_phon = (grp == phonetic_top_group)
            cur_fm = pf_fm if is_phon else fm
            cur_h = pf_line_h if is_phon else line_h
            if line:
                max_w = max(max_w, _line_width(cur_fm, line))
            total_h += cur_h
            if idx + 1 < len(paragraphs):
                nxt_grp = row_groups[idx + 1] if (idx + 1) < len(row_groups) else (idx + 1)
                total_h += pf_gap if (is_phon and nxt_grp == phonetic_top_group) else (pf_gap + 1.0 if is_phon else line_gap)
    width = int(math.ceil(max_w + pad_left + pad_right + 28))
    height = int(math.ceil(total_h + pad_top + pad_bottom + 6))
    return max(width, 64), max(height, 38)


def build_typography_plan(
    text: str,
    base_font: QFont,
    contents_rect: QRect | QRectF,
    row_groups: tuple[int, ...] | list[int] = (),
    bilingual_hierarchy: bool = False,
    bottom_align: bool = False,
    phonetic_top_group: int | None = None,
) -> TypographyPlan:
    """Layout lines at 100% uniform size (plus optional 76% top phonetic row) without eager QPainterPath flattening."""
    rect = QRectF(contents_rect)
    if not text:
        empty = QRectF(rect.center(), rect.center())
        return TypographyPlan((), empty, empty, empty, False)

    avail_w = max(48.0, rect.width() - 8.0)
    rows = _wrap_paragraphs(text, base_font, row_groups, avail_w)
    if not rows:
        empty = QRectF(rect.center(), rect.center())
        return TypographyPlan((), empty, empty, empty, False)

    uniform_font = QFont(base_font)
    fm = QFontMetricsF(uniform_font)
    line_h = fm.lineSpacing()
    ascent = fm.ascent()
    descent = fm.descent()
    line_gap = max(4.0, line_h * 0.14)

    if phonetic_top_group is None:
        total_h = len(rows) * line_h + max(0, len(rows) - 1) * line_gap
        pf_font = uniform_font
        pf_fm = fm
        pf_line_h = line_h
        pf_ascent = ascent
        pf_descent = descent
        pf_gap = line_gap
    else:
        pf_font = make_phonetic_top_font(uniform_font)
        pf_fm = QFontMetricsF(pf_font)
        pf_line_h = pf_fm.lineSpacing()
        pf_ascent = pf_fm.ascent()
        pf_descent = pf_fm.descent()
        pf_gap = max(3.0, pf_line_h * 0.12)
        total_h = 0.0
        for idx, (_lt, grp) in enumerate(rows):
            is_phon = (grp == phonetic_top_group)
            total_h += pf_line_h if is_phon else line_h
            if idx + 1 < len(rows):
                nxt_grp = rows[idx + 1][1]
                total_h += pf_gap if (is_phon and nxt_grp == phonetic_top_group) else (pf_gap + 1.0 if is_phon else line_gap)

    if bottom_align:
        y_cursor = max(rect.top(), rect.bottom() - 4.0 - total_h)
    else:
        y_cursor = rect.center().y() - total_h / 2.0

    lines: list[TypographyLine] = []
    primary_bounds = QRectF()
    full_bounds = QRectF()

    for idx, (line_text, group) in enumerate(rows):
        is_phon = (phonetic_top_group is not None and group == phonetic_top_group)
        cur_font = pf_font if is_phon else uniform_font
        cur_fm = pf_fm if is_phon else fm
        cur_h = pf_line_h if is_phon else line_h
        cur_ascent = pf_ascent if is_phon else ascent
        cur_descent = pf_descent if is_phon else descent

        adv_w = _line_width(cur_fm, line_text) if line_text else 0.0
        x = rect.center().x() - adv_w / 2.0
        baseline = y_cursor + cur_ascent
        if line_text:
            tight = cur_fm.tightBoundingRect(line_text)
            glyph_left = min(x, x + tight.left())
            glyph_right = max(x + adv_w, x + tight.right())
            glyph_top = min(y_cursor, baseline + tight.top())
            glyph_bottom = max(baseline + cur_descent, baseline + tight.bottom())
            line_rect = QRectF(
                glyph_left - 2.0,
                glyph_top - 2.0,
                (glyph_right - glyph_left) + 4.0,
                (glyph_bottom - glyph_top) + 4.0,
            )
            primary_bounds = line_rect if primary_bounds.isNull() else primary_bounds.united(line_rect)
            full_bounds = line_rect if full_bounds.isNull() else full_bounds.united(line_rect)

        lines.append(
            TypographyLine(
                text=line_text,
                group=group,
                is_secondary=is_phon,
                font=cur_font,
                x=x,
                y_top=y_cursor,
                baseline=baseline,
                line_height=cur_h,
                ascent=cur_ascent,
                width=adv_w,
            )
        )
        if idx + 1 < len(rows):
            nxt_grp = rows[idx + 1][1]
            step_gap = (
                (pf_gap if nxt_grp == phonetic_top_group else pf_gap + 1.0)
                if is_phon
                else line_gap
            )
        else:
            step_gap = line_gap
        y_cursor += cur_h + step_gap

    return TypographyPlan(
        lines=tuple(lines),
        primary_bounds=primary_bounds,
        secondary_bounds=QRectF(),
        full_bounds=full_bounds,
        hierarchical=False,
    )


def iter_visual_lines(label) -> tuple[TypographyLine, ...]:
    """Return cached or freshly computed TypographyLines for a live or export label."""
    cached = getattr(label, '_cached_plan', None)
    text = label.text()
    rect = label.contentsRect()
    phonetic_top = getattr(label, 'phonetic_top_group', None)
    if (
        cached is not None
        and getattr(label, '_cached_text', None) == text
        and getattr(label, '_cached_size', None) == label.size()
    ):
        return cached.lines
    row_groups = tuple(getattr(label, 'sweep_row_groups', ()) or ())
    bottom_align = getattr(label, '_song_stage_size', None) is not None
    return build_typography_plan(
        text,
        label.font(),
        rect,
        row_groups,
        False,
        bottom_align=bottom_align,
        phonetic_top_group=phonetic_top,
    ).lines


def accent_glow_color(color_mode: str, base_color: str | QColor) -> QColor:
    """Match halo glow color to the active subtitle palette."""
    glow_map = {
        'cyber_neon': '#38BDF8',
        'sunset_fire': '#FB7185',
        'fire_gold': '#FB923C',
        'sakura_neon': '#E879F9',
        'matrix_lime': '#34D399',
        'gold': '#FBBF24',
        'pearl': '#CBD5E1',
        'rose_ice': '#F9A8D4',
        'shift': '#48B7BC',
        'mint': '#48B7BC',
        'sunset': '#FFAFBD',
        'ocean': '#7CBFFF',
        'pastel': '#CBABFF',
        'aurora': '#34D399',
        'emerald': '#34D399',
        'lavender': '#C084FC',
        'cherry': '#FB7185',
    }
    if color_mode in glow_map:
        return QColor(glow_map[color_mode])
    c = QColor(base_color)
    return c if c.isValid() else QColor('#7CBFFF')


def primary_brush(color_mode: str, bounds: QRectF, base_color: str | QColor, progress: float = 1.0):
    """Build text fill brush (flat color, interpolated shift, or multi-stop gradient)."""
    original = QColor(base_color)
    if not original.isValid():
        original = QColor('#FFFFFF')
    if color_mode in ('original', 'off', '', None):
        return original
    if color_mode == 'shift':
        target = QColor('#74DFC2')
        t = max(0.0, min(1.0, float(progress)))
        return QColor(
            round(original.red() + (target.red() - original.red()) * t),
            round(original.green() + (target.green() - original.green()) * t),
            round(original.blue() + (target.blue() - original.blue()) * t),
            original.alpha(),
        )
    stops = PALETTE_STOPS.get(color_mode)
    if not stops:
        return original
    gradient = QLinearGradient(bounds.left(), bounds.top(), bounds.right(), bounds.top())
    denom = max(1, len(stops) - 1)
    for idx, hex_color in enumerate(stops):
        gradient.setColorAt(idx / denom, QColor(hex_color))
    return gradient


def draw_cinema_pill(painter: QPainter, rect: QRect | QRectF, bg_color: str | QColor, bg_opacity: float) -> None:
    """Draw a smooth anti-aliased frosted glass pill behind subtitles."""
    opacity = max(0.0, min(1.0, float(bg_opacity)))
    if opacity <= 0.0:
        return
    r = QRectF(rect).adjusted(4.0, 4.0, -4.0, -4.0)
    if r.width() <= 4.0 or r.height() <= 4.0:
        return
    radius = min(14.0, r.height() * 0.28)
    base = QColor(bg_color)
    if not base.isValid():
        base = QColor('#090D16')
    base.setAlpha(int(round(255 * opacity)))

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(base)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(r, radius, radius)
    border = QColor(255, 255, 255, int(round(30 * opacity)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(border, 1.0))
    painter.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.restore()


# ---------------------------------------------------------------------------
# Numpy SIMD Engine: Circular Dilation + Half-Res Separable Gaussian Blur
# ---------------------------------------------------------------------------

def _rgba_view(img: QImage) -> tuple[np.ndarray, object]:
    """Return mutable (H, W, 4) uint8 numpy view matching bytesPerLine stride."""
    w, h = img.width(), img.height()
    ptr = img.bits()
    stride = img.bytesPerLine()
    buf = np.frombuffer(ptr, dtype=np.uint8, count=h * stride)
    arr = buf.reshape((h, stride))[:, : w * 4].reshape((h, w, 4))
    return arr, ptr


def _dilate_alpha_disk(alpha: np.ndarray, radius_px: float) -> np.ndarray:
    """Anti-aliased circular dilation using outer-ring + cardinal taps in SIMD."""
    r = float(radius_px)
    if r <= 0.05:
        return alpha
    r = min(r, 9.0)
    rad = int(math.ceil(r + 0.35))
    h, w = alpha.shape
    padded = np.pad(alpha, ((rad, rad), (rad, rad)), mode='constant')
    acc = alpha.copy()
    fringe = np.zeros_like(alpha)

    inner_limit = max(0.0, r - 0.35)
    ring_floor = max(0.0, r - 1.45)
    outer_limit = r + 0.45
    span = max(0.2, outer_limit - inner_limit)

    for dy in range(-rad, rad + 1):
        y0 = rad + dy
        for dx in range(-rad, rad + 1):
            if dx == 0 and dy == 0:
                continue
            dist = math.hypot(dx, dy)
            if dist > outer_limit:
                continue
            # Keep perimeter ring + cardinal hairline anchors, skip redundant deep interior taps
            if dist < ring_floor and not ((dx == 0 or dy == 0) and (abs(dx + dy) & 1 == 1)):
                continue
            x0 = rad + dx
            sl = padded[y0 : y0 + h, x0 : x0 + w]
            if dist <= inner_limit:
                np.maximum(acc, sl, out=acc)
            else:
                weight = max(0, min(255, int(round(((outer_limit - dist) / span) * 255.0))))
                if weight > 0:
                    np.maximum(fringe, ((sl.astype(np.uint16) * weight) >> 8).astype(np.uint8), out=fringe)
    np.maximum(acc, fringe, out=acc)
    return acc


def _binomial_blur_u16(buf: np.ndarray, passes: int = 2) -> np.ndarray:
    """Separable 5-tap [1, 4, 6, 4, 1] / 16 integer blur on uint16 (H, W[, C])."""
    work = buf.astype(np.uint16, copy=False)
    pad_tail = ((0, 0),) if work.ndim == 3 else ()
    for _ in range(max(1, passes)):
        px = np.pad(work, ((0, 0), (2, 2), *pad_tail), mode='constant')
        hx = (px[:, :-4] + (px[:, 1:-3] << 2) + px[:, 2:-2] * 6 + (px[:, 3:-1] << 2) + px[:, 4:]) >> 4
        py = np.pad(hx, ((2, 2), (0, 0), *pad_tail), mode='constant')
        work = (py[:-4, :] + (py[1:-3, :] << 2) + py[2:-2, :] * 6 + (py[3:-1, :] << 2) + py[4:, :]) >> 4
    return np.clip(work, 0, 255).astype(np.uint8)


def _upsample_2x_bilinear_u8(small: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Fast Numpy 2x bilinear upsample with zero Qt temporary allocations."""
    sh, sw = small.shape
    s16 = small.astype(np.uint16)
    s_r = np.empty_like(s16)
    s_r[:, :-1] = s16[:, 1:]
    s_r[:, -1] = s16[:, -1]
    s_d = np.empty_like(s16)
    s_d[:-1, :] = s16[1:, :]
    s_d[-1, :] = s16[-1, :]
    s_dr = np.empty_like(s16)
    s_dr[:-1, :] = s_r[1:, :]
    s_dr[-1, :] = s_r[-1, :]

    up = np.empty((sh * 2, sw * 2), dtype=np.uint8)
    up[0::2, 0::2] = s16
    up[0::2, 1::2] = (s16 + s_r) >> 1
    up[1::2, 0::2] = (s16 + s_d) >> 1
    up[1::2, 1::2] = (s16 + s_r + s_d + s_dr) >> 2
    if up.shape[0] >= target_h and up.shape[1] >= target_w:
        return up[:target_h, :target_w]
    out = np.zeros((target_h, target_w), dtype=np.uint8)
    ch, cw = min(target_h, up.shape[0]), min(target_w, up.shape[1])
    out[:ch, :cw] = up[:ch, :cw]
    return out


def _blur_alpha_half_res(alpha: np.ndarray, passes: int = 2) -> np.ndarray:
    """Blur an alpha mask via 2x2 integer box downsample + separable Gaussian + Numpy 2x upsample."""
    h, w = alpha.shape
    if h < 4 or w < 4:
        return _binomial_blur_u16(alpha, passes=1)
    h2, w2 = max(2, h // 2), max(2, w // 2)
    cropped = alpha[: h2 * 2, : w2 * 2]
    if cropped.shape == (h2 * 2, w2 * 2):
        c16 = cropped.astype(np.uint16).reshape(h2, 2, w2, 2)
        small = (c16[:, 0, :, 0] + c16[:, 0, :, 1] + c16[:, 1, :, 0] + c16[:, 1, :, 1]) >> 2
    else:
        small = alpha[::2, ::2].astype(np.uint16)
    blurred_small = _binomial_blur_u16(small, passes=passes)
    return _upsample_2x_bilinear_u8(blurred_small, h, w)


def make_blurred_qimage(src: QImage | None, downscale: int = 2, passes: int = 3) -> QImage | None:
    """Create a genuine optical Gaussian-blurred half-resolution QImage for Focus Blur transitions."""
    if src is None or src.isNull() or src.width() < 4 or src.height() < 4:
        return None
    work = src
    if work.format() != QImage.Format.Format_ARGB32_Premultiplied:
        work = work.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    scale = max(1, int(downscale))
    sw = max(2, work.width() // scale)
    sh = max(2, work.height() // scale)
    small = work.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if small.format() != QImage.Format.Format_ARGB32_Premultiplied:
        small = small.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    arr, ptr = _rgba_view(small)
    blurred = _binomial_blur_u16(arr, passes=passes)
    arr[:, :, :] = blurred
    del arr, ptr
    return small


def _compose_premul_accum16(
    accum16: np.ndarray,
    alpha_mask: np.ndarray,
    color: QColor,
) -> None:
    """Fast shift-only integer premultiplied alpha-over accumulation (zero uint16 division)."""
    ca = color.alpha()
    if ca <= 1:
        return
    if ca >= 254:
        src_a = alpha_mask.astype(np.uint16)
    else:
        src_a = (alpha_mask.astype(np.uint16) * ca) >> 8
    inv_a = 256 - src_a
    if _LITTLE_ENDIAN:
        c0, c1, c2 = color.blue(), color.green(), color.red()
        a_idx = 3
        i0, i1, i2 = 0, 1, 2
    else:
        c0, c1, c2 = color.red(), color.green(), color.blue()
        a_idx = 0
        i0, i1, i2 = 1, 2, 3

    accum16[:, :, i0] = (src_a * c0 + accum16[:, :, i0] * inv_a) >> 8
    accum16[:, :, i1] = (src_a * c1 + accum16[:, :, i1] * inv_a) >> 8
    accum16[:, :, i2] = (src_a * c2 + accum16[:, :, i2] * inv_a) >> 8
    accum16[:, :, a_idx] = src_a + ((accum16[:, :, a_idx] * inv_a) >> 8)


def _draw_plan_text(painter: QPainter, plan: TypographyPlan, brush, phonetic_brush=None) -> None:
    main_pen = QPen(brush, 0)
    phon_pen = QPen(phonetic_brush, 0) if phonetic_brush is not None else None
    for line in plan.lines:
        if not line.text:
            continue
        painter.setPen(phon_pen if (phon_pen is not None and line.is_secondary) else main_pen)
        painter.setFont(line.font)
        painter.drawText(QPointF(line.x, line.baseline), line.text)


def draw_studio_text_layers(
    painter: QPainter,
    plan: TypographyPlan,
    font_color: str | QColor,
    color_mode: str = 'original',
    progress: float = 1.0,
    use_shadow: bool = True,
    shadow_alpha: int = 185,
    use_outline: bool = True,
    outline_width: int = 2,
    outline_color: str | QColor = '#090D16',
    glow: bool = False,
    draw_fill: bool = True,
) -> None:
    """Fast DirectWrite layered vector drawing (used by export and oversized fallback)."""
    if not plan.lines:
        return
    bounds = plan.full_bounds
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    if use_shadow and shadow_alpha > 0:
        for blur_step, dy, alpha_mul in ((3, 3.2, 0.25), (1, 1.8, 0.45)):
            sc = QColor(0, 0, 0, min(255, int(round(shadow_alpha * alpha_mul))))
            painter.save()
            painter.translate(0.0, dy)
            _draw_plan_text(painter, plan, sc)
            painter.restore()
            if blur_step == 3 and glow:
                break

    if glow:
        glow_c = accent_glow_color(color_mode, font_color)
        glow_c.setAlpha(46)
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            painter.save()
            painter.translate(ox, oy)
            _draw_plan_text(painter, plan, glow_c)
            painter.restore()

    if use_outline and outline_width > 0:
        oc = QColor(outline_color)
        if not oc.isValid():
            oc = QColor('#090D16')
        oc.setAlpha(238)
        r = min(float(outline_width), 4.0)
        taps = 12 if r >= 2.0 else 8
        for idx in range(taps):
            ang = (2.0 * math.pi * idx) / taps
            painter.save()
            painter.translate(math.cos(ang) * r, math.sin(ang) * r)
            _draw_plan_text(painter, plan, oc)
            painter.restore()

    if draw_fill:
        fill = primary_brush(color_mode, bounds, font_color, progress)
        has_phon = any(l.is_secondary for l in plan.lines)
        phon_fill = QColor('#BAE6FD') if has_phon else None
        _draw_plan_text(painter, plan, fill, phonetic_brush=phon_fill)

    painter.restore()


def rasterize_unlit_karaoke_sprite(
    plan: TypographyPlan,
    dpr: float,
    use_shadow: bool = True,
    shadow_alpha: int = 185,
    use_outline: bool = True,
    outline_width: int = 3,
    outline_color: str | QColor = '#060913',
) -> tuple[QImage | None, QPointF]:
    """Rasterize dimmed unlit layer for AMLL feathered karaoke via DirectWrite + Numpy SIMD."""
    if not plan.lines or plan.full_bounds.isNull():
        return None, QPointF()
    dpr = max(1.0, float(dpr))
    margin = max(24.0, (outline_width if use_outline else 0) + 14.0)
    sprite_rect = plan.full_bounds.adjusted(-margin, -margin, margin, margin)
    origin = sprite_rect.topLeft()
    pw = max(2, int(math.ceil(sprite_rect.width() * dpr)))
    ph = max(2, int(math.ceil(sprite_rect.height() * dpr)))
    if pw * ph > MAX_SPRITE_PIXELS:
        return None, QPointF()

    fg = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
    fg.fill(Qt.GlobalColor.transparent)
    p = QPainter(fg)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.scale(dpr, dpr)
    p.translate(-origin)
    _draw_plan_text(p, plan, QColor(218, 226, 240, 128))
    p.end()

    fg_arr, fg_ptr = _rgba_view(fg)
    a_idx = 3 if _LITTLE_ENDIAN else 0
    alpha = fg_arr[:, :, a_idx].copy()
    del fg_arr, fg_ptr

    accum16 = np.zeros((ph, pw, 4), dtype=np.uint16)

    if use_shadow and shadow_alpha > 0:
        dy = max(1, int(round(2.0 * dpr)))
        if dy < ph:
            shifted = np.zeros_like(alpha)
            shifted[dy:, :] = alpha[:-dy, :]
            _compose_premul_accum16(accum16, shifted, QColor(0, 0, 0, min(255, int(shadow_alpha * 0.55))))

    if use_outline and outline_width > 0:
        oc = QColor(outline_color)
        if not oc.isValid():
            oc = QColor('#060913')
        oc.setAlpha(150)
        # Fast 4-direction cardinal shift outline (~4x faster than full disk dilation for dimmed unlit layer)
        step = max(1, min(3, int(round(float(outline_width) * 0.65 * dpr))))
        stroke_a = alpha.copy()
        if step < ph and step < pw:
            np.maximum(stroke_a[step:, :], alpha[:-step, :], out=stroke_a[step:, :])
            np.maximum(stroke_a[:-step, :], alpha[step:, :], out=stroke_a[:-step, :])
            np.maximum(stroke_a[:, step:], alpha[:, :-step], out=stroke_a[:, step:])
            np.maximum(stroke_a[:, :-step], alpha[:, step:], out=stroke_a[:, :-step])
        _compose_premul_accum16(accum16, stroke_a, oc)

    out = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
    out_arr, out_ptr = _rgba_view(out)
    out_arr[:, :, :] = np.clip(accum16, 0, 255).astype(np.uint8)
    del out_arr, out_ptr

    cp = QPainter(out)
    cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    cp.drawImage(0, 0, fg)
    cp.end()
    out.setDevicePixelRatio(dpr)
    return out, origin


def rasterize_studio_sprite(
    plan: TypographyPlan,
    dpr: float,
    font_color: str | QColor,
    color_mode: str = 'original',
    use_shadow: bool = True,
    shadow_alpha: int = 185,
    use_outline: bool = True,
    outline_width: int = 2,
    outline_color: str | QColor = '#090D16',
    glow: bool = False,
    studio_mode: bool = True,
    vfx_style: str = 'standard',
) -> tuple[QImage | None, QPointF]:
    """Rasterize high-craft crisp text sprite (~6ms) with optional 3D/Neon/Fire/Holo shader passes."""
    if not plan.lines or plan.full_bounds.isNull():
        return None, QPointF()
    dpr = max(1.0, float(dpr))
    extra_glow_pad = 26.0 if vfx_style in ('neon_tube', 'fire_ember') else (20.0 if glow else 12.0)
    margin = max(24.0, (outline_width if use_outline else 0) + extra_glow_pad)
    sprite_rect = plan.full_bounds.adjusted(-margin, -margin, margin, margin)
    origin = sprite_rect.topLeft()
    pw = max(2, int(math.ceil(sprite_rect.width() * dpr)))
    ph = max(2, int(math.ceil(sprite_rect.height() * dpr)))
    if pw * ph > MAX_SPRITE_PIXELS:
        return None, QPointF()

    fg = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
    fg.fill(Qt.GlobalColor.transparent)
    p = QPainter(fg)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.scale(dpr, dpr)
    p.translate(-origin)
    fill_brush = primary_brush(color_mode, plan.full_bounds, font_color, 1.0)
    phon_fill = QColor('#BAE6FD') if any(l.is_secondary for l in plan.lines) else None
    _draw_plan_text(p, plan, fill_brush, phonetic_brush=phon_fill)
    p.end()

    fg_arr, fg_ptr = _rgba_view(fg)
    a_idx = 3 if _LITTLE_ENDIAN else 0
    alpha = fg_arr[:, :, a_idx].copy()
    if vfx_style == 'cyber_holo':
        # Subtle CRT hologram scanline modulation directly on device pixels
        if _LITTLE_ENDIAN:
            fg_arr[::3, :, :3] = ((fg_arr[::3, :, :3].astype(np.uint16) * 214) >> 8).astype(np.uint8)
        else:
            fg_arr[::3, :, 1:] = ((fg_arr[::3, :, 1:].astype(np.uint16) * 214) >> 8).astype(np.uint8)
    del fg_arr, fg_ptr

    accum16 = np.zeros((ph, pw, 4), dtype=np.uint16)

    # Share one half-res blurred halo across shadow and multi-tier VFX glow
    if (use_shadow and shadow_alpha > 0) or glow or vfx_style in ('neon_tube', 'fire_ember', 'deep_glow', 'cyber_holo'):
        h2, w2 = max(2, ph // 2), max(2, pw // 2)
        cropped = alpha[: h2 * 2, : w2 * 2]
        if cropped.shape == (h2 * 2, w2 * 2):
            c16 = cropped.astype(np.uint16).reshape(h2, 2, w2, 2)
            small_alpha = (c16[:, 0, :, 0] + c16[:, 0, :, 1] + c16[:, 1, :, 0] + c16[:, 1, :, 1]) >> 2
        else:
            small_alpha = alpha[::2, ::2].astype(np.uint16)
        blur_passes = 3 if vfx_style in ('neon_tube', 'fire_ember') else 2
        halo_small = _binomial_blur_u16(small_alpha, passes=blur_passes)

        if use_shadow and shadow_alpha > 0:
            dy_s = max(1, int(round(1.3 * dpr)))
            dx_s = int(round(0.4 * dpr))
            s_shifted = np.zeros_like(halo_small)
            sh_src = halo_small.shape[0] - dy_s if dy_s < halo_small.shape[0] else 0
            sw_src = halo_small.shape[1] - dx_s if dx_s < halo_small.shape[1] else 0
            if sh_src > 0 and sw_src > 0:
                s_shifted[dy_s:, dx_s:] = halo_small[:sh_src, :sw_src]
            shadow_blur = _upsample_2x_bilinear_u8(s_shifted, ph, pw)
            _compose_premul_accum16(accum16, shadow_blur, QColor(0, 0, 0, min(255, int(shadow_alpha))))

        if glow or vfx_style in ('neon_tube', 'fire_ember', 'cyber_holo'):
            glow_c = accent_glow_color(color_mode, font_color)
            if vfx_style == 'fire_ember':
                outer_c = QColor('#EF4444')
                outer_c.setAlpha(185)
                glow_blur = _upsample_2x_bilinear_u8(halo_small, ph, pw)
                _compose_premul_accum16(accum16, glow_blur, outer_c)
                inner_small = _binomial_blur_u16(small_alpha, passes=1)
                inner_blur = _upsample_2x_bilinear_u8(inner_small, ph, pw)
                inner_c = QColor('#FDE047')
                inner_c.setAlpha(155)
                _compose_premul_accum16(accum16, inner_blur, inner_c)
            elif vfx_style == 'neon_tube':
                outer_c = QColor(glow_c)
                outer_c.setAlpha(205)
                glow_blur = _upsample_2x_bilinear_u8(halo_small, ph, pw)
                _compose_premul_accum16(accum16, glow_blur, outer_c)
                inner_small = _binomial_blur_u16(small_alpha, passes=1)
                inner_blur = _upsample_2x_bilinear_u8(inner_small, ph, pw)
                hot_c = QColor(255, 255, 255, 130)
                _compose_premul_accum16(accum16, inner_blur, hot_c)
            elif vfx_style == 'cyber_holo':
                glow_blur = _upsample_2x_bilinear_u8(halo_small, ph, pw)
                c_left = QColor('#06B6D4'); c_left.setAlpha(165)
                _compose_premul_accum16(accum16, glow_blur, c_left)
                c_mag = QColor('#EC4899'); c_mag.setAlpha(95)
                s_mag = np.zeros_like(glow_blur)
                shift_x = max(1, int(round(2.5 * dpr)))
                if shift_x < pw:
                    s_mag[:, shift_x:] = glow_blur[:, :-shift_x]
                _compose_premul_accum16(accum16, s_mag, c_mag)
            else:
                glow_c.setAlpha(178 if studio_mode else 120)
                glow_blur = _upsample_2x_bilinear_u8(halo_small, ph, pw)
                _compose_premul_accum16(accum16, glow_blur, glow_c)

    # Metallic 3D extruded bevel block behind outline
    if vfx_style == 'metallic_3d':
        ext_col = QColor('#1E293B')
        ext_col.setAlpha(230)
        for step in (3, 2, 1):
            dx3 = int(round(step * 1.1 * dpr))
            dy3 = int(round(step * 1.4 * dpr))
            if dy3 < ph and dx3 < pw:
                ext = np.zeros_like(alpha)
                ext[dy3:, dx3:] = alpha[: ph - dy3, : pw - dx3]
                _compose_premul_accum16(accum16, ext, ext_col)

    if use_outline and outline_width > 0:
        oc = QColor(outline_color)
        if not oc.isValid():
            oc = QColor('#090D16')
        oc.setAlpha(244)
        stroke_a = _dilate_alpha_disk(alpha, float(outline_width) * dpr)
        _compose_premul_accum16(accum16, stroke_a, oc)

    out = QImage(pw, ph, QImage.Format.Format_ARGB32_Premultiplied)
    out_arr, out_ptr = _rgba_view(out)
    out_arr[:, :, :] = np.clip(accum16, 0, 255).astype(np.uint8)
    del out_arr, out_ptr

    cp = QPainter(out)
    cp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    cp.drawImage(0, 0, fg)
    cp.end()
    out.setDevicePixelRatio(dpr)
    return out, origin


class SubtitleRenderCache:
    """Bounded 4-entry LRU cache holding pre-shaped TypographyPlans and DPR sprites."""

    def __init__(self, max_entries: int = MAX_CACHE_ENTRIES):
        self._max_entries = max(1, int(max_entries))
        self._plans: OrderedDict[tuple, TypographyPlan] = OrderedDict()
        self._sprites: OrderedDict[tuple, tuple[QImage, QPointF]] = OrderedDict()

    def clear(self) -> None:
        self._plans.clear()
        self._sprites.clear()

    def __len__(self) -> int:
        return len(self._sprites)

    def get_plan(self, key: tuple) -> TypographyPlan | None:
        plan = self._plans.get(key)
        if plan is not None:
            self._plans.move_to_end(key)
        return plan

    def put_plan(self, key: tuple, plan: TypographyPlan) -> TypographyPlan:
        self._plans[key] = plan
        self._plans.move_to_end(key)
        while len(self._plans) > self._max_entries:
            self._plans.popitem(last=False)
        return plan

    def get_sprite(self, key: tuple) -> tuple[QImage, QPointF] | None:
        hit = self._sprites.get(key)
        if hit is not None:
            self._sprites.move_to_end(key)
        return hit

    def put_sprite(self, key: tuple, sprite: QImage | None, origin: QPointF) -> None:
        if sprite is None:
            return
        self._sprites[key] = (sprite, QPointF(origin))
        self._sprites.move_to_end(key)
        while len(self._sprites) > self._max_entries:
            self._sprites.popitem(last=False)
