"""Offline Qt workload; snapshots allow the same before/after measurement."""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import time
from types import SimpleNamespace
from unittest.mock import patch

from tools.ui_preview import APPLICATION, ROOT, pump


def wait_ready(page):
    deadline = time.monotonic() + 4
    while getattr(getattr(page, '_playlist_view', None), 'is_busy', False):
        if time.monotonic() >= deadline:
            raise RuntimeError('Playlist loading did not settle')
        APPLICATION.processEvents()
        time.sleep(.002)


def run(before=False, count=1000, rounds=3):
    if before:
        spec = importlib.util.spec_from_file_location(
            "ui.pages.foryou_before", ROOT / "docs/foryou-search/original/for_you.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        from ui.pages import for_you as module
    records = []
    items = [SimpleNamespace(id=str(i), title=f"Track {i:05d}", artist="Artist",
                             thumbnail=None, mtime=i) for i in range(count)]
    for _ in range(rounds):
        page = module.ForYouPage()
        # Avoid native/window maximize influencing the comparison viewport.
        with patch.object(page, "showEvent", lambda e: None):
            page.resize(1280, 820)
            page.show()
            pump(30)
            created = [0]
            original = page.create_playlist_card
            def create(*args):
                created[0] += 1
                return original(*args)
            page.create_playlist_card = create
            page.current_playing_id = items[-1].id
            start = time.perf_counter()
            page.load_playlist(items)
            load_ms = (time.perf_counter() - start) * 1000
            pump(30)
            page.search_input.setText(items[-1].title)
            page.search_timer.stop()
            start = time.perf_counter()
            page.execute_filter()
            filter_submit_ms = (time.perf_counter() - start) * 1000
            wait_ready(page)
            filter_ms = (time.perf_counter() - start) * 1000
            pump(30)
            created[0] = 0
            start = time.perf_counter()
            page.search_input.clear()
            if page.search_timer.isActive():
                page.search_timer.stop()
                page.execute_filter()
            clear_submit_ms = (time.perf_counter() - start) * 1000
            wait_ready(page)
            clear_ms = (time.perf_counter() - start) * 1000
            clear_created = created[0]
            pump(30)
            start = time.perf_counter()
            page.playlist_scroll.verticalScrollBar().setValue(
                page.playlist_scroll.verticalScrollBar().maximum())
            pump(40)
            scroll_ms = (time.perf_counter() - start) * 1000
            records.append(dict(load_ms=load_ms, filter_ms=filter_ms, clear_ms=clear_ms,
                                filter_submit_ms=filter_submit_ms, clear_submit_ms=clear_submit_ms,
                                clear_cards_created=clear_created,
                                live_cards=len(page.cards_map), scroll_with_40ms_pump=scroll_ms))
        page.search_timer.stop()
        page.close()
        page.deleteLater()
        pump(50)
    return dict(before=before, items=count, rounds=rounds, records=records,
                medians={key: statistics.median(r[key] for r in records) for key in records[0]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", action="store_true")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.before, args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["medians"], indent=2))
