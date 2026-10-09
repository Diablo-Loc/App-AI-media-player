from pathlib import Path as _BaselinePath
import unittest as _BaselineTest
if not (_BaselinePath(__file__).resolve().parents[1] / 'app/bootstrap/application.py').exists():
    raise _BaselineTest.SkipTest('Historical refactor was reverted by the user; see tests/README.md. Current baseline/UI gates: test_ui_refresh.py.')
import unittest
from unittest.mock import Mock

from app.control.subtitle_appearance import DEFAULT_APPEARANCE, SubtitleAppearanceController
from app.subtitle.mode import SubtitleMode


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.layer, self.panel, self.store = Mock(), Mock(), Mock()
        self.config = {"font_size": 28}
        self.presenter = SubtitleAppearanceController(self.layer, self.panel, self.store, self.config)

    def test_font_color_updates_view_and_persistence(self):
        self.presenter.set_font_color("#123456")
        self.layer.apply_style.assert_called_once_with(color="#123456")
        self.assertEqual(self.config["font_color"], "#123456")
        self.store.save_appearance.assert_called_once_with(self.config)

    def test_outline_update_is_saved_as_one_section(self):
        self.presenter.set_outline(True, 3, "#ABCDEF")
        self.assertEqual(self.config["outline_width"], 3)
        self.store.save_appearance.assert_called_once()

    def test_reset_keeps_shared_config_and_synchronizes_view(self):
        identity = id(self.config)
        self.presenter.reset()
        self.assertEqual(id(self.presenter.config), identity)
        self.assertEqual(self.config, DEFAULT_APPEARANCE)
        self.layer.set_mode.assert_called_once_with(SubtitleMode.EN_VI)
        self.panel.sync_ui.assert_called_once_with(self.config)

    def test_lock_and_fade_are_applied_immediately(self):
        self.presenter.set_locked(True)
        self.presenter.set_fade_enabled(False)
        self.layer.set_locked.assert_called_once_with(True)
        self.layer.set_fade_enabled.assert_called_once_with(False)
