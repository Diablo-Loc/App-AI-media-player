"""Compact optional effects controls and a preview using the real lyric painter."""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (QGroupBox, QVBoxLayout, QHBoxLayout, QLabel,
                              QComboBox, QCheckBox, QPushButton)

from ui.subtitle_effects import SubtitleEffects, ENTRANCES, COLORS, PRESETS, normalize_options
from ui.subtitle_particles import TRAILS, INTENSITIES


class SubtitleEffectsPanel(QGroupBox):
    changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__('Hiệu ứng phụ đề', parent)
        self.setObjectName('subtitleEffectsGroup')
        self.setCheckable(True)
        self.setChecked(False)
        self.setStyleSheet('''
            QGroupBox#subtitleEffectsGroup { border: 1px solid #405267;
                border-radius: 10px; margin-top: 14px; padding: 14px 8px 8px; }
            QGroupBox#subtitleEffectsGroup::title { subcontrol-origin: margin;
                left: 10px; padding: 0 5px; color: #74DFC2; }
        ''')
        layout = QVBoxLayout(self)
        layout.setSpacing(7)
        description = QLabel('Bật để kết hợp chuyển động, màu và ánh sáng.\nTắt để dùng cách hiển thị gốc.')
        description.setWordWrap(True)
        description.setStyleSheet('border: none; font-size: 11px; font-weight: normal; color: #A8B8CA;')
        layout.addWidget(description)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel('Bộ mẫu'))
        self.presets = QComboBox()
        for value, title, options in PRESETS:
            self.presets.addItem(title, value)
        preset_row.addWidget(self.presets, 1)
        layout.addLayout(preset_row)
        self.presets.currentIndexChanged.connect(self._preset_changed)
        self.entrance = self._choice(layout, 'Chuyển động', ENTRANCES)
        self.entrance.setToolTip('Chuyển động cả câu, giữ nguyên nét chữ và dấu của mọi ngôn ngữ.')
        self.color = self._choice(layout, 'Màu chữ', COLORS)
        self.trail = self._choice(layout, 'Dọc câu', TRAILS)
        self.trail.setToolTip('Quét theo thời lượng câu, không phải timing lời hát từng từ.\n'
                             'Câu dày tự gom vùng; dấu, emoji và chữ gốc vẫn giữ nguyên.')
        self.intensity = self._choice(layout, 'Mật độ', INTENSITIES)
        self.intensity.setToolTip('Nhẹ 8 / Vừa 16 / Rực rỡ 24 hạt tối đa, không tăng theo độ dài câu.')
        self.soft_fade = QCheckBox('Mờ dần khi vào câu')
        self.soft_fade.setToolTip('Mờ nhẹ phần chữ khi vào câu; Fade gốc vẫn điều khiển hiện/ẩn khung.')
        self.glow = QCheckBox('Ánh sáng viền nhẹ')
        self.shimmer = QCheckBox('Dải sáng lướt một lần')
        for widget in (self.soft_fade, self.glow, self.shimmer):
            layout.addWidget(widget)
            widget.toggled.connect(self._edited)
        self.duration = self._choice(layout, 'Độ dài', ((220, 'Nhanh · 220 ms'),
            (320, 'Vừa · 320 ms'), (480, 'Êm · 480 ms')))
        self.duration.setToolTip('Tự rút ngắn với câu ngắn; không kéo dài thời gian hiển thị sub.')
        # Import here: the layer imports only the effect engine, never this panel.
        from ui.subs_ui.subtitle_layer import DraggableSubtitle
        self.preview = DraggableSubtitle(self)
        self.preview.setText('Một câu hát dịu dàng\n優しいメロディー')
        self.preview.current_font_size = 18
        self.preview.current_bg_opacity = .15
        self.preview.update_style()
        self.preview.setMinimumHeight(72)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.preview._subtitle_effects = SubtitleEffects(self.preview)
        layout.addWidget(self.preview)
        self.preview_button = QPushButton('Xem thử hiệu ứng')
        self.preview_button.setToolTip('Xem mẫu ngay tại đây, không thay đổi video đang phát.')
        self.preview_button.clicked.connect(self.play_preview)
        layout.addWidget(self.preview_button)
        self.sync_options(None)
        self.toggled.connect(self._edited)

    def _choice(self, layout, title, choices):
        row = QHBoxLayout()
        label = QLabel(title)
        label.setStyleSheet('border: none; font-weight: normal; font-size: 12px;')
        row.addWidget(label)
        combo = QComboBox()
        for value, text in choices:
            combo.addItem(text, value)
        row.addWidget(combo, 1)
        layout.addLayout(row)
        combo.currentIndexChanged.connect(self._edited)
        return combo

    def options(self):
        return normalize_options(dict(enabled=self.isChecked(), entrance=self.entrance.currentData(),
            color=self.color.currentData(), soft_fade=self.soft_fade.isChecked(),
            glow=self.glow.isChecked(), shimmer=self.shimmer.isChecked(),
            duration=self.duration.currentData(), trail=self.trail.currentData(),
            intensity=self.intensity.currentData()))

    def sync_options(self, value):
        options = normalize_options(value)
        widgets = (self, self.presets, self.entrance, self.color, self.duration, self.trail, self.intensity,
                   self.soft_fade, self.glow, self.shimmer)
        blockers = [QSignalBlocker(widget) for widget in widgets]
        self.setChecked(options['enabled'])
        for combo, key in ((self.entrance, 'entrance'), (self.color, 'color'),
                           (self.trail, 'trail'), (self.intensity, 'intensity')):
            combo.setCurrentIndex(combo.findData(options[key]))
        index = self.duration.findData(options['duration'])
        if index < 0:
            self.duration.addItem(f"Tùy chỉnh · {options['duration']} ms", options['duration'])
            index = self.duration.findData(options['duration'])
        self.duration.setCurrentIndex(index)
        for widget, key in ((self.soft_fade, 'soft_fade'), (self.glow, 'glow'), (self.shimmer, 'shimmer')):
            widget.setChecked(options[key])
        del blockers
        self._sync_preset()
        self.preview._subtitle_effects.configure(options)

    def _edited(self, *args):
        self._sync_preset()
        self.preview._subtitle_effects.configure(self.options())
        self.changed.emit(self.options())

    def _sync_preset(self):
        options = self.options()
        selected = 0
        for index, (name, title, settings) in enumerate(PRESETS):
            if settings and all(options[key] == value for key, value in settings.items()):
                selected = index
                break
        blocker = QSignalBlocker(self.presets)
        self.presets.setCurrentIndex(selected)

    def _preset_changed(self, index):
        if index == 0:
            return
        options = self.options()
        options.update(PRESETS[index][2])
        options.update(soft_fade=True, shimmer=False, glow=False)
        self.sync_options(options)
        self.changed.emit(self.options())
        self.play_preview()

    def play_preview(self):
        effect = self.preview._subtitle_effects
        effect.clear()
        effect.sync((0, 0, 3000, self.preview.text()), 0)

    def hideEvent(self, event):
        self.preview._subtitle_effects.settle()
        super().hideEvent(event)
