"""Commercial-grade isolated YouTube Online Studio page for BoTube.

Self-contained tab (zero mutations to offline Library, For You, SubtitleManager, or AudioStreamEngine):
- 2-ID scoped QSS (`#youtubeOnlineRoot ...`) so global `SHELL_STYLE` never overrides buttons, chips, or badges.
- Fluid responsive 16:9 Home Grid with channel avatars & zero ragged right gap.
- Authentic 2-column YouTube Watch Page: 4K/2K/1080p CinemaScope & 16:9 video + 64-bit Hi-Fi WASAPI audio,
  Audio-Only Hi-Fi cover stage, 3-mode Subtitle control (Off / YouTube CC / AI Sub Handoff),
  Chapters, Clickable Timestamps, clean Top Comments, Radio Mix Queue, and unclipped Up Next cards.
- Streamlined Account & Playlist Sync dialog with live 1-click browser/cookie verification.
- 100% Bilingual VI/EN with clean worker/process lifecycle ownership.
"""
from __future__ import annotations

from collections import OrderedDict
import html
import logging
from pathlib import Path
import random
import re
import shutil
import tempfile
from typing import Any, Callable
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from control.worker_lifecycle import OwnedProcesses
from core.audio_profile import AudioProfile
from core.youtube_online_client import (
    COOKIE_VAULT_SENTINEL,
    OnlineChannelInfo,
    OnlineChapter,
    OnlineComment,
    OnlineSubtitleCue,
    OnlineSubtitleTrack,
    OnlineVideoItem,
    OnlineWatchInfo,
    ResolvedStream,
    TOPIC_CHIPS,
    YouTubeOnlineClient,
    YouTubeOnlineProfileStore,
    create_youtube_ai_worker,
    delete_cookie_vault,
    format_seconds_mmss,
    has_active_cookie_source,
    has_cached_ai_subtitles,
    has_cookie_vault,
    import_cookies_into_vault,
    is_bo_ai_subtitle_available,
    load_cached_ai_subtitles,
    online_ai_sub_cache_dir,
    parse_duration_text,
    parse_youtube_input,
    save_cached_ai_subtitles,
    serialize_ai_segments_to_cues,
)
from core.youtube_online_player import OnlineVideoSurface, YouTubeOnlinePlaybackController
from subtitle.mode import SubtitleMode
from ui.i18n import get_language, register_language_listener, tr_pair, unregister_language_listener
from ui.icons import ACCENT, INK, MUTED, TEXT, button_icon, icon
from ui.subs_ui.subtitle_layer import SubtitleLayer

logger = logging.getLogger(__name__)

_RE_DESC_TS = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")

# Strictly 2-ID scoped selectors (`#youtubeOnlineRoot #...`) beat `QWidget#applicationShell QPushButton/QLabel`
# (specificity 202 vs 102) without ever modifying global design_system.py!
YOUTUBE_PAGE_STYLE = """
QWidget#youtubeOnlineRoot {
    background: #0D1118;
    color: #EDF3FA;
    font-family: 'Segoe UI', 'Malgun Gothic', 'Meiryo UI', 'Microsoft YaHei UI', sans-serif;
}
QWidget#youtubeOnlineRoot QWidget#ytFullscreenPage {
    background: #000000;
}
QWidget#youtubeOnlineRoot QScrollArea {
    background: transparent;
    border: none;
}
QWidget#youtubeOnlineRoot QWidget#ytScrollHost {
    background: transparent;
}

/* ---- Topbar & Sub-nav ---- */
QWidget#youtubeOnlineRoot QFrame#ytTopBar {
    background: #101722;
    border-bottom: 1px solid #1E2A3B;
}
QWidget#youtubeOnlineRoot QFrame#ytSubNav {
    background: #0E141E;
    border-bottom: 1px solid #1A2535;
}
QWidget#youtubeOnlineRoot QLabel#ytBrandText {
    color: #F4F8FD;
    font-size: 16px;
    font-weight: 800;
    background: transparent;
    border: none;
}
QWidget#youtubeOnlineRoot QLabel#ytHifiPill {
    background: #FF4E45;
    color: #FFFFFF;
    border: none;
    border-radius: 5px;
    font-size: 10px;
    font-weight: 800;
    padding: 0 6px;
}
QWidget#youtubeOnlineRoot QLineEdit#ytSearchInput {
    background: #151D29;
    color: #EDF3FA;
    border: 1px solid #2A384D;
    border-radius: 19px;
    padding: 0 16px;
    font-size: 13px;
    selection-background-color: #2E5A4F;
}
QWidget#youtubeOnlineRoot QLineEdit#ytSearchInput:focus {
    border: 1px solid #77E0BE;
    background: #182230;
}
QWidget#youtubeOnlineRoot QPushButton#ytIconBtn {
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 4px;
    color: #EDF3FA;
}
QWidget#youtubeOnlineRoot QPushButton#ytIconBtn:hover {
    background: #202C3D;
}
QWidget#youtubeOnlineRoot QPushButton#ytIconBtn:disabled {
    color: #4A596B;
}
QWidget#youtubeOnlineRoot QPushButton#ytSearchBtn {
    background: #1B2636;
    border: 1px solid #2E3F55;
    border-radius: 19px;
    padding: 0;
}
QWidget#youtubeOnlineRoot QPushButton#ytSearchBtn:hover {
    background: #25344A;
    border-color: #77E0BE;
}
QWidget#youtubeOnlineRoot QPushButton#ytAudioToggle {
    background: #182332;
    color: #DCE6F2;
    border: 1px solid #2C3E55;
    border-radius: 17px;
    padding: 5px 11px;
    font-size: 12px;
    font-weight: 600;
}
QWidget#youtubeOnlineRoot QPushButton#ytAudioToggle:hover {
    background: #223044;
    border-color: #46607E;
}
QWidget#youtubeOnlineRoot QPushButton#ytAudioToggle:checked {
    background: #17382F;
    color: #77E0BE;
    border: 1px solid #3A8C75;
}
QWidget#youtubeOnlineRoot QPushButton#ytAccountBtn {
    background: #182332;
    color: #EDF3FA;
    border: 1px solid #2C3E55;
    border-radius: 17px;
    padding: 5px 11px;
    font-size: 12px;
    font-weight: 600;
}
QWidget#youtubeOnlineRoot QPushButton#ytAccountBtn:hover {
    background: #233349;
    border-color: #77E0BE;
}

/* ---- Sub-nav tabs & Topic chips ---- */
QWidget#youtubeOnlineRoot QPushButton#ytNavTab {
    background: transparent;
    color: #96A7BC;
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 600;
}
QWidget#youtubeOnlineRoot QPushButton#ytNavTab:hover {
    background: #192332;
    color: #EDF3FA;
}
QWidget#youtubeOnlineRoot QPushButton#ytNavTab:checked {
    background: #19372F;
    color: #9FF1D7;
}
QWidget#youtubeOnlineRoot QPushButton#ytChipBtn {
    background: #161F2D;
    color: #C8D5E4;
    border: 1px solid #263549;
    border-radius: 15px;
    padding: 5px 14px;
    font-size: 12px;
    font-weight: 600;
}
QWidget#youtubeOnlineRoot QPushButton#ytChipBtn:hover {
    background: #222F42;
    color: #FFFFFF;
    border-color: #3E536E;
}
QWidget#youtubeOnlineRoot QPushButton#ytChipBtn:checked {
    background: #77E0BE;
    color: #0B1117;
    border: 1px solid #77E0BE;
}

/* ---- Home Video Cards ---- */
QWidget#youtubeOnlineRoot QFrame#ytCard {
    background: #121924;
    border: 1px solid #1C2736;
    border-radius: 12px;
}
QWidget#youtubeOnlineRoot QFrame#ytCard:hover {
    background: #182231;
    border: 1px solid #33465E;
}
QWidget#youtubeOnlineRoot QPushButton#ytCardChannel {
    background: transparent;
    border: none;
    color: #9AAABC;
    font-size: 12px;
    font-weight: 500;
    text-align: left;
    padding: 0;
}
QWidget#youtubeOnlineRoot QPushButton#ytCardChannel:hover {
    color: #77E0BE;
}

/* ---- Watch Stage, Transport & Action Pills ---- */
QWidget#youtubeOnlineRoot QFrame#ytStageFrame {
    background: #05080D;
    border: 1px solid #1E2A3B;
    border-radius: 12px;
}
QWidget#youtubeOnlineRoot QFrame#ytWatchControls {
    background: #111824;
    border: 1px solid #202E40;
    border-radius: 10px;
}
QWidget#youtubeOnlineRoot QFrame#ytWatchControlsFS {
    background: rgba(14, 19, 28, 224);
    border: 1px solid rgba(64, 86, 114, 140);
    border-radius: 12px;
    margin: 0 24px 16px 24px;
}
QWidget#youtubeOnlineRoot QPushButton#ytPlayCircle {
    background: #77E0BE;
    color: #0D1118;
    border: none;
    border-radius: 19px;
    padding: 0;
}
QWidget#youtubeOnlineRoot QPushButton#ytPlayCircle:hover {
    background: #9BF0D5;
}
QWidget#youtubeOnlineRoot QPushButton#ytPlayCircle:pressed {
    background: #5EC9A7;
}
QWidget#youtubeOnlineRoot QLabel#ytAudioBadge {
    background: #14322B;
    color: #88E8C9;
    border: 1px solid #2A5F52;
    border-radius: 11px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}
QWidget#youtubeOnlineRoot QLabel#ytErrorBadge {
    background: #36181C;
    color: #FF8E8E;
    border: 1px solid #6E2F36;
    border-radius: 11px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}
QWidget#youtubeOnlineRoot QPushButton#ytSubscribeBtn {
    background: #FF4E45;
    color: #FFFFFF;
    border: none;
    border-radius: 17px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 700;
}
QWidget#youtubeOnlineRoot QPushButton#ytSubscribeBtn:hover {
    background: #FF6961;
}
QWidget#youtubeOnlineRoot QPushButton#ytSubscribeBtn:checked {
    background: #212E40;
    color: #D7E2EF;
    border: 1px solid #394D66;
}
QWidget#youtubeOnlineRoot QPushButton#ytActionPill {
    background: #182231;
    color: #E3ECF7;
    border: 1px solid #29384C;
    border-radius: 17px;
    padding: 6px 11px;
    font-size: 12px;
    font-weight: 600;
}
QWidget#youtubeOnlineRoot QPushButton#ytActionPill:hover {
    background: #233146;
    border-color: #415875;
}
QWidget#youtubeOnlineRoot QPushButton#ytActionPill:checked {
    background: #361C27;
    color: #FF8FA8;
    border: 1px solid #75374D;
}
QWidget#youtubeOnlineRoot QPushButton#ytActionPill:disabled {
    background: #121822;
    color: #54657A;
    border: 1px solid #1C2634;
}
QWidget#youtubeOnlineRoot QPushButton#ytPrimaryPill {
    background: #77E0BE;
    color: #0B1117;
    border: none;
    border-radius: 17px;
    padding: 6px 13px;
    font-size: 12px;
    font-weight: 700;
}
QWidget#youtubeOnlineRoot QPushButton#ytPrimaryPill:hover {
    background: #98EED3;
}
QWidget#youtubeOnlineRoot QPushButton#ytWatchChanBtn {
    background: transparent;
    border: none;
    color: #F2F6FC;
    font-size: 14px;
    font-weight: 700;
    text-align: left;
    padding: 0;
}
QWidget#youtubeOnlineRoot QPushButton#ytWatchChanBtn:hover {
    color: #77E0BE;
}
QWidget#youtubeOnlineRoot QPushButton#ytDescToggle {
    background: transparent;
    border: none;
    color: #77E0BE;
    font-size: 12px;
    font-weight: 600;
    text-align: left;
    padding: 2px 0;
}
QWidget#youtubeOnlineRoot QPushButton#ytDescToggle:hover {
    color: #A6F3DA;
}

/* ---- Panels, Description, Comments, Related Rows ---- */
QWidget#youtubeOnlineRoot QFrame#ytPanel {
    background: #121A25;
    border: 1px solid #1F2D3E;
    border-radius: 12px;
}
QWidget#youtubeOnlineRoot QFrame#ytCommentCard {
    background: #0F1620;
    border: 1px solid #1D293A;
    border-radius: 10px;
}
QWidget#youtubeOnlineRoot QFrame#ytRelRow {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}
QWidget#youtubeOnlineRoot QFrame#ytRelRow:hover {
    background: #1A2434;
    border: 1px solid #2A3A50;
}
QWidget#youtubeOnlineRoot QFrame#ytRelRowActive {
    background: #17312A;
    border: 1px solid #2E6456;
    border-radius: 10px;
}
QWidget#youtubeOnlineRoot QFrame#ytMiniBar {
    background: #101723;
    border-top: 1px solid #243347;
}
QWidget#youtubeOnlineRoot QLabel#ytBufferingPill {
    background: rgba(13, 17, 24, 225);
    color: #77E0BE;
    border: 1px solid #2E6456;
    border-radius: 8px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
}
QWidget#youtubeOnlineRoot QPushButton#ytBackAppBtn {
    background: #172333;
    color: #DCE7F4;
    border: 1px solid #2A3D55;
    border-radius: 17px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 700;
}
QWidget#youtubeOnlineRoot QPushButton#ytBackAppBtn:hover {
    background: #22344A;
    color: #77E0BE;
    border-color: #77E0BE;
}
QWidget#youtubeOnlineRoot QFrame#ytAiProgressBar {
    background: #122129;
    border: 1px solid #26544A;
    border-radius: 9px;
}
QWidget#youtubeOnlineRoot QLabel#ytSubOverlay {
    background: rgba(8, 11, 17, 222);
    color: #FFFFFF;
    border: none;
    border-radius: 9px;
    padding: 8px 18px;
    font-size: 16px;
    font-weight: 700;
    margin-bottom: 14px;
}
QWidget#youtubeOnlineRoot QLabel#ytSubOverlayFS {
    background: rgba(8, 11, 17, 225);
    color: #FFFFFF;
    border: none;
    border-radius: 11px;
    padding: 12px 26px 15px 26px;
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 24px;
}

/* ---- Compact Combos & Sliders ---- */
QWidget#youtubeOnlineRoot QComboBox#ytCombo {
    background: #172130;
    color: #EDF3FA;
    border: 1px solid #2A3A4F;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 600;
    min-height: 26px;
}
QWidget#youtubeOnlineRoot QComboBox#ytCombo:hover {
    border-color: #46607E;
    background: #1D293B;
}
QWidget#youtubeOnlineRoot QComboBox#ytCombo::drop-down {
    border: none;
    width: 20px;
}
QWidget#youtubeOnlineRoot QComboBox#ytCombo QAbstractItemView {
    background: #161F2D;
    color: #EDF3FA;
    border: 1px solid #344760;
    selection-background-color: #244D42;
    outline: none;
}
QWidget#youtubeOnlineRoot QSlider#ytSeekSlider::groove:horizontal {
    height: 5px;
    background: #2A384C;
    border-radius: 2px;
}
QWidget#youtubeOnlineRoot QSlider#ytSeekSlider::sub-page:horizontal {
    background: #FF4E45;
    border-radius: 2px;
}
QWidget#youtubeOnlineRoot QSlider#ytSeekSlider::handle:horizontal {
    background: #FFFFFF;
    width: 13px;
    height: 13px;
    margin: -4px 0;
    border-radius: 6px;
}
QWidget#youtubeOnlineRoot QSlider#ytSeekSlider::handle:horizontal:hover {
    background: #77E0BE;
}
QWidget#youtubeOnlineRoot QSlider#ytVolSlider::groove:horizontal {
    height: 4px;
    background: #2A384C;
    border-radius: 2px;
}
QWidget#youtubeOnlineRoot QSlider#ytVolSlider::sub-page:horizontal {
    background: #77E0BE;
    border-radius: 2px;
}
QWidget#youtubeOnlineRoot QSlider#ytVolSlider::handle:horizontal {
    background: #EDF3FA;
    width: 11px;
    height: 11px;
    margin: -4px 0;
    border-radius: 5px;
}
QWidget#youtubeOnlineRoot QListWidget#ytSuggestPopup {
    background: #151E2B;
    color: #EDF3FA;
    border: 1px solid #354962;
    border-radius: 10px;
    padding: 5px;
    outline: none;
    font-size: 13px;
}
QWidget#youtubeOnlineRoot QListWidget#ytSuggestPopup::item {
    padding: 7px 12px;
    border-radius: 6px;
}
QWidget#youtubeOnlineRoot QListWidget#ytSuggestPopup::item:hover,
QWidget#youtubeOnlineRoot QListWidget#ytSuggestPopup::item:selected {
    background: #213044;
    color: #A9F1D9;
}
"""

ACCOUNT_DIALOG_STYLE = """
QDialog#ytAccountDialog {
    background: #0D1118;
    color: #EDF3FA;
    font-family: 'Segoe UI', 'Malgun Gothic', 'Meiryo UI', 'Microsoft YaHei UI', sans-serif;
}
QDialog#ytAccountDialog QScrollArea {
    background: transparent;
    border: none;
}
QDialog#ytAccountDialog QScrollBar:vertical {
    background: #0D1118;
    width: 8px;
    border-radius: 4px;
    margin: 2px 0;
}
QDialog#ytAccountDialog QScrollBar::handle:vertical {
    background: #27364A;
    border-radius: 4px;
    min-height: 28px;
}
QDialog#ytAccountDialog QScrollBar::handle:vertical:hover {
    background: #3B516D;
}
QDialog#ytAccountDialog QScrollBar::add-line:vertical,
QDialog#ytAccountDialog QScrollBar::sub-line:vertical {
    height: 0px;
}
QDialog#ytAccountDialog QWidget#ytAccScrollBody {
    background: transparent;
    border: none;
}
QDialog#ytAccountDialog QLabel {
    background: transparent;
    border: none;
    color: #EDF3FA;
}
QDialog#ytAccountDialog QFrame#ytGuideCard {
    background: #102026;
    border: 1px solid #26544A;
    border-radius: 12px;
}
QDialog#ytAccountDialog QFrame#ytAccCard {
    background: #141C27;
    border: 1px solid #243347;
    border-radius: 12px;
}
QDialog#ytAccountDialog QLineEdit {
    background: #0F1620;
    color: #EDF3FA;
    border: 1px solid #2B3B50;
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 24px;
    font-size: 12px;
}
QDialog#ytAccountDialog QLineEdit:focus {
    border-color: #77E0BE;
}
QDialog#ytAccountDialog QLineEdit[vaultActive="true"] {
    background: #0F231E;
    color: #96F0D2;
    border: 1px solid #3C8F75;
    font-weight: 600;
}
QDialog#ytAccountDialog QPushButton#ytVaultMigrateBtn {
    background: #1B342D;
    color: #9AF3D6;
    border: 1px solid #3F957A;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 700;
}
QDialog#ytAccountDialog QPushButton#ytVaultMigrateBtn:hover {
    background: #24473D;
    border-color: #77E0BE;
}
QDialog#ytAccountDialog QComboBox {
    background: #0F1620;
    color: #EDF3FA;
    border: 1px solid #2B3B50;
    border-radius: 8px;
    padding: 6px 12px;
    min-height: 24px;
    font-size: 12px;
}
QDialog#ytAccountDialog QComboBox QAbstractItemView {
    background: #161F2D;
    color: #EDF3FA;
    border: 1px solid #354962;
    selection-background-color: #244D42;
}
QDialog#ytAccountDialog QPushButton {
    background: #1C2736;
    color: #EDF3FA;
    border: 1px solid #2E3F55;
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 24px;
    font-size: 12px;
    font-weight: 600;
}
QDialog#ytAccountDialog QPushButton:hover {
    background: #263549;
    border-color: #46607E;
}
QDialog#ytAccountDialog QPushButton#ytDlgPrimary {
    background: #77E0BE;
    color: #0B1117;
    border: none;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 12px;
    font-weight: 700;
}
QDialog#ytAccountDialog QPushButton#ytDlgPrimary:hover {
    background: #98EED3;
}
QDialog#ytAccountDialog QPushButton#ytDlgPrimary:disabled {
    background: #243445;
    color: #6B7D92;
}
"""


# =====================================================================
# ASYNC WORKERS & BOUNDED THUMBNAIL CACHE (WITH CIRCULAR AVATARS)
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
    """RAM-bounded async HTTP thumbnail/avatar loader (max 240 pixmaps, rounded/circular masks)."""

    MAX_CACHE = 240

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending: dict[str, list[tuple[weakref.ref, QSize, int]]] = {}
        self._active_replies: set[QNetworkReply] = set()

    def load(self, url: str, target_label: QLabel, target_size: QSize, *, radius: int = 8) -> None:
        u = str(url or "").strip()
        if not u:
            return
        if u in self._cache:
            pix = self._cache[u]
            self._cache.move_to_end(u)
            self._apply_pixmap(target_label, pix, target_size, radius)
            return
        ref = weakref.ref(target_label)
        if u in self._pending:
            self._pending[u].append((ref, target_size, radius))
            return
        self._pending[u] = [(ref, target_size, radius)]
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
                    for ref, sz, rad in targets:
                        lbl = ref()
                        if lbl is not None:
                            try:
                                self._apply_pixmap(lbl, pix, sz, rad)
                            except RuntimeError:
                                pass
        finally:
            reply.deleteLater()

    @staticmethod
    def _apply_pixmap(label: QLabel, pix: QPixmap, target_size: QSize, radius: int) -> None:
        if pix.isNull() or target_size.width() <= 0 or target_size.height() <= 0:
            return
        scaled = pix.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - target_size.width()) // 2)
        y = max(0, (scaled.height() - target_size.height()) // 2)
        cropped = scaled.copy(x, y, min(target_size.width(), scaled.width()), min(target_size.height(), scaled.height()))

        out = QPixmap(target_size)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        path = QPainterPath()
        r = min(radius, target_size.width() // 2, target_size.height() // 2)
        path.addRoundedRect(0, 0, target_size.width(), target_size.height(), r, r)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        label.setPixmap(out)

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
# CUSTOM INTERACTIVE WIDGETS (SEEK SLIDER, FLUID CARD, RELATED ROW)
# =====================================================================

class _ClickSeekSlider(QSlider):
    """YouTube-style progress bar supporting smooth drag scrubbing, click-to-seek & chapter tooltips."""

    drag_preview = Signal(int)
    seek_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("ytSeekSlider")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._chapters: list[OnlineChapter] = []
        self._dragging = False

    def set_chapters(self, chapters: list[OnlineChapter]) -> None:
        self._chapters = list(chapters or [])

    def _value_at_x(self, x: float) -> int:
        w = max(1, self.width())
        ratio = max(0.0, min(1.0, float(x) / float(w)))
        return int(round(self.minimum() + ratio * (self.maximum() - self.minimum())))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > 0:
            self._dragging = True
            val = self._value_at_x(event.position().x())
            self.setValue(val)
            self.drag_preview.emit(val)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.maximum() > 0:
            val_ms = self._value_at_x(event.position().x())
            if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
                self.setValue(val_ms)
                self.drag_preview.emit(val_ms)
                event.accept()
                return
            sec = val_ms / 1000.0
            tip = format_seconds_mmss(sec)
            for ch in self._chapters:
                if sec >= ch.start_sec and (ch.end_sec <= 0 or sec < ch.end_sec):
                    tip = f"{tip} · {ch.title}"
                    break
            self.setToolTip(tip)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            val = self._value_at_x(event.position().x())
            self.setValue(val)
            self.seek_requested.emit(val)
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _elide_two_lines(text: str, max_chars_per_line: int = 38) -> str:
    clean = " ".join(str(text or "").split())
    limit = max(24, max_chars_per_line * 2)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


class _OnlineVideoCard(QFrame):
    """Fluid 16:9 YouTube Desktop video/playlist/channel card with circular channel avatar."""

    clicked = Signal(object)
    channel_clicked = Signal(str, str)
    queue_clicked = Signal(object)
    download_clicked = Signal(object)

    def __init__(
        self,
        item: OnlineVideoItem,
        thumb_loader: _OnlineThumbnailLoader,
        *,
        card_width: int = 296,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.item = item
        self.setObjectName("ytCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        cw = max(248, int(card_width))
        tw = cw - 16
        th = max(130, int(round(tw * 9.0 / 16.0)))
        self.setFixedWidth(cw)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 10)
        root.setSpacing(8)

        # 16:9 Thumbnail container with crisp overlaid duration/LIVE badge
        thumb_wrap = QWidget()
        thumb_wrap.setFixedSize(tw, th)
        thumb_wrap.setStyleSheet("background: #0A0E15; border-radius: 9px;")
        t_grid = QGridLayout(thumb_wrap)
        t_grid.setContentsMargins(0, 0, 0, 0)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(tw, th)
        self.lbl_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_thumb.setStyleSheet("background: #0E1520; border-radius: 9px; color: #53657A; font-weight: 700;")
        if item.item_type == "channel":
            self.lbl_thumb.setText("CHANNEL")
        elif item.item_type == "playlist":
            self.lbl_thumb.setText("PLAYLIST")
        t_grid.addWidget(self.lbl_thumb, 0, 0)

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
                badge.setStyleSheet(
                    "background: #DC362E; color: #FFFFFF; border-radius: 5px; "
                    "padding: 2px 7px; font-size: 10px; font-weight: 800; margin: 6px;"
                )
            elif item.item_type == "playlist":
                badge.setStyleSheet(
                    "background: rgba(11, 16, 23, 225); color: #77E0BE; border: 1px solid #2A5F52; "
                    "border-radius: 5px; padding: 2px 7px; font-size: 11px; font-weight: 700; margin: 6px;"
                )
            else:
                badge.setStyleSheet(
                    "background: rgba(9, 13, 19, 225); color: #F2F6FB; "
                    "border-radius: 5px; padding: 2px 6px; font-size: 11px; font-weight: 600; margin: 6px;"
                )
            t_grid.addWidget(badge, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        root.addWidget(thumb_wrap)

        # Info Row: Circular Channel Avatar + Title & Channel/Stats + Quick Actions
        info_row = QHBoxLayout()
        info_row.setContentsMargins(2, 0, 2, 0)
        info_row.setSpacing(9)

        avatar_lbl = QLabel()
        avatar_lbl.setFixedSize(32, 32)
        avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        initials = (item.channel_name or item.title or "Y").strip()[:1].upper()
        avatar_lbl.setText(initials)
        avatar_lbl.setStyleSheet(
            "background: #1D293A; color: #8DE7CA; border-radius: 16px; font-size: 12px; font-weight: 700;"
        )
        if item.channel_avatar:
            thumb_loader.load(item.channel_avatar, avatar_lbl, QSize(32, 32), radius=16)
        info_row.addWidget(avatar_lbl, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)

        chars_per_line = max(24, (tw - 60) // 7)
        lbl_title = QLabel(_elide_two_lines(item.title, chars_per_line))
        lbl_title.setWordWrap(True)
        lbl_title.setFixedHeight(40)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lbl_title.setStyleSheet("color: #EDF3FA; font-size: 13px; font-weight: 600;")
        lbl_title.setToolTip(item.title)
        text_col.addWidget(lbl_title)

        meta_bottom = QHBoxLayout()
        meta_bottom.setContentsMargins(0, 0, 0, 0)
        meta_bottom.setSpacing(4)

        sub_col = QVBoxLayout()
        sub_col.setContentsMargins(0, 0, 0, 0)
        sub_col.setSpacing(1)

        ch_name = item.channel_name or ("YouTube" if item.item_type != "channel" else item.title)
        ch_btn = QPushButton(ch_name[:28] + ("…" if len(ch_name) > 28 else ""))
        ch_btn.setObjectName("ytCardChannel")
        ch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ch_btn.setToolTip(ch_name)
        ch_btn.clicked.connect(lambda: self.channel_clicked.emit(item.channel_id, ch_name))
        sub_col.addWidget(ch_btn)

        stats_parts = [p for p in (item.views_text, item.published_text) if p]
        stats_str = " • ".join(stats_parts) if stats_parts else ("Playlist" if item.item_type == "playlist" else "")
        lbl_stats = QLabel(stats_str)
        lbl_stats.setStyleSheet("color: #7D90A6; font-size: 11px;")
        sub_col.addWidget(lbl_stats)
        meta_bottom.addLayout(sub_col, 1)

        if item.item_type == "video":
            btn_q = QPushButton()
            btn_q.setObjectName("ytIconBtn")
            btn_q.setFixedSize(26, 26)
            button_icon(btn_q, "plus", tr_pair("Thêm vào hàng đợi", "Add to queue"), color=MUTED, size=14)
            btn_q.clicked.connect(lambda: self.queue_clicked.emit(self.item))
            meta_bottom.addWidget(btn_q)

            btn_dl = QPushButton()
            btn_dl.setObjectName("ytIconBtn")
            btn_dl.setFixedSize(26, 26)
            button_icon(btn_dl, "download", tr_pair("Tải về BoTube", "Download to BoTube"), color=MUTED, size=14)
            btn_dl.clicked.connect(lambda: self.download_clicked.emit(self.item))
            meta_bottom.addWidget(btn_dl)

        text_col.addLayout(meta_bottom)
        info_row.addLayout(text_col, 1)
        root.addLayout(info_row)

        if item.thumbnail_url:
            thumb_loader.load(item.thumbnail_url, self.lbl_thumb, QSize(tw, th), radius=9)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _CompactRelatedRow(QFrame):
    """Unclipped YouTube Watch right-column Up Next / Queue compact card."""

    clicked = Signal(object)

    THUMB_SIZE = QSize(132, 74)

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
        self.setObjectName("ytRelRowActive" if is_active else "ytRelRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(90)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(7, 7, 8, 7)
        row.setSpacing(10)

        if index_num is not None:
            lbl_idx = QLabel("▶" if is_active else str(index_num))
            lbl_idx.setFixedWidth(18)
            lbl_idx.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_idx.setStyleSheet(f"color: {'#77E0BE' if is_active else '#7D90A6'}; font-size: 11px; font-weight: 700;")
            row.addWidget(lbl_idx)

        thumb_wrap = QWidget()
        thumb_wrap.setFixedSize(self.THUMB_SIZE)
        thumb_wrap.setStyleSheet("background: #0A0E14; border-radius: 7px;")
        t_grid = QGridLayout(thumb_wrap)
        t_grid.setContentsMargins(0, 0, 0, 0)

        lbl_thumb = QLabel()
        lbl_thumb.setFixedSize(self.THUMB_SIZE)
        lbl_thumb.setStyleSheet("background: #101722; border-radius: 7px;")
        t_grid.addWidget(lbl_thumb, 0, 0)

        if item.duration_text:
            dur = QLabel(item.duration_text)
            dur.setStyleSheet(
                "background: rgba(9, 13, 19, 225); color: #EDF3FA; border-radius: 4px; "
                "padding: 1px 5px; font-size: 10px; font-weight: 600; margin: 4px;"
            )
            t_grid.addWidget(dur, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        row.addWidget(thumb_wrap)

        col = QVBoxLayout()
        col.setContentsMargins(0, 1, 0, 1)
        col.setSpacing(3)

        lbl_t = QLabel(_elide_two_lines(item.title, 26))
        lbl_t.setWordWrap(True)
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lbl_t.setStyleSheet(f"color: {'#A9F1D9' if is_active else '#EDF3FA'}; font-size: 12px; font-weight: 600;")
        lbl_t.setToolTip(item.title)
        col.addWidget(lbl_t)

        lbl_ch = QLabel(item.channel_name or "YouTube")
        lbl_ch.setStyleSheet("color: #9AAABC; font-size: 11px;")
        col.addWidget(lbl_ch)

        stats = " • ".join(p for p in (item.views_text, item.published_text) if p)
        if stats:
            lbl_v = QLabel(stats[:34] + ("…" if len(stats) > 34 else ""))
            lbl_v.setStyleSheet("color: #74879C; font-size: 11px;")
            col.addWidget(lbl_v)
        col.addStretch(1)
        row.addLayout(col, 1)

        if item.thumbnail_url:
            thumb_loader.load(item.thumbnail_url, lbl_thumb, self.THUMB_SIZE, radius=7)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# =====================================================================
# STREAMLINED ACCOUNT & PLAYLIST SYNC DIALOG (1-CLICK VERIFICATION)
# =====================================================================

class _YouTubeAccountDialog(QDialog):
    """Clean, commercial YouTube Account Connection & Playlist Import dialog."""

    playlist_import_requested = Signal(str, str)  # (url_or_special, title_hint)

    def __init__(
        self,
        profile: YouTubeOnlineProfileStore,
        client: YouTubeOnlineClient | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("ytAccountDialog")
        self.profile = profile
        self.client = client or YouTubeOnlineClient(profile_store=profile)
        self._verify_worker: _TaskWorker | None = None
        self._vault_active: bool = False

        self.setWindowTitle(tr_pair("Tài khoản YouTube & Đồng bộ", "YouTube Account & Sync"))
        self.setStyleSheet(ACCOUNT_DIALOG_STYLE)
        self.setMinimumSize(640, 560)
        scr = QGuiApplication.primaryScreen()
        max_h = (scr.availableGeometry().height() - 60) if scr is not None else 760
        self.resize(690, min(760, max(580, max_h)))

        outer_root = QVBoxLayout(self)
        outer_root.setContentsMargins(20, 16, 20, 16)
        outer_root.setSpacing(12)

        hdr = QLabel(tr_pair("Kết nối Tài khoản YouTube & Cài đặt AI", "Connect YouTube Account & AI Settings"))
        hdr.setStyleSheet("font-size: 18px; font-weight: 700; color: #F4F8FD;")
        outer_root.addWidget(hdr)

        # Scrollable cards body so controls NEVER get vertically squished or clipped at any DPI!
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("ytAccScrollBody")
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 6, 4)
        root.setSpacing(12)

        # GUIDE CARD RIGHT AT THE TOP: Clear 30-second Cookie extraction instructions
        guide_card = QFrame()
        guide_card.setObjectName("ytGuideCard")
        gl = QVBoxLayout(guide_card)
        gl.setContentsMargins(16, 12, 16, 12)
        gl.setSpacing(6)
        lbl_g_title = QLabel(
            tr_pair(
                "📘 Hướng dẫn lấy Cookie YouTube chuẩn nhất (30 giây — an toàn 100%, chỉ đọc)",
                "📘 Quick Guide: Connect YouTube Cookies Safely (30 seconds — 100% read-only)",
            )
        )
        lbl_g_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #8DE7CA;")
        ext_name = "Get cookies.txt LOCALLY"
        ext_url = "https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
        lbl_g_body = QLabel(
            tr_pair(
                "• <b>Cách 1 (Nhanh nhất):</b> Đăng nhập YouTube trên <b>Firefox</b> → chọn <i>Firefox</i> ở mục 1 bên dưới → bấm <b>Kiểm tra &amp; Kết nối</b>.<br>"
                "• <b>Cách 2 (Dùng Chrome / Edge / Cốc Cốc — không bị lỗi khóa):</b><br>"
                f"&nbsp;&nbsp;1. Cài đúng tiện ích mã nguồn mở <b>“{ext_name}”</b> tại "
                f'<a href="{ext_url}" style="color:#77E0BE;text-decoration:underline;">Chrome Web Store</a>.<br>'
                "&nbsp;&nbsp;2. Mở <b>youtube.com</b> (đã đăng nhập) → bấm biểu tượng tiện ích → bấm <b>Export</b> tải tệp <code>cookies.txt</code>.<br>"
                "&nbsp;&nbsp;3. Bấm <b>Chọn file</b> ở mục 1 bên dưới → BoTube tự <b>mã hóa kín (Windows DPAPI)</b> vào Két riêng &amp; <b>tự xóa tệp gốc trong Downloads</b> → bấm <b>Kiểm tra &amp; Kết nối</b>.<br>"
                "<span style='color:#92B7AD;'>💡 Mẹo giữ phiên 6+ tháng: đăng nhập YouTube ở <b>Cửa sổ Ẩn danh</b> → Export → đóng cửa sổ Ẩn danh (không bấm Đăng xuất). Cookie chỉ mã hóa cục bộ theo tài khoản Windows của bạn.</span>",
                "• <b>Method 1 (Fastest):</b> Sign in to YouTube in <b>Firefox</b> → pick <i>Firefox</i> below → click <b>Test &amp; Connect</b>.<br>"
                "• <b>Method 2 (Chrome / Edge / Brave — never locked):</b><br>"
                f"&nbsp;&nbsp;1. Install the open-source extension <b>“{ext_name}”</b> from "
                f'<a href="{ext_url}" style="color:#77E0BE;text-decoration:underline;">Chrome Web Store</a>.<br>'
                "&nbsp;&nbsp;2. Open signed-in <b>youtube.com</b> → click the extension → <b>Export</b> to save <code>cookies.txt</code>.<br>"
                "&nbsp;&nbsp;3. Click <b>Browse</b> below → BoTube automatically <b>encrypts it with Windows DPAPI</b> into its private Vault &amp; <b>shreds the Downloads copy</b> → click <b>Test &amp; Connect</b>.<br>"
                "<span style='color:#92B7AD;'>💡 6+ Month Tip: sign in to YouTube inside an <b>Incognito window</b> → Export → close window (without clicking Sign out). Vault is encrypted locally for your Windows user only.</span>",
            )
        )
        lbl_g_body.setTextFormat(Qt.TextFormat.RichText)
        lbl_g_body.setWordWrap(True)
        lbl_g_body.setOpenExternalLinks(True)
        lbl_g_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lbl_g_body.setStyleSheet("color: #C7D7E7; font-size: 12px; line-height: 1.45;")
        gl.addWidget(lbl_g_title)
        gl.addWidget(lbl_g_body)

        g_btns = QHBoxLayout()
        g_btns.setSpacing(8)
        self.btn_copy_ext_name = QPushButton(tr_pair("📋 Copy tên tiện ích", "📋 Copy Extension Name"))
        self.btn_copy_ext_name.setFixedHeight(32)
        self.btn_copy_ext_name.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_ext_name.clicked.connect(lambda: self._copy_guide_text(ext_name, self.btn_copy_ext_name, tr_pair("📋 Copy tên tiện ích", "📋 Copy Extension Name")))

        self.btn_copy_ext_link = QPushButton(tr_pair("🔗 Copy link cài", "🔗 Copy Store Link"))
        self.btn_copy_ext_link.setFixedHeight(32)
        self.btn_copy_ext_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_ext_link.clicked.connect(lambda: self._copy_guide_text(ext_url, self.btn_copy_ext_link, tr_pair("🔗 Copy link cài", "🔗 Copy Store Link")))

        self.btn_open_ext_store = QPushButton(tr_pair("🌐 Mở Chrome Web Store", "🌐 Open Chrome Web Store"))
        self.btn_open_ext_store.setFixedHeight(32)
        self.btn_open_ext_store.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_ext_store.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ext_url)))

        g_btns.addWidget(self.btn_copy_ext_name)
        g_btns.addWidget(self.btn_copy_ext_link)
        g_btns.addWidget(self.btn_open_ext_store)
        g_btns.addStretch(1)
        gl.addLayout(g_btns)
        root.addWidget(guide_card)

        # CARD 1: 1-Click Browser / Cookie Account Connect + Instant Liked / Watch Later
        card_acc = QFrame()
        card_acc.setObjectName("ytAccCard")
        al = QVBoxLayout(card_acc)
        al.setContentsMargins(16, 14, 16, 14)
        al.setSpacing(10)

        lbl_acc = QLabel(tr_pair("1. Kết nối phiên YouTube sẵn có (1-Click)", "1. Connect Existing YouTube Session (1-Click)"))
        lbl_acc.setStyleSheet("font-size: 13px; font-weight: 700; color: #8DE7CA;")
        al.addWidget(lbl_acc)

        br_row = QHBoxLayout()
        br_row.setSpacing(8)
        self.combo_browser = QComboBox()
        self.combo_browser.setFixedHeight(36)
        self.combo_browser.setMinimumWidth(0)
        self.combo_browser.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.combo_browser.setProperty("_i18n_safe_combo", True)
        for val, vi_l, en_l in (
            ("", "Không dùng (Chỉ dùng Hồ sơ cục bộ BoTube)", "None (Local BoTube Profile only)"),
            ("firefox", "Firefox (Khuyên dùng — không bị khóa)", "Firefox (Recommended — never locked)"),
            ("edge", "Microsoft Edge", "Microsoft Edge"),
            ("chrome", "Google Chrome", "Google Chrome"),
            ("brave", "Brave", "Brave"),
        ):
            self.combo_browser.addItem(tr_pair(vi_l, en_l), val)
        cur_br = str(profile.get_pref("cookies_browser", "") or "")
        idx_br = self.combo_browser.findData(cur_br)
        if idx_br >= 0:
            self.combo_browser.setCurrentIndex(idx_br)

        self.btn_verify = QPushButton(tr_pair("Kiểm tra && Kết nối", "Test && Connect"))
        self.btn_verify.setObjectName("ytDlgPrimary")
        self.btn_verify.setFixedHeight(36)
        self.btn_verify.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_verify.clicked.connect(self._on_verify_connection)
        br_row.addWidget(self.combo_browser, 1)
        br_row.addWidget(self.btn_verify)
        al.addLayout(br_row)

        cf_row = QHBoxLayout()
        cf_row.setSpacing(8)
        raw_cf = str(profile.get_pref("cookies_file", "") or "").strip()
        self.txt_cookie_file = QLineEdit()
        self.txt_cookie_file.setFixedHeight(36)
        self.txt_cookie_file.setPlaceholderText(
            tr_pair("Chọn tệp cookies.txt để mã hóa vào Két BoTube (DPAPI)...", "Select cookies.txt to encrypt into BoTube Vault (DPAPI)...")
        )
        btn_cf = QPushButton(tr_pair("Chọn file", "Browse"))
        btn_cf.setFixedHeight(36)
        btn_cf.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cf.clicked.connect(self._browse_cookie_file)
        btn_cf_clr = QPushButton(tr_pair("Xóa", "Clear"))
        btn_cf_clr.setFixedHeight(36)
        btn_cf_clr.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cf_clr.clicked.connect(self._clear_cookie_file)
        cf_row.addWidget(self.txt_cookie_file, 1)
        cf_row.addWidget(btn_cf)
        cf_row.addWidget(btn_cf_clr)
        al.addLayout(cf_row)

        self.chk_auto_wipe_source = QCheckBox(
            tr_pair(
                "Tự động xóa an toàn tệp cookies.txt gốc (Downloads) ngay sau khi mã hóa vào Két BoTube",
                "Automatically shred original cookies.txt (Downloads) right after encrypting into Vault",
            )
        )
        self.chk_auto_wipe_source.setStyleSheet(
            "QCheckBox { color: #B8D7CE; font-size: 12px; spacing: 8px; padding: 1px 0; }"
        )
        self.chk_auto_wipe_source.setChecked(bool(profile.get_pref("cookie_auto_wipe_source", True)))
        al.addWidget(self.chk_auto_wipe_source)

        self.btn_migrate_vault = QPushButton(
            tr_pair(
                "🔒 Mã hóa tệp cookies.txt này vào Két kín (Windows DPAPI) && xóa bản gốc",
                "🔒 Encrypt This cookies.txt into Private Vault (Windows DPAPI) && Wipe Original",
            )
        )
        self.btn_migrate_vault.setObjectName("ytVaultMigrateBtn")
        self.btn_migrate_vault.setFixedHeight(34)
        self.btn_migrate_vault.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_migrate_vault.clicked.connect(self._on_migrate_existing_cookie_file)
        al.addWidget(self.btn_migrate_vault)

        if raw_cf == COOKIE_VAULT_SENTINEL and has_cookie_vault():
            self._apply_vault_ui_state(active=True)
        else:
            initial_txt = "" if raw_cf == COOKIE_VAULT_SENTINEL else raw_cf
            self._apply_vault_ui_state(active=False, plain_path=initial_txt)
        self.txt_cookie_file.textChanged.connect(self._refresh_migrate_button_visibility)

        self.lbl_verify_status = QLabel("")
        self.lbl_verify_status.setWordWrap(True)
        self.lbl_verify_status.setStyleSheet("color: #9AAABC; font-size: 12px; padding: 4px 0;")
        self.lbl_verify_status.hide()
        al.addWidget(self.lbl_verify_status)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        btn_liked = QPushButton(tr_pair("❤️ Mở Video đã thích trên YouTube", "❤️ Open YouTube Liked Videos"))
        btn_liked.setFixedHeight(36)
        btn_liked.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_liked.clicked.connect(lambda: self._open_special_playlist(":ytfav", tr_pair("Video đã thích (YouTube)", "Liked Videos (YouTube)")))
        btn_wl = QPushButton(tr_pair("🕒 Mở Xem sau (Watch Later)", "🕒 Open Watch Later"))
        btn_wl.setFixedHeight(36)
        btn_wl.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_wl.clicked.connect(lambda: self._open_special_playlist(":ytwatchlater", tr_pair("Xem sau (YouTube)", "Watch Later (YouTube)")))
        quick_row.addWidget(btn_liked, 1)
        quick_row.addWidget(btn_wl, 1)
        al.addLayout(quick_row)
        root.addWidget(card_acc)

        # CARD 2: Instant Playlist URL Import (Works even WITHOUT cookies for Public/Unlisted!)
        card_pl = QFrame()
        card_pl.setObjectName("ytAccCard")
        pl_lay = QVBoxLayout(card_pl)
        pl_lay.setContentsMargins(16, 14, 16, 14)
        pl_lay.setSpacing(8)
        lbl_pl = QLabel(tr_pair("2. Nghe ngay bất kỳ Playlist YouTube / YouTube Music nào", "2. Play Any YouTube / YouTube Music Playlist"))
        lbl_pl.setStyleSheet("font-size: 13px; font-weight: 700; color: #EDF3FA;")
        pl_lay.addWidget(lbl_pl)

        pl_row = QHBoxLayout()
        pl_row.setSpacing(8)
        self.txt_pl_url = QLineEdit()
        self.txt_pl_url.setFixedHeight(36)
        self.txt_pl_url.setPlaceholderText("https://www.youtube.com/playlist?list=...")
        btn_imp_pl = QPushButton(tr_pair("Mở Playlist", "Open Playlist"))
        btn_imp_pl.setObjectName("ytDlgPrimary")
        btn_imp_pl.setFixedHeight(36)
        btn_imp_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_imp_pl.clicked.connect(self._on_import_playlist)
        pl_row.addWidget(self.txt_pl_url, 1)
        pl_row.addWidget(btn_imp_pl)
        pl_lay.addLayout(pl_row)
        root.addWidget(card_pl)

        # CARD 3: Local BoTube Profile, YouTube AI Whisper & Translation Toggles + Takeout CSV
        card_loc = QFrame()
        card_loc.setObjectName("ytAccCard")
        loc_outer = QVBoxLayout(card_loc)
        loc_outer.setContentsMargins(16, 14, 16, 14)
        loc_outer.setSpacing(10)

        lbl_ai_hdr = QLabel(tr_pair("3. Phụ đề AI Whisper & Hồ sơ YouTube BoTube", "3. YouTube Whisper AI Subtitles & Local Profile"))
        lbl_ai_hdr.setStyleSheet("font-size: 13px; font-weight: 700; color: #EDF3FA;")
        loc_outer.addWidget(lbl_ai_hdr)

        ai_ok_sys, _ai_reason = is_bo_ai_subtitle_available(None)
        chk_qss = "QCheckBox { color: #DCE6F2; font-size: 12px; spacing: 8px; padding: 2px 0; } QCheckBox:disabled { color: #647589; }"
        self.chk_allow_ai_sub = QCheckBox(
            tr_pair(
                "Bật AI Whisper tạo phụ đề trên tab YouTube (bỏ chọn để tắt AI Whisper)",
                "Enable Whisper AI subtitles on YouTube (uncheck to disable Whisper AI)",
            )
        )
        self.chk_allow_ai_sub.setStyleSheet(chk_qss)
        self.chk_allow_ai_translate = QCheckBox(
            tr_pair(
                "Tự động dịch AI (Song ngữ / Việt) — bỏ chọn để chỉ chạy Whisper lời gốc",
                "Enable AI Translation (Bilingual) — uncheck for original Whisper lyrics only",
            )
        )
        self.chk_allow_ai_translate.setStyleSheet(chk_qss)
        if ai_ok_sys:
            allow_sub = bool(profile.get_pref("allow_ai_sub", True))
            self.chk_allow_ai_sub.setChecked(allow_sub)
            self.chk_allow_ai_translate.setChecked(bool(profile.get_pref("allow_ai_translate", True)))
            self.chk_allow_ai_translate.setEnabled(allow_sub)
            self.chk_allow_ai_sub.toggled.connect(self.chk_allow_ai_translate.setEnabled)
        else:
            self.chk_allow_ai_sub.setChecked(False)
            self.chk_allow_ai_sub.setEnabled(False)
            self.chk_allow_ai_translate.setChecked(False)
            self.chk_allow_ai_translate.setEnabled(False)
            tip = tr_pair(
                "Máy chưa cài gói tài nguyên AI (Whisper) hoặc đã tắt trong Cài đặt BoTube.",
                "Whisper AI resources are not installed or AI is disabled in BoTube Settings.",
            )
            self.chk_allow_ai_sub.setToolTip(tip)
            self.chk_allow_ai_translate.setToolTip(tip)
        loc_outer.addWidget(self.chk_allow_ai_sub)
        loc_outer.addWidget(self.chk_allow_ai_translate)

        ll = QHBoxLayout()
        ll.setSpacing(10)
        subs_n = len(profile.list_subscriptions())
        likes_n = len(profile.list_liked())
        wl_n = len(profile.list_watch_later())
        pls_n = len(profile.list_playlists())
        lbl_loc = QLabel(
            tr_pair(
                f"Hồ sơ cục bộ: {subs_n} kênh · {pls_n} playlist · {wl_n} xem sau · {likes_n} đã thích",
                f"Local profile: {subs_n} channels · {pls_n} playlists · {wl_n} watch later · {likes_n} liked",
            )
        )
        lbl_loc.setStyleSheet("color: #BAC8D8; font-size: 12px; font-weight: 600;")
        btn_csv = QPushButton(tr_pair("Nhập kênh từ .CSV", "Import Channels .CSV"))
        btn_csv.setFixedHeight(34)
        btn_csv.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_csv.clicked.connect(self._on_import_csv)
        ll.addWidget(lbl_loc, 1)
        ll.addWidget(btn_csv)
        loc_outer.addLayout(ll)
        root.addWidget(card_loc)
        root.addStretch(1)

        scroll.setWidget(body)
        outer_root.addWidget(scroll, 1)

        # Pinned Footer Save / Close
        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_close = QPushButton(tr_pair("Đóng", "Close"))
        btn_close.setFixedHeight(36)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.reject)
        btn_save = QPushButton(tr_pair("Lưu cấu hình", "Save Settings"))
        btn_save.setObjectName("ytDlgPrimary")
        btn_save.setFixedHeight(36)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.clicked.connect(self._on_save)
        foot.addWidget(btn_close)
        foot.addWidget(btn_save)
        outer_root.addLayout(foot)

    def _copy_guide_text(self, value: str, btn: QPushButton, orig_label: str) -> None:
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(str(value))
        btn.setText(tr_pair("✓ Đã copy!", "✓ Copied!"))
        QTimer.singleShot(1600, lambda b=btn, lbl=orig_label: b.setText(lbl))

    def _apply_vault_ui_state(self, *, active: bool, plain_path: str = "") -> None:
        self._vault_active = bool(active)
        self.txt_cookie_file.blockSignals(True)
        if self._vault_active:
            self.txt_cookie_file.setReadOnly(True)
            self.txt_cookie_file.setProperty("vaultActive", "true")
            self.txt_cookie_file.setText(
                tr_pair(
                    "🔒 Két mã hóa BoTube (Windows DPAPI · An toàn)",
                    "🔒 BoTube Encrypted Vault (Windows DPAPI · Safe)",
                )
            )
            self.txt_cookie_file.setCursorPosition(0)
        else:
            self.txt_cookie_file.setReadOnly(False)
            self.txt_cookie_file.setProperty("vaultActive", "false")
            self.txt_cookie_file.setText(plain_path)
        self.txt_cookie_file.blockSignals(False)
        self.txt_cookie_file.style().unpolish(self.txt_cookie_file)
        self.txt_cookie_file.style().polish(self.txt_cookie_file)
        self._refresh_migrate_button_visibility()

    def _refresh_migrate_button_visibility(self) -> None:
        if self._vault_active:
            self.btn_migrate_vault.hide()
            return
        cur = self.txt_cookie_file.text().strip()
        show = bool(cur and cur != COOKIE_VAULT_SENTINEL and Path(cur).is_file())
        self.btn_migrate_vault.setVisible(show)

    def _import_cookie_file_into_vault(self, source_path: str | Path) -> bool:
        wipe_src = bool(self.chk_auto_wipe_source.isChecked())
        ok, msg = import_cookies_into_vault(source_path, wipe_source=wipe_src)
        if ok:
            self._apply_vault_ui_state(active=True)
            self.profile.set_pref("cookie_auto_wipe_source", wipe_src)
            self.profile.set_pref("cookies_file", COOKIE_VAULT_SENTINEL)
            self.lbl_verify_status.setStyleSheet("color: #77E0BE; font-size: 12px; font-weight: 600;")
            self.lbl_verify_status.setText(msg)
            self.lbl_verify_status.show()
            return True
        self.lbl_verify_status.setStyleSheet("color: #F29C9C; font-size: 12px;")
        self.lbl_verify_status.setText(f"⚠️ {msg}")
        self.lbl_verify_status.show()
        return False

    def _on_migrate_existing_cookie_file(self) -> None:
        cur = self.txt_cookie_file.text().strip()
        if cur and not self._vault_active:
            self._import_cookie_file_into_vault(cur)

    def _clear_cookie_file(self) -> None:
        had_vault = self._vault_active or has_cookie_vault()
        delete_cookie_vault()
        self._apply_vault_ui_state(active=False, plain_path="")
        self.profile.set_pref("cookies_file", "")
        if had_vault:
            self.lbl_verify_status.setStyleSheet("color: #9AAABC; font-size: 12px;")
            self.lbl_verify_status.setText(
                tr_pair(
                    "🗑️ Đã ghi đè xóa sạch Két Cookie mã hóa của BoTube.",
                    "🗑️ Securely wiped and deleted BoTube's encrypted Cookie Vault.",
                )
            )
            self.lbl_verify_status.show()

    def _save_cookie_prefs(self) -> tuple[str, str]:
        br = str(self.combo_browser.currentData() or "")
        if self._vault_active and has_cookie_vault():
            cf = COOKIE_VAULT_SENTINEL
        else:
            raw_txt = self.txt_cookie_file.text().strip()
            cf = "" if self._vault_active else raw_txt
        self.profile.set_pref("cookies_browser", br)
        self.profile.set_pref("cookies_file", cf)
        if hasattr(self, "chk_auto_wipe_source"):
            self.profile.set_pref("cookie_auto_wipe_source", bool(self.chk_auto_wipe_source.isChecked()))
        if hasattr(self, "chk_allow_ai_sub") and self.chk_allow_ai_sub.isEnabled():
            self.profile.set_pref("allow_ai_sub", bool(self.chk_allow_ai_sub.isChecked()))
            self.profile.set_pref("allow_ai_translate", bool(self.chk_allow_ai_translate.isChecked()))
        return br, cf

    def _on_verify_connection(self) -> None:
        br, cf = self._save_cookie_prefs()
        self.btn_verify.setEnabled(False)
        self.lbl_verify_status.setStyleSheet("color: #8DE7CA; font-size: 12px;")
        self.lbl_verify_status.setText(tr_pair("Đang kiểm tra kết nối phiên YouTube…", "Checking YouTube session…"))
        self.lbl_verify_status.show()

        if self._verify_worker is not None:
            self._verify_worker.cancel()
        w = _TaskWorker(
            1,
            lambda procs: self.client.verify_cookie_connection(
                cookies_browser=br, cookies_file=cf, processes=procs
            ),
            pass_processes=True,
            parent=self,
        )
        w.finished_ok.connect(self._on_verify_done)
        w.failed.connect(lambda _g, m: self._on_verify_done(1, (False, m, 0)))
        w.finished.connect(w.deleteLater)
        self._verify_worker = w
        w.start()

    def _on_verify_done(self, _gen: int, payload: tuple[bool, str, int]) -> None:
        self._verify_worker = None
        self.btn_verify.setEnabled(True)
        ok, msg, count = payload
        if ok:
            self.lbl_verify_status.setStyleSheet("color: #77E0BE; font-size: 12px; font-weight: 600;")
            self.lbl_verify_status.setText(
                tr_pair(
                    f"✅ Đã kết nối tài khoản YouTube thành công ({msg})! Bấm nút bên dưới để mở Video đã thích hoặc dán link Playlist Riêng tư.",
                    f"✅ Connected to YouTube account ({msg})! Open Liked Videos below or paste any private playlist URL.",
                )
            )
        else:
            self.lbl_verify_status.setStyleSheet("color: #F29C9C; font-size: 12px;")
            self.lbl_verify_status.setText(f"⚠️ {msg}")
        self.lbl_verify_status.show()

    def _open_special_playlist(self, target: str, title_hint: str) -> None:
        self._save_cookie_prefs()
        self.playlist_import_requested.emit(target, title_hint)
        self.accept()

    def _on_import_playlist(self) -> None:
        url = self.txt_pl_url.text().strip()
        if not url:
            return
        self._save_cookie_prefs()
        self.playlist_import_requested.emit(url, "")
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
            tr_pair("Chọn tệp cookies.txt để mã hóa vào Két BoTube", "Select cookies.txt to encrypt into BoTube Vault"),
            "",
            "Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._import_cookie_file_into_vault(path)

    def _on_save(self) -> None:
        self._save_cookie_prefs()
        self.accept()

    def closeEvent(self, event) -> None:
        if self._verify_worker is not None:
            self._verify_worker.cancel()
            self._verify_worker.wait(500)
        super().closeEvent(event)


# =====================================================================
# ISOLATED FLOATING ALWAYS-ON-TOP YOUTUBE MINI-PLAYER (PIP WINDOW)
# =====================================================================

class _YouTubeMiniPlayerWindow(QWidget):
    """Floating Picture-in-Picture mini-player for YouTube Online (zero edits to offline MiniPlayer)."""

    prev_requested = Signal()
    play_pause_requested = Signal()
    next_requested = Signal()
    restore_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("ytPipMiniWindow")
        self.setMinimumSize(320, 214)
        self.resize(432, 286)
        self.setStyleSheet(
            "QWidget#ytPipMiniWindow { background: #0C1118; border: 1px solid #30455D; border-radius: 12px; "
            "font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; }"
            "QLabel#ytPipTitle { color: #EDF3FA; font-size: 12px; font-weight: 700; background: transparent; border: none; }"
            "QPushButton#ytPipBtn { background: transparent; border: none; border-radius: 8px; padding: 4px; color: #DCE6F2; }"
            "QPushButton#ytPipBtn:hover { background: #1E2C3E; }"
            "QPushButton#ytPipPlay { background: #77E0BE; border: none; border-radius: 15px; padding: 0; }"
            "QPushButton#ytPipPlay:hover { background: #98EED3; }"
        )
        self._drag_offset: QPoint | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Draggable slim top bar
        hdr = QHBoxLayout()
        hdr.setContentsMargins(6, 0, 2, 0)
        hdr.setSpacing(6)
        self.lbl_title = QLabel("YouTube Hi-Fi")
        self.lbl_title.setObjectName("ytPipTitle")
        self.btn_restore = QPushButton()
        self.btn_restore.setObjectName("ytPipBtn")
        self.btn_restore.setFixedSize(26, 26)
        self.btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_restore, "maximize", tr_pair("Quay lại cửa sổ lớn", "Restore full player"), color=ACCENT, size=14)
        self.btn_restore.clicked.connect(self.restore_requested.emit)
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("ytPipBtn")
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_close, "x", tr_pair("Đóng Mini-Player", "Close Mini-Player"), color=TEXT, size=14)
        self.btn_close.clicked.connect(self.restore_requested.emit)
        hdr.addWidget(self.lbl_title, 1)
        hdr.addWidget(self.btn_restore)
        hdr.addWidget(self.btn_close)
        root.addLayout(hdr)

        # Stage host (reparents live stage_frame with 1080p/4K video + floating subtitles!)
        self.stage_host = QWidget()
        self.stage_lay = QVBoxLayout(self.stage_host)
        self.stage_lay.setContentsMargins(0, 0, 0, 0)
        self.stage_lay.setSpacing(0)
        root.addWidget(self.stage_host, 1)

        # Compact bottom transport + resize grip
        foot = QHBoxLayout()
        foot.setContentsMargins(6, 0, 2, 0)
        foot.setSpacing(8)
        foot.addStretch(1)

        self.btn_prev = QPushButton()
        self.btn_prev.setObjectName("ytPipBtn")
        self.btn_prev.setFixedSize(28, 28)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_prev, "skip-back", "Previous", color=TEXT, size=15)
        self.btn_prev.clicked.connect(self.prev_requested.emit)

        self.btn_play = QPushButton()
        self.btn_play.setObjectName("ytPipPlay")
        self.btn_play.setFixedSize(30, 30)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_play, "pause", "Play / Pause", color=INK, size=15)
        self.btn_play.clicked.connect(self.play_pause_requested.emit)

        self.btn_next = QPushButton()
        self.btn_next.setObjectName("ytPipBtn")
        self.btn_next.setFixedSize(28, 28)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_next, "skip-forward", "Next", color=TEXT, size=15)
        self.btn_next.clicked.connect(self.next_requested.emit)

        foot.addWidget(self.btn_prev)
        foot.addWidget(self.btn_play)
        foot.addWidget(self.btn_next)
        foot.addStretch(1)
        foot.addWidget(QSizeGrip(self), 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        root.addLayout(foot)

    def set_playing(self, playing: bool) -> None:
        button_icon(self.btn_play, "pause" if playing else "play", "Play / Pause", color=INK, size=15)

    def set_title(self, title: str) -> None:
        clean = " ".join(str(title or "YouTube Hi-Fi").split())
        self.lbl_title.setText(clean[:44] + ("…" if len(clean) > 44 else ""))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.restore_requested.emit()


class _YouTubePillWindow(QWidget):
    """BoTube's signature Dynamic Island Pill (Viên thuốc) adapted exclusively for YouTube Online."""

    prev_requested = Signal()
    play_pause_requested = Signal()
    next_requested = Signal()
    pip_switch_requested = Signal()
    restore_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("ytPillWindow")
        self.setFixedSize(472, 68)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.container = QWidget(self)
        self.container.setObjectName("ytPillContainer")
        self.container.setGeometry(10, 4, 452, 60)
        self.container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setStyleSheet(
            "QWidget#ytPillWindow { background: transparent; }"
            "QWidget#ytPillContainer { background: #101722; border: 1px solid #3D546D; border-radius: 30px; "
            "font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; }"
            "QLabel#ytPillTitle { color: #F2F6FC; font-size: 12px; font-weight: 700; background: transparent; border: none; }"
            "QLabel#ytPillSub { color: #8DE7CA; font-size: 10px; font-weight: 600; background: transparent; border: none; }"
            "QPushButton#ytPillBtn { background: transparent; border: none; border-radius: 14px; color: #DCE6F2; }"
            "QPushButton#ytPillBtn:hover { background: #223044; }"
            "QPushButton#ytPillPlay { background: #77E0BE; border: none; border-radius: 15px; }"
            "QPushButton#ytPillPlay:hover { background: #98EED3; }"
        )

        lay = QHBoxLayout(self.container)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)

        self.lbl_art = QLabel()
        self.lbl_art.setFixedSize(42, 42)
        self.lbl_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_art.setStyleSheet("background: #1B2738; border-radius: 21px; border: 1px solid #2D4058;")
        lay.addWidget(self.lbl_art)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(2)
        info.addStretch(1)
        self.lbl_title = QLabel("YouTube Hi-Fi")
        self.lbl_title.setObjectName("ytPillTitle")
        self.lbl_title.setFixedWidth(210)
        self.lbl_sub = QLabel("WASAPI · Ready")
        self.lbl_sub.setObjectName("ytPillSub")
        self.lbl_sub.setFixedWidth(210)
        info.addWidget(self.lbl_title)
        info.addWidget(self.lbl_sub)
        info.addStretch(1)
        lay.addLayout(info)
        lay.addStretch(1)

        self.btn_prev = QPushButton()
        self.btn_prev.setObjectName("ytPillBtn")
        self.btn_prev.setFixedSize(28, 28)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_prev, "skip-back", "Previous", color=TEXT, size=15)
        self.btn_prev.clicked.connect(self.prev_requested.emit)

        self.btn_play = QPushButton()
        self.btn_play.setObjectName("ytPillPlay")
        self.btn_play.setFixedSize(30, 30)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_play, "pause", "Play / Pause", color=INK, size=15)
        self.btn_play.clicked.connect(self.play_pause_requested.emit)

        self.btn_next = QPushButton()
        self.btn_next.setObjectName("ytPillBtn")
        self.btn_next.setFixedSize(28, 28)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_next, "skip-forward", "Next", color=TEXT, size=15)
        self.btn_next.clicked.connect(self.next_requested.emit)

        self.btn_to_pip = QPushButton()
        self.btn_to_pip.setObjectName("ytPillBtn")
        self.btn_to_pip.setFixedSize(28, 28)
        self.btn_to_pip.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_to_pip, "picture-in-picture-2", tr_pair("Mở khung Video PiP", "Open Video PiP"), color=ACCENT, size=14)
        self.btn_to_pip.clicked.connect(self.pip_switch_requested.emit)

        self.btn_restore = QPushButton()
        self.btn_restore.setObjectName("ytPillBtn")
        self.btn_restore.setFixedSize(28, 28)
        self.btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_restore, "maximize", tr_pair("Mở lại cửa sổ YouTube", "Restore YouTube Window"), color=TEXT, size=14)
        self.btn_restore.clicked.connect(self.restore_requested.emit)

        for b in (self.btn_prev, self.btn_play, self.btn_next, self.btn_to_pip, self.btn_restore):
            lay.addWidget(b)

        self._drag_start: QPoint | None = None
        self._win_start: QPoint | None = None
        self._dragging = False

    def update_meta(self, title: str, subtitle: str, playing: bool) -> None:
        t = " ".join(str(title or "YouTube Hi-Fi").split())
        s = " ".join(str(subtitle or "YouTube Hi-Fi").split())
        self.lbl_title.setText(t[:30] + ("…" if len(t) > 30 else ""))
        self.lbl_sub.setText(s[:36] + ("…" if len(s) > 36 else ""))
        button_icon(self.btn_play, "pause" if playing else "play", "Play / Pause", color=INK, size=15)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._win_start = self.frameGeometry().topLeft()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_start is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._drag_start
            if not self._dragging and (delta.x() ** 2 + delta.y() ** 2) >= 25:
                self._dragging = True
            if self._dragging and self._win_start is not None:
                self.move(self._win_start + delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start = None
        self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.restore_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.restore_requested.emit()


# =====================================================================
# MAIN COMMERCIAL YOUTUBE ONLINE STUDIO PAGE
# =====================================================================

class YouTubeOnlinePage(QWidget):
    """Isolated YouTube Desktop Studio tab (zero mutations to BoTube's offline architecture)."""

    playback_starting = Signal()
    download_requested = Signal(str, str)  # (youtube_url, title)
    back_to_botube_requested = Signal()
    status_message = Signal(str)

    VIEW_HOME = 0
    VIEW_WATCH = 1
    VIEW_CHANNEL = 2
    VIEW_PLAYLIST = 3
    VIEW_LIBRARY = 4
    VIEW_FULLSCREEN = 5

    def __init__(
        self,
        *,
        profile_provider: Callable[[], AudioProfile] | None = None,
        audio_panel_opener: Callable[[QWidget], None] | None = None,
        sub_settings_opener: Callable[[], None] | None = None,
        sub_style_provider: Callable[[], dict[str, Any]] | None = None,
        on_before_exclusive: Callable[[], None] | None = None,
        on_after_exclusive: Callable[[], None] | None = None,
        profile_store: YouTubeOnlineProfileStore | None = None,
        client: YouTubeOnlineClient | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("youtubeOnlineRoot")
        self.setStyleSheet(YOUTUBE_PAGE_STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self._audio_panel_opener = audio_panel_opener
        self._sub_settings_opener = sub_settings_opener
        self._sub_style_provider = sub_style_provider
        self._on_before_exclusive = on_before_exclusive
        self._on_after_exclusive = on_after_exclusive
        self._sub_style_cfg: dict[str, Any] = {}
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
        self._is_pip_mode = False
        self._pip_window: _YouTubeMiniPlayerWindow | None = None
        self._is_pill_mode = False
        self._pill_window: _YouTubePillWindow | None = None
        self._bench_temp_dir: str | None = None
        self._pending_seek_target: int | None = None
        self._stream_recovery_vid = ""
        self._active_lib_section = "playlists"
        self._pre_fs_view_idx = self.VIEW_WATCH
        self._last_seek_ms = 0
        self._user_dragging_seek = False
        self._active_channel: OnlineChannelInfo | None = None
        self._active_playlist_items: list[OnlineVideoItem] = []
        self._active_playlist_title = ""
        self._active_playlist_url = ""

        # Isolated In-Tab AI Subtitle Generation state (never touches offline SubtitleManager!)
        self._ai_cues: list[OnlineSubtitleCue] = []
        self._ai_cues_vid = ""
        self._ai_worker = None
        self._ai_temp_dir: str | None = None
        self._ai_gen_vid = ""
        self._ai_gen_title = ""
        self._workspace_mode = "both"
        self._sub_style_initialized = False
        self._window_filter_host: QObject | None = None
        self._shutting_down = False

        # Worker tracking with generation counters
        self._workers: dict[str, _TaskWorker] = {}
        self._gens: dict[str, int] = {}

        # Build UI
        self._build_ui()

        # Dedicated Playback Engine (100% isolated from offline player!)
        self.player = YouTubeOnlinePlaybackController(
            self.video_widget,
            profile_provider=profile_provider,
            on_before_exclusive=on_before_exclusive,
            on_after_exclusive=on_after_exclusive,
            parent=self,
        )
        # Isolated BoTube SubtitleLayer for '✨ AI BoTube' mode (inherits 100% of BoTube Subtitle Studio!)
        self.yt_sub_layer = SubtitleLayer(initial_mode=SubtitleMode.EN_VI, parent=None)
        self.yt_sub_layer.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.yt_sub_layer.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.yt_sub_layer.enable_render = False
        self.yt_sub_layer.hide()
        if hasattr(self.yt_sub_layer, "_subtitle_effects"):
            self.yt_sub_layer._subtitle_effects.bind_position_provider(self.player.position_ms)
        self.player.set_volume(float(self.profile.get_pref("volume", 0.7) or 0.7))
        self.player.playback_starting.connect(self.playback_starting.emit)
        self.player.state_changed.connect(self._on_player_state_changed)
        self.player.position_changed.connect(self._on_player_position_changed)
        self.player.track_ended.connect(self._on_track_ended)
        self.player.subtitle_text_changed.connect(self._on_subtitle_text_changed)
        self.player.audio_status_changed.connect(self._on_audio_status_changed)
        self.player.buffering_changed.connect(self._on_buffering_changed)
        self.player.error_occurred.connect(self._on_player_error)
        self.player.stream_recovery_needed.connect(self._on_stream_recovery_needed)

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

        # Fullscreen auto-hide overlay controls timer (2.2s mouse inactivity)
        self._fs_hide_timer = QTimer(self)
        self._fs_hide_timer.setSingleShot(True)
        self._fs_hide_timer.setInterval(2200)
        self._fs_hide_timer.timeout.connect(self._hide_fs_controls_if_idle)

        # Smooth 55ms seek coalescer (prevents rapid click/scrubbing jitter)
        self._seek_coalesce_timer = QTimer(self)
        self._seek_coalesce_timer.setSingleShot(True)
        self._seek_coalesce_timer.setInterval(55)
        self._seek_coalesce_timer.timeout.connect(self._flush_coalesced_seek)

        # Restore saved UI preferences & sync AI availability + BoTube Subtitle style
        self._sync_pref_controls()
        self.refresh_ai_availability()
        if callable(self._sub_style_provider):
            try:
                self.apply_subtitle_style(self._sub_style_provider())
            except Exception:
                pass

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

        # 1. TOP YOUTUBE BAR (Clean centered search + fixed-size brand/HI-FI pill)
        self.top_bar = QFrame()
        self.top_bar.setObjectName("ytTopBar")
        self.top_bar.setFixedHeight(58)
        top_lay = QHBoxLayout(self.top_bar)
        top_lay.setContentsMargins(14, 8, 14, 8)
        top_lay.setSpacing(8)

        # Standalone Back-to-BoTube Offline Workspace button
        self.btn_back_botube = QPushButton("← BoTube")
        self.btn_back_botube.setObjectName("ytBackAppBtn")
        self.btn_back_botube.setFixedHeight(34)
        self.btn_back_botube.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_back_botube.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_back_botube, "house", "BoTube", color=ACCENT, size=15, icon_only=False)
        self.btn_back_botube.clicked.connect(self.back_to_botube_requested.emit)

        self.btn_back = QPushButton()
        self.btn_back.setObjectName("ytIconBtn")
        self.btn_back.setFixedSize(32, 32)
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_back, "arrow-left", "Back", color=TEXT, size=17)
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self._go_back)

        self.btn_forward = QPushButton()
        self.btn_forward.setObjectName("ytIconBtn")
        self.btn_forward.setFixedSize(32, 32)
        self.btn_forward.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_forward, "arrow-right", "Forward", color=TEXT, size=17)
        self.btn_forward.setEnabled(False)
        self.btn_forward.clicked.connect(self._go_forward)

        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("ytIconBtn")
        self.btn_refresh.setFixedSize(32, 32)
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_refresh, "refresh-cw", "Refresh", color=TEXT, size=15)
        self.btn_refresh.clicked.connect(self._refresh_current_view)

        brand = QLabel("YouTube")
        brand.setObjectName("ytBrandText")
        brand.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        badge_pro = QLabel("HI-FI")
        badge_pro.setObjectName("ytHifiPill")
        badge_pro.setFixedSize(44, 20)
        badge_pro.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Centered search bar
        self.search_input = QLineEdit()
        self.search_input.setObjectName("ytSearchInput")
        self.search_input.setFixedHeight(36)
        self.search_input.setMinimumWidth(140)
        self.search_input.setMaximumWidth(520)
        self.search_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.returnPressed.connect(self._on_search_submitted)
        self.search_input.textEdited.connect(self._on_search_text_edited)
        self.search_input.installEventFilter(self)

        self.btn_search = QPushButton()
        self.btn_search.setObjectName("ytSearchBtn")
        self.btn_search.setFixedSize(36, 36)
        self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_search, "search", "Search", color=TEXT, size=15)
        self.btn_search.clicked.connect(self._on_search_submitted)

        # BoTube signature Dynamic Island Pill (Chế độ Viên thuốc) quick button
        self.btn_top_pill = QPushButton()
        self.btn_top_pill.setObjectName("ytAccountBtn")
        self.btn_top_pill.setFixedHeight(34)
        self.btn_top_pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_top_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_top_pill, "disc-3", "Dynamic Island Pill", color=ACCENT, size=15, icon_only=False)
        self.btn_top_pill.clicked.connect(self.toggle_pill_mode)

        # BoTube Audio Studio (EQ / DAC / WASAPI Exclusive) quick button
        self.btn_top_audio_fx = QPushButton()
        self.btn_top_audio_fx.setObjectName("ytAccountBtn")
        self.btn_top_audio_fx.setFixedHeight(34)
        self.btn_top_audio_fx.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_top_audio_fx.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_top_audio_fx, "sliders-horizontal", "Audio Studio", color=ACCENT, size=15, icon_only=False)
        self.btn_top_audio_fx.clicked.connect(lambda: self._open_audio_studio(self.btn_top_audio_fx))

        # Quick Audio-Only toggle pill
        self.btn_audio_mode = QPushButton()
        self.btn_audio_mode.setObjectName("ytAudioToggle")
        self.btn_audio_mode.setCheckable(True)
        self.btn_audio_mode.setFixedHeight(34)
        self.btn_audio_mode.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_audio_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_audio_mode.toggled.connect(self._on_audio_only_toggled)

        # Account & Sync button
        self.btn_account = QPushButton()
        self.btn_account.setObjectName("ytAccountBtn")
        self.btn_account.setFixedHeight(34)
        self.btn_account.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_account.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_account.clicked.connect(self._open_account_dialog)

        top_lay.addWidget(self.btn_back_botube)
        top_lay.addSpacing(2)
        top_lay.addWidget(self.btn_back)
        top_lay.addWidget(self.btn_forward)
        top_lay.addWidget(self.btn_refresh)
        top_lay.addSpacing(2)
        top_lay.addWidget(brand)
        top_lay.addWidget(badge_pro)
        top_lay.addStretch(1)
        top_lay.addWidget(self.search_input, 4)
        top_lay.addWidget(self.btn_search)
        top_lay.addStretch(1)
        top_lay.addWidget(self.btn_top_pill)
        top_lay.addWidget(self.btn_top_audio_fx)
        top_lay.addWidget(self.btn_audio_mode)
        top_lay.addWidget(self.btn_account)
        root.addWidget(self.top_bar)

        # 2. SUB-NAV BAR (Full Standalone YouTube Categories — 100% Isolated Inside YouTube Tab!)
        self.sub_nav = QFrame()
        self.sub_nav.setObjectName("ytSubNav")
        self.sub_nav.setFixedHeight(44)
        snav_lay = QHBoxLayout(self.sub_nav)
        snav_lay.setContentsMargins(14, 4, 14, 4)
        snav_lay.setSpacing(4)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key in ("home", "music", "subscriptions", "library", "history", "watch_later", "liked", "watch"):
            btn = QPushButton()
            btn.setObjectName("ytNavTab")
            btn.setCheckable(True)
            btn.setFixedHeight(32)
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
        self._build_fullscreen_view() # index 5 (True 100% Edge-to-Edge Video Fullscreen!)
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
        lay.setContentsMargins(16, 10, 16, 6)
        lay.setSpacing(10)

        # Topic Chips Row (Crisp pills, zero clipped items)
        self.chips_scroll = QScrollArea()
        self.chips_scroll.setFixedHeight(40)
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        chips_host = QWidget()
        chips_host.setObjectName("ytScrollHost")
        self.chips_layout = QHBoxLayout(chips_host)
        self.chips_layout.setContentsMargins(0, 2, 0, 2)
        self.chips_layout.setSpacing(8)
        self.topic_buttons: dict[str, QPushButton] = {}
        for key, vi_lbl, _en_lbl, _q in TOPIC_CHIPS:
            btn = QPushButton(vi_lbl.replace("&", "&&"))
            btn.setObjectName("ytChipBtn")
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setFixedHeight(30)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
        sf_lay.setContentsMargins(0, 2, 0, 2)
        sf_lay.setSpacing(8)
        self.lbl_search_heading = QLabel("")
        self.lbl_search_heading.setStyleSheet("font-size: 14px; font-weight: 700; color: #EDF3FA;")
        sf_lay.addWidget(self.lbl_search_heading)
        sf_lay.addSpacing(8)
        self.filter_buttons: dict[str, QPushButton] = {}
        for fkey in ("all", "videos", "playlists", "channels", "live"):
            fb = QPushButton()
            fb.setObjectName("ytChipBtn")
            fb.setCheckable(True)
            fb.setChecked(fkey == "all")
            fb.setFixedHeight(30)
            fb.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            fb.setCursor(Qt.CursorShape.PointingHandCursor)
            fb.clicked.connect(lambda _c=False, k=fkey: self._select_search_filter(k))
            self.filter_buttons[fkey] = fb
            sf_lay.addWidget(fb)
        sf_lay.addStretch(1)
        self.search_filter_bar.hide()
        lay.addWidget(self.search_filter_bar)

        # Responsive Fluid 16:9 Grid Scroll Area
        self.home_scroll = QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.home_grid_host = QWidget()
        self.home_grid_host.setObjectName("ytScrollHost")
        self.home_grid = QGridLayout(self.home_grid_host)
        self.home_grid.setContentsMargins(0, 4, 4, 16)
        self.home_grid.setHorizontalSpacing(14)
        self.home_grid.setVerticalSpacing(16)
        self.home_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.home_scroll.setWidget(self.home_grid_host)
        lay.addWidget(self.home_scroll, 1)

        self.stack.addWidget(page)

    def _build_watch_view(self) -> None:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(16, 12, 16, 10)
        outer.setSpacing(16)

        # LEFT COLUMN (Scrollable Watch Stage + Controls + Metadata + Description + Comments)
        self.watch_left_scroll = QScrollArea()
        self.watch_left_scroll.setWidgetResizable(True)
        self.watch_left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_host = QWidget()
        left_host.setObjectName("ytScrollHost")
        left_lay = QVBoxLayout(left_host)
        left_lay.setContentsMargins(0, 0, 6, 24)
        left_lay.setSpacing(10)
        self._watch_left_lay = left_lay

        # 16:9 Stage (Video + Audio-Only Art + Floating Subtitle Overlay + Buffering Pill)
        self.stage_frame = QFrame()
        self.stage_frame.setObjectName("ytStageFrame")
        self.stage_frame.setMinimumHeight(400)
        self.stage_frame.setMaximumHeight(580)
        self.stage_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        stage_grid = QGridLayout(self.stage_frame)
        stage_grid.setContentsMargins(0, 0, 0, 0)

        self.stage_stack = QStackedWidget()
        self.video_widget = OnlineVideoSurface()
        self.video_widget.clicked.connect(self.toggle_play_pause)
        self.video_widget.double_clicked.connect(self._toggle_fullscreen_stage)
        self.stage_stack.addWidget(self.video_widget)

        # Audio-Only Hi-Fi Cover Art Stage
        audio_stage = QWidget()
        audio_stage.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0E1826, stop:1 #102624); border-radius: 11px;"
        )
        as_lay = QVBoxLayout(audio_stage)
        as_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        as_lay.setSpacing(12)
        self.lbl_audio_art = QLabel()
        self.lbl_audio_art.setFixedSize(300, 169)
        self.lbl_audio_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_audio_art.setStyleSheet("background: #131D2B; border-radius: 12px;")
        self.lbl_audio_title = QLabel("")
        self.lbl_audio_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_audio_title.setWordWrap(True)
        self.lbl_audio_title.setStyleSheet("color: #F2F6FC; font-size: 16px; font-weight: 700; padding: 0 28px;")
        self.lbl_audio_artist = QLabel("")
        self.lbl_audio_artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_audio_artist.setStyleSheet("color: #8DE7CA; font-size: 13px; font-weight: 600;")
        as_lay.addWidget(self.lbl_audio_art, alignment=Qt.AlignmentFlag.AlignHCenter)
        as_lay.addWidget(self.lbl_audio_title)
        as_lay.addWidget(self.lbl_audio_artist)
        self.stage_stack.addWidget(audio_stage)

        stage_grid.addWidget(self.stage_stack, 0, 0)

        # Floating YouTube CC Overlay (transparent frameless Tool window so it composites crisply over GPU video!)
        self.lbl_sub_overlay = QLabel("")
        self.lbl_sub_overlay.setObjectName("ytSubOverlay")
        self.lbl_sub_overlay.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.lbl_sub_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.lbl_sub_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lbl_sub_overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.lbl_sub_overlay.setStyleSheet(
            "QLabel { background: rgba(8, 11, 17, 224); color: #FFFFFF; border: none; border-radius: 9px; "
            "padding: 7px 16px; font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; font-size: 16px; font-weight: 700; }"
        )
        self.lbl_sub_overlay.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_sub_overlay.setWordWrap(True)
        self.lbl_sub_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub_overlay.hide()
        self.watch_left_scroll.verticalScrollBar().valueChanged.connect(self.sync_floating_overlays)
        left_lay.addWidget(self.stage_frame)

        # Commercial Player Controls Bar (Compact, zero horizontal clipping even on 1024px windows!)
        ctrl_box = QFrame()
        self.ctrl_box = ctrl_box
        ctrl_box.setObjectName("ytWatchControls")
        ctrl_lay = QVBoxLayout(ctrl_box)
        ctrl_lay.setContentsMargins(12, 7, 12, 8)
        ctrl_lay.setSpacing(6)

        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)
        self.lbl_pos_time = QLabel("0:00")
        self.lbl_pos_time.setFixedWidth(44)
        self.lbl_pos_time.setStyleSheet("color: #DCE6F2; font-size: 12px; font-family: Consolas;")
        self.seek_slider = _ClickSeekSlider()
        self.seek_slider.setRange(0, 0)
        self.seek_slider.drag_preview.connect(self._on_seek_drag_preview)
        self.seek_slider.seek_requested.connect(self._on_seek_requested)
        self.lbl_dur_time = QLabel("0:00")
        self.lbl_dur_time.setFixedWidth(44)
        self.lbl_dur_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_dur_time.setStyleSheet("color: #9AAABC; font-size: 12px; font-family: Consolas;")
        seek_row.addWidget(self.lbl_pos_time)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.lbl_dur_time)
        ctrl_lay.addLayout(seek_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_prev = QPushButton()
        self.btn_prev.setObjectName("ytIconBtn")
        self.btn_prev.setFixedSize(34, 34)
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
        self.btn_next.setObjectName("ytIconBtn")
        self.btn_next.setFixedSize(34, 34)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_next, "skip-forward", "Next", color=TEXT, size=17)
        self.btn_next.clicked.connect(self.play_next)

        self.btn_mute = QPushButton()
        self.btn_mute.setObjectName("ytIconBtn")
        self.btn_mute.setFixedSize(32, 32)
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_mute, "volume-2", "Mute", color=TEXT, size=16)
        self.btn_mute.clicked.connect(self._toggle_mute)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setObjectName("ytVolSlider")
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(round(float(self.profile.get_pref("volume", 0.7) or 0.7) * 100)))
        self.vol_slider.setFixedWidth(58)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)

        # 3-Mode Subtitle Selector (Off / YouTube CC / ✨ AI BoTube controlled by BoTube Subtitle Studio!)
        self.combo_sub_mode = QComboBox()
        self.combo_sub_mode.setObjectName("ytCombo")
        self.combo_sub_mode.setProperty("_i18n_safe_combo", True)
        self.combo_sub_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_sub_mode.addItem("Sub: Tắt", "off")
        self.combo_sub_mode.addItem("YouTube CC", "youtube_cc")
        self.combo_sub_mode.addItem("✨ AI BoTube", "ai_botube")
        self.combo_sub_mode.currentIndexChanged.connect(self._on_sub_mode_changed)

        self.combo_sub_lang = QComboBox()
        self.combo_sub_lang.setObjectName("ytCombo")
        self.combo_sub_lang.setProperty("_i18n_skip_combo", True)
        self.combo_sub_lang.setMaximumWidth(108)
        self.combo_sub_lang.hide()
        self.combo_sub_lang.currentIndexChanged.connect(self._on_sub_lang_changed)

        self.btn_sub_style = QPushButton()
        self.btn_sub_style.setObjectName("ytIconBtn")
        self.btn_sub_style.setFixedSize(28, 28)
        self.btn_sub_style.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_sub_style, "captions", tr_pair("Cài đặt giao diện Phụ đề BoTube", "BoTube Subtitle Style Settings"), color=ACCENT, size=15)
        self.btn_sub_style.clicked.connect(self._open_sub_settings)
        self.btn_sub_style.hide()

        # Quality Selector (Audio Hi-Fi + 4K/2K/1080p/720p/480p/360p)
        self.combo_quality = QComboBox()
        self.combo_quality.setObjectName("ytCombo")
        self.combo_quality.setProperty("_i18n_safe_combo", True)
        self.combo_quality.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.combo_quality.addItem("Audio Hi-Fi", "audio_only")
        self.combo_quality.addItem("1080p HD", "1080p")
        self.combo_quality.addItem("720p HD", "720p")
        self.combo_quality.currentIndexChanged.connect(self._on_quality_changed)

        # Speed Selector
        self.combo_speed = QComboBox()
        self.combo_speed.setObjectName("ytCombo")
        self.combo_speed.setProperty("_i18n_skip_combo", True)
        self.combo_speed.setFixedWidth(54)
        for sp in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
            self.combo_speed.addItem(f"{sp:g}x", sp)
        self.combo_speed.setCurrentIndex(2)
        self.combo_speed.currentIndexChanged.connect(self._on_speed_changed)

        self.btn_ctrl_audio_fx = QPushButton()
        self.btn_ctrl_audio_fx.setObjectName("ytIconBtn")
        self.btn_ctrl_audio_fx.setFixedSize(28, 28)
        self.btn_ctrl_audio_fx.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_ctrl_audio_fx, "sliders-horizontal", "Audio Studio (EQ / DAC)", color=ACCENT, size=15)
        self.btn_ctrl_audio_fx.clicked.connect(lambda: self._open_audio_studio(self.btn_ctrl_audio_fx))

        self.btn_pip_mini = QPushButton()
        self.btn_pip_mini.setObjectName("ytIconBtn")
        self.btn_pip_mini.setFixedSize(28, 28)
        self.btn_pip_mini.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_pip_mini, "picture-in-picture-2", tr_pair("Chế độ Mini-Player nổi", "Floating Mini-Player"), color=TEXT, size=15)
        self.btn_pip_mini.clicked.connect(self.toggle_mini_player)

        self.btn_cinema = QPushButton()
        self.btn_cinema.setObjectName("ytIconBtn")
        self.btn_cinema.setFixedSize(28, 28)
        self.btn_cinema.setCheckable(True)
        self.btn_cinema.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_cinema, "tv", "Cinema Mode", color=TEXT, size=15)
        self.btn_cinema.toggled.connect(self._toggle_cinema_mode)

        self.btn_fs = QPushButton()
        self.btn_fs.setObjectName("ytIconBtn")
        self.btn_fs.setFixedSize(28, 28)
        self.btn_fs.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_fs, "maximize", "Fullscreen", color=TEXT, size=15)
        self.btn_fs.clicked.connect(self._toggle_fullscreen_stage)

        btn_row.addWidget(self.btn_prev)
        btn_row.addWidget(self.btn_play)
        btn_row.addWidget(self.btn_next)
        btn_row.addSpacing(2)
        btn_row.addWidget(self.btn_mute)
        btn_row.addWidget(self.vol_slider)
        btn_row.addStretch(1)
        btn_row.addWidget(self.combo_sub_mode)
        btn_row.addWidget(self.combo_sub_lang)
        btn_row.addWidget(self.btn_sub_style)
        btn_row.addWidget(self.combo_quality)
        btn_row.addWidget(self.combo_speed)
        btn_row.addWidget(self.btn_ctrl_audio_fx)
        btn_row.addWidget(self.btn_pip_mini)
        btn_row.addWidget(self.btn_cinema)
        btn_row.addWidget(self.btn_fs)
        ctrl_lay.addLayout(btn_row)
        left_lay.addWidget(ctrl_box)

        # Inline Isolated AI Subtitle Progress Strip (hidden when idle)
        self.ai_sub_bar = QFrame()
        self.ai_sub_bar.setObjectName("ytAiProgressBar")
        ai_lay = QHBoxLayout(self.ai_sub_bar)
        ai_lay.setContentsMargins(12, 6, 12, 6)
        ai_lay.setSpacing(10)
        self.lbl_ai_status = QLabel("")
        self.lbl_ai_status.setStyleSheet("color: #8DE7CA; font-size: 12px; font-weight: 600;")
        self.ai_progress = QProgressBar()
        self.ai_progress.setRange(0, 100)
        self.ai_progress.setFixedHeight(8)
        self.ai_progress.setFixedWidth(140)
        self.ai_progress.setTextVisible(False)
        self.ai_progress.setStyleSheet(
            "QProgressBar { background: #1B2D36; border: none; border-radius: 4px; }"
            "QProgressBar::chunk { background: #77E0BE; border-radius: 4px; }"
        )
        self.btn_ai_cancel = QPushButton("✕")
        self.btn_ai_cancel.setObjectName("ytIconBtn")
        self.btn_ai_cancel.setFixedSize(26, 26)
        self.btn_ai_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_cancel.clicked.connect(self._cancel_ai_subtitle_job)
        ai_lay.addWidget(self.lbl_ai_status, 1)
        ai_lay.addWidget(self.ai_progress)
        ai_lay.addWidget(self.btn_ai_cancel)
        self.ai_sub_bar.hide()
        left_lay.addWidget(self.ai_sub_bar)

        # Title + Buffering Pill + Active Hi-Fi Audio Status Badge (outside GPU surface so always crisp!)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.lbl_watch_title = QLabel("")
        self.lbl_watch_title.setWordWrap(True)
        self.lbl_watch_title.setStyleSheet("color: #F4F8FD; font-size: 18px; font-weight: 700;")
        self.lbl_buffering = QLabel("")
        self.lbl_buffering.setObjectName("ytBufferingPill")
        self.lbl_buffering.setFixedHeight(26)
        self.lbl_buffering.hide()
        self.lbl_audio_badge = QLabel("Hi-Fi 64-bit · Ready")
        self.lbl_audio_badge.setObjectName("ytAudioBadge")
        self.lbl_audio_badge.setFixedHeight(26)
        self.lbl_audio_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_audio_badge.setToolTip(tr_pair("Bấm để mở BoTube Audio Studio (WASAPI Exclusive / EQ / DAC)", "Click to open BoTube Audio Studio (WASAPI Exclusive / EQ / DAC)"))
        self.lbl_audio_badge.installEventFilter(self)
        self.lbl_audio_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        title_row.addWidget(self.lbl_watch_title, 1)
        title_row.addWidget(self.lbl_buffering, 0, Qt.AlignmentFlag.AlignTop)
        title_row.addWidget(self.lbl_audio_badge, 0, Qt.AlignmentFlag.AlignTop)
        left_lay.addLayout(title_row)

        # Channel Row + Action Pills (Compact spacing so zero clipping even at 1024px!)
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self.lbl_ch_avatar = QLabel()
        self.lbl_ch_avatar.setFixedSize(36, 36)
        self.lbl_ch_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_ch_avatar.setStyleSheet("background: #1C2736; border-radius: 18px; color: #8DE7CA; font-weight: 700;")
        action_row.addWidget(self.lbl_ch_avatar)

        ch_col = QVBoxLayout()
        ch_col.setSpacing(1)
        self.btn_watch_channel = QPushButton("")
        self.btn_watch_channel.setObjectName("ytWatchChanBtn")
        self.btn_watch_channel.setMaximumWidth(165)
        self.btn_watch_channel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_watch_channel.clicked.connect(self._open_current_channel)
        self.lbl_watch_subs = QLabel("")
        self.lbl_watch_subs.setStyleSheet("color: #8EA0B5; font-size: 11px;")
        ch_col.addWidget(self.btn_watch_channel)
        ch_col.addWidget(self.lbl_watch_subs)
        action_row.addLayout(ch_col)

        self.btn_subscribe = QPushButton()
        self.btn_subscribe.setObjectName("ytSubscribeBtn")
        self.btn_subscribe.setCheckable(True)
        self.btn_subscribe.setFixedHeight(32)
        self.btn_subscribe.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_subscribe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_subscribe.clicked.connect(self._toggle_subscribe_current)
        action_row.addSpacing(2)
        action_row.addWidget(self.btn_subscribe)
        action_row.addStretch(1)

        self.btn_like = QPushButton()
        self.btn_like.setObjectName("ytActionPill")
        self.btn_like.setCheckable(True)
        self.btn_like.setFixedHeight(32)
        self.btn_like.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_like.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_like.clicked.connect(self._toggle_like_current)

        self.btn_watch_later = QPushButton()
        self.btn_watch_later.setObjectName("ytActionPill")
        self.btn_watch_later.setCheckable(True)
        self.btn_watch_later.setFixedHeight(32)
        self.btn_watch_later.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_watch_later.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_watch_later.clicked.connect(self._toggle_watch_later_current)

        self.btn_save_pl = QPushButton()
        self.btn_save_pl.setObjectName("ytActionPill")
        self.btn_save_pl.setFixedHeight(32)
        self.btn_save_pl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_save_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_pl.clicked.connect(self._open_save_playlist_menu)

        self.btn_ai_sub_gen = QPushButton()
        self.btn_ai_sub_gen.setObjectName("ytActionPill")
        self.btn_ai_sub_gen.setFixedHeight(32)
        self.btn_ai_sub_gen.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_ai_sub_gen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_sub_gen.clicked.connect(self._on_ai_sub_btn_clicked)

        self.btn_dl_video = QPushButton()
        self.btn_dl_video.setObjectName("ytPrimaryPill")
        self.btn_dl_video.setFixedHeight(32)
        self.btn_dl_video.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_dl_video.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_dl_video.clicked.connect(self._download_current_video)

        self.btn_copy_link = QPushButton()
        self.btn_copy_link.setObjectName("ytActionPill")
        self.btn_copy_link.setFixedHeight(32)
        self.btn_copy_link.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_copy_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy_link.clicked.connect(self._copy_current_link)

        for b in (self.btn_like, self.btn_watch_later, self.btn_save_pl, self.btn_ai_sub_gen, self.btn_dl_video, self.btn_copy_link):
            action_row.addWidget(b)
        left_lay.addLayout(action_row)

        # Chapters Strip (hidden when video has no chapters)
        self.chapters_wrap = QFrame()
        self.chapters_wrap.setObjectName("ytPanel")
        ch_lay = QVBoxLayout(self.chapters_wrap)
        ch_lay.setContentsMargins(14, 10, 14, 10)
        ch_lay.setSpacing(6)
        self.lbl_chapters_hdr = QLabel()
        self.lbl_chapters_hdr.setStyleSheet("color: #98EED3; font-size: 12px; font-weight: 700;")
        ch_lay.addWidget(self.lbl_chapters_hdr)
        self.chapters_scroll = QScrollArea()
        self.chapters_scroll.setFixedHeight(36)
        self.chapters_scroll.setWidgetResizable(True)
        self.chapters_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chapters_row_host = QWidget()
        self.chapters_row_host.setObjectName("ytScrollHost")
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
        desc_lay.setContentsMargins(14, 12, 14, 10)
        desc_lay.setSpacing(6)
        self.lbl_watch_stats = QLabel("")
        self.lbl_watch_stats.setStyleSheet("color: #E3ECF7; font-size: 13px; font-weight: 700;")
        self.desc_browser = QTextBrowser()
        self.desc_browser.setOpenLinks(False)
        self.desc_browser.anchorClicked.connect(self._on_desc_link_clicked)
        self.desc_browser.setMaximumHeight(82)
        self.desc_browser.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; color: #C2D0E0; font-size: 12px; }"
        )
        self.btn_toggle_desc = QPushButton()
        self.btn_toggle_desc.setObjectName("ytDescToggle")
        self.btn_toggle_desc.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_desc.clicked.connect(self._toggle_description)
        desc_lay.addWidget(self.lbl_watch_stats)
        desc_lay.addWidget(self.desc_browser)
        desc_lay.addWidget(self.btn_toggle_desc)
        left_lay.addWidget(self.desc_box)

        # Comments Section (Clean cards, zero nested label borders!)
        self.comments_box = QFrame()
        self.comments_box.setObjectName("ytPanel")
        c_lay = QVBoxLayout(self.comments_box)
        c_lay.setContentsMargins(14, 12, 14, 14)
        c_lay.setSpacing(10)
        c_hdr = QHBoxLayout()
        self.lbl_comments_hdr = QLabel()
        self.lbl_comments_hdr.setStyleSheet("color: #EDF3FA; font-size: 14px; font-weight: 700;")
        self.btn_load_comments = QPushButton()
        self.btn_load_comments.setObjectName("ytActionPill")
        self.btn_load_comments.setFixedHeight(30)
        self.btn_load_comments.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load_comments.clicked.connect(self._load_comments_async)
        c_hdr.addWidget(self.lbl_comments_hdr)
        c_hdr.addStretch(1)
        c_hdr.addWidget(self.btn_load_comments)
        c_lay.addLayout(c_hdr)
        self.comments_list_lay = QVBoxLayout()
        self.comments_list_lay.setSpacing(8)
        c_lay.addLayout(self.comments_list_lay)
        left_lay.addWidget(self.comments_box)
        left_lay.addStretch(1)

        self.watch_left_scroll.setWidget(left_host)
        outer.addWidget(self.watch_left_scroll, 7)

        # RIGHT COLUMN (Active Queue / Radio Mix + Unclipped Related Up Next)
        self.watch_right_panel = QWidget()
        self.watch_right_panel.setMinimumWidth(290)
        self.watch_right_panel.setMaximumWidth(400)
        right_lay = QVBoxLayout(self.watch_right_panel)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(12)

        # Queue / Auto-Mix Panel
        self.queue_frame = QFrame()
        self.queue_frame.setObjectName("ytPanel")
        qf_lay = QVBoxLayout(self.queue_frame)
        qf_lay.setContentsMargins(12, 10, 12, 10)
        qf_lay.setSpacing(8)

        qh = QHBoxLayout()
        self.lbl_queue_title = QLabel()
        self.lbl_queue_title.setStyleSheet("color: #EDF3FA; font-size: 13px; font-weight: 700;")
        self.btn_autoplay = QPushButton()
        self.btn_autoplay.setObjectName("ytChipBtn")
        self.btn_autoplay.setCheckable(True)
        self.btn_autoplay.setChecked(self._autoplay)
        self.btn_autoplay.setFixedHeight(28)
        self.btn_autoplay.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_autoplay.toggled.connect(self._on_autoplay_toggled)
        qh.addWidget(self.lbl_queue_title, 1)
        qh.addWidget(self.btn_autoplay)
        qf_lay.addLayout(qh)

        q_ctrl = QHBoxLayout()
        q_ctrl.setSpacing(6)
        self.btn_q_shuffle = QPushButton()
        self.btn_q_shuffle.setObjectName("ytIconBtn")
        self.btn_q_shuffle.setCheckable(True)
        self.btn_q_shuffle.setFixedSize(30, 30)
        button_icon(self.btn_q_shuffle, "shuffle", "Shuffle", color=MUTED, size=15)
        self.btn_q_shuffle.toggled.connect(self._on_shuffle_toggled)

        self.btn_q_repeat = QPushButton()
        self.btn_q_repeat.setObjectName("ytIconBtn")
        self.btn_q_repeat.setCheckable(True)
        self.btn_q_repeat.setFixedSize(30, 30)
        button_icon(self.btn_q_repeat, "repeat", "Repeat", color=MUTED, size=15)
        self.btn_q_repeat.toggled.connect(self._on_repeat_toggled)

        self.btn_start_mix = QPushButton()
        self.btn_start_mix.setObjectName("ytChipBtn")
        self.btn_start_mix.setFixedHeight(28)
        self.btn_start_mix.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_mix.clicked.connect(self._start_radio_mix)

        q_ctrl.addWidget(self.btn_q_shuffle)
        q_ctrl.addWidget(self.btn_q_repeat)
        q_ctrl.addWidget(self.btn_start_mix)
        q_ctrl.addStretch(1)
        qf_lay.addLayout(q_ctrl)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_scroll.setMinimumHeight(98)
        self.queue_scroll.setMaximumHeight(220)
        self.queue_host = QWidget()
        self.queue_host.setObjectName("ytScrollHost")
        self.queue_lay = QVBoxLayout(self.queue_host)
        self.queue_lay.setContentsMargins(0, 0, 2, 0)
        self.queue_lay.setSpacing(4)
        self.queue_lay.addStretch(1)
        self.queue_scroll.setWidget(self.queue_host)
        qf_lay.addWidget(self.queue_scroll)
        right_lay.addWidget(self.queue_frame)

        # Related / Up Next Panel
        rel_frame = QFrame()
        rel_frame.setObjectName("ytPanel")
        rf_lay = QVBoxLayout(rel_frame)
        rf_lay.setContentsMargins(12, 10, 12, 10)
        rf_lay.setSpacing(8)
        self.lbl_related_hdr = QLabel()
        self.lbl_related_hdr.setStyleSheet("color: #EDF3FA; font-size: 13px; font-weight: 700;")
        rf_lay.addWidget(self.lbl_related_hdr)
        self.related_scroll = QScrollArea()
        self.related_scroll.setWidgetResizable(True)
        self.related_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.related_host = QWidget()
        self.related_host.setObjectName("ytScrollHost")
        self.related_lay = QVBoxLayout(self.related_host)
        self.related_lay.setContentsMargins(0, 0, 2, 0)
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
        self.lbl_chan_page_avatar.setStyleSheet("background: #1C2636; border-radius: 34px;")
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
        self.btn_chan_page_sub.setFixedHeight(36)
        self.btn_chan_page_sub.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_chan_page_sub.clicked.connect(self._toggle_subscribe_channel_page)
        hl.addWidget(self.btn_chan_page_sub)
        lay.addWidget(hdr)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(8)
        self.btn_chan_videos = QPushButton()
        self.btn_chan_videos.setObjectName("ytChipBtn")
        self.btn_chan_videos.setCheckable(True)
        self.btn_chan_videos.setChecked(True)
        self.btn_chan_videos.setFixedHeight(30)
        self.btn_chan_videos.clicked.connect(lambda: self._switch_channel_tab("videos"))
        self.btn_chan_playlists = QPushButton()
        self.btn_chan_playlists.setObjectName("ytChipBtn")
        self.btn_chan_playlists.setCheckable(True)
        self.btn_chan_playlists.setFixedHeight(30)
        self.btn_chan_playlists.clicked.connect(lambda: self._switch_channel_tab("playlists"))
        tab_row.addWidget(self.btn_chan_videos)
        tab_row.addWidget(self.btn_chan_playlists)
        tab_row.addStretch(1)
        lay.addLayout(tab_row)

        self.channel_scroll = QScrollArea()
        self.channel_scroll.setWidgetResizable(True)
        self.channel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.channel_grid_host = QWidget()
        self.channel_grid_host.setObjectName("ytScrollHost")
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
        hl.setSpacing(10)
        col = QVBoxLayout()
        self.lbl_pl_page_title = QLabel("")
        self.lbl_pl_page_title.setStyleSheet("color: #EDF3FA; font-size: 19px; font-weight: 700;")
        self.lbl_pl_page_meta = QLabel("")
        self.lbl_pl_page_meta.setWordWrap(True)
        self.lbl_pl_page_meta.setStyleSheet("color: #9AAABC; font-size: 12px;")
        col.addWidget(self.lbl_pl_page_title)
        col.addWidget(self.lbl_pl_page_meta)
        hl.addLayout(col, 1)

        self.btn_pl_connect_cookie = QPushButton()
        self.btn_pl_connect_cookie.setObjectName("ytPrimaryPill")
        self.btn_pl_connect_cookie.setFixedHeight(34)
        self.btn_pl_connect_cookie.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pl_connect_cookie.clicked.connect(self._open_account_dialog)
        self.btn_pl_connect_cookie.hide()
        hl.addWidget(self.btn_pl_connect_cookie)

        self.btn_pl_play_all = QPushButton()
        self.btn_pl_play_all.setObjectName("ytPrimaryPill")
        self.btn_pl_play_all.setFixedHeight(34)
        self.btn_pl_play_all.clicked.connect(lambda: self._play_active_playlist(shuffle=False))
        self.btn_pl_shuffle = QPushButton()
        self.btn_pl_shuffle.setObjectName("ytActionPill")
        self.btn_pl_shuffle.setFixedHeight(34)
        self.btn_pl_shuffle.clicked.connect(lambda: self._play_active_playlist(shuffle=True))
        self.btn_pl_pin = QPushButton()
        self.btn_pl_pin.setObjectName("ytActionPill")
        self.btn_pl_pin.setFixedHeight(34)
        self.btn_pl_pin.clicked.connect(self._pin_active_playlist)
        for b in (self.btn_pl_play_all, self.btn_pl_shuffle, self.btn_pl_pin):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            hl.addWidget(b)
        lay.addWidget(hdr)

        self.pl_scroll = QScrollArea()
        self.pl_scroll.setWidgetResizable(True)
        self.pl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pl_list_host = QWidget()
        self.pl_list_host.setObjectName("ytScrollHost")
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
        for k in ("playlists", "watch_later", "liked", "history", "subscriptions"):
            b = QPushButton()
            b.setObjectName("ytChipBtn")
            b.setCheckable(True)
            b.setChecked(k == "playlists")
            b.setFixedHeight(30)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, key=k: self._render_library_section(key))
            self.lib_tab_btns[k] = b
            top.addWidget(b)
        top.addStretch(1)

        self.btn_lib_import_pl = QPushButton()
        self.btn_lib_import_pl.setObjectName("ytPrimaryPill")
        self.btn_lib_import_pl.setFixedHeight(32)
        self.btn_lib_import_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_import_pl.clicked.connect(self._prompt_import_playlist_url)
        self.btn_lib_new_pl = QPushButton()
        self.btn_lib_new_pl.setObjectName("ytActionPill")
        self.btn_lib_new_pl.setFixedHeight(32)
        self.btn_lib_new_pl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_new_pl.clicked.connect(self._prompt_new_playlist)
        self.btn_lib_clear_hist = QPushButton()
        self.btn_lib_clear_hist.setObjectName("ytActionPill")
        self.btn_lib_clear_hist.setFixedHeight(32)
        self.btn_lib_clear_hist.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_clear_hist.clicked.connect(self._clear_online_history)
        self.btn_lib_clear_hist.hide()

        self.btn_lib_play_all = QPushButton()
        self.btn_lib_play_all.setObjectName("ytPrimaryPill")
        self.btn_lib_play_all.setFixedHeight(32)
        self.btn_lib_play_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_play_all.clicked.connect(lambda: self._play_active_lib_section(shuffle=False))
        self.btn_lib_play_all.hide()

        self.btn_lib_shuffle = QPushButton()
        self.btn_lib_shuffle.setObjectName("ytActionPill")
        self.btn_lib_shuffle.setFixedHeight(32)
        self.btn_lib_shuffle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_shuffle.clicked.connect(lambda: self._play_active_lib_section(shuffle=True))
        self.btn_lib_shuffle.hide()

        self.btn_lib_sync_yt_liked = QPushButton()
        self.btn_lib_sync_yt_liked.setObjectName("ytActionPill")
        self.btn_lib_sync_yt_liked.setFixedHeight(32)
        self.btn_lib_sync_yt_liked.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lib_sync_yt_liked.clicked.connect(self._sync_youtube_liked_into_library)
        self.btn_lib_sync_yt_liked.hide()

        top.addWidget(self.btn_lib_import_pl)
        top.addWidget(self.btn_lib_new_pl)
        top.addWidget(self.btn_lib_play_all)
        top.addWidget(self.btn_lib_shuffle)
        top.addWidget(self.btn_lib_sync_yt_liked)
        top.addWidget(self.btn_lib_clear_hist)
        lay.addLayout(top)

        self.lib_scroll = QScrollArea()
        self.lib_scroll.setWidgetResizable(True)
        self.lib_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lib_host = QWidget()
        self.lib_host.setObjectName("ytScrollHost")
        self.lib_lay = QVBoxLayout(self.lib_host)
        self.lib_lay.setSpacing(8)
        self.lib_lay.addStretch(1)
        self.lib_scroll.setWidget(self.lib_host)
        lay.addWidget(self.lib_scroll, 1)

        self.stack.addWidget(page)

    def _build_fullscreen_view(self) -> None:
        """Dedicated 100% Edge-to-Edge GPU Video Fullscreen Canvas with auto-hiding cinema control bar."""
        fs_page = QWidget()
        fs_page.setObjectName("ytFullscreenPage")
        fs_page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        fs_page.setMouseTracking(True)
        fs_page.installEventFilter(self)
        self.fullscreen_page = fs_page
        self.fullscreen_lay = QVBoxLayout(fs_page)
        self.fullscreen_lay.setContentsMargins(0, 0, 0, 0)
        self.fullscreen_lay.setSpacing(0)
        self.stack.addWidget(fs_page)

    def _build_mini_bar(self) -> None:
        self.mini_bar = QFrame()
        self.mini_bar.setObjectName("ytMiniBar")
        self.mini_bar.setFixedHeight(64)
        lay = QHBoxLayout(self.mini_bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(12)

        self.lbl_mini_thumb = QLabel()
        self.lbl_mini_thumb.setFixedSize(80, 45)
        self.lbl_mini_thumb.setStyleSheet("background: #141C27; border-radius: 6px;")
        lay.addWidget(self.lbl_mini_thumb)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.lbl_mini_title = QLabel("")
        self.lbl_mini_title.setStyleSheet("color: #F2F6FC; font-size: 13px; font-weight: 700;")
        self.lbl_mini_sub = QLabel("")
        self.lbl_mini_sub.setStyleSheet("color: #8DE7CA; font-size: 11px;")
        info.addWidget(self.lbl_mini_title)
        info.addWidget(self.lbl_mini_sub)
        lay.addLayout(info, 1)

        self.btn_mini_prev = QPushButton()
        self.btn_mini_prev.setObjectName("ytIconBtn")
        self.btn_mini_prev.setFixedSize(34, 34)
        button_icon(self.btn_mini_prev, "skip-back", "Previous", color=TEXT, size=16)
        self.btn_mini_prev.clicked.connect(self.play_previous)

        self.btn_mini_play = QPushButton()
        self.btn_mini_play.setObjectName("ytPlayCircle")
        self.btn_mini_play.setFixedSize(38, 38)
        button_icon(self.btn_mini_play, "play", "Play/Pause", color=INK, size=17)
        self.btn_mini_play.clicked.connect(self.toggle_play_pause)

        self.btn_mini_next = QPushButton()
        self.btn_mini_next.setObjectName("ytIconBtn")
        self.btn_mini_next.setFixedSize(34, 34)
        button_icon(self.btn_mini_next, "skip-forward", "Next", color=TEXT, size=16)
        self.btn_mini_next.clicked.connect(self.play_next)

        self.btn_mini_open = QPushButton()
        self.btn_mini_open.setObjectName("ytPrimaryPill")
        self.btn_mini_open.setFixedHeight(34)
        self.btn_mini_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mini_open.clicked.connect(lambda: self._show_view(self.VIEW_WATCH))

        lay.addWidget(self.btn_mini_prev)
        lay.addWidget(self.btn_mini_play)
        lay.addWidget(self.btn_mini_next)
        lay.addSpacing(4)
        lay.addWidget(self.btn_mini_open)
        self.mini_bar.hide()

    # =================================================================
    # BILINGUAL I18N (100% VI/EN COVERAGE)
    # =================================================================

    def minimumSizeHint(self) -> QSize:
        # Keep MainWindow free to shrink to its original 1100x750 / compact 760px widths!
        return QSize(320, 240)

    def set_workspace_mode(self, mode: str) -> None:
        self._workspace_mode = str(mode or "both").strip().lower()
        self.retranslate(get_language())

    def retranslate(self, lang: str | None = None) -> None:
        lg = lang or get_language()
        self.search_input.setPlaceholderText(
            tr_pair("Tìm kiếm YouTube, bài hát, nghệ sĩ hoặc dán link...", "Search YouTube, songs, artists, or paste URL...", lg)
        )
        if getattr(self, "_workspace_mode", "both") == "online":
            self.btn_back_botube.setText(tr_pair("Menu", "Menu", lg))
            self.btn_back_botube.setToolTip(tr_pair("Mở thanh bên (YouTube · Tải về · Cài đặt)", "Toggle sidebar (YouTube · Downloads · Settings)", lg))
        else:
            self.btn_back_botube.setText("BoTube")
            self.btn_back_botube.setToolTip(tr_pair("Quay về Thư viện Offline BoTube", "Return to BoTube Offline Library", lg))
        self.btn_top_pill.setText(tr_pair("Viên thuốc", "Pill", lg))
        self.btn_top_pill.setToolTip(tr_pair("Chế độ Viên thuốc (Dynamic Island) độc quyền BoTube", "BoTube Signature Dynamic Island Pill Mode", lg))
        self.btn_top_audio_fx.setText(tr_pair("Âm thanh", "Audio EQ", lg))
        self.btn_top_audio_fx.setToolTip(tr_pair("Chỉnh Âm thanh Hi-Fi, EQ & DAC BoTube", "BoTube Hi-Fi Audio Studio, EQ & DAC", lg))
        self.btn_audio_mode.setText(
            tr_pair("🎵 Chỉ nghe Nhạc", "🎵 Audio Only", lg)
            if self.btn_audio_mode.isChecked()
            else tr_pair("🎬 Video + Hi-Fi", "🎬 Video + Hi-Fi", lg)
        )
        has_ck = has_active_cookie_source(
            str(self.profile.get_pref("cookies_browser", "") or ""),
            str(self.profile.get_pref("cookies_file", "") or ""),
        )
        self.btn_account.setText(
            tr_pair("● Tài khoản YouTube", "● YouTube Connected", lg)
            if has_ck
            else tr_pair("👤 Tài khoản", "👤 Account", lg)
        )

        nav_labels = {
            "home": tr_pair("Trang chủ", "Home", lg),
            "music": tr_pair("Âm nhạc", "Music", lg),
            "subscriptions": tr_pair("Kênh đăng ký", "Subscriptions", lg),
            "library": tr_pair("Playlist", "Playlists", lg),
            "history": tr_pair("Lịch sử", "History", lg),
            "watch_later": tr_pair("Xem sau", "Watch Later", lg),
            "liked": tr_pair("Đã thích", "Liked", lg),
            "watch": tr_pair("▶ Đang xem", "▶ Now Watching", lg),
        }
        for k, txt in nav_labels.items():
            self.nav_buttons[k].setText(txt)

        for key, vi_l, en_l, _q in TOPIC_CHIPS:
            if key in self.topic_buttons:
                self.topic_buttons[key].setText(tr_pair(vi_l, en_l, lg).replace("&", "&&"))

        flt_labels = {
            "all": tr_pair("Tất cả", "All", lg),
            "videos": tr_pair("Video", "Videos", lg),
            "playlists": tr_pair("Danh sách phát", "Playlists", lg),
            "channels": tr_pair("Kênh", "Channels", lg),
            "live": tr_pair("Trực tiếp", "Live", lg),
        }
        for k, txt in flt_labels.items():
            self.filter_buttons[k].setText(txt)

        # Watch controls (3 clean subtitle options: Off / YouTube CC / ✨ AI BoTube controlled by BoTube Subtitle Studio!)
        self.combo_sub_mode.setItemText(0, tr_pair("Sub: Tắt", "Sub: Off", lg))
        self.combo_sub_mode.setItemText(1, tr_pair("YouTube CC", "YouTube CC", lg))
        has_ai = bool(self._current_item and has_cached_ai_subtitles(self._current_item.video_id))
        ai_ok, _ai_reason = is_bo_ai_subtitle_available(self.profile)
        suffix_off = tr_pair(" (Tắt AI)", " (AI Off)", lg) if not ai_ok else ""
        self.combo_sub_mode.setItemText(
            2,
            tr_pair("✨ AI BoTube (Đã lưu)" if has_ai else "✨ AI BoTube", "✨ BoTube AI (Saved)" if has_ai else "✨ BoTube AI", lg) + suffix_off,
        )
        self.btn_ai_sub_gen.setText(tr_pair("↻ Tạo lại Sub", "↻ Regen Sub", lg))
        self.btn_ai_sub_gen.setToolTip(
            tr_pair(
                "Tạo lại phụ đề AI Whisper cho video này (tự tải nền audio, lưu cache & xóa file tạm)"
                if ai_ok
                else "AI Whisper đang tắt hoặc chưa được cài trong Cài đặt BoTube",
                "Regenerate Whisper AI subtitles for this video (temp audio auto-deleted)"
                if ai_ok
                else "Whisper AI is disabled or not installed in BoTube Settings",
                lg,
            )
        )
        self.btn_like.setText(
            tr_pair("❤️ Đã thích", "❤️ Liked", lg) if self.btn_like.isChecked() else tr_pair("🤍 Thích", "🤍 Like", lg)
        )
        self.btn_watch_later.setText(
            tr_pair("✓ Xem sau", "✓ Saved", lg) if self.btn_watch_later.isChecked() else tr_pair("🕒 Xem sau", "🕒 Later", lg)
        )
        self.btn_save_pl.setText(tr_pair("+ Lưu", "+ Save", lg))
        self.btn_dl_video.setText(tr_pair("⬇ Tải về", "⬇ Download", lg))
        self.btn_copy_link.setText(tr_pair("📋 Link", "📋 Copy", lg))
        self._refresh_subscribe_button_text(lg)

        self.lbl_chapters_hdr.setText(tr_pair("Phân đoạn (Chapters)", "Chapters", lg))
        self.btn_toggle_desc.setText(
            tr_pair("Thu gọn mô tả ▲", "Show less ▲", lg) if self._desc_expanded else tr_pair("Xem thêm mô tả ▼", "Show more ▼", lg)
        )
        self.lbl_comments_hdr.setText(tr_pair("Bình luận nổi bật", "Top Comments", lg))
        self.btn_load_comments.setText(tr_pair("Làm mới", "Refresh", lg))
        self.btn_autoplay.setText(tr_pair("Tự động phát", "Auto-Play", lg))
        self.btn_start_mix.setText(tr_pair("📻 Mix Radio", "📻 Radio Mix", lg))
        self.lbl_related_hdr.setText(tr_pair("Đề xuất tiếp theo", "Up Next", lg))
        self._update_queue_header_text(lg)

        # Channel, Playlist, Library, Mini-bar
        self.btn_chan_videos.setText(tr_pair("Video", "Videos", lg))
        self.btn_chan_playlists.setText(tr_pair("Danh sách phát", "Playlists", lg))
        self.btn_pl_connect_cookie.setText(tr_pair("🔑 Kết nối Cookie / Tài khoản", "🔑 Connect Cookies / Account", lg))
        self.btn_pl_play_all.setText(tr_pair("▶ Phát tất cả", "▶ Play All", lg))
        self.btn_pl_shuffle.setText(tr_pair("🔀 Trộn bài", "🔀 Shuffle", lg))
        self.btn_pl_pin.setText(tr_pair("📌 Lưu Thư viện", "📌 Pin Playlist", lg))

        lib_labels = {
            "playlists": tr_pair("Danh sách phát", "Playlists", lg),
            "watch_later": tr_pair("Xem sau", "Watch Later", lg),
            "liked": tr_pair("Đã thích", "Liked Videos", lg),
            "history": tr_pair("Lịch sử xem", "Watch History", lg),
            "subscriptions": tr_pair("Kênh đăng ký", "Subscriptions", lg),
        }
        for k, txt in lib_labels.items():
            self.lib_tab_btns[k].setText(txt)
        self.btn_lib_import_pl.setText(tr_pair("+ Nhập URL Playlist", "+ Import Playlist URL", lg))
        self.btn_lib_new_pl.setText(tr_pair("+ Tạo Playlist", "+ New Playlist", lg))
        self.btn_lib_play_all.setText(tr_pair("▶ Phát tất cả", "▶ Play All", lg))
        self.btn_lib_shuffle.setText(tr_pair("🔀 Trộn bài", "🔀 Shuffle", lg))
        self.btn_lib_sync_yt_liked.setText(tr_pair("↻ Đồng bộ Đã thích YouTube", "↻ Sync YouTube Liked", lg))
        self.btn_lib_clear_hist.setText(tr_pair("🗑 Xóa lịch sử", "🗑 Clear History", lg))
        self.btn_mini_open.setText(tr_pair("Mở trình phát", "Open Player", lg))

    @staticmethod
    def _normalize_sub_mode(raw: str) -> str:
        val = str(raw or "off").strip().lower()
        if val in ("ai_botube", "ai_bilingual", "ai_vi", "ai_en"):
            return "ai_botube"
        if val == "youtube_cc":
            return "youtube_cc"
        return "off"

    def _sync_pref_controls(self) -> None:
        audio_only = bool(self.profile.get_pref("audio_only", False))
        self.btn_audio_mode.blockSignals(True)
        self.btn_audio_mode.setChecked(audio_only)
        self.btn_audio_mode.blockSignals(False)
        self.stage_stack.setCurrentIndex(1 if audio_only else 0)

        sub_mode = self._normalize_sub_mode(str(self.profile.get_pref("subtitle_mode", "off") or "off"))
        idx = self.combo_sub_mode.findData(sub_mode)
        if idx >= 0:
            self.combo_sub_mode.blockSignals(True)
            self.combo_sub_mode.setCurrentIndex(idx)
            self.combo_sub_mode.blockSignals(False)
        self.combo_sub_lang.setVisible(sub_mode == "youtube_cc")
        self.btn_sub_style.setVisible(sub_mode == "ai_botube")

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

        lib_nav_map = {
            "playlists": "library",
            "history": "history",
            "watch_later": "watch_later",
            "liked": "liked",
            "subscriptions": "subscriptions",
        }
        active_nav = {
            self.VIEW_HOME: "music" if (self._current_topic == "music" and not self._current_search_query) else "home",
            self.VIEW_WATCH: "watch",
            self.VIEW_CHANNEL: "subscriptions",
            self.VIEW_PLAYLIST: "library",
            self.VIEW_LIBRARY: lib_nav_map.get(self._active_lib_section, "library"),
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
        if view_idx not in (self.VIEW_WATCH, self.VIEW_FULLSCREEN):
            if not self._is_pip_mode:
                self.hide_floating_overlays()
        else:
            QTimer.singleShot(40, self.sync_floating_overlays)

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
        self.sync_floating_overlays()

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
        elif key in ("subscriptions", "library", "history", "watch_later", "liked"):
            sec = "playlists" if key == "library" else key
            self._active_lib_section = sec
            self._show_view(self.VIEW_LIBRARY, record_nav=True)
            self._render_library_section(sec)
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
        if not q or parse_youtube_input(q) is not None:
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
    # HOME / TOPIC DISCOVERY FEED (FLUID GRID)
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
        # Quietly warm VISIONOS session cookies once so the very first video click starts in ~0.14s!
        if self._grid_items and not getattr(self.client, "_visitor_data", ""):
            first_vid = next((it.video_id for it in self._grid_items if it.video_id), "")
            if first_vid:
                self._run_async(
                    "warm_visitor",
                    lambda: self.client._ensure_visitor_session(first_vid),
                    on_ok=lambda _v: None,
                    on_err=lambda _m: None,
                )

    def _compute_fluid_grid_metrics(self, scroll_area: QScrollArea) -> tuple[int, int]:
        avail = max(320, scroll_area.viewport().width() - 18)
        cols = max(1, min(5, avail // 285))
        spacing = 14
        card_w = max(248, (avail - (cols - 1) * spacing) // cols)
        return cols, card_w

    def _relayout_home_grid(self) -> None:
        self._clear_layout(self.home_grid)
        if not self._grid_items:
            lbl = QLabel(tr_pair("Chưa có kết quả nào. Thử từ khóa khác hoặc bấm làm mới.", "No results yet. Try another query or click refresh."))
            lbl.setStyleSheet("color: #8EA0B5; font-size: 13px; padding: 24px;")
            self.home_grid.addWidget(lbl, 0, 0)
            return
        cols, card_w = self._compute_fluid_grid_metrics(self.home_scroll)
        for idx, item in enumerate(self._grid_items):
            card = _OnlineVideoCard(item, self._thumbs, card_width=card_w)
            card.clicked.connect(self._on_card_clicked)
            card.channel_clicked.connect(self.open_channel)
            card.queue_clicked.connect(self._append_to_queue)
            card.download_clicked.connect(self._emit_download_item)
            self.home_grid.addWidget(card, idx // cols, idx % cols)

    def _on_card_clicked(self, item: OnlineVideoItem) -> None:
        if item.item_type == "playlist" and item.playlist_id:
            self.open_playlist(item.playlist_id, title_hint=item.title, seed_video_id=item.video_id)
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
        self._stream_recovery_vid = ""
        self._desc_expanded = False
        self.desc_browser.setMaximumHeight(82)
        if self._pip_window is not None:
            self._pip_window.set_title(item.title or item.video_id)

        self.lbl_watch_title.setText(item.title or item.video_id)
        self.lbl_audio_title.setText(item.title or item.video_id)
        self.lbl_audio_artist.setText(item.channel_name or "YouTube Hi-Fi")
        self.btn_watch_channel.setText(item.channel_name or "YouTube")
        self.lbl_ch_avatar.setText((item.channel_name or "Y")[:1].upper())
        self.lbl_watch_subs.setText("")
        self.lbl_watch_stats.setText(" • ".join(p for p in (item.views_text, item.published_text) if p))
        self.desc_browser.setHtml("")
        self.chapters_wrap.hide()
        self._clear_layout(self.comments_list_lay)
        self.lbl_sub_overlay.hide()
        self.lbl_audio_badge.setObjectName("ytAudioBadge")
        self.lbl_audio_badge.setText(tr_pair("Đang kết nối…", "Connecting…"))
        self.lbl_audio_badge.style().polish(self.lbl_audio_badge)
        self.lbl_buffering.setText(tr_pair("Đang kết nối luồng Hi-Fi…", "Resolving Hi-Fi stream…"))
        self.lbl_buffering.show()
        self.btn_like.setChecked(self.profile.is_liked(item.video_id))
        self.btn_watch_later.setChecked(self.profile.is_in_watch_later(item.video_id))
        self.btn_subscribe.setChecked(self.profile.is_subscribed(item.channel_id))
        self.refresh_ai_availability()
        self.retranslate(get_language())

        if item.thumbnail_url:
            self._thumbs.load(item.thumbnail_url, self.lbl_audio_art, QSize(300, 169), radius=10)
            self._thumbs.load(item.thumbnail_url, self.lbl_mini_thumb, QSize(80, 45), radius=6)
        if item.channel_avatar:
            self._thumbs.load(item.channel_avatar, self.lbl_ch_avatar, QSize(36, 36), radius=18)
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

        # 2. Fetch full YouTube Watch details (description, channel, related videos, comments token)
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

        # Populate available Quality choices cleanly (including CinemaScope 4K/2K/1080p!)
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
        if self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off")) == "youtube_cc":
            self.combo_sub_lang.setVisible(self.combo_sub_lang.count() > 0)

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

        # Auto-load cached AI subtitles from isolated disk cache (<2ms); if AI mode is active & uncached, auto-run AI!
        self._ai_cues = []
        self._ai_cues_vid = ""
        cached_ai = load_cached_ai_subtitles(stream.video_id)
        if cached_ai:
            self._ai_cues = cached_ai
            self._ai_cues_vid = stream.video_id
        self.refresh_ai_availability()
        self.retranslate(get_language())

        cur_sub_mode = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off"))
        ai_ok, _reason = is_bo_ai_subtitle_available(self.profile)
        if cur_sub_mode == "youtube_cc":
            self.yt_sub_layer.enable_render = False
            self.yt_sub_layer.hide()
            self._load_selected_youtube_cc()
        elif cur_sub_mode == "ai_botube" and ai_ok:
            self.lbl_sub_overlay.hide()
            self.player.set_subtitles([], enabled=False)
            if self._ai_cues:
                self._apply_ai_cues_for_mode("ai_botube")
            elif not stream.is_live:
                # User chose ✨ AI BoTube -> automatically generate for every new video (no manual click needed!)
                self.yt_sub_layer.enable_render = False
                self.yt_sub_layer.hide()
                self._start_ai_subtitle_generation(force_regen=False)
            else:
                self.yt_sub_layer.enable_render = False
                self.yt_sub_layer.hide()
        else:
            self.player.set_subtitles([], enabled=False)
            self.yt_sub_layer.enable_render = False
            self.yt_sub_layer.hide()
            self.lbl_sub_overlay.hide()

    def _on_stream_recovery_needed(self, video_id: str) -> None:
        """Auto-recover ONCE via bundled yt-dlp.exe if a direct fast-path video URL returns HTTP 403/ResourceError."""
        if self._current_item is None or self._current_item.video_id != video_id:
            return
        if self._stream_recovery_vid == video_id:
            return
        self._stream_recovery_vid = video_id
        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        self.lbl_buffering.setText(tr_pair("Đang làm mới luồng phát…", "Refreshing video stream…"))
        self.lbl_buffering.show()
        self._run_async(
            "stream",
            lambda procs: self.client.resolve_stream(
                video_id,
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
                force_refresh=True,
                prefer_ytdlp=True,
            ),
            on_ok=self._on_stream_resolved,
            on_err=self._on_stream_error,
            pass_processes=True,
        )

    def _on_stream_error(self, msg: str) -> None:
        self.lbl_buffering.hide()
        self.lbl_audio_badge.setObjectName("ytErrorBadge")
        self.lbl_audio_badge.setText(tr_pair("Lỗi kết nối luồng", "Stream Error"))
        self.lbl_audio_badge.style().polish(self.lbl_audio_badge)
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
            self._thumbs.load(info.channel_avatar, self.lbl_ch_avatar, QSize(36, 36), radius=18)
        if info.subscriber_text:
            self.lbl_watch_subs.setText(info.subscriber_text)
        stats = " • ".join(p for p in (info.views_text, info.published_text) if p)
        if stats:
            self.lbl_watch_stats.setText(stats)
        if info.description:
            self.desc_browser.setHtml(self._format_description_html(info.description))
        if info.chapters and (self._current_stream is None or not self._current_stream.chapters):
            self._render_chapters(info.chapters)

        self._render_related_list(info.related)
        if info.comment_token:
            self._load_comments_async()
        # Proactively pre-resolve the #1 next track via fast 0.25s InnerTube IOS so pressing Next is instant!
        QTimer.singleShot(1200, self._maybe_preresolve_next)

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
        self.desc_browser.setMaximumHeight(420 if self._desc_expanded else 82)
        self.retranslate(get_language())

    def _render_chapters(self, chapters: list[OnlineChapter]) -> None:
        self.seek_slider.set_chapters(chapters)
        self._clear_layout(self.chapters_row)
        if not chapters:
            self.chapters_wrap.hide()
            return
        for ch in chapters[:24]:
            btn = QPushButton(f"{format_seconds_mmss(ch.start_sec)}  {ch.title[:28]}")
            btn.setObjectName("ytChipBtn")
            btn.setFixedHeight(28)
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
        # Keep queue compact when only 1 track is loaded, spacious when playlist/mix is active
        self.queue_scroll.setFixedHeight(106 if len(self._queue) <= 1 else min(220, len(self._queue) * 102 + 8))

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
    # COMMENTS (CLEAN BORDERLESS INNER TYPOGRAPHY + CIRCULAR AVATARS)
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
            card.setObjectName("ytCommentCard")
            outer = QHBoxLayout(card)
            outer.setContentsMargins(12, 10, 12, 10)
            outer.setSpacing(10)

            av = QLabel((c.author.lstrip("@") or "U")[:1].upper())
            av.setFixedSize(32, 32)
            av.setAlignment(Qt.AlignmentFlag.AlignCenter)
            av.setStyleSheet("background: #1B2738; color: #8DE7CA; border-radius: 16px; font-size: 12px; font-weight: 700;")
            if c.avatar_url:
                self._thumbs.load(c.avatar_url, av, QSize(32, 32), radius=16)
            outer.addWidget(av, 0, Qt.AlignmentFlag.AlignTop)

            cl = QVBoxLayout()
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(4)
            hdr = QHBoxLayout()
            hdr.setSpacing(8)
            author_lbl = QLabel(c.author + (" ★" if c.is_creator else ""))
            author_lbl.setStyleSheet(f"color: {'#77E0BE' if c.is_creator else '#E4EDF8'}; font-size: 12px; font-weight: 700;")
            time_lbl = QLabel(c.published_text)
            time_lbl.setStyleSheet("color: #788B9F; font-size: 11px;")
            hdr.addWidget(author_lbl)
            hdr.addWidget(time_lbl)
            hdr.addStretch(1)
            if c.likes_text:
                lk = QLabel(f"👍 {c.likes_text}")
                lk.setStyleSheet("color: #8FA3B8; font-size: 11px; font-weight: 600;")
                hdr.addWidget(lk)
            cl.addLayout(hdr)

            txt = QLabel(c.text)
            txt.setWordWrap(True)
            txt.setStyleSheet("color: #CFDCEB; font-size: 12px;")
            cl.addWidget(txt)
            outer.addLayout(cl, 1)
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
        if self._pip_window is not None:
            self._pip_window.set_playing(playing)
        self._sync_pill_meta()
        self._update_mini_bar_visibility()

    def seek_relative(self, delta_ms: int) -> None:
        self.player.seek_relative(delta_ms)

    def adjust_volume(self, delta: float) -> None:
        cur = int(self.vol_slider.value())
        nxt = max(0, min(100, int(round(cur + float(delta) * 100))))
        self.vol_slider.setValue(nxt)

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

        # Drive BoTube's real SubtitleLayer live when '✨ AI BoTube' mode is active
        if self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off")) == "ai_botube" and self._ai_cues:
            if self._can_show_floating_subtitle():
                self._sync_yt_sub_layer_anchor()
                self.yt_sub_layer.enable_render = True
                self.yt_sub_layer.update_position(pos_ms)
            else:
                self.yt_sub_layer.enable_render = False
                if not self.yt_sub_layer.isHidden():
                    self.yt_sub_layer.hide()

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

    def _on_seek_drag_preview(self, pos_ms: int) -> None:
        self._user_dragging_seek = True
        self.lbl_pos_time.setText(format_seconds_mmss(max(0, int(pos_ms)) / 1000.0))

    def _on_seek_requested(self, pos_ms: int) -> None:
        self._user_dragging_seek = False
        target = max(0, int(pos_ms))
        self._pending_seek_target = target
        self.lbl_pos_time.setText(format_seconds_mmss(target / 1000.0))
        self._seek_coalesce_timer.start()

    def _flush_coalesced_seek(self) -> None:
        target = self._pending_seek_target
        self._pending_seek_target = None
        if target is not None:
            self.player.seek(target)

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

    def _open_audio_studio(self, anchor_widget: QWidget) -> None:
        if callable(self._audio_panel_opener):
            self._audio_panel_opener(anchor_widget)

    def _open_sub_settings(self) -> None:
        if callable(self._sub_settings_opener):
            self._sub_settings_opener()

    def _stage_global_rect(self) -> QRect | None:
        """Compute the visible on-screen global rectangle of stage_frame for floating subtitles over GPU video."""
        if not self.stage_frame.isVisible() or self.stage_frame.width() < 80 or self.stage_frame.height() < 60:
            return None
        tl = self.stage_frame.mapToGlobal(QPoint(0, 0))
        rect = QRect(tl.x(), tl.y(), self.stage_frame.width(), self.stage_frame.height())
        if not self._is_fullscreen_stage and not self._is_pip_mode:
            vp = self.watch_left_scroll.viewport()
            if vp is not None and vp.isVisible():
                v_tl = vp.mapToGlobal(QPoint(0, 0))
                v_rect = QRect(v_tl.x(), v_tl.y(), vp.width(), vp.height())
                rect = rect.intersected(v_rect)
                if rect.height() < 90 or rect.width() < 120:
                    return None
        return rect

    def _can_show_floating_subtitle(self) -> bool:
        if self._is_pill_mode:
            return False
        if self._is_pip_mode:
            return self._pip_window is not None and self._pip_window.isVisible() and self.stage_frame.isVisible()
        if not self.isVisible():
            return False
        if self.stack.currentIndex() not in (self.VIEW_WATCH, self.VIEW_FULLSCREEN):
            return False
        win = self.window()
        if win is not None and (not win.isVisible() or win.isMinimized()):
            return False
        if win is not None and not win.isActiveWindow():
            active = QApplication.activeWindow()
            allowed = (win, self.yt_sub_layer, self.lbl_sub_overlay)
            sub_panel = getattr(win, "subsettings_panel", None)
            if active is not None and active not in allowed and active is not sub_panel:
                return False
        return self._stage_global_rect() is not None

    def _sync_yt_sub_layer_anchor(self) -> None:
        rect = self._stage_global_rect()
        if rect is None:
            return
        margin = 22 if self._is_fullscreen_stage else (10 if self._is_pip_mode else 16)
        self.yt_sub_layer._current_margin = margin
        self.yt_sub_layer.set_anchor_rect(rect)
        if not self.yt_sub_layer.isHidden():
            self.yt_sub_layer._ensure_within_bounds_global()
            self.yt_sub_layer.raise_()

    def _position_cc_overlay(self) -> None:
        rect = self._stage_global_rect()
        if rect is None or self.lbl_sub_overlay.isHidden():
            return
        max_w = max(280, int(rect.width() * 0.88))
        self.lbl_sub_overlay.setMaximumWidth(max_w)
        self.lbl_sub_overlay.adjustSize()
        margin = 24 if self._is_fullscreen_stage else (10 if self._is_pip_mode else 16)
        x = rect.left() + max(0, (rect.width() - self.lbl_sub_overlay.width()) // 2)
        y = max(rect.top() + 8, rect.bottom() - self.lbl_sub_overlay.height() - margin)
        self.lbl_sub_overlay.move(int(x), int(y))
        self.lbl_sub_overlay.raise_()

    def sync_floating_overlays(self, *_args) -> None:
        if getattr(self, "_shutting_down", False) or getattr(self, "yt_sub_layer", None) is None:
            return
        try:
            mode = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off"))
            if not self._can_show_floating_subtitle() or mode == "off":
                self.hide_floating_overlays()
                return
            if mode == "ai_botube":
                if self.lbl_sub_overlay is not None:
                    self.lbl_sub_overlay.hide()
                if self._ai_cues:
                    self._sync_yt_sub_layer_anchor()
                    self.yt_sub_layer.enable_render = True
                    self.yt_sub_layer.update_position(self.player.position_ms())
            elif mode == "youtube_cc":
                self.yt_sub_layer.enable_render = False
                self.yt_sub_layer.hide()
                if self.lbl_sub_overlay is not None and self.lbl_sub_overlay.text().strip():
                    self.lbl_sub_overlay.show()
                    self._position_cc_overlay()
        except RuntimeError:
            pass

    def hide_floating_overlays(self) -> None:
        layer = getattr(self, "yt_sub_layer", None)
        if layer is not None:
            try:
                layer.enable_render = False
                layer.hide()
            except RuntimeError:
                pass
        lbl = getattr(self, "lbl_sub_overlay", None)
        if lbl is not None:
            try:
                lbl.hide()
            except RuntimeError:
                pass

    def apply_subtitle_style(self, config: dict[str, Any] | None = None) -> None:
        """Sync 100% of BoTube's Subtitle Appearance Studio settings live onto YouTube's SubtitleLayer."""
        cfg = dict(config or {})
        self._sub_style_cfg = cfg

        # Resolve BoTube SubtitleMode (JP / EN / VI / JP_VI / JP_EN / EN_VI / JP_EN_VI / OFF)
        raw_mode = str(cfg.get("mode") or "en_vi").strip().lower()
        try:
            sub_mode = SubtitleMode(raw_mode)
        except Exception:
            sub_mode = SubtitleMode.EN_VI
        # On first sync (before user explicitly toggles OFF inside BoTube's panel), avoid silent blank when AI BoTube is chosen
        if not self._sub_style_initialized and sub_mode == SubtitleMode.OFF:
            sub_mode = SubtitleMode.EN_VI
        self._sub_style_initialized = True

        base_px = max(14, min(56, int(cfg.get("font_size", 24) or 24)))
        if self._is_pip_mode:
            eff_px = max(12, min(20, int(round(base_px * 0.56))))
        elif self._is_fullscreen_stage:
            eff_px = base_px
        else:
            eff_px = max(14, min(32, int(round(base_px * 0.84))))

        layer = self.yt_sub_layer
        layer.set_mode(sub_mode)
        layer.apply_style(
            font_size=eff_px,
            color=str(cfg.get("font_color", "#FFFF00") or "#FFFF00"),
            bg_color=str(cfg.get("bg_color", "#000000") or "#000000"),
            bg_opacity=float(cfg.get("bg_opacity", 0.5) if cfg.get("bg_opacity") is not None else 0.5),
            outline_enabled=bool(cfg.get("outline_enabled", True)),
            outline_width=int(cfg.get("outline_width", 4) or 4),
            outline_color=str(cfg.get("outline_color", "#000000") or "#000000"),
            shadow_enabled=bool(cfg.get("shadow_enabled", True)),
            shadow_alpha=int(cfg.get("shadow_alpha", 160) if cfg.get("shadow_alpha") is not None else 160),
        )
        layer.set_fade_enabled(bool(cfg.get("fade_enabled", True)))
        layer.set_phonetic_enabled(bool(cfg.get("phonetic_enabled", False)))
        layer.set_word_karaoke_enabled(bool(cfg.get("word_karaoke_enabled", False)))
        layer.set_locked(bool(cfg.get("lock_position", False)))
        if hasattr(layer, "_subtitle_effects"):
            layer._subtitle_effects.configure(cfg.get("subtitle_effects"))

        # Update YouTube CC overlay font size proportionally for Watch / Fullscreen / PiP
        cc_px = 24 if self._is_fullscreen_stage else (13 if self._is_pip_mode else 16)
        cc_pad = "10px 22px" if self._is_fullscreen_stage else ("5px 11px" if self._is_pip_mode else "7px 16px")
        self.lbl_sub_overlay.setStyleSheet(
            f"QLabel {{ background: rgba(8, 11, 17, 224); color: #FFFFFF; border: none; border-radius: 9px; "
            f"padding: {cc_pad}; font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; font-size: {cc_px}px; font-weight: 700; }}"
        )
        self.sync_floating_overlays()

    def refresh_ai_availability(self) -> None:
        """Gray out ✨ AI BoTube mode & Regen button whenever Whisper AI is disabled or not installed."""
        ai_ok, _reason = is_bo_ai_subtitle_available(self.profile)
        model = self.combo_sub_mode.model()
        if model is not None:
            for idx in range(self.combo_sub_mode.count()):
                val = str(self.combo_sub_mode.itemData(idx) or "")
                if val == "ai_botube":
                    item = model.item(idx) if hasattr(model, "item") else None
                    if item is not None:
                        item.setEnabled(bool(ai_ok))
        self.btn_ai_sub_gen.setEnabled(bool(ai_ok))
        if not ai_ok:
            cur = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off"))
            if cur == "ai_botube":
                idx_off = self.combo_sub_mode.findData("off")
                if idx_off >= 0:
                    self.combo_sub_mode.blockSignals(True)
                    self.combo_sub_mode.setCurrentIndex(idx_off)
                    self.combo_sub_mode.blockSignals(False)
                self.player.set_subtitles_enabled(False)
                self.hide_floating_overlays()
        cur_after = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off"))
        self.btn_sub_style.setVisible(bool(ai_ok and cur_after == "ai_botube"))

    def sync_to_audio_panel(self, panel) -> None:
        """Display YouTube Online's live Hi-Fi / WASAPI Exclusive status inside BoTube's Audio Studio panel."""
        if panel is None:
            return
        try:
            info = self.player.live_signal_path_info()
            if hasattr(panel, "set_signal_path"):
                panel.set_signal_path(info["source"], info["dsp"], info["output"])
            if hasattr(panel, "set_status"):
                panel.set_status(info["status"], busy=False)
        except Exception:
            pass

    def prepare_benchmark_audio_for(self, benchmark_page) -> None:
        """Fetch lossless audio sample of the active YouTube song so Benchmark Lab measures THIS exact track."""
        stream = self._current_stream
        item = self._current_item
        if benchmark_page is None or stream is None or item is None or not item.video_id:
            return
        # Cancel any stale offline benchmark worker before loading our YouTube audio
        old_w = getattr(benchmark_page, "_worker", None)
        if old_w is not None and hasattr(old_w, "stop"):
            try:
                old_w.stop()
            except Exception:
                pass
            benchmark_page._worker = None
        benchmark_page._generation = int(getattr(benchmark_page, "_generation", 0)) + 1

        self._cleanup_bench_temp_dir()
        tmp_dir = tempfile.mkdtemp(prefix=f"botube-yt-bench-{item.video_id}-")
        self._bench_temp_dir = tmp_dir
        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        vid = item.video_id
        title = item.title or vid
        dur_s = float(stream.duration_sec or item.duration_sec or 0.0)
        # Full track for normal songs <= 8 min; instant 45s lossless excerpt for multi-hour mixes!
        cap_s = 45.0 if dur_s > 480.0 else 0.0
        start_s = min(90.0, dur_s * 0.20) if cap_s > 0.0 else 0.0

        if hasattr(benchmark_page, "lbl_source"):
            benchmark_page.lbl_source.setText(
                tr_pair(f"Đang nạp âm thanh YouTube: {title}…", f"Loading YouTube audio: {title}…")
            )
        if hasattr(benchmark_page, "busy_bar"):
            benchmark_page.busy_bar.show()
        if hasattr(benchmark_page, "btn_run"):
            benchmark_page.btn_run.setEnabled(False)

        def _on_bench_audio_ready(audio_path: Any) -> None:
            p = str(audio_path or "").strip()
            if p and hasattr(benchmark_page, "set_source_file"):
                benchmark_page.set_source_file(p, auto_run=True)

        def _on_bench_audio_err(msg: str) -> None:
            if hasattr(benchmark_page, "busy_bar"):
                benchmark_page.busy_bar.hide()
            if hasattr(benchmark_page, "btn_run"):
                benchmark_page.btn_run.setEnabled(True)
            if hasattr(benchmark_page, "lbl_verdict_headline"):
                benchmark_page.lbl_verdict_headline.setText(
                    tr_pair(f"Không nạp được luồng YouTube để đo kiểm: {msg}", f"Failed to fetch YouTube audio for benchmark: {msg}")
                )

        self._run_async(
            "bench_audio",
            lambda procs: self.client.download_temp_audio_for_ai(
                vid,
                stream,
                tmp_dir,
                title=title,
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
                max_duration_sec=cap_s,
                start_sec=start_s,
            ),
            on_ok=_on_bench_audio_ready,
            on_err=_on_bench_audio_err,
            pass_processes=True,
        )

    def _cleanup_bench_temp_dir(self) -> None:
        tmp = self._bench_temp_dir
        self._bench_temp_dir = None
        if tmp:
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass

    def on_audio_profile_changed(self) -> None:
        """Seamlessly re-apply live BoTube Audio Studio profile (EQ / Preset / DAC / Exclusive)."""
        self.player.reapply_audio_profile()

    def _on_sub_mode_changed(self) -> None:
        mode = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off"))
        ai_ok, _reason = is_bo_ai_subtitle_available(self.profile)
        if mode == "ai_botube" and not ai_ok:
            self.refresh_ai_availability()
            self.status_message.emit(
                tr_pair(
                    "AI Whisper đang tắt hoặc chưa được cài trong Cài đặt BoTube / Tài khoản YouTube.",
                    "Whisper AI is disabled or not installed in BoTube Settings / YouTube Account.",
                )
            )
            return
        self.profile.set_pref("subtitle_mode", mode)
        self.btn_sub_style.setVisible(mode == "ai_botube")
        if mode == "off":
            self.combo_sub_lang.hide()
            self.player.set_subtitles_enabled(False)
            self.hide_floating_overlays()
        elif mode == "youtube_cc":
            self.yt_sub_layer.enable_render = False
            self.yt_sub_layer.hide()
            self.combo_sub_lang.setVisible(self.combo_sub_lang.count() > 0)
            self._load_selected_youtube_cc()
        elif mode == "ai_botube":
            self.combo_sub_lang.hide()
            self.lbl_sub_overlay.hide()
            self.player.set_subtitles([], enabled=False)
            if self._current_item is None:
                return
            vid = self._current_item.video_id
            if self._ai_cues and self._ai_cues_vid == vid:
                self._apply_ai_cues_for_mode("ai_botube")
            else:
                cached = load_cached_ai_subtitles(vid)
                if cached:
                    self._ai_cues = cached
                    self._ai_cues_vid = vid
                    self._apply_ai_cues_for_mode("ai_botube")
                else:
                    self._start_ai_subtitle_generation(force_regen=False)

    def _apply_ai_cues_for_mode(self, _mode: str = "ai_botube") -> None:
        """Load AI cues into BoTube's real SubtitleLayer so 100% of BoTube Subtitle Studio controls display."""
        segments = [
            {
                "start": int(c.start_ms),
                "end": int(c.end_ms),
                "orig": c.orig or c.text,
                "en": c.en,
                "vi": c.vi,
            }
            for c in (self._ai_cues or [])
        ]
        self.lbl_sub_overlay.hide()
        self.player.set_subtitles([], enabled=False)
        self.yt_sub_layer.load_subtitles(segments)
        if self.yt_sub_layer.mode == SubtitleMode.OFF:
            self.yt_sub_layer.set_mode(SubtitleMode.EN_VI)
        self.sync_floating_overlays()

    def _on_ai_sub_btn_clicked(self) -> None:
        """Regenerate Whisper AI subtitles on demand (always force_regen when AI is available)."""
        ai_ok, _reason = is_bo_ai_subtitle_available(self.profile)
        if not ai_ok or self._current_item is None or not self._current_item.video_id:
            return
        self._start_ai_subtitle_generation(force_regen=True)

    def _start_ai_subtitle_generation(self, *, force_regen: bool = False) -> None:
        """Download ONLY compact temp audio, reuse BoTube AIWorker, cache JSON to disk & delete temp audio!"""
        if self._current_item is None or not self._current_item.video_id:
            return
        vid = self._current_item.video_id
        title = self._current_item.title or vid

        if not force_regen:
            cached = load_cached_ai_subtitles(vid)
            if cached:
                self._ai_cues = cached
                self._ai_cues_vid = vid
                mode = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "ai_botube"))
                if mode != "ai_botube":
                    idx = self.combo_sub_mode.findData("ai_botube")
                    if idx >= 0:
                        self.combo_sub_mode.blockSignals(True)
                        self.combo_sub_mode.setCurrentIndex(idx)
                        self.combo_sub_mode.blockSignals(False)
                self.btn_sub_style.setVisible(True)
                self._apply_ai_cues_for_mode("ai_botube")
                self.retranslate(get_language())
                self.status_message.emit(tr_pair("⚡ Đã nạp AI Sub từ bộ nhớ đệm ổ cứng!", "⚡ Loaded cached AI Subtitles from disk!"))
                return

        self._cancel_ai_subtitle_job()
        self._ai_gen_vid = vid
        self._ai_gen_title = title
        self._ai_temp_dir = tempfile.mkdtemp(prefix=f"botube-yt-ai-{vid}-")

        self.ai_progress.setValue(8)
        self.lbl_ai_status.setText(tr_pair("🤖 Bước 1/2: Đang tải audio nền (tự xóa sau khi xong)…", "🤖 Step 1/2: Fetching temp audio (auto-deleted after)…"))
        self.ai_sub_bar.show()

        stream = self._current_stream if (self._current_stream and self._current_stream.video_id == vid) else None
        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        tmp_dir = self._ai_temp_dir

        self._run_async(
            "ai_audio_dl",
            lambda procs: self.client.download_temp_audio_for_ai(
                vid,
                stream,
                tmp_dir,
                title=title,
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
            ),
            on_ok=lambda audio_path: self._run_bo_ai_worker_on_temp_audio(vid, title, str(audio_path)),
            on_err=self._on_ai_sub_failed,
            pass_processes=True,
        )

    def _run_bo_ai_worker_on_temp_audio(self, vid: str, title: str, temp_audio_path: str) -> None:
        if vid != self._ai_gen_vid:
            self._cleanup_ai_temp_dir()
            return
        skip_tr = not bool(self.profile.get_pref("allow_ai_translate", True))
        self.ai_progress.setValue(20)
        self.lbl_ai_status.setText(
            tr_pair(
                "🤖 Bước 2/2: Đang nhận diện lời gốc bằng Whisper (không gọi dịch AI)…"
                if skip_tr
                else "🤖 Bước 2/2: Đang tách lời & dịch song ngữ AI…",
                "🤖 Step 2/2: Transcribing original lyrics with Whisper (no AI translate)…"
                if skip_tr
                else "🤖 Step 2/2: Generating & translating AI subtitles…",
            )
        )
        try:
            out_dir = str(self._ai_temp_dir or online_ai_sub_cache_dir())
            worker = create_youtube_ai_worker(
                media_id=f"yt_{vid}",
                input_path=temp_audio_path,
                output_dir=out_dir,
                skip_translate=skip_tr,
                parent=self,
            )
            worker.progress.connect(self._on_ai_sub_progress)
            worker.data_ready.connect(lambda _mid, segs, v=vid, t=title: self._on_ai_sub_finished(v, t, segs))
            worker.failed.connect(lambda _mid, err: self._on_ai_sub_failed(err))
            worker.finished.connect(worker.deleteLater)
            self._ai_worker = worker
            worker.start()
            # Keep Whisper/NLLB at BELOW_NORMAL CPU priority so live 1080p GPU video + WASAPI audio stay silky smooth!
            QTimer.singleShot(450, lambda w=worker: self._lower_ai_worker_priority(w))
        except Exception as err:
            self._on_ai_sub_failed(str(err))

    @staticmethod
    def _lower_ai_worker_priority(worker) -> None:
        try:
            proc = getattr(worker, "_process", None)
            pid = getattr(proc, "pid", None)
            if pid:
                import psutil
                psutil.Process(int(pid)).nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        except Exception:
            pass

    def _on_ai_sub_progress(self, percent: int, message: str) -> None:
        pct = max(20, min(99, int(percent or 20)))
        self.ai_progress.setValue(pct)
        if message:
            self.lbl_ai_status.setText(f"🤖 {message} ({pct}%)")

    def _on_ai_sub_finished(self, vid: str, title: str, segments: list[Any]) -> None:
        self._ai_worker = None
        self._cleanup_ai_temp_dir()
        self.ai_sub_bar.hide()

        cues = serialize_ai_segments_to_cues(segments)
        if not cues:
            self.status_message.emit(tr_pair("AI không phát hiện lời thoại/ca từ trong video này.", "AI detected no lyrics or speech in this video."))
            return

        save_cached_ai_subtitles(vid, cues, title=title)
        if self._current_item is not None and self._current_item.video_id == vid:
            self._ai_cues = cues
            self._ai_cues_vid = vid
            cur_mode = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off"))
            if cur_mode != "ai_botube":
                idx = self.combo_sub_mode.findData("ai_botube")
                if idx >= 0:
                    self.combo_sub_mode.blockSignals(True)
                    self.combo_sub_mode.setCurrentIndex(idx)
                    self.combo_sub_mode.blockSignals(False)
                self.profile.set_pref("subtitle_mode", "ai_botube")
            self.combo_sub_lang.hide()
            self.btn_sub_style.setVisible(True)
            self._apply_ai_cues_for_mode("ai_botube")
            self.retranslate(get_language())
        self.status_message.emit(
            tr_pair(
                f"✅ Đã tạo & lưu AI Sub ({len(cues)} câu) — file audio tạm đã được dọn sạch!",
                f"✅ Saved AI Subtitles ({len(cues)} cues) — temp audio cleaned up!",
            )
        )

    def _on_ai_sub_failed(self, err_msg: str) -> None:
        self._ai_worker = None
        self._cleanup_ai_temp_dir()
        self.ai_sub_bar.hide()
        first_line = str(err_msg or "").strip().splitlines()
        short = first_line[-1][:140] if first_line else "AI Error"
        self.status_message.emit(tr_pair(f"⚠️ Không tạo được AI Sub: {short}", f"⚠️ AI Subtitle failed: {short}"))

    def _cancel_ai_subtitle_job(self) -> None:
        self._ai_gen_vid = ""
        prev_dl = self._workers.pop("ai_audio_dl", None)
        if prev_dl is not None:
            prev_dl.cancel()
        if self._ai_worker is not None:
            try:
                if hasattr(self._ai_worker, "stop"):
                    self._ai_worker.stop()
                else:
                    self._ai_worker.requestInterruption()
                self._ai_worker.wait(1000)
            except Exception:
                pass
            self._ai_worker = None
        self._cleanup_ai_temp_dir()
        self.ai_sub_bar.hide()

    def _cleanup_ai_temp_dir(self) -> None:
        tmp = self._ai_temp_dir
        self._ai_temp_dir = None
        if tmp:
            try:
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:
                pass

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
                self.status_message.emit(tr_pair("Video này chưa có phụ đề CC — hãy chọn ✨ AI BoTube để tự tạo!", "No YouTube CC — select ✨ BoTube AI to auto-generate!"))
            return
        self._run_async(
            "subtitle_cc",
            lambda: self.client.fetch_subtitle_cues(trk),
            on_ok=lambda cues: self.player.set_subtitles(cues, enabled=True, display_mode="orig_only"),
            on_err=lambda _m: self.player.set_subtitles([], enabled=False),
        )

    def _on_subtitle_text_changed(self, text: str) -> None:
        if getattr(self, "_shutting_down", False) or getattr(self, "lbl_sub_overlay", None) is None:
            return
        clean = str(text or "").strip()
        mode = self._normalize_sub_mode(str(self.combo_sub_mode.currentData() or "off"))
        if clean and mode == "youtube_cc":
            plain_lines = re.sub(r"<[^>]+>", "", clean.replace("<br>", "\n")).splitlines()
            longest = max((len(ln.strip()) for ln in plain_lines), default=0)
            wrap_threshold = 72 if self._is_fullscreen_stage else 56
            self.lbl_sub_overlay.setWordWrap(longest > wrap_threshold)
            self.lbl_sub_overlay.setText(clean)
            if self._can_show_floating_subtitle():
                self.lbl_sub_overlay.show()
                self._position_cc_overlay()
            else:
                self.lbl_sub_overlay.hide()
        else:
            self.lbl_sub_overlay.setText("")
            self.lbl_sub_overlay.hide()

    def _on_audio_status_changed(self, label: str) -> None:
        self.lbl_audio_badge.setObjectName("ytAudioBadge")
        self.lbl_audio_badge.setText(label)
        self.lbl_audio_badge.style().polish(self.lbl_audio_badge)
        if self._current_item is not None:
            self.lbl_mini_sub.setText(f"{self._current_item.channel_name or 'YouTube'} · {label}")
        self._sync_pill_meta()

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
        self.stage_frame.setMaximumHeight(700 if checked else 580)

    def _sync_pill_meta(self) -> None:
        if self._pill_window is None:
            return
        title = self._current_item.title if self._current_item else "YouTube Hi-Fi"
        badge = self.lbl_audio_badge.text() or (self._current_item.channel_name if self._current_item else "YouTube")
        self._pill_window.update_meta(title, badge, self.player.is_playing)
        if self._current_item and self._current_item.thumbnail_url:
            self._thumbs.load(self._current_item.thumbnail_url, self._pill_window.lbl_art, QSize(42, 42), radius=21)

    def toggle_pill_mode(self) -> None:
        """Toggle BoTube's signature Dynamic Island Pill (Viên thuốc) for YouTube Online."""
        if self._is_pill_mode:
            self.exit_pill_mode()
            return
        if self._is_fullscreen_stage:
            self.exit_fullscreen_stage()
        if self._is_pip_mode:
            self.exit_mini_player()
        if self._pill_window is None:
            pill = _YouTubePillWindow(None)
            pill.prev_requested.connect(self.play_previous)
            pill.play_pause_requested.connect(self.toggle_play_pause)
            pill.next_requested.connect(self.play_next)
            pill.pip_switch_requested.connect(self._switch_pill_to_pip)
            pill.restore_requested.connect(self.exit_pill_mode)
            self._pill_window = pill

        self._is_pill_mode = True
        self.hide_floating_overlays()
        self._sync_pill_meta()
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            geo = scr.availableGeometry()
            self._pill_window.move(
                geo.left() + (geo.width() - self._pill_window.width()) // 2,
                geo.top() + 14,
            )
        win = self.window()
        if win is not None and win.isVisible():
            win.hide()
        self._pill_window.show()
        self._pill_window.raise_()

    def _switch_pill_to_pip(self) -> None:
        self.exit_pill_mode()
        self.toggle_mini_player()

    def exit_pill_mode(self) -> None:
        if not self._is_pill_mode:
            return
        self._is_pill_mode = False
        if self._pill_window is not None:
            self._pill_window.hide()
        win = self.window()
        if win is not None:
            win.show()
            if win.isMinimized():
                win.showNormal()
            win.unsetCursor()
            win.setCursor(Qt.CursorShape.ArrowCursor)
            win.raise_()
            win.activateWindow()

    def toggle_mini_player(self) -> None:
        """Toggle isolated floating always-on-top YouTube PiP Mini-Player (zero video/audio drop!)."""
        if self._is_pip_mode:
            self.exit_mini_player()
            return
        if self._is_pill_mode:
            self.exit_pill_mode()
        if self._is_fullscreen_stage:
            self.exit_fullscreen_stage()
        if self._pip_window is None:
            pip = _YouTubeMiniPlayerWindow(None)
            pip.prev_requested.connect(self.play_previous)
            pip.play_pause_requested.connect(self.toggle_play_pause)
            pip.next_requested.connect(self.play_next)
            pip.restore_requested.connect(self.exit_mini_player)
            self._pip_window = pip

        self._is_pip_mode = True
        self._watch_left_lay.removeWidget(self.stage_frame)
        self.stage_frame.setMinimumHeight(0)
        self.stage_frame.setMaximumHeight(16777215)
        self._pip_window.stage_lay.addWidget(self.stage_frame)
        self.stage_frame.show()
        if self._current_item is not None:
            self._pip_window.set_title(self._current_item.title or self._current_item.video_id)
        self._pip_window.set_playing(self.player.is_playing)
        # Position cleanly at bottom-right of primary screen
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            geo = scr.availableGeometry()
            self._pip_window.move(
                geo.right() - self._pip_window.width() - 20,
                geo.bottom() - self._pip_window.height() - 20,
            )
        self._pip_window.show()
        self._pip_window.raise_()
        self.apply_subtitle_style(self._sub_style_cfg)
        button_icon(self.btn_pip_mini, "picture-in-picture-2", tr_pair("Đang ở Mini-Player (bấm để thu về)", "In Mini-Player (click to restore)"), color=ACCENT, size=15)

    def exit_mini_player(self) -> None:
        if not self._is_pip_mode:
            return
        self._is_pip_mode = False
        if self._pip_window is not None:
            self._pip_window.stage_lay.removeWidget(self.stage_frame)
            self._pip_window.hide()
        self.stage_frame.setStyleSheet("")
        self.stage_frame.setMaximumHeight(700 if self._cinema_mode else 580)
        self.stage_frame.setMinimumHeight(400)
        self._watch_left_lay.insertWidget(0, self.stage_frame)
        self.stage_frame.show()
        self.apply_subtitle_style(self._sub_style_cfg)
        button_icon(self.btn_pip_mini, "picture-in-picture-2", tr_pair("Chế độ Mini-Player nổi", "Floating Mini-Player"), color=TEXT, size=15)
        win = self.window()
        if win is not None:
            win.showNormal() if win.isMinimized() else None
            win.raise_()
            win.activateWindow()

    def _toggle_fullscreen_stage(self) -> None:
        win = self.window()
        if win is None:
            return
        if self._is_pip_mode:
            self.exit_mini_player()
        if self._is_fullscreen_stage:
            self.exit_fullscreen_stage()
        else:
            self._is_fullscreen_stage = True
            self._pre_fs_view_idx = self.stack.currentIndex()
            if hasattr(win, "mouse_hide_timer") and win.mouse_hide_timer.isActive():
                win.mouse_hide_timer.stop()
            win.unsetCursor()
            self.top_bar.hide()
            self.sub_nav.hide()
            self.mini_bar.hide()

            # Reparent ONLY stage_frame (100% GPU full screen) + auto-hiding ctrl_box docked cleanly below!
            self._watch_left_lay.removeWidget(self.stage_frame)
            self._watch_left_lay.removeWidget(self.ctrl_box)
            self.stage_frame.setMinimumHeight(0)
            self.stage_frame.setMaximumHeight(16777215)
            self.stage_frame.setStyleSheet("QFrame#ytStageFrame { background: #000000; border: none; border-radius: 0px; }")
            self.ctrl_box.setObjectName("ytWatchControlsFS")
            self.ctrl_box.style().unpolish(self.ctrl_box)
            self.ctrl_box.style().polish(self.ctrl_box)

            self.fullscreen_lay.addWidget(self.stage_frame, 1)
            self.fullscreen_lay.addWidget(self.ctrl_box, 0)
            self.ctrl_box.show()
            self.video_widget.setMouseTracking(True)
            self.video_widget.installEventFilter(self)
            if hasattr(self.video_widget, "videoWidget"):
                self.video_widget.videoWidget().installEventFilter(self)

            self.lbl_sub_overlay.setObjectName("ytSubOverlayFS")
            self.player.set_subtitle_fullscreen(True)
            self.apply_subtitle_style(self._sub_style_cfg)

            self.stack.setCurrentIndex(self.VIEW_FULLSCREEN)
            if hasattr(win, "sidebar_container"):
                win.sidebar_container.hide()
            if hasattr(win, "playback_bar"):
                win.playback_bar.hide()
            win.showFullScreen()
            button_icon(self.btn_fs, "minimize", "Exit Fullscreen", color=ACCENT, size=15)
            self._fs_hide_timer.start()
            QTimer.singleShot(80, self.sync_floating_overlays)

    def _wake_fs_controls(self) -> None:
        if not self._is_fullscreen_stage:
            return
        was_hidden = self.ctrl_box.isHidden()
        self.ctrl_box.show()
        self.ctrl_box.raise_()
        self.unsetCursor()
        self.video_widget.unsetCursor()
        win = self.window()
        if win is not None:
            win.unsetCursor()
        if was_hidden:
            self.apply_subtitle_style(self._sub_style_cfg)
        self._fs_hide_timer.start()

    def _hide_fs_controls_if_idle(self) -> None:
        if not self._is_fullscreen_stage:
            return
        if self.ctrl_box.underMouse() or QApplication.activePopupWidget() is not None:
            self._fs_hide_timer.start()
            return
        self.ctrl_box.hide()
        self.apply_subtitle_style(self._sub_style_cfg)

    def exit_fullscreen_stage(self) -> None:
        if not self._is_fullscreen_stage:
            return
        self._is_fullscreen_stage = False
        self._fs_hide_timer.stop()
        self.unsetCursor()
        self.video_widget.unsetCursor()
        win = self.window()

        # Restore stage_frame + ctrl_box back into Watch column
        self.fullscreen_lay.removeWidget(self.stage_frame)
        self.fullscreen_lay.removeWidget(self.ctrl_box)
        self.stage_frame.setStyleSheet("")
        self.stage_frame.setMaximumHeight(700 if self._cinema_mode else 580)
        self.stage_frame.setMinimumHeight(400)
        self.ctrl_box.setObjectName("ytWatchControls")
        self.ctrl_box.style().unpolish(self.ctrl_box)
        self.ctrl_box.style().polish(self.ctrl_box)
        self._watch_left_lay.insertWidget(0, self.stage_frame)
        self._watch_left_lay.insertWidget(1, self.ctrl_box)
        self.ctrl_box.show()

        self.lbl_sub_overlay.setObjectName("ytSubOverlay")
        self.lbl_sub_overlay.style().polish(self.lbl_sub_overlay)
        self.player.set_subtitle_fullscreen(False)
        self.apply_subtitle_style(self._sub_style_cfg)

        self.top_bar.show()
        self.sub_nav.show()
        self.watch_right_panel.setVisible(not self._cinema_mode)
        self.stack.setCurrentIndex(self.VIEW_WATCH)
        if win is not None:
            if hasattr(win, "mouse_hide_timer") and win.mouse_hide_timer.isActive():
                win.mouse_hide_timer.stop()
            if win.isFullScreen():
                win.showNormal()
            if hasattr(win, "playback_bar"):
                win.playback_bar.hide()
            win.unsetCursor()
            win.setCursor(Qt.CursorShape.ArrowCursor)
        button_icon(self.btn_fs, "maximize", "Fullscreen", color=TEXT, size=15)

    def _update_mini_bar_visibility(self) -> None:
        show_mini = (
            self._current_item is not None
            and self.player.is_loaded
            and self.stack.currentIndex() not in (self.VIEW_WATCH, self.VIEW_FULLSCREEN)
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

    def _toggle_watch_later_current(self) -> None:
        if self._current_item is None:
            self.btn_watch_later.setChecked(False)
            return
        saved = self.profile.toggle_watch_later(self._current_item)
        self.btn_watch_later.setChecked(saved)
        self.retranslate(get_language())
        self.status_message.emit(
            tr_pair("🕒 Đã thêm vào Xem sau (YouTube Online)", "🕒 Added to Watch Later (YouTube Online)")
            if saved
            else tr_pair("Đã bỏ khỏi Xem sau", "Removed from Watch Later")
        )

    def _open_save_playlist_menu(self) -> None:
        if self._current_item is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #161F2D; color: #EDF3FA; border: 1px solid #354962; padding: 4px; }"
            "QMenu::item { padding: 6px 14px; border-radius: 5px; }"
            "QMenu::item:selected { background: #234C41; color: #A9F1D9; }"
        )
        for pl in self.profile.list_playlists():
            act = menu.addAction(f"🎵  {pl.get('name', 'Playlist')}")
            act.triggered.connect(lambda _c=False, pid=pl["id"]: self._save_current_to_playlist(pid))
        menu.addSeparator()
        act_new = menu.addAction(tr_pair("+ Tạo Playlist Online mới…", "+ Create New Online Playlist…"))
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
        dlg = _YouTubeAccountDialog(self.profile, client=self.client, parent=self)
        dlg.playlist_import_requested.connect(lambda u, t: self.open_playlist(u, title_hint=t))
        dlg.exec()
        self.refresh_ai_availability()
        self.retranslate(get_language())

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
            self._thumbs.load(info.avatar_url, self.lbl_chan_page_avatar, QSize(68, 68), radius=34)
        self._clear_layout(self.channel_grid)
        cols, card_w = self._compute_fluid_grid_metrics(self.channel_scroll)
        for idx, it in enumerate(info.items):
            card = _OnlineVideoCard(it, self._thumbs, card_width=card_w)
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

    def open_playlist(self, playlist_url_or_id: str, *, title_hint: str = "", seed_video_id: str = "") -> None:
        raw = str(playlist_url_or_id or "").strip()
        if not raw:
            return
        self._show_view(self.VIEW_PLAYLIST, record_nav=True)
        self._active_playlist_url = raw if raw.startswith(("http://", "https://", ":")) else f"https://www.youtube.com/playlist?list={raw}"
        self.lbl_pl_page_title.setText(title_hint or tr_pair("Đang tải Playlist…", "Loading Playlist…"))
        self.lbl_pl_page_meta.setText("")
        self.lbl_pl_page_meta.setStyleSheet("color: #9AAABC; font-size: 12px;")
        self.btn_pl_connect_cookie.hide()
        self._clear_layout(self.pl_list_lay)

        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        self._run_async(
            "playlist",
            lambda procs: self.client.fetch_playlist(
                raw,
                seed_video_id=seed_video_id,
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
            ),
            on_ok=self._on_playlist_loaded,
            on_err=self._on_playlist_error,
            pass_processes=True,
            busy_text=tr_pair("Đang đọc danh sách phát YouTube…", "Fetching YouTube playlist…"),
        )

    def _on_playlist_error(self, msg: str) -> None:
        self.lbl_pl_page_title.setText(tr_pair("Không tải được Playlist YouTube", "Unable to Load YouTube Playlist"))
        self.lbl_pl_page_meta.setStyleSheet("color: #F29C9C; font-size: 12px;")
        self.lbl_pl_page_meta.setText(str(msg or "Unknown error"))
        self.btn_pl_connect_cookie.show()

    def _on_playlist_loaded(self, payload: tuple[str, list[OnlineVideoItem]]) -> None:
        title, items = payload
        self._active_playlist_title = title
        self._active_playlist_items = list(items or [])
        self.btn_pl_connect_cookie.hide()
        self.lbl_pl_page_meta.setStyleSheet("color: #9AAABC; font-size: 12px;")
        self.lbl_pl_page_title.setText(title)
        self.lbl_pl_page_meta.setText(tr_pair(f"{len(items)} video/bài hát", f"{len(items)} videos/tracks"))
        self._clear_layout(self.pl_list_lay)
        for idx, it in enumerate(self._active_playlist_items):
            row = _CompactRelatedRow(it, self._thumbs, index_num=idx + 1)
            if it.item_type == "playlist" and it.playlist_id:
                row.clicked.connect(
                    lambda item_obj: self.open_playlist(item_obj.playlist_id, title_hint=item_obj.title)
                )
            else:
                row.clicked.connect(
                    lambda item_obj, i=idx: self.play_video_item(
                        item_obj,
                        queue=[x for x in self._active_playlist_items if x.video_id],
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
        self._active_lib_section = section
        for k, b in self.lib_tab_btns.items():
            b.setChecked(k == section)
        lib_nav_map = {
            "playlists": "library",
            "history": "history",
            "watch_later": "watch_later",
            "liked": "liked",
            "subscriptions": "subscriptions",
        }
        if self.stack.currentIndex() == self.VIEW_LIBRARY:
            target_nav = lib_nav_map.get(section, "library")
            for k, b in self.nav_buttons.items():
                b.setChecked(k == target_nav)
        self.btn_lib_import_pl.setVisible(section == "playlists")
        self.btn_lib_new_pl.setVisible(section == "playlists")
        self.btn_lib_clear_hist.setVisible(section == "history")
        self.btn_lib_sync_yt_liked.setVisible(section == "liked")
        is_playable_list = section in ("liked", "watch_later", "history")
        self.btn_lib_play_all.setVisible(is_playable_list)
        self.btn_lib_shuffle.setVisible(is_playable_list)
        self._clear_layout(self.lib_lay)

        if section == "playlists":
            playlists = self.profile.list_playlists()
            if not playlists:
                lbl = QLabel(
                    tr_pair(
                        "Chưa có Playlist Online nào. Bấm “+ Nhập URL Playlist” để dán link YouTube nghe ngay, hoặc vào “Tài khoản” để mở Video đã thích!",
                        "No Online Playlists yet. Click “+ Import Playlist URL” to play any YouTube playlist, or open “Account” for Liked Videos!",
                    )
                )
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
                btn_play.setObjectName("ytPrimaryPill")
                btn_play.setFixedHeight(32)
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
                    btn_sync.setObjectName("ytActionPill")
                    btn_sync.setFixedHeight(32)
                    btn_sync.clicked.connect(lambda _c=False, u=pl["source_url"], nm=pl.get("name", ""): self.open_playlist(u, title_hint=nm))
                    row.addWidget(btn_sync)
                btn_del = QPushButton(tr_pair("Xóa", "Delete"))
                btn_del.setObjectName("ytActionPill")
                btn_del.setFixedHeight(32)
                btn_del.clicked.connect(lambda _c=False, pid=pl["id"]: self._delete_saved_playlist(pid))
                row.addWidget(btn_del)
                self.lib_lay.addWidget(card)
        elif section in ("liked", "history", "watch_later"):
            if section == "liked":
                items = self.profile.list_liked()
                q_title = tr_pair("Video Online đã thích", "Liked Online Videos")
            elif section == "watch_later":
                items = self.profile.list_watch_later()
                q_title = tr_pair("Xem sau (YouTube Online)", "Watch Later (YouTube Online)")
            else:
                items = self.profile.list_watch_history()
                q_title = tr_pair("Lịch sử xem Online", "Online Watch History")
            if not items:
                if section == "liked":
                    empty_msg = tr_pair(
                        "Danh sách đã thích đang trống. Bấm “🤍 Thích” trên video bất kỳ hoặc bấm “↻ Đồng bộ Đã thích YouTube” ở góc phải trên để nhập danh sách đã thích từ tài khoản YouTube của bạn!",
                        "Liked list is empty. Click “🤍 Like” on any video or click “↻ Sync YouTube Liked” above to import your YouTube Liked Videos!",
                    )
                else:
                    empty_msg = tr_pair("Danh sách đang trống.", "This list is empty.")
                lbl = QLabel(empty_msg)
                lbl.setWordWrap(True)
                lbl.setStyleSheet("color: #8EA0B5; font-size: 13px; padding: 20px;")
                self.lib_lay.addWidget(lbl)
            else:
                for idx, it in enumerate(items[:80]):
                    row = _CompactRelatedRow(it, self._thumbs, index_num=idx + 1)
                    row.clicked.connect(lambda item_obj, i=idx: self.play_video_item(item_obj, queue=items[:80], queue_index=i, queue_title=q_title))
                    self.lib_lay.addWidget(row)
        elif section == "subscriptions":
            subs = self.profile.list_subscriptions()
            if not subs:
                lbl = QLabel(tr_pair("Bạn chưa đăng ký kênh nào trong BoTube. Bấm “Đăng ký” ở bất kỳ kênh nào hoặc nhập subscriptions.csv trong Tài khoản.", "No subscriptions yet. Click “Subscribe” on any channel or import subscriptions.csv via Account."))
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
                btn_open.setObjectName("ytPrimaryPill")
                btn_open.setFixedHeight(32)
                btn_open.clicked.connect(lambda _c=False, cid=s["channel_id"], nm=s.get("name", ""): self.open_channel(cid, nm))
                btn_unsub = QPushButton(tr_pair("Hủy đăng ký", "Unsubscribe"))
                btn_unsub.setObjectName("ytActionPill")
                btn_unsub.setFixedHeight(32)
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

    def _play_active_lib_section(self, *, shuffle: bool = False) -> None:
        sec = self._active_lib_section
        if sec == "liked":
            items = self.profile.list_liked()
            q_title = tr_pair("Video Online đã thích", "Liked Online Videos")
        elif sec == "watch_later":
            items = self.profile.list_watch_later()
            q_title = tr_pair("Xem sau (YouTube Online)", "Watch Later (YouTube Online)")
        elif sec == "history":
            items = self.profile.list_watch_history()
            q_title = tr_pair("Lịch sử xem Online", "Online Watch History")
        else:
            return
        if not items:
            self.status_message.emit(tr_pair("Danh sách đang trống.", "List is empty."))
            return
        if shuffle:
            random.shuffle(items)
        self.play_video_item(items[0], queue=items[:100], queue_index=0, queue_title=q_title)

    def _sync_youtube_liked_into_library(self) -> None:
        """Import/sync YouTube Liked Videos (:ytfav) directly into BoTube's isolated 'Đã thích' list."""
        cookies_br = str(self.profile.get_pref("cookies_browser", "") or "")
        cookies_file = str(self.profile.get_pref("cookies_file", "") or "")
        if not has_active_cookie_source(cookies_br, cookies_file):
            self.status_message.emit(
                tr_pair(
                    "Hãy chọn Firefox hoặc nạp cookies.txt trong Tài khoản để đồng bộ Video đã thích trên YouTube!",
                    "Select Firefox or load cookies.txt in Account to sync your YouTube Liked Videos!",
                )
            )
            self._open_account_dialog()
            return

        def _on_liked_synced(payload: tuple[str, list[OnlineVideoItem]]) -> None:
            _title, yt_items = payload
            added = 0
            for it in reversed(yt_items or []):
                if it.video_id and not self.profile.is_liked(it.video_id):
                    self.profile.toggle_like(it)
                    added += 1
            self._render_library_section("liked")
            self.status_message.emit(
                tr_pair(
                    f"✅ Đã đồng bộ Video đã thích YouTube ({len(yt_items)} video, thêm mới {added})!",
                    f"✅ Synced YouTube Liked Videos ({len(yt_items)} videos, {added} newly added)!",
                )
            )

        self._run_async(
            "sync_yt_liked",
            lambda procs: self.client.fetch_playlist(
                ":ytfav",
                cookies_browser=cookies_br,
                cookies_file=cookies_file,
                processes=procs,
                max_items=150,
            ),
            on_ok=_on_liked_synced,
            on_err=lambda m: self.status_message.emit(tr_pair(f"⚠️ Đồng bộ Đã thích thất bại: {m}", f"⚠️ Sync Liked failed: {m}")),
            pass_processes=True,
            busy_text=tr_pair("Đang đồng bộ danh sách Đã thích từ YouTube…", "Syncing YouTube Liked Videos…"),
        )

    # =================================================================
    # EVENTS & SHUTDOWN
    # =================================================================

    def showEvent(self, event) -> None:
        super().showEvent(event)
        win = self.window()
        if win is not None and self._window_filter_host is not win:
            if self._window_filter_host is not None:
                try:
                    self._window_filter_host.removeEventFilter(self)
                except Exception:
                    pass
            win.installEventFilter(self)
            self._window_filter_host = win
        QTimer.singleShot(40, self.sync_floating_overlays)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if not self._is_pip_mode:
            self.hide_floating_overlays()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        et = event.type()
        if obj is getattr(self, "search_input", None) and et == QEvent.Type.FocusOut:
            QTimer.singleShot(150, self._hide_suggest_if_unfocused)
        elif obj is getattr(self, "lbl_audio_badge", None) and et == QEvent.Type.MouseButtonRelease:
            self._open_audio_studio(self.lbl_audio_badge)
            return True
        elif obj is self._window_filter_host:
            if et in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.WindowActivate):
                self.sync_floating_overlays()
            elif et in (QEvent.Type.WindowDeactivate, QEvent.Type.Hide, QEvent.Type.WindowStateChange):
                QTimer.singleShot(20, self.sync_floating_overlays)
        elif self._is_fullscreen_stage and et in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            self._wake_fs_controls()
        return super().eventFilter(obj, event)

    def _hide_suggest_if_unfocused(self) -> None:
        if not self.search_input.hasFocus() and not self.suggest_popup.hasFocus():
            self.suggest_popup.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.stack.currentIndex() == self.VIEW_HOME and self._grid_items:
            self._grid_resize_timer.start()
        self.sync_floating_overlays()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def shutdown(self) -> None:
        self._shutting_down = True
        unregister_language_listener(self.retranslate)
        self._suggest_timer.stop()
        self._grid_resize_timer.stop()
        self._fs_hide_timer.stop()
        self._seek_coalesce_timer.stop()
        self._cancel_ai_subtitle_job()
        self._cleanup_bench_temp_dir()
        self.hide_floating_overlays()
        if self._window_filter_host is not None:
            try:
                self._window_filter_host.removeEventFilter(self)
            except Exception:
                pass
            self._window_filter_host = None
        if getattr(self, "yt_sub_layer", None) is not None:
            try:
                self.yt_sub_layer.hide()
                self.yt_sub_layer.deleteLater()
            except RuntimeError:
                pass
            self.yt_sub_layer = None
        if getattr(self, "lbl_sub_overlay", None) is not None:
            try:
                self.lbl_sub_overlay.hide()
                self.lbl_sub_overlay.deleteLater()
            except RuntimeError:
                pass
            self.lbl_sub_overlay = None
        self.exit_pill_mode()
        if self._pill_window is not None:
            self._pill_window.deleteLater()
            self._pill_window = None
        self.exit_mini_player()
        if self._pip_window is not None:
            self._pip_window.deleteLater()
            self._pip_window = None
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
