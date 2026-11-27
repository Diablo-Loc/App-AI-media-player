"""Dedicated Watch History page ('Lịch sử') — Refined Dark Studio aesthetic:
- Clean editorial date dividers (uppercase micro-header + hairline rule)
- Borderless flat virtualized rows with subtle hover luminance (zero box-in-box clutter)
- Sleek Continue Listening dock with cover thumbnail & single-primary-CTA hierarchy
- Bounded retention controls (days + item cap), instant search, and O(1) widget pooling."""
from __future__ import annotations

import os
from bisect import bisect_right
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.user_collections import (
    HistoryItemView,
    UserCollectionsStore,
    format_duration_mmss,
)
from ui.collection_menus import (
    ConfirmActionDialog,
    StyledComboBox,
    show_add_to_playlist_menu,
    show_media_context_menu,
)
from ui.elided_label import ElidedLabel
from ui.i18n import tr_pair, translate_text
from ui.icons import ACCENT, HEART_COLOR, INK, button_icon, icon, label_icon
from ui.pages.for_you import LazyThumb

RETENTION_DAY_OPTIONS: Tuple[Tuple[str, int], ...] = (
    ("7 ngày gần nhất", 7),
    ("14 ngày gần nhất", 14),
    ("30 ngày gần nhất", 30),
    ("90 ngày gần nhất", 90),
    ("Không giới hạn ngày", 0),
)

RETENTION_ITEM_OPTIONS: Tuple[Tuple[str, int], ...] = (
    ("Tối đa 50 bài", 50),
    ("Tối đa 100 bài", 100),
    ("Tối đa 200 bài", 200),
    ("Tối đa 300 bài", 300),
    ("Tối đa 500 bài", 500),
)

_GHOST_ICON_BTN = """
QPushButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px;
}
QPushButton:hover {
    background: rgba(255, 255, 255, 0.08);
}
QPushButton:pressed {
    background: rgba(255, 255, 255, 0.13);
}
"""

_PRIMARY_PILL_BTN = """
QPushButton {
    background: #77E0BE;
    color: #0B1117;
    border: none;
    border-radius: 18px;
    padding: 0 18px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton:hover {
    background: #94EBD0;
}
QPushButton:pressed {
    background: #62CFA9;
}
QPushButton:disabled {
    background: #1D2835;
    color: #526173;
}
"""

_DANGER_GHOST_PILL_BTN = """
QPushButton {
    background: rgba(255, 255, 255, 0.045);
    color: #C7D4E2;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    padding: 0 15px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background: rgba(220, 76, 94, 0.16);
    color: #FF9BA7;
    border-color: rgba(220, 76, 94, 0.35);
}
QPushButton:disabled {
    color: #4E5E70;
    background: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.04);
}
"""


class _HistorySectionHeader(QFrame):
    """Editorial date divider: crisp label + subtle extending hairline + quiet count."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 4)
        layout.setSpacing(12)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            "color: #93A8BE; font-size: 11px; font-weight: 700; letter-spacing: 0.7px;"
        )

        self.rule = QFrame()
        self.rule.setFixedHeight(1)
        self.rule.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.rule.setStyleSheet("background: rgba(255, 255, 255, 0.06);")

        self.lbl_count = QLabel()
        self.lbl_count.setStyleSheet("color: #63758A; font-size: 11px; font-weight: 600;")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.rule, 1)
        layout.addWidget(self.lbl_count)

    def bind(self, section_label: str, item_count: int) -> None:
        self.lbl_title.setText(translate_text(section_label.upper()))
        self.lbl_count.setText(translate_text(f"{item_count} video"))


class _HistoryTrackRow(QFrame):
    """Flat, borderless studio row matching Collections & modern desktop players."""

    row_clicked = Signal(object)
    fav_clicked = Signal(object)
    add_playlist_clicked = Signal(object, QPoint)
    remove_clicked = Signal(str)
    context_requested = Signal(object, QPoint)

    STYLE_NORMAL = """
        QFrame#historyRow {
            background-color: transparent;
            border: none;
            border-bottom: 1px solid rgba(255, 255, 255, 0.045);
            border-radius: 0px;
        }
        QFrame#historyRow:hover {
            background-color: rgba(255, 255, 255, 0.045);
            border-bottom: 1px solid transparent;
            border-radius: 10px;
        }
    """
    STYLE_ACTIVE = """
        QFrame#historyRow {
            background-color: rgba(119, 224, 190, 0.10);
            border: none;
            border-radius: 10px;
        }
        QFrame#historyRow:hover {
            background-color: rgba(119, 224, 190, 0.14);
        }
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("historyRow")
        self.setFixedHeight(78)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.view_item: Optional[HistoryItemView] = None
        self._bound_thumb_key: Optional[str] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(14)

        self.thumb = LazyThumb(None, 114, 64, self)
        self.thumb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.thumb)

        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 2, 0, 2)
        info_col.setSpacing(2)
        info_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.lbl_title = ElidedLabel("", max_lines=1)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_title.setStyleSheet("color: #F0F5FB; font-size: 13.5px; font-weight: 600;")

        self.lbl_artist = ElidedLabel("", max_lines=1)
        self.lbl_artist.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_artist.setStyleSheet("color: #8A9BB0; font-size: 12px;")

        self.lbl_meta = QLabel()
        self.lbl_meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_meta.setStyleSheet("color: #63758A; font-size: 11px;")

        info_col.addWidget(self.lbl_title)
        info_col.addWidget(self.lbl_artist)
        info_col.addWidget(self.lbl_meta)
        layout.addLayout(info_col, 1)

        self.lbl_time_col = QLabel("00:00")
        self.lbl_time_col.setFixedWidth(48)
        self.lbl_time_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_time_col.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_time_col.setStyleSheet("color: #6B7D92; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.lbl_time_col)

        actions = QHBoxLayout()
        actions.setContentsMargins(6, 0, 0, 0)
        actions.setSpacing(2)

        self.btn_fav = QPushButton()
        self.btn_fav.setFixedSize(32, 32)
        self.btn_fav.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fav.setStyleSheet(_GHOST_ICON_BTN)
        self.btn_fav.clicked.connect(self._on_fav)

        self.btn_add = QPushButton()
        self.btn_add.setFixedSize(32, 32)
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.setStyleSheet(_GHOST_ICON_BTN)
        button_icon(self.btn_add, "plus", "Thêm vào Playlist", color="#7C8FA4", size=16)
        self.btn_add.clicked.connect(self._on_add)

        self.btn_remove = QPushButton()
        self.btn_remove.setFixedSize(32, 32)
        self.btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove.setStyleSheet(_GHOST_ICON_BTN)
        button_icon(self.btn_remove, "x", "Xóa khỏi lịch sử", color="#687A8F", size=15)
        self.btn_remove.clicked.connect(self._on_remove)

        actions.addWidget(self.btn_fav)
        actions.addWidget(self.btn_add)
        actions.addWidget(self.btn_remove)
        layout.addLayout(actions)

        self.setStyleSheet(self.STYLE_NORMAL)

    def bind(
        self,
        item_view: HistoryItemView,
        is_playing: bool,
        is_fav: bool,
    ) -> None:
        self.view_item = item_view
        media = item_view.media

        self.thumb.item_data = media
        self.thumb._build_cache_key()
        if self._bound_thumb_key != self.thumb.cache_key:
            if self.thumb._current_worker:
                self.thumb._current_worker.cancel()
                self.thumb._current_worker = None
            self.thumb._is_loaded = False
            self.thumb.clear()
            label_icon(self.thumb, "music", size=20)
            self.thumb.setStyleSheet("background-color: #131B26; border-radius: 7px; border: none;")
            self._bound_thumb_key = self.thumb.cache_key

        self.lbl_title.setText(media.title)
        self.lbl_artist.setText(media.artist or "Unknown Artist")
        self.lbl_time_col.setText(item_view.time_text)

        dur_str = format_duration_mmss(media.duration)
        parts: List[str] = []
        if media.duration and media.duration > 0:
            parts.append(dur_str)
        if item_view.watch_count > 1:
            parts.append(translate_text(f"Xem {item_view.watch_count} lần"))
        if media.path and not os.path.exists(media.path):
            parts.append(translate_text("Thiếu file gốc"))
        self.lbl_meta.setText("  ·  ".join(parts))
        self.lbl_meta.setVisible(bool(parts))

        if is_playing:
            self.setStyleSheet(self.STYLE_ACTIVE)
            self.lbl_title.setStyleSheet("color: #8CF0D0; font-size: 13.5px; font-weight: 700;")
        else:
            self.setStyleSheet(self.STYLE_NORMAL)
            self.lbl_title.setStyleSheet("color: #F0F5FB; font-size: 13.5px; font-weight: 600;")

        button_icon(
            self.btn_fav,
            "heart-filled" if is_fav else "heart",
            translate_text("Bỏ Yêu thích" if is_fav else "Yêu thích"),
            color=HEART_COLOR if is_fav else "#7C8FA4",
            size=16,
        )
        self.btn_add.setToolTip(translate_text("Thêm vào Playlist"))
        self.btn_remove.setToolTip(translate_text("Xóa khỏi lịch sử"))

    def _on_fav(self) -> None:
        if self.view_item is not None:
            self.fav_clicked.emit(self.view_item.media)

    def _on_add(self) -> None:
        if self.view_item is not None:
            pos = self.btn_add.mapToGlobal(QPoint(0, self.btn_add.height() + 4))
            self.add_playlist_clicked.emit(self.view_item.media, pos)

    def _on_remove(self) -> None:
        if self.view_item is not None:
            self.remove_clicked.emit(self.view_item.media.id)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.view_item is not None:
            if self.rect().contains(event.position().toPoint()):
                self.row_clicked.emit(self.view_item.media)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self.view_item is not None:
            self.context_requested.emit(self.view_item.media, event.globalPos())
            event.accept()


class _HistoryViewport(QObject):
    """Variable-height virtualized viewport supporting editorial date dividers + flat track rows."""

    HEADER_H = 36
    HEADER_GAP = 4
    ROW_H = 78
    ROW_GAP = 2
    TOP_PAD = 4
    SIDE_PAD = 2

    def __init__(self, page: "HistoryPage"):
        super().__init__(page)
        self.page = page
        self.entries: List[Tuple[str, Any]] = []
        self.offsets: List[int] = []
        self.heights: List[int] = []
        self.total_height: int = 0

        self.header_pool: List[_HistorySectionHeader] = []
        self.row_pool: List[_HistoryTrackRow] = []
        self.active_headers: Dict[int, _HistorySectionHeader] = {}
        self.active_rows: Dict[int, _HistoryTrackRow] = {}

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)

        page.scroll_area.viewport().installEventFilter(self)
        page.scroll_area.verticalScrollBar().valueChanged.connect(self.schedule)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.schedule()
        return False

    def schedule(self, *_args: Any) -> None:
        if not self.timer.isActive():
            self.timer.start(16)

    def set_grouped_data(self, grouped: List[Tuple[str, str, List[HistoryItemView]]]) -> None:
        entries: List[Tuple[str, Any]] = []
        offsets: List[int] = []
        heights: List[int] = []
        y = self.TOP_PAD

        for section_label, _date_key, items in grouped:
            if y > self.TOP_PAD:
                y += 10
            entries.append(("header", (section_label, len(items))))
            offsets.append(y)
            heights.append(self.HEADER_H)
            y += self.HEADER_H + self.HEADER_GAP

            for item_view in items:
                entries.append(("item", item_view))
                offsets.append(y)
                heights.append(self.ROW_H)
                y += self.ROW_H + self.ROW_GAP

        self.entries = entries
        self.offsets = offsets
        self.heights = heights
        self.total_height = max(0, y + 12)

        for hdr in self.active_headers.values():
            hdr.hide()
        for row in self.active_rows.values():
            row.hide()
            row.thumb.setProperty("playlist_visible", False)
            if row.thumb._current_worker:
                row.thumb._current_worker.cancel()
                row.thumb._current_worker = None
        self.active_headers.clear()
        self.active_rows.clear()

        self.page.list_canvas.setMinimumHeight(self.total_height)
        self.render()

    def render(self) -> None:
        if not self.entries:
            self.page.list_canvas.setMinimumHeight(0)
            return

        viewport = self.page.scroll_area.viewport()
        vp_h = max(1, viewport.height())
        vp_w = max(200, viewport.width() - self.SIDE_PAD * 2)
        scroll_y = self.page.scroll_area.verticalScrollBar().value()

        top_y = max(0, scroll_y - 180)
        bot_y = scroll_y + vp_h + 260

        first = max(0, bisect_right(self.offsets, top_y) - 1)
        last = min(len(self.entries), bisect_right(self.offsets, bot_y) + 1)
        wanted = set(range(first, last))

        free_headers = [w for idx, w in self.active_headers.items() if idx not in wanted]
        free_headers += [w for w in self.header_pool if w not in self.active_headers.values() and w not in free_headers]

        free_rows = [w for idx, w in self.active_rows.items() if idx not in wanted]
        free_rows += [w for w in self.row_pool if w not in self.active_rows.values() and w not in free_rows]

        next_headers: Dict[int, _HistorySectionHeader] = {}
        next_rows: Dict[int, _HistoryTrackRow] = {}

        store = self.page.store
        playing_id = self.page.current_playing_id

        self.page.list_canvas.setUpdatesEnabled(False)
        try:
            for idx in range(first, last):
                kind, payload = self.entries[idx]
                y = self.offsets[idx]
                h = self.heights[idx]
                if kind == "header":
                    hdr = self.active_headers.get(idx)
                    if hdr is None:
                        hdr = free_headers.pop() if free_headers else self._create_header()
                    section_label, count = payload
                    hdr.bind(section_label, count)
                    hdr.setGeometry(self.SIDE_PAD, y, vp_w, h)
                    hdr.show()
                    next_headers[idx] = hdr
                else:
                    row = self.active_rows.get(idx)
                    if row is None:
                        row = free_rows.pop() if free_rows else self._create_row()
                    item_view: HistoryItemView = payload
                    mid = item_view.media.id
                    is_fav = store.is_favorite(mid) if store is not None else False
                    row.bind(item_view, is_playing=(mid == playing_id), is_fav=is_fav)
                    row.setGeometry(self.SIDE_PAD, y, vp_w, h)
                    row.show()
                    visible = self.page.isVisible() and (y + h > scroll_y) and (y < scroll_y + vp_h)
                    row.thumb.setProperty("playlist_visible", visible)
                    if visible:
                        row.thumb._start_async_loading()
                    elif row.thumb._current_worker:
                        row.thumb._current_worker.cancel()
                        row.thumb._current_worker = None
                    next_rows[idx] = row

            for hdr in free_headers:
                hdr.hide()
            for row in free_rows:
                row.hide()
                row.thumb.setProperty("playlist_visible", False)
                if row.thumb._current_worker:
                    row.thumb._current_worker.cancel()
                    row.thumb._current_worker = None

            self.active_headers = next_headers
            self.active_rows = next_rows
        finally:
            self.page.list_canvas.setUpdatesEnabled(True)

    def _create_header(self) -> _HistorySectionHeader:
        hdr = _HistorySectionHeader(self.page.list_canvas)
        self.header_pool.append(hdr)
        return hdr

    def _create_row(self) -> _HistoryTrackRow:
        row = _HistoryTrackRow(self.page.list_canvas)
        row.row_clicked.connect(self.page._on_row_clicked)
        row.fav_clicked.connect(self.page._on_fav_clicked)
        row.add_playlist_clicked.connect(self.page._on_add_playlist_clicked)
        row.remove_clicked.connect(self.page._on_remove_item)
        row.context_requested.connect(self.page._on_context_menu)
        self.row_pool.append(row)
        return row

    def cancel_workers(self) -> None:
        self.timer.stop()
        for row in self.row_pool:
            row.thumb.setProperty("playlist_visible", False)
            if row.thumb._current_worker:
                row.thumb._current_worker.cancel()
                row.thumb._current_worker = None


class HistoryPage(QWidget):
    """Tab Lịch sử xem: nhóm theo ngày xem, giới hạn kép tối ưu, thiết kế phẳng tinh tế."""

    play_requested = Signal(object, list)
    resume_requested = Signal(object, int)

    def __init__(
        self,
        store: Optional[UserCollectionsStore] = None,
        media_library: Any = None,
        notify_callback: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.store = store
        self.media_library = media_library
        self._notify = notify_callback
        self.current_playing_id: Optional[str] = None
        self._current_flat_items: List[Any] = []
        self._resume_thumb_key: Optional[str] = None
        self._needs_refresh: bool = False

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh_view)

        self._init_ui()
        self._viewport = _HistoryViewport(self)

        if self.store is not None:
            self.bind_store(self.store, self.media_library)

    def _init_ui(self) -> None:
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 4, 2)
        root.setSpacing(12)

        # --- 1. EDITORIAL HEADER ---
        top_row = QHBoxLayout()
        top_row.setContentsMargins(4, 0, 4, 0)
        top_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)

        self.lbl_heading = QLabel("Lịch sử xem")
        self.lbl_heading.setStyleSheet("font-size: 25px; font-weight: 700; color: #F4F8FC;")

        meta_line = QHBoxLayout()
        meta_line.setContentsMargins(0, 0, 0, 0)
        meta_line.setSpacing(8)
        self.lbl_total_badge = QLabel("0 video")
        self.lbl_total_badge.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #77E0BE;")
        self.lbl_subtitle = QLabel("·  Tự động gom theo ngày và dọn gọn lịch sử cũ")
        self.lbl_subtitle.setStyleSheet("font-size: 12.5px; color: #7A8DA2;")
        meta_line.addWidget(self.lbl_total_badge)
        meta_line.addWidget(self.lbl_subtitle)
        meta_line.addStretch()

        title_col.addWidget(self.lbl_heading)
        title_col.addLayout(meta_line)
        top_row.addLayout(title_col, 1)

        self.btn_play_all = QPushButton("Phát tất cả")
        self.btn_play_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_all.setFixedHeight(36)
        self.btn_play_all.setStyleSheet(_PRIMARY_PILL_BTN)
        button_icon(self.btn_play_all, "play", "Phát toàn bộ lịch sử", color=INK, size=15, icon_only=False)
        self.btn_play_all.clicked.connect(self._on_play_all)

        self.btn_clear_all = QPushButton("Xóa lịch sử")
        self.btn_clear_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_all.setFixedHeight(36)
        self.btn_clear_all.setStyleSheet(_DANGER_GHOST_PILL_BTN)
        button_icon(self.btn_clear_all, "trash", "Xóa toàn bộ lịch sử", color="#A9B8C9", size=14, icon_only=False)
        self.btn_clear_all.clicked.connect(self._on_clear_all)

        top_row.addWidget(self.btn_play_all)
        top_row.addWidget(self.btn_clear_all)
        root.addLayout(top_row)

        # --- 2. REFINED CONTINUE LISTENING DOCK (quiet secondary CTA so primary hierarchy stays clean) ---
        self.resume_banner = QFrame()
        self.resume_banner.setObjectName("resumeBanner")
        self.resume_banner.setStyleSheet(
            "QFrame#resumeBanner { background: rgba(255, 255, 255, 0.035); "
            "border: 1px solid rgba(255, 255, 255, 0.065); border-radius: 12px; }"
        )
        resume_layout = QHBoxLayout(self.resume_banner)
        resume_layout.setContentsMargins(12, 8, 12, 8)
        resume_layout.setSpacing(12)

        self.resume_thumb = LazyThumb(None, 64, 36, self.resume_banner)
        resume_layout.addWidget(self.resume_thumb)

        resume_info = QVBoxLayout()
        resume_info.setContentsMargins(0, 0, 0, 0)
        resume_info.setSpacing(1)
        lbl_resume_kicker = QLabel("TIẾP TỤC PHIÊN NGHE GẦN NHẤT")
        lbl_resume_kicker.setStyleSheet(
            "color: #77E0BE; font-size: 9.5px; font-weight: 700; letter-spacing: 0.8px;"
        )
        self.lbl_resume_text = ElidedLabel("", max_lines=1)
        self.lbl_resume_text.setStyleSheet("color: #E4EDF7; font-size: 13px; font-weight: 600;")
        resume_info.addWidget(lbl_resume_kicker)
        resume_info.addWidget(self.lbl_resume_text)
        resume_layout.addLayout(resume_info, 1)

        self.btn_resume = QPushButton("Nghe tiếp")
        self.btn_resume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_resume.setFixedHeight(32)
        self.btn_resume.setStyleSheet(
            "QPushButton { background: rgba(119, 224, 190, 0.14); color: #9CF2D5; "
            "border: 1px solid rgba(119, 224, 190, 0.35); border-radius: 16px; "
            "padding: 0 14px; font-weight: 600; font-size: 12px; }"
            "QPushButton:hover { background: rgba(119, 224, 190, 0.24); color: #D4FFF0; }"
        )
        button_icon(self.btn_resume, "play", "Tiếp tục phát tại vị trí dừng", color=ACCENT, size=13, icon_only=False)
        self.btn_resume.clicked.connect(self._on_resume_clicked)
        resume_layout.addWidget(self.btn_resume)

        self.resume_banner.hide()
        root.addWidget(self.resume_banner)

        # --- 3. FILTER & RETENTION CONTROLS BAR ---
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setContentsMargins(2, 2, 2, 0)
        ctrl_bar.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm bài hát, ca sĩ hoặc ngày xem (VD: Hôm nay, 27/11)...")
        self.search_input.addAction(icon("search", "#788B9F"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setFixedHeight(36)
        self.search_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_input.setStyleSheet(
            "QLineEdit { background: rgba(255, 255, 255, 0.045); color: #EDF3FA; "
            "border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 18px; padding: 0 14px; font-size: 12.5px; }"
            "QLineEdit:focus { background: #141C27; border-color: #77E0BE; }"
        )
        self.search_input.textChanged.connect(lambda _t: self._search_timer.start())

        lbl_ret = QLabel("Lưu giữ:")
        lbl_ret.setStyleSheet("color: #6B7E94; font-size: 12px; font-weight: 600; padding-left: 4px;")

        combo_style = (
            "QComboBox { background: rgba(255, 255, 255, 0.045); color: #DCE7F3; "
            "border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 18px; "
            "padding: 0 28px 0 13px; font-size: 12px; font-weight: 600; }"
            "QComboBox:hover { background: rgba(255, 255, 255, 0.085); border-color: rgba(255, 255, 255, 0.16); }"
            "QComboBox:focus { border-color: #77E0BE; }"
            "QComboBox::drop-down { width: 24px; border: none; background: transparent; }"
            "QComboBox::down-arrow { image: none; width: 0px; height: 0px; }"
            "QComboBox QAbstractItemView { background: #161F2B; color: #EDF3FA; "
            "selection-background-color: #19372F; selection-color: #A9F1D9; "
            "border: 1px solid #2A394C; border-radius: 8px; padding: 4px; }"
        )

        self.combo_max_days = StyledComboBox()
        self.combo_max_days.setFixedHeight(36)
        self.combo_max_days.setMinimumWidth(124)
        self.combo_max_days.setStyleSheet(combo_style)
        for text, days in RETENTION_DAY_OPTIONS:
            self.combo_max_days.addItem(text, days)
        self.combo_max_days.currentIndexChanged.connect(self._on_retention_changed)

        self.combo_max_items = StyledComboBox()
        self.combo_max_items.setFixedHeight(36)
        self.combo_max_items.setMinimumWidth(114)
        self.combo_max_items.setStyleSheet(combo_style)
        for text, count in RETENTION_ITEM_OPTIONS:
            self.combo_max_items.addItem(text, count)
        self.combo_max_items.currentIndexChanged.connect(self._on_retention_changed)

        ctrl_bar.addWidget(self.search_input, 1)
        ctrl_bar.addWidget(lbl_ret)
        ctrl_bar.addWidget(self.combo_max_days)
        ctrl_bar.addWidget(self.combo_max_items)
        root.addLayout(ctrl_bar)

        # --- 4. BODY: MINIMAL EMPTY STATE OR BORDERLESS VIRTUALIZED LIST ---
        self.empty_card = QFrame()
        self.empty_card.setStyleSheet("QFrame { background: transparent; border: none; }")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(32, 60, 32, 60)
        empty_layout.setSpacing(10)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_empty_icon = QLabel()
        label_icon(self.lbl_empty_icon, "history", size=38, color="#6B7D92")
        self.lbl_empty_title = QLabel("Chưa có lịch sử xem")
        self.lbl_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_title.setStyleSheet("color: #DCE7F3; font-size: 16px; font-weight: 600;")
        self.lbl_empty_desc = QLabel(
            "Mỗi khi bạn phát một video hoặc bài hát, thời điểm xem sẽ tự động lưu tại đây theo từng ngày."
        )
        self.lbl_empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_desc.setWordWrap(True)
        self.lbl_empty_desc.setMaximumWidth(420)
        self.lbl_empty_desc.setStyleSheet("color: #74879C; font-size: 13px;")

        empty_layout.addWidget(self.lbl_empty_icon, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.lbl_empty_title)
        empty_layout.addWidget(self.lbl_empty_desc, alignment=Qt.AlignmentFlag.AlignCenter)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")

        self.list_canvas = QWidget()
        self.list_canvas.setStyleSheet("background: transparent;")
        self.scroll_area.setWidget(self.list_canvas)

        root.addWidget(self.empty_card, 1)
        root.addWidget(self.scroll_area, 1)
        self.scroll_area.hide()

    def bind_store(self, store: UserCollectionsStore, media_library: Any = None) -> None:
        self.store = store
        if media_library is not None:
            self.media_library = media_library
        store.history_changed.connect(self._on_store_changed)
        store.favorites_changed.connect(self._on_fav_store_changed)
        store.last_played_changed.connect(self._on_last_played_store_changed)
        self._sync_retention_combos()
        self.refresh_view()

    def _on_store_changed(self) -> None:
        if not self.isVisible():
            self._needs_refresh = True
            return
        self.refresh_view()

    def _on_fav_store_changed(self) -> None:
        if not self.isVisible():
            self._needs_refresh = True
            return
        self._viewport.render()

    def _on_last_played_store_changed(self) -> None:
        if not self.isVisible():
            self._needs_refresh = True
            return
        self._refresh_resume_banner()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._needs_refresh:
            self.refresh_view()
        else:
            self._viewport.schedule()
            if self.resume_banner.isVisible() and self.resume_thumb.item_data is not None:
                self.resume_thumb.setProperty("playlist_visible", True)
                self.resume_thumb._start_async_loading()

    def hideEvent(self, event) -> None:
        self._viewport.cancel_workers()
        if self.resume_thumb._current_worker:
            self.resume_thumb._current_worker.cancel()
            self.resume_thumb._current_worker = None
        super().hideEvent(event)

    def refresh_thumbnail(self, media_id: str, thumb_path: str) -> None:
        if not media_id or not thumb_path:
            return
        matched = False
        for kind, payload in self._viewport.entries:
            if kind == "item" and getattr(payload.media, "id", None) == media_id:
                if getattr(payload.media, "thumbnail", None) != thumb_path:
                    payload.media.thumbnail = thumb_path
                    matched = True
        if self.resume_thumb.item_data is not None and getattr(self.resume_thumb.item_data, "id", None) == media_id:
            if getattr(self.resume_thumb.item_data, "thumbnail", None) != thumb_path:
                self.resume_thumb.item_data.thumbnail = thumb_path
                self._resume_thumb_key = None
                matched = True
        if self.isVisible():
            if matched or any(kind == "item" and getattr(p.media, "id", None) == media_id for kind, p in self._viewport.entries):
                self._viewport.schedule()
                if self.resume_banner.isVisible() and self.resume_thumb.item_data is not None and getattr(self.resume_thumb.item_data, "id", None) == media_id:
                    self._refresh_resume_banner()
        elif matched:
            self._needs_refresh = True

    def _sync_retention_combos(self) -> None:
        if self.store is None:
            return
        self.combo_max_days.blockSignals(True)
        self.combo_max_items.blockSignals(True)
        idx_days = self.combo_max_days.findData(self.store.history_max_days)
        if idx_days >= 0:
            self.combo_max_days.setCurrentIndex(idx_days)
        idx_items = self.combo_max_items.findData(self.store.history_max_items)
        if idx_items >= 0:
            self.combo_max_items.setCurrentIndex(idx_items)
        self.combo_max_days.blockSignals(False)
        self.combo_max_items.blockSignals(False)

    def _on_retention_changed(self, *_args: Any) -> None:
        if self.store is None:
            return
        days = int(self.combo_max_days.currentData() or 0)
        items_cap = int(self.combo_max_items.currentData() or 300)
        self.store.set_history_limits(max_days=days, max_items=items_cap)

    def _refresh_resume_banner(self) -> None:
        if self.store is None:
            self.resume_banner.hide()
            return
        lp = self.store.get_last_played(self.media_library)
        if not lp:
            self.resume_banner.hide()
            return
        media, pos_ms, _updated_at = lp
        if not media.path or not os.path.exists(media.path):
            self.resume_banner.hide()
            return
        pos_text = format_duration_mmss(pos_ms / 1000.0)
        pause_lbl = translate_text(f"Dừng tại {pos_text}")
        self.lbl_resume_text.setText(f"{media.title}  ·  {media.artist}  ·  {pause_lbl}")
        self.resume_thumb.item_data = media
        self.resume_thumb._build_cache_key()
        if self._resume_thumb_key != self.resume_thumb.cache_key:
            self.resume_thumb._is_loaded = False
            self.resume_thumb.clear()
            label_icon(self.resume_thumb, "music", size=16)
            self.resume_thumb.setStyleSheet("background-color: #131B26; border-radius: 6px; border: none;")
            self._resume_thumb_key = self.resume_thumb.cache_key
        self.resume_banner.show()
        if self.isVisible():
            self.resume_thumb.setProperty("playlist_visible", True)
            self.resume_thumb._start_async_loading()
        else:
            self.resume_thumb.setProperty("playlist_visible", False)

    def set_playing_media_id(self, media_id: Optional[str]) -> None:
        self.current_playing_id = media_id
        if self.isVisible():
            self._viewport.render()
        else:
            self._needs_refresh = True

    def refresh_view(self) -> None:
        self._needs_refresh = False
        self._refresh_resume_banner()
        if self.store is None:
            self.empty_card.show()
            self.scroll_area.hide()
            return

        total_count = self.store.history_count()
        self.lbl_total_badge.setText(translate_text(f"{total_count} video"))
        self.btn_clear_all.setEnabled(total_count > 0)

        query = self.search_input.text().strip()
        grouped = self.store.get_history_grouped(query=query, media_library=self.media_library)
        flat = [iv.media for _lbl, _dk, items in grouped for iv in items]
        self._current_flat_items = flat
        self.btn_play_all.setEnabled(len(flat) > 0)

        if not grouped:
            if query and total_count > 0:
                self.lbl_empty_title.setText(translate_text("Không tìm thấy kết quả phù hợp"))
                self.lbl_empty_desc.setText(
                    tr_pair(
                        f"Không có video nào trong lịch sử khớp với từ khóa “{query}”.",
                        f"No items in your playback history match “{query}”.",
                    )
                )
            else:
                self.lbl_empty_title.setText(translate_text("Chưa có lịch sử xem"))
                self.lbl_empty_desc.setText(
                    translate_text(
                        "Mỗi khi bạn phát một video hoặc bài hát, thời điểm xem sẽ tự động lưu tại đây theo từng ngày."
                    )
                )
            self._viewport.set_grouped_data([])
            self.scroll_area.hide()
            self.empty_card.show()
            return

        self.empty_card.hide()
        self.scroll_area.show()
        self._viewport.set_grouped_data(grouped)

    def get_playback_playlist(self) -> List[Any]:
        return list(self._current_flat_items)

    def _on_row_clicked(self, media_item: Any) -> None:
        queue = list(self._current_flat_items) if self._current_flat_items else [media_item]
        self.play_requested.emit(media_item, queue)

    def _on_play_all(self) -> None:
        if self._current_flat_items:
            self.play_requested.emit(self._current_flat_items[0], list(self._current_flat_items))

    def _on_resume_clicked(self) -> None:
        if self.store is None:
            return
        lp = self.store.get_last_played(self.media_library)
        if lp:
            media, pos_ms, _ts = lp
            self.resume_requested.emit(media, pos_ms)

    def _on_fav_clicked(self, media_item: Any) -> None:
        if self.store is None:
            return
        now_fav = self.store.toggle_favorite(media_item)
        if self._notify:
            self._notify(
                f"❤️ Đã thêm “{media_item.title}” vào Yêu thích"
                if now_fav
                else f"💔 Đã bỏ “{media_item.title}” khỏi Yêu thích"
            )

    def _on_add_playlist_clicked(self, media_item: Any, global_pos: QPoint) -> None:
        if self.store is None:
            return
        show_add_to_playlist_menu(self, global_pos, media_item, self.store, on_notify=self._notify)

    def _on_remove_item(self, media_id: str) -> None:
        if self.store is None:
            return
        if self.store.remove_history_item(media_id) and self._notify:
            self._notify("🕒 Đã xóa mục khỏi lịch sử xem")

    def _on_clear_all(self) -> None:
        if self.store is None or self.store.history_count() == 0:
            return
        dlg = ConfirmActionDialog(
            title="Xóa toàn bộ lịch sử xem",
            message="Bạn có chắc chắn muốn xóa toàn bộ lịch sử xem? Yêu thích, Playlist và Top nghe nhiều nhất vẫn được giữ nguyên.",
            confirm_label="Xóa lịch sử",
            danger=True,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.store.clear_history()
            if self._notify:
                self._notify("🧹 Đã xóa sạch toàn bộ lịch sử xem")

    def _on_context_menu(self, media_item: Any, global_pos: QPoint) -> None:
        show_media_context_menu(
            self,
            global_pos,
            media_item,
            self.store,
            on_play=lambda item: self._on_row_clicked(item),
            on_notify=self._notify,
        )
