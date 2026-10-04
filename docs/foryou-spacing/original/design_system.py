"""Presentation tokens and styles. No playback, persistence or AI policy here."""
from PySide6.QtGui import QFont

BACKGROUND = "#0D1118"
SURFACE = "#151C26"
RAISED = "#1B2431"
BORDER = "#273445"
TEXT = "#EDF3FA"
MUTED = "#9AAABC"
ACCENT = "#77E0BE"

SHELL_STYLE = """
QMainWindow { background: #0D1118; }
QWidget#applicationShell { background: #0D1118; }
QWidget#navigationRail { background: #101722; border-right: 1px solid #273445; }
QWidget#applicationShell QLabel { color: #EDF3FA; background: transparent; border: none; }
QWidget#applicationShell QLineEdit {
    background: #151C26; color: #EDF3FA; selection-background-color: #30584F;
    border: 1px solid #273445; border-radius: 10px; padding: 0 12px;
}
QWidget#applicationShell QLineEdit:focus { border-color: #77E0BE; }
QWidget#applicationShell QPushButton {
    background: #1B2431; color: #EDF3FA; border: 1px solid #273445;
    border-radius: 9px; padding: 8px 12px; font-weight: 600;
}
QWidget#applicationShell QPushButton:hover { background: #253243; border-color: #405267; }
QWidget#applicationShell QPushButton:pressed { background: #304052; }
QWidget#applicationShell QPushButton:disabled { color: #526173; border-color: #202B38; }
QWidget#applicationShell QPushButton[role="primary"] { background: #77E0BE; color: #0D1118; border-color: #77E0BE; }
QWidget#applicationShell QPushButton[role="primary"]:hover { background: #9AEDD3; }
QWidget#applicationShell QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 0; }
QWidget#applicationShell QScrollBar::handle:vertical { background: #344254; min-height: 32px; border-radius: 4px; }
QWidget#applicationShell QScrollBar::handle:vertical:hover { background: #53667D; }
QWidget#applicationShell QScrollBar::add-line:vertical, QWidget#applicationShell QScrollBar::sub-line:vertical { height: 0; }
QWidget#applicationShell QScrollBar::add-page:vertical, QWidget#applicationShell QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #202C3B; color: #EDF3FA; border: 1px solid #405267; padding: 6px; }
"""

SIDEBAR_STYLE = """
QListWidget { background: transparent; color: #9AAABC; border: none; outline: none; }
QListWidget::item { height: 44px; border-radius: 9px; margin: 3px 10px; padding-left: 10px; font-size: 13px; }
QListWidget::item:hover { background: #1B2431; color: #EDF3FA; }
QListWidget::item:selected { background: #19372F; color: #A9F1D9; font-weight: 600; }
"""

ICON_BUTTON_STYLE = """
QPushButton { background: transparent; border: none; border-radius: 9px; padding: 4px; }
QPushButton:hover { background: #253243; }
QPushButton:pressed { background: #304052; }
"""

PLAYBACK_STYLE = """
#playbackBar { background: #111823; border-top: 1px solid #273445; }
#infoPanel { background: transparent; border-radius: 10px; }
#infoPanel:hover { background: #1B2431; }
QLabel { color: #9AAABC; font-size: 12px; border: none; background: transparent; }
#songTitle { color: #EDF3FA; font-size: 14px; font-weight: 600; }
QPushButton { background: transparent; border: none; border-radius: 9px; padding: 4px; }
QPushButton:hover { background: #253243; }
QPushButton:pressed { background: #304052; }
#playButton { background: #77E0BE; border-radius: 20px; }
#playButton:hover { background: #9AEDD3; }
#playButton:disabled { background: #273445; }
QSlider::groove:horizontal { height: 4px; background: #344254; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #77E0BE; border-radius: 2px; }
QSlider::handle:horizontal { background: #EDF3FA; width: 12px; margin: -4px 0; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: #77E0BE; }
"""

FORM_STYLE = """
QWidget { color: #EDF3FA; }
QScrollArea { border: none; background: transparent; }
QLabel { background: transparent; border: none; }
QLineEdit, QComboBox, QTextEdit {
    background: #151C26; color: #EDF3FA; border: 1px solid #273445;
    border-radius: 8px; padding: 8px; selection-background-color: #30584F;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #77E0BE; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #1B2431; color: #EDF3FA; selection-background-color: #30584F; }
QPushButton { background: #1B2431; color: #EDF3FA; border: 1px solid #273445; border-radius: 8px; padding: 8px 12px; }
QPushButton:hover { background: #253243; border-color: #405267; }
QPushButton:disabled { color: #526173; background: #151C26; }
QPushButton[role="primary"] { background: #77E0BE; color: #0D1118; border-color: #77E0BE; font-weight: 600; }
QPushButton[role="primary"]:hover { background: #9AEDD3; }
QPushButton[role="primary"]:disabled { background: #273445; border-color: #273445; color: #526173; }
QMessageBox { background: #151C26; }
"""

DIALOG_STYLE = FORM_STYLE + """
QDialog { background: #0D1118; color: #EDF3FA; font-family: 'Segoe UI'; font-size: 13px; }
QWidget#detailTab, QWidget#detailContent { background: #151C26; }
QTabWidget::pane { background: #151C26; border: 1px solid #273445; border-radius: 8px; }
QTabBar::tab { background: #1B2431; color: #9AAABC; padding: 9px 18px; margin-right: 4px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: #19372F; color: #A9F1D9; border-bottom: 2px solid #77E0BE; }
QPlainTextEdit { background: #101722; color: #EDF3FA; border: 1px solid #273445; border-radius: 8px; padding: 12px; font-family: 'Segoe UI'; font-size: 13px; }
QTableView { background: #101722; color: #EDF3FA; alternate-background-color: #151C26; border: 1px solid #273445; gridline-color: #273445; font-size: 13px; }
QTableView::item { padding: 8px; }
QTableView::item:selected { background: #30584F; color: #EDF3FA; }
QHeaderView::section { background: #1B2431; color: #A9F1D9; padding: 10px; border: 1px solid #273445; font-weight: 600; }
QHeaderView { background: #151C26; }
QTableCornerButton::section { background: #1B2431; border: 1px solid #273445; }
QPushButton#primaryButton { background: #77E0BE; color: #0D1118; border: none; }
QPushButton#primaryButton:hover { background: #9AEDD3; }
QPushButton#primaryButton:disabled { background: #273445; color: #526173; }
QScrollBar:vertical { background: #151C26; width: 8px; }
QScrollBar::handle:vertical { background: #344254; min-height: 32px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""

DOWNLOAD_PANEL_STYLE = """
QFrame { background: #151C26; border: 1px solid #273445; border-radius: 12px; }
QLabel { color: #9AAABC; font-size: 13px; font-weight: 600; border: none; background: transparent; padding: 6px; }
QTextEdit { background: #101722; color: #EDF3FA; border: 1px solid #273445; border-radius: 8px; padding: 12px; font-family: 'Segoe UI'; font-size: 13px; }
QTextEdit:focus { border-color: #77E0BE; }
"""


def apply_shell(window):
    # Scope typography to the browser; subtitle/overlay font settings stay owned
    # by their original components and are not globally overwritten.
    window.central_widget.setObjectName("applicationShell")
    window.browser_widget.setFont(QFont("Segoe UI", 10))
    window.setStyleSheet(SHELL_STYLE)
