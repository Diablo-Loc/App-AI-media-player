import re
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QLabel,
    QTabWidget, QWidget, QTableView, QHeaderView, QComboBox, QProgressBar,
    QAbstractItemView, QStyledItemDelegate, QLineEdit
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack, QUndoCommand

from ui.subs_ui.subtitle_model import SubtitleTableModel
from ui.subs_ui.subtitle_dialog_logic import SubtitleToolsDialogLogic
from ..icons import button_icon, icon, INK
from ..design_system import DIALOG_STYLE


class SubtitleCellEditDelegate(QStyledItemDelegate):
    """Keep inline subtitle edits readable inside the compact table rows."""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setObjectName("subtitleCellEditor")
        editor.setAutoFillBackground(True)
        editor.setStyleSheet(
            "QLineEdit#subtitleCellEditor {"
            "background: #0D1118; color: #EDF3FA;"
            "border: 2px solid #77E0BE; border-radius: 4px;"
            "padding: 2px 6px;"
            "selection-background-color: #77E0BE;"
            "selection-color: #0D1118;"
            "}"
        )
        font = index.data(Qt.FontRole)
        if font is not None:
            editor.setFont(font)
        if index.column() in (0, 1):
            editor.setAlignment(Qt.AlignCenter)
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.EditRole)
        editor.setText("" if value is None else str(value))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(1, 1, -1, -1))


class SubtitleToolsDialog(SubtitleToolsDialogLogic, QDialog):
    def __init__(self, media_path: str = "", media_id: str = "", parent=None):
        QDialog.__init__(self, parent)
        self.media_path = media_path
        self.media_id = media_id
        self.raw_data = None
        self.detected_lang = "auto"
        self.sub_path = ""
        self.trans_worker = None
        self.align_worker = None
        self.is_online_translation = False
        self.active_row_index = -1

        self.setWindowTitle("Quản Lý & Chỉnh Sửa Phụ Đề Đa Ngôn Ngữ")
        self.resize(1150, 750)

        self.init_ui()
        self.setStyleSheet(DIALOG_STYLE)
        self.init_shortcuts()

        self.active_row_index = -1

        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(200)
        self.playback_timer.timeout.connect(self._sync_active_sub_highlight)

        self._connected_player = None
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.on_reload_clicked()

    def init_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_subtitle_content)
        QShortcut(QKeySequence("Ctrl+V"), self, self._handle_paste_shortcut)
        try:
            QShortcut(QKeySequence.Undo, self, lambda: self.undo_stack.undo())
            QShortcut(QKeySequence.Redo, self, lambda: self.undo_stack.redo())
        except Exception:
            pass

        QShortcut(QKeySequence("Ctrl+K"), self, self._shortcut_split_current)
        QShortcut(QKeySequence("Ctrl+M"), self, self._shortcut_merge_current)
        QShortcut(QKeySequence("Ctrl+Right"), self, lambda: self._shortcut_shift_current(0.5))
        QShortcut(QKeySequence("Ctrl+Left"), self, lambda: self._shortcut_shift_current(-0.5))

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        self.lbl_info = QLabel("<b>📂 Bài hiện tại:</b> Đang nạp...")
        self.lbl_info.setStyleSheet("color: #3ea6ff; padding: 2px;")
        header_layout.addWidget(self.lbl_info, stretch=1)

        header_layout.addWidget(QLabel(" Ngôn ngữ gốc:"))
        self.combo_lang = QComboBox()
        self.combo_lang.addItems(["AUTO", "JA", "EN", "VI", "KO", "ZH", "FR", "DE", "ES"])
        self.combo_lang.currentTextChanged.connect(self._on_lang_changed)
        header_layout.addWidget(self.combo_lang)

        # Additive burn-in export action.  The controller snapshots the live
        # subtitle presentation and never mutates this editor or playback.
        from ui.video_subtitle_export import VideoExportButton
        header_layout.addWidget(VideoExportButton(self))

        layout.addLayout(header_layout)

        self.tabs = QTabWidget()

        self.tab_orig = QWidget()
        layout_orig = QVBoxLayout(self.tab_orig)

        orig_tools = QHBoxLayout()
        self.btn_align = QPushButton("Khớp & Sửa Lời Chuẩn (Align Lyrics)")
        button_icon(self.btn_align, "sparkles", "Khớp & Sửa Lời Chuẩn", icon_only=False)
        self.btn_align.clicked.connect(self.align_whisper_with_reference)
        orig_tools.addWidget(self.btn_align)
        orig_tools.addStretch()
        layout_orig.addLayout(orig_tools)

        self.editor_orig = QPlainTextEdit()
        layout_orig.addWidget(self.editor_orig)
        self.tabs.addTab(self.tab_orig, icon("languages"), "Phụ Đề Gốc (Văn Bản)")

        self.tab_combined = QWidget()
        layout_combined = QVBoxLayout(self.tab_combined)

        table_tools = QHBoxLayout()
        btn_add_row = QPushButton("Thêm Dòng")
        button_icon(btn_add_row, "plus", "Thêm Dòng", icon_only=False)
        btn_add_row.clicked.connect(self._add_table_row)
        btn_del_row = QPushButton("Xóa Dòng Đang Chọn")
        button_icon(btn_del_row, "trash", "Xóa dòng đang chọn", icon_only=False)
        btn_del_row.clicked.connect(self._delete_table_row)

        btn_paste = QPushButton("Dán (Ctrl+V)")
        button_icon(btn_paste, "clipboard", "Dán từ Clipboard (Ctrl+V)", icon_only=False)
        btn_paste.clicked.connect(self.paste_to_table)
        btn_import = QPushButton("Import")
        button_icon(btn_import, "download", "Import phụ đề", icon_only=False)
        btn_import.clicked.connect(self._import_subs)
        btn_export = QPushButton("Export")
        button_icon(btn_export, "upload", "Export phụ đề", icon_only=False)
        btn_export.clicked.connect(self._export_subs)

        table_tools.addWidget(btn_add_row)
        table_tools.addWidget(btn_del_row)
        table_tools.addWidget(btn_paste)
        table_tools.addWidget(btn_import)
        table_tools.addWidget(btn_export)
        btn_snap = QPushButton("Snap 0.05s")
        btn_snap.clicked.connect(self._snap_times)
        table_tools.addWidget(btn_snap)

        self.lbl_sync_status = QLabel("🎵 Đang đồng bộ thời gian thực")
        self.lbl_sync_status.setStyleSheet("color: #ffb74d; font-size: 12px; font-style: italic; margin-left: 10px;")
        table_tools.addWidget(self.lbl_sync_status)

        table_tools.addStretch()
        layout_combined.addLayout(table_tools)

        self.table_model = SubtitleTableModel([])
        self.table_combined = QTableView()
        self.table_combined.setAlternatingRowColors(True)
        self.undo_stack = QUndoStack(self)
        # connect model changes to undo handler in logic
        try:
            self.table_model.dataChanged.connect(self._on_model_data_changed)
        except Exception:
            pass

        self.table_combined.setModel(self.table_model)
        self.table_combined.setItemDelegate(SubtitleCellEditDelegate(self.table_combined))
        self.table_combined.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_combined.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_combined.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_combined.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_combined.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table_combined.verticalHeader().setDefaultSectionSize(36)
        self.table_combined.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_combined.setObjectName("subtitleTable")
        layout_combined.addWidget(self.table_combined)

        self.table_combined.doubleClicked.connect(self._on_row_double_clicked)
        self.table_combined.clicked.connect(self._on_row_clicked)
        self.table_combined.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table_combined.customContextMenuRequested.connect(self._on_table_context_menu)

        self.tabs.addTab(self.tab_combined, icon("captions"), "Bảng Phụ Đề Đa Ngôn Ngữ")
        layout.addWidget(self.tabs)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("QProgressBar { border: none; background: #2c2c2e; } QProgressBar::chunk { background: #3ea6ff; }")
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()

        btn_copy = QPushButton("Copy tab")
        button_icon(btn_copy, "clipboard", "Copy tab hiện tại", icon_only=False)
        btn_copy.setObjectName("secondaryButton")
        btn_copy.setToolTip("Copy nội dung tab hiện tại")
        btn_copy.clicked.connect(self.copy_text)
        btn_layout.addWidget(btn_copy)

        self.btn_undo = QPushButton("Undo")
        button_icon(self.btn_undo, "undo", "Hoàn tác", icon_only=False)
        self.btn_undo.setObjectName("secondaryButton")
        self.btn_undo.setToolTip("Hoàn tác thao tác (Ctrl+Z)")
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self.undo_stack.undo)
        self.btn_undo.setShortcut(QKeySequence.Undo)
        btn_layout.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("Redo")
        button_icon(self.btn_redo, "redo", "Làm lại", icon_only=False)
        self.btn_redo.setObjectName("secondaryButton")
        self.btn_redo.setToolTip("Làm lại thao tác (Ctrl+Y)")
        self.btn_redo.setEnabled(False)
        self.btn_redo.clicked.connect(self.undo_stack.redo)
        self.btn_redo.setShortcut(QKeySequence.Redo)
        btn_layout.addWidget(self.btn_redo)

        btn_reload = QPushButton("Nạp lại")
        button_icon(btn_reload, "refresh-cw", "Nạp lại phụ đề", icon_only=False)
        btn_reload.setObjectName("secondaryButton")
        btn_reload.clicked.connect(self.on_reload_clicked)
        btn_layout.addWidget(btn_reload)

        self.btn_translate = QPushButton("Dịch (AI)")
        button_icon(self.btn_translate, "languages", "Tự động dịch (AI)", color=INK, icon_only=False)
        self.btn_translate.setObjectName("primaryButton")
        self.btn_translate.clicked.connect(self.start_auto_translation)
        btn_layout.addWidget(self.btn_translate)

        self.undo_stack.canUndoChanged.connect(self.btn_undo.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.btn_redo.setEnabled)
        # connect tooltip updater directly so it can be disconnected reliably
        try:
            self.undo_stack.canUndoChanged.connect(self._update_undo_redo_tooltips)
            self.undo_stack.canRedoChanged.connect(self._update_undo_redo_tooltips)
        except Exception:
            pass

        btn_layout.addStretch()

        btn_cancel = QPushButton("Hủy")
        btn_cancel.setObjectName("secondaryButton")
        btn_cancel.clicked.connect(self.reject)
        btn_hide = QPushButton("Về app")
        button_icon(btn_hide, "eye-off", "Ẩn và quay lại app", icon_only=False)
        btn_hide.setObjectName("secondaryButton")
        btn_hide.clicked.connect(self._hide_and_return)
        btn_hide.setToolTip("Ẩn cửa sổ này và quay lại ứng dụng (không lưu, không đóng)")
        btn_hide.setShortcut(QKeySequence("Ctrl+H"))
        btn_layout.addWidget(btn_hide)
        btn_layout.addWidget(btn_cancel)

        self.btn_save = QPushButton("Lưu (Ctrl+S)")
        button_icon(self.btn_save, "save", "Lưu và cập nhật (Ctrl+S)", color=INK, icon_only=False)
        self.btn_save.setObjectName("primaryButton")
        self.btn_save.setShortcut(QKeySequence("Ctrl+S"))
        self.btn_save.clicked.connect(self.save_subtitle_content)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)


    def _update_undo_redo_tooltips(self):
        # Be defensive: undo_stack may be deleted before this slot runs
        try:
            us = getattr(self, 'undo_stack', None)
            if us is None:
                return
            can_undo = False
            can_redo = False
            try:
                can_undo = bool(us.canUndo())
            except Exception:
                can_undo = False
            try:
                can_redo = bool(us.canRedo())
            except Exception:
                can_redo = False
        except Exception:
            return

        try:
            if getattr(self, 'btn_undo', None):
                self.btn_undo.setToolTip("Hoàn tác thao tác (Ctrl+Z)" if can_undo else "Không có thao tác để hoàn tác")
            if getattr(self, 'btn_redo', None):
                self.btn_redo.setToolTip("Làm lại thao tác (Ctrl+Y)" if can_redo else "Không có thao tác để làm lại")
        except Exception:
            # Avoid propagating UI errors when widgets are being destroyed
            pass

    def _on_lang_changed(self, new_lang: str):
        self.detected_lang = new_lang.lower()
