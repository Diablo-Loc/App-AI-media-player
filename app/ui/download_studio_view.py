"""Lightweight polish + Studio download engine enhancer preserving DownloadPage's exact original layout & 1100x750 geometry."""
import json
import os
from pathlib import Path
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QPushButton,
)

from config import ConfigManager
from download_core.download_options import ORIGINAL, download_options
from download_core.studio_download_engine import (
    StudioDownloadWorker,
    StudioTitleWorker,
    audio_advice_text,
    normalize_cookies_browser,
    normalize_quality_choice,
)
from paths import project_root
from ui.i18n import get_language, normalize_language, tr_pair, translate_widget_tree
from ui.icons import ACCENT, button_icon

_COOKIE_CHOICES = (
    ("Tắt (Mặc định)", "Off (Default)", ""),
    ("Microsoft Edge", "Microsoft Edge", "edge"),
    ("Google Chrome", "Google Chrome", "chrome"),
    ("Brave", "Brave", "brave"),
    ("Firefox", "Firefox", "firefox"),
)


class DownloadStudioView(QObject):
    """Non-intrusive enhancer keeping DownloadPage's exact layout, sizeHint, and SettingMenu contract intact."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self._row_results: dict[int, bool] = {}
        self._build_polish()
        self._enhance_setting_menu()
        self._wire_signals()
        self._sync_hifi_pill()
        page.installEventFilter(self)

    def _build_polish(self):
        page = self.page

        # Insert 1 compact Hi-Fi pill button into _path_controls (0px added vertical height)
        self.btn_hifi_preset = QPushButton("Chuẩn Hi-Fi")
        self.btn_hifi_preset.setObjectName("dlHifiPillBtn")
        self.btn_hifi_preset.setFixedHeight(30)
        self.btn_hifi_preset.setMaximumWidth(148)
        self.btn_hifi_preset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_hifi_preset.setStyleSheet(
            "QPushButton#dlHifiPillBtn { background: #162B26; color: #77E0BE; border: 1px solid #2D5A4E; "
            "border-radius: 15px; padding: 0px 10px; font-size: 11px; font-weight: 600; }"
            "QPushButton#dlHifiPillBtn:hover { background: #1E3A33; border-color: #77E0BE; }"
        )
        button_icon(self.btn_hifi_preset, "sparkles", color=ACCENT, size=13, icon_only=False)

        path_controls = getattr(page, "_path_controls", None)
        if path_controls is not None and path_controls.layout() is not None:
            path_controls.layout().insertWidget(0, self.btn_hifi_preset, alignment=Qt.AlignmentFlag.AlignVCenter)
        page.combo_path.setMinimumWidth(110)

        # Clean studio placeholders & subtle dark-theme palette refinements on existing widgets
        page.txt_links.setPlaceholderText("Dán link video hoặc nhạc (mỗi dòng một link)...")
        page.txt_names.setPlaceholderText(
            "Để trống = Tự lấy tiêu đề gốc khi bấm Bắt đầu,\n"
            "hoặc bấm 'Lấy tên' / tự nhập tên từng dòng..."
        )
        page.txt_links.setStyleSheet(
            "QTextEdit { background: #0E141D; color: #EDF3FA; border: 1px solid #223042; border-radius: 8px; padding: 6px; }"
            "QTextEdit:focus { border-color: #77E0BE; }"
        )
        page.txt_names.setStyleSheet(
            "QTextEdit { background: #0E141D; color: #EDF3FA; border: 1px solid #223042; border-radius: 8px; padding: 6px; }"
            "QTextEdit:focus { border-color: #77E0BE; }"
        )
        page.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #263547; background-color: #151C26; color: #EDF3FA; "
            "font-weight: bold; font-size: 12px; border-radius: 10px; text-align: center; }"
            "QProgressBar::chunk { background-color: #24B47E; border-radius: 9px; }"
        )
        page.fail_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #35252C; background-color: #151C26; color: #F28B94; "
            "font-weight: bold; font-size: 12px; border-radius: 10px; text-align: center; }"
            "QProgressBar::chunk { background-color: #D64556; border-radius: 9px; }"
        )
        page.btn_toggle_path.setStyleSheet(
            "QPushButton { border-radius: 12px; background-color: #2A3646; border: 1px solid #3C4D63; }"
            "QPushButton:checked { background-color: #77E0BE; border-color: #77E0BE; }"
        )
        self._apply_combo_path_style(page.btn_toggle_path.isChecked())
        self._set_status_style("ok")
        self._update_target_hint_status()

    def _enhance_setting_menu(self):
        menu = self.page.setting_menu
        dl = download_options(self.page.full_config)

        # Repair displayed quality combo if legacy setting.json holds mojibake text (never mutate dict on init)
        norm_q = normalize_quality_choice(dl.get("quality", ORIGINAL))
        if menu.quality_combo.findText(norm_q) != -1 and menu.quality_combo.currentText() != norm_q:
            menu.quality_combo.blockSignals(True)
            try:
                menu.quality_combo.setCurrentText(norm_q)
            finally:
                menu.quality_combo.blockSignals(False)

        form = menu.findChild(QFormLayout)
        self.combo_cookies = QComboBox(menu)
        self.combo_cookies.setMinimumHeight(38)
        is_en = get_language() == "en"
        for vi_label, en_label, value in _COOKIE_CHOICES:
            self.combo_cookies.addItem(en_label if is_en else vi_label, value)
        saved_cookie = normalize_cookies_browser(dl.get("cookies_browser", ""))
        idx_c = self.combo_cookies.findData(saved_cookie)
        if idx_c >= 0:
            self.combo_cookies.setCurrentIndex(idx_c)
        self.combo_cookies.setToolTip(
            tr_pair(
                "Chỉ bật khi tải nhạc YouTube Music Premium hoặc video giới hạn tuổi/chống bot. "
                "Tắt mặc định để không đọc dữ liệu trình duyệt.",
                "Enable only for YouTube Music Premium or age/bot-restricted streams. "
                "Off by default to never read browser cookies.",
            )
        )
        if form is not None:
            form.addRow(tr_pair("Cookie trình duyệt:", "Browser Cookies:"), self.combo_cookies)

        self.auto_refresh_cb = QCheckBox(
            tr_pair("Tự cập nhật Thư viện khi tải xong", "Auto-refresh Library after download"), menu
        )
        self.auto_refresh_cb.setChecked(bool(dl.get("auto_refresh", True)))
        root_lay = menu.layout()
        if root_lay is not None:
            idx_cb = root_lay.indexOf(menu.auto_update_cb)
            if idx_cb >= 0:
                root_lay.insertWidget(idx_cb, self.auto_refresh_cb)
            else:
                root_lay.addWidget(self.auto_refresh_cb)

        # Unify SettingMenu popup styling with SettingsStudioView Obsidian-Slate + Mint card palette
        menu.setStyleSheet(
            menu.styleSheet()
            + "QFrame { background: #131A24; border: 1px solid #263649; border-radius: 12px; }"
            + "QComboBox { background: #151C26; border: 1px solid #273445; border-radius: 8px; }"
            + "QComboBox:hover, QComboBox:focus { border-color: #77E0BE; }"
        )
        menu.ensurePolished()
        menu.adjustSize()

    def retranslate_ui(self, lang: str | None = None) -> None:
        target = get_language() if lang is None else normalize_language(lang)
        is_en = target == "en"
        self.combo_cookies.blockSignals(True)
        try:
            for i, (vi_lbl, en_lbl, _val) in enumerate(_COOKIE_CHOICES):
                if i < self.combo_cookies.count():
                    self.combo_cookies.setItemText(i, en_lbl if is_en else vi_lbl)
        finally:
            self.combo_cookies.blockSignals(False)

        self.page.txt_links.setPlaceholderText(
            "Paste video or music URLs (one URL per line)..."
            if is_en
            else "Dán link video hoặc nhạc (mỗi dòng một link)..."
        )
        self.page.txt_names.setPlaceholderText(
            "Leave blank to auto-fetch original titles on Start,\n"
            "or click 'Fetch Titles' / enter custom names per line..."
            if is_en
            else "Để trống = Tự lấy tiêu đề gốc khi bấm Bắt đầu,\n"
            "hoặc bấm 'Lấy tên' / tự nhập tên từng dòng..."
        )
        self._sync_hifi_pill()
        self._update_target_hint_status()
        translate_widget_tree(self.page.setting_menu, target)
        translate_widget_tree(self.page, target)

    def _wire_signals(self):
        page = self.page
        for btn, old_slot in (
            (page.btn_start, page.start_download),
            (page.btn_get_name, page.get_video_names),
            (page.btn_stop, page.stop_download),
        ):
            try:
                btn.clicked.disconnect(old_slot)
            except (TypeError, RuntimeError):
                pass

        page.btn_start.clicked.connect(self.start_download)
        page.btn_get_name.clicked.connect(self.get_video_names)
        page.btn_stop.clicked.connect(self.stop_download)
        page.btn_clear.clicked.connect(self._on_cleared)
        page.btn_toggle_path.toggled.connect(self._on_toggle_path_style)
        page.combo_path.currentTextChanged.connect(lambda *_: self._update_target_hint_status())
        self.btn_hifi_preset.clicked.connect(self.apply_hifi_master_preset)

        menu = page.setting_menu
        menu.settings_saved.connect(lambda *_: self._sync_hifi_pill())
        for cb in (menu.format_combo, menu.quality_combo):
            cb.currentTextChanged.connect(
                lambda *_: QTimer.singleShot(
                    0, lambda m=menu: translate_widget_tree(m, get_language()) if get_language() == "en" else None
                )
            )
        btn_save = menu.findChild(QPushButton, "btn_save")
        if btn_save is not None:
            btn_save.clicked.connect(lambda: QTimer.singleShot(0, self._persist_extended_menu_options))

    def eventFilter(self, obj, event):
        if obj is self.page and event.type() == QEvent.Type.Show:
            self._sync_hifi_pill()
        return super().eventFilter(obj, event)

    def _set_status_style(self, kind: str = "ok"):
        color = {"ok": "#77E0BE", "err": "#F28B94", "info": "#7BCBFF", "warn": "#F2C96B"}.get(kind, "#77E0BE")
        self.page.lbl_status.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600;")

    def _apply_combo_path_style(self, checked: bool):
        if checked:
            self.page.combo_path.setStyleSheet(
                "QComboBox { background-color: #151C26; color: #EDF3FA; border: 1px solid #35475E; border-radius: 6px; padding-left: 6px; }"
                "QLineEdit { background-color: transparent; color: #EDF3FA; }"
            )
        else:
            self.page.combo_path.setStyleSheet(
                "QComboBox { background-color: #10151D; color: #546477; border: 1px solid #202B3A; border-radius: 6px; padding-left: 6px; }"
                "QLineEdit { background-color: transparent; color: #546477; }"
            )

    def _on_toggle_path_style(self, checked: bool):
        QTimer.singleShot(0, lambda c=bool(checked): (self._apply_combo_path_style(c), self._update_target_hint_status()))

    def _resolve_save_path(self) -> tuple[str | None, str]:
        page = self.page
        if page.btn_toggle_path.isChecked():
            path = page.combo_path.currentText().strip()
            if not path:
                return None, "Vui lòng chọn hoặc nhập thư mục riêng."
            return path, path
        last_folder = str(ConfigManager.get_last_folder() or "").strip()
        if last_folder and os.path.isdir(last_folder):
            return last_folder, last_folder
        default_video = project_root() / "video"
        if default_video.is_dir():
            return str(default_video), str(default_video)
        return None, "Chưa có thư mục gốc! Hãy mở thư mục video hoặc bật nút chọn thư mục riêng."

    def _update_target_hint_status(self):
        if (getattr(self.page, "download_thread", None) and self.page.download_thread.isRunning()) or (
            getattr(self.page, "title_thread", None) and self.page.title_thread.isRunning()
        ):
            return
        if self.page.btn_toggle_path.isChecked():
            txt = self.page.combo_path.currentText().strip()
            self._set_status_style("ok")
            if txt:
                self.page.lbl_status.setText(
                    tr_pair(f"Lưu theo đường dẫn riêng: {txt}", f"Custom save folder: {txt}")
                )
            else:
                self.page.lbl_status.setText(
                    tr_pair("Chế độ: Lưu theo đường dẫn tùy chỉnh.", "Mode: Save to custom folder.")
                )
        else:
            resolved, _ = self._resolve_save_path()
            self._set_status_style("ok")
            if resolved:
                self.page.lbl_status.setText(
                    tr_pair(f"Chế độ: Lưu tại thư mục App ({resolved}).", f"Mode: Save to App folder ({resolved}).")
                )
            else:
                self.page.lbl_status.setText(
                    tr_pair("Chế độ: Lưu tại thư mục của App.", "Mode: Save to App folder.")
                )

    def _sync_hifi_pill(self):
        dl = download_options(self.page.full_config)
        fmt = str(dl.get("format", "Video MP4"))
        q = normalize_quality_choice(dl.get("quality", ORIGINAL))
        res = str(dl.get("resolution", "1080p"))
        short_fmt = "MKV" if "MKV" in fmt else ("Audio" if "Audio" in fmt else "MP4")
        short_q = "Orig" if q == ORIGINAL else q.split(" ")[0]
        label = f"{short_fmt} · {short_q}"
        default_pill = tr_pair("Chuẩn Hi-Fi", "Hi-Fi Master")
        self.btn_hifi_preset.setText(f"Hi-Fi: {label}" if (fmt == "Video MKV" and q == ORIGINAL) else default_pill)
        full_tag = f"{short_fmt} · {'Original' if q == ORIGINAL else q.split(' ')[0]}" + (f" · {res}" if "Audio" not in fmt else "")
        if get_language() == "en":
            self.btn_hifi_preset.setToolTip(
                f"Click to apply Video MKV + Original (48 kHz Opus, 0% re-encode).\n"
                f"Active: {full_tag}"
            )
        else:
            self.btn_hifi_preset.setToolTip(
                f"Bấm để chọn ngay Video MKV + Original (Opus 48 kHz, 0% nén lại).\n"
                f"Đang dùng: {full_tag} — {audio_advice_text(fmt, q)}"
            )

    def _persist_extended_menu_options(self):
        page = self.page
        if not isinstance(page.full_config, dict):
            page.full_config = {}
        dl = page.full_config.setdefault("download", {})
        dl["quality"] = normalize_quality_choice(dl.get("quality", ORIGINAL))
        cookie = str(self.combo_cookies.currentData() or "")
        if cookie or "cookies_browser" in dl:
            dl["cookies_browser"] = cookie
        dl["auto_refresh"] = bool(self.auto_refresh_cb.isChecked())
        page.setting_menu.settings = page.full_config
        try:
            Path(page.settings_file).parent.mkdir(parents=True, exist_ok=True)
            with open(page.settings_file, "w", encoding="utf-8") as fh:
                json.dump(page.full_config, fh, indent=4, ensure_ascii=False)
        except OSError:
            pass
        self._sync_hifi_pill()

    def apply_hifi_master_preset(self):
        """One-click commercial Hi-Fi download preset: Video MKV + Original (48 kHz Opus, 0% re-encode)."""
        page = self.page
        menu = page.setting_menu
        menu.format_combo.blockSignals(True)
        menu.quality_combo.blockSignals(True)
        try:
            menu.format_combo.setCurrentText("Video MKV")
            menu.on_format_changed("Video MKV")
            if menu.quality_combo.findText(ORIGINAL) != -1:
                menu.quality_combo.setCurrentText(ORIGINAL)
            menu.update_quality_note()
        finally:
            menu.format_combo.blockSignals(False)
            menu.quality_combo.blockSignals(False)

        if not isinstance(page.full_config, dict):
            page.full_config = {}
        dl = page.full_config.setdefault("download", {})
        dl["format"] = "Video MKV"
        dl["quality"] = ORIGINAL
        dl["resolution"] = menu.res_combo.currentText() or dl.get("resolution", "1080p")
        dl["auto_update"] = True
        dl["auto_refresh"] = bool(self.auto_refresh_cb.isChecked())
        menu.settings = page.full_config
        try:
            Path(page.settings_file).parent.mkdir(parents=True, exist_ok=True)
            with open(page.settings_file, "w", encoding="utf-8") as fh:
                json.dump(page.full_config, fh, indent=4, ensure_ascii=False)
        except OSError as exc:
            self._set_status_style("err")
            page.lbl_status.setText(f"❌ Lỗi lưu cấu hình: {exc}")
            return

        self._sync_hifi_pill()
        self._set_status_style("ok")
        page.lbl_status.setText("✅ Đã chọn Chuẩn Hi-Fi (MKV · Original 48 kHz Opus, 0% nén lại).")

    def _on_cleared(self):
        self._row_results.clear()
        for editor in (self.page.txt_links, self.page.txt_names):
            editor.setCurrentCharFormat(QTextCharFormat())
        self._set_status_style("ok")

    def _set_running_ui(self, running: bool, *, label: str = "Đang tải..."):
        page = self.page
        page.btn_start.setEnabled(not running)
        page.btn_get_name.setEnabled(not running)
        page.btn_clear.setEnabled(not running)
        page.btn_stop.setEnabled(running)
        page.btn_start.setText(label if running else "Bắt đầu")

    def _set_main_refresh_paused(self, paused: bool):
        win = self.page.window()
        if win is not None and hasattr(win, "refresh_paused"):
            win.refresh_paused = bool(paused)

    def get_video_names(self):
        page = self.page
        links = [l.strip() for l in page.txt_links.toPlainText().splitlines() if l.strip()]
        if not links:
            self._set_status_style("err")
            page.lbl_status.setText("Lỗi: Vui lòng dán ít nhất 1 link trước khi lấy tên!")
            return
        self._row_results.clear()
        for editor in (page.txt_links, page.txt_names):
            editor.setCurrentCharFormat(QTextCharFormat())
        self._clear_editor_highlights()
        self._set_running_ui(True, label="Đang lấy...")
        page.txt_names.clear()
        cookies = str(self.combo_cookies.currentData() or "")
        worker = StudioTitleWorker(links, cookies_browser=cookies)
        page.title_thread = worker
        page._worker_owner.own(worker)
        worker.row_title_signal.connect(self._on_row_title_fetched)
        worker.status_signal.connect(page.update_status)
        worker.log_signal.connect(self._on_live_log)
        worker.finished_signal.connect(self._on_titles_finished)
        worker.start()

    def _on_live_log(self, text: str):
        self.page.parse_live_log(text)
        if "[download]" in text and "%" in text:
            self._set_status_style("info")

    def _on_titles_finished(self, ok_count: int, total: int):
        self._set_running_ui(False)
        self.page.btn_get_name.setText("Lấy tên")
        self._set_status_style("ok" if ok_count == total else "warn")

    def _on_row_title_fetched(self, row_index: int, title: str, ok: bool):
        self._set_row_title_at(row_index, title if ok else "")
        if not ok:
            self._record_and_highlight_row(row_index, False)

    def _clear_editor_highlights(self):
        for editor in (self.page.txt_links, self.page.txt_names):
            doc = editor.document()
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.setCharFormat(QTextCharFormat())

    def _reapply_all_highlights(self):
        for idx, ok in list(self._row_results.items()):
            self._highlight_row(idx, ok)

    def _record_and_highlight_row(self, index: int, success: bool):
        self._row_results[index] = bool(success)
        self._highlight_row(index, success)

    def _set_row_title_at(self, row_index: int, title: str):
        lines = self.page.txt_names.toPlainText().splitlines()
        while len(lines) <= row_index:
            lines.append("")
        lines[row_index] = title
        self.page.txt_names.setPlainText("\n".join(lines))
        self._reapply_all_highlights()

    def _highlight_row(self, index: int, success: bool):
        color = "#77E0BE" if success else "#F28B94"
        for editor in (self.page.txt_links, self.page.txt_names):
            doc = editor.document()
            if index >= doc.blockCount():
                continue
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(index):
                cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            fmt = cursor.charFormat()
            fmt.setForeground(QColor(color))
            cursor.setCharFormat(fmt)

    def start_download(self):
        page = self.page
        links = [l.strip() for l in page.txt_links.toPlainText().splitlines() if l.strip()]
        raw_names = [n.strip() for n in page.txt_names.toPlainText().splitlines()]
        has_any_name = any(raw_names)

        if not links:
            self._set_status_style("err")
            page.lbl_status.setText("Lỗi: Vui lòng dán link video hoặc nhạc cần tải!")
            return
        if has_any_name and len(raw_names) != len(links):
            self._set_status_style("err")
            page.lbl_status.setText(
                f"Lỗi: Số link ({len(links)}) và số dòng Tên ({len(raw_names)}) không khớp! (Để trống Tên nếu muốn tự lấy tiêu đề)"
            )
            return

        save_path, display = self._resolve_save_path()
        if not save_path:
            self._set_status_style("err")
            page.lbl_status.setText(f"Lỗi: {display}")
            return
        if not os.path.exists(save_path):
            try:
                os.makedirs(save_path, exist_ok=True)
            except OSError:
                self._set_status_style("err")
                page.lbl_status.setText("Lỗi: Đường dẫn thư mục không hợp lệ!")
                return

        self._row_results.clear()
        self._clear_editor_highlights()
        page.current_save_path = save_path
        page.progress_bar.setMaximum(len(links))
        page.fail_bar.setMaximum(len(links))
        page.progress_bar.setFormat(f"%v/{len(links)}")
        page.fail_bar.setFormat(f"%v/{len(links)}")
        page.progress_bar.setValue(0)
        page.fail_bar.setValue(0)
        self._set_status_style("ok")
        self._set_running_ui(True)

        auto_title = not has_any_name
        names_arg = [] if auto_title else raw_names
        dl_cfg = {"download": dict(download_options(page.full_config))}
        dl_cfg["download"]["quality"] = normalize_quality_choice(dl_cfg["download"].get("quality", ORIGINAL))
        cookies = str(self.combo_cookies.currentData() or "")
        worker = StudioDownloadWorker(
            links,
            names_arg,
            save_path,
            dl_cfg,
            auto_title=auto_title,
            cookies_browser=cookies,
        )
        page.download_thread = worker
        page._worker_owner.own(worker)
        worker.progress_signal.connect(lambda ok_c, total: page.progress_bar.setValue(ok_c))
        worker.fail_signal.connect(lambda err_c, total: page.fail_bar.setValue(err_c))
        worker.row_result_signal.connect(self._record_and_highlight_row)
        worker.resolved_title_signal.connect(self._set_row_title_at)
        worker.status_signal.connect(page.update_status)
        worker.log_signal.connect(self._on_live_log)
        worker.finished_signal.connect(self._on_download_finished)
        page.download_started_signal.emit()
        worker.start()

    def _on_download_finished(self, success_count: int):
        page = self.page
        self._set_running_ui(False)
        if success_count > 0:
            page.btn_refresh_all.setEnabled(True)
            self._set_status_style("ok")
            page.lbl_status.setText(f"🎉 Hoàn tất! Tải thành công {success_count} tệp.")
            if self.auto_refresh_cb.isChecked():
                page.trigger_manual_refresh()
            else:
                self._set_main_refresh_paused(False)
        else:
            self._set_main_refresh_paused(False)
            self._set_status_style("warn")
            page.lbl_status.setText("⚠️ Chưa tải được tệp nào. Kiểm tra link hoặc bật Cookie trong ⚙️.")

    def stop_download(self):
        page = self.page
        stopped = False
        for attr in ("download_thread", "title_thread"):
            thr = getattr(page, attr, None)
            if thr is not None and thr.isRunning():
                thr.stop()
                stopped = True
        if stopped:
            self._set_status_style("err")
            page.lbl_status.setText("⏹️ Đang hủy quá trình tải...")
            page.btn_stop.setEnabled(False)
            self._set_main_refresh_paused(False)


def install_download_studio_view(window) -> DownloadStudioView | None:
    """Attach lightweight DownloadStudioView onto window.download_page if present."""
    page = getattr(window, "download_page", None)
    if page is None:
        return None
    view = DownloadStudioView(page)
    page.studio_view = view
    return view
