"""Commercial bilingual GitHub Releases + Inno Setup update dialog & controller for BoTube."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Callable

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from core.app_updater import (
    ReleaseInfo,
    cleanup_stale_installers,
    detect_install_mode,
    download_installer_atomic,
    fetch_latest_release,
    is_newer_version,
    launch_inno_installer,
)
from ui.i18n import (
    get_language,
    register_language_listener,
    tr_pair,
    unregister_language_listener,
)
from ui.icons import ACCENT, INK, MUTED, TEXT, button_icon
from version import APP_NAME, APP_VERSION, GITHUB_RELEASES_API, GITHUB_RELEASES_WEB

_AUTO_CHECK_INTERVAL_SEC = 24 * 3600.0
_STARTUP_CHECK_DELAY_MS = 4500

_KEY_AUTO_CHECK = 'auto_check_updates'
_KEY_LAST_CHECK_TS = 'last_update_check_ts'
_KEY_SKIPPED_VER = 'skipped_update_version'

_DIALOG_STYLE = '''
    QDialog#updateStudioDialog {
        background: #0D1118;
        color: #EDF3FA;
        font-family: 'Segoe UI';
    }
    QLabel { color: #EDF3FA; background: transparent; border: none; }
    QLabel#updTitle { font-size: 18px; font-weight: 700; color: #EDF3FA; }
    QLabel#updSubtitle { font-size: 12px; color: #8FA2B7; }
    QLabel#updVersionPill {
        background: #16332B; color: #77E0BE; border: 1px solid #2D5A4E;
        border-radius: 6px; padding: 3px 10px; font-size: 12px; font-weight: 700;
    }
    QLabel#updMetaPill {
        background: #1A232E; color: #9AAABC; border: 1px solid #2B394B;
        border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 600;
    }
    QFrame#updCard {
        background: #131A24; border: 1px solid #202C3C; border-radius: 10px;
    }
    QLabel#updSectionTitle { font-size: 12px; font-weight: 700; color: #AFC0D4; }
    QTextBrowser#updNotesBrowser {
        background: transparent; color: #DCE6F2; border: none;
        font-size: 12px; selection-background-color: #244F42;
    }
    QLabel#updInfoBanner {
        background: #122129; color: #A6C8D6; border: 1px solid #213B47;
        border-radius: 8px; padding: 8px 11px; font-size: 11px;
    }
    QLabel#updProgressLabel { font-size: 12px; color: #CBE6DD; font-weight: 600; }
    QLabel#updErrorLabel {
        background: #2A161A; color: #FF9EA9; border: 1px solid #592932;
        border-radius: 8px; padding: 8px 10px; font-size: 11px;
    }
    QProgressBar#updProgressBar {
        background: #1A2431; border: 1px solid #263447; border-radius: 5px;
        height: 10px; text-align: center;
    }
    QProgressBar#updProgressBar::chunk {
        background: #77E0BE; border-radius: 4px;
    }
    QPushButton#updPrimaryBtn {
        background: #77E0BE; color: #0B1218; border: none;
        border-radius: 8px; padding: 8px 16px; font-size: 12px; font-weight: 700;
    }
    QPushButton#updPrimaryBtn:hover { background: #8CE8CA; }
    QPushButton#updPrimaryBtn:disabled { background: #2A3A46; color: #6F8296; }
    QPushButton#updSecondaryBtn {
        background: #1A232E; color: #EDF3FA; border: 1px solid #2A384A;
        border-radius: 8px; padding: 8px 14px; font-size: 12px; font-weight: 600;
    }
    QPushButton#updSecondaryBtn:hover { background: #233040; border-color: #3E526A; }
    QPushButton#updGhostBtn {
        background: transparent; color: #8FA2B7; border: 1px solid transparent;
        border-radius: 8px; padding: 7px 10px; font-size: 12px; font-weight: 600;
    }
    QPushButton#updGhostBtn:hover { color: #EDF3FA; background: #18212E; }
    QScrollBar:vertical { background: #131A24; width: 7px; border-radius: 3px; }
    QScrollBar::handle:vertical { background: #2A394C; border-radius: 3px; min-height: 24px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
'''


def _format_bytes(num_bytes: int) -> str:
    val = max(0, int(num_bytes))
    if val >= 1024 * 1024 * 1024:
        return f'{val / (1024 ** 3):.2f} GB'
    if val >= 1024 * 1024:
        return f'{val / (1024 ** 2):.1f} MB'
    if val >= 1024:
        return f'{val / 1024:.0f} KB'
    return f'{val} B'


def _as_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return default


class UpdateCheckWorker(QThread):
    """Non-blocking background GitHub Releases checker."""

    update_found = Signal(object)  # ReleaseInfo
    up_to_date = Signal(str)  # latest or current version
    failed = Signal(str)

    def __init__(
        self,
        *,
        current_version: str = APP_VERSION,
        api_url: str = GITHUB_RELEASES_API,
        fetch_fn: Callable[..., ReleaseInfo | None] = fetch_latest_release,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.current_version = current_version
        self.api_url = api_url
        self._fetch_fn = fetch_fn

    def run(self) -> None:
        try:
            cleanup_stale_installers()
        except Exception:
            pass
        if self.isInterruptionRequested():
            return
        try:
            info = self._fetch_fn(self.api_url)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
            return
        if self.isInterruptionRequested():
            return
        if info is None:
            self.up_to_date.emit(self.current_version)
            return
        if is_newer_version(info.version, self.current_version):
            self.update_found.emit(info)
        else:
            self.up_to_date.emit(info.version or self.current_version)


class UpdateDownloadWorker(QThread):
    """Background streaming installer downloader with SHA-256 verification."""

    progress = Signal(int, int, float)
    finished_ok = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        release: ReleaseInfo,
        *,
        download_fn: Callable[..., Path] = download_installer_atomic,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.release = release
        self._download_fn = download_fn

    def run(self) -> None:
        try:
            out_path = self._download_fn(
                self.release,
                progress_cb=lambda d, t, spd: self.progress.emit(int(d), int(t), float(spd)),
                cancelled=self.isInterruptionRequested,
            )
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.finished_ok.emit(str(out_path))
        except InterruptedError:
            self.cancelled.emit()
        except Exception as exc:
            if self.isInterruptionRequested():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Commercial bilingual update dialog with Markdown notes, progress bar, and UAC-safe launch."""

    skip_requested = Signal(str)
    install_launched = Signal(str)

    def __init__(
        self,
        release: ReleaseInfo,
        *,
        current_version: str = APP_VERSION,
        install_mode: str | None = None,
        install_dir: Path | None = None,
        download_fn: Callable[..., Path] = download_installer_atomic,
        launch_fn: Callable[..., tuple[bool, str]] = launch_inno_installer,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.release = release
        self.current_version = current_version
        if install_mode is None or install_dir is None:
            det_mode, det_dir = detect_install_mode()
            self.install_mode = install_mode or det_mode
            self.install_dir = install_dir or det_dir
        else:
            self.install_mode = install_mode
            self.install_dir = install_dir
        self._download_fn = download_fn
        self._launch_fn = launch_fn
        self._download_worker: UpdateDownloadWorker | None = None
        self._last_progress: tuple[int, int, float] | None = None
        self._error_pair: tuple[str, str] | None = None
        self._listener_active = False

        self.setObjectName('updateStudioDialog')
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(560, 460)
        self.setStyleSheet(_DIALOG_STYLE)

        self._build_ui()
        self.retranslate_ui(get_language())
        register_language_listener(self._on_language_changed)
        self._listener_active = True

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # Top header
        hdr = QVBoxLayout()
        hdr.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName('updTitle')
        title_row.addWidget(self.lbl_title)
        title_row.addStretch()

        self.lbl_version_pill = QLabel(f'v{self.current_version} → v{self.release.version}')
        self.lbl_version_pill.setObjectName('updVersionPill')
        title_row.addWidget(self.lbl_version_pill)
        hdr.addLayout(title_row)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setObjectName('updSubtitle')
        meta_row.addWidget(self.lbl_subtitle)
        meta_row.addStretch()

        if self.release.asset_size > 0:
            self.lbl_size_pill = QLabel(_format_bytes(self.release.asset_size))
            self.lbl_size_pill.setObjectName('updMetaPill')
            meta_row.addWidget(self.lbl_size_pill)
        else:
            self.lbl_size_pill = None

        if self.release.sha256:
            self.lbl_sha_pill = QLabel('SHA-256 ✓')
            self.lbl_sha_pill.setObjectName('updMetaPill')
            meta_row.addWidget(self.lbl_sha_pill)
        else:
            self.lbl_sha_pill = None
        hdr.addLayout(meta_row)
        root.addLayout(hdr)

        # Release notes card
        notes_card = QFrame()
        notes_card.setObjectName('updCard')
        notes_lay = QVBoxLayout(notes_card)
        notes_lay.setContentsMargins(14, 12, 14, 12)
        notes_lay.setSpacing(6)

        self.lbl_notes_heading = QLabel()
        self.lbl_notes_heading.setObjectName('updSectionTitle')
        notes_lay.addWidget(self.lbl_notes_heading)

        self.notes_browser = QTextBrowser()
        self.notes_browser.setObjectName('updNotesBrowser')
        self.notes_browser.setOpenExternalLinks(True)
        self.notes_browser.setMinimumHeight(140)
        self.notes_browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        notes_lay.addWidget(self.notes_browser, stretch=1)
        root.addWidget(notes_card, stretch=1)

        # Data-safety / mode banner
        self.lbl_info_banner = QLabel()
        self.lbl_info_banner.setObjectName('updInfoBanner')
        self.lbl_info_banner.setWordWrap(True)
        root.addWidget(self.lbl_info_banner)

        # Download progress panel (hidden until download starts)
        self.progress_wrap = QWidget()
        prog_lay = QVBoxLayout(self.progress_wrap)
        prog_lay.setContentsMargins(0, 2, 0, 2)
        prog_lay.setSpacing(6)

        self.lbl_progress = QLabel()
        self.lbl_progress.setObjectName('updProgressLabel')
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName('updProgressBar')
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        prog_lay.addWidget(self.lbl_progress)
        prog_lay.addWidget(self.progress_bar)
        self.progress_wrap.hide()
        root.addWidget(self.progress_wrap)

        # Inline error banner (hidden unless an error occurs)
        self.lbl_error = QLabel()
        self.lbl_error.setObjectName('updErrorLabel')
        self.lbl_error.setWordWrap(True)
        self.lbl_error.hide()
        root.addWidget(self.lbl_error)

        # Action footer
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_skip = QPushButton()
        self.btn_skip.setObjectName('updGhostBtn')
        self.btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_skip.clicked.connect(self._on_skip_clicked)

        self.btn_github = QPushButton()
        self.btn_github.setObjectName('updSecondaryBtn')
        self.btn_github.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_github.clicked.connect(self._on_open_github)

        self.btn_later = QPushButton()
        self.btn_later.setObjectName('updSecondaryBtn')
        self.btn_later.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_later.clicked.connect(self._on_later_or_cancel)

        self.btn_install = QPushButton()
        self.btn_install.setObjectName('updPrimaryBtn')
        self.btn_install.setCursor(Qt.CursorShape.PointingHandCursor)
        button_icon(self.btn_install, 'download', 'Tải và cài đặt bản cập nhật', color=INK, size=14, icon_only=False)
        self.btn_install.clicked.connect(self._on_install_clicked)
        if not self.release.download_url:
            self.btn_install.setEnabled(False)

        btn_row.addWidget(self.btn_skip)
        btn_row.addWidget(self.btn_github)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_later)
        btn_row.addWidget(self.btn_install)
        root.addLayout(btn_row)

    def _is_downloading(self) -> bool:
        return self._download_worker is not None and self._download_worker.isRunning()

    def _on_language_changed(self, lang: str) -> None:
        self.retranslate_ui(lang)

    def retranslate_ui(self, lang: str | None = None) -> None:
        is_en = (get_language() if lang is None else lang) == 'en'
        self.setWindowTitle(
            f'Update {APP_NAME} v{self.release.version}' if is_en else f'Cập nhật {APP_NAME} v{self.release.version}'
        )
        self.lbl_title.setText(
            f'New {APP_NAME} Update Available' if is_en else f'Có bản cập nhật mới cho {APP_NAME}'
        )
        pub_date = self.release.published_at[:10] if len(self.release.published_at) >= 10 else ''
        if pub_date:
            self.lbl_subtitle.setText(
                f'Official GitHub Release · Published {pub_date}'
                if is_en
                else f'Bản phát hành chính thức từ GitHub · Ngày {pub_date}'
            )
        else:
            self.lbl_subtitle.setText(
                'Official GitHub Release' if is_en else 'Bản phát hành chính thức từ GitHub'
            )

        self.lbl_notes_heading.setText("What's New" if is_en else 'Thay đổi trong phiên bản này')
        notes = self.release.notes.strip()
        if notes:
            self.notes_browser.setMarkdown(notes)
        else:
            self.notes_browser.setPlainText(
                'Performance improvements, stability fixes, and refinements.'
                if is_en
                else 'Cải thiện hiệu năng, sửa lỗi và tối ưu độ ổn định.'
            )

        if self.install_mode == 'installed':
            self.lbl_info_banner.setText(
                'Safe in-place upgrade: BoTube will close automatically, install the update, and relaunch. '
                'Your library, playlists, subtitles, and offline AI models are preserved 100%.'
                if is_en
                else 'Nâng cấp trực tiếp an toàn: BoTube sẽ tự đóng, cập nhật nhanh rồi tự mở lại. '
                'Toàn bộ thư viện, playlist, phụ đề và mô hình AI ngoại tuyến được giữ nguyên 100%.'
            )
        elif self.install_mode == 'portable':
            self.lbl_info_banner.setText(
                'Portable build detected: downloading will launch the interactive Inno Setup installer so you can '
                'choose the installation folder without affecting your current portable data.'
                if is_en
                else 'Phát hiện bản Portable: trình cài đặt Inno Setup sẽ mở ở chế độ chọn thư mục để bạn chủ động '
                'cài đặt mà không ghi đè dữ liệu portable hiện tại.'
            )
        else:
            self.lbl_info_banner.setText(
                'Development mode detected: downloading will open the standard Inno Setup wizard cleanly.'
                if is_en
                else 'Đang chạy ở chế độ lập trình (Dev): trình cài đặt Inno Setup sẽ mở ở chế độ tiêu chuẩn.'
            )

        self.btn_skip.setText('Skip Version' if is_en else 'Bỏ qua bản này')
        self.btn_github.setText('View on GitHub' if is_en else 'Mở GitHub')
        if self._is_downloading():
            self.btn_later.setText('Cancel' if is_en else 'Hủy tải')
            self.btn_install.setText('Downloading...' if is_en else 'Đang tải...')
        else:
            self.btn_later.setText('Later' if is_en else 'Để sau')
            self.btn_install.setText('Download & Install' if is_en else 'Tải & Cài đặt ngay')

        if self._last_progress is not None and self.progress_wrap.isVisible():
            self._render_progress(*self._last_progress)
        if self._error_pair is not None and self.lbl_error.isVisible():
            self.lbl_error.setText(self._error_pair[1] if is_en else self._error_pair[0])

    def _set_error(self, vi_msg: str, en_msg: str) -> None:
        self._error_pair = (vi_msg, en_msg)
        self.lbl_error.setText(tr_pair(vi_msg, en_msg))
        self.lbl_error.show()

    def _clear_error(self) -> None:
        self._error_pair = None
        self.lbl_error.hide()
        self.lbl_error.setText('')

    def _render_progress(self, downloaded: int, total: int, speed_bps: float) -> None:
        self._last_progress = (downloaded, total, speed_bps)
        is_en = get_language() == 'en'
        if total > 0:
            pct = max(0, min(100, int(round((downloaded / total) * 100))))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            spd_str = f' · {_format_bytes(int(speed_bps))}/s' if speed_bps > 1024 else ''
            if is_en:
                txt = f'Downloading installer... {pct}% ({_format_bytes(downloaded)} / {_format_bytes(total)}{spd_str})'
            else:
                txt = f'Đang tải bộ cài... {pct}% ({_format_bytes(downloaded)} / {_format_bytes(total)}{spd_str})'
        else:
            self.progress_bar.setRange(0, 0)
            if is_en:
                txt = f'Downloading installer... {_format_bytes(downloaded)}'
            else:
                txt = f'Đang tải bộ cài... {_format_bytes(downloaded)}'
        self.lbl_progress.setText(txt)

    def _on_skip_clicked(self) -> None:
        self.skip_requested.emit(self.release.version)
        self.reject()

    def _on_open_github(self) -> None:
        QDesktopServices.openUrl(QUrl(self.release.html_url or GITHUB_RELEASES_WEB))

    def _on_later_or_cancel(self) -> None:
        if self._is_downloading():
            assert self._download_worker is not None
            self._download_worker.requestInterruption()
            self.btn_later.setEnabled(False)
            self.lbl_progress.setText(tr_pair('Đang hủy tải xuống...', 'Cancelling download...'))
            return
        self.reject()

    def _on_install_clicked(self) -> None:
        if self._is_downloading() or not self.release.download_url:
            return
        self._clear_error()
        self.progress_wrap.show()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_progress.setText(tr_pair('Đang kết nối máy chủ GitHub...', 'Connecting to GitHub...'))
        self.btn_install.setEnabled(False)
        self.btn_skip.setVisible(False)
        self.btn_later.setEnabled(True)

        worker = UpdateDownloadWorker(self.release, download_fn=self._download_fn, parent=self)
        worker.progress.connect(self._render_progress)
        worker.finished_ok.connect(self._on_download_finished)
        worker.failed.connect(self._on_download_failed)
        worker.cancelled.connect(self._on_download_cancelled)
        self._download_worker = worker
        self.retranslate_ui(get_language())
        worker.start()

    def _reset_after_download(self) -> None:
        self._download_worker = None
        self.btn_install.setEnabled(bool(self.release.download_url))
        self.btn_skip.setVisible(True)
        self.btn_later.setEnabled(True)
        self.retranslate_ui(get_language())

    def _on_download_cancelled(self) -> None:
        self.progress_wrap.hide()
        self._reset_after_download()

    def _on_download_failed(self, err_msg: str) -> None:
        self.progress_wrap.hide()
        self._reset_after_download()
        self._set_error(
            f'Không thể tải bộ cài: {err_msg}. Bạn có thể thử lại hoặc tải trực tiếp trên GitHub.',
            f'Download failed: {err_msg}. You can retry or download directly from GitHub.',
        )

    def _on_download_finished(self, installer_path: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.lbl_progress.setText(
            tr_pair(
                'Đã xác thực bộ cài. Đang khởi chạy trình cập nhật...',
                'Installer verified. Launching setup...',
            )
        )
        silent = self.install_mode == 'installed'
        target_dir = self.install_dir if silent else None
        ok, err = self._launch_fn(Path(installer_path), install_dir=target_dir, silent=silent)
        self._reset_after_download()
        if ok:
            self.install_launched.emit(installer_path)
            self.accept()
            return
        if err == 'UAC_CANCELLED':
            self._set_error(
                'Bạn đã hủy xác nhận quyền Quản trị (UAC). Bộ cài đã tải và xác thực sẵn — bấm "Tải & Cài đặt ngay" để thử lại.',
                'Administrator confirmation (UAC) was cancelled. The verified installer is cached — click "Download & Install" to retry.',
            )
        else:
            self._set_error(
                f'Không thể khởi chạy bộ cài: {err}. Bạn có thể mở GitHub để tải thủ công.',
                f'Failed to launch installer: {err}. You can open GitHub to download manually.',
            )

    def shutdown_worker(self) -> None:
        worker = self._download_worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait(1500)
        self._download_worker = None

    def closeEvent(self, event) -> None:
        self.shutdown_worker()
        if self._listener_active:
            unregister_language_listener(self._on_language_changed)
            self._listener_active = False
        super().closeEvent(event)


class AppUpdateController(QObject):
    """Lifecycle-owned auto-update orchestrator attached to `MainWindow`."""

    status_changed = Signal(str, str, str)  # (state, vi_msg, en_msg)

    def __init__(
        self,
        window,
        *,
        settings: QSettings | None = None,
        current_version: str = APP_VERSION,
        api_url: str = GITHUB_RELEASES_API,
        fetch_fn: Callable[..., ReleaseInfo | None] = fetch_latest_release,
        download_fn: Callable[..., Path] = download_installer_atomic,
        launch_fn: Callable[..., tuple[bool, str]] = launch_inno_installer,
    ):
        super().__init__(window)
        self.window = window
        self.settings = settings or QSettings('MyStudio', 'AI_Music_Player')
        self.current_version = current_version
        self.api_url = api_url
        self._fetch_fn = fetch_fn
        self._download_fn = download_fn
        self._launch_fn = launch_fn

        self._check_worker: UpdateCheckWorker | None = None
        self._manual_check = False
        self._active_dialog: UpdateDialog | None = None
        self._last_release: ReleaseInfo | None = None
        self._last_status: tuple[str, str, str] = ('idle', '', '')

        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.setInterval(_STARTUP_CHECK_DELAY_MS)
        self._startup_timer.timeout.connect(self._on_startup_timer)

        if self._should_schedule_startup_check():
            self._startup_timer.start()

    def _should_schedule_startup_check(self) -> bool:
        if os.environ.get('QT_QPA_PLATFORM', '').strip().lower() == 'offscreen':
            return False
        if os.environ.get('BOTUBE_DISABLE_AUTO_UPDATE', '').strip() == '1':
            return False
        if getattr(self.window, '_disable_auto_update_check', False):
            return False
        return self.auto_check_enabled()

    def auto_check_enabled(self) -> bool:
        return _as_bool(self.settings.value(_KEY_AUTO_CHECK, True), default=True)

    def set_auto_check_enabled(self, enabled: bool) -> None:
        self.settings.setValue(_KEY_AUTO_CHECK, bool(enabled))
        if not enabled and self._startup_timer.isActive():
            self._startup_timer.stop()

    def skipped_version(self) -> str:
        return str(self.settings.value(_KEY_SKIPPED_VER, '') or '').strip()

    def set_skipped_version(self, version: str) -> None:
        self.settings.setValue(_KEY_SKIPPED_VER, str(version or '').strip())

    def last_status(self) -> tuple[str, str, str]:
        return self._last_status

    def _emit_status(self, state: str, vi_msg: str, en_msg: str) -> None:
        self._last_status = (state, vi_msg, en_msg)
        self.status_changed.emit(state, vi_msg, en_msg)

    def _on_startup_timer(self) -> None:
        if not self.auto_check_enabled():
            return
        try:
            last_ts = float(self.settings.value(_KEY_LAST_CHECK_TS, 0.0) or 0.0)
        except (TypeError, ValueError):
            last_ts = 0.0
        if last_ts > 0.0 and (time.time() - last_ts) < _AUTO_CHECK_INTERVAL_SEC:
            return
        self.check_now(manual=False)

    def check_now(self, *, manual: bool = True) -> bool:
        """Start an asynchronous GitHub Releases update check."""
        if self._check_worker is not None and self._check_worker.isRunning():
            if manual:
                self._manual_check = True
            return False

        self._manual_check = bool(manual)
        if manual:
            self._emit_status(
                'checking',
                'Đang kiểm tra bản phát hành mới trên GitHub...',
                'Checking GitHub Releases for updates...',
            )

        worker = UpdateCheckWorker(
            current_version=self.current_version,
            api_url=self.api_url,
            fetch_fn=self._fetch_fn,
            parent=self,
        )
        worker.update_found.connect(self._on_update_found)
        worker.up_to_date.connect(self._on_up_to_date)
        worker.failed.connect(self._on_check_failed)
        worker.finished.connect(self._on_check_worker_finished)
        self._check_worker = worker
        worker.start()
        return True

    def _on_check_worker_finished(self) -> None:
        self._check_worker = None

    def _on_up_to_date(self, version_str: str) -> None:
        self.settings.setValue(_KEY_LAST_CHECK_TS, time.time())
        ver = version_str or self.current_version
        self._emit_status(
            'up_to_date',
            f'✓ Bạn đang sử dụng phiên bản mới nhất (v{ver}).',
            f'✓ You are running the latest version (v{ver}).',
        )

    def _on_check_failed(self, err_msg: str) -> None:
        if self._manual_check:
            self._emit_status(
                'error',
                f'Không thể kiểm tra cập nhật: {err_msg}',
                f'Update check failed: {err_msg}',
            )

    def _on_update_found(self, release: ReleaseInfo) -> None:
        self.settings.setValue(_KEY_LAST_CHECK_TS, time.time())
        self._last_release = release
        self._emit_status(
            'available',
            f'Đã có bản mới v{release.version} (hiện tại v{self.current_version}).',
            f'Update v{release.version} is available (current v{self.current_version}).',
        )
        if not self._manual_check and self.skipped_version() == release.version:
            return
        self.open_update_dialog(release)

    def open_update_dialog(self, release: ReleaseInfo | None = None) -> UpdateDialog | None:
        target = release or self._last_release
        if target is None:
            return None
        if self._active_dialog is not None:
            try:
                self._active_dialog.raise_()
                self._active_dialog.activateWindow()
                return self._active_dialog
            except RuntimeError:
                self._active_dialog = None

        dlg = UpdateDialog(
            target,
            current_version=self.current_version,
            download_fn=self._download_fn,
            launch_fn=self._launch_fn,
            parent=self.window,
        )
        dlg.skip_requested.connect(self.set_skipped_version)
        dlg.install_launched.connect(self._on_install_launched)
        dlg.finished.connect(self._on_dialog_closed)
        self._active_dialog = dlg
        dlg.show()
        return dlg

    def _on_dialog_closed(self, *_args) -> None:
        if self._active_dialog is not None:
            self._active_dialog.deleteLater()
            self._active_dialog = None

    def _on_install_launched(self, _installer_path: str) -> None:
        mode, _ = detect_install_mode()
        if mode == 'installed' and self.window is not None:
            # Close BoTube cleanly so Inno Setup replaces binaries with zero file locks
            QTimer.singleShot(150, self.window.close)

    def shutdown(self) -> None:
        if self._startup_timer.isActive():
            self._startup_timer.stop()
        if self._check_worker is not None and self._check_worker.isRunning():
            self._check_worker.requestInterruption()
            self._check_worker.wait(1500)
        self._check_worker = None
        if self._active_dialog is not None:
            try:
                self._active_dialog.shutdown_worker()
                self._active_dialog.close()
            except RuntimeError:
                pass
            self._active_dialog = None


def install_app_update_controller(window, *, settings: QSettings | None = None) -> AppUpdateController:
    """Attach and return an owned `AppUpdateController` on `MainWindow`."""
    existing = getattr(window, 'update_controller', None)
    if isinstance(existing, AppUpdateController):
        return existing
    ctrl = AppUpdateController(window, settings=settings)
    window.update_controller = ctrl
    return ctrl
