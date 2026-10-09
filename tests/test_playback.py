from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
from types import SimpleNamespace
import unittest

from app.playback.playlist import adjacent_item, current_index


class PlaylistTests(unittest.TestCase):
    def setUp(self):
        self.items = [SimpleNamespace(id=str(i)) for i in range(3)]

    def test_repeat_all_at_both_boundaries(self):
        self.assertIs(adjacent_item(self.items, self.items[-1], 1), self.items[0])
        self.assertIs(adjacent_item(self.items, self.items[0], -1), self.items[-1])

    def test_equal_reloaded_media_object_keeps_position(self):
        reloaded = SimpleNamespace(id="1")
        self.assertEqual(current_index(self.items, reloaded), 1)
        self.assertIs(adjacent_item(self.items, reloaded, 1), self.items[2])

    def test_unknown_and_empty_playlist(self):
        self.assertIsNone(adjacent_item([], None, 1))
        self.assertIs(adjacent_item(self.items, SimpleNamespace(id="missing"), -1), self.items[0])

    def test_duplicate_ids_use_exact_metadata_equality_like_original(self):
        first = SimpleNamespace(id="same", title="first")
        second = SimpleNamespace(id="same", title="second")
        self.assertEqual(current_index([first, second], second), 1)
        self.assertIsNone(current_index([first], second))
