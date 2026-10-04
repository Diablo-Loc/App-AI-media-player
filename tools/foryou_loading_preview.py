"""Render search/clear loading and completed states with isolated Qt data."""
from pathlib import Path
import argparse

from tools.ui_preview import isolated_window, populate, pump
from tools.foryou_search_probe import wait_ready


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    with isolated_window() as (window, root):
        items = populate(window, root)
        def preview_maximized():
            window.showNormal()
            window.resize(1280, 820)
        window.showMaximized = preview_maximized
        window.sidebar.setCurrentRow(1)
        window.handle_sidebar_click(window.sidebar.item(1))
        page = window.foryou_page
        page.update_art(items[0])
        page.mark_playing_item(items[0].id)
        pump(120)
        page.search_input.setText('Quiet')
        pump(60)
        assert page._playlist_view.loading.isVisible()
        window.grab().save(str(output / 'search-loading.png'))
        wait_ready(page)
        window.grab().save(str(output / 'search-ready.png'))
        page.search_input.clear()
        assert page._playlist_view.loading.isVisible()
        window.grab().save(str(output / 'clear-loading.png'))
        wait_ready(page)
        window.grab().save(str(output / 'clear-ready.png'))
        from ui.playlist_thumbnail_queue import thumbnail_queue
        thumbnail_queue().pool.waitForDone(3000)
        pump(30)
    print('Rendered four loading/result states:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    render(args.output)
