"""Render actual restored Qt widgets with synthetic media and isolated storage.

No model, downloader or native audio engine is started. The native/video/GPU/EXE
integration remains a separate manual check. Useful for before/after reviews.
"""
import argparse
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import subprocess
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QLinearGradient, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

APPLICATION = QApplication.instance() or QApplication([])
# The offscreen plugin does not enumerate Windows system fonts automatically.
if os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen"):
    for font in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf", "seguiemj.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
    APPLICATION.setFont(QFont("Segoe UI", 10))


def pump(milliseconds=100):
    end = time.monotonic() + milliseconds / 1000
    while time.monotonic() < end:
        APPLICATION.processEvents()
        time.sleep(0.002)


@contextmanager
def isolated_window():
    with tempfile.TemporaryDirectory(prefix="botube-ui-") as directory, ExitStack() as stack:
        root = Path(directory)
        storage = root / "storage"
        storage.mkdir()
        # Install the path adapter BEFORE importing modules that capture paths.
        paths = types.ModuleType("paths")
        paths.project_root = lambda: root
        paths.storage_dir = lambda: storage
        paths.input_dir = lambda: root
        paths.asset_dir = lambda name=None: ROOT / (name or "")
        paths.get_icon_path = lambda name="app_icon.ico": ROOT / "icon" / name
        paths.get_input_path = lambda name: root / name
        paths.init_folders = lambda: None
        stack.enter_context(patch.dict(sys.modules, {"paths": paths}))
        from ui.main_window import MainWindow
        from core.media_library import MediaLibrary
        from core.subtitle_manager import SubtitleManager
        import config
        # Path globals captured on a previous preview also need a new temp root.
        stack.enter_context(patch.object(config, "CONFIG_FILE", str(storage / "app_config.json")))
        for module_name in ("ui.main_window", "ui.pages.download", "ui.pages.settings_dialog"):
            module = sys.modules.get(module_name)
            if module and hasattr(module, "storage_dir"):
                stack.enter_context(patch.object(module, "storage_dir", lambda: storage))
        preferences = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
        stack.enter_context(patch("ui.pages.settings.QSettings", return_value=preferences))
        stack.enter_context(patch("ui.pages.settings.check_resource_status", return_value={"whisper": {}}))
        stack.enter_context(patch("ui.main_window.ConfigManager.get_last_folder", return_value=""))
        stack.enter_context(patch("ui.main_window.SystemMediaManager", return_value=Mock(enabled=False)))
        stack.enter_context(patch("ui.main_window.TempFileManager.TEMP_DIR", root / "temp"))
        stack.enter_context(patch("ui.main_window.psutil.Process"))
        window = MainWindow(SubtitleManager(str(storage)), Mock(), MediaLibrary(str(storage / "library.json")))
        try:
            window.resize(1280, 820)
            window.show()
            pump(150)
            yield window, root
        finally:
            window.mini_player.hide()
            window.sub_layer.hide()
            window.playback_bar.info_popup.hide()
            window.close()
            window.deleteLater()
            pump(30)


def populate(window, root):
    from core.media_library import MediaMetadata
    titles = ["Midnight in Tokyo", "A little closer", "Golden hour", "Blue horizon", "After the rain", "Quiet moments", "City lights", "Stay with me", "Dreams in motion", "New beginnings", "The last summer", "Somewhere we belong"]
    colors = ["#366F80", "#A56D70", "#AD9066", "#535F9B", "#567D70", "#77608F"]
    items = []
    for index, title in enumerate(titles):
        image = QImage(640, 360, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        gradient = QLinearGradient(0, 0, 640, 360)
        gradient.setColorAt(0, QColor(colors[index % len(colors)]))
        gradient.setColorAt(1, QColor("#141B27"))
        painter.fillRect(image.rect(), gradient)
        painter.setPen(QColor(255, 255, 255, 45))
        for radius in (80, 125, 175):
            painter.drawEllipse(420-radius, 180-radius, radius*2, radius*2)
        painter.setPen(QColor("#F1F5F9"))
        painter.setFont(QFont("Segoe UI", 22, QFont.Weight.DemiBold))
        painter.drawText(36, 230, title)
        painter.end()
        cover = root / f"cover-{index}.png"
        image.save(str(cover))
        items.append(MediaMetadata(id=str(index), path=str(root / f"track-{index}.mp4"), title=title, artist=["Luna", "Studio Sessions", "Haru"][index % 3], duration=215, thumbnail=str(cover), mtime=1700000000 + index))
    window.all_media_items = items
    window.update_media_grid(items.copy())
    window.foryou_page.load_playlist(items.copy())
    window.playback_bar.set_media_info(items[0].title, items[0].artist, items[0])
    window.playback_bar.update_duration(215000, "03:35")
    window.playback_bar.update_position(73000, "01:13")
    return items


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    with isolated_window() as (window, root):
        items = populate(window, root)
        selected = next(item for item in items if item.id == "0")
        # Offscreen's virtual screen is 800x800. Keep the comparison viewport
        # consistent; actual maximize/restore is exercised by UI tests instead.
        def preview_maximized():
            window.showNormal()
            window.resize(1280, 820)
        window.showMaximized = preview_maximized
        for index, name in ((0, "home"), (2, "library"), (1, "for-you"), (3, "download"), (4, "settings")):
            window.sidebar.setCurrentRow(index)
            window.handle_sidebar_click(window.sidebar.item(index))
            if index == 1:
                window.foryou_page.update_art(selected)
                window.foryou_page.mark_playing_item(selected.id)
            pump(350)
            window.grab().save(str(output / f"{name}.png"))
        window.mini_player.update_info(selected.title, selected.artist, True, selected.thumbnail)
        window.mini_player.show()
        pump()
        window.mini_player.grab().save(str(output / "mini-player.png"))
        window.mini_player.hide()
        from ui.subs_ui.lyric_settings_dialog import SubtitleToolsDialog
        from ui.subs_ui.subtitle_dialog_logic import SubtitleToolsDialogLogic
        from PySide6.QtWidgets import QDialog
        # The ORIGINAL mixed-inheritance dialog also crashes at signal binding
        # in this offscreen runtime (see UI_REFRESH.md). This preview-only adapter
        # puts QDialog first to review the unchanged init_ui visually. It does
        # NOT validate the production dialog's lifecycle or modify its MRO.
        members = {name: value for name, value in SubtitleToolsDialog.__dict__.items()
                   if callable(value) and name not in ("__new__",)}
        members["on_reload_clicked"] = lambda self: None
        PreviewDialog = type("SubtitlePreviewDialog", (QDialog, SubtitleToolsDialogLogic), members)
        dialog = PreviewDialog(parent=window)
        dialog.show()
        pump()
        dialog.grab().save(str(output / "subtitle-tools.png"))
        dialog.tabs.setCurrentIndex(1)
        dialog.table_model.set_segments([{"start": 1.25, "end": 4.75, "jp": "Original lyric", "en": "English lyric", "vi": "Loi dich"}])
        pump()
        dialog.grab().save(str(output / "subtitle-table.png"))
        dialog.hide()
        dialog.deleteLater()
        window.playback_bar.info_popup.show()
        pump()
        window.playback_bar.info_popup.grab().save(str(output / "media-info.png"))
        window.playback_bar.info_popup.hide()
    print(f"Rendered 9 Qt views: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true", help="Render the captured original Git revision in a temporary tree")
    arguments = parser.parse_args()
    if arguments.baseline:
        with tempfile.TemporaryDirectory(prefix="botube-original-ui-") as directory:
            shadow = Path(directory)
            names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "4148c138c1e38f4959574caf925f1c86dbcca339", "--", "app"], cwd=ROOT).decode().splitlines()
            for name in names:
                if not name.endswith((".py", ".json")):
                    continue
                target = (shadow / name).resolve()
                if not target.is_relative_to(shadow.resolve()):
                    raise ValueError(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(["git", "show", f"4148c138c1e38f4959574caf925f1c86dbcca339:{name}"], cwd=ROOT))
            sys.path.insert(0, str(shadow))
            sys.path.insert(0, str(shadow / "app"))
            render(arguments.output)
    else:
        render(arguments.output)
