"""Background burn-in export using the current subtitle presentation snapshot.

Playback, subtitle storage and the live SubtitleLayer stay read-only.  The worker
renders a narrow transparent RGBA band with the existing painter-only effect
engine and pipes it directly into FFmpeg, so no per-frame image files are kept.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
import copy
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
import weakref

from PySide6.QtCore import (
    QObject, QPoint, QPointF, QProcess, QRect, QRectF, QSize, Qt, QTextBoundaryFinder, QThread, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QProgressDialog, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QVBoxLayout,
    QWidget,
)

from control.worker_lifecycle import OwnedProcesses
from core.audio_effects import find_tool
from ui.icons import button_icon
from ui.design_system import ACCENT, BORDER, DIALOG_STYLE, MUTED, RAISED, SURFACE, TEXT
from ui.subtitle_effects import SubtitleEffects, normalize_options
from ui.subtitle_particles import subtitle_row_groups


FADE_MS = 220
MAX_EXPORT_FPS = 60.0
MP4_COPY_AUDIO = frozenset({'aac', 'mp3', 'alac', 'ac3', 'eac3'})
ASPECT_RATIOS = {
    'source': None,
    '16:9': (16, 9),
    '9:16': (9, 16),
    '1:1': (1, 1),
    '4:5': (4, 5),
    '4:3': (4, 3),
    '3:2': (3, 2),
    '21:9': (21, 9),
}
RESOLUTION_SHORT_EDGE = {'source': None, '720': 720, '1080': 1080, '1440': 1440, '2160': 2160}
QUALITY_CRF = {'very_high': 16, 'high': 18, 'balanced': 20, 'compact': 23}
FIT_MODES = frozenset({'contain', 'cover', 'stretch'})
BACKGROUND_COLORS = {'black': 'black', 'dark': '#151A22', 'white': 'white'}
EXPORT_SCALE_FLAGS = 'lanczos+accurate_rnd+full_chroma_int'


@dataclass(frozen=True)
class ExportSettings:
    container: str = 'mp4'
    aspect: str = 'source'
    resolution: str = 'source'
    fit_mode: str = 'contain'
    background: str = 'black'
    fps: float | None = None
    quality: str = 'high'
    safe_subtitles: bool = True
    # 0% keeps the live placement unchanged whenever it already fits.  The
    # guard still prevents actual clipping; users can opt into larger editor
    # style title-safe margins from the export dialog.
    safe_horizontal_percent: int = 0
    safe_vertical_percent: int = 0
    override_font_size: bool = False
    font_size: int = 24
    subtitle_x_percent: int = 0
    subtitle_y_percent: int = 0
    override_bg_opacity: bool = False
    bg_opacity_percent: int = 50
    custom_width: int = 1920
    custom_height: int = 1080


def _even(value):
    value = max(2, int(round(value)))
    return value if value % 2 == 0 else value + 1


def resolve_canvas(probe, settings: ExportSettings):
    """Resolve final even canvas dimensions without changing the source media."""
    source_w, source_h = int(probe['width']), int(probe['height'])
    if settings.resolution == 'custom':
        return _even(settings.custom_width), _even(settings.custom_height)
    ratio = ASPECT_RATIOS.get(settings.aspect)
    if ratio is None:
        ratio = (source_w, source_h)
    rw, rh = ratio
    short_edge = RESOLUTION_SHORT_EDGE.get(settings.resolution)
    if short_edge is None:
        # Source resolution means keep its short edge even when the user picks
        # another aspect ratio; this avoids an accidental quality up-scale.
        short_edge = min(source_w, source_h)
        if settings.aspect == 'source':
            return _even(source_w), _even(source_h)
    if rw >= rh:
        height = short_edge
        width = short_edge * rw / rh
    else:
        width = short_edge
        height = short_edge * rh / rw
    return _even(width), _even(height)


def source_video_filter(width, height, settings: ExportSettings):
    """Build only the source-to-canvas transform used before subtitle overlay."""
    mode = settings.fit_mode if settings.fit_mode in FIT_MODES else 'contain'
    bg = BACKGROUND_COLORS.get(settings.background, 'black')
    if mode == 'cover':
        return (f'scale={width}:{height}:force_original_aspect_ratio=increase:'
                f'flags={EXPORT_SCALE_FLAGS},'
                f'crop={width}:{height}:(iw-{width})/2:(ih-{height})/2')
    if mode == 'stretch':
        return f'scale={width}:{height}:flags={EXPORT_SCALE_FLAGS}'
    return (f'scale={width}:{height}:force_original_aspect_ratio=decrease:'
            f'flags={EXPORT_SCALE_FLAGS},'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={bg}')


def subtitle_composition_filter(base_filter, overlay_y):
    """Compose RGBA subtitles at 4:4:4, then return compatible 4:2:0 video."""
    return (f'[1:v:0]{base_filter},format=yuv444p[base444];'
            f'[base444][0:v:0]overlay=0:{int(overlay_y)}:format=yuv444:'
            'alpha=straight:eof_action=pass:repeatlast=0,'
            'format=yuv420p,setsar=1[v]')


def source_transform(canvas_width, canvas_height, source_width, source_height,
                     settings: ExportSettings):
    """Return the transformed full-source rectangle inside the export canvas."""
    source_width = max(1.0, float(source_width))
    source_height = max(1.0, float(source_height))
    mode = settings.fit_mode if settings.fit_mode in FIT_MODES else 'contain'
    if mode == 'stretch':
        return {
            'x': 0.0, 'y': 0.0,
            'width': float(canvas_width), 'height': float(canvas_height),
            'scale_x': float(canvas_width)/source_width,
            'scale_y': float(canvas_height)/source_height,
        }
    ratio_x = float(canvas_width)/source_width
    ratio_y = float(canvas_height)/source_height
    scale = max(ratio_x, ratio_y) if mode == 'cover' else min(ratio_x, ratio_y)
    width = source_width*scale
    height = source_height*scale
    return {
        'x': (float(canvas_width)-width)/2.0,
        'y': (float(canvas_height)-height)/2.0,
        'width': width,
        'height': height,
        'scale_x': scale,
        'scale_y': scale,
    }


def _graphemes(text):
    """Return complete Qt grapheme clusters so export wrapping keeps emoji/accents intact."""
    if not text:
        return []
    encoded = text.encode('utf-16-le', errors='surrogatepass')
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    clusters = []
    start = 0
    end = finder.toNextBoundary()
    while end >= 0:
        clusters.append(encoded[start*2:end*2].decode('utf-16-le', errors='surrogatepass'))
        start = end
        end = finder.toNextBoundary()
    return clusters


class ExportPreviewWidget(QWidget):
    """Lightweight export-only canvas preview using an existing cached thumbnail."""
    def __init__(self, snapshot=None, thumbnail_path=None, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.settings_value = ExportSettings()
        self.source_image = QImage()
        if thumbnail_path:
            image = QImage(str(thumbnail_path))
            if not image.isNull():
                self.source_image = image
        self._overlay_image = QImage()
        self._overlay_y = 0.0
        self.preview_cue_index = 0
        self._last_render_key = None
        self.setMinimumSize(520, 330)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_settings(self, settings):
        self.settings_value = settings
        self._last_render_key = None
        self.update()

    def set_source_image(self, image):
        if image is None or image.isNull():
            return
        self.source_image = image.copy()
        self._last_render_key = None
        self.update()

    def set_preview_cue_index(self, index):
        self.preview_cue_index = max(0, int(index))
        self._last_render_key = None
        self.update()

    def _source_ratio(self):
        if not self.source_image.isNull() and self.source_image.height() > 0:
            return self.source_image.width()/self.source_image.height()
        snap = self.snapshot
        if snap is not None and snap.video_width > 0 and snap.video_height > 0:
            return snap.video_width/snap.video_height
        return 16/9

    def _canvas_ratio(self):
        settings = self.settings_value
        if settings.resolution == 'custom' and settings.custom_height > 0:
            return settings.custom_width/settings.custom_height
        ratio = ASPECT_RATIOS.get(settings.aspect)
        if ratio is not None:
            return ratio[0]/ratio[1]
        return self._source_ratio()

    def _canvas_rect(self):
        bounds = self.rect().adjusted(26, 26, -26, -26)
        if bounds.width() <= 0 or bounds.height() <= 0:
            return QRect()
        ratio = max(.1, self._canvas_ratio())
        width = bounds.width()
        height = round(width/ratio)
        if height > bounds.height():
            height = bounds.height()
            width = round(height*ratio)
        return QRect(
            bounds.center().x()-width//2,
            bounds.center().y()-height//2,
            max(1, width), max(1, height),
        )

    def _background_color(self):
        return QColor(BACKGROUND_COLORS.get(self.settings_value.background, 'black'))

    def _draw_source(self, painter, canvas):
        painter.fillRect(canvas, self._background_color())
        if self.source_image.isNull():
            painter.setPen(QColor(MUTED))
            painter.drawText(canvas, Qt.AlignmentFlag.AlignCenter,
                             'Khung xem trước video\n(thumbnail chưa sẵn sàng)')
            return
        mode = self.settings_value.fit_mode
        if mode == 'stretch':
            painter.drawImage(QRectF(canvas), self.source_image)
            return

        # Keep the decoded frame at its original resolution.  Scaling it to the
        # logical QWidget size first throws away pixels before Qt applies the
        # Windows HiDPI device transform, which makes both 1080p previews and
        # fractional-DPI screens visibly soft.
        source = QRectF(self.source_image.rect())
        source_ratio = source.width()/max(1.0, source.height())
        canvas_ratio = canvas.width()/max(1.0, float(canvas.height()))
        if mode == 'cover':
            if source_ratio > canvas_ratio:
                crop_w = source.height()*canvas_ratio
                source.setLeft(source.left()+(source.width()-crop_w)/2.0)
                source.setWidth(crop_w)
            else:
                crop_h = source.width()/canvas_ratio
                source.setTop(source.top()+(source.height()-crop_h)/2.0)
                source.setHeight(crop_h)
            target = QRectF(canvas)
        else:
            if source_ratio > canvas_ratio:
                target_w = float(canvas.width())
                target_h = target_w/source_ratio
            else:
                target_h = float(canvas.height())
                target_w = target_h*source_ratio
            target = QRectF(
                canvas.center().x()-target_w/2.0,
                canvas.center().y()-target_h/2.0,
                target_w, target_h,
            )
        painter.save()
        painter.setClipRect(canvas)
        painter.drawImage(target, self.source_image, source)
        painter.restore()

    def _rebuild_overlay(self, canvas, dpr):
        if self.snapshot is None or not self.snapshot.cues or canvas.isEmpty():
            self._overlay_image = QImage()
            return
        source_w = self.source_image.width() if not self.source_image.isNull() else 1600
        source_h = self.source_image.height() if not self.source_image.isNull() else 900
        if source_w <= 0 or source_h <= 0:
            source_w, source_h = 1600, 900
        try:
            # SubtitleBandRenderer works in raster pixels. Render the preview at
            # the backing-store resolution and tag the image with the monitor
            # DPR so its logical size remains identical to the on-screen
            # canvas.  Moving the dialog between mixed-DPI monitors is handled
            # by the render key in paintEvent.
            physical_w = max(1, round(canvas.width()*dpr))
            physical_h = max(1, round(canvas.height()*dpr))
            renderer = SubtitleBandRenderer(
                self.snapshot, physical_w, physical_h, self.settings_value,
                probe={'width': source_w, 'height': source_h},
            )
            cue_index = min(self.preview_cue_index, len(self.snapshot.cues)-1)
            cue = self.snapshot.cues[cue_index]
            sample_time = cue.start + max(1.0, (cue.end-cue.start)*.35)
            frame = renderer.frame(sample_time)
            image = QImage(
                frame, physical_w, renderer.band_height,
                QImage.Format.Format_RGBA8888,
            )
            self._overlay_image = image.copy()
            self._overlay_image.setDevicePixelRatio(dpr)
            self._overlay_y = renderer.overlay_y/dpr
        except Exception:
            self._overlay_image = QImage()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor('#090D13'))
        canvas = self._canvas_rect()
        if canvas.isEmpty():
            return
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(QColor('#070A0F'))
        painter.drawRoundedRect(canvas.adjusted(-1, -1, 1, 1), 10, 10)
        painter.save()
        painter.setClipRect(canvas)
        self._draw_source(painter, canvas)
        dpr = max(1.0, float(self.devicePixelRatioF()))
        render_key = (canvas.width(), canvas.height(), round(dpr, 3))
        if self._last_render_key != render_key:
            self._last_render_key = render_key
            self._rebuild_overlay(canvas, dpr)
        if not self._overlay_image.isNull():
            painter.drawImage(
                QPointF(float(canvas.x()), float(canvas.y())+self._overlay_y),
                self._overlay_image,
            )
        painter.restore()

        if self.settings_value.safe_subtitles:
            hx = round(canvas.width()*self.settings_value.safe_horizontal_percent/100)
            hy = round(canvas.height()*self.settings_value.safe_vertical_percent/100)
            safe = canvas.adjusted(hx, hy, -hx, -hy)
            pen = QPen(QColor(ACCENT))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(safe)

        painter.setPen(QColor(TEXT))
        painter.drawText(
            QRect(canvas.x(), canvas.bottom()+7, canvas.width(), 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            'PREVIEW KHUNG XUẤT',
        )


class VideoExportSettingsDialog(QDialog):
    """Editor-style export UI; only returns an immutable ExportSettings value."""
    def __init__(self, parent=None, snapshot=None, media_item=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.media_item = media_item
        self.setWindowTitle('Xuất video + lyric')
        self.setMinimumSize(1040, 700)
        self.resize(1180, 760)
        self.setStyleSheet(DIALOG_STYLE + f"""
            QFrame#exportCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
            QLabel#exportTitle {{ color: {TEXT}; font-size: 22px; font-weight: 700; }}
            QLabel#exportSection {{ color: {TEXT}; font-size: 14px; font-weight: 700; }}
            QLabel#exportMuted {{ color: {MUTED}; font-size: 12px; }}
            QPushButton#presetButton {{ min-height: 30px; padding: 5px 10px; }}
            QPushButton#presetButton:checked {{ background: #19372F; border-color: {ACCENT}; color: #A9F1D9; }}
            QSpinBox {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px; }}
            QSlider::groove:horizontal {{ height: 4px; background: #344254; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; margin: -4px 0; border-radius: 6px; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        title = QLabel('Xuất video + lyric')
        title.setObjectName('exportTitle')
        subtitle = QLabel('Xem trước bố cục đầu ra và tinh chỉnh trước khi render.')
        subtitle.setObjectName('exportMuted')
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header.addLayout(header_text, 1)
        reset = QPushButton('Khôi phục đề xuất')
        reset.clicked.connect(self._reset_recommended)
        header.addWidget(reset)
        root.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)

        preview_card = QFrame()
        preview_card.setObjectName('exportCard')
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(9)
        preview_heading = QLabel('Bản xem trước')
        preview_heading.setObjectName('exportSection')
        preview_hint = QLabel('Thumbnail chỉ dùng để kiểm tra bố cục; video xuất vẫn lấy hình từ file gốc.')
        preview_hint.setObjectName('exportMuted')
        preview_hint.setWordWrap(True)
        thumbnail_path = getattr(media_item, 'thumbnail', None) if media_item is not None else None
        self.preview = ExportPreviewWidget(snapshot, thumbnail_path, preview_card)
        self.preview_cue = QComboBox()
        self.preview_cue.setToolTip('Chỉ đổi câu dùng để xem trước, không thay đổi lyric xuất.')
        if snapshot is not None and snapshot.cues:
            indexes = sorted(set((0, len(snapshot.cues)//2, len(snapshot.cues)-1)))
            for index in indexes:
                text = snapshot.cues[index].text.replace('\n', ' ')
                if len(text) > 44:
                    text = text[:41] + '…'
                self.preview_cue.addItem(f'Câu {index+1}: {text}', index)
        self.preview_status = QLabel('Theo video nguồn • Vừa khung • Chất lượng cao')
        self.preview_status.setObjectName('exportMuted')
        preview_layout.addWidget(preview_heading)
        preview_layout.addWidget(preview_hint)
        preview_layout.addWidget(self.preview, 1)
        if self.preview_cue.count():
            preview_layout.addWidget(self.preview_cue)
        preview_layout.addWidget(self.preview_status)
        body.addWidget(preview_card, 3)

        settings_card = QFrame()
        settings_card.setObjectName('exportCard')
        settings_outer = QVBoxLayout(settings_card)
        settings_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        form_layout = QVBoxLayout(content)
        form_layout.setContentsMargins(18, 16, 18, 16)
        form_layout.setSpacing(14)

        section = QLabel('Thiết lập đầu ra')
        section.setObjectName('exportSection')
        form_layout.addWidget(section)

        preset_row = QHBoxLayout()
        for label, aspect, resolution in (
            ('Nguồn', 'source', 'source'), ('YouTube', '16:9', '1080'),
            ('Shorts', '9:16', '1080'), ('Vuông', '1:1', '1080'),
        ):
            button = QPushButton(label)
            button.setObjectName('presetButton')
            button.clicked.connect(
                lambda _checked=False, a=aspect, r=resolution: self._apply_quick_preset(a, r)
            )
            preset_row.addWidget(button)
        form_layout.addLayout(preset_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.container = QComboBox()
        self.container.addItem('MP4 — tương thích rộng', 'mp4')
        self.container.addItem('MKV — giữ audio linh hoạt', 'mkv')
        form.addRow('Định dạng', self.container)

        self.aspect = QComboBox()
        for label, value in (
            ('Theo video gốc', 'source'), ('16:9 — YouTube / màn hình', '16:9'),
            ('9:16 — Shorts / Reels / TikTok', '9:16'), ('1:1 — Vuông', '1:1'),
            ('4:5 — Social portrait', '4:5'), ('4:3 — Cổ điển', '4:3'),
            ('3:2 — Cinematic', '3:2'), ('21:9 — Ultrawide', '21:9'),
        ):
            self.aspect.addItem(label, value)
        form.addRow('Tỉ lệ', self.aspect)

        self.resolution = QComboBox()
        self.resolution.addItem('Theo độ phân giải nguồn', 'source')
        self.resolution.addItem('720p — HD', '720')
        self.resolution.addItem('1080p — Full HD', '1080')
        self.resolution.addItem('1440p — QHD', '1440')
        self.resolution.addItem('2160p — 4K', '2160')
        self.resolution.addItem('Tùy chỉnh…', 'custom')
        form.addRow('Độ phân giải', self.resolution)

        custom_size = QHBoxLayout()
        self.custom_width = QSpinBox()
        self.custom_width.setRange(160, 7680)
        self.custom_width.setValue(1920)
        self.custom_width.setSingleStep(2)
        self.custom_height = QSpinBox()
        self.custom_height.setRange(160, 7680)
        self.custom_height.setValue(1080)
        self.custom_height.setSingleStep(2)
        swap = QPushButton('↔')
        swap.setToolTip('Đổi chiều rộng và chiều cao')
        swap.setFixedWidth(38)
        swap.clicked.connect(self._swap_custom_size)
        self.swap_custom = swap
        custom_size.addWidget(self.custom_width)
        custom_size.addWidget(QLabel('×'))
        custom_size.addWidget(self.custom_height)
        custom_size.addWidget(QLabel('px'))
        custom_size.addWidget(swap)
        form.addRow('Kích thước', custom_size)

        self.fit_mode = QComboBox()
        self.fit_mode.addItem('Vừa khung — giữ trọn hình', 'contain')
        self.fit_mode.addItem('Lấp đầy — crop phần dư', 'cover')
        self.fit_mode.addItem('Kéo giãn — không crop', 'stretch')
        form.addRow('Bố cục video', self.fit_mode)

        self.background = QComboBox()
        self.background.addItem('Đen', 'black')
        self.background.addItem('Xám đậm', 'dark')
        self.background.addItem('Trắng', 'white')
        form.addRow('Nền phần trống', self.background)

        self.fps = QComboBox()
        self.fps.addItem('Theo video nguồn', None)
        for fps in (24, 25, 30, 50, 60):
            self.fps.addItem(f'{fps} fps', float(fps))
        form.addRow('Frame rate', self.fps)

        self.quality = QComboBox()
        self.quality.addItem('Rất cao — CRF 16', 'very_high')
        self.quality.addItem('Cao — CRF 18', 'high')
        self.quality.addItem('Cân bằng — CRF 20', 'balanced')
        self.quality.addItem('Nhẹ — CRF 23', 'compact')
        self.quality.setCurrentIndex(1)
        form.addRow('Chất lượng', self.quality)
        form_layout.addLayout(form)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f'color: {BORDER};')
        form_layout.addWidget(divider)

        safe_title = QLabel('Lyric / subtitle')
        safe_title.setObjectName('exportSection')
        form_layout.addWidget(safe_title)
        self.safe_subtitles = QCheckBox('Chống cắt chữ/effect ở mép khung')
        self.safe_subtitles.setChecked(True)
        form_layout.addWidget(self.safe_subtitles)
        safe_grid = QGridLayout()
        safe_grid.addWidget(QLabel('Lề ngang'), 0, 0)
        self.safe_horizontal = QSpinBox()
        self.safe_horizontal.setRange(0, 20)
        self.safe_horizontal.setValue(0)
        self.safe_horizontal.setSuffix('%')
        safe_grid.addWidget(self.safe_horizontal, 0, 1)
        safe_grid.addWidget(QLabel('Lề dọc'), 1, 0)
        self.safe_vertical = QSpinBox()
        self.safe_vertical.setRange(0, 20)
        self.safe_vertical.setValue(0)
        self.safe_vertical.setSuffix('%')
        safe_grid.addWidget(self.safe_vertical, 1, 1)
        form_layout.addLayout(safe_grid)
        safe_note = QLabel('0% giữ vị trí như trong app; tăng lề nếu muốn title-safe area kiểu editor.')
        safe_note.setObjectName('exportMuted')
        safe_note.setWordWrap(True)
        form_layout.addWidget(safe_note)

        subtitle_divider = QFrame()
        subtitle_divider.setFrameShape(QFrame.Shape.HLine)
        subtitle_divider.setStyleSheet(f'color: {BORDER};')
        form_layout.addWidget(subtitle_divider)

        export_style_title = QLabel('Ghi đè riêng khi xuất')
        export_style_title.setObjectName('exportSection')
        form_layout.addWidget(export_style_title)

        live_font_size = 24
        if snapshot is not None:
            try:
                live_font_size = int(snapshot.style.get('font_size', 24))
            except (TypeError, ValueError):
                live_font_size = 24
        self.override_font_size = QCheckBox('Ghi đè cỡ chữ khi xuất')
        form_layout.addWidget(self.override_font_size)
        font_row = QHBoxLayout()
        self.font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_size_slider.setRange(10, 96)
        self.font_size_slider.setValue(max(10, min(96, live_font_size)))
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 96)
        self.font_size.setValue(max(10, min(96, live_font_size)))
        self.font_size.setSuffix(' px')
        font_row.addWidget(self.font_size_slider, 1)
        font_row.addWidget(self.font_size)
        form_layout.addLayout(font_row)
        font_note = QLabel(f'Tắt = dùng cỡ chữ đang hiển thị trong app ({live_font_size}px).')
        font_note.setObjectName('exportMuted')
        form_layout.addWidget(font_note)

        position_grid = QGridLayout()
        position_grid.addWidget(QLabel('Dịch ngang'), 0, 0)
        self.subtitle_x = QSlider(Qt.Orientation.Horizontal)
        self.subtitle_x.setRange(-35, 35)
        self.subtitle_x.setValue(0)
        self.subtitle_x_value = QSpinBox()
        self.subtitle_x_value.setRange(-35, 35)
        self.subtitle_x_value.setValue(0)
        self.subtitle_x_value.setSuffix('%')
        position_grid.addWidget(self.subtitle_x, 0, 1)
        position_grid.addWidget(self.subtitle_x_value, 0, 2)
        position_grid.addWidget(QLabel('Dịch dọc (+ lên)'), 1, 0)
        self.subtitle_y = QSlider(Qt.Orientation.Horizontal)
        self.subtitle_y.setRange(-35, 35)
        self.subtitle_y.setValue(0)
        self.subtitle_y_value = QSpinBox()
        self.subtitle_y_value.setRange(-35, 35)
        self.subtitle_y_value.setValue(0)
        self.subtitle_y_value.setSuffix('%')
        position_grid.addWidget(self.subtitle_y, 1, 1)
        position_grid.addWidget(self.subtitle_y_value, 1, 2)
        form_layout.addLayout(position_grid)

        reset_position = QPushButton('Đưa vị trí sub về như trong app')
        reset_position.clicked.connect(self._reset_subtitle_position)
        form_layout.addWidget(reset_position)

        self.override_bg_opacity = QCheckBox('Ghi đè độ trong nền subtitle')
        form_layout.addWidget(self.override_bg_opacity)
        opacity_row = QHBoxLayout()
        self.bg_opacity = QSlider(Qt.Orientation.Horizontal)
        self.bg_opacity.setRange(0, 100)
        live_opacity = 50
        if snapshot is not None:
            try:
                live_opacity = round(float(snapshot.style.get('bg_opacity', .5))*100)
            except (TypeError, ValueError):
                live_opacity = 50
        self.bg_opacity.setValue(max(0, min(100, live_opacity)))
        self.bg_opacity_value = QSpinBox()
        self.bg_opacity_value.setRange(0, 100)
        self.bg_opacity_value.setSuffix('%')
        self.bg_opacity_value.setValue(max(0, min(100, live_opacity)))
        opacity_row.addWidget(self.bg_opacity, 1)
        opacity_row.addWidget(self.bg_opacity_value)
        form_layout.addLayout(opacity_row)

        self.output_summary = QLabel()
        self.output_summary.setObjectName('exportMuted')
        self.output_summary.setWordWrap(True)
        form_layout.addWidget(self.output_summary)
        form_layout.addStretch()
        scroll.setWidget(content)
        settings_outer.addWidget(scroll)
        body.addWidget(settings_card, 2)
        root.addLayout(body, 1)

        footer = QHBoxLayout()
        footer_note = QLabel('Bản xuất re-encode hình để burn-in lyric; audio sẽ copy khi container hỗ trợ.')
        footer_note.setObjectName('exportMuted')
        footer.addWidget(footer_note, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText('Tiếp tục xuất')
        ok.setProperty('role', 'primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Hủy')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        root.addLayout(footer)

        self.resolution.currentIndexChanged.connect(self._update_custom_size_state)
        self.safe_subtitles.toggled.connect(self.safe_horizontal.setEnabled)
        self.safe_subtitles.toggled.connect(self.safe_vertical.setEnabled)
        for control in (
            self.container, self.aspect, self.resolution, self.fit_mode,
            self.background, self.fps, self.quality,
        ):
            control.currentIndexChanged.connect(self._refresh_preview)
        for spin in (self.custom_width, self.custom_height, self.safe_horizontal, self.safe_vertical):
            spin.valueChanged.connect(self._refresh_preview)
        self.preview_cue.currentIndexChanged.connect(self._preview_cue_changed)
        self.override_font_size.toggled.connect(self._update_export_override_state)
        self.font_size_slider.valueChanged.connect(self.font_size.setValue)
        self.font_size.valueChanged.connect(self.font_size_slider.setValue)
        self.font_size.valueChanged.connect(self._refresh_preview)
        self.subtitle_x.valueChanged.connect(self.subtitle_x_value.setValue)
        self.subtitle_x_value.valueChanged.connect(self.subtitle_x.setValue)
        self.subtitle_x_value.valueChanged.connect(self._refresh_preview)
        self.subtitle_y.valueChanged.connect(self.subtitle_y_value.setValue)
        self.subtitle_y_value.valueChanged.connect(self.subtitle_y.setValue)
        self.subtitle_y_value.valueChanged.connect(self._refresh_preview)
        self.override_bg_opacity.toggled.connect(self._update_export_override_state)
        self.bg_opacity.valueChanged.connect(self.bg_opacity_value.setValue)
        self.bg_opacity_value.valueChanged.connect(self.bg_opacity.setValue)
        self.bg_opacity_value.valueChanged.connect(self._refresh_preview)
        self.safe_subtitles.toggled.connect(self._refresh_preview)
        self._update_export_override_state()
        self._update_custom_size_state()
        self._refresh_preview()
        self._start_high_quality_preview()

    def _apply_quick_preset(self, aspect, resolution):
        self.aspect.setCurrentIndex(max(0, self.aspect.findData(aspect)))
        self.resolution.setCurrentIndex(max(0, self.resolution.findData(resolution)))
        self.fit_mode.setCurrentIndex(max(0, self.fit_mode.findData('contain')))
        self.quality.setCurrentIndex(max(0, self.quality.findData('high')))
        self._refresh_preview()

    def _reset_recommended(self):
        self.container.setCurrentIndex(max(0, self.container.findData('mp4')))
        self.aspect.setCurrentIndex(max(0, self.aspect.findData('source')))
        self.resolution.setCurrentIndex(max(0, self.resolution.findData('source')))
        self.fit_mode.setCurrentIndex(max(0, self.fit_mode.findData('contain')))
        self.background.setCurrentIndex(max(0, self.background.findData('black')))
        self.fps.setCurrentIndex(0)
        self.quality.setCurrentIndex(max(0, self.quality.findData('high')))
        self.safe_subtitles.setChecked(True)
        self.safe_horizontal.setValue(0)
        self.safe_vertical.setValue(0)
        self.override_font_size.setChecked(False)
        self.subtitle_x_value.setValue(0)
        self.subtitle_y_value.setValue(0)
        self.override_bg_opacity.setChecked(False)
        self._refresh_preview()

    def _reset_subtitle_position(self):
        self.subtitle_x_value.setValue(0)
        self.subtitle_y_value.setValue(0)

    def _update_export_override_state(self, *_args):
        font_enabled = self.override_font_size.isChecked()
        self.font_size_slider.setEnabled(font_enabled)
        self.font_size.setEnabled(font_enabled)
        opacity_enabled = self.override_bg_opacity.isChecked()
        self.bg_opacity.setEnabled(opacity_enabled)
        self.bg_opacity_value.setEnabled(opacity_enabled)
        self._refresh_preview()

    def _preview_cue_changed(self, _index=None):
        cue_index = self.preview_cue.currentData()
        if cue_index is None:
            cue_index = 0
        self.preview.set_preview_cue_index(int(cue_index))
        self._start_high_quality_preview()

    def _start_high_quality_preview(self):
        if self.snapshot is None or not self.snapshot.source:
            return
        source = Path(self.snapshot.source)
        if not source.is_file():
            return
        try:
            ffmpeg = find_tool('ffmpeg')
        except Exception:
            return
        previous = getattr(self, '_preview_process', None)
        if previous is not None and previous.state() != QProcess.ProcessState.NotRunning:
            previous.kill()
        cue_index = self.preview_cue.currentData() if self.preview_cue.count() else 0
        cue_index = int(cue_index or 0)
        cue_index = min(max(0, cue_index), len(self.snapshot.cues)-1)
        cue = self.snapshot.cues[cue_index]
        seek_seconds = max(0.0, float(cue.start)/1000.0 + 0.08)
        process = QProcess(self)
        self._preview_process = process
        process.setProgram(str(ffmpeg))
        process.setArguments([
            '-hide_banner', '-loglevel', 'error', '-ss', f'{seek_seconds:.3f}',
            '-i', str(source), '-frames:v', '1', '-an', '-sn',
            '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos',
            '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1',
        ])
        process.finished.connect(
            lambda *_args, p=process: self._high_quality_preview_finished(p)
        )
        process.start()

    def _high_quality_preview_finished(self, process):
        if process is not getattr(self, '_preview_process', None):
            process.deleteLater()
            return
        data = bytes(process.readAllStandardOutput())
        image = QImage.fromData(data)
        if not image.isNull():
            self.preview.set_source_image(image)
        self._preview_process = None
        process.deleteLater()

    def done(self, result):
        process = getattr(self, '_preview_process', None)
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(250)
        self._preview_process = None
        super().done(result)

    def _swap_custom_size(self):
        width, height = self.custom_width.value(), self.custom_height.value()
        self.custom_width.setValue(height)
        self.custom_height.setValue(width)
        self._refresh_preview()

    def _update_custom_size_state(self, _index=None):
        enabled = self.resolution.currentData() == 'custom'
        self.custom_width.setEnabled(enabled)
        self.custom_height.setEnabled(enabled)
        self.swap_custom.setEnabled(enabled)
        self.aspect.setEnabled(not enabled)
        self._refresh_preview()

    def _summary_text(self):
        settings = self.settings()
        if settings.resolution == 'custom':
            size = f'{settings.custom_width}×{settings.custom_height}'
        elif settings.resolution == 'source':
            size = 'độ phân giải nguồn'
        else:
            size = f'{settings.resolution}p'
        fps = 'FPS nguồn' if settings.fps is None else f'{int(settings.fps)} FPS'
        font = f' • chữ {settings.font_size}px' if settings.override_font_size else ''
        return (f'{settings.container.upper()} • {size} • {fps} • '
                f'CRF {QUALITY_CRF.get(settings.quality, 18)}{font}')

    def _refresh_preview(self, *_args):
        if not hasattr(self, 'preview'):
            return
        settings = self.settings()
        self.preview.set_settings(settings)
        fit_labels = {'contain': 'Vừa khung', 'cover': 'Lấp đầy', 'stretch': 'Kéo giãn'}
        aspect = settings.aspect if settings.resolution != 'custom' else f'{settings.custom_width}:{settings.custom_height}'
        self.preview_status.setText(
            f'{aspect} • {fit_labels.get(settings.fit_mode, settings.fit_mode)} • '
            f'{self.quality.currentText()}'
        )
        self.output_summary.setText('Đầu ra: ' + self._summary_text())
        self.background.setEnabled(settings.fit_mode == 'contain')

    def settings(self):
        return ExportSettings(
            container=str(self.container.currentData()), aspect=str(self.aspect.currentData()),
            resolution=str(self.resolution.currentData()), fit_mode=str(self.fit_mode.currentData()),
            background=str(self.background.currentData()), fps=self.fps.currentData(),
            quality=str(self.quality.currentData()), safe_subtitles=self.safe_subtitles.isChecked(),
            safe_horizontal_percent=self.safe_horizontal.value(),
            safe_vertical_percent=self.safe_vertical.value(),
            override_font_size=self.override_font_size.isChecked(),
            font_size=self.font_size.value(),
            subtitle_x_percent=self.subtitle_x_value.value(),
            subtitle_y_percent=self.subtitle_y_value.value(),
            override_bg_opacity=self.override_bg_opacity.isChecked(),
            bg_opacity_percent=self.bg_opacity_value.value(),
            custom_width=self.custom_width.value(), custom_height=self.custom_height.value(),
        )


@dataclass(frozen=True)
class ExportCue:
    index: int
    start: float
    end: float
    text: str
    previous_source_end: float | None = None
    box_width: int = 0
    box_height: int = 0
    contents_x: int = 0
    contents_y: int = 0
    contents_width: int = 0
    contents_height: int = 0
    sweep_row_groups: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExportSnapshot:
    source: str
    cues: tuple[ExportCue, ...]
    style: dict
    effects: dict
    fade_enabled: bool
    anchor_width: int
    anchor_height: int
    user_moved: bool
    rel_x_offset: int
    bottom_offset: int
    anchor_x: int = 0
    anchor_y: int = 0
    video_x: int = 0
    video_y: int = 0
    video_width: int = 0
    video_height: int = 0
    video_aspect_mode: str = 'contain'


def snapshot_from_window(window) -> ExportSnapshot:
    """Capture presentation state on the GUI thread without mutating the layer."""
    controller = getattr(window, 'app_controller', None)
    item = getattr(controller, 'current_media_item', None)
    source = str(getattr(item, 'path', '') or '')
    layer = getattr(window, 'sub_layer', None)
    if layer is None:
        raise RuntimeError('Không tìm thấy lớp phụ đề hiện tại.')

    # QLabel.sizeHint/adjustSize includes the active Qt stylesheet box model.
    # Snapshot it on the GUI thread so the worker does not have to approximate
    # padding/leading or create QWidget instances off-thread.
    size_probe = QLabel(layer)
    size_probe.setStyleSheet(layer.styleSheet())
    size_probe.setFont(layer.font())
    try:
        size_probe.setAlignment(layer.alignment())
        size_probe.setWordWrap(layer.wordWrap())
        size_probe.setTextFormat(layer.textFormat())
        size_probe.setMargin(layer.margin())
        size_probe.setIndent(layer.indent())
    except AttributeError:
        pass
    size_probe.ensurePolished()

    cues = []
    source_cues = tuple(getattr(layer, 'subtitles', ()) or ())
    for index, cue in enumerate(source_cues):
        text = layer.build_text(cue).strip()
        if not text:
            continue
        start = float(cue.get('start', 0) or 0)
        end = float(cue.get('end', 0) or 0)
        if end < start:
            continue
        previous_source_end = None
        if index > 0:
            try:
                previous_source_end = float(source_cues[index-1].get('end', 0) or 0)
            except (AttributeError, TypeError, ValueError):
                previous_source_end = 0.0
        size_probe.setText(text)
        size_probe.adjustSize()
        probe_contents = size_probe.contentsRect()
        cues.append(ExportCue(
            index, start, end, text, previous_source_end,
            box_width=max(1, int(size_probe.width())),
            box_height=max(1, int(size_probe.height())),
            contents_x=int(probe_contents.x()),
            contents_y=int(probe_contents.y()),
            contents_width=max(1, int(probe_contents.width())),
            contents_height=max(1, int(probe_contents.height())),
            sweep_row_groups=subtitle_row_groups(text, getattr(layer, 'mode', None), cue),
        ))
    size_probe.deleteLater()

    anchor = layer._anchor_geometry() if hasattr(layer, '_anchor_geometry') else None
    anchor_x = int(anchor.x()) if anchor is not None else 0
    anchor_y = int(anchor.y()) if anchor is not None else 0
    anchor_width = int(anchor.width()) if anchor is not None else 0
    anchor_height = int(anchor.height()) if anchor is not None else 0
    video_x = video_y = video_width = video_height = 0
    video_aspect_mode = 'contain'
    video = getattr(window, 'video_display', None)
    if video is not None:
        try:
            video_top_left = video.mapToGlobal(QPoint(0, 0))
            video_x, video_y = int(video_top_left.x()), int(video_top_left.y())
            video_width, video_height = int(video.width()), int(video.height())
        except (AttributeError, RuntimeError):
            pass
        try:
            aspect_mode = video.aspectRatioMode()
            if aspect_mode == Qt.AspectRatioMode.IgnoreAspectRatio:
                video_aspect_mode = 'stretch'
            elif aspect_mode == Qt.AspectRatioMode.KeepAspectRatioByExpanding:
                video_aspect_mode = 'cover'
        except (AttributeError, RuntimeError):
            pass
    if (video_width <= 0 or video_height <= 0) and (anchor_width < 160 or anchor_height < 120):
        if video is not None:
            anchor_width = max(anchor_width, int(video.width()))
            anchor_height = max(anchor_height, int(video.height()))

    live_font = layer.font()
    live_pixel_size = int(live_font.pixelSize())
    # Ask the real live QLabel for its resolved stylesheet padding.  This is
    # more exact than duplicating the QSS constants in the exporter and also
    # stays correct if the live subtitle theme changes later.
    pad_left = pad_right = 12
    pad_top = pad_bottom = 6
    try:
        layer_rect = layer.rect()
        contents_rect = layer.contentsRect()
        pad_left = max(0, int(contents_rect.x()-layer_rect.x()))
        pad_top = max(0, int(contents_rect.y()-layer_rect.y()))
        pad_right = max(0, int(layer_rect.width()-contents_rect.width()-pad_left))
        pad_bottom = max(0, int(layer_rect.height()-contents_rect.height()-pad_top))
    except (AttributeError, RuntimeError):
        pass
    style = {
        'font_size': live_pixel_size if live_pixel_size > 0 else int(getattr(layer, 'current_font_size', 24)),
        'font_family': str(live_font.family() or 'Segoe UI'),
        'font_weight': int(live_font.weight()),
        'font_color': str(getattr(layer, 'current_color', '#FFFF00')),
        'bg_color': str(getattr(layer, 'current_bg_color', '#000000')),
        'bg_opacity': float(getattr(layer, 'current_bg_opacity', .5)),
        'outline_enabled': bool(getattr(layer, 'use_outline', True)),
        'outline_width': int(getattr(layer, 'outline_width', 4)),
        'outline_color': str(getattr(layer, 'outline_color', '#000000')),
        'shadow_enabled': bool(getattr(layer, 'use_shadow', True)),
        'shadow_alpha': int(getattr(layer, 'shadow_alpha', 160)),
        'padding_left': pad_left,
        'padding_right': pad_right,
        'padding_top': pad_top,
        'padding_bottom': pad_bottom,
    }
    effects = copy.deepcopy(getattr(getattr(layer, '_subtitle_effects', None), 'options', {}))
    user_moved = bool(getattr(layer, '_user_moved', False))
    bottom_offset = (int(getattr(layer, '_rel_y_from_bottom', 0)) if user_moved
                     else int(getattr(layer, '_current_margin', 40)))
    return ExportSnapshot(
        source=source,
        cues=tuple(cues),
        style=style,
        effects=normalize_options(effects),
        fade_enabled=bool(getattr(layer, 'use_fade_effect', True)),
        anchor_width=max(1, anchor_width),
        anchor_height=max(1, anchor_height),
        user_moved=user_moved,
        rel_x_offset=int(getattr(layer, '_rel_x_offset', 0)) if user_moved else 0,
        # Keep the signed drag offset.  The live layer can be moved partly
        # outside its anchor; FFmpeg's overlay clipping should reproduce that
        # placement instead of silently snapping the export back inside.
        bottom_offset=bottom_offset,
        anchor_x=anchor_x,
        anchor_y=anchor_y,
        video_x=video_x,
        video_y=video_y,
        video_width=max(0, video_width),
        video_height=max(0, video_height),
        video_aspect_mode=video_aspect_mode,
    )


def _fraction(value, default=30.0):
    try:
        number = float(Fraction(str(value)))
        return number if math.isfinite(number) and number > 0 else default
    except (ValueError, ZeroDivisionError, TypeError):
        return default


def parse_probe(payload):
    streams = payload.get('streams') if isinstance(payload, dict) else None
    streams = streams if isinstance(streams, list) else []
    video = next((stream for stream in streams
                  if stream.get('codec_type') == 'video'
                  and not (stream.get('disposition') or {}).get('attached_pic')), None)
    if not video:
        raise RuntimeError('Video không có luồng hình ảnh để xuất.')
    width, height = int(video.get('width') or 0), int(video.get('height') or 0)
    if width <= 0 or height <= 0:
        raise RuntimeError('Không đọc được độ phân giải video.')
    rotation = 0
    try:
        rotation = int((video.get('tags') or {}).get('rotate') or 0)
    except (TypeError, ValueError):
        rotation = 0
    for side in video.get('side_data_list') or ():
        try:
            if 'rotation' in side:
                rotation = int(side['rotation'])
                break
        except (TypeError, ValueError):
            pass
    if abs(rotation) % 180 == 90:
        width, height = height, width
    fps = min(MAX_EXPORT_FPS, _fraction(video.get('avg_frame_rate') or video.get('r_frame_rate')))
    duration = 0.0
    for value in (video.get('duration'), (payload.get('format') or {}).get('duration')):
        try:
            duration = max(duration, float(value or 0))
        except (TypeError, ValueError):
            pass
    if duration <= 0:
        try:
            duration_ts = float(video.get('duration_ts') or 0)
            time_base = float(Fraction(str(video.get('time_base') or '0')))
            duration = max(duration, duration_ts*time_base)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    if duration <= 0:
        try:
            duration = max(duration, float(video.get('nb_frames') or 0)/fps)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    audio_codecs = tuple(str(stream.get('codec_name') or '').lower()
                         for stream in streams if stream.get('codec_type') == 'audio')
    return {'width': width, 'height': height, 'fps': fps, 'duration': duration,
            'audio_codecs': audio_codecs}


def audio_arguments(output_path, audio_codecs):
    suffix = Path(output_path).suffix.lower()
    if suffix == '.mkv' or all(codec in MP4_COPY_AUDIO for codec in audio_codecs):
        return ['-c:a', 'copy'], True
    return ['-c:a', 'aac', '-b:a', '320k'], False


class _RenderLabel(QObject):
    """Small QObject facade supplying the label API used by the effect painters."""
    def __init__(self, font, style, dpr=1.0):
        super().__init__()
        self._font = font
        self._text = ''
        self._size = QSize(1, 1)
        self._contents = QRect(0, 0, 1, 1)
        self._dpr = max(1.0, float(dpr))
        self.current_font_size = font.pixelSize()
        self.current_color = style['font_color']
        self.use_shadow = style['shadow_enabled']
        self.shadow_alpha = style['shadow_alpha']
        self.use_outline = style['outline_enabled']
        self.outline_width = style['outline_width']
        self.outline_color = style['outline_color']
        self.sweep_row_groups = ()

    def configure(self, text, size, contents, sweep_row_groups=()):
        self._text, self._size, self._contents = text, QSize(size), QRect(contents)
        self.sweep_row_groups = tuple(sweep_row_groups or ())

    def text(self): return self._text
    def font(self): return self._font
    def fontMetrics(self): return QFontMetrics(self._font)
    def size(self): return self._size
    def rect(self): return QRect(0, 0, self._size.width(), self._size.height())
    def contentsRect(self): return QRect(self._contents)
    def devicePixelRatioF(self): return self._dpr
    def isVisible(self): return True
    def update(self): pass


class SubtitleBandRenderer:
    """Deterministic media-time renderer reusing the production effect painters."""
    def __init__(self, snapshot: ExportSnapshot, width: int, height: int,
                 settings: ExportSettings | None = None, probe=None):
        self.snapshot = snapshot
        self.settings = settings or ExportSettings()
        self.width, self.height = width, height
        source_w = int((probe or {}).get('width') or width)
        source_h = int((probe or {}).get('height') or height)
        self.source_map = source_transform(width, height, source_w, source_h, self.settings)

        # Map the exact live screen coordinate system onto the transformed
        # source rectangle. This keeps the same apparent font size and
        # placement the user saw in QVideoWidget, even when the app window and
        # source video have different aspect ratios.
        has_live_video_rect = snapshot.video_width > 1 and snapshot.video_height > 1
        if has_live_video_rect:
            live_ratio_x = snapshot.video_width/max(1.0, float(source_w))
            live_ratio_y = snapshot.video_height/max(1.0, float(source_h))
            if snapshot.video_aspect_mode == 'stretch':
                live_scale_x, live_scale_y = live_ratio_x, live_ratio_y
            else:
                live_uniform_scale = (
                    max(live_ratio_x, live_ratio_y)
                    if snapshot.video_aspect_mode == 'cover'
                    else min(live_ratio_x, live_ratio_y)
                )
                live_scale_x = live_scale_y = live_uniform_scale
            live_content_w = source_w*live_scale_x
            live_content_h = source_h*live_scale_y
            live_content_x = snapshot.video_x + (snapshot.video_width-live_content_w)/2.0
            live_content_y = snapshot.video_y + (snapshot.video_height-live_content_h)/2.0
            live_center_x = snapshot.anchor_x + snapshot.anchor_width/2.0
            if snapshot.user_moved:
                live_center_x += snapshot.rel_x_offset
            live_bottom_y = snapshot.anchor_y + snapshot.anchor_height - snapshot.bottom_offset
            source_center_x = (live_center_x-live_content_x)/max(live_scale_x, 1e-9)
            source_bottom_y = (live_bottom_y-live_content_y)/max(live_scale_y, 1e-9)
            self.center_x = self.source_map['x'] + source_center_x*self.source_map['scale_x']
            self.bottom_y = self.source_map['y'] + source_bottom_y*self.source_map['scale_y']
            # Font-size is a vertical measure.  Matching the source/video
            # vertical scale reproduces the live apparent text height even if
            # either QVideoWidget or export uses the explicit stretch mode.
            font_scale = self.source_map['scale_y']/max(live_scale_y, 1e-9)
            self.scale = max(.20, min(8.0, font_scale))
        else:
            # Compatibility fallback for synthetic tests/older snapshots.
            reference_h = snapshot.anchor_height if snapshot.anchor_height >= 240 else 720
            self.scale = max(.35, min(4.0, height / max(1, reference_h)))
            self.center_x = width/2 + (snapshot.rel_x_offset*self.scale if snapshot.user_moved else 0)
            self.bottom_y = height-snapshot.bottom_offset*self.scale
        self.center_x += width*(self.settings.subtitle_x_percent/100.0)
        self.bottom_y -= height*(self.settings.subtitle_y_percent/100.0)
        style = dict(snapshot.style)
        if self.settings.override_font_size:
            style['font_size'] = max(8, int(self.settings.font_size))
        if self.settings.override_bg_opacity:
            style['bg_opacity'] = max(0.0, min(1.0, self.settings.bg_opacity_percent/100.0))
        font = QFont()
        font.setFamily(str(style.get('font_family') or 'Segoe UI'))
        try:
            font.setWeight(QFont.Weight(int(style.get('font_weight', int(QFont.Weight.Bold)))))
        except (TypeError, ValueError):
            font.setBold(True)
        # Paint in the same logical units as the live label, then scale the
        # complete raster.  This also scales the production painter's fixed
        # shadow/glow/particle geometry instead of enlarging only the font.
        font.setPixelSize(max(8, int(style['font_size'])))
        self.style, self.font = style, font
        self.metrics = QFontMetrics(font)
        self.pad_left = max(0, int(style.get('padding_left', 12)))
        self.pad_right = max(0, int(style.get('padding_right', 12)))
        self.pad_top = max(0, int(style.get('padding_top', 6)))
        self.pad_bottom = max(0, int(style.get('padding_bottom', 6)))
        visible_left = max(0.0, self.source_map['x'])
        visible_top = max(0.0, self.source_map['y'])
        visible_right = min(float(width), self.source_map['x']+self.source_map['width'])
        visible_bottom = min(float(height), self.source_map['y']+self.source_map['height'])
        if visible_right <= visible_left or visible_bottom <= visible_top:
            visible_left, visible_top = 0.0, 0.0
            visible_right, visible_bottom = float(width), float(height)
        visible_w = visible_right-visible_left
        visible_h = visible_bottom-visible_top
        safe_pad_x = (round(visible_w*self.settings.safe_horizontal_percent/100)
                      if self.settings.safe_subtitles else 0)
        safe_pad_y = (round(visible_h*self.settings.safe_vertical_percent/100)
                      if self.settings.safe_subtitles else 0)
        self.safe_left = round(visible_left) + safe_pad_x
        self.safe_right = round(visible_right) - safe_pad_x
        self.safe_top = round(visible_top) + safe_pad_y
        self.safe_bottom = round(visible_bottom) - safe_pad_y
        self.safe_x = safe_pad_x
        self.safe_y = safe_pad_y
        available_px = max(1, self.safe_right-self.safe_left)
        self.max_logical_text_width = max(
            1, math.floor(available_px/self.scale)-self.pad_left-self.pad_right
        )
        self._wrapped_cache = {}
        logical_band = max((
            self._geometry(self._display_text(cue.text), cue)[0].height()
            for cue in snapshot.cues
        ), default=16)
        logical_band = max(16, logical_band)
        safe_height = (max(1, self.safe_bottom-self.safe_top)
                       if self.settings.safe_subtitles else height)
        self.band_height = min(safe_height, max(1, math.ceil(logical_band*self.scale)))
        self.image = QImage(width, self.band_height, QImage.Format.Format_RGBA8888)
        if self.image.isNull():
            raise RuntimeError('Không cấp phát được bộ đệm hình phụ đề.')
        self._blank_frame = bytes(width*self.band_height*4)
        self._static_frame_key = None
        self._static_frame = None
        self.label = _RenderLabel(font, style, self.scale)
        self.effects = SubtitleEffects(self.label)
        self.effects.options = normalize_options(snapshot.effects)
        self._path_key = None
        self._path = None
        self._cue_starts = [cue.start for cue in snapshot.cues]
        overlay_y = round(self.bottom_y)-self.band_height
        if self.settings.safe_subtitles:
            maximum_y = max(self.safe_top, self.safe_bottom-self.band_height)
            overlay_y = min(max(overlay_y, self.safe_top), maximum_y)
        self.overlay_y = overlay_y

    def _split_long_token(self, token):
        chunks, current = [], ''
        for cluster in _graphemes(token):
            candidate = current + cluster
            if current and self.metrics.horizontalAdvance(candidate) > self.max_logical_text_width:
                chunks.append(current)
                current = cluster
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks or ['']

    def _wrap_line(self, line):
        if not line or self.metrics.horizontalAdvance(line) <= self.max_logical_text_width:
            return [line]
        words = line.split()
        if len(words) <= 1:
            return self._split_long_token(line)
        rows, current = [], ''
        for word in words:
            parts = ([word] if self.metrics.horizontalAdvance(word) <= self.max_logical_text_width
                     else self._split_long_token(word))
            for part in parts:
                candidate = part if not current else current + ' ' + part
                if current and self.metrics.horizontalAdvance(candidate) > self.max_logical_text_width:
                    rows.append(current)
                    current = part
                else:
                    current = candidate
        if current:
            rows.append(current)
        return rows or ['']

    def _display_text(self, text):
        cached = self._wrapped_cache.get(text)
        if cached is not None:
            return cached
        if not self.settings.safe_subtitles:
            result = text
        else:
            rows = []
            for line in text.split('\n'):
                rows.extend(self._wrap_line(line))
            result = '\n'.join(rows)
        self._wrapped_cache[text] = result
        return result

    def _display_row_groups(self, cue, display_text):
        source_lines = cue.text.split('\n')
        groups = tuple(cue.sweep_row_groups or ())
        if len(groups) != len(source_lines):
            return tuple(range(len(display_text.split('\n'))))
        if not self.settings.safe_subtitles:
            return groups
        expanded = []
        for index, line in enumerate(source_lines):
            expanded.extend([groups[index]] * len(self._wrap_line(line)))
        if len(expanded) != len(display_text.split('\n')):
            return tuple(range(len(display_text.split('\n'))))
        return tuple(expanded)

    def _geometry(self, text, cue=None):
        if (not self.settings.override_font_size
                and cue is not None and text == cue.text
                and cue.box_width > 0 and cue.box_height > 0
                and cue.contents_width > 0 and cue.contents_height > 0):
            return (
                QSize(cue.box_width, cue.box_height),
                QRect(cue.contents_x, cue.contents_y, cue.contents_width, cue.contents_height),
            )
        lines = text.split('\n')
        width = (max((self.metrics.horizontalAdvance(line) for line in lines), default=1)
                 + self.pad_left + self.pad_right)
        max_logical_width = self.max_logical_text_width + self.pad_left + self.pad_right
        width = min(max_logical_width, max(1, width))
        height = max(
            1, self.metrics.lineSpacing()*len(lines) + self.pad_top + self.pad_bottom
        )
        contents = QRect(
            self.pad_left,
            self.pad_top,
            max(1, width-self.pad_left-self.pad_right),
            max(1, height-self.pad_top-self.pad_bottom),
        )
        return QSize(width, height), contents

    def _path_for(self, text, size, contents):
        key = (text, size.width(), size.height(), contents.getRect())
        if key == self._path_key:
            return self._path
        path = QPainterPath()
        lines = text.split('\n')
        line_height = self.metrics.lineSpacing()
        total_h = line_height * len(lines)
        for index, line in enumerate(lines):
            x = contents.x() + (contents.width()-self.metrics.horizontalAdvance(line))/2
            y = contents.y() + (contents.height()-total_h)/2 + self.metrics.ascent() + index*line_height
            path.addText(x, y, self.font, line)
        self._path_key, self._path = key, path
        return path

    def _cue_at(self, pts_ms):
        if not self.snapshot.cues:
            return None, 0.0, False
        idx = bisect_right(self._cue_starts, pts_ms)-1
        if idx < 0:
            return None, 0.0, False
        cue = self.snapshot.cues[idx]
        if cue.start <= pts_ms <= cue.end:
            opacity = 1.0
            if self.snapshot.fade_enabled:
                prev_end = cue.previous_source_end
                if prev_end is None or cue.start-prev_end > 400:
                    t = min(1.0, max(0.0, (pts_ms-cue.start)/FADE_MS))
                    opacity = 1-(1-t)**3
            return cue, opacity, True
        if self.snapshot.fade_enabled and pts_ms <= cue.end+FADE_MS:
            next_start = self.snapshot.cues[idx+1].start if idx+1 < len(self.snapshot.cues) else math.inf
            if pts_ms < next_start:
                t = min(1.0, max(0.0, (pts_ms-cue.end)/FADE_MS))
                return cue, (1-t)**3, False
        return None, 0.0, False

    def _effect_phase(self, cue, pts_ms):
        options = self.effects.options
        duration = max(1, min(options['duration'], int((cue.end-cue.start)/2)))
        elapsed = max(0.0, pts_ms-cue.start)
        moving = (options['entrance'] != 'none' or options['soft_fade'] or options['shimmer']
                  or options['color'] == 'shift')
        return 1.0 if elapsed >= duration or not moving else min(1.0, elapsed/duration)

    def frame(self, pts_ms):
        cue, opacity, active = self._cue_at(pts_ms)
        if cue is None or opacity <= 0:
            return self._blank_frame
        display_text = self._display_text(cue.text)
        display_row_groups = self._display_row_groups(cue, display_text)

        # Most subtitle time is static text.  Re-use the already rasterized
        # band once entry/fade motion is settled; animated trails/kinetics keep
        # their timestamp-driven path.  Raw bytes are still piped for every
        # video frame, so FFmpeg timing stays unchanged.
        options = self.effects.options
        static_effect = (
            not options['enabled'] or (
                options['entrance'] == 'none'
                and not options['soft_fade']
                and not options['shimmer']
                and options['color'] != 'shift'
                and options['trail'] == 'none'
            )
        )
        static_key = (cue.index, display_text) if active and opacity == 1.0 and static_effect else None
        if static_key is not None and static_key == self._static_frame_key:
            return self._static_frame

        self.image.fill(Qt.GlobalColor.transparent)
        size, contents = self._geometry(display_text, cue)
        self.label.configure(display_text, size, contents, display_row_groups)
        path = self._path_for(display_text, size, contents)
        keep_erased_sweep = (
            not active
            and options['enabled']
            and options['trail'] != 'none'
            and options['erase_passed']
            and cue.end-cue.start >= 160
        )
        if active or keep_erased_sweep:
            self.effects.cue = (cue.index, cue.start, cue.end, display_text)
            if active:
                self.effects.progress = self._effect_phase(cue, pts_ms)
                self.effects.scan_progress = min(
                    1.0, max(0.0, (pts_ms-cue.start)/max(1, cue.end-cue.start))
                )
            else:
                # Match the live SubtitleLayer fade-out contract: once an
                # erase sweep has completed, keep its final mask while the
                # label opacity fades. Clearing cue here would make paint()
                # treat the frame as a fresh static phrase and flash the old
                # glyphs back immediately before the next cue.
                self.effects.progress = 1.0
                self.effects.scan_progress = 1.0
        else:
            self.effects.cue = None
            self.effects.progress = 1.0
            self.effects.scan_progress = 1.0

        target_w = max(1, math.ceil(size.width()*self.scale))
        target_h = max(1, math.ceil(size.height()*self.scale))
        label_image = QImage(target_w, target_h, QImage.Format.Format_ARGB32_Premultiplied)
        label_image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(label_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(self.scale, self.scale)
        painter.setOpacity(opacity)
        bg = QColor(self.style['bg_color'])
        if not bg.isValid():
            bg = QColor('#000000')
        bg.setAlpha(int(max(0.0, min(1.0, self.style['bg_opacity']))*255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRect(0, 0, size.width(), size.height()), 6, 6)
        if not self.effects.paint(painter, path):
            if self.style['shadow_enabled']:
                painter.fillPath(path.translated(2, 2),
                                 QColor(0, 0, 0, self.style['shadow_alpha']))
            if self.style['outline_enabled']:
                pen = QPen(QColor(self.style['outline_color']), self.style['outline_width'])
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawPath(path)
            painter.fillPath(path, QColor(self.style['font_color']))
        painter.end()

        x = round(self.center_x-target_w/2)
        if self.settings.safe_subtitles:
            max_x = max(self.safe_left, self.safe_right-target_w)
            x = min(max(x, self.safe_left), max_x)
        y = self.band_height-target_h
        band = QPainter(self.image)
        band.drawImage(x, y, label_image)
        band.end()
        result = self.image.bits().tobytes()
        if static_key is not None:
            self._static_frame_key = static_key
            self._static_frame = result
        return result


class VideoSubtitleExportWorker(QThread):
    progress = Signal(int, str)
    succeeded = Signal(str, bool, bool)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, snapshot: ExportSnapshot, output_path: str,
                 settings: ExportSettings | None = None, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.output_path = str(output_path)
        self.settings = settings or ExportSettings()
        self.processes = OwnedProcesses()

    def stop(self):
        self.requestInterruption()
        self.processes.stop()

    def _probe(self):
        ffprobe = find_tool('ffprobe')
        process = self.processes.track(subprocess.Popen([
            ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', self.snapshot.source
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
        out, err = process.communicate(timeout=8)
        self.processes.release(process)
        if process.returncode:
            raise RuntimeError((err or b'ffprobe failed').decode('utf-8', errors='replace')[-1200:])
        return parse_probe(json.loads(out.decode('utf-8', errors='replace')))

    def run(self):
        partial = None
        log_path = None
        try:
            if self.isInterruptionRequested():
                self.cancelled.emit(); return
            probe = self._probe()
            canvas_width, canvas_height = resolve_canvas(probe, self.settings)
            renderer = SubtitleBandRenderer(
                self.snapshot, canvas_width, canvas_height, self.settings, probe=probe
            )
            fps = min(MAX_EXPORT_FPS, float(self.settings.fps or probe['fps']))
            last_cue_ms = max(cue.end for cue in self.snapshot.cues)
            overlay_end_ms = last_cue_ms + (FADE_MS if self.snapshot.fade_enabled else 0)
            frame_count = max(1, math.ceil(max(0.0, overlay_end_ms)*fps/1000.0)+2)
            output = Path(self.output_path)
            partial = output.with_name(
                output.stem + f'.botube-exporting-{uuid.uuid4().hex}' + output.suffix
            )
            audio_args, audio_copied = audio_arguments(output, probe['audio_codecs'])
            ffmpeg = find_tool('ffmpeg')
            base_filter = source_video_filter(canvas_width, canvas_height, self.settings)
            if self.settings.fps is not None:
                base_filter += f',fps={fps:.6f}'
            # Composite subtitle pixels at full chroma resolution first.  If
            # the RGBA band is converted straight into the normal yuv420p
            # pipeline, thin colored glyph edges/outline can shimmer between
            # encoded frames and look softer than the Qt source raster.  A
            # yuv444 intermediate preserves those edges during the blend, then
            # the final format conversion returns to broadly compatible 4:2:0.
            filter_graph = subtitle_composition_filter(base_filter, renderer.overlay_y)
            threads = max(1, min(8, (os.cpu_count() or 2)//2))
            crf = QUALITY_CRF.get(self.settings.quality, 18)
            command = [
                ffmpeg, '-y', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-f', 'rawvideo', '-pixel_format', 'rgba',
                '-video_size', f"{canvas_width}x{renderer.band_height}",
                '-framerate', f'{fps:.6f}', '-i', 'pipe:0', '-i', self.snapshot.source,
                '-filter_complex', filter_graph, '-map', '[v]', '-map', '1:a?', '-map_metadata', '1',
                '-metadata:s:v:0', 'rotate=0',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', str(crf), '-pix_fmt', 'yuv420p',
                '-threads', str(threads), *audio_args,
            ]
            if output.suffix.lower() == '.mp4':
                command += ['-movflags', '+faststart']
            command.append(str(partial))

            handle = tempfile.NamedTemporaryFile(prefix='botube-video-export-', suffix='.log', delete=False)
            log_path = handle.name
            creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
            try:
                process = self.processes.track(subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=handle,
                    creationflags=creation,
                ))
            except Exception:
                handle.close()
                raise
            last_percent = -1
            try:
                for frame_index in range(frame_count):
                    if self.isInterruptionRequested():
                        self.processes.stop()
                        break
                    # Sample the visual state at the centre of the encoded
                    # frame interval.  Sampling on the left edge can turn a
                    # smooth 220 ms fade/entry into a larger first-step alpha
                    # jump when the cue begins between two video frames.
                    pts_ms = (frame_index + 0.5)*1000.0/fps
                    process.stdin.write(renderer.frame(pts_ms))
                    percent = min(97, int((frame_index+1)*98/frame_count))
                    if percent != last_percent:
                        last_percent = percent
                        self.progress.emit(percent, f'Đang dựng phụ đề và mã hóa video… {percent}%')
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                if not self.isInterruptionRequested():
                    self.progress.emit(98, 'Đang hoàn tất video…')
                return_code = process.wait()
            except (BrokenPipeError, OSError):
                return_code = process.wait()
            finally:
                handle.close()
                # Keep a still-running process owned if rendering itself raised;
                # the outer cleanup will stop/wait it before removing partials.
                if process.poll() is not None:
                    self.processes.release(process)

            if self.isInterruptionRequested():
                self.cancelled.emit(); return
            if return_code:
                detail = ''
                try:
                    detail = Path(log_path).read_text(encoding='utf-8', errors='replace')[-2000:]
                except OSError:
                    pass
                raise RuntimeError('FFmpeg không thể hoàn tất bản xuất.\n' + detail.strip())
            if not partial.is_file() or partial.stat().st_size <= 0:
                raise RuntimeError('FFmpeg kết thúc nhưng không tạo được file video hợp lệ.')
            os.replace(partial, output)
            partial = None
            self.progress.emit(100, 'Hoàn tất')
            self.succeeded.emit(str(output), audio_copied, bool(probe['audio_codecs']))
        except subprocess.TimeoutExpired:
            self.processes.stop()
            self.failed.emit('Đọc thông tin media quá thời gian cho phép.')
        except Exception as exc:
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
        finally:
            self.processes.stop()
            self.processes.wait()
            if partial is not None:
                try:
                    Path(partial).unlink(missing_ok=True)
                except OSError:
                    pass
            if log_path:
                try:
                    Path(log_path).unlink(missing_ok=True)
                except OSError:
                    pass


class VideoSubtitleExportController(QObject):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = weakref.ref(window)
        self._ui_parent = None
        self.worker = None
        self.progress_dialog = None

    def start(self, ui_parent=None):
        window = self._window()
        if window is None:
            return
        ui_parent = ui_parent or window
        self._ui_parent = weakref.ref(ui_parent)
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(ui_parent, 'Đang xuất video', 'Một video đang được xuất. Bạn có thể hủy ở hộp tiến trình.')
            return
        try:
            snapshot = snapshot_from_window(window)
        except Exception as exc:
            QMessageBox.warning(ui_parent, 'Không thể xuất video', str(exc)); return
        source = Path(snapshot.source)
        if not source.is_file():
            QMessageBox.warning(ui_parent, 'Không thể xuất video', 'File video hiện tại không tồn tại.'); return
        if not snapshot.cues:
            QMessageBox.information(ui_parent, 'Không có lyric để xuất',
                'Chế độ phụ đề hiện tại không có câu nào để hiển thị. Hãy bật/chọn lyric rồi thử lại.'); return

        media_item = getattr(getattr(window, 'app_controller', None), 'current_media_item', None)
        settings_dialog = VideoExportSettingsDialog(
            ui_parent, snapshot=snapshot, media_item=media_item
        )
        if settings_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = settings_dialog.settings()
        extension = '.mkv' if settings.container == 'mkv' else '.mp4'
        default = source.with_name(source.stem + '_lyrics' + extension)
        file_filter = ('Matroska MKV (*.mkv)' if settings.container == 'mkv'
                       else 'Video MP4 (*.mp4)')
        output, _selected = QFileDialog.getSaveFileName(
            ui_parent, 'Xuất video kèm phụ đề / lyric', str(default), file_filter)
        if not output:
            return
        path = Path(output)
        if path.suffix.lower() != extension:
            path = path.with_suffix(extension)
        try:
            if path.resolve() == source.resolve():
                QMessageBox.warning(ui_parent, 'Không thể ghi đè video gốc', 'Hãy chọn một tên file khác để giữ nguyên video nguồn.'); return
        except OSError:
            pass

        dialog = QProgressDialog('Đang chuẩn bị bản xuất…', 'Hủy', 0, 100, ui_parent)
        dialog.setWindowTitle('Xuất video + lyric')
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        worker = VideoSubtitleExportWorker(snapshot, str(path), settings=settings)
        self.worker, self.progress_dialog = worker, dialog
        dialog.canceled.connect(worker.stop)
        worker.progress.connect(self._progress)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(self._finished)
        dialog.show()
        worker.start(QThread.Priority.LowPriority)

    def _message_parent(self):
        window = self._window()
        parent = self._ui_parent() if self._ui_parent is not None else None
        if parent is not None:
            try:
                if parent.isVisible():
                    return parent
            except RuntimeError:
                pass
        return window

    def _progress(self, value, label):
        # QProgressDialog.setValue() may process events for a modal dialog.
        # During that nested event loop the worker can finish and _finished()
        # can clear self.progress_dialog. Keep the object for the whole slot so
        # the second UI update never dereferences a newly-cleared attribute.
        dialog = self.progress_dialog
        if dialog is None:
            return
        try:
            dialog.setLabelText(label)
            dialog.setValue(value)
        except RuntimeError:
            # The owning SubtitleToolsDialog can be closed while the
            # application-owned worker finishes or is being cancelled.
            if self.progress_dialog is dialog:
                self.progress_dialog = None

    def _succeeded(self, output, audio_copied, had_audio):
        parent = self._message_parent()
        dialog = self.progress_dialog
        if dialog is not None:
            try:
                dialog.setLabelText('Hoàn tất')
                dialog.setValue(100)
                dialog.close()
            except RuntimeError:
                pass
        if parent is not None:
            if not had_audio:
                audio = 'Video nguồn không có luồng âm thanh.'
            elif audio_copied:
                audio = 'Âm thanh được giữ nguyên luồng nguồn.'
            else:
                audio = 'Âm thanh đã đổi sang AAC 320 kb/s để tương thích MP4.'
            QMessageBox.information(parent, 'Xuất video hoàn tất', f'Đã tạo:\n{output}\n\n{audio}')

    def _failed(self, message):
        parent = self._message_parent()
        dialog = self.progress_dialog
        if dialog is not None:
            try:
                dialog.close()
            except RuntimeError:
                pass
        if parent is not None:
            QMessageBox.critical(parent, 'Xuất video thất bại', message[:3000])

    def _cancelled(self):
        dialog = self.progress_dialog
        if dialog is not None:
            try:
                dialog.close()
            except RuntimeError:
                pass

    def _finished(self):
        finished_worker = self.sender()
        if finished_worker is self.worker:
            self.worker = None
            self.progress_dialog = None
            self._ui_parent = None
        if finished_worker is not None:
            finished_worker.deleteLater()

    def shutdown(self):
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.stop()
            worker.wait()


def controller_for(window):
    application = QApplication.instance()
    if application is None:
        raise RuntimeError('Ứng dụng Qt chưa sẵn sàng.')
    controller = getattr(application, '_video_subtitle_export_controller', None)
    if controller is None or controller._window() is not window:
        controller = VideoSubtitleExportController(window, application)
        application._video_subtitle_export_controller = controller
        application.aboutToQuit.connect(controller.shutdown)
    return controller


class VideoExportButton(QPushButton):
    """Drop-in action for SubtitleToolsDialog; keeps the old dialog API intact."""
    def __init__(self, dialog):
        super().__init__('Xuất video + lyric', dialog)
        self._dialog = weakref.ref(dialog)
        self.setObjectName('primaryButton')
        button_icon(self, 'upload', 'Xuất video kèm phụ đề / lyric đang hiển thị', icon_only=False)
        self.clicked.connect(self._start_export)

    def _start_export(self):
        dialog = self._dialog()
        window = dialog.parent() if dialog is not None else None
        if window is None:
            return
        controller_for(window).start(dialog)
