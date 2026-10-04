from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.core.media_library import MediaLibrary
from app.media.models import MediaMetadata
from app.thumbnail.persistence import ThumbnailPersistenceBatch


class ThumbnailPersistenceTests(unittest.TestCase):
    def test_batch_has_same_final_json_with_ten_writes_instead_of_120(self):
        with tempfile.TemporaryDirectory() as directory:
            library = MediaLibrary(Path(directory) / "library.json")
            library.items = {str(i): MediaMetadata(str(i), f"{i}.mp4", f"Song {i}") for i in range(120)}
            batch = ThumbnailPersistenceBatch(library)
            with patch.object(library, "save", wraps=library.save) as save:
                for mid in library.items:
                    batch.record(mid, f"{mid}.jpg")
                batch.flush()
                self.assertEqual(save.call_count, 10)
            self.assertEqual(json.loads(library.db_path.read_text(encoding="utf-8")), {mid: asdict(meta) for mid, meta in library.items.items()})

    def test_partial_batch_is_visible_immediately_and_flushes_once(self):
        library = Mock()
        batch = ThumbnailPersistenceBatch(library)
        batch.record("media", "thumb.jpg")
        library.update_thumbnail_in_db.assert_called_once_with("media", "thumb.jpg", persist=False)
        library.save.assert_not_called()
        batch.flush()
        batch.flush()
        library.save.assert_called_once()

    def test_default_update_still_persists_for_legacy_callers(self):
        with tempfile.TemporaryDirectory() as directory:
            library = MediaLibrary(Path(directory) / "library.json")
            library.items["id"] = MediaMetadata("id", "song.mp4", "Song")
            library.update_thumbnail_in_db("id", "thumb.jpg")
            self.assertEqual(json.loads(library.db_path.read_text(encoding="utf-8"))["id"]["thumbnail"], "thumb.jpg")
