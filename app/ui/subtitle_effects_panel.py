"""Wide zero-scroll subtitle VFX controls aligned with BoTube's Fluent Dark design system."""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QGridLayout,
    QFrame,
    QLabel,
    QComboBox,
    QCheckBox,
    QPushButton,
    QSizePolicy,
)

from ui.icons import INK, button_icon
from ui.subtitle_effects import SubtitleEffects, ENTRANCES, COLORS, PRESETS, ALL_TRAILS as TRAILS, normalize_options
from ui.subtitle_particles import INTENSITIES
from ui.subtitle_kinetic import STRENGTHS, PARTS, KINETIC_MODES, CHOREO_EXIT_MODES


class SubtitleEffectsPanel(QGroupBox):
    changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__('Hiệu ứng phụ đề && Xem thử', parent)
        self.setObjectName('subtitleEffectsGroup')
        self.setCheckable(True)
        self.setChecked(False)
        self.setStyleSheet('''
            QGroupBox#subtitleEffectsGroup {
                background-color: #131A24;
                border: 1px solid #233042;
                border-radius: 10px;
                margin-top: 12px;
                padding: 12px 12px 10px;
            }
            QGroupBox#subtitleEffectsGroup::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #77E0BE;
                font-weight: 700;
                font-size: 12px;
            }
            QGroupBox#subtitleEffectsGroup::indicator {
                width: 13px;
                height: 13px;
                border-radius: 4px;
                border: 1px solid #3A4B61;
                background-color: #18212E;
            }
            QGroupBox#subtitleEffectsGroup::indicator:checked {
                border: 2px solid #77E0BE;
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.46, fx:0.5, fy:0.5,
                    stop:0 #77E0BE, stop:0.72 #77E0BE, stop:0.76 #131A24, stop:1 #131A24);
            }
            QFrame#vfxPreviewStage {
                background-color: #090D13;
                border: 1px solid #202B3B;
                border-radius: 8px;
            }
            QPushButton#vfxPreviewBtn {
                background-color: #77E0BE;
                border: 1px solid #77E0BE;
                border-radius: 8px;
                padding: 6px 14px;
                color: #0D1118;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton#vfxPreviewBtn:hover {
                background-color: #9AEDD3;
                border-color: #9AEDD3;
            }
            QPushButton#vfxPreviewBtn:pressed {
                background-color: #5FD3AD;
            }
        ''')

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(2, 4, 2, 2)

        # Compact 4x2 dropdown grid (zero scrolling, wide readable labels)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)

        self.presets = self._grid_choice(grid, 0, 0, 'Bộ mẫu nhanh', [(v, t) for v, t, _ in PRESETS], connect=False)
        self.presets.currentIndexChanged.connect(self._preset_changed)

        self.entrance = self._grid_choice(grid, 0, 1, 'Chuyển động câu', ENTRANCES)
        self.entrance.setToolTip('Chuyển động vào và thoát câu mượt 60 FPS.')

        self.color = self._grid_choice(grid, 1, 0, 'Màu sắc & Ánh kim', COLORS)
        self.trail = self._grid_choice(grid, 1, 1, 'Hiệu ứng dọc câu', TRAILS)
        self.trail.setToolTip('Đồng bộ theo tiến độ câu đang hát.')

        self.intensity = self._grid_choice(grid, 2, 0, 'Mật độ hạt', INTENSITIES)
        self.intensity.setToolTip('Nhẹ 8 / Vừa 16 / Rực rỡ 24 hạt tối đa.')

        self.duration = self._grid_choice(grid, 2, 1, 'Tốc độ hiệu ứng', (
            (220, 'Rất nhanh · 220 ms'),
            (260, 'Nhanh · 260 ms'),
            (320, 'Vừa · 320 ms'),
            (360, 'Êm · 360 ms'),
            (440, 'Điện ảnh · 440 ms'),
            (480, 'Mềm · 480 ms'),
            (540, 'Hoành tráng · 540 ms'),
        ))
        self.duration.setToolTip('Tự rút ngắn với câu ngắn; không làm lệch mốc hiển thị sub.')

        self.kinetic_strength = self._grid_choice(grid, 3, 0, 'Lực typography', STRENGTHS)
        self.kinetic_parts = self._grid_choice(grid, 3, 1, 'Chia cụm chữ', PARTS)
        self.kinetic_strength.setToolTip('Áp dụng cho nhóm hiệu ứng typography.')
        self.kinetic_parts.setToolTip('Tối đa 16 cụm; giữ nguyên dấu tiếng Việt, Nhật và emoji.')

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        # Compact 2x2 checkboxes row
        chk_grid = QGridLayout()
        chk_grid.setHorizontalSpacing(10)
        chk_grid.setVerticalSpacing(2)
        self.erase_passed = QCheckBox('Ẩn chữ sau vệt quét')
        self.erase_passed.setToolTip('Từ đã quét sẽ ẩn tới hết câu; sang câu mới hoặc tua lại hiện bình thường.')
        self.soft_fade = QCheckBox('Mờ dần khi vào câu')
        self.soft_fade.setToolTip('Mờ nhẹ phần chữ khi vào câu.')
        self.glow = QCheckBox('Ánh sáng viền quang học')
        self.shimmer = QCheckBox('Dải sáng lướt một lần')
        for idx, widget in enumerate((self.erase_passed, self.soft_fade, self.glow, self.shimmer)):
            chk_grid.addWidget(widget, idx // 2, idx % 2)
            widget.toggled.connect(self._edited)
        layout.addLayout(chk_grid)

        # Wide real-renderer VFX preview stage
        stage = QFrame(self)
        stage.setObjectName('vfxPreviewStage')
        stage.setMinimumHeight(92)
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(6, 4, 6, 4)

        from ui.subs_ui.subtitle_layer import DraggableSubtitle
        self.preview = DraggableSubtitle(stage)
        self.preview.bilingual_hierarchy = False
        self.preview.sweep_row_groups = (0, 1)
        self.preview.setText('Racing into the starlit midnight\nLao vào màn đêm rực ánh sao')
        self.preview.current_font_size = 18
        self.preview.current_color = '#FFFFFF'
        self.preview.current_bg_color = '#0D1118'
        self.preview.current_bg_opacity = 0.0
        self.preview.outline_width = 2
        self.preview.outline_color = '#060913'
        self.preview.update_style()
        self.preview.setMinimumHeight(84)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.preview._subtitle_effects = SubtitleEffects(self.preview)
        self._preview_lines = (
            'Racing into the starlit midnight\nLao vào màn đêm rực ánh sao',
            'Anh vẫn chờ em giữa ánh đèn đêm\nEvery letter dancing to the beat',
        )
        self._preview_idx = 0
        stage_layout.addWidget(self.preview)
        layout.addWidget(stage, 1)

        self.preview_button = QPushButton(' Xem thử hiệu ứng')
        self.preview_button.setObjectName('vfxPreviewBtn')
        self.preview_button.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.preview_button, 'play', 'Xem thử hiệu ứng', color=INK, size=14, icon_only=False)
        self.preview_button.setToolTip('Xem thử hiệu ứng trực tiếp, không ảnh hưởng video đang phát.')
        self.preview_button.clicked.connect(self.play_preview)
        layout.addWidget(self.preview_button)

        self.sync_options(None)
        self.toggled.connect(self._edited)

    def _grid_choice(self, grid, row, col, title, choices, connect=True):
        box = QVBoxLayout()
        box.setSpacing(2)
        lbl = QLabel(title)
        lbl.setStyleSheet('border: none; font-weight: 600; font-size: 11px; color: #8FA1B6; margin: 0;')
        box.addWidget(lbl)
        combo = QComboBox()
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(10)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setMinimumWidth(0)
        for value, text in choices:
            combo.addItem(text, value)
        combo.view().setMinimumWidth(290)
        box.addWidget(combo)
        grid.addLayout(box, row, col)
        if connect:
            combo.currentIndexChanged.connect(self._edited)
        return combo

    def options(self):
        return normalize_options(dict(
            enabled=self.isChecked(),
            entrance=self.entrance.currentData(),
            color=self.color.currentData(),
            soft_fade=self.soft_fade.isChecked(),
            glow=self.glow.isChecked(),
            shimmer=self.shimmer.isChecked(),
            duration=self.duration.currentData(),
            trail=self.trail.currentData(),
            intensity=self.intensity.currentData(),
            erase_passed=self.erase_passed.isChecked(),
            kinetic_strength=self.kinetic_strength.currentData(),
            kinetic_parts=self.kinetic_parts.currentData(),
        ))

    def sync_options(self, value):
        options = normalize_options(value)
        widgets = (self, self.presets, self.entrance, self.color, self.duration, self.trail, self.intensity,
                   self.soft_fade, self.glow, self.shimmer, self.erase_passed,
                   self.kinetic_strength, self.kinetic_parts)
        blockers = [QSignalBlocker(widget) for widget in widgets]
        self.setChecked(options['enabled'])
        for combo, key in ((self.entrance, 'entrance'), (self.color, 'color'),
                           (self.trail, 'trail'), (self.intensity, 'intensity'),
                           (self.kinetic_strength, 'kinetic_strength'), (self.kinetic_parts, 'kinetic_parts')):
            combo.setCurrentIndex(combo.findData(options[key]))
        index = self.duration.findData(options['duration'])
        if index < 0:
            self.duration.addItem(f"Tùy chỉnh · {options['duration']} ms", options['duration'])
            index = self.duration.findData(options['duration'])
        self.duration.setCurrentIndex(index)
        for widget, key in ((self.soft_fade, 'soft_fade'), (self.glow, 'glow'),
                            (self.shimmer, 'shimmer'), (self.erase_passed, 'erase_passed')):
            widget.setChecked(options[key])
        del blockers
        self._sync_preset()
        self._sync_kinetic_controls()
        self.preview._subtitle_effects.configure(options)

    def _edited(self, *args):
        self._sync_preset()
        self._sync_kinetic_controls()
        self.preview._subtitle_effects.configure(self.options())
        self.changed.emit(self.options())

    def _sync_kinetic_controls(self):
        active = self.entrance.currentData() in KINETIC_MODES
        self.kinetic_strength.setEnabled(active)
        self.kinetic_parts.setEnabled(active)

    def _sync_preset(self):
        options = self.options()
        selected = 0
        for index, (name, title, settings) in enumerate(PRESETS):
            if (settings and all(options[key] == value for key, value in settings.items())
                    and options['erase_passed'] == settings.get('erase_passed', False)):
                selected = index
                break
        blocker = QSignalBlocker(self.presets)
        self.presets.setCurrentIndex(selected)

    def _preset_changed(self, index):
        if index == 0:
            return
        options = self.options()
        options['erase_passed'] = False
        options.update(soft_fade=True, shimmer=False, glow=False)
        options.update(PRESETS[index][2])
        self.sync_options(options)
        self.changed.emit(self.options())
        self.play_preview()

    def play_preview(self):
        effect = self.preview._subtitle_effects
        if effect.options.get('entrance') in CHOREO_EXIT_MODES:
            old_txt = self.preview.text()
            self._preview_idx = (self._preview_idx + 1) % len(self._preview_lines)
            next_txt = self._preview_lines[self._preview_idx]
            effect.replay_preview_with_exit(old_txt, next_txt)
        else:
            effect.clear()
            effect.sync((0, 0, 3000, self.preview.text()), 0)

    def hideEvent(self, event):
        self.preview._subtitle_effects.settle()
        super().hideEvent(event)
