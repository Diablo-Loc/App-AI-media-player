"""Personal Collections page ('Bộ sưu tập') — Refined Dark Studio aesthetic:
- Recessed navigation rail with quiet section headers (no box-in-box border clutter)
- Atmospheric tinted hero header with stacked editorial KPIs & single primary pill CTA
- Borderless flat virtualized track rows with subtle hairline dividers & clean rank typography
- Multi-Folder Media Sources manager & O(1) viewport-virtualized scrolling."""
from __future__ import annotations

import os
import random
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.user_collections import (
    TopTrackView,
    UserCollectionsStore,
    format_duration_mmss,
    format_listen_duration_vi,
)
from ui.collection_menus import (
    AddSongsPickerDialog,
    ConfirmActionDialog,
    StyledComboBox,
    TextPromptDialog,
    show_add_to_playlist_menu,
    show_media_context_menu,
)
from ui.elided_label import ElidedLabel
from ui.icons import ACCENT, HEART_COLOR, INK, MUTED, TEXT, button_icon, icon, label_icon
from ui.pages.for_you import LazyThumb

FAVORITES_COLLECTION_ID = "__favorites__"
MOST_PLAYED_COLLECTION_ID = "__most_played__"
FLAME_COLOR = "#F5B85B"

TOP_PERIOD_OPTIONS: Tuple[Tuple[str, str], ...] = (
    ("Tất cả thời gian", "all"),
    ("30 ngày qua", "30d"),
    ("7 ngày qua", "7d"),
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

_SECONDARY_PILL_BTN = """
QPushButton {
    background: rgba(255, 255, 255, 0.05);
    color: #DCE7F3;
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 18px;
    padding: 0 15px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton:hover {
    background: rgba(255, 255, 255, 0.10);
    border-color: rgba(255, 255, 255, 0.16);
}
QPushButton:pressed {
    background: rgba(255, 255, 255, 0.14);
}
QPushButton:disabled {
    color: #4E5E70;
    background: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.04);
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

_CIRCLE_GHOST_BTN = """
QPushButton {
    background: rgba(255, 255, 255, 0.045);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    padding: 0px;
}
QPushButton:hover {
    background: rgba(255, 255, 255, 0.10);
    border-color: rgba(255, 255, 255, 0.16);
}
QPushButton:disabled {
    background: rgba(255, 255, 255, 0.02);
    border-color: rgba(255, 255, 255, 0.04);
}
"""


class _CollectionTrackRow(QFrame):
    """Flat, borderless studio track row with subtle hover surface and clean typographic hierarchy."""

    row_clicked = Signal(object)
    fav_clicked = Signal(object)
    add_playlist_clicked = Signal(object, QPoint)
    remove_clicked = Signal(object)
    context_requested = Signal(object, QPoint)

    STYLE_NORMAL = """
        QFrame#collectionRow {
            background-color: transparent;
            border: none;
            border-bottom: 1px solid rgba(255, 255, 255, 0.045);
            border-radius: 0px;
        }
        QFrame#collectionRow:hover {
            background-color: rgba(255, 255, 255, 0.045);
            border-bottom: 1px solid transparent;
            border-radius: 10px;
        }
    """
    STYLE_ACTIVE = """
        QFrame#collectionRow {
            background-color: rgba(119, 224, 190, 0.10);
            border: none;
            border-radius: 10px;
        }
        QFrame#collectionRow:hover {
            background-color: rgba(119, 224, 190, 0.14);
        }
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("collectionRow")
        self.setFixedHeight(78)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.media_item: Optional[Any] = None
        self._bound_thumb_key: Optional[str] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(14)

        self.lbl_index = QLabel("1")
        self.lbl_index.setFixedSize(32, 26)
        self.lbl_index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_index.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_index.setStyleSheet("color: #6B7D92; font-size: 13px; font-weight: 600;")
        layout.addWidget(self.lbl_index)

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

        self.lbl_top_meta = QLabel()
        self.lbl_top_meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_top_meta.setStyleSheet("color: #63758A; font-size: 11px;")
        self.lbl_top_meta.hide()

        info_col.addWidget(self.lbl_title)
        info_col.addWidget(self.lbl_artist)
        info_col.addWidget(self.lbl_top_meta)
        layout.addLayout(info_col, 1)

        # Minimal popularity column (visible only in 'Nghe nhiều nhất')
        self.top_stats_box = QWidget()
        self.top_stats_box.setFixedWidth(96)
        self.top_stats_box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        top_box_layout = QVBoxLayout(self.top_stats_box)
        top_box_layout.setContentsMargins(0, 0, 4, 0)
        top_box_layout.setSpacing(5)
        top_box_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        self.lbl_play_badge = QLabel("0 lượt")
        self.lbl_play_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_play_badge.setStyleSheet("color: #DCE7F3; font-size: 12px; font-weight: 600;")

        self.heat_track = QFrame()
        self.heat_track.setFixedSize(82, 3)
        self.heat_track.setStyleSheet("background: rgba(255, 255, 255, 0.08); border-radius: 1px; border: none;")
        self.heat_fill = QFrame(self.heat_track)
        self.heat_fill.setGeometry(0, 0, 40, 3)
        self.heat_fill.setStyleSheet("background: #77E0BE; border-radius: 1px; border: none;")

        top_box_layout.addWidget(self.lbl_play_badge)
        top_box_layout.addWidget(self.heat_track, alignment=Qt.AlignmentFlag.AlignRight)
        self.top_stats_box.hide()
        layout.addWidget(self.top_stats_box)

        self.lbl_duration = QLabel("00:00")
        self.lbl_duration.setFixedWidth(50)
        self.lbl_duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_duration.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_duration.setStyleSheet("color: #6B7D92; font-size: 12px;")
        layout.addWidget(self.lbl_duration)

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
        button_icon(self.btn_add, "plus", "Thêm vào Playlist khác", color="#7C8FA4", size=16)
        self.btn_add.clicked.connect(self._on_add)

        self.btn_remove = QPushButton()
        self.btn_remove.setFixedSize(32, 32)
        self.btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove.setStyleSheet(_GHOST_ICON_BTN)
        button_icon(self.btn_remove, "x", "Gỡ khỏi danh sách", color="#687A8F", size=15)
        self.btn_remove.clicked.connect(self._on_remove)

        actions.addWidget(self.btn_fav)
        actions.addWidget(self.btn_add)
        actions.addWidget(self.btn_remove)
        layout.addLayout(actions)

        self.setStyleSheet(self.STYLE_NORMAL)

    def bind(
        self,
        index_num: int,
        media: Any,
        is_playing: bool,
        is_fav: bool,
        in_favorites_view: bool,
        top_view: Optional[TopTrackView] = None,
    ) -> None:
        self.media_item = media

        if top_view is not None:
            rank = top_view.rank
            self.lbl_index.setText(f"#{rank}")
            if rank == 1:
                self.lbl_index.setStyleSheet(
                    "color: #F5C451; background: rgba(245, 196, 81, 0.12); "
                    "border: none; border-radius: 6px; font-size: 13px; font-weight: 800;"
                )
            elif rank == 2:
                self.lbl_index.setStyleSheet(
                    "color: #D2DCE8; background: rgba(210, 220, 232, 0.10); "
                    "border: none; border-radius: 6px; font-size: 12.5px; font-weight: 700;"
                )
            elif rank == 3:
                self.lbl_index.setStyleSheet(
                    "color: #E29B72; background: rgba(226, 155, 114, 0.11); "
                    "border: none; border-radius: 6px; font-size: 12.5px; font-weight: 700;"
                )
            else:
                self.lbl_index.setStyleSheet(
                    "color: #6B7D92; background: transparent; border: none; font-size: 12.5px; font-weight: 600;"
                )
        else:
            self.lbl_index.setText(str(index_num))
            self.lbl_index.setStyleSheet(
                f"color: {'#77E0BE' if is_playing else '#6B7D92'}; background: transparent; "
                "border: none; font-size: 12.5px; font-weight: 600;"
            )

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

        self.lbl_title.setText(getattr(media, "title", "Unknown"))
        artist = getattr(media, "artist", "Unknown Artist") or "Unknown Artist"
        if getattr(media, "path", "") and not os.path.exists(media.path):
            artist = f"{artist}  ·  Thiếu file gốc"
        self.lbl_artist.setText(artist)
        dur = float(getattr(media, "duration", 0.0) or 0.0)
        self.lbl_duration.setText(format_duration_mmss(dur) if dur > 0 else "--:--")

        if top_view is not None:
            meta_parts: List[str] = []
            if top_view.total_listen_sec >= 5.0:
                meta_parts.append(f"Đã nghe {format_listen_duration_vi(top_view.total_listen_sec)}")
            if top_view.last_played_at > 0:
                dt = datetime.fromtimestamp(top_view.last_played_at)
                today = datetime.now().date()
                if dt.date() == today:
                    meta_parts.append(f"Hôm nay {dt.strftime('%H:%M')}")
                else:
                    meta_parts.append(dt.strftime("%d/%m/%Y"))
            self.lbl_top_meta.setText("  ·  ".join(meta_parts))
            self.lbl_top_meta.setVisible(bool(meta_parts))

            self.lbl_play_badge.setText(f"{top_view.play_count} lượt")
            bar_color = "#F5C451" if top_view.rank == 1 else "#77E0BE" if top_view.rank <= 3 else "#4A8F7C"
            txt_color = "#F5C451" if top_view.rank == 1 else "#DCE7F3"
            self.lbl_play_badge.setStyleSheet(f"color: {txt_color}; font-size: 12px; font-weight: 600;")
            fill_w = max(6, min(82, int(round(82 * top_view.share_ratio))))
            self.heat_fill.setGeometry(0, 0, fill_w, 3)
            self.heat_fill.setStyleSheet(f"background: {bar_color}; border-radius: 1px; border: none;")
            self.top_stats_box.show()
        else:
            self.lbl_top_meta.hide()
            self.top_stats_box.hide()

        if is_playing:
            self.setStyleSheet(self.STYLE_ACTIVE)
            self.lbl_title.setStyleSheet("color: #8CF0D0; font-size: 13.5px; font-weight: 700;")
        else:
            self.setStyleSheet(self.STYLE_NORMAL)
            self.lbl_title.setStyleSheet("color: #F0F5FB; font-size: 13.5px; font-weight: 600;")

        button_icon(
            self.btn_fav,
            "heart-filled" if is_fav else "heart",
            "Bỏ Yêu thích" if is_fav else "Yêu thích",
            color=HEART_COLOR if is_fav else "#7C8FA4",
            size=16,
        )
        self.btn_remove.setVisible(not in_favorites_view)
        self.btn_remove.setToolTip(
            "Gỡ khỏi Bảng xếp hạng" if top_view is not None else "Gỡ khỏi danh sách"
        )

    def _on_fav(self) -> None:
        if self.media_item is not None:
            self.fav_clicked.emit(self.media_item)

    def _on_add(self) -> None:
        if self.media_item is not None:
            pos = self.btn_add.mapToGlobal(QPoint(0, self.btn_add.height() + 4))
            self.add_playlist_clicked.emit(self.media_item, pos)

    def _on_remove(self) -> None:
        if self.media_item is not None:
            self.remove_clicked.emit(self.media_item)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.media_item is not None:
            if self.rect().contains(event.position().toPoint()):
                self.row_clicked.emit(self.media_item)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self.media_item is not None:
            self.context_requested.emit(self.media_item, event.globalPos())
            event.accept()


class _CollectionTrackViewport(QObject):
    ROW_H = 78
    PITCH = 80
    TOP_PAD = 4
    SIDE_PAD = 2

    def __init__(self, page: "PlaylistsPage"):
        super().__init__(page)
        self.page = page
        self.items: List[Any] = []
        self.top_map: Dict[str, TopTrackView] = {}
        self.pool: List[_CollectionTrackRow] = []
        self.active: Dict[int, _CollectionTrackRow] = {}

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)

        page.track_scroll.viewport().installEventFilter(self)
        page.track_scroll.verticalScrollBar().valueChanged.connect(self.schedule)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.schedule()
        return False

    def schedule(self, *_args: Any) -> None:
        if not self.timer.isActive():
            self.timer.start(16)

    def set_items(self, items: List[Any], top_views: Optional[List[TopTrackView]] = None) -> None:
        self.items = list(items)
        self.top_map = {tv.media.id: tv for tv in (top_views or [])}
        for row in self.active.values():
            row.hide()
            row.thumb.setProperty("playlist_visible", False)
            if row.thumb._current_worker:
                row.thumb._current_worker.cancel()
                row.thumb._current_worker = None
        self.active.clear()
        total_h = max(0, len(self.items) * self.PITCH + self.TOP_PAD * 2) if self.items else 0
        self.page.track_canvas.setMinimumHeight(total_h)
        self.render()

    def render(self) -> None:
        count = len(self.items)
        if count == 0:
            self.page.track_canvas.setMinimumHeight(0)
            return

        viewport = self.page.track_scroll.viewport()
        vp_h = max(1, viewport.height())
        vp_w = max(200, viewport.width() - self.SIDE_PAD * 2)
        scroll_y = self.page.track_scroll.verticalScrollBar().value()

        first = max(0, (scroll_y - self.TOP_PAD) // self.PITCH - 1)
        last = min(count, first + ceil(vp_h / self.PITCH) + 4)
        wanted = set(range(first, last))

        free = [w for idx, w in self.active.items() if idx not in wanted]
        free += [w for w in self.pool if w not in self.active.values() and w not in free]
        retained: Dict[int, _CollectionTrackRow] = {}

        store = self.page.store
        playing_id = self.page.current_playing_id
        in_fav_view = self.page.selected_collection_id == FAVORITES_COLLECTION_ID

        self.page.track_canvas.setUpdatesEnabled(False)
        try:
            for idx in range(first, last):
                media = self.items[idx]
                row = self.active.get(idx)
                if row is None:
                    row = free.pop() if free else self._create_row()
                mid = getattr(media, "id", "")
                is_fav = store.is_favorite(mid) if store is not None else False
                row.bind(
                    index_num=idx + 1,
                    media=media,
                    is_playing=(mid == playing_id),
                    is_fav=is_fav,
                    in_favorites_view=in_fav_view,
                    top_view=self.top_map.get(mid),
                )
                y = self.TOP_PAD + idx * self.PITCH
                row.setGeometry(self.SIDE_PAD, y, vp_w, self.ROW_H)
                row.show()
                visible = self.page.isVisible() and (y + self.ROW_H > scroll_y) and (y < scroll_y + vp_h)
                row.thumb.setProperty("playlist_visible", visible)
                if visible:
                    row.thumb._start_async_loading()
                elif row.thumb._current_worker:
                    row.thumb._current_worker.cancel()
                    row.thumb._current_worker = None
                retained[idx] = row

            for row in free:
                row.hide()
                row.thumb.setProperty("playlist_visible", False)
                if row.thumb._current_worker:
                    row.thumb._current_worker.cancel()
                    row.thumb._current_worker = None
            self.active = retained
        finally:
            self.page.track_canvas.setUpdatesEnabled(True)

    def _create_row(self) -> _CollectionTrackRow:
        row = _CollectionTrackRow(self.page.track_canvas)
        row.row_clicked.connect(self.page._on_row_clicked)
        row.fav_clicked.connect(self.page._on_fav_clicked)
        row.add_playlist_clicked.connect(self.page._on_add_playlist_clicked)
        row.remove_clicked.connect(self.page._on_remove_from_playlist)
        row.context_requested.connect(self.page._on_context_menu)
        self.pool.append(row)
        return row

    def cancel_workers(self) -> None:
        self.timer.stop()
        for row in self.pool:
            row.thumb.setProperty("playlist_visible", False)
            if row.thumb._current_worker:
                row.thumb._current_worker.cancel()
                row.thumb._current_worker = None


class PlaylistsPage(QWidget):
    """Tab Bộ sưu tập: Yêu thích ❤️ + Top Nghe nhiều nhất 🔥 + Playlist cá nhân + Đa thư mục."""

    play_requested = Signal(object, list)
    folders_scan_requested = Signal(list)

    _HERO_TINTS = {
        FAVORITES_COLLECTION_ID: (
            "QFrame#collectionHero { "
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 rgba(255, 107, 139, 0.11), stop:1 rgba(13, 17, 24, 0.0)); "
            "border: none; border-bottom: 1px solid rgba(255, 255, 255, 0.07); border-radius: 14px; }"
        ),
        MOST_PLAYED_COLLECTION_ID: (
            "QFrame#collectionHero { "
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 rgba(245, 184, 91, 0.11), stop:1 rgba(13, 17, 24, 0.0)); "
            "border: none; border-bottom: 1px solid rgba(255, 255, 255, 0.07); border-radius: 14px; }"
        ),
        "custom": (
            "QFrame#collectionHero { "
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 rgba(119, 224, 190, 0.09), stop:1 rgba(13, 17, 24, 0.0)); "
            "border: none; border-bottom: 1px solid rgba(255, 255, 255, 0.07); border-radius: 14px; }"
        ),
    }

    def __init__(
        self,
        store: Optional[UserCollectionsStore] = None,
        media_library: Any = None,
        all_items_provider: Optional[Callable[[], List[Any]]] = None,
        notify_callback: Optional[Callable[[str], None]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.store = store
        self.media_library = media_library
        self._all_items_provider = all_items_provider
        self._notify = notify_callback

        self.selected_collection_id: str = FAVORITES_COLLECTION_ID
        self.current_playing_id: Optional[str] = None
        self.top_period: str = "all"
        self._full_tracks: List[Any] = []
        self._filtered_tracks: List[Any] = []
        self._top_views_full: List[TopTrackView] = []
        self._needs_refresh: bool = False
        self._needs_folders_refresh: bool = False

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_track_filter)

        self._init_ui()
        self._viewport = _CollectionTrackViewport(self)

        if self.store is not None:
            self.bind_store(self.store, self.media_library)

    def _init_ui(self) -> None:
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        # =====================================================================
        # LEFT RAIL: QUIET RECESSED SURFACE (NO HARSH BOX BORDER)
        # =====================================================================
        self.left_rail = QFrame()
        self.left_rail.setMinimumWidth(196)
        self.left_rail.setMaximumWidth(254)
        self.left_rail.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.left_rail.setObjectName("collectionsRail")
        self.left_rail.setStyleSheet(
            "QFrame#collectionsRail { "
            "background: #101620; border: 1px solid rgba(255, 255, 255, 0.055); border-radius: 14px; }"
        )
        rail_layout = QVBoxLayout(self.left_rail)
        rail_layout.setContentsMargins(10, 14, 10, 12)
        rail_layout.setSpacing(8)

        pl_top = QHBoxLayout()
        pl_top.setContentsMargins(6, 0, 2, 2)
        lbl_rail_title = QLabel("BỘ SƯU TẬP")
        lbl_rail_title.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #6E8096; letter-spacing: 0.9px;"
        )

        # Quiet ghost button — keeps ONLY ONE primary mint CTA on the entire screen!
        self.btn_create_playlist = QPushButton("Tạo playlist")
        self.btn_create_playlist.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_create_playlist.setFixedHeight(28)
        self.btn_create_playlist.setStyleSheet(
            "QPushButton { background: rgba(255, 255, 255, 0.05); color: #C9D7E6; "
            "border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; "
            "padding: 0 10px; font-weight: 600; font-size: 11.5px; }"
            "QPushButton:hover { background: rgba(119, 224, 190, 0.14); color: #9CF2D5; "
            "border-color: rgba(119, 224, 190, 0.35); }"
        )
        button_icon(self.btn_create_playlist, "plus", "Tạo Playlist mới", color=ACCENT, size=13, icon_only=False)
        self.btn_create_playlist.clicked.connect(self._on_create_playlist)

        pl_top.addWidget(lbl_rail_title)
        pl_top.addStretch()
        pl_top.addWidget(self.btn_create_playlist)
        rail_layout.addLayout(pl_top)

        self.collection_list = QListWidget()
        self.collection_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.collection_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { height: 40px; border-radius: 9px; padding: 0 10px; margin: 1px 0; "
            "color: #A9B8C9; font-size: 13px; font-weight: 500; }"
            "QListWidget::item:hover { background: rgba(255, 255, 255, 0.05); color: #EDF3FA; }"
            "QListWidget::item:selected { background: rgba(119, 224, 190, 0.12); color: #F0F7F5; font-weight: 600; }"
        )
        self.collection_list.currentItemChanged.connect(self._on_collection_selected)
        rail_layout.addWidget(self.collection_list, 3)

        # --- Multi-Folder Manager Section ---
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255, 255, 255, 0.06);")
        rail_layout.addWidget(sep)

        folder_hdr = QHBoxLayout()
        folder_hdr.setContentsMargins(6, 4, 2, 0)
        folder_hdr.setSpacing(4)
        lbl_folders = QLabel("NGUỒN THƯ MỤC")
        lbl_folders.setStyleSheet(
            "font-size: 10.5px; font-weight: 700; color: #6E8096; letter-spacing: 0.9px;"
        )

        self.btn_add_folder = QPushButton()
        self.btn_add_folder.setFixedSize(28, 28)
        self.btn_add_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_folder.setStyleSheet(_GHOST_ICON_BTN)
        button_icon(self.btn_add_folder, "folder-plus", "Thêm thư mục nhạc/video", color=ACCENT, size=15)
        self.btn_add_folder.clicked.connect(self._on_add_folder)

        self.btn_rescan_folders = QPushButton()
        self.btn_rescan_folders.setFixedSize(28, 28)
        self.btn_rescan_folders.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rescan_folders.setStyleSheet(_GHOST_ICON_BTN)
        button_icon(self.btn_rescan_folders, "refresh-cw", "Quét lại toàn bộ thư mục", color="#8A9BB0", size=14)
        self.btn_rescan_folders.clicked.connect(self._on_rescan_folders)

        folder_hdr.addWidget(lbl_folders)
        folder_hdr.addStretch()
        folder_hdr.addWidget(self.btn_add_folder)
        folder_hdr.addWidget(self.btn_rescan_folders)
        rail_layout.addLayout(folder_hdr)

        self.folder_scroll = QScrollArea()
        self.folder_scroll.setWidgetResizable(True)
        self.folder_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.folder_scroll.setMaximumHeight(150)
        self.folder_scroll.setStyleSheet("background: transparent; border: none;")

        self.folder_container = QWidget()
        self.folder_container.setStyleSheet("background: transparent;")
        self.folder_layout = QVBoxLayout(self.folder_container)
        self.folder_layout.setContentsMargins(2, 0, 2, 0)
        self.folder_layout.setSpacing(3)
        self.folder_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.folder_scroll.setWidget(self.folder_container)
        rail_layout.addWidget(self.folder_scroll, 2)

        root.addWidget(self.left_rail)

        # =====================================================================
        # RIGHT PANE: EDITORIAL ATMOSPHERIC HERO + BORDERLESS TRACK TABLE
        # =====================================================================
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("collectionHero")
        self.hero_card.setStyleSheet(self._HERO_TINTS[FAVORITES_COLLECTION_ID])
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(20, 18, 20, 16)
        hero_layout.setSpacing(14)

        hero_top = QHBoxLayout()
        hero_top.setSpacing(16)

        self.lbl_hero_emblem = QLabel()
        self.lbl_hero_emblem.setFixedSize(56, 56)
        self.lbl_hero_emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hero_emblem.setStyleSheet(
            "background: rgba(255, 255, 255, 0.055); border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 14px;"
        )
        hero_top.addWidget(self.lbl_hero_emblem)

        hero_meta = QVBoxLayout()
        hero_meta.setSpacing(4)
        hero_meta.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.lbl_collection_title = ElidedLabel("Bài hát Yêu thích", max_lines=1)
        self.lbl_collection_title.setStyleSheet("font-size: 24px; font-weight: 700; color: #F4F8FC;")
        self.lbl_collection_stats = QLabel("0 bài hát")
        self.lbl_collection_stats.setStyleSheet("font-size: 12.5px; color: #8A9BB0;")
        hero_meta.addWidget(self.lbl_collection_title)
        hero_meta.addWidget(self.lbl_collection_stats)
        hero_top.addLayout(hero_meta, 1)

        hero_layout.addLayout(hero_top)

        # Editorial stacked metric columns (NO bordered box soup!)
        self.top_kpi_strip = QWidget()
        self.top_kpi_strip.setFixedHeight(44)
        kpi_layout = QHBoxLayout(self.top_kpi_strip)
        kpi_layout.setContentsMargins(2, 0, 2, 0)
        kpi_layout.setSpacing(22)

        def _make_metric_col(caption: str, initial_val: str, accent: bool = False) -> Tuple[QWidget, ElidedLabel]:
            col_w = QWidget()
            col_w.setMinimumWidth(0)
            col_lay = QVBoxLayout(col_w)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(2)
            lbl_cap = QLabel(caption)
            lbl_cap.setStyleSheet(
                "color: #6B7E94; font-size: 10px; font-weight: 700; letter-spacing: 0.8px;"
            )
            lbl_val = ElidedLabel(initial_val, max_lines=1)
            lbl_val.setMinimumWidth(0)
            lbl_val.setFixedHeight(22)
            lbl_val.setStyleSheet(
                f"color: {'#77E0BE' if accent else '#EDF3FA'}; font-size: 15px; font-weight: 700;"
            )
            col_lay.addWidget(lbl_cap)
            col_lay.addWidget(lbl_val)
            return col_w, lbl_val

        def _v_divider() -> QFrame:
            line = QFrame()
            line.setFixedSize(1, 28)
            line.setStyleSheet("background: rgba(255, 255, 255, 0.08);")
            return line

        col_plays, self.lbl_kpi_plays = _make_metric_col("TỔNG LƯỢT PHÁT", "0 lượt", accent=False)
        col_time, self.lbl_kpi_time = _make_metric_col("THỜI GIAN NGHE", "0 giây", accent=False)
        col_artist, self.lbl_kpi_artist = _make_metric_col("NGHỆ SĨ HÀNG ĐẦU", "--", accent=True)

        kpi_layout.addWidget(col_plays, 1)
        kpi_layout.addWidget(_v_divider())
        kpi_layout.addWidget(col_time, 1)
        kpi_layout.addWidget(_v_divider())
        kpi_layout.addWidget(col_artist, 2)
        self.top_kpi_strip.hide()
        hero_layout.addWidget(self.top_kpi_strip)

        # Action bar: ONE primary pill button + quiet secondary pills + borderless-feel search
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btn_play_all = QPushButton("Phát tất cả")
        self.btn_play_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play_all.setFixedHeight(36)
        self.btn_play_all.setStyleSheet(_PRIMARY_PILL_BTN)
        button_icon(self.btn_play_all, "play", "Phát toàn bộ danh sách", color=INK, size=15, icon_only=False)
        self.btn_play_all.clicked.connect(self._on_play_all)

        self.btn_shuffle_play = QPushButton("Trộn bài")
        self.btn_shuffle_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_shuffle_play.setFixedHeight(36)
        self.btn_shuffle_play.setStyleSheet(_SECONDARY_PILL_BTN)
        button_icon(self.btn_shuffle_play, "shuffle", "Phát ngẫu nhiên danh sách", color=TEXT, size=15, icon_only=False)
        self.btn_shuffle_play.clicked.connect(self._on_shuffle_play)

        self.combo_top_period = StyledComboBox()
        self.combo_top_period.setFixedHeight(36)
        self.combo_top_period.setMinimumWidth(128)
        self.combo_top_period.setStyleSheet(
            "QComboBox { background: rgba(255, 255, 255, 0.05); color: #DCE7F3; "
            "border: 1px solid rgba(255, 255, 255, 0.09); border-radius: 18px; "
            "padding: 0 30px 0 14px; font-size: 12px; font-weight: 600; }"
            "QComboBox:hover { background: rgba(255, 255, 255, 0.09); border-color: rgba(255, 255, 255, 0.16); }"
            "QComboBox:focus { border-color: #77E0BE; }"
            "QComboBox::drop-down { width: 26px; border: none; background: transparent; }"
            "QComboBox::down-arrow { image: none; width: 0px; height: 0px; }"
            "QComboBox QAbstractItemView { background: #161F2B; color: #EDF3FA; "
            "selection-background-color: #19372F; selection-color: #A9F1D9; "
            "border: 1px solid #2A394C; border-radius: 8px; padding: 4px; }"
        )
        for text, pkey in TOP_PERIOD_OPTIONS:
            self.combo_top_period.addItem(text, pkey)
        self.combo_top_period.currentIndexChanged.connect(self._on_top_period_changed)
        self.combo_top_period.hide()

        self.btn_reset_stats = QPushButton()
        self.btn_reset_stats.setFixedSize(36, 36)
        self.btn_reset_stats.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_stats.setStyleSheet(_CIRCLE_GHOST_BTN)
        button_icon(self.btn_reset_stats, "rotate-ccw", "Đặt lại thống kê nghe nhiều nhất", color="#9AAABC", size=15)
        self.btn_reset_stats.clicked.connect(self._on_reset_stats)
        self.btn_reset_stats.hide()

        self.btn_add_songs = QPushButton("Thêm bài")
        self.btn_add_songs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_songs.setFixedHeight(36)
        self.btn_add_songs.setStyleSheet(_SECONDARY_PILL_BTN)
        button_icon(self.btn_add_songs, "plus", "Chọn thêm bài từ Thư viện", color=ACCENT, size=15, icon_only=False)
        self.btn_add_songs.clicked.connect(self._on_open_song_picker)

        self.btn_rename_pl = QPushButton()
        self.btn_rename_pl.setFixedSize(36, 36)
        self.btn_rename_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rename_pl.setStyleSheet(_CIRCLE_GHOST_BTN)
        button_icon(self.btn_rename_pl, "edit-3", "Đổi tên Playlist", color="#9AAABC", size=15)
        self.btn_rename_pl.clicked.connect(self._on_rename_playlist)

        self.btn_delete_pl = QPushButton()
        self.btn_delete_pl.setFixedSize(36, 36)
        self.btn_delete_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete_pl.setStyleSheet(_CIRCLE_GHOST_BTN)
        button_icon(self.btn_delete_pl, "trash", "Xóa Playlist", color="#9AAABC", size=15)
        self.btn_delete_pl.clicked.connect(self._on_delete_playlist)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm trong danh sách...")
        self.search_input.addAction(icon("search", "#788B9F"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setFixedHeight(36)
        self.search_input.setMinimumWidth(70)
        self.search_input.setMaximumWidth(240)
        self.search_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_input.setStyleSheet(
            "QLineEdit { background: rgba(255, 255, 255, 0.045); color: #EDF3FA; "
            "border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 18px; padding: 0 12px; font-size: 12.5px; }"
            "QLineEdit:focus { background: #141C27; border-color: #77E0BE; }"
        )
        self.search_input.textChanged.connect(lambda _t: self._search_timer.start())

        action_row.addWidget(self.btn_play_all)
        action_row.addWidget(self.btn_shuffle_play)
        action_row.addWidget(self.combo_top_period)
        action_row.addWidget(self.btn_reset_stats)
        action_row.addWidget(self.btn_add_songs)
        action_row.addWidget(self.btn_rename_pl)
        action_row.addWidget(self.btn_delete_pl)
        action_row.addStretch()
        action_row.addWidget(self.search_input)
        hero_layout.addLayout(action_row)

        right_col.addWidget(self.hero_card)

        # Subtle table column header row (Spotify / Tidal desktop rhythm)
        self.table_header = QWidget()
        self.table_header.setFixedHeight(26)
        th_layout = QHBoxLayout(self.table_header)
        th_layout.setContentsMargins(12, 2, 12, 2)
        th_layout.setSpacing(14)

        col_lbl_style = "color: #5D7086; font-size: 10.5px; font-weight: 700; letter-spacing: 0.8px;"
        lbl_col_idx = QLabel("#")
        lbl_col_idx.setFixedWidth(32)
        lbl_col_idx.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_col_idx.setStyleSheet(col_lbl_style)

        lbl_col_title = QLabel("TIÊU ĐỀ")
        lbl_col_title.setStyleSheet(col_lbl_style)

        self.lbl_col_plays = QLabel("LƯỢT NGHE")
        self.lbl_col_plays.setFixedWidth(96)
        self.lbl_col_plays.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_col_plays.setStyleSheet(col_lbl_style)
        self.lbl_col_plays.hide()

        lbl_col_dur = QLabel("THỜI LƯỢNG")
        lbl_col_dur.setFixedWidth(84)
        lbl_col_dur.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_col_dur.setStyleSheet(col_lbl_style)

        self.lbl_col_actions_spacer = QWidget()
        self.lbl_col_actions_spacer.setFixedWidth(104)

        th_layout.addWidget(lbl_col_idx)
        th_layout.addWidget(lbl_col_title, 1)
        th_layout.addWidget(self.lbl_col_plays)
        th_layout.addWidget(lbl_col_dur)
        th_layout.addWidget(self.lbl_col_actions_spacer)
        right_col.addWidget(self.table_header)

        # Minimal empty state (no dashed border box)
        self.empty_card = QFrame()
        self.empty_card.setStyleSheet("QFrame { background: transparent; border: none; }")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(32, 54, 32, 54)
        empty_layout.setSpacing(10)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_empty_icon = QLabel()
        label_icon(self.lbl_empty_icon, "heart", size=38, color=MUTED)
        self.lbl_empty_title = QLabel("Danh sách đang trống")
        self.lbl_empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_title.setStyleSheet("color: #DCE7F3; font-size: 16px; font-weight: 600;")
        self.lbl_empty_desc = QLabel("")
        self.lbl_empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_desc.setWordWrap(True)
        self.lbl_empty_desc.setMaximumWidth(420)
        self.lbl_empty_desc.setStyleSheet("color: #74879C; font-size: 13px;")

        empty_layout.addWidget(self.lbl_empty_icon, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.lbl_empty_title)
        empty_layout.addWidget(self.lbl_empty_desc, alignment=Qt.AlignmentFlag.AlignCenter)

        self.track_scroll = QScrollArea()
        self.track_scroll.setWidgetResizable(True)
        self.track_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.track_scroll.setStyleSheet("background: transparent; border: none;")

        self.track_canvas = QWidget()
        self.track_canvas.setStyleSheet("background: transparent;")
        self.track_scroll.setWidget(self.track_canvas)

        right_col.addWidget(self.empty_card, 1)
        right_col.addWidget(self.track_scroll, 1)
        self.track_scroll.hide()

        root.addLayout(right_col, 1)

    def bind_store(self, store: UserCollectionsStore, media_library: Any = None) -> None:
        self.store = store
        if media_library is not None:
            self.media_library = media_library
        store.favorites_changed.connect(self._on_store_changed)
        store.playlists_changed.connect(self._on_store_changed)
        store.stats_changed.connect(self._on_store_changed)
        store.folders_changed.connect(self._on_folders_store_changed)
        self.refresh_all()
        self.refresh_folders_ui()

    def _on_store_changed(self) -> None:
        if not self.isVisible():
            self._needs_refresh = True
            return
        self.refresh_all()

    def _on_folders_store_changed(self) -> None:
        if not self.isVisible():
            self._needs_folders_refresh = True
            return
        self.refresh_folders_ui()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._needs_refresh:
            self.refresh_all()
        else:
            self._viewport.schedule()
        if self._needs_folders_refresh:
            self.refresh_folders_ui()

    def hideEvent(self, event) -> None:
        self._viewport.cancel_workers()
        super().hideEvent(event)

    def refresh_thumbnail(self, media_id: str, thumb_path: str) -> None:
        if not media_id or not thumb_path:
            return
        matched = False
        for item in self._full_tracks:
            if getattr(item, "id", None) == media_id and getattr(item, "thumbnail", None) != thumb_path:
                item.thumbnail = thumb_path
                matched = True
        for item in self._viewport.items:
            if getattr(item, "id", None) == media_id and getattr(item, "thumbnail", None) != thumb_path:
                item.thumbnail = thumb_path
                matched = True
        if self.isVisible():
            if matched or any(getattr(it, "id", None) == media_id for it in self._viewport.items):
                self._viewport.schedule()
        elif matched:
            self._needs_refresh = True

    def set_playing_media_id(self, media_id: Optional[str]) -> None:
        self.current_playing_id = media_id
        if self.isVisible():
            self._viewport.render()
        else:
            self._needs_refresh = True

    def select_collection(self, collection_id: str) -> None:
        self.selected_collection_id = collection_id
        self.refresh_all()

    def refresh_all(self) -> None:
        self._needs_refresh = False
        if self.store is None:
            return

        playlists = self.store.get_playlists()
        valid_ids = {FAVORITES_COLLECTION_ID, MOST_PLAYED_COLLECTION_ID} | {pl["id"] for pl in playlists}
        if self.selected_collection_id not in valid_ids:
            self.selected_collection_id = FAVORITES_COLLECTION_ID

        self.collection_list.blockSignals(True)
        self.collection_list.clear()

        fav_count = self.store.favorite_count()
        fav_item = QListWidgetItem(
            icon("heart-filled", HEART_COLOR),
            f"Bài hát Yêu thích  ·  {fav_count}",
        )
        fav_item.setData(Qt.ItemDataRole.UserRole, FAVORITES_COLLECTION_ID)
        self.collection_list.addItem(fav_item)

        top_count = self.store.play_stats_count()
        top_item = QListWidgetItem(
            icon("flame", FLAME_COLOR),
            f"Nghe nhiều nhất  ·  {top_count}",
        )
        top_item.setData(Qt.ItemDataRole.UserRole, MOST_PLAYED_COLLECTION_ID)
        self.collection_list.addItem(top_item)

        selected_row = 1 if self.selected_collection_id == MOST_PLAYED_COLLECTION_ID else 0
        for idx, pl in enumerate(playlists, start=2):
            pl_item = QListWidgetItem(
                icon("list-music", ACCENT if pl["id"] == self.selected_collection_id else "#8A9BB0"),
                f"{pl['name']}  ·  {pl['count']}",
            )
            pl_item.setData(Qt.ItemDataRole.UserRole, pl["id"])
            self.collection_list.addItem(pl_item)
            if pl["id"] == self.selected_collection_id:
                selected_row = idx

        self.collection_list.setCurrentRow(selected_row)
        self.collection_list.blockSignals(False)

        self._refresh_selected_collection_pane()

    def _refresh_selected_collection_pane(self) -> None:
        if self.store is None:
            return
        is_fav = self.selected_collection_id == FAVORITES_COLLECTION_ID
        is_top = self.selected_collection_id == MOST_PLAYED_COLLECTION_ID
        is_custom = not is_fav and not is_top

        self.btn_add_songs.setVisible(is_custom)
        self.btn_rename_pl.setVisible(is_custom)
        self.btn_delete_pl.setVisible(is_custom)
        self.top_kpi_strip.setVisible(is_top)
        self.combo_top_period.setVisible(is_top)
        self.btn_reset_stats.setVisible(is_top)
        self.lbl_col_plays.setVisible(is_top)
        self.lbl_col_actions_spacer.setFixedWidth(70 if is_fav else 104)

        tint_key = self.selected_collection_id if self.selected_collection_id in self._HERO_TINTS else "custom"
        self.hero_card.setStyleSheet(self._HERO_TINTS[tint_key])

        self._top_views_full = []
        if is_fav:
            label_icon(self.lbl_hero_emblem, "heart-filled", size=24, color=HEART_COLOR)
            self.lbl_collection_title.setText("Bài hát Yêu thích")
            self.btn_play_all.setText("Phát tất cả")
            tracks = self.store.get_favorites(self.media_library)
            total_sec = sum(max(0.0, float(getattr(t, "duration", 0.0) or 0.0)) for t in tracks)
            self.lbl_collection_stats.setText(
                f"{len(tracks)} bài hát  ·  Tổng thời lượng {format_duration_mmss(total_sec)}"
                if total_sec > 0
                else f"{len(tracks)} bài hát"
            )
        elif is_top:
            label_icon(self.lbl_hero_emblem, "trophy", size=24, color=FLAME_COLOR)
            self.lbl_collection_title.setText("Top bài hát nghe nhiều nhất")
            self.btn_play_all.setText("Phát Top")
            self._top_views_full = self.store.get_top_tracks(
                period=self.top_period, limit=100, media_library=self.media_library
            )
            tracks = [tv.media for tv in self._top_views_full]
            summary = self.store.get_listening_summary(
                period=self.top_period, media_library=self.media_library
            )
            period_label = next(
                (lbl for lbl, key in TOP_PERIOD_OPTIONS if key == self.top_period), "Tất cả thời gian"
            )
            self.lbl_collection_stats.setText(
                f"{len(tracks)} bài hát  ·  {period_label}  ·  Tính lượt khi nghe >50% bài"
            )
            self.lbl_kpi_plays.setText(f"{summary['total_plays']} lượt")
            self.lbl_kpi_time.setText(format_listen_duration_vi(summary["total_listen_sec"]))
            if summary["top_artist"]:
                self.lbl_kpi_artist.setText(
                    f"{summary['top_artist']}  ·  {summary['top_artist_plays']} lượt"
                )
            else:
                self.lbl_kpi_artist.setText("Chưa có dữ liệu")
            self.btn_reset_stats.setEnabled(self.store.play_stats_count() > 0)
        else:
            label_icon(self.lbl_hero_emblem, "list-music", size=24, color=ACCENT)
            pl_meta = self.store.get_playlist(self.selected_collection_id)
            self.lbl_collection_title.setText(pl_meta["name"] if pl_meta else "Playlist")
            self.btn_play_all.setText("Phát tất cả")
            tracks = self.store.get_playlist_items(self.selected_collection_id, self.media_library)
            total_sec = sum(max(0.0, float(getattr(t, "duration", 0.0) or 0.0)) for t in tracks)
            self.lbl_collection_stats.setText(
                f"{len(tracks)} bài hát  ·  Tổng thời lượng {format_duration_mmss(total_sec)}"
                if total_sec > 0
                else f"{len(tracks)} bài hát"
            )

        self._full_tracks = tracks
        self._apply_track_filter()

    def _apply_track_filter(self) -> None:
        q = self.search_input.text().strip().lower()
        is_top = self.selected_collection_id == MOST_PLAYED_COLLECTION_ID
        if q:
            filtered = [
                t
                for t in self._full_tracks
                if q in getattr(t, "title", "").lower() or q in getattr(t, "artist", "").lower()
            ]
            filtered_ids = {getattr(t, "id", "") for t in filtered}
            top_views = [tv for tv in self._top_views_full if tv.media.id in filtered_ids] if is_top else []
        else:
            filtered = list(self._full_tracks)
            top_views = list(self._top_views_full) if is_top else []

        self._filtered_tracks = filtered
        has_any = len(filtered) > 0
        self.btn_play_all.setEnabled(has_any)
        self.btn_shuffle_play.setEnabled(has_any)
        self.table_header.setVisible(has_any)

        if not has_any:
            is_fav = self.selected_collection_id == FAVORITES_COLLECTION_ID
            if q and self._full_tracks:
                label_icon(self.lbl_empty_icon, "search", size=34, color="#6B7D92")
                self.lbl_empty_title.setText("Không tìm thấy bài hát phù hợp")
                self.lbl_empty_desc.setText(f"Không có bài nào khớp với từ khóa “{q}”.")
            elif is_fav:
                label_icon(self.lbl_empty_icon, "heart", size=36, color=HEART_COLOR)
                self.lbl_empty_title.setText("Chưa có bài hát Yêu thích")
                self.lbl_empty_desc.setText(
                    "Bấm biểu tượng trái tim trên thanh phát nhạc hoặc chuột phải vào video bất kỳ để lưu vào đây."
                )
            elif is_top:
                label_icon(self.lbl_empty_icon, "trophy", size=36, color=FLAME_COLOR)
                self.lbl_empty_title.setText("Chưa có dữ liệu bảng xếp hạng")
                self.lbl_empty_desc.setText(
                    "Nghe trên 50% thời lượng bài hát (hoặc 4 phút với video dài) để BoTube ghi nhận 1 lượt nghe vào bảng xếp hạng."
                )
            else:
                label_icon(self.lbl_empty_icon, "list-music", size=36, color=ACCENT)
                self.lbl_empty_title.setText("Playlist này chưa có bài hát")
                self.lbl_empty_desc.setText(
                    "Bấm nút “Thêm bài” ở trên hoặc chuột phải vào bài hát bất kỳ ở Thư viện để thêm vào."
                )
            self._viewport.set_items([], [])
            self.track_scroll.hide()
            self.empty_card.show()
            return

        self.empty_card.hide()
        self.track_scroll.show()
        self._viewport.set_items(filtered, top_views)

    def refresh_folders_ui(self) -> None:
        self._needs_folders_refresh = False
        while self.folder_layout.count():
            child = self.folder_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        folders = self.store.get_folders() if self.store is not None else []
        if not folders:
            lbl_none = QLabel("Chưa thêm thư mục nguồn.")
            lbl_none.setStyleSheet("color: #63758A; font-size: 11.5px; padding: 6px 6px;")
            lbl_none.setWordWrap(True)
            self.folder_layout.addWidget(lbl_none)
            return

        for fpath in folders:
            chip = QFrame()
            chip.setStyleSheet(
                "QFrame { background: transparent; border: none; border-radius: 7px; }"
                "QFrame:hover { background: rgba(255, 255, 255, 0.05); }"
            )
            row = QHBoxLayout(chip)
            row.setContentsMargins(6, 4, 4, 4)
            row.setSpacing(6)

            ic = QLabel()
            label_icon(ic, "folder-open", size=14, color="#6B7D92")
            ic.setFixedSize(16, 16)

            folder_name = Path(fpath).name or fpath
            lbl = ElidedLabel(folder_name, max_lines=1)
            lbl.setToolTip(fpath)
            lbl.setStyleSheet("color: #B9C8D9; font-size: 12px; font-weight: 500; border: none;")

            btn_rm = QPushButton()
            btn_rm.setFixedSize(22, 22)
            btn_rm.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_rm.setStyleSheet(_GHOST_ICON_BTN)
            button_icon(btn_rm, "x", f"Gỡ thư mục {folder_name}", color="#687A8F", size=12)
            btn_rm.clicked.connect(lambda _c=False, p=fpath: self._on_remove_folder(p))

            row.addWidget(ic)
            row.addWidget(lbl, 1)
            row.addWidget(btn_rm)
            self.folder_layout.addWidget(chip)

    def get_playback_playlist(self) -> List[Any]:
        return list(self._filtered_tracks)

    def current_custom_playlist_header(self) -> Tuple[Optional[str], str]:
        """Return (custom_playlist_id_or_None, header_title) for Favorites, Most Played, and Custom Playlists."""
        if self.selected_collection_id == FAVORITES_COLLECTION_ID:
            return None, "Bài hát Yêu thích"
        if self.selected_collection_id == MOST_PLAYED_COLLECTION_ID:
            return None, "Nghe nhiều nhất"
        if self.store is None:
            return None, ""
        pl = self.store.get_playlist(self.selected_collection_id)
        if not pl:
            return None, ""
        return pl["id"], pl["name"]

    # =========================================================================
    # USER ACTIONS
    # =========================================================================
    def _on_collection_selected(self, current: Optional[QListWidgetItem], prev: Optional[QListWidgetItem]) -> None:
        if current is None:
            return
        cid = current.data(Qt.ItemDataRole.UserRole)
        if cid and cid != self.selected_collection_id:
            if prev is not None:
                prev_cid = prev.data(Qt.ItemDataRole.UserRole)
                if prev_cid not in (FAVORITES_COLLECTION_ID, MOST_PLAYED_COLLECTION_ID):
                    prev.setIcon(icon("list-music", "#8A9BB0"))
            if cid not in (FAVORITES_COLLECTION_ID, MOST_PLAYED_COLLECTION_ID):
                current.setIcon(icon("list-music", ACCENT))
            self.selected_collection_id = cid
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            self._refresh_selected_collection_pane()

    def _on_create_playlist(self) -> None:
        if self.store is None:
            return
        dlg = TextPromptDialog(
            title="Tạo Playlist cá nhân",
            label_text="Đặt tên cho Playlist mới:",
            placeholder="VD: Nhạc Học Bài, Ballad Buồn, EDM Tập Gym...",
            confirm_label="Tạo Playlist",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            created = self.store.create_playlist(dlg.value())
            if created:
                self.selected_collection_id = created["id"]
                self.refresh_all()
                if self._notify:
                    self._notify(f"✨ Đã tạo Playlist mới: “{created['name']}”")

    def _on_rename_playlist(self) -> None:
        if self.store is None or self.selected_collection_id in (FAVORITES_COLLECTION_ID, MOST_PLAYED_COLLECTION_ID):
            return
        pl = self.store.get_playlist(self.selected_collection_id)
        if not pl:
            return
        dlg = TextPromptDialog(
            title="Đổi tên Playlist",
            label_text="Nhập tên mới cho Playlist:",
            initial_text=pl["name"],
            confirm_label="Lưu tên mới",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if self.store.rename_playlist(self.selected_collection_id, dlg.value()) and self._notify:
                self._notify(f"✎ Đã đổi tên Playlist thành “{dlg.value()}”")

    def _on_delete_playlist(self) -> None:
        if self.store is None or self.selected_collection_id in (FAVORITES_COLLECTION_ID, MOST_PLAYED_COLLECTION_ID):
            return
        pl = self.store.get_playlist(self.selected_collection_id)
        if not pl:
            return
        dlg = ConfirmActionDialog(
            title="Xóa Playlist",
            message=f"Bạn có muốn xóa Playlist “{pl['name']}” ({pl['count']} bài)?\nCác file video/nhạc gốc trên ổ cứng không bị ảnh hưởng.",
            confirm_label="Xóa Playlist",
            danger=True,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pid = self.selected_collection_id
            self.selected_collection_id = FAVORITES_COLLECTION_ID
            self.store.delete_playlist(pid)
            if self._notify:
                self._notify(f"🗑 Đã xóa Playlist “{pl['name']}”")

    def _on_open_song_picker(self) -> None:
        if self.store is None or self.selected_collection_id in (FAVORITES_COLLECTION_ID, MOST_PLAYED_COLLECTION_ID):
            return
        pl = self.store.get_playlist(self.selected_collection_id)
        if not pl:
            return
        all_items = self._all_items_provider() if callable(self._all_items_provider) else []
        existing_ids = {getattr(t, "id", "") for t in self._full_tracks}
        dlg = AddSongsPickerDialog(
            playlist_name=pl["name"],
            all_items=all_items,
            existing_ids=existing_ids,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            chosen = dlg.selected_items()
            added = self.store.add_many_to_playlist(self.selected_collection_id, chosen)
            if added > 0 and self._notify:
                self._notify(f"🎶 Đã thêm {added} bài hát vào Playlist “{pl['name']}”")

    def _on_play_all(self) -> None:
        if self._filtered_tracks:
            self.play_requested.emit(self._filtered_tracks[0], list(self._filtered_tracks))

    def _on_shuffle_play(self) -> None:
        if not self._filtered_tracks:
            return
        shuffled = list(self._filtered_tracks)
        random.shuffle(shuffled)
        self.play_requested.emit(shuffled[0], shuffled)

    def _on_row_clicked(self, media_item: Any) -> None:
        queue = list(self._filtered_tracks) if self._filtered_tracks else [media_item]
        self.play_requested.emit(media_item, queue)

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

    def _on_top_period_changed(self, *_args: Any) -> None:
        pkey = str(self.combo_top_period.currentData() or "all")
        if pkey != self.top_period:
            self.top_period = pkey
            if self.selected_collection_id == MOST_PLAYED_COLLECTION_ID:
                self._refresh_selected_collection_pane()

    def _on_reset_stats(self) -> None:
        if self.store is None or self.store.play_stats_count() == 0:
            return
        dlg = ConfirmActionDialog(
            title="Đặt lại Top nghe nhiều nhất",
            message="Bạn có chắc chắn muốn đặt lại toàn bộ thống kê lượt nghe và thời gian nghe? Yêu thích, Playlist và Lịch sử xem không bị ảnh hưởng.",
            confirm_label="Đặt lại thống kê",
            danger=True,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.store.reset_play_stats()
            if self._notify:
                self._notify("🔄 Đã đặt lại bảng xếp hạng nghe nhiều nhất")

    def _on_remove_from_playlist(self, media_item: Any) -> None:
        if self.store is None or self.selected_collection_id == FAVORITES_COLLECTION_ID:
            return
        mid = getattr(media_item, "id", "")
        if self.selected_collection_id == MOST_PLAYED_COLLECTION_ID:
            if self.store.remove_play_stat(mid) and self._notify:
                self._notify(f"➖ Đã gỡ “{media_item.title}” khỏi Top nghe nhiều nhất")
            return
        if self.store.remove_from_playlist(self.selected_collection_id, mid) and self._notify:
            self._notify(f"➖ Đã gỡ “{media_item.title}” khỏi Playlist")

    def _on_context_menu(self, media_item: Any, global_pos: QPoint) -> None:
        show_media_context_menu(
            self,
            global_pos,
            media_item,
            self.store,
            on_play=lambda item: self._on_row_clicked(item),
            on_notify=self._notify,
        )

    def _on_add_folder(self) -> None:
        if self.store is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Chọn thêm thư mục nhạc / video")
        if not folder:
            return
        added = self.store.add_folder(folder)
        folders = self.store.get_folders()
        if added:
            from config import ConfigManager
            ConfigManager.save_last_folder(folder)
            self.folders_scan_requested.emit(folders)
            if self._notify:
                self._notify(f"📂 Đã thêm nguồn thư mục: {Path(folder).name or folder}")
        else:
            if self._notify:
                self._notify("ℹ️ Thư mục này đã có trong danh sách nguồn")

    def _on_remove_folder(self, folder_path: str) -> None:
        if self.store is None:
            return
        if self.store.remove_folder(folder_path):
            folders = self.store.get_folders()
            from config import ConfigManager
            ConfigManager.save_last_folder(folders[0] if folders else "")
            self.folders_scan_requested.emit(folders)
            if self._notify:
                self._notify(f"📂 Đã gỡ nguồn thư mục: {Path(folder_path).name or folder_path}")

    def _on_rescan_folders(self) -> None:
        if self.store is None:
            return
        folders = self.store.get_folders()
        if folders:
            self.folders_scan_requested.emit(folders)
            if self._notify:
                self._notify(f"🔄 Đang quét lại {len(folders)} thư mục nguồn...")
