"""Shared dark-studio context menus, dialogs, and multi-select song picker for Collections & History."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.user_collections import UserCollectionsStore, format_duration_mmss
from ui.design_system import DIALOG_STYLE
from ui.icons import ACCENT, HEART_COLOR, MUTED, TEXT, icon


class StyledComboBox(QComboBox):
    """Dark studio QComboBox that paints a crisp HiDPI Lucide chevron-down icon."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chevron = icon("chevron-down", MUTED)
        size = 14
        rect = QRect(self.width() - size - 9, (self.height() - size) // 2, size, size)
        chevron.paint(painter, rect)
        painter.end()

MENU_STYLE = """
QMenu {
    background-color: #151C26;
    color: #EDF3FA;
    border: 1px solid #2C3B4E;
    border-radius: 10px;
    padding: 6px;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QMenu::item {
    padding: 7px 14px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: #19372F;
    color: #A9F1D9;
}
QMenu::item:disabled {
    color: #526173;
}
QMenu::separator {
    height: 1px;
    background: #273445;
    margin: 5px 8px;
}
"""


def reveal_in_file_manager(file_path: str) -> bool:
    if not file_path:
        return False
    p = Path(file_path)
    if not p.exists():
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p.resolve())])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p.resolve())])
        else:
            subprocess.Popen(["xdg-open", str(p.resolve().parent)])
        return True
    except Exception:
        return False


class TextPromptDialog(QDialog):
    def __init__(
        self,
        title: str,
        label_text: str,
        initial_text: str = "",
        placeholder: str = "",
        confirm_label: str = "Lưu",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #EDF3FA; font-size: 14px; font-weight: 600;")
        layout.addWidget(lbl)

        self.input_edit = QLineEdit(initial_text)
        self.input_edit.setPlaceholderText(placeholder)
        self.input_edit.setFixedHeight(38)
        self.input_edit.selectAll()
        layout.addWidget(self.input_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_ok = QPushButton(confirm_label)
        self.btn_ok.setProperty("role", "primary")
        self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ok.clicked.connect(self._on_accept)
        self.input_edit.returnPressed.connect(self._on_accept)

        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        layout.addLayout(btn_row)

    def _on_accept(self) -> None:
        if self.input_edit.text().strip():
            self.accept()

    def value(self) -> str:
        return self.input_edit.text().strip()


class ConfirmActionDialog(QDialog):
    def __init__(
        self,
        title: str,
        message: str,
        confirm_label: str = "Xác nhận",
        danger: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(430)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        lbl = QLabel(message)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #EDF3FA; font-size: 13px; line-height: 140%;")
        layout.addWidget(lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_confirm = QPushButton(confirm_label)
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        if danger:
            self.btn_confirm.setStyleSheet(
                "QPushButton { background: #C84B5B; color: #FFFFFF; border: 1px solid #D95F6E; "
                "border-radius: 8px; padding: 8px 16px; font-weight: 600; }"
                "QPushButton:hover { background: #DF5C6D; }"
            )
        else:
            self.btn_confirm.setProperty("role", "primary")
        self.btn_confirm.clicked.connect(self.accept)

        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_confirm)
        layout.addLayout(btn_row)


class AddSongsPickerDialog(QDialog):
    """Multi-select dialog to quickly add multiple library tracks into a Playlist."""

    def __init__(
        self,
        playlist_name: str,
        all_items: Sequence[Any],
        existing_ids: set[str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Thêm bài hát vào “{playlist_name}”")
        self.setModal(True)
        self.resize(620, 520)
        self.setStyleSheet(DIALOG_STYLE)

        self._all_items = [item for item in all_items if getattr(item, "id", "") not in existing_ids]
        self._selected_ids: set[str] = set()
        self._item_by_id = {item.id: item for item in self._all_items}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header = QLabel(f"Chọn bài hát để thêm vào Playlist “{playlist_name}”")
        header.setStyleSheet("font-size: 15px; font-weight: 700; color: #EDF3FA;")
        layout.addWidget(header)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Tìm nhanh theo tên bài hát hoặc ca sĩ...")
        self.search_input.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search_input.setFixedHeight(38)
        self.search_input.textChanged.connect(self._apply_filter)

        self.chk_select_visible = QCheckBox("Chọn tất cả đang lọc")
        self.chk_select_visible.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_select_visible.setStyleSheet("color: #9AAABC; font-size: 12px;")
        self.chk_select_visible.clicked.connect(self._toggle_select_visible)

        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.chk_select_visible)
        layout.addLayout(search_row)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget { background: #101722; border: 1px solid #273445; border-radius: 10px; padding: 6px; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #EDF3FA; }"
            "QListWidget::item:hover { background: #1B2431; }"
        )
        self.list_widget.itemChanged.connect(self._on_item_checked)
        layout.addWidget(self.list_widget, 1)

        footer = QHBoxLayout()
        self.lbl_selected = QLabel("Đã chọn: 0 bài")
        self.lbl_selected.setStyleSheet("color: #77E0BE; font-size: 13px; font-weight: 600;")
        footer.addWidget(self.lbl_selected)
        footer.addStretch()

        btn_cancel = QPushButton("Đóng")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        self.btn_add = QPushButton("Thêm vào Playlist")
        self.btn_add.setProperty("role", "primary")
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self.accept)

        footer.addWidget(btn_cancel)
        footer.addWidget(self.btn_add)
        layout.addLayout(footer)

        self._populate_list("")

    def _populate_list(self, query: str) -> None:
        q = query.strip().lower()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for item in self._all_items:
            title = getattr(item, "title", "")
            artist = getattr(item, "artist", "Unknown Artist")
            if q and q not in title.lower() and q not in artist.lower():
                continue
            dur = format_duration_mmss(getattr(item, "duration", 0.0))
            row = QListWidgetItem(f"{title}  —  {artist}   [{dur}]")
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(
                Qt.CheckState.Checked if item.id in self._selected_ids else Qt.CheckState.Unchecked
            )
            self.list_widget.addItem(row)
        self.list_widget.blockSignals(False)

    def _apply_filter(self, text: str) -> None:
        self.chk_select_visible.setChecked(False)
        self._populate_list(text)

    def _on_item_checked(self, row: QListWidgetItem) -> None:
        mid = row.data(Qt.ItemDataRole.UserRole)
        if not mid:
            return
        if row.checkState() == Qt.CheckState.Checked:
            self._selected_ids.add(mid)
        else:
            self._selected_ids.discard(mid)
        self._refresh_count()

    def _toggle_select_visible(self, checked: bool) -> None:
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            row = self.list_widget.item(i)
            mid = row.data(Qt.ItemDataRole.UserRole)
            row.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            if checked:
                self._selected_ids.add(mid)
            else:
                self._selected_ids.discard(mid)
        self.list_widget.blockSignals(False)
        self._refresh_count()

    def _refresh_count(self) -> None:
        n = len(self._selected_ids)
        self.lbl_selected.setText(f"Đã chọn: {n} bài")
        self.btn_add.setEnabled(n > 0)

    def selected_items(self) -> List[Any]:
        return [self._item_by_id[mid] for mid in self._selected_ids if mid in self._item_by_id]


def populate_add_to_playlist_submenu(
    menu: QMenu,
    media_item: Any,
    store: UserCollectionsStore,
    parent_widget: Optional[QWidget] = None,
    on_notify: Optional[Callable[[str], None]] = None,
) -> None:
    playlists = store.get_playlists()
    if playlists:
        for pl in playlists:
            pid = pl["id"]
            pl_name = pl["name"]
            act = menu.addAction(icon("list-music", TEXT), f"{pl_name} ({pl['count']})")
            act.triggered.connect(
                lambda _checked=False, p_id=pid, p_name=pl_name: _handle_add_single(
                    store, p_id, p_name, media_item, on_notify
                )
            )
        menu.addSeparator()

    act_new = menu.addAction(icon("plus", ACCENT), "Tạo Playlist mới và thêm bài này...")
    act_new.triggered.connect(
        lambda _checked=False: _handle_create_and_add(
            parent_widget, store, media_item, on_notify
        )
    )


def _handle_add_single(
    store: UserCollectionsStore,
    playlist_id: str,
    playlist_name: str,
    media_item: Any,
    on_notify: Optional[Callable[[str], None]],
) -> None:
    added = store.add_to_playlist(playlist_id, media_item)
    if on_notify:
        title = getattr(media_item, "title", "Bài hát")
        if added:
            on_notify(f"🎶 Đã thêm “{title}” vào Playlist “{playlist_name}”")
        else:
            on_notify(f"ℹ️ “{title}” đã có sẵn trong Playlist “{playlist_name}”")


def _handle_create_and_add(
    parent_widget: Optional[QWidget],
    store: UserCollectionsStore,
    media_item: Any,
    on_notify: Optional[Callable[[str], None]],
) -> None:
    dlg = TextPromptDialog(
        title="Tạo Playlist mới",
        label_text="Nhập tên cho Playlist mới của bạn:",
        placeholder="VD: Nhạc Chill Đêm Khuya, US-UK Hay Nhất...",
        confirm_label="Tạo & Thêm bài",
        parent=parent_widget,
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        created = store.create_playlist(dlg.value())
        if created:
            store.add_to_playlist(created["id"], media_item)
            if on_notify:
                on_notify(f"✨ Đã tạo Playlist “{created['name']}” và thêm bài hát")


def show_add_to_playlist_menu(
    parent_widget: QWidget,
    global_pos: QPoint,
    media_item: Any,
    store: UserCollectionsStore,
    on_notify: Optional[Callable[[str], None]] = None,
) -> None:
    if media_item is None or store is None:
        return
    menu = QMenu(parent_widget)
    menu.setStyleSheet(MENU_STYLE)
    populate_add_to_playlist_submenu(menu, media_item, store, parent_widget=parent_widget, on_notify=on_notify)
    menu.exec(global_pos)


def show_media_context_menu(
    parent_widget: QWidget,
    global_pos: QPoint,
    media_item: Any,
    store: Optional[UserCollectionsStore],
    on_play: Optional[Callable[[Any], None]] = None,
    on_notify: Optional[Callable[[str], None]] = None,
) -> None:
    if media_item is None:
        return
    menu = QMenu(parent_widget)
    menu.setStyleSheet(MENU_STYLE)

    if on_play is not None:
        act_play = menu.addAction(icon("play", ACCENT), "Phát ngay")
        act_play.triggered.connect(lambda _c=False: on_play(media_item))
        menu.addSeparator()

    if store is not None:
        is_fav = store.is_favorite(getattr(media_item, "id", ""))
        fav_label = "Bỏ khỏi Yêu thích" if is_fav else "Thêm vào Yêu thích"
        fav_icon = icon("heart-filled", HEART_COLOR) if is_fav else icon("heart", TEXT)
        act_fav = menu.addAction(fav_icon, fav_label)

        def _toggle_fav() -> None:
            now_fav = store.toggle_favorite(media_item)
            if on_notify:
                title = getattr(media_item, "title", "Bài hát")
                on_notify(
                    f"❤️ Đã thêm “{title}” vào Yêu thích"
                    if now_fav
                    else f"💔 Đã bỏ “{title}” khỏi Yêu thích"
                )

        act_fav.triggered.connect(lambda _c=False: _toggle_fav())

        sub_pl = menu.addMenu(icon("list-music", TEXT), "Thêm vào Playlist")
        sub_pl.setStyleSheet(MENU_STYLE)
        populate_add_to_playlist_submenu(
            sub_pl, media_item, store, parent_widget=parent_widget, on_notify=on_notify
        )

    path_str = str(getattr(media_item, "path", "") or "")
    if path_str and os.path.exists(path_str):
        menu.addSeparator()
        act_open_dir = menu.addAction(icon("folder-open", TEXT), "Hiển thị trong thư mục")
        act_open_dir.triggered.connect(lambda _c=False: reveal_in_file_manager(path_str))

    menu.exec(global_pos)
