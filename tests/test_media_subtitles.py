from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.core.media_library import MediaLibrary
from app.core.subtitle_manager import SubtitleManager
from app.media.identity import media_id_for_path
from app.media.models import MediaMetadata
from app.subtitle.model import Subtitle, SubtitleLine


class MediaSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.media = self.root / "song.mp4"
        self.media.write_bytes(b"test media")
        self.manager = SubtitleManager(self.root / "storage")
        self.media_id = media_id_for_path(self.media)

    def test_media_ids_match_existing_hash_and_subtitle_manager(self):
        previous = hashlib.md5(f"{str(self.media.resolve()).lower()}_{self.media.stat().st_size}".encode()).hexdigest()
        self.assertEqual(self.media_id, previous)
        self.assertEqual(self.manager.get_reliable_id({"path": str(self.media)}), previous)
        self.assertIsNone(media_id_for_path(self.root))

    def test_object_subtitle_round_trip_preserves_all_languages(self):
        segment = Subtitle(1.0, 2.0, SubtitleLine("日本語", "ja", "JP"), SubtitleLine("English", "en", "EN"), SubtitleLine("Tiếng Việt", "vi", "VI"))
        result = self.manager.save_segments(self.media_id, [segment], str(self.media))
        self.assertIsNotNone(result)
        saved = self.manager.get_raw_data(self.media_id)
        self.assertEqual(saved["original_name"], "song")
        self.assertEqual(saved["segments"][0], {"start": 0.9, "end": 2.1, "jp": "日本語", "en": "English", "vi": "Tiếng Việt"})
        self.assertEqual(self.manager.get_segments_for_ui(self.media_id)[0]["start"], 900)

    def test_dict_subtitle_round_trip_does_not_pad_again_or_lose_text(self):
        segment = {"start": 0.9, "end": 2.1, "jp": "日本語", "en": "English", "vi": "Tiếng Việt"}
        self.manager.save_segments(self.media_id, [segment])
        self.manager.save_segments(self.media_id, self.manager.get_raw_data(self.media_id)["segments"])
        self.assertEqual(self.manager.get_raw_data(self.media_id)["segments"], [segment])

    def test_failed_source_write_does_not_render_or_report_success(self):
        with patch("app.core.subtitle_manager.write_json_atomic", side_effect=OSError("disk full")), patch("app.core.subtitle_renderer.ASSRenderer.generate") as render:
            with self.assertLogs("app.core.subtitle_manager", level="ERROR"):
                self.assertIsNone(self.manager.save_segments(self.media_id, [{"start": 0, "end": 1, "jp": "hello"}]))
            render.assert_not_called()

    def test_library_cache_uses_shared_model_and_explicit_database(self):
        library = MediaLibrary(self.root / "library.json")
        library.items[self.media_id] = MediaMetadata(self.media_id, str(self.media), "song")
        library.save()
        restored = MediaLibrary(library.db_path)
        self.assertEqual(restored.items[self.media_id].title, "song")
        self.assertFalse(hasattr(library, "subtitle_mgr"))

    def test_default_storage_does_not_follow_working_directory(self):
        old_cwd = Path.cwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(self.root)
        with patch("app.core.media_library.storage_dir", return_value=self.root / "portable"), patch("app.core.subtitle_manager.storage_dir", return_value=self.root / "portable"):
            self.assertEqual(MediaLibrary().db_path, self.root / "portable" / "library_cache.json")
            self.assertEqual(SubtitleManager().root, self.root / "portable")
