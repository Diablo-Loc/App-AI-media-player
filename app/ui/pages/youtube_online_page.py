"""Commercial-grade isolated YouTube Online Studio page for BoTube.

Self-contained tab (zero mutations to offline Library, For You, SubtitleManager, or AudioStreamEngine):
- Full YouTube Desktop workflow: Home & Topic Chips, Live Search + Autocomplete, URL paste
  (Video/Playlist/Channel), 2-Column Watch Page (4K/1080p Video or Audio-Only Hi-Fi 64-bit DAC),
  Chapters, Clickable Timestamps, Top Comments, Auto-Mix Radio Queue, Channel View, Playlist View,
  Local Profile (Subscriptions / Liked / Online Playlists / Watch History) + Read-Only Cookie Sync.
- 3-Mode Subtitle Control: Off (0% overhead) | YouTube CC (instant native captions) | AI Sub Handoff.
- 100% Bilingual VI/EN with zero leftover strings and clean worker/process lifecycle ownership.
"""
from __future__ import annotations

from collections import OrderedDict
import html
import logging
import random
import re
from typing import Any, Callable
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from control.worker_lifecycle import OwnedProcesses
from core.audio_profile import AudioProfile
from core.youtube_online_client import (
    OnlineChannelInfo,
    OnlineChapter,
    OnlineComment,
    OnlineSubtitleTrack,
    OnlineVideoItem,
    OnlineWatchInfo,
    ResolvedStream,
    TOPIC_CHIPS,
    YouTubeOnlineClient,
    YouTubeOnlineProfileStore,
    format_seconds_mmss,
    parse_duration_text,
    parse_youtube_input,
)
from core.youtube_online_player import YouTubeOnlinePlaybackController
from ui.design_system import DIALOG_STYLE, FORM_STYLE, ICON_BUTTON_STYLE
from ui.i18n import get_language, register_language_listener, tr_pair, unregister_language_listener
from ui.icons import ACCENT, HEART_COLOR, INK, MUTED, TEXT, button_icon, icon

logger = logging.getLogger(__name__)

_RE_DESC_TS = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")

YOUTUBE_PAGE_STYLE = """
QWidget#youtubeOnlineRoot { background: #0D1118; color: #EDF3FA; }
QFrame#ytTopBar {
    background: #101722; border-bottom: 1px solid #222F40;
}
QFrame#ytSubNav {
    background: #0F1520; border-bottom: 1px solid #1E2A3A;
}
QLineEdit#ytSearchInput {
    background: #151C26; color: #EDF3FA; border: 1px solid #2A384B;
    border-radius: 19px; padding: 0 16px; font-size: 13px;
}
QLineEdit#ytSearchInput:focus { border-color: #77E0BE; background: #18212E; }
QPushButton[ytChip="true"] {
    background: #161F2C; color: #C2D0E0; border: 1px solid #263447;
    border-radius: 15px; padding: 5px 14px; font-size: 12px; font-weight: 600;
}
QPushButton[ytChip="true"]:hover { background: #212E40; color: #EDF3FA; border-color: #3D5068; }
QPushButton[ytChip="true"]:checked {
    background: #77E0BE; color: #0D1118; border-color: #77E0BE;
}
QPushButton[ytNavTab="true"] {
    background: transparent; color: #9AAABC; border: none;
    border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 600;
}
QPushButton[ytNavTab="true"]:hover { background: #1A2332; color: #EDF3FA; }
QPushButton[ytNavTab="true"]:checked {
    background: #19372F; color: #A9F1D9;
}
QPushButton#ytSubscribeBtn {
    background: #FF4E45; color: #FFFFFF; border: none;
    border-radius: 17px; padding: 7px 18px; font-weight: 700; font-size: 12px;
}
QPushButton#ytSubscribeBtn:hover { background: #FF6B63; }
QPushButton#ytSubscribeBtn:checked {
    background: #233041; color: #D4E0EE; border: 1px solid #394C64;
}
QPushButton#ytPlayCircle {
    background: #77E0BE; color: #0D1118; border: none; border-radius: 19px;
}
QPushButton#ytPlayCircle:hover { background: #9AEDD3; }
QPushButton#ytAudioToggle {
    background: #192433; color: #DCE6F2; border: 1px solid #2C3D54;
    border-radius: 16px; padding: 5px 13px; font-size: 12px; font-weight: 600;
}
QPushButton#ytAudioToggle:checked {
    background: #19372F; color: #77E0BE; border-color: #77E0BE;
}
QFrame#ytCard {
    background: #131A24; border: 1px solid #1E2938; border-radius: 12px;
}
QFrame#ytCard:hover {
    background: #192230; border-color: #364961;
}
QFrame#ytWatchControls {
    background: #121924; border: 1px solid #222F40; border-radius: 10px;
}
QFrame#ytPanel {
    background: #131B26; border: 1px solid #223042; border-radius: 12px;
}
QFrame#ytMiniBar {
    background: #111824; border-top: 1px solid #28364A;
}
QLabel#ytAudioBadge {
    background: #16322B; color: #8AE8CA; border: 1px solid #2B5E51;
    border-radius: 11px; padding: 3px 10px; font-size: 11px; font-weight: 600;
}
QLabel#ytLiveBadge {
    background: #D93832; color: #FFFFFF; border-radius: 4px;
    padding: 2px 6px; font-size: 10px; font-weight: 700;
}
QComboBox[ytCompact="true"] {
    background: #17202D; color: #EDF3FA; border: 1px solid #2B394D;
    border-radius: 7px; padding: 4px 8px; font-size: 12px; min-height: 26px;
}
QComboBox[ytCompact="true"]:hover { border-color: #465B76; }
QComboBox[ytCompact="true"] QAbstractItemView {
    background: #18212E; color: #EDF3FA; selection-background-color: #284E44;
    border: 1px solid #35475E;
}
QSlider#ytSeekSlider::groove:horizontal {
    height: 5px; background: #2D3B4F; border-radius: 2px;
}
QSlider#ytSeekSlider::sub-page:horizontal {
    background: #FF4E45; border-radius: 2px;
}
QSlider#ytSeekSlider::handle:horizontal {
    background: #EDF3FA; width: 13px; height: 13px; margin: -4px 0; border-radius: 6px;
}
QSlider#ytSeekSlider::handle:horizontal:hover { background: #77E0BE; }
QListWidget#ytSuggestPopup {
    background: #161F2B; color: #EDF3FA; border: 1px solid #34465C;
    border-radius: 10px; padding: 4px; outline: none; font-size: 13px;
}
QListWidget#ytSuggestPopup::item { padding: 7px 12px; border-radius: 6px; }
QListWidget#ytSuggestPopup::item:hover,
QListWidget#ytSuggestPopup::item:selected { background: #223044; color: #A9F1D9; }
"""


# =====================================================================
# ASYNC WORKERS & BOUNDED THUMBNAIL CACHE
# =====================================================================

class _TaskWorker(QThread):
    """Generic cancellable background worker with generation guard and process ownership."""

    finished_ok = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, generation: int, fn: Callable[..., Any], *, pass_processes: bool = False, parent: QObject | None = None):
        super().__init__(parent)
        self.generation = int(generation)
        self._fn = fn
        self._pass_processes = bool(pass_processes)
        self.processes = OwnedProcesses()

    def run(self) -> None:
        try:
            res = self._fn(self.processes) if self._pass_processes else self._fn()
            if not self.isInterruptionRequested():
                self.finished_ok.emit(self.generation, res)
        except Exception as err:
            if not self.isInterruptionRequested():
                self.failed.emit(self.generation, str(err))
        finally:
            self.processes.stop()
            self.processes.wait()

    def cancel(self) -> None:
        self.requestInterruption()
        self.processes.stop()


class _OnlineThumbnailLoader(QObject):
    """RAM-bounded async HTTP thumbnail loader (max 220 pixmaps, weakref label targets)."""

    MAX_CACHE = 220

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: dict[str, list[tuple[weakref.ref, QSize]]] = {}
        self._active_replies: set[QNetworkReply] = set()

    def load(self, url: str, target_label: QLabel, target_size: QSize) -> None:
        u = str(url or "").strip()
        if not u:
            return
        if u in self._cache:
            pix = self._cache[u]
            self._cache.move_to_end(u)
            self._apply_pixmap(target_label, pix, target_size)
            return
        ref = weakref.ref(target_label)
        if u in self._pending:
            self._pending[u].append((ref, target_size))
            return
        self._pending[u] = [(ref, target_size)]
        req = QNetworkRequest(QUrl(u))
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        reply = self._nam.get(req)
        self._active_replies.add(reply)
        reply.finished.connect(lambda r=reply, key=u: self._on_finished(r, key))

    def _on_finished(self, reply: QNetworkReply, url: str) -> None:
        self._active_replies.discard(reply)
        targets = self._pending.pop(url, [])
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                raw = bytes(reply.readAll())
                pix = QPixmap()
                if pix.loadFromData(raw):
                    self._cache[url] = pix
                    self._cache.move_to_end(url)
                    while len(self._cache) > self.MAX_CACHE:
                        self._cache.popitem(last=False)
                    for ref, sz in targets:
                        lbl = ref()
                        if lbl is not None:
                            try:
                                self._apply_pixmap(lbl, pix, sz)
                            except RuntimeError:
                                pass
        finally:
            reply.deleteLater()

    @staticmethod
    def _apply_pixmap(label: QLabel, pix: QPixmap, target_size: QSize) -> None:
        if pix.isNull():
            return
        scaled = pix.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Center crop cleanly to exact aspect ratio
        x = max(0, (scaled.width() - target_size.width()) // 2)
        y = max(0, (scaled.height() - target_size.height()) // 2)
        cropped = scaled.copy(x, y, min(target_size.width(), scaled.width()), min(target_size.height(), scaled.height()))
        label.setPixmap(cropped)

    def shutdown(self) -> None:
        for reply in list(self._active_replies):
            try:
                reply.abort()
                reply.deleteLater()
            except Exception:
                pass
        self._active_replies.clear()
        self._pending.clear()


# =====================================================================
# CUSTOM INTERACTIVE WIDGETS (SEEK SLIDER, VIDEO CARD, STAGE)
# =====================================================================

class _ClickSeekSlider(QSlider):
    """YouTube-style progress bar supporting instant click-to-seek and chapter hover tooltips."""

    seek_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("ytSeekSlider")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._chapters: list[OnlineChapter] = []

    def set_chapters(self, chapters: list[OnlineChapter]) -> None:
        self._chapters = list(chapters or [])

    def _value_at_x(self, x: float) -> int:
        w = max(1, self.width())
        ratio = max(0.0, min(1.0, float(x) / float(w)))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
            val = self._value_at_x(event.position().x())
            self.setValue(val)
            self.seek_requested.emit(val)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.maximum() > 0:
            val_ms = self._value_at_x(event.position().x())
            sec = val_ms / 1000.0
            tip = format_seconds_mmss(sec)
            for ch in self._chapters:
                if sec >= ch.start_sec and (ch.end_sec <= 0 or sec < ch.end_sec):
                    tip = f"{tip} · {ch.title}"
                    break
            self.setToolTip(tip)
        super().mouseMoveEvent(event)


class _OnlineVideoCard(QFrame):
    """Crisp 16:9 YouTube Desktop video/playlist/channel card."""

    clicked = Signal(object)
    channel_clicked = Signal(str, str)
    queue_clicked = Signal(object)
    download_clicked = Signal(object)

    THUMB_SIZE = QSize(272, 153)

    def __init__(self, item: OnlineVideoItem, thumb_loader: _OnlineThumbnailLoader, parent: QWidget | None = None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("ytCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(288)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 10)
        root.setSpacing(7)

        # Thumbnail container with overlaid duration/LIVE badge
        thumb_wrap = QFrame()
        thumb_wrap.setFixedSize(self.THUMB_SIZE)
        thumb_wrap.setStyleSheet("background: #0A0E14; border-radius: 9px; border: none;")
        thumb_grid = QGridLayout(thumb_wrap)
        thumb_grid.setContentsMargins(0, 0, 0, 0)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(self.THUMB_SIZE)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setStyleSheet("background: #101620; border-radius: 9px; color: #536479;")
        if item.item_type == "channel":
            self.lbl_thumb.setText("CHANNEL")
        elif item.item_type == "playlist":
            self.lbl_thumb.setText("PLAYLIST")
        thumb_grid.addWidget(self.lbl_thumb, 0, 0)

        badge_text = ""
        if item.is_live:
            badge_text = "LIVE"
        elif item.item_type == "playlist":
            badge_text = item.video_count_text or "Playlist"
        elif item.item_type == "channel":
            badge_text = tr_pair("Kênh", "Channel")
        elif item.duration_text:
            badge_text = item.duration_text

        if badge_text:
            badge = QLabel(badge_text)
            if item.is_live:
                badge.setObjectName("ytLiveBadge")
            elif item.item_type == "playlist":
                badge.setStyleSheet(
                    "background: rgba(13, 17, 24, 225); color: #77E0BE; border: 1px solid #2B5E51; "
                    "border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 700;"
                )
            else:
                badge.setStyleSheet(
                    "background: rgba(10, 14, 20, 220); color: #F2F6FB; "
                    "border-radius: 5px; padding: 2px 6px; font-size: 11px; font-weight: 600;"
                )
            thumb_grid.addWidget(badge, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
            thumb_grid.setContentsMargins(0, 0, 6, 6)

        root.addWidget(thumb_wrap)

        # Title (2 lines crisp)
        self.lbl_title = QLabel(item.title)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setFixedHeight(38)
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl_title.setStyleSheet("color: #EDF3FA; font-size: 13px; font-weight: 600;")
        self.lbl_title.setToolTip(item.title)
        root.addWidget(self.lbl_title)

        # Channel & metadata row + compact quick actions
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(4)

        meta_col = QVBoxLayout()
        meta_col.setContentsMargins(0, 0, 0, 0)
        meta_col.setSpacing(2)

        ch_btn = QPushButton(item.channel_name or ("YouTube" if item.item_type != "channel" else item.title))
        ch_btn.setFlat(True)
        ch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ch_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #9AAABC; "
            "font-size: 12px; text-align: left; padding: 0; font-weight: 500; }"
            "QPushButton:hover { color: #77E0BE; }"
        )
        ch_btn.clicked.connect(lambda: self.channel_clicked.emit(item.channel_id, item.channel_name or item.title))
        meta_col.addWidget(ch_btn)

        stats_parts = [p for p in (item.views_text, item.published_text) if p]
        lbl_stats = QLabel(" • ".join(stats_parts) if stats_parts else ("Playlist" if item.item_type == "playlist" else ""))
        lbl_stats.setStyleSheet("color: #7D8FA3; font-size: 11px;")
        meta_col.addWidget(lbl_stats)
        meta_row.addLayout(meta_col, 1)

        if item.item_type == "video":
            btn_q = QPushButton()
            btn_q.setFixedSize(26, 26)
            btn_q.setStyleSheet(ICON_BUTTON_STYLE)
            button_icon(btn_q, "plus", tr_pair("Thêm vào hàng đợi", "Add to queue"), color=MUTED, size=14)
            btn_q.clicked.connect(lambda: self.queue_clicked.emit(self.item))
            meta_row.addWidget(btn_q)

            btn_dl = QPushButton()
            btn_dl.setFixedSize(26, 26)
            btn_dl.setStyleSheet(ICON_BUTTON_STYLE)
            button_icon(btn_dl, "download", tr_pair("Tải về thư viện BoTube", "Download to BoTube library"), color=MUTED, size=14)
            btn_dl.clicked.connect(lambda: self.download_clicked.emit(self.item))
            meta_row.addWidget(btn_dl)

        root.addLayout(meta_row)

        if item.thumbnail_url:
            thumb_loader.load(item.thumbnail_url, self.lbl_thumb, self.THUMB_SIZE)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _CompactRelatedRow(QFrame):
    """YouTube Watch right-column Up Next / Queue compact horizontal card."""

    clicked = Signal(object)

    THUMB_SIZE = QSize(136, 76)

    def __init__(
        self,
        item: OnlineVideoItem,
        thumb_loader: _OnlineThumbnailLoader,
        *,
        is_active: bool = False,
        index_num: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.item = item
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_highlight(is_active)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(8)

        if index_num is not None:
            lbl_idx = QLabel("▶" if is_active else str(index_num))
            lbl_idx.setFixedWidth(18)
            lbl_idx.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_idx.setStyleSheet(f"color: {'#77E0BE' if is_active else '#7D8FA3'}; font-size: 11px; font-weight: 700;")
            row.addWidget(lbl_idx)

        thumb_wrap = QFrame()
        thumb_wrap.setFixedSize(self.THUMB_SIZE)
        thumb_wrap.setStyleSheet("background: #0A0E14; border-radius: 7px; border: none;")
        t_grid = QGridLayout(thumb_wrap)
        t_grid.setContentsMargins(0, 0, 4, 4)

        lbl_thumb = QLabel()
        lbl_thumb.setFixedSize(self.THUMB_SIZE)
        lbl_thumb.setStyleSheet("background: #101620; border-radius: 7px;")
        t_grid.addWidget(lbl_thumb, 0, 0)

        if item.duration_text:
            dur = QLabel(item.duration_text)
            dur.setStyleSheet(
                "background: rgba(10, 14, 20, 220); color: #EDF3FA; border-radius: 4px; "
                "padding: 1px 5px; font-size: 10px; font-weight: 600;"
            )
            t_grid.addWidget(dur, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        row.addWidget(thumb_wrap)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        lbl_t = QLabel(item.title)
        lbl_t.setWordWrap(True)
        lbl_t.setMaximumHeight(36)
        lbl_t.setStyleSheet(f"color: {'#A9F1D9' if is_active else '#EDF3FA'}; font-size: 12px; font-weight: 600;")
        lbl_t.setToolTip(item.title)
        col.addWidget(lbl_t)

        lbl_ch = QLabel(item.channel_name or "YouTube")
        lbl_ch.setStyleSheet("color: #9AAABC; font-size: 11px;")
        col.addWidget(lbl_ch)

        if item.views_text:
            lbl_v = QLabel(item.views_text)
            lbl_v.setStyleSheet("color: #728499; font-size: 11px;")
            col.addWidget(lbl_v)
        col.addStretch(1)
        row.addLayout(col, 1)

        if item.thumbnail_url:
            thumb_loader.load(item.thumbnail_url, lbl_thumb, self.THUMB_SIZE)

    def _set_highlight(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "QFrame { background: #19312B; border: 1px solid #2E6456; border-radius: 9px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame { background: transparent; border: 1px solid transparent; border-radius: 9px; }"
                "QFrame:hover { background: #1A2433; border-color: #2A394D; }"
            )

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# =====================================================================
# ACCOUNT & PLAYLIST SYNC DIALOG (SAFE LOCAL PROFILE + OPTIONAL COOKIE)
# =====================================================================

class _YouTubeAccountDialog(QDialog):
    """Manage Local YouTube Profile, Playlist URL Import, Takeout CSV & Read-Only Cookie Sync."""

    playlist_import_requested = Signal(str)

    def __init__(self, profile: YouTubeOnlineProfileStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle(tr_pair("Tài khoản YouTube & Đồng bộ Playlist", "YouTube Profile & Playlist Sync"))
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel(tr_pair("Hồ sơ YouTube Online cục bộ (An toàn 100%)", "Local YouTube Online Profile (100% Account-Safe)"))
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #EDF3FA;")
        root.addWidget(title)

        subs_n = len(profile.list_subscriptions())
        likes_n = len(profile.list_liked())
        pls_n = len(profile.list_playlists())
        hist_n = len(profile.list_watch_history())
        lbl_stats = QLabel(
            tr_pair(
                f"Đã lưu cục bộ trên máy: {subs_n} kênh đăng ký · {pls_n} playlist · {likes_n} đã thích · {hist_n} lịch sử.\n"
                "Mọi thao tác Đăng ký / Thích / Lưu Playlist hoạt động ngay tại BoTube, không gửi ghi tự động lên Google nên không lo khóa tài khoản.",
                f"Stored safely on your PC: {subs_n} subscriptions · {pls_n} playlists · {likes_n} liked · {hist_n} history.\n"
                "Subscriptions, likes, and playlists stay 100% local with zero automated Google write requests.",
            )
        )
        lbl_stats.setWordWrap(True)
        lbl_stats.setStyleSheet("color: #9AAABC; font-size: 12px;")
        root.addWidget(lbl_stats)

        # 1. Import any YouTube Playlist URL
        box_pl = QFrame()
        box_pl.setStyleSheet("background: #151C26; border: 1px solid #273445; border-radius: 10px;")
        pl_lay = QVBoxLayout(box_pl)
        pl_lay.setContentsMargins(14, 12, 14, 12)
        pl_lay.setSpacing(8)
        lbl_pl = QLabel(tr_pair("Nhập trực tiếp Playlist từ YouTube / YouTube Music", "Import Playlist from YouTube / YouTube Music"))
        lbl_pl.setStyleSheet("font-weight: 600; color: #A9F1D9; font-size: 13px;")
        pl_lay.addWidget(lbl_pl)

        pl_row = QHBoxLayout()
        self.txt_pl_url = QLineEdit()
        self.txt_pl_url.setPlaceholderText("https://www.youtube.com/playlist?list=... / :ytfav")
        btn_imp_pl = QPushButton(tr_pair("Nhập Playlist", "Import Playlist"))
        btn_imp_pl.setProperty("role", "primary")
        btn_imp_pl.clicked.connect(self._on_import_playlist)
        pl_row.addWidget(self.txt_pl_url, 1)
        pl_row.addWidget(btn_imp_pl)
        pl_lay.addLayout(pl_row)
        root.addWidget(box_pl)

        # 2. Import Google Takeout subscriptions.csv
        box_csv = QFrame()
        box_csv.setStyleSheet("background: #151C26; border: 1px solid #273445; border-radius: 10px;")
        csv_lay = QHBoxLayout(box_csv)
        csv_lay.setContentsMargins(14, 12, 14, 12)
        lbl_csv = QLabel(tr_pair("Nhập danh sách Kênh đăng ký (Google Takeout CSV)", "Import Subscribed Channels (Google Takeout CSV)"))
        lbl_csv.setStyleSheet("color: #DCE6F2; font-size: 12px; font-weight: 600;")
        btn_csv = QPushButton(tr_pair("Chọn tệp .csv", "Choose .csv file"))
        btn_csv.clicked.connect(self._on_import_csv)
        csv_lay.addWidget(lbl_csv, 1)
        csv_lay.addWidget(btn_csv)
        root.addWidget(box_csv)

        # 3. Optional Read-Only Cookie Sync for Private / Liked Playlists
        box_ck = QFrame()
        box_ck.setStyleSheet("background: #151C26; border: 1px solid #273445; border-radius: 10px;")
        ck_lay = QVBoxLayout(box_ck)
        ck_lay.setContentsMargins(14, 12, 14, 12)
        ck_lay.setSpacing(8)
        lbl_ck = QLabel(tr_pair("Đồng bộ chỉ-đọc Playlist Riêng tư (Tùy chọn Cookie)", "Read-Only Private Playlist Sync (Optional Cookies)"))
        lbl_ck.setStyleSheet("font-weight: 600; color: #EDF3FA; font-size: 13px;")
        ck_lay.addWidget(lbl_ck)

        lbl_ck_note = QLabel(
            tr_pair(
                "Chỉ cần thiết nếu bạn muốn phát Playlist Riêng tư hoặc danh sách Đã thích từ tài khoản YouTube thật. Khuyên dùng Firefox hoặc tệp cookies.txt.",
                "Only needed if you want to play Private playlists or Liked Videos from your YouTube account. Firefox or cookies.txt recommended.",
            )
        )
        lbl_ck_note.setWordWrap(True)
        lbl_ck_note.setStyleSheet("color: #8EA0B5; font-size: 11px;")
        ck_lay.addWidget(lbl_ck_note)

        row_br = QHBoxLayout()
        row_br.addWidget(QLabel(tr_pair("Trình duyệt:", "Browser:")))
        self.combo_browser = QComboBox()
        self.combo_browser.setProperty("_i18n_safe_combo", True)
        for val, vi_l, en_l in (
            ("", "Không dùng (Mặc định an toàn)", "None (Default Safe)"),
            ("firefox", "Firefox", "Firefox"),
            ("edge", "Microsoft Edge", "Microsoft Edge"),
            ("chrome", "Google Chrome", "Google Chrome"),
            ("brave", "Brave", "Brave"),
        ):
            self.combo_browser.addItem(tr_pair(vi_l, en_l), val)
        cur_br = str(profile.get_pref("cookies_browser", "") or "")
        idx_br = self.combo_browser.findData(cur_br)
        if idx_br >= 0:
            self.combo_browser.setCurrentIndex(idx_br)
        row_br.addWidget(self.combo_browser, 1)
        ck_lay.addLayout(row_br)

        row_cf = QHBoxLayout()
        self.txt_cookie_file = QLineEdit(str(profile.get_pref("cookies_file", "") or ""))
        self.txt_cookie_file.setPlaceholderText(tr_pair("Hoặc chọn đường dẫn cookies.txt (ưu tiên cao hơn)...", "Or choose cookies.txt file (takes priority)..."))
        btn_cf = QPushButton(tr_pair("Chọn file", "Browse"))
        btn_cf.clicked.connect(self._browse_cookie_file)
        btn_cf_clear = QPushButton(tr_pair("Xóa", "Clear"))
        btn_cf_clear.clicked.connect(lambda: self.txt_cookie_file.setText(""))
        row_cf.addWidget(self.txt_cookie_file, 1)
        row_cf.addWidget(btn_cf)
        row_cf.addWidget(btn_cf_clear)
        ck_lay.addLayout(row_cf)
        root.addWidget(box_ck)

        # Footer Save / Close
        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_close = QPushButton(tr_pair("Đóng", "Close"))
        btn_close.clicked.connect(self.reject)
        btn_save = QPushButton(tr_pair("Lưu cấu hình", "Save Settings"))
        btn_save.setProperty("role", "primary")
        btn_save.clicked.connect(self._on_save)
        foot.addWidget(btn_close)
        foot.addWidget(btn_save)
        root.addLayout(foot)

    def _on_import_playlist(self) -> None:
        url = self.txt_pl_url.text().strip()
        if not url:
            return
        self.playlist_import_requested.emit(url)
        self.accept()

    def _on_import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr_pair("Chọn tệp subscriptions.csv", "Select subscriptions.csv"),
            "",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        added = self.profile.import_subscriptions_csv(path)
        QMessageBox.information(
            self,
            "YouTube Online",
            tr_pair(f"Đã nhập thành công {added} kênh đăng ký mới!", f"Successfully imported {added} new channel subscriptions!"),
        )

    def _browse_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr_pair("Chọn tệp cookies.txt", "Select cookies.txt"),
            "",
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            self.txt_cookie_file.setText(path)

    def _on_save(self) -> None:
        self.profile.set_pref("cookies_browser", str(self.combo_browser.currentData() or ""))
        self.profile.set_pref("cookies_file", self.txt_cookie_file.text().strip())
        self.accept()


# =====================================================================
# MAIN COMMERCIAL YOUTUBE ONLINE STUDIO PAGE
# =====================================================================

class YouTubeOnlinePage(QWidget):
    """Isolated YouTube Desktop Studio tab (zero mutations to BoTube's offline architecture)."""

    playback_starting = Signal()
    download_requested = Signal(str, str)  # (youtube_url, title)
    status_message = Signal(str)

    VIEW_HOME = 0
    VIEW_WATCH = 1
    VIEW_CHANNEL = 2
    VIEW_PLAYLIST = 3
    VIEW_LIBRARY = 4

    def __init__(
        self,
        *,
        profile_provider: Callable[[], AudioProfile] | None = None,
        profile_store: YouTubeOnlineProfileStore | None = None,
        client: YouTubeOnlineClient | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("youtubeOnlineRoot")
        self.setStyleSheet(YOUTUBE_PAGE_STYLE)

        self.profile = profile_store or YouTubeOnlineProfileStore()
        self.client = client or YouTubeOnlineClient(profile_store=self.profile)
        self._thumbs = _OnlineThumbnailLoader(self)

        # Navigation & State
        self._initialized_feed = False
        self._nav_history: list[dict[str, Any]] = []
        self._nav_index = -1
        self._current_topic = "all"
        self._current_search_query = ""
        self._current_search_filter = "all"
        self._grid_items: list[OnlineVideoItem] = []

        # Watch & Queue State
        self._current_item: OnlineVideoItem | None = None
        self._current_watch: OnlineWatchInfo | None = None
        self._current_stream: ResolvedStream | None = None
        self._queue: list[OnlineVideoItem] = []
        self._queue_index = -1
        self._queue_title = ""
        self._shuffle_queue = False
        self._repeat_mode = False
        self._autoplay = bool(self.profile.get_pref("autoplay", True))
        self._preresolved_vid = ""
        self._desc_expanded = False
        self._cinema_mode = False
        self._is_fullscreen_stage = False
        self._last_seek_ms = 0
        self._user_dragging_seek = False
        self._active_channel: OnlineChannelInfo | None = None
        self._active_playlist_items: list[OnlineVideoItem] = []
        self._active_playlist_title = ""
        self._active_playlist_url = ""

        # Worker tracking with generation counters
        self._workers: dict[str, _TaskWorker] = {}
        self._gens: dict[str, int] = {}

        # Build UI
        self._build_ui()

        # Dedicated Playback Engine (100% isolated from offline player!)
        self.player = YouTubeOnlinePlaybackController(
            self.video_widget,
            profile_provider=profile_provider,
            parent=self,
        )
        self.player.set_volume(float(self.profile.get_pref("volume", 0.7) or 0.7))
        self.player.playback_starting.connect(self.playback_starting.emit)
        self.player.state_changed.connect(self._on_player_state_changed)
        self.player.position_changed.connect(self._on_player_position_changed)
        self.player.track_ended.connect(self._on_track_ended)
        self.player.subtitle_text_changed.connect(self._on_subtitle_text_changed)
        self.player.audio_status_changed.connect(self._on_audio_status_changed)
        self.player.buffering_changed.connect(self._on_buffering_changed)
        self.player.error_occurred.connect(self._on_player_error)

        # Debounced search autocomplete timer
        self._suggest_timer = QTimer(self)
        self._suggest_timer.setSingleShot(True)
        self._suggest_timer.setInterval(230)
        self._suggest_timer.timeout.connect(self._fetch_suggestions_async)

        # Debounced responsive grid relayout timer
        self._grid_resize_timer = QTimer(self)
        self._grid_resize_timer.setSingleShot(True)
        self._grid_resize_timer.setInterval(120)
        self._grid_resize_timer.timeout.connect(self._relayout_home_grid)

        # Restore saved UI preferences
        self._sync_pref_controls()

        # Register live VI/EN language updates
        register_language_listener(self.retranslate)
        self.retranslate(get_language())

    # =================================================================
    # UI CONSTRUCTION
    # =================================================================

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. TOP YOUTUBE BAR
        self.top_bar = QFrame()
        self.top_bar.setObjectName("ytTopBar")
        self.top_bar.setFixedHeight(58)
        top_lay = QHBoxLayout(self.top_bar)
        top_lay.setContentsMargins(14, 8, 14, 8)
        top_lay.setSpacing(8)

        self.btn_back = QPushButton()
        self.btn_back.setFixedSize(34, 34)
        self.btn_back.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_back, "arrow-left", "Back", color=TEXT, size=18)
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self._go_back)

        self.btn_forward = QPushButton()
        self.btn_forward.setFixedSize(34, 34)
        self.btn_forward.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_forward.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_forward, "arrow-right", "Forward", color=TEXT, size=18)
        self.btn_forward.setEnabled(False)
        self.btn_forward.clicked.connect(self._go_forward)

        self.btn_refresh = QPushButton()
        self.btn_refresh.setFixedSize(34, 34)
        self.btn_refresh.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_refresh, "refresh-cw", "Refresh", color=TEXT, size=16)
        self.btn_refresh.clicked.connect(self._refresh_current_view)

        brand = QLabel("YouTube")
        brand.setStyleSheet(
            "color: #EDF3FA; font-size: 16px; font-weight: 800; padding: 0 4px;"
        )
        badge_pro = QLabel("HI-FI")
        badge_pro.setStyleSheet(
            "background: #FF4E45; color: #FFFFFF; border-radius: 5px; "
            "padding: 2px 6px; font-size: 10px; font-weight: 800;"
        )

        # Search pill
        self.search_input = QLineEdit()
        self.search_input.setObjectName("ytSearchInput")
        self.search_input.setFixedHeight(38)
        self.search_input.setMinimumWidth(240)
        self.search_input.setMaximumWidth(560)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._on_search_submitted)
        self.search_input.textEdited.connect(self._on_search_text_edited)
        self.search_input.installEventFilter(self)

        self.btn_search = QPushButton()
        self.btn_search.setFixedSize(38, 38)
        self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.setStyleSheet(
            "QPushButton { background: #1C2636; border: 1px solid #2E3E54; border-radius: 19px; }"
            "QPushButton:hover { background: #263449; border-color: #77E0BE; }"
        )
        button_icon(self.btn_search, "search", "Search", color=TEXT, size=16)
        self.btn_search.clicked.connect(self._on_search_submitted)

        # Quick Audio-Only toggle pill
        self.btn_audio_mode = QPushButton()
        self.btn_audio_mode.setObjectName("ytAudioToggle")
        self.btn_audio_mode.setCheckable(True)
        self.btn_audio_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_audio_mode.toggled.connect(self._on_audio_only_toggled)

        # Account & Sync button
        self.btn_account = QPushButton()
        self.btn_account.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_account.setStyleSheet(
            "QPushButton { background: #192433; color: #EDF3FA; border: 1px solid #2C3D54; "
            "border-radius: 16px; padding: 5px 12px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #233247; border-color: #77E0BE; }"
        )
        self.btn_account.clicked.connect(self._open_account_dialog)

        top_lay.addWidget(self.btn_back)
        top_lay.addWidget(self.btn_forward)
        top_lay.addWidget(self.btn_refresh)
        top_lay.addWidget(brand)
        top_lay.addWidget(badge_pro)
        top_lay.addSpacing(8)
        top_lay.addWidget(self.search_input, 1)
        top_lay.addWidget(self.btn_search)
        top_lay.addSpacing(8)
        top_lay.addWidget(self.btn_audio_mode)
        top_lay.addWidget(self.btn_account)
        root.addWidget(self.top_bar)

        # 2. SUB-NAV BAR (Home | Music | Subscriptions | Online Library | Now Watching)
        self.sub_nav = QFrame()
        self.sub_nav.setObjectName("ytSubNav")
        self.sub_nav.setFixedHeight(44)
        snav_lay = QHBoxLayout(self.sub_nav)
        snav_lay.setContentsMargins(16, 4, 16, 4)
        snav_lay.setSpacing(6)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key in ("home", "music", "subscriptions", "library", "watch"):
            btn = QPushButton()
            btn.setProperty("ytNavTab", True)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, k=key: self._on_subnav_clicked(k))
            self.nav_buttons[key] = btn
            snav_lay.addWidget(btn)
        self.nav_buttons["watch"].hide()
        snav_lay.addStretch(1)

        self.lbl_busy = QLabel("")
        self.lbl_busy.setStyleSheet("color: #77E0BE; font-size: 12px; font-weight: 600;")
        snav_lay.addWidget(self.lbl_busy)
        root.addWidget(self.sub_nav)

        # 3. MAIN VIEW STACK
        self.stack = QStackedWidget()
        self._build_home_view()       # index 0
        self._build_watch_view()      # index 1
        self._build_channel_view()    # index 2
        self._build_playlist_view()   # index 3
        self._build_library_view()    # index 4
        root.addWidget(self.stack, 1)

        # 4. PERSISTENT IN-TAB MINI PLAYER BAR (when browsing while audio/video plays)
        self._build_mini_bar()
        root.addWidget(self.mini_bar)

        # 5. FLOATING AUTOCOMPLETE POPUP
        self.suggest_popup = QListWidget(self)
        self.suggest_popup.setObjectName("ytSuggestPopup")
        self.suggest_popup.setWindowFlags(Qt.WindowType.SubWindow)
        self.suggest_popup.hide()
        self.suggest_popup.itemClicked.connect(self._on_suggestion_clicked)

    def _build_home_view(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        # Topic Chips / Search Filter Row
        self.chips_scroll = QScrollArea()
        self.chips_scroll.setFixedHeight(42)
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_scroll.setStyleSheet("background: transparent; border: none;")

        chips_host = QWidget()
        self.chips_layout = QHBoxLayout(chips_host)
        self.chips_layout.setContentsMargins(0, 2, 0, 2)
        self.chips_layout.setSpacing(8)
        self.topic_buttons: dict[str, QPushButton] = {}
        for key, vi_lbl, _en_lbl, _q in TOPIC_CHIPS:
            btn = QPushButton(vi_lbl)
            btn.setProperty("ytChip", True)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self._select_topic(k))
            self.topic_buttons[key] = btn
            self.chips_layout.addWidget(btn)
        self.chips_layout.addStretch(1)
        self.chips_scroll.setWidget(chips_host)
        lay.addWidget(self.chips_scroll)

        # Search filter bar (shown only during active search)
        self.search_filter_bar = QWidget()
        sf_lay = QHBoxLayout(self.search_filter_bar)
        sf_lay.setContentsMargins(0, 0, 0, 0)
        sf_lay.setSpacing(8)
        self.lbl_search_heading = QLabel("")
        self.lbl_search_heading.setStyleSheet("font-size: 14px; font-weight: 700; color: #EDF3FA;")
        sf_lay.addWidget(self.lbl_search_heading)
        sf_lay.addSpacing(8)
        self.filter_buttons: dict[str, QPushButton] = {}
        for fkey in ("all", "videos", "playlists", "channels", "live"):
            fb = QPushButton()
            fb.setProperty("ytChip", True)
            fb.setCheckable(True)
            fb.setChecked(fkey == "all")
            fb.setCursor(Qt.CursorShape.PointingHandCursor)
            fb.clicked.connect(lambda _c=False, k=fkey: self._select_search_filter(k))
            self.filter_buttons[fkey] = fb
            sf_lay.addWidget(fb)
        sf_lay.addStretch(1)
        self.search_filter_bar.hide()
        lay.addWidget(self.search_filter_bar)

        # Responsive 16:9 Grid Scroll Area
        self.home_scroll = QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setStyleSheet("background: transparent; border: none;")
        self.home_grid_host = QWidget()
        self.home_grid = QGridLayout(self.home_grid_host)
        self.home_grid.setContentsMargins(2, 4, 2, 16)
        self.home_grid.setHorizontalSpacing(14)
        self.home_grid.setVerticalSpacing(16)
        self.home_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.home_scroll.setWidget(self.home_grid_host)
        lay.addWidget(self.home_scroll, 1)

        self.stack.addWidget(page)

    def _build_watch_view(self) -> None:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(14)

        # LEFT COLUMN (Scrollable Watch Stage + Controls + Metadata + Description + Comments)
        self.watch_left_scroll = QScrollArea()
        self.watch_left_scroll.setWidgetResizable(True)
        self.watch_left_scroll.setStyleSheet("background: transparent; border: none;")
        left_host = QWidget()
        left_lay = QVBoxLayout(left_host)
        left_lay.setContentsMargins(0, 0, 4, 24)
        left_lay.setSpacing(10)

        # 16:9 Stage (Video + Audio-Only Art + Floating Subtitle Overlay + Buffering Pill)
        self.stage_frame = QFrame()
        self.stage_frame.setMinimumHeight(340)
        self.stage_frame.setMaximumHeight(540)
        self.stage_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.stage_frame.setStyleSheet("background: #070A0F; border-radius: 12px; border: 1px solid #1E2938;")
        stage_grid = QGridLayout(self.stage_frame)
        stage_grid.setContentsMargins(0, 0, 0, 0)

        self.stage_stack = QStackedWidget()
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background: #000000;")
        self.stage_stack.addWidget(self.video_widget)

        # Audio-Only Hi-Fi Cover Art Stage
        audio_stage = QWidget()
        audio_stage.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0E1826, stop:1 #102422); border-radius: 12px;")
        as_lay = QVBoxLayout(audio_stage)
        as_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        as_lay.setSpacing(10)
        self.lbl_audio_art = QLabel()
        self.lbl_audio_art.setFixedSize(260, 146)
        self.lbl_audio_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_audio_art.setStyleSheet("background: #131D2B; border: 1px solid #2A3F54; border-radius: 12px;")
        self.lbl_audio_title = QLabel("")
        self.lbl_audio_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_audio_title.setWordWrap(True)
        self.lbl_audio_title.setStyleSheet("color: #EDF3FA; font-size: 16px; font-weight: 700; padding: 0 24px;")
        self.lbl_audio_artist = QLabel("")
        self.lbl_audio_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_audio_artist.setStyleSheet("color: #8DE7CA; font-size: 13px; font-weight: 600;")
        as_lay.addWidget(self.lbl_audio_art, alignment=Qt.AlignmentFlag.AlignHCenter)
        as_lay.addWidget(self.lbl_audio_title)
        as_lay.addWidget(self.lbl_audio_artist)
        self.stage_stack.addWidget(audio_stage)

        stage_grid.addWidget(self.stage_stack, 0, 0)

        # Buffering indicator pill (top-left)
        self.lbl_buffering = QLabel("")
        self.lbl_buffering.setStyleSheet(
            "background: rgba(13, 17, 24, 220); color: #77E0BE; border: 1px solid #2E6456; "
            "border-radius: 8px; padding: 5px 12px; font-size: 12px; font-weight: 600; margin: 12px;"
        )
        self.lbl_buffering.hide()
        stage_grid.addWidget(self.lbl_buffering, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Floating Subtitle / CC Overlay (bottom-center — hidden whenever Sub is Off or empty!)
        self.lbl_sub_overlay = QLabel("")
        self.lbl_sub_overlay.setWordWrap(True)
        self.lbl_sub_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_sub_overlay.setStyleSheet(
            "background: rgba(8, 12, 18, 215); color: #FFFFFF; border-radius: 8px; "
            "padding: 7px 16px; font-size: 17px; font-weight: 700; margin-bottom: 16px;"
        )
        self.lbl_sub_overlay.hide()
        stage_grid.addWidget(self.lbl_sub_overlay, 0, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        left_lay.addWidget(self.stage_frame)

        # Commercial Player Controls Bar
        ctrl_box = QFrame()
        ctrl_box.setObjectName("ytWatchControls")
        ctrl_lay = QVBoxLayout(ctrl_box)
        ctrl_lay.setContentsMargins(12, 8, 12, 10)
        ctrl_lay.setSpacing(6)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)
        self.lbl_pos_time = QLabel("0:00")
        self.lbl_pos_time.setStyleSheet("color: #DCE6F2; font-size: 12px; font-family: Consolas;")
        self.seek_slider = _ClickSeekSlider()
        self.seek_slider.setRange(0, 0)
        self.seek_slider.seek_requested.connect(self._on_seek_requested)
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, "_user_dragging_seek", True))
        self.seek_slider.sliderReleased.connect(self._on_seek_slider_released)
        self.lbl_dur_time = QLabel("0:00")
        self.lbl_dur_time.setStyleSheet("color: #9AAABC; font-size: 12px; font-family: Consolas;")
        seek_row.addWidget(self.lbl_pos_time)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.lbl_dur_time)
        ctrl_lay.addLayout(seek_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_prev = QPushButton()
        self.btn_prev.setFixedSize(34, 34)
        self.btn_prev.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_prev, "skip-back", "Previous", color=TEXT, size=17)
        self.btn_prev.clicked.connect(self.play_previous)

        self.btn_play = QPushButton()
        self.btn_play.setObjectName("ytPlayCircle")
        self.btn_play.setFixedSize(38, 38)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_play, "play", "Play / Pause", color=INK, size=18)
        self.btn_play.clicked.connect(self.toggle_play_pause)

        self.btn_next = QPushButton()
        self.btn_next.setFixedSize(34, 34)
        self.btn_next.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_next, "skip-forward", "Next", color=TEXT, size=17)
        self.btn_next.clicked.connect(self.play_next)

        self.btn_mute = QPushButton()
        self.btn_mute.setFixedSize(32, 32)
        self.btn_mute.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_mute, "volume-2", "Mute", color=TEXT, size=16)
        self.btn_mute.clicked.connect(self._toggle_mute)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(round(float(self.profile.get_pref("volume", 0.7) or 0.7) * 100)))
        self.vol_slider.setFixedWidth(82)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)

        # 3-Mode Subtitle Selector + CC Language Picker
        self.combo_sub_mode = QComboBox()
        self.combo_sub_mode.setProperty("ytCompact", True)
        self.combo_sub_mode.setProperty("_i18n_safe_combo", True)
        self.combo_sub_mode.addItem("Sub: Tắt", "off")
        self.combo_sub_mode.addItem("Sub: YouTube CC", "youtube_cc")
        self.combo_sub_mode.addItem("AI Sub (Tải về)", "ai_handoff")
        self.combo_sub_mode.currentIndexChanged.connect(self._on_sub_mode_changed)

        self.combo_sub_lang = QComboBox()
        self.combo_sub_lang.setProperty("ytCompact", True)
        self.combo_sub_lang.setProperty("_i18n_skip_combo", True)
        self.combo_sub_lang.setMaximumWidth(140)
        self.combo_sub_lang.hide()
        self.combo_sub_lang.currentIndexChanged.connect(self._on_sub_lang_changed)

        # Quality Selector (Audio Hi-Fi + 4K/2K/1080p/720p/480p/360p)
        self.combo_quality = QComboBox()
        self.combo_quality.setProperty("ytCompact", True)
        self.combo_quality.setProperty("_i18n_safe_combo", True)
        self.combo_quality.addItem("Audio Hi-Fi", "audio_only")
        self.combo_quality.addItem("1080p HD", "1080p")
        self.combo_quality.addItem("720p HD", "720p")
        self.combo_quality.currentIndexChanged.connect(self._on_quality_changed)

        # Speed Selector
        self.combo_speed = QComboBox()
        self.combo_speed.setProperty("ytCompact", True)
        self.combo_speed.setProperty("_i18n_skip_combo", True)
        for sp in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
            self.combo_speed.addItem(f"{sp:g}x", sp)
        self.combo_speed.setCurrentIndex(2)
        self.combo_speed.currentIndexChanged.connect(self._on_speed_changed)

        self.btn_cinema = QPushButton()
        self.btn_cinema.setFixedSize(32, 32)
        self.btn_cinema.setCheckable(True)
        self.btn_cinema.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_cinema.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_cinema, "tv", "Cinema Mode", color=TEXT, size=16)
        self.btn_cinema.toggled.connect(self._toggle_cinema_mode)

        self.btn_fs = QPushButton()
        self.btn_fs.setFixedSize(32, 32)
        self.btn_fs.setStyleSheet(ICON_BUTTON_STYLE)
        self.btn_fs.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_fs, "maximize", "Fullscreen", color=TEXT, size=16)
        self.btn_fs.clicked.connect(self._toggle_fullscreen_stage)

        btn_row.addWidget(self.btn_prev)
        btn_row.addWidget(self.btn_play)
        btn_row.addWidget(self.btn_next)
        btn_row.addSpacing(4)
        btn_row.addWidget(self.btn_mute)
        btn_row.addWidget(self.vol_slider)
        btn_row.addStretch(1)
        btn_row.addWidget(self.combo_sub_mode)
        btn_row.addWidget(self.combo_sub_lang)
        btn_row.addWidget(self.combo_quality)
        btn_row.addWidget(self.combo_speed)
        btn_row.addWidget(self.btn_cinema)
        btn_row.addWidget(self.btn_fs)
        ctrl_lay.addLayout(btn_row)
        left_lay.addWidget(ctrl_box)

        # Title + Active Hi-Fi Audio Status Badge
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.lbl_watch_title = QLabel("")
        self.lbl_watch_title.setWordWrap(True)
        self.lbl_watch_title.setStyleSheet("color: #EDF3FA; font-size: 18px; font-weight: 700;")
        self.lbl_audio_badge = QLabel("Hi-Fi 64-bit · Ready")
        self.lbl_audio_badge.setObjectName("ytAudioBadge")
        self.lbl_audio_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        title_row.addWidget(self.lbl_watch_title, 1)
        title_row.addWidget(self.lbl_audio_badge, 0, Qt.AlignmentFlag.AlignTop)
        left_lay.addLayout(title_row)

        # Channel Row + Action Pills (Subscribe, Like, Save Playlist, 1-Click Download, Copy Link)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.lbl_ch_avatar = QLabel()
        self.lbl_ch_avatar.setFixedSize(40, 40)
        self.lbl_ch_avatar.setStyleSheet("background: #1B2534; border-radius: 20px; border: 1px solid #2E3F55;")
        action_row.addWidget(self.lbl_ch_avatar)

        ch_col = QVBoxLayout()
        ch_col.setSpacing(1)
        self.btn_watch_channel = QPushButton("")
        self.btn_watch_channel.setFlat(True)
        self.btn_watch_channel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_watch_channel.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #EDF3FA; "
            "font-size: 14px; font-weight: 700; text-align: left; padding: 0; }"
            "QPushButton:hover { color: #77E0BE; }"
        )
        self.btn_watch_channel.clicked.connect(self._open_current_channel)
        self.lbl_watch_subs = QLabel("")
        self.lbl_watch_subs.setStyleSheet("color: #8EA0B5; font-size: 11px;")
        ch_col.addWidget(self.btn_watch_channel)
        ch_col.addWidget(self.lbl_watch_subs)
        action_row.addLayout(ch_col)

        self.btn_subscribe = QPushButton()
        self.btn_subscribe.setObjectName("ytSubscribeBtn")
        self.btn_subscribe.setCheckable(True)
        self.btn_subscribe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_subscribe.clicked.connect(self._toggle_subscribe_current)
        action_row.addWidget(self.btn_subscribe)
        action_row.addStretch(1)

        self.btn_like = QPushButton()
        self.btn_like.setCheckable(True)
        self.btn_like.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_like.clicked.connect(self._toggle_like_current)

        self.btn_save_pl = QPushButton()
        self.btn_save_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_pl.clicked.connect(self._open_save_playlist_menu)

        self.btn_dl_video = QPushButton()
        self.btn_dl_video.setProperty("role", "primary")
        self.btn_dl_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dl_video.clicked.connect(self._download_current_video)

        self.btn_copy_link = QPushButton()
        self.btn_copy_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_link.clicked.connect(self._copy_current_link)

        for b in (self.btn_like, self.btn_save_pl, self.btn_dl_video, self.btn_copy_link):
            action_row.addWidget(b)
        left_lay.addLayout(action_row)

        # Chapters Strip (hidden when video has no chapters)
        self.chapters_wrap = QFrame()
        self.chapters_wrap.setObjectName("ytPanel")
        ch_lay = QVBoxLayout(self.chapters_wrap)
        ch_lay.setContentsMargins(12, 8, 12, 8)
        ch_lay.setSpacing(6)
        self.lbl_chapters_hdr = QLabel()
        self.lbl_chapters_hdr.setStyleSheet("color: #A9F1D9; font-size: 12px; font-weight: 700;")
        ch_lay.addWidget(self.lbl_chapters_hdr)
        self.chapters_scroll = QScrollArea()
        self.chapters_scroll.setFixedHeight(36)
        self.chapters_scroll.setWidgetResizable(True)
        self.chapters_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chapters_scroll.setStyleSheet("background: transparent; border: none;")
        self.chapters_row_host = QWidget()
        self.chapters_row = QHBoxLayout(self.chapters_row_host)
        self.chapters_row.setContentsMargins(0, 0, 0, 0)
        self.chapters_row.setSpacing(6)
        self.chapters_scroll.setWidget(self.chapters_row_host)
        ch_lay.addWidget(self.chapters_scroll)
        self.chapters_wrap.hide()
        left_lay.addWidget(self.chapters_wrap)

        # Collapsible Description Box with Clickable Timestamps
        self.desc_box = QFrame()
        self.desc_box.setObjectName("ytPanel")
        desc_lay = QVBoxLayout(self.desc_box)
        desc_lay.setContentsMargins(14, 10, 14, 10)
        desc_lay.setSpacing(6)
        self.lbl_watch_stats = QLabel("")
        self.lbl_watch_stats.setStyleSheet("color: #DCE6F2; font-size: 12px; font-weight: 700;")
        self.desc_browser = QTextBrowser()
        self.desc_browser.setOpenLinks(False)
        self.desc_browser.anchorClicked.connect(self._on_desc_link_clicked)
        self.desc_browser.setMaximumHeight(84)
        self.desc_browser.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; color: #BAC8D8; font-size: 12px; }"
        )
        self.btn_toggle_desc = QPushButton()
        self.btn_toggle_desc.setFlat(True)
        self.btn_toggle_desc.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_desc.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #77E0BE; font-size: 12px; font-weight: 600; text-align: left; padding: 0; }"
        )
        self.btn_toggle_desc.clicked.connect(self._toggle_description)
        desc_lay.addWidget(self.lbl_watch_stats)
        desc_lay.addWidget(self.desc_browser)
        desc_lay.addWidget(self.btn_toggle_desc)
        left_lay.addWidget(self.desc_box)

        # Comments Section (Lazy-loaded Top Comments)
        self.comments_box = QFrame()
        self.comments_box.setObjectName("ytPanel")
        c_lay = QVBoxLayout(self.comments_box)
        c_lay.setContentsMargins(14, 12, 14, 12)
        c_lay.setSpacing(10)
        c_hdr = QHBoxLayout()
        self.lbl_comments_hdr = QLabel()
        self.lbl_comments_hdr.setStyleSheet("color: #EDF3FA; font-size: 14px; font-weight: 700;")
        self.btn_load_comments = QPushButton()
        self.btn_load_comments.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load_comments.clicked.connect(self._load_comments_async)
        c_hdr.addWidget(self.lbl_comments_hdr)
        c_hdr.addStretch(1)
        c_hdr.addWidget(self.btn_load_comments)
        c_lay.addLayout(c_hdr)
        self.comments_list_lay = QVBoxLayout()
        self.comments_list_lay.setSpacing(10)
        c_lay.addLayout(self.comments_list_lay)
        left_lay.addWidget(self.comments_box)
        left_lay.addStretch(1)

        self.watch_left_scroll.setWidget(left_host)
        outer.addWidget(self.watch_left_scroll, 7)

        # RIGHT COLUMN (Active Playlist / Mix Queue + Related Up Next Videos)
        self.watch_right_panel = QWidget()
        self.watch_right_panel.setMinimumWidth(320)
        self.watch_right_panel.setMaximumWidth(420)
        right_lay = QVBoxLayout(self.watch_right_panel)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(10)

        # Queue / Auto-Mix Panel
        self.queue_frame = QFrame()
        self.queue_frame.setObjectName("ytPanel")
        qf_lay = QVBoxLayout(self.queue_frame)
        qf_lay.setContentsMargins(10, 10, 10, 10)
        qf_lay.setSpacing(8)

        qh = QHBoxLayout()
        self.lbl_queue_title = QLabel()
        self.lbl_queue_title.setStyleSheet("color: #EDF3FA; font-size: 13px; font-weight: 700;")
        self.btn_autoplay = QPushButton()
        self.btn_autoplay.setProperty("ytChip", True)
        self.btn_autoplay.setCheckable(True)
        self.btn_autoplay.setChecked(self._autoplay)
        self.btn_autoplay.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_autoplay.toggled.connect(self._on_autoplay_toggled)
        qh.addWidget(self.lbl_queue_title, 1)
        qh.addWidget(self.btn_autoplay)
        qf_lay.addLayout(qh)

        q_ctrl = QHBoxLayout()
        q_ctrl.setSpacing(6)
        self.btn_q_shuffle = QPushButton()
        self.btn_q_shuffle.setCheckable(True)
        self.btn_q_shuffle.setFixedSize(30, 30)
        self.btn_q_shuffle.setStyleSheet(ICON_BUTTON_STYLE)
        button_icon(self.btn_q_shuffle, "shuffle", "Shuffle", color=MUTED, size=15)
        self.btn_q_shuffle.toggled.connect(self._on_shuffle_toggled)

        self.btn_q_repeat = QPushButton()
        self.btn_q_repeat.setCheckable(True)
        self.btn_q_repeat.setFixedSize(30, 30)
        self.btn_q_repeat.setStyleSheet(ICON_BUTTON_STYLE)
        button_icon(self.btn_q_repeat, "repeat", "Repeat", color=MUTED, size=15)
        self.btn_q_repeat.toggled.connect(self._on_repeat_toggled)

        self.btn_start_mix = QPushButton()
        self.btn_start_mix.setProperty("ytChip", True)
        self.btn_start_mix.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_mix.clicked.connect(self._start_radio_mix)

        q_ctrl.addWidget(self.btn_q_shuffle)
        q_ctrl.addWidget(self.btn_q_repeat)
        q_ctrl.addWidget(self.btn_start_mix)
        q_ctrl.addStretch(1)
        qf_lay.addLayout(q_ctrl)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setMaximumHeight(260)
        self.queue_scroll.setStyleSheet("background: transparent; border: none;")
        self.queue_host = QWidget()
        self.queue_lay = QVBoxLayout(self.queue_host)
        self.queue_lay.setContentsMargins(0, 0, 0, 0)
        self.queue_lay.setSpacing(4)
        self.queue_lay.addStretch(1)
        self.queue_scroll.setWidget(self.queue_host)
        qf_lay.addWidget(self.queue_scroll)
        right_lay.addWidget(self.queue_frame)

        # Related / Up Next Panel
        rel_frame = QFrame()
        rel_frame.setObjectName("ytPanel")
        rf_lay = QVBoxLayout(rel_frame)
        rf_lay.setContentsMargins(10, 10, 10, 10)
        rf_lay.setSpacing(8)
        self.lbl_related_hdr = QLabel()
        self.lbl_related_hdr.setStyleSheet("color: #EDF3FA; font-size: 13px; font-weight: 700;")
        rf_lay.addWidget(self.lbl_related_hdr)
        self.related_scroll = QScrollArea()
        self.related_scroll.setWidgetResizable(True)
        self.related_scroll.setStyleSheet("background: transparent; border: none;")
        self.related_host = QWidget()
        self.related_lay = QVBoxLayout(self.related_host)
        self.related_lay.setContentsMargins(0, 0, 0, 0)
        self.related_lay.setSpacing(6)
        self.related_lay.addStretch(1)
        self.related_scroll.setWidget(self.related_host)
        rf_lay.addWidget(self.related_scroll, 1)
        right_lay.addWidget(rel_frame, 1)

        outer.addWidget(self.watch_right_panel, 3)
        self.stack.addWidget(page)

    def _build_channel_view(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(12)

        hdr = QFrame()
        hdr.setObjectName("ytPanel")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(14)
        self.lbl_chan_page_avatar = QLabel()
        self.lbl_chan_page_avatar.setFixedSize(68, 68)
        self.lbl_chan_page_avatar.setStyleSheet("background: #1C2636; border-radius: 34px; border: 2px solid #354760;")
        hl.addWidget(self.lbl_chan_page_avatar)

        ch_info = QVBoxLayout()
        ch_info.setSpacing(4)
        self.lbl_chan_page_name = QLabel("")
        self.lbl_chan_page_name.setStyleSheet("color: #EDF3FA; font-size: 20px; font-weight: 700;")
        self.lbl_chan_page_meta = QLabel("")
        self.lbl_chan_page_meta.setStyleSheet("color: #9AAABC; font-size: 12px;")
        ch_info.addWidget(self.lbl_chan_page_name)
        ch_info.addWidget(self.lbl_chan_page_meta)
        hl.addLayout(ch_info, 1)

        self.btn_chan_page_sub = QPushButton()
        self.btn_chan_page_sub.setObjectName("ytSubscribeBtn")
        self.btn_chan_page_sub.setCheckable(True)
        self.btn_chan_page_sub.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_chan_page_sub.clicked.connect(self._toggle_subscribe_channel_page)
        hl.addWidget(self.btn_chan_page_sub)
        lay.addWidget(hdr)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        self.btn_chan_videos = QPushButton()
        self.btn_chan_videos.setProperty("ytChip", True)
        self.btn_chan_videos.setCheckable(True)
        self.btn_chan_videos.setChecked(True)
        self.btn_chan_videos.clicked.connect(lambda: self._switch_channel_tab("videos"))
        self.btn_chan_playlists = QPushButton()
        self.btn_chan_playlists.setProperty("ytChip", True)
        self.btn_chan_playlists.setCheckable(True)
        self.btn_chan_playlists.clicked.connect(lambda: self._switch_channel_tab("playlists"))
        tab_row.addWidget(self.btn_chan_videos)
        tab_row.addWidget(self.btn_chan_playlists)
        tab_row.addStretch(1)
        lay.addLayout(tab_row)

        self.channel_scroll = QScrollArea()
        self.channel_scroll.setWidgetResizable(True)
        self.channel_scroll.setStyleSheet("background: transparent; border: none;")
        self.channel_grid_host = QWidget()
        self.channel_grid = QGridLayout(self.channel_grid_host)
        self.channel_grid.setSpacing(14)
        self.channel_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.channel_scroll.setWidget(self.channel_grid_host)
        lay.addWidget(self.channel_scroll, 1)

        self.stack.addWidget(page)

    def _build_playlist_view(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(12)

        hdr = QFrame()
        hdr.setObjectName("ytPanel")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 14, 16, 14)
        hl.setSpacing(12)
        col = QVBoxLayout()
        self.lbl_pl_page_title = QLabel("")
        self.lbl_pl_page_title.setStyleSheet("color: #EDF3FA; font-size: 19px; font-weight: 700;")
        self.lbl_pl_page_meta = QLabel("")
        self.lbl_pl_page_meta.setStyleSheet("color: #9AAABC; font-size: 12px;")
        col.addWidget(self.lbl_pl_page_title)
        col.addWidget(self.lbl_pl_page_meta)
        hl.addLayout(col, 1)

        self.btn_pl_play_all = QPushButton()
        self.btn_pl_play_all.setProperty("role", "primary")
        self.btn_pl_play_all.clicked.connect(lambda: self._play_active_playlist(shuffle=False))
        self.btn_pl_shuffle = QPushButton()
        self.btn_pl_shuffle.clicked.connect(lambda: self._play_active_playlist(shuffle=True))
        self.btn_pl_pin = QPushButton()
        self.btn_pl_pin.clicked.connect(self._pin_active_playlist)
        for b in (self.btn_pl_play_all, self.btn_pl_shuffle, self.btn_pl_pin):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hl.addWidget(b)
        lay.addWidget(hdr)

        self.pl_scroll = QScrollArea()
        self.pl_scroll.setWidgetResizable(True)
        self.pl_scroll.setStyleSheet("background: transparent; border: none;")
        self.pl_list_host = QWidget()
        self.pl_list_lay = QVBoxLayout(self.pl_list_host)
        self.pl_list_lay.setSpacing(6)
        self.pl_list_lay.addStretch(1)
        self.pl_scroll.setWidget(self.pl_list_host)
        lay.addWidget(self.pl_scroll, 1)

        self.stack.addWidget(page)

    def _build_library_view(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.lib_tab_btns: dict[str, QPushButton] = {}
        for k in ("playlists", "liked", "history", "subscriptions"):
            b = QPushButton()
            b.setProperty("ytChip", True)
            b.setCheckable(True)
            b.setChecked(k == "playlists")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, key=k: self._render_library_section(key))
            self.lib_tab_btns[k] = b
            top.addWidget(b)
        top.addStretch(1)

        self.btn_lib_import_pl = QPushButton()
        self.btn_lib_import_pl.setProperty("role", "primary")
        self.btn_lib_import_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_import_pl.clicked.connect(self._prompt_import_playlist_url)
        self.btn_lib_new_pl = QPushButton()
        self.btn_lib_new_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_new_pl.clicked.connect(self._prompt_new_playlist)
        self.btn_lib_clear_hist = QPushButton()
        self.btn_lib_clear_hist.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_clear_hist.clicked.connect(self._clear_online_history)
        self.btn_lib_clear_hist.hide()

        top.addWidget(self.btn_lib_import_pl)
        top.addWidget(self.btn_lib_new_pl)
        top.addWidget(self.btn_lib_clear_hist)
        lay.addLayout(top)

        self.lib_scroll = QScrollArea()
        self.lib_scroll.setWidgetResizable(True)
        self.lib_scroll.setStyleSheet("background: transparent; border: none;")
        self.lib_host = QWidget()
        self.lib_lay = QVBoxLayout(self.lib_host)
        self.lib_lay.setSpacing(10)
        self.lib_lay.addStretch(1)
        self.lib_scroll.setWidget(self.lib_host)
        lay.addWidget(self.lib_scroll, 1)

        self.stack.addWidget(page)

    def _build_mini_bar(self) -> None:
        self.mini_bar = QFrame()
        self.mini_bar.setObjectName("ytMiniBar")
        self.mini_bar.setFixedHeight(62)
        lay = QHBoxLayout(self.mini_bar)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.setSpacing(10)

        self.lbl_mini_thumb = QLabel()
        self.lbl_mini_thumb.setFixedSize(76, 44)
        self.lbl_mini_thumb.setStyleSheet("background: #141C27; border-radius: 6px;")
        lay.addWidget(self.lbl_mini_thumb)

        info = QVBoxLayout()
        info.setSpacing(1)
        self.lbl_mini_title = QLabel("")
        self.lbl_mini_title.setStyleSheet("color: #EDF3FA; font-size: 13px; font-weight: 700;")
        self.lbl_mini_sub = QLabel("")
        self.lbl_mini_sub.setStyleSheet("color: #8DE7CA; font-size: 11px;")
        info.addWidget(self.lbl_mini_title)
        info.addWidget(self.lbl_mini_sub)
        lay.addLayout(info, 1)

        self.btn_mini_prev = QPushButton()
        self.btn_mini_prev.setFixedSize(32, 32)
        self.btn_mini_prev.setStyleSheet(ICON_BUTTON_STYLE)
        button_icon(self.btn_mini_prev, "skip-back", "Previous", color=TEXT, size=16)
        self.btn_mini_prev.clicked.connect(self.play_previous)

        self.btn_mini_play = QPushButton()
        self.btn_mini_play.setObjectName("ytPlayCircle")
        self.btn_mini_play.setFixedSize(36, 36)
        button_icon(self.btn_mini_play, "play", "Play/Pause", color=INK, size=17)
        self.btn_mini_play.clicked.connect(self.toggle_play_pause)

        self.btn_mini_next = QPushButton()
        self.btn_mini_next.setFixedSize(32, 32)
        self.btn_mini_next.setStyleSheet(ICON_BUTTON_STYLE)
        button_icon(self.btn_mini_next, "skip-forward", "Next", color=TEXT, size=16)
        self.btn_mini_next.clicked.connect(self.play_next)

        self.btn_mini_open = QPushButton()
        self.btn_mini_open.setProperty("role", "primary")
        self.btn_mini_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mini_open.clicked.connect(lambda: self._show_view(self.VIEW_WATCH))

        lay.addWidget(self.btn_mini_prev)
        lay.addWidget(self.btn_mini_play)
        lay.addWidget(self.btn_mini_next)
        lay.addWidget(self.btn_mini_open)
        self.mini_bar.hide()

    # =================================================================
    # BILINGUAL I18N (100% VI/EN COVERAGE)
    # =================================================================

    def retranslate(self, lang: str | None = None) -> None:
        lg = lang or get_language()
        self.search_input.setPlaceholderText(
            tr_pair("Tìm kiếm YouTube, bài hát, nghệ sĩ hoặc dán link video / playlist...", "Search YouTube, songs, artists, or paste video / playlist URL...", lg)
        )
        self.btn_audio_mode.setText(
            tr_pair("🎵 Chỉ nghe Nhạc", "🎵 Audio Only", lg)
            if self.btn_audio_mode.isChecked()
            else tr_pair("🎬 Video + Hi-Fi", "🎬 Video + Hi-Fi", lg)
        )
        self.btn_account.setText(tr_pair("👤 Tài khoản & Đồng bộ", "👤 Profile & Sync", lg))

        nav_labels = {
            "home": tr_pair("Trang chủ", "Home", lg),
            "music": tr_pair("Âm nhạc", "Music", lg),
            "subscriptions": tr_pair("Kênh đăng ký", "Subscriptions", lg),
            "library": tr_pair("Thư viện Online", "Online Library", lg),
            "watch": tr_pair("▶ Đang xem", "▶ Now Watching", lg),
        }
        for k, txt in nav_labels.items():
            self.nav_buttons[k].setText(txt)

        for key, vi_l, en_l, _q in TOPIC_CHIPS:
            if key in self.topic_buttons:
                self.topic_buttons[key].setText(tr_pair(vi_l, en_l, lg))

        flt_labels = {
            "all": tr_pair("Tất cả", "All", lg),
            "videos": tr_pair("Video", "Videos", lg),
            "playlists": tr_pair("Danh sách phát", "Playlists", lg),
            "channels": tr_pair("Kênh", "Channels", lg),
            "live": tr_pair("Trực tiếp", "Live", lg),
        }
        for k, txt in flt_labels.items():
            self.filter_buttons[k].setText(txt)

        # Watch controls
        self.combo_sub_mode.setItemText(0, tr_pair("Sub: Tắt", "Sub: Off", lg))
        self.combo_sub_mode.setItemText(1, tr_pair("Sub: YouTube CC", "Sub: YouTube CC", lg))
        self.combo_sub_mode.setItemText(2, tr_pair("AI Sub (Tải về)", "AI Sub (Download)", lg))
        self.btn_like.setText(
            tr_pair("❤️ Đã thích", "❤️ Liked", lg) if self.btn_like.isChecked() else tr_pair("🤍 Thích", "🤍 Like", lg)
        )
        self.btn_save_pl.setText(tr_pair("＋ Lưu Playlist", "＋ Save Playlist", lg))
        self.btn_dl_video.setText(tr_pair("⬇ Tải về BoTube", "⬇ Save to BoTube", lg))
        self.btn_copy_link.setText(tr_pair("📋 Sao chép link", "📋 Copy URL", lg))
        self._refresh_subscribe_button_text(lg)

        self.lbl_chapters_hdr.setText(tr_pair("Phân đoạn (Chapters)", "Chapters", lg))
        self.btn_toggle_desc.setText(
            tr_pair("Thu gọn mô tả", "Show less", lg) if self._desc_expanded else tr_pair("Xem thêm mô tả", "Show more", lg)
        )
        self.lbl_comments_hdr.setText(tr_pair("Bình luận nổi bật", "Top Comments", lg))
        self.btn_load_comments.setText(tr_pair("Tải bình luận", "Load Comments", lg))
        self.btn_autoplay.setText(tr_pair("Tự động phát", "Auto-Play", lg))
        self.btn_start_mix.setText(tr_pair("📻 Mix Radio", "📻 Radio Mix", lg))
        self.lbl_related_hdr.setText(tr_pair("Đề xuất tiếp theo", "Up Next", lg))
        self._update_queue_header_text(lg)

        # Channel, Playlist, Library, Mini-bar
        self.btn_chan_videos.setText(tr_pair("Video", "Videos", lg))
        self.btn_chan_playlists.setText(tr_pair("Danh sách phát", "Playlists", lg))
        self.btn_pl_play_all.setText(tr_pair("▶ Phát tất cả", "▶ Play All", lg))
        self.btn_pl_shuffle.setText(tr_pair("🔀 Trộn bài", "🔀 Shuffle", lg))
        self.btn_pl_pin.setText(tr_pair("📌 Lưu vào Thư viện Online", "📌 Pin to Online Library", lg))

        lib_labels = {
            "playlists": tr_pair("Danh sách phát", "Playlists", lg),
            "liked": tr_pair("Đã thích", "Liked Videos", lg),
            "history": tr_pair("Lịch sử xem", "Watch History", lg),
            "subscriptions": tr_pair("Kênh đăng ký", "Subscriptions", lg),
        }
        for k, txt in lib_labels.items():
            self.lib_tab_btns[k].setText(txt)
        self.btn_lib_import_pl.setText(tr_pair("＋ Nhập URL Playlist", "＋ Import Playlist URL", lg))
        self.btn_lib_new_pl.setText(tr_pair("＋ Tạo Playlist mới", "＋ New Playlist", lg))
        self.btn_lib_clear_hist.setText(tr_pair("🗑 Xóa lịch sử", "🗑 Clear History", lg))
        self.btn_mini_open.setText(tr_pair("Mở trình phát", "Open Player", lg))

    def _sync_pref_controls(self) -> None:
        audio_only = bool(self.profile.get_pref("audio_only", False))
        self.btn_audio_mode.blockSignals(True)
        self.btn_audio_mode.setChecked(audio_only)
        self.btn_audio_mode.blockSignals(False)
        self.stage_stack.setCurrentIndex(1 if audio_only else 0)

        sub_mode = str(self.profile.get_pref("subtitle_mode", "off") or "off")
        idx = self.combo_sub_mode.findData(sub_mode)
        if idx >= 0:
            self.combo_sub_mode.blockSignals(True)
            self.combo_sub_mode.setCurrentIndex(idx)
            self.combo_sub_mode.blockSignals(False)
        self.combo_sub_lang.setVisible(sub_mode == "youtube_cc")

    # =================================================================
    # LIFECYCLE & WORKER RUNNER
    # =================================================================

    def on_tab_activated(self) -> None:
        """Called lazily when user clicks the YouTube Online sidebar tab."""
        if not self._initialized_feed:
            self._initialized_feed = True
            self._show_view(self.VIEW_HOME, record_nav=True)
            QTimer.singleShot(80, self._deferred_initial_feed)

    def _deferred_initial_feed(self) -> None:
        if self.isVisible() and not self._grid_items and not self._current_search_query:
            self._load_home_feed("all")

    def _run_async(
        self,
        slot_name: str,
        fn: Callable[..., Any],
        on_ok: Callable[[Any], None],
        on_err: Callable[[str], None] | None = None,
        *,
        pass_processes: bool = False,
        busy_text: str = "",
    ) -> None:
        prev = self._workers.get(slot_name)
        if prev is not None:
            prev.cancel()
        gen = self._gens.get(slot_name, 0) + 1
        self._gens[slot_name] = gen
        if busy_text:
            self.lbl_busy.setText(busy_text)

        worker = _TaskWorker(gen, fn, pass_processes=pass_processes, parent=self)

        def _handle_ok(g: int, result: Any) -> None:
            if g != self._gens.get(slot_name):
                return
            self._workers.pop(slot_name, None)
            if busy_text and self.lbl_busy.text() == busy_text:
                self.lbl_busy.setText("")
            on_ok(result)

        def _handle_err(g: int, msg: str) -> None:
            if g != self._gens.get(slot_name):
                return
            self._workers.pop(slot_name, None)
            if busy_text and self.lbl_busy.text() == busy_text:
                self.lbl_busy.setText("")
            if on_err is not None:
                on_err(msg)
            else:
                self.status_message.emit(f"YouTube Online: {msg}")

        worker.finished_ok.connect(_handle_ok)
        worker.failed.connect(_handle_err)
        worker.finished.connect(worker.deleteLater)
        self._workers[slot_name] = worker
        worker.start()

    # =================================================================
    # NAVIGATION & SEARCH + AUTOCOMPLETE
    # =================================================================

    def _show_view(self, view_idx: int, *, record_nav: bool = False, nav_state: dict[str, Any] | None = None) -> None:
        self.stack.setCurrentIndex(view_idx)
        self.suggest_popup.hide()

        active_nav = {
            self.VIEW_HOME: "music" if (self._current_topic == "music" and not self._current_search_query) else "home",
            self.VIEW_WATCH: "watch",
            self.VIEW_CHANNEL: "subscriptions",
            self.VIEW_PLAYLIST: "library",
            self.VIEW_LIBRARY: "library",
        }.get(view_idx, "home")
        for k, b in self.nav_buttons.items():
            b.setChecked(k == active_nav)

        if record_nav:
            entry = nav_state or {"view": view_idx}
            self._nav_history = self._nav_history[: self._nav_index + 1]
            self._nav_history.append(entry)
            self._nav_index = len(self._nav_history) - 1
            self.btn_back.setEnabled(self._nav_index > 0)
            self.btn_forward.setEnabled(False)

        self._update_mini_bar_visibility()

    def _go_back(self) -> None:
        if self._nav_index <= 0:
            return
        self._nav_index -= 1
        self._restore_nav_entry(self._nav_history[self._nav_index])

    def _go_forward(self) -> None:
        if self._nav_index + 1 >= len(self._nav_history):
            return
        self._nav_index += 1
        self._restore_nav_entry(self._nav_history[self._nav_index])

    def _restore_nav_entry(self, entry: dict[str, Any]) -> None:
        self.btn_back.setEnabled(self._nav_index > 0)
        self.btn_forward.setEnabled(self._nav_index + 1 < len(self._nav_history))
        view = int(entry.get("view", self.VIEW_HOME))
        self._show_view(view, record_nav=False)

    def _on_subnav_clicked(self, key: str) -> None:
        if key == "home":
            self._current_search_query = ""
            self.search_filter_bar.hide()
            self.chips_scroll.show()
            self._select_topic("all")
        elif key == "music":
            self._current_search_query = ""
            self.search_filter_bar.hide()
            self.chips_scroll.show()
            self._select_topic("music")
        elif key == "subscriptions":
            self._show_view(self.VIEW_LIBRARY, record_nav=True)
            self._render_library_section("subscriptions")
        elif key == "library":
            self._show_view(self.VIEW_LIBRARY, record_nav=True)
            self._render_library_section("playlists")
        elif key == "watch":
            self._show_view(self.VIEW_WATCH, record_nav=True)

    def _refresh_current_view(self) -> None:
        idx = self.stack.currentIndex()
        if idx == self.VIEW_HOME:
            if self._current_search_query:
                self._perform_search(self._current_search_query, self._current_search_filter)
            else:
                self._load_home_feed(self._current_topic, force_refresh=True)
        elif idx == self.VIEW_WATCH and self._current_item is not None:
            self._start_watching_item(self._current_item, force_refresh_stream=True)
        elif idx == self.VIEW_CHANNEL and self._active_channel is not None:
            self.open_channel(self._active_channel.channel_id, self._active_channel.name)
        elif idx == self.VIEW_LIBRARY:
            active_lib = next((k for k, b in self.lib_tab_btns.items() if b.isChecked()), "playlists")
            self._render_library_section(active_lib)

    def _on_search_text_edited(self, text: str) -> None:
        q = text.strip()
        if not q:
            self.suggest_popup.hide()
            return
        if parse_youtube_input(q) is not None:
            self.suggest_popup.hide()
            return
        self._suggest_timer.start()

    def _fetch_suggestions_async(self) -> None:
        q = self.search_input.text().strip()
        if not q or parse_youtube_input(q) is not None:
            self.suggest_popup.hide()
            return
        lang = get_language()
        self._run_async(
            "suggest",
            lambda: self.client.fetch_suggestions(q, lang=lang),
            on_ok=lambda items: self._show_suggestions(q, items),
            on_err=lambda _m: None,
        )

    def _show_suggestions(self, query: str, suggestions: list[str]) -> None:
        if self.search_input.text().strip() != query or not self.search_input.hasFocus():
            self.suggest_popup.hide()
            return
        hist = [h for h in self.profile.list_search_history() if query.lower() in h.lower()][:3]
        merged: list[tuple[str, bool]] = []
        seen: set[str] = set()
        for h in hist:
            seen.add(h.lower())
            merged.append((h, True))
        for s in suggestions:
            if s.lower() not in seen:
                seen.add(s.lower())
                merged.append((s, False))
        if not merged:
            self.suggest_popup.hide()
            return
        self.suggest_popup.clear()
        for text, is_hist in merged[:10]:
            it = QListWidgetItem(("🕒  " if is_hist else "🔍  ") + text)
            it.setData(Qt.ItemDataRole.UserRole, text)
            self.suggest_popup.addItem(it)
        pos = self.search_input.mapTo(self, QPoint(0, self.search_input.height() + 4))
        self.suggest_popup.setGeometry(pos.x(), pos.y(), self.search_input.width(), min(320, len(merged) * 34 + 12))
        self.suggest_popup.raise_()
        self.suggest_popup.show()

    def _on_suggestion_clicked(self, item: QListWidgetItem) -> None:
        text = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        self.suggest_popup.hide()
        if text:
            self.search_input.setText(text)
            self._on_search_submitted()

    def _on_search_submitted(self) -> None:
        raw = self.search_input.text().strip()
        self.suggest_popup.hide()
        if not raw:
            return
        direct = parse_youtube_input(raw)
        if direct is not None:
            kind = direct.get("kind")
            if kind == "video":
                vid = direct["video_id"]
                item = OnlineVideoItem(
                    video_id=vid,
                    title=vid,
                    thumbnail_url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    playlist_id=direct.get("playlist_id", ""),
                )
                self.play_video_item(item)
                return
            if kind == "playlist":
                self.open_playlist(direct.get("url") or direct.get("playlist_id", ""))
                return
            if kind == "channel" and direct.get("channel_id"):
                self.open_channel(direct["channel_id"], "")
                return

        self.profile.record_search(raw)
        self._current_search_query = raw
        self._current_search_filter = "all"
        for k, b in self.filter_buttons.items():
            b.setChecked(k == "all")
        self._perform_search(raw, "all")

    def _select_search_filter(self, fkey: str) -> None:
        self._current_search_filter = fkey
        for k, b in self.filter_buttons.items():
            b.setChecked(k == fkey)
        if self._current_search_query:
            self._perform_search(self._current_search_query, fkey)

    def _perform_search(self, query: str, filter_key: str) -> None:
        self._show_view(self.VIEW_HOME, record_nav=True)
        self.chips_scroll.hide()
        self.search_filter_bar.show()
        self.lbl_search_heading.setText(tr_pair(f"Kết quả: “{query}”", f"Results: “{query}”"))
        lang = get_language()
        self._run_async(
            "feed",
            lambda: self.client.search(query, filter_key=filter_key, lang=lang),
            on_ok=self._populate_home_grid,
            on_err=self._on_feed_error,
            busy_text=tr_pair("Đang tìm kiếm YouTube…", "Searching YouTube…"),
        )

    # =================================================================
    # HOME / TOPIC DISCOVERY FEED
    # =================================================================

    def _select_topic(self, topic_key: str) -> None:
        self._current_topic = topic_key
        self._current_search_query = ""
        self.search_filter_bar.hide()
        self.chips_scroll.show()
        for k, b in self.topic_buttons.items():
            b.setChecked(k == topic_key)
        self._show_view(self.VIEW_HOME, record_nav=True)
        self._load_home_feed(topic_key)

    def _load_home_feed(self, topic_key: str, *, force_refresh: bool = False) -> None:
        lang = get_language()
        self._run_async(
            "feed",
            lambda: self.client.fetch_home_feed(topic_key, lang=lang, force_refresh=force_refresh),
            on_ok=self._populate_home_grid,
            on_err=self._on_feed_error,
            busy_text=tr_pair("Đang tải đề xuất YouTube…", "Loading YouTube feed…"),
        )

    def _on_feed_error(self, msg: str) -> None:
        self._clear_layout(self.home_grid)
        lbl = QLabel(tr_pair(f"Không thể kết nối YouTube: {msg}", f"Could not reach YouTube: {msg}"))
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #F09595; font-size: 13px; padding: 24px;")
        self.home_grid.addWidget(lbl, 0, 0)

    def _populate_home_grid(self, items: list[OnlineVideoItem]) -> None:
        self._grid_items = list(items or [])
        self._relayout_home_grid()

    def _relayout_home_grid(self) -> None:
        self._clear_layout(self.home_grid)
        if not self._grid_items:
            lbl = QLabel(tr_pair("Chưa có kết quả nào. Thử từ khóa khác hoặc bấm làm mới.", "No results yet. Try another query or click refresh."))
            lbl.setStyleSheet("color: #8EA0B5; font-size: 13px; padding: 24px;")
            self.home_grid.addWidget(lbl, 0, 0)
            return
        avail = max(320, self.home_scroll.viewport().width() - 16)
        cols = max(1, min(5, avail // 302))
        for idx, item in enumerate(self._grid_items):
            card = _OnlineVideoCard(item, self._thumbs)
            card.clicked.connect(self._on_card_clicked)
            card.channel_clicked.connect(self.open_channel)
            card.queue_clicked.connect(self._append_to_queue)
            card.download_clicked.connect(self._emit_download_item)
            self.home_grid.addWidget(card, idx // cols, idx % cols)

    def _on_card_clicked(self, item: OnlineVideoItem) -> None:
        if item.item_type == "playlist" and item.playlist_id:
            self.open_playlist(item.playlist_id, title_hint=item.title)
        elif item.item_type == "channel" and item.channel_id:
            self.open_channel(item.channel_id, item.channel_name or item.title)
        elif item.video_id:
            self.play_video_item(item)

    # =================================================================
    # WATCH PAGE & STREAM PLAYBACK
    # =================================================================

    def play_video_item(
        self,
        item: OnlineVideoItem,
        *,
        queue: list[OnlineVideoItem] | None = None,
        queue_index: int | None = None,
        queue_title: str = "",
    ) -> None:
        if not item or not item.video_id:
            return
        if queue is not None:
            self._queue = [x for x in queue if x.video_id]
            self._queue_index = queue_index if queue_index is not None else 0
            self._queue_title = queue_title
        elif not self._queue or all(q.video_id != item.video_id for q in self._queue):
            self._queue = [item]
            self._queue_index = 0
            self._queue_title = tr_pair("Hàng đợi phát", "Now Playing Queue")
        else:
            for i, q in enumerate(self._queue):
                if q.video_id == item.video_id:
                    self._queue_index = i
                    break

        self.nav_buttons["watch"].show()
        self._show_view(self.VIEW_WATCH, record_nav=True)
        self._start_watching_item(item)

    def _start_watching_item(self, item: OnlineVideoItem, *, force_refresh_stream: bool = False) -> None:
        self._current_item = item
        self._current_watch = None
        self._current_stream = None
        self._preresolved_vid = ""
        self._desc_expanded = False
        self.desc_browser.setMaximumHeight(84)

        self.lbl_watch_title.setText(item.title or item.video_id)
        self.lbl_audio_title.setText(item.title or item.video_id)
        self.lbl_audio_artist.setText(item.channel_name or "YouTube Hi-Fi")
        self.btn_watch_channel.setText(item.channel_name or "YouTube")
        self.lbl_watch_subs.setText("")
        self.lbl_watch_stats.setText(" • ".join(p for p in (item.views_text, item.published_text) if p))
        self.desc_browser.setHtml("")
        self.chapters_wrap.hide()
        self._clear_layout(self.comments_list_lay)
        self.lbl_sub_overlay.hide()
        self.lbl_buffering.setText(tr_pair("Đang kết nối luồng Hi-Fi…", "Resolving Hi-Fi stream…"))
        self.lbl_buffering.show()
        self.btn_like.setChecked(self.profile.is_liked(item.video_id))
        self.btn_subscribe.setChecked(self.profile.is_subscribed(item.channel_id))
        self.retranslate(get_language())

        if item.thumbnail_url:
            self._thumbs.load(item.thumbnail_url, self.lbl_audio_art, QSize(260, 146))
            self._thumbs.load(item.thumbnail_url, self.lbl_mini_thumb, QSize(76, 44))
        self.lbl_mini_title.setText(item.title)
        self.lbl_mini_sub.setText(item.channel_name or "YouTube")

        self._render_queue_list()
        self.profile.record_watch(item)

        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        lang = get_language()

        # 1. Resolve audio + video + subtitle streams via bundled yt-dlp.exe
        self._run_async(
            "stream",
            lambda procs: self.client.resolve_stream(
                item.video_id,
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
                force_refresh=force_refresh_stream,
            ),
            on_ok=self._on_stream_resolved,
            on_err=self._on_stream_error,
            pass_processes=True,
            busy_text=tr_pair("Đang kết nối luồng YouTube…", "Connecting to YouTube stream…"),
        )

        # 2. Fetch full YouTube Watch details (description, channel, related videos, comments token) in parallel!
        self._run_async(
            "watch_meta",
            lambda: self.client.fetch_watch_info(item.video_id, playlist_id=item.playlist_id, lang=lang),
            on_ok=self._on_watch_info_ready,
            on_err=lambda _m: None,
        )

    def _on_stream_resolved(self, stream: ResolvedStream) -> None:
        if self._current_item is None or stream.video_id != self._current_item.video_id:
            return
        self._current_stream = stream
        self.lbl_buffering.hide()

        if stream.title and self._current_item.title == self._current_item.video_id:
            self._current_item.title = stream.title
            self.lbl_watch_title.setText(stream.title)
            self.lbl_audio_title.setText(stream.title)
            self.lbl_mini_title.setText(stream.title)
        if stream.channel_name and not self._current_item.channel_name:
            self._current_item.channel_name = stream.channel_name
            self._current_item.channel_id = stream.channel_id
            self.btn_watch_channel.setText(stream.channel_name)
            self.lbl_audio_artist.setText(stream.channel_name)
            self.lbl_mini_sub.setText(stream.channel_name)
            self.profile.record_watch(self._current_item)

        # Populate available Quality choices cleanly
        self.combo_quality.blockSignals(True)
        self.combo_quality.clear()
        self.combo_quality.addItem("Audio Hi-Fi", "audio_only")
        for q_label in ("2160p", "1440p", "1080p", "720p", "480p", "360p"):
            if q_label in stream.video_streams:
                pretty = {"2160p": "4K · 2160p", "1440p": "2K · 1440p", "1080p": "1080p HD", "720p": "720p HD"}.get(q_label, q_label)
                self.combo_quality.addItem(pretty, q_label)
        audio_only = self.btn_audio_mode.isChecked()
        pref_q = "audio_only" if audio_only else str(self.profile.get_pref("quality", "1080p") or "1080p")
        q_idx = self.combo_quality.findData(pref_q)
        if q_idx < 0:
            q_idx = 1 if self.combo_quality.count() > 1 and not audio_only else 0
        self.combo_quality.setCurrentIndex(q_idx)
        self.combo_quality.blockSignals(False)

        # Populate YouTube CC subtitle tracks
        self.combo_sub_lang.blockSignals(True)
        self.combo_sub_lang.clear()
        for track in stream.subtitles:
            self.combo_sub_lang.addItem(track.label, track)
        pref_sub_lang = str(self.profile.get_pref("subtitle_lang", "vi") or "vi")
        picked_sub_idx = 0
        for i, trk in enumerate(stream.subtitles):
            if trk.lang_code == pref_sub_lang or trk.lang_code.startswith(pref_sub_lang + "-"):
                picked_sub_idx = i
                break
        if stream.subtitles:
            self.combo_sub_lang.setCurrentIndex(picked_sub_idx)
        self.combo_sub_lang.blockSignals(False)

        if stream.chapters:
            self._render_chapters(stream.chapters)

        # Begin playback!
        chosen_q = str(self.combo_quality.currentData() or "1080p")
        self.player.load_and_play(
            stream,
            audio_only=audio_only or (chosen_q == "audio_only"),
            quality="1080p" if chosen_q == "audio_only" else chosen_q,
        )
        self.stage_stack.setCurrentIndex(1 if (audio_only or chosen_q == "audio_only") else 0)

        # If subtitle mode is YouTube CC, load the selected CC track right away (0% GPU!)
        if self.combo_sub_mode.currentData() == "youtube_cc":
            self._load_selected_youtube_cc()
        else:
            self.player.set_subtitles([], enabled=False)

    def _on_stream_error(self, msg: str) -> None:
        self.lbl_buffering.hide()
        self.lbl_audio_badge.setText(tr_pair("Lỗi kết nối luồng", "Stream Error"))
        self.status_message.emit(tr_pair(f"Không phát được video: {msg}", f"Playback failed: {msg}"))

    def _on_watch_info_ready(self, info: OnlineWatchInfo) -> None:
        if self._current_item is None or info.video_id != self._current_item.video_id:
            return
        self._current_watch = info
        if info.title:
            self.lbl_watch_title.setText(info.title)
            self.lbl_audio_title.setText(info.title)
            self.lbl_mini_title.setText(info.title)
            self._current_item.title = info.title
        if info.channel_name:
            self.btn_watch_channel.setText(info.channel_name)
            self.lbl_audio_artist.setText(info.channel_name)
            self.lbl_mini_sub.setText(info.channel_name)
            self._current_item.channel_name = info.channel_name
        if info.channel_id:
            self._current_item.channel_id = info.channel_id
            self.btn_subscribe.setChecked(self.profile.is_subscribed(info.channel_id))
            self._refresh_subscribe_button_text()
        if info.channel_avatar:
            self._thumbs.load(info.channel_avatar, self.lbl_ch_avatar, QSize(40, 40))
        if info.subscriber_text:
            self.lbl_watch_subs.setText(info.subscriber_text)
        stats = " • ".join(p for p in (info.views_text, info.published_text) if p)
        if stats:
            self.lbl_watch_stats.setText(stats)
        if info.description:
            self.desc_browser.setHtml(self._format_description_html(info.description))
        if info.chapters and (self._current_stream is None or not self._current_stream.chapters):
            self._render_chapters(info.chapters)

        # Render Up Next / Related list
        self._render_related_list(info.related)

        # Auto-load top comments gently
        if info.comment_token:
            self._load_comments_async()

    def _format_description_html(self, desc: str) -> str:
        escaped = html.escape(desc)
        linked = _RE_DESC_TS.sub(
            r'<a href="ts:\1" style="color:#77E0BE;text-decoration:none;font-weight:600;">\1</a>',
            escaped,
        )
        return linked.replace("\n", "<br>")

    def _on_desc_link_clicked(self, url: QUrl) -> None:
        raw = url.toString()
        if raw.startswith("ts:"):
            sec = parse_duration_text(raw[3:])
            self.player.seek(sec * 1000)

    def _toggle_description(self) -> None:
        self._desc_expanded = not self._desc_expanded
        self.desc_browser.setMaximumHeight(420 if self._desc_expanded else 84)
        self.retranslate(get_language())

    def _render_chapters(self, chapters: list[OnlineChapter]) -> None:
        self.seek_slider.set_chapters(chapters)
        self._clear_layout(self.chapters_row)
        if not chapters:
            self.chapters_wrap.hide()
            return
        for ch in chapters[:24]:
            btn = QPushButton(f"{format_seconds_mmss(ch.start_sec)}  {ch.title[:28]}")
            btn.setProperty("ytChip", True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{format_seconds_mmss(ch.start_sec)} — {ch.title}")
            btn.clicked.connect(lambda _c=False, s=ch.start_sec: self.player.seek(int(s * 1000)))
            self.chapters_row.addWidget(btn)
        self.chapters_row.addStretch(1)
        self.chapters_wrap.show()

    def _render_related_list(self, items: list[OnlineVideoItem]) -> None:
        self._clear_layout(self.related_lay)
        for it in (items or [])[:20]:
            row = _CompactRelatedRow(it, self._thumbs)
            row.clicked.connect(self._on_card_clicked)
            self.related_lay.addWidget(row)
        self.related_lay.addStretch(1)

    def _render_queue_list(self) -> None:
        self._clear_layout(self.queue_lay)
        self._update_queue_header_text()
        for idx, it in enumerate(self._queue):
            row = _CompactRelatedRow(
                it,
                self._thumbs,
                is_active=(idx == self._queue_index),
                index_num=idx + 1,
            )
            row.clicked.connect(lambda item_obj, i=idx: self._jump_queue_index(i))
            self.queue_lay.addWidget(row)
        self.queue_lay.addStretch(1)

    def _update_queue_header_text(self, lang: str | None = None) -> None:
        base = self._queue_title or tr_pair("Hàng đợi phát", "Up Next Queue", lang)
        if self._queue:
            cur = max(1, self._queue_index + 1)
            self.lbl_queue_title.setText(f"{base} ({cur}/{len(self._queue)})")
        else:
            self.lbl_queue_title.setText(base)

    def _jump_queue_index(self, idx: int) -> None:
        if 0 <= idx < len(self._queue):
            self._queue_index = idx
            self._start_watching_item(self._queue[idx])

    def _append_to_queue(self, item: OnlineVideoItem) -> None:
        if not item or not item.video_id:
            return
        if all(q.video_id != item.video_id for q in self._queue):
            self._queue.append(item)
            self._render_queue_list()
            self.status_message.emit(tr_pair(f"Đã thêm vào hàng đợi: {item.title}", f"Added to queue: {item.title}"))

    def _start_radio_mix(self) -> None:
        if self._current_item is None:
            return
        vid = self._current_item.video_id
        lang = get_language()
        self._run_async(
            "mix",
            lambda: self.client.fetch_auto_mix(vid, lang=lang),
            on_ok=self._on_mix_loaded,
            busy_text=tr_pair("Đang tạo danh sách Mix Radio…", "Building YouTube Radio Mix…"),
        )

    def _on_mix_loaded(self, items: list[OnlineVideoItem]) -> None:
        if not items or self._current_item is None:
            return
        cur_vid = self._current_item.video_id
        merged = [self._current_item] + [it for it in items if it.video_id != cur_vid]
        self._queue = merged
        self._queue_index = 0
        self._queue_title = tr_pair("Mix Radio đề xuất", "YouTube Radio Mix")
        self._render_queue_list()
        self.status_message.emit(tr_pair(f"Đã tạo Mix Radio ({len(merged)} bài).", f"Radio Mix ready ({len(merged)} tracks)."))

    # =================================================================
    # COMMENTS
    # =================================================================

    def _load_comments_async(self) -> None:
        tok = self._current_watch.comment_token if self._current_watch else ""
        if not tok:
            return
        lang = get_language()
        self._run_async(
            "comments",
            lambda: self.client.fetch_comments(tok, lang=lang, limit=20),
            on_ok=self._render_comments,
            on_err=lambda _m: None,
        )

    def _render_comments(self, comments: list[OnlineComment]) -> None:
        self._clear_layout(self.comments_list_lay)
        if not comments:
            lbl = QLabel(tr_pair("Chưa có bình luận hiển thị.", "No comments available."))
            lbl.setStyleSheet("color: #7D8FA3; font-size: 12px;")
            self.comments_list_lay.addWidget(lbl)
            return
        for c in comments:
            card = QFrame()
            card.setStyleSheet("background: #101722; border: 1px solid #1E2B3C; border-radius: 9px;")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 8, 12, 8)
            cl.setSpacing(4)
            hdr = QHBoxLayout()
            author_lbl = QLabel(c.author + (" ★" if c.is_creator else ""))
            author_lbl.setStyleSheet(f"color: {'#77E0BE' if c.is_creator else '#DCE6F2'}; font-size: 12px; font-weight: 700;")
            time_lbl = QLabel(c.published_text)
            time_lbl.setStyleSheet("color: #728499; font-size: 11px;")
            hdr.addWidget(author_lbl)
            hdr.addWidget(time_lbl)
            hdr.addStretch(1)
            if c.likes_text:
                lk = QLabel(f"👍 {c.likes_text}")
                lk.setStyleSheet("color: #8EA0B5; font-size: 11px;")
                hdr.addWidget(lk)
            cl.addLayout(hdr)
            txt = QLabel(c.text)
            txt.setWordWrap(True)
            txt.setStyleSheet("color: #C7D4E3; font-size: 12px;")
            cl.addWidget(txt)
            self.comments_list_lay.addWidget(card)

    # =================================================================
    # TRANSPORT, SUBTITLES, QUALITY, PRE-RESOLVE & HARDWARE KEYS
    # =================================================================

    def toggle_play_pause(self) -> None:
        self.player.toggle_play_pause()

    def pause_if_playing(self) -> None:
        self.player.pause_if_playing()

    def is_playing_active(self) -> bool:
        return self.player.is_playing

    def play_next(self) -> None:
        if self._repeat_mode and self._current_item is not None:
            self.player.seek(0)
            self.player.play()
            return
        if self._queue and len(self._queue) > 1:
            if self._shuffle_queue:
                choices = [i for i in range(len(self._queue)) if i != self._queue_index]
                nxt = random.choice(choices) if choices else 0
            else:
                nxt = self._queue_index + 1
            if nxt < len(self._queue):
                self._queue_index = nxt
                self._start_watching_item(self._queue[nxt])
                return
        # Seamless YouTube Auto-Play from Related list!
        if self._autoplay and self._current_watch and self._current_watch.related:
            nxt_item = next(
                (r for r in self._current_watch.related if r.item_type == "video" and r.video_id),
                None,
            )
            if nxt_item is not None:
                self._queue.append(nxt_item)
                self._queue_index = len(self._queue) - 1
                self._start_watching_item(nxt_item)

    def play_previous(self) -> None:
        if self.player.position_ms() > 4000:
            self.player.seek(0)
            return
        if self._queue and self._queue_index > 0:
            self._queue_index -= 1
            self._start_watching_item(self._queue[self._queue_index])

    def _on_track_ended(self) -> None:
        if self._repeat_mode or self._autoplay or (self._queue_index + 1 < len(self._queue)):
            self.play_next()

    def _on_player_state_changed(self, playing: bool) -> None:
        ico = "pause" if playing else "play"
        button_icon(self.btn_play, ico, "Play / Pause", color=INK, size=18)
        button_icon(self.btn_mini_play, ico, "Play / Pause", color=INK, size=17)
        self._update_mini_bar_visibility()

    def _on_player_position_changed(self, pos_ms: int, dur_ms: int) -> None:
        self._last_seek_ms = pos_ms
        if dur_ms > 0 and self.seek_slider.maximum() != dur_ms:
            self.seek_slider.setRange(0, dur_ms)
            self.lbl_dur_time.setText(format_seconds_mmss(dur_ms / 1000.0))
        if not self._user_dragging_seek:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(pos_ms)
            self.seek_slider.blockSignals(False)
        self.lbl_pos_time.setText(format_seconds_mmss(pos_ms / 1000.0))

        # Pre-resolve next track 18 seconds before EOF for instant zero-wait transitions!
        if dur_ms > 25000 and (dur_ms - pos_ms) <= 18000:
            self._maybe_preresolve_next()

    def _maybe_preresolve_next(self) -> None:
        nxt_item: OnlineVideoItem | None = None
        if self._queue and (self._queue_index + 1) < len(self._queue):
            nxt_item = self._queue[self._queue_index + 1]
        elif self._autoplay and self._current_watch and self._current_watch.related:
            nxt_item = next(
                (r for r in self._current_watch.related if r.item_type == "video" and r.video_id),
                None,
            )
        if nxt_item is None or not nxt_item.video_id or nxt_item.video_id == self._preresolved_vid:
            return
        self._preresolved_vid = nxt_item.video_id
        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        self._run_async(
            "preresolve",
            lambda procs: self.client.resolve_stream(
                nxt_item.video_id,
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
            ),
            on_ok=lambda _r: None,
            on_err=lambda _m: None,
            pass_processes=True,
        )

    def _on_seek_requested(self, pos_ms: int) -> None:
        self.player.seek(pos_ms)

    def _on_seek_slider_released(self) -> None:
        self._user_dragging_seek = False
        self.player.seek(self.seek_slider.value())

    def _on_volume_changed(self, value: int) -> None:
        vol = max(0.0, min(1.0, value / 100.0))
        self.player.set_volume(vol)
        self.profile.set_pref("volume", vol)
        ico = "volume-x" if vol <= 0.001 else ("volume-1" if vol < 0.5 else "volume-2")
        button_icon(self.btn_mute, ico, "Mute", color=TEXT, size=16)

    def _toggle_mute(self) -> None:
        muted = not self.player._muted
        self.player.set_muted(muted)
        button_icon(self.btn_mute, "volume-x" if muted else "volume-2", "Mute", color=TEXT, size=16)

    def _on_audio_only_toggled(self, checked: bool) -> None:
        self.profile.set_pref("audio_only", bool(checked))
        self.player.set_audio_only(bool(checked))
        self.stage_stack.setCurrentIndex(1 if checked else 0)
        self.retranslate(get_language())

    def _on_quality_changed(self) -> None:
        q = str(self.combo_quality.currentData() or "1080p")
        is_audio = (q == "audio_only")
        self.btn_audio_mode.blockSignals(True)
        self.btn_audio_mode.setChecked(is_audio)
        self.btn_audio_mode.blockSignals(False)
        self.profile.set_pref("audio_only", is_audio)
        if not is_audio:
            self.profile.set_pref("quality", q)
        self.player.set_quality(q)
        self.stage_stack.setCurrentIndex(1 if is_audio else 0)
        self.retranslate(get_language())

    def _on_speed_changed(self) -> None:
        sp = float(self.combo_speed.currentData() or 1.0)
        self.profile.set_pref("speed", sp)
        self.player.set_playback_rate(sp)

    def _on_sub_mode_changed(self) -> None:
        mode = str(self.combo_sub_mode.currentData() or "off")
        if mode == "ai_handoff":
            # Keep YouTube streaming clean & hand off to BoTube's Studio Download + AI Sub pipeline!
            self.combo_sub_mode.blockSignals(True)
            self.combo_sub_mode.setCurrentIndex(0)
            self.combo_sub_mode.blockSignals(False)
            self.combo_sub_lang.hide()
            self.player.set_subtitles_enabled(False)
            if self._current_item is not None:
                self._emit_download_item(self._current_item)
                self.status_message.emit(
                    tr_pair(
                        "Đã chuyển link sang tab Tải về để bạn lưu và tạo Phụ đề AI song ngữ BoTube.",
                        "Sent link to Downloads so you can save and generate full BoTube AI subtitles.",
                    )
                )
            return

        self.profile.set_pref("subtitle_mode", mode)
        if mode == "off":
            self.combo_sub_lang.hide()
            self.player.set_subtitles_enabled(False)
            self.lbl_sub_overlay.hide()
        elif mode == "youtube_cc":
            self.combo_sub_lang.show()
            self._load_selected_youtube_cc()

    def _on_sub_lang_changed(self) -> None:
        trk = self.combo_sub_lang.currentData()
        if isinstance(trk, OnlineSubtitleTrack):
            self.profile.set_pref("subtitle_lang", trk.lang_code)
            if self.combo_sub_mode.currentData() == "youtube_cc":
                self._load_selected_youtube_cc()

    def _load_selected_youtube_cc(self) -> None:
        trk = self.combo_sub_lang.currentData()
        if not isinstance(trk, OnlineSubtitleTrack):
            self.player.set_subtitles([], enabled=False)
            self.lbl_sub_overlay.hide()
            if self._current_stream is not None:
                self.status_message.emit(tr_pair("Video này chưa có phụ đề CC trên YouTube.", "This video has no YouTube CC captions."))
            return
        self._run_async(
            "subtitle_cc",
            lambda: self.client.fetch_subtitle_cues(trk),
            on_ok=lambda cues: self.player.set_subtitles(cues, enabled=True),
            on_err=lambda _m: self.player.set_subtitles([], enabled=False),
        )

    def _on_subtitle_text_changed(self, text: str) -> None:
        clean = str(text or "").strip()
        if clean and self.combo_sub_mode.currentData() == "youtube_cc":
            self.lbl_sub_overlay.setText(clean)
            self.lbl_sub_overlay.show()
            self.lbl_sub_overlay.raise_()
        else:
            self.lbl_sub_overlay.setText("")
            self.lbl_sub_overlay.hide()

    def _on_audio_status_changed(self, label: str) -> None:
        self.lbl_audio_badge.setText(label)
        if self._current_item is not None:
            self.lbl_mini_sub.setText(f"{self._current_item.channel_name or 'YouTube'} · {label}")

    def _on_buffering_changed(self, buffering: bool) -> None:
        if buffering:
            self.lbl_buffering.setText(tr_pair("Đang nạp bộ đệm 64-bit…", "Buffering 64-bit audio…"))
            self.lbl_buffering.show()
        else:
            self.lbl_buffering.hide()

    def _on_player_error(self, msg: str) -> None:
        self.status_message.emit(f"YouTube Online: {msg}")

    def _on_autoplay_toggled(self, checked: bool) -> None:
        self._autoplay = bool(checked)
        self.profile.set_pref("autoplay", self._autoplay)

    def _on_shuffle_toggled(self, checked: bool) -> None:
        self._shuffle_queue = bool(checked)
        button_icon(self.btn_q_shuffle, "shuffle", "Shuffle", color=ACCENT if checked else MUTED, size=15)

    def _on_repeat_toggled(self, checked: bool) -> None:
        self._repeat_mode = bool(checked)
        button_icon(self.btn_q_repeat, "repeat", "Repeat", color=ACCENT if checked else MUTED, size=15)

    def _toggle_cinema_mode(self, checked: bool) -> None:
        self._cinema_mode = bool(checked)
        self.watch_right_panel.setVisible(not checked)
        self.stage_frame.setMaximumHeight(680 if checked else 540)

    def _toggle_fullscreen_stage(self) -> None:
        win = self.window()
        if win is None:
            return
        if self._is_fullscreen_stage:
            self.exit_fullscreen_stage()
        else:
            self._is_fullscreen_stage = True
            self.top_bar.hide()
            self.sub_nav.hide()
            self.watch_right_panel.hide()
            self.stage_frame.setMaximumHeight(16777215)
            self.stage_frame.setMinimumHeight(520)
            if hasattr(win, "sidebar_container"):
                win.sidebar_container.hide()
            if hasattr(win, "playback_bar"):
                win.playback_bar.hide()
            win.showFullScreen()
            button_icon(self.btn_fs, "minimize", "Exit Fullscreen", color=ACCENT, size=16)

    def exit_fullscreen_stage(self) -> None:
        if not self._is_fullscreen_stage:
            return
        self._is_fullscreen_stage = False
        win = self.window()
        self.top_bar.show()
        self.sub_nav.show()
        self.watch_right_panel.setVisible(not self._cinema_mode)
        self.stage_frame.setMaximumHeight(680 if self._cinema_mode else 540)
        self.stage_frame.setMinimumHeight(340)
        if win is not None:
            if hasattr(win, "sidebar_container"):
                win.sidebar_container.show()
            if hasattr(win, "playback_bar"):
                win.playback_bar.show()
            if win.isFullScreen():
                win.showNormal()
        button_icon(self.btn_fs, "maximize", "Fullscreen", color=TEXT, size=16)

    def _update_mini_bar_visibility(self) -> None:
        show_mini = (
            self._current_item is not None
            and self.player.is_loaded
            and self.stack.currentIndex() != self.VIEW_WATCH
        )
        self.mini_bar.setVisible(show_mini)

    # =================================================================
    # LOCAL PROFILE ACTIONS (SUBSCRIBE, LIKE, SAVE PLAYLIST, DOWNLOAD)
    # =================================================================

    def _refresh_subscribe_button_text(self, lang: str | None = None) -> None:
        lg = lang or get_language()
        self.btn_subscribe.setText(
            tr_pair("✓ Đã đăng ký", "✓ Subscribed", lg) if self.btn_subscribe.isChecked() else tr_pair("Đăng ký", "Subscribe", lg)
        )
        self.btn_chan_page_sub.setText(
            tr_pair("✓ Đã đăng ký", "✓ Subscribed", lg) if self.btn_chan_page_sub.isChecked() else tr_pair("Đăng ký", "Subscribe", lg)
        )

    def _toggle_subscribe_current(self) -> None:
        if self._current_item is None or not self._current_item.channel_id:
            self.btn_subscribe.setChecked(False)
            return
        avatar = self._current_watch.channel_avatar if self._current_watch else self._current_item.channel_avatar
        subbed = self.profile.toggle_subscription(
            self._current_item.channel_id,
            self._current_item.channel_name,
            avatar,
        )
        self.btn_subscribe.setChecked(subbed)
        self._refresh_subscribe_button_text()

    def _toggle_like_current(self) -> None:
        if self._current_item is None:
            self.btn_like.setChecked(False)
            return
        liked = self.profile.toggle_like(self._current_item)
        self.btn_like.setChecked(liked)
        self.retranslate(get_language())

    def _open_save_playlist_menu(self) -> None:
        if self._current_item is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #18212E; color: #EDF3FA; border: 1px solid #35475E; } QMenu::item:selected { background: #264B41; }")
        for pl in self.profile.list_playlists():
            act = menu.addAction(f"🎵  {pl.get('name', 'Playlist')}")
            act.triggered.connect(lambda _c=False, pid=pl["id"]: self._save_current_to_playlist(pid))
        menu.addSeparator()
        act_new = menu.addAction(tr_pair("＋ Tạo Playlist Online mới…", "＋ Create New Online Playlist…"))
        act_new.triggered.connect(self._create_playlist_with_current)
        menu.exec(self.btn_save_pl.mapToGlobal(QPoint(0, self.btn_save_pl.height())))

    def _save_current_to_playlist(self, playlist_id: str) -> None:
        if self._current_item is None:
            return
        added = self.profile.add_item_to_playlist(playlist_id, self._current_item)
        self.status_message.emit(
            tr_pair("Đã lưu vào Playlist Online!", "Saved to Online Playlist!")
            if added
            else tr_pair("Video đã có trong Playlist này.", "Video is already in this playlist.")
        )

    def _create_playlist_with_current(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            tr_pair("Tạo Playlist Online", "New Online Playlist"),
            tr_pair("Nhập tên Playlist:", "Playlist name:"),
        )
        if ok and name.strip():
            items = [self._current_item] if self._current_item is not None else []
            self.profile.create_playlist(name.strip(), items=items)
            self.status_message.emit(tr_pair(f"Đã tạo Playlist “{name.strip()}”.", f"Created playlist “{name.strip()}”."))

    def _download_current_video(self) -> None:
        if self._current_item is not None:
            self._emit_download_item(self._current_item)

    def _emit_download_item(self, item: OnlineVideoItem) -> None:
        url = item.watch_url
        if url:
            self.download_requested.emit(url, item.title)

    def _copy_current_link(self) -> None:
        if self._current_item is None:
            return
        url = self._current_item.watch_url
        if url:
            cb = QGuiApplication.clipboard()
            if cb is not None:
                cb.setText(url)
            self.status_message.emit(tr_pair("Đã sao chép đường dẫn YouTube!", "Copied YouTube URL!"))

    def _open_account_dialog(self) -> None:
        dlg = _YouTubeAccountDialog(self.profile, parent=self)
        dlg.playlist_import_requested.connect(self.open_playlist)
        dlg.exec()

    # =================================================================
    # CHANNEL, PLAYLIST & ONLINE LIBRARY VIEWS
    # =================================================================

    def _open_current_channel(self) -> None:
        if self._current_item and self._current_item.channel_id:
            self.open_channel(self._current_item.channel_id, self._current_item.channel_name)

    def open_channel(self, channel_id: str, name_hint: str = "", tab: str = "videos") -> None:
        cid = str(channel_id or "").strip()
        if not cid:
            return
        self._show_view(self.VIEW_CHANNEL, record_nav=True)
        self.lbl_chan_page_name.setText(name_hint or cid)
        self.lbl_chan_page_meta.setText(tr_pair("Đang tải thông tin kênh…", "Loading channel…"))
        self.btn_chan_page_sub.setChecked(self.profile.is_subscribed(cid))
        self._refresh_subscribe_button_text()
        self.btn_chan_videos.setChecked(tab == "videos")
        self.btn_chan_playlists.setChecked(tab == "playlists")
        lang = get_language()
        self._run_async(
            "channel",
            lambda: self.client.fetch_channel(cid, tab=tab, lang=lang),
            on_ok=self._on_channel_loaded,
            busy_text=tr_pair("Đang tải trang Kênh…", "Loading channel…"),
        )

    def _switch_channel_tab(self, tab: str) -> None:
        if self._active_channel is not None:
            self.open_channel(self._active_channel.channel_id, self._active_channel.name, tab=tab)

    def _on_channel_loaded(self, info: OnlineChannelInfo) -> None:
        self._active_channel = info
        self.lbl_chan_page_name.setText(info.name)
        meta_parts = [p for p in (info.handle, info.subscriber_text) if p]
        self.lbl_chan_page_meta.setText(" • ".join(meta_parts))
        self.btn_chan_page_sub.setChecked(self.profile.is_subscribed(info.channel_id))
        self._refresh_subscribe_button_text()
        if info.avatar_url:
            self._thumbs.load(info.avatar_url, self.lbl_chan_page_avatar, QSize(68, 68))
        self._clear_layout(self.channel_grid)
        avail = max(320, self.channel_scroll.viewport().width() - 16)
        cols = max(1, min(5, avail // 302))
        for idx, it in enumerate(info.items):
            card = _OnlineVideoCard(it, self._thumbs)
            card.clicked.connect(self._on_card_clicked)
            card.channel_clicked.connect(self.open_channel)
            card.queue_clicked.connect(self._append_to_queue)
            card.download_clicked.connect(self._emit_download_item)
            self.channel_grid.addWidget(card, idx // cols, idx % cols)

    def _toggle_subscribe_channel_page(self) -> None:
        if self._active_channel is None:
            return
        subbed = self.profile.toggle_subscription(
            self._active_channel.channel_id,
            self._active_channel.name,
            self._active_channel.avatar_url,
        )
        self.btn_chan_page_sub.setChecked(subbed)
        self._refresh_subscribe_button_text()

    def open_playlist(self, playlist_url_or_id: str, *, title_hint: str = "") -> None:
        raw = str(playlist_url_or_id or "").strip()
        if not raw:
            return
        self._show_view(self.VIEW_PLAYLIST, record_nav=True)
        self._active_playlist_url = raw if raw.startswith(("http://", "https://", ":")) else f"https://www.youtube.com/playlist?list={raw}"
        self.lbl_pl_page_title.setText(title_hint or tr_pair("Đang tải Playlist…", "Loading Playlist…"))
        self.lbl_pl_page_meta.setText("")
        self._clear_layout(self.pl_list_lay)

        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        self._run_async(
            "playlist",
            lambda procs: self.client.fetch_playlist(
                raw,
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
            ),
            on_ok=self._on_playlist_loaded,
            on_err=lambda m: self.lbl_pl_page_meta.setText(tr_pair(f"Lỗi tải Playlist: {m}", f"Playlist load error: {m}")),
            pass_processes=True,
            busy_text=tr_pair("Đang đọc danh sách phát YouTube…", "Fetching YouTube playlist…"),
        )

    def _on_playlist_loaded(self, payload: tuple[str, list[OnlineVideoItem]]) -> None:
        title, items = payload
        self._active_playlist_title = title
        self._active_playlist_items = list(items or [])
        self.lbl_pl_page_title.setText(title)
        self.lbl_pl_page_meta.setText(tr_pair(f"{len(items)} video/bài hát", f"{len(items)} videos/tracks"))
        self._clear_layout(self.pl_list_lay)
        for idx, it in enumerate(self._active_playlist_items):
            row = _CompactRelatedRow(it, self._thumbs, index_num=idx + 1)
            row.clicked.connect(
                lambda item_obj, i=idx: self.play_video_item(
                    item_obj,
                    queue=self._active_playlist_items,
                    queue_index=i,
                    queue_title=self._active_playlist_title,
                )
            )
            self.pl_list_lay.addWidget(row)
        self.pl_list_lay.addStretch(1)

    def _play_active_playlist(self, *, shuffle: bool = False) -> None:
        if not self._active_playlist_items:
            return
        items = list(self._active_playlist_items)
        if shuffle:
            random.shuffle(items)
        self.play_video_item(items[0], queue=items, queue_index=0, queue_title=self._active_playlist_title)

    def _pin_active_playlist(self) -> None:
        if not self._active_playlist_title:
            return
        self.profile.create_playlist(
            self._active_playlist_title,
            source_url=self._active_playlist_url,
            items=self._active_playlist_items,
        )
        self.status_message.emit(tr_pair("Đã lưu Playlist vào Thư viện Online!", "Pinned playlist to Online Library!"))

    def _render_library_section(self, section: str) -> None:
        for k, b in self.lib_tab_btns.items():
            b.setChecked(k == section)
        self.btn_lib_import_pl.setVisible(section == "playlists")
        self.btn_lib_new_pl.setVisible(section == "playlists")
        self.btn_lib_clear_hist.setVisible(section == "history")
        self._clear_layout(self.lib_lay)

        if section == "playlists":
            playlists = self.profile.list_playlists()
            if not playlists:
                lbl = QLabel(tr_pair("Chưa có Playlist Online nào. Bấm “+ Nhập URL Playlist” để dán link YouTube nghe ngay!", "No Online Playlists yet. Click “+ Import Playlist URL” to play any YouTube playlist!"))
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #8EA0B5; font-size: 13px; padding: 20px;")
                self.lib_lay.addWidget(lbl)
            for pl in playlists:
                card = QFrame()
                card.setObjectName("ytPanel")
                row = QHBoxLayout(card)
                row.setContentsMargins(14, 10, 14, 10)
                items_raw = [OnlineVideoItem.from_dict(d) for d in (pl.get("items") or [])]
                col = QVBoxLayout()
                t = QLabel(str(pl.get("name") or "Playlist"))
                t.setStyleSheet("color: #EDF3FA; font-size: 14px; font-weight: 700;")
                sub = QLabel(tr_pair(f"{len(items_raw)} bài", f"{len(items_raw)} tracks") + (" · YouTube Sync" if pl.get("source_url") else ""))
                sub.setStyleSheet("color: #8EA0B5; font-size: 12px;")
                col.addWidget(t)
                col.addWidget(sub)
                row.addLayout(col, 1)

                btn_play = QPushButton(tr_pair("▶ Phát", "▶ Play"))
                btn_play.setProperty("role", "primary")
                btn_play.clicked.connect(
                    lambda _c=False, its=items_raw, nm=pl.get("name", ""), url=pl.get("source_url", ""): (
                        self.play_video_item(its[0], queue=its, queue_index=0, queue_title=nm)
                        if its
                        else (self.open_playlist(url, title_hint=nm) if url else None)
                    )
                )
                row.addWidget(btn_play)
                if pl.get("source_url"):
                    btn_sync = QPushButton(tr_pair("↻ Mở / Đồng bộ", "↻ Open / Sync"))
                    btn_sync.clicked.connect(lambda _c=False, u=pl["source_url"], nm=pl.get("name", ""): self.open_playlist(u, title_hint=nm))
                    row.addWidget(btn_sync)
                btn_del = QPushButton(tr_pair("Xóa", "Delete"))
                btn_del.clicked.connect(lambda _c=False, pid=pl["id"]: self._delete_saved_playlist(pid))
                row.addWidget(btn_del)
                self.lib_lay.addWidget(card)
        elif section in ("liked", "history"):
            items = self.profile.list_liked() if section == "liked" else self.profile.list_watch_history()
            if not items:
                lbl = QLabel(tr_pair("Danh sách đang trống.", "This list is empty."))
                lbl.setStyleSheet("color: #8EA0B5; font-size: 13px; padding: 20px;")
                self.lib_lay.addWidget(lbl)
            else:
                q_title = tr_pair("Video Online đã thích", "Liked Online Videos") if section == "liked" else tr_pair("Lịch sử xem Online", "Online Watch History")
                for idx, it in enumerate(items[:80]):
                    row = _CompactRelatedRow(it, self._thumbs, index_num=idx + 1)
                    row.clicked.connect(lambda item_obj, i=idx: self.play_video_item(item_obj, queue=items[:80], queue_index=i, queue_title=q_title))
                    self.lib_lay.addWidget(row)
        elif section == "subscriptions":
            subs = self.profile.list_subscriptions()
            if not subs:
                lbl = QLabel(tr_pair("Bạn chưa đăng ký kênh nào trong BoTube. Bấm “Đăng ký” ở bất kỳ kênh nào hoặc nhập subscriptions.csv trong Tài khoản & Đồng bộ.", "No subscriptions yet. Click “Subscribe” on any channel or import subscriptions.csv via Profile & Sync."))
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #8EA0B5; font-size: 13px; padding: 20px;")
                self.lib_lay.addWidget(lbl)
            for s in subs:
                card = QFrame()
                card.setObjectName("ytPanel")
                row = QHBoxLayout(card)
                row.setContentsMargins(14, 10, 14, 10)
                lbl = QLabel(str(s.get("name") or s.get("channel_id")))
                lbl.setStyleSheet("color: #EDF3FA; font-size: 14px; font-weight: 700;")
                row.addWidget(lbl, 1)
                btn_open = QPushButton(tr_pair("Xem Kênh", "Open Channel"))
                btn_open.setProperty("role", "primary")
                btn_open.clicked.connect(lambda _c=False, cid=s["channel_id"], nm=s.get("name", ""): self.open_channel(cid, nm))
                btn_unsub = QPushButton(tr_pair("Hủy đăng ký", "Unsubscribe"))
                btn_unsub.clicked.connect(lambda _c=False, cid=s["channel_id"], nm=s.get("name", ""): self._unsub_from_list(cid, nm))
                row.addWidget(btn_open)
                row.addWidget(btn_unsub)
                self.lib_lay.addWidget(card)
        self.lib_lay.addStretch(1)

    def _delete_saved_playlist(self, pid: str) -> None:
        self.profile.delete_playlist(pid)
        self._render_library_section("playlists")

    def _unsub_from_list(self, cid: str, name: str) -> None:
        self.profile.toggle_subscription(cid, name)
        self._render_library_section("subscriptions")

    def _prompt_import_playlist_url(self) -> None:
        url, ok = QInputDialog.getText(
            self,
            tr_pair("Nhập Playlist YouTube", "Import YouTube Playlist"),
            tr_pair("Dán đường dẫn Playlist YouTube / YouTube Music (hoặc :ytfav):", "Paste YouTube / YouTube Music Playlist URL (or :ytfav):"),
        )
        if ok and url.strip():
            self.open_playlist(url.strip())

    def _prompt_new_playlist(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            tr_pair("Tạo Playlist Online", "Create Online Playlist"),
            tr_pair("Nhập tên Playlist mới:", "New playlist name:"),
        )
        if ok and name.strip():
            self.profile.create_playlist(name.strip())
            self._render_library_section("playlists")

    def _clear_online_history(self) -> None:
        self.profile.clear_watch_history()
        self._render_library_section("history")

    # =================================================================
    # EVENTS & SHUTDOWN
    # =================================================================

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.search_input and event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(150, self._hide_suggest_if_unfocused)
        return super().eventFilter(obj, event)

    def _hide_suggest_if_unfocused(self) -> None:
        if not self.search_input.hasFocus() and not self.suggest_popup.hasFocus():
            self.suggest_popup.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.stack.currentIndex() == self.VIEW_HOME and self._grid_items:
            self._grid_resize_timer.start()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def shutdown(self) -> None:
        unregister_language_listener(self.retranslate)
        self._suggest_timer.stop()
        self._grid_resize_timer.stop()
        self.exit_fullscreen_stage()
        for worker in list(self._workers.values()):
            try:
                worker.cancel()
                worker.wait(1200)
            except Exception:
                pass
        self._workers.clear()
        self._thumbs.shutdown()
        self.player.shutdown()
