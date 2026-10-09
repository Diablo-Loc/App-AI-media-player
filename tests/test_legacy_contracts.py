from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import contextlib
from dataclasses import asdict
import io
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple
import unittest
from unittest.mock import Mock, patch

from app.core.media_library import MediaLibrary, SUPPORTED_EXTS, get_raw_metadata
from app.core.subtitle_manager import SubtitleManager
from app.media.identity import media_id_for_path
from app.media.models import MediaMetadata
from app.playback.playlist import adjacent_item

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "legacy_contracts.json").read_text(encoding="utf-8"))


def original(name, **extra):
    # These are frozen snippets of our own baseline, never user/network input.
    namespace = dict(Path=Path, List=List, Dict=Dict, Tuple=Tuple, Any=Any,
                     MediaMetadata=MediaMetadata, SUPPORTED_EXTS=SUPPORTED_EXTS,
                     logger=logging.getLogger("legacy"), sys=sys,
                     subprocess=subprocess, json=json)
    namespace.update(extra)
    source = FIXTURE["contracts"][name]["source"]
    exec(compile(source, f"baseline:{name}", "exec"), namespace)
    names = {"navigate": "_navigate_active_playlist", "scan": "scan_folder", "clean_segment": "_clean_segment", "raw_metadata": "get_raw_metadata"}
    return namespace[names[name]]


class LegacyContractTests(unittest.TestCase):
    def test_playlist_matches_original_with_duplicate_ids_and_boundaries(self):
        navigate = original("navigate")
        items = [MediaMetadata("same", "a", "A"), MediaMetadata("same", "b", "B"), MediaMetadata("other", "c", "C")]
        for playlist in ([], items):
            for current in (None, items[0], items[1], MediaMetadata("same", "b", "B"), MediaMetadata("missing", "d", "D")):
                for direction in (-5, -1, 0, 1, 5):
                    with self.subTest(current=current, direction=direction, count=len(playlist)):
                        callback = Mock()
                        old = SimpleNamespace(active_playlist=playlist, current_media_item=current, on_media_clicked=callback)
                        with contextlib.redirect_stdout(io.StringIO()):
                            navigate(old, direction)
                        result = adjacent_item(playlist, current, direction)
                        if callback.called:
                            self.assertIs(result, callback.call_args.args[0])
                            self.assertFalse(callback.call_args.kwargs["update_playlist"])
                        else:
                            self.assertIsNone(result)

    def test_subtitle_object_outputs_match_original(self):
        clean = original("clean_segment")
        samples = [
            SimpleNamespace(start=0.02, end=1.23456, top=" 日本語 ", middle=SimpleNamespace(text=" English "), bottom=" Tiếng Việt "),
            SimpleNamespace(start=4.52, end=6.79, text=" raw ASR "),
            SimpleNamespace(start=0, end=0),
            SimpleNamespace(start="invalid", end=1),
        ]
        for sample in samples:
            with self.subTest(sample=sample), patch("app.core.subtitle_manager.logger"), patch("logging.Logger.error"):
                self.assertEqual(SubtitleManager._clean_segment(None, sample), clean(None, sample))

    def test_metadata_tags_duration_and_fallback_match_original(self):
        probe = original("raw_metadata")
        samples = [
            {"format": {"tags": {"TITLE": "日本語", "ARTIST": "Artist"}, "duration": "12.5"}},
            {"format": {"tags": {"title": "Song - Artist"}, "duration": "N/A"}},
            {"format": {"duration": None}}, {},
        ]
        for data in samples:
            with self.subTest(data=data), patch("subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(data))):
                self.assertEqual(get_raw_metadata("fallback.mp4"), probe("fallback.mp4"))
        with patch("subprocess.run", side_effect=TimeoutError("timeout")), patch("logging.Logger.error"):
            self.assertEqual(get_raw_metadata("fallback.mp4"), probe("fallback.mp4"))

    def test_recursive_scan_new_cached_and_zero_duration_match_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "media"
            folder.mkdir()
            (folder / "nested").mkdir()
            for name in ("new.mp4", "cached.mp3", "retry.wav", "nested/子.MKV", "skip.txt", "unfinished.mp4.part"):
                (folder / name).write_bytes(b"media")
            current = MediaLibrary(root / "cache.json")
            for name, duration in (("cached.mp3", 32), ("retry.wav", 0)):
                file = folder / name
                mid = media_id_for_path(file)
                current.items[mid] = MediaMetadata(mid, str(file), "User title", "User artist", "cache.jpg", duration)
            old = SimpleNamespace(
                items={mid: MediaMetadata(**asdict(meta)) for mid, meta in current.items.items()},
                subtitle_mgr=SimpleNamespace(get_reliable_id=media_id_for_path), save=Mock(),
            )
            metadata = Mock(side_effect=lambda path: (Path(path).stem, "Probe artist", 10.5))
            scan = original("scan", get_raw_metadata=metadata)
            with contextlib.redirect_stdout(io.StringIO()):
                previous = scan(old, str(folder))
            old_calls = list(metadata.call_args_list)
            metadata.reset_mock()
            with patch("app.core.media_library.get_raw_metadata", metadata), contextlib.redirect_stdout(io.StringIO()):
                result = current.scan_folder(str(folder))
            self.assertEqual([asdict(item) for item in result], [asdict(item) for item in previous])
            self.assertEqual(metadata.call_args_list, old_calls)
            self.assertEqual(json.loads(current.db_path.read_text(encoding="utf-8")), {mid: asdict(item) for mid, item in old.items.items()})
