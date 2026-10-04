"""Render playlist, download popup and compact rail using isolated Qt fixtures."""
import argparse
from pathlib import Path

from tools.ui_preview import isolated_window, populate, pump
from PySide6.QtCore import QCoreApplication, QEvent


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    with isolated_window() as (window, root):
        items = populate(window, root)[:4]
        for item, title in zip(items, (
            "A Small Miracle", "Empty old City -", "Brand New Sky",
            "Unwavering Starch — Một tựa bài hát dài để kiểm tra bố cục",
        )):
            item.title = title
            item.artist = "Wuthering Waves, Fleet S — Nghệ sĩ và tên kênh rất dài"
        page = window.foryou_page
        page.load_playlist(items)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        page.mark_playing_item(items[-1].id)
        window.content_stack.setCurrentIndex(1)
        pump(400)
        page.playlist_container.grab().save(str(output / "playlist.png"))
        window.content_stack.setCurrentIndex(3)
        window.download_page.open_settings_dialog()
        pump(100)
        menu = window.download_page.setting_menu
        menu.grab().save(str(output / "download-settings.png"))
        print("Popup:", menu.size().toTuple(), "minimum:", menu.minimumSizeHint().toTuple())
        print("Combos:", [(combo.size().toTuple(), combo.fontMetrics().height())
                           for combo in (menu.format_combo, menu.quality_combo, menu.res_combo)])
        window.toggle_nav_animation()
        pump(250)
        window.sidebar_container.grab().save(str(output / "sidebar.png"))
        print("Rail/button:", window.sidebar_container.width(), window.btn_menu.geometry().getRect())
    print("Rendered layout fixtures:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    render(parser.parse_args().output)
