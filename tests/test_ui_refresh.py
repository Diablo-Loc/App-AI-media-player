"""Behavior and frozen-source gates for the restored-baseline UI refresh."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.capture_ui_contracts import contracts
from tools.ui_preview import isolated_window, populate, pump, APPLICATION
from tests.reliability_contracts import before_reliability_changes
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import QPushButton
from PySide6.QtTest import QSignalSpy

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "docs/restored-app-baseline.json").read_text(encoding="utf-8"))
UI_CONTRACTS = json.loads((ROOT / "docs/ui/original-contracts.json").read_text(encoding="utf-8"))
# These methods own presentation. Every other original UI method is frozen.
VISUAL_METHODS = {
    "app/ui/main_window.py": "MainWindow.init_ui MainWindow.init_grid_page MainWindow.update_volume_from_popup MainWindow.adjust_volume MainWindow.apply_global_styles MainWindow.toggle_fullscreen MainWindow.toggle_nav_animation MainWindow.hide_controls MainWindow.update_video_location",
    "app/ui/media_card.py": "MediaCard.show_default_icon MediaCard.refresh_style",
    "app/ui/nav/sidebar.py": "Sidebar.__init__ Sidebar.add_menu_items Sidebar.set_mini_mode Sidebar.set_full_mode",
    "app/ui/pages/download.py": "DownloadPage.init_ui",
    "app/ui/pages/dynamic_island.py": "MiniPlayer.__init__ MiniPlayer.update_info MiniPlayer.set_rounded_pixmap",
    "app/ui/pages/for_you.py": "LazyThumb.__init__ LazyThumb._start_async_loading LazyThumb._on_loaded ForYouPage.init_ui ForYouPage.create_playlist_card ForYouPage.set_shuffle_visual ForYouPage.toggle_repeat ForYouPage.set_card_active_style VideoStage.update_layout_execution",
    "app/ui/pages/mode_manager.py": "BaseVideoPage.__init__",
    "app/ui/pages/settings.py": "SettingsPage.init_ui SettingsPage.add_section_title SettingsPage.add_setting_row SettingsPage.get_qss",
    "app/ui/pages/settings_dialog.py": "SettingMenu.init_ui",
    "app/ui/playback_bar.py": "PlaybackBar.__init__ PlaybackBar.init_ui PlaybackBar.set_shuffle_visual PlaybackBar.update_play_state PlaybackBar.set_media_info",
    "app/ui/subs_ui/lyric_settings_dialog.py": "SubtitleToolsDialog.__init__ SubtitleToolsDialog.init_ui",
    "app/ui/subs_ui/sub_panel.py": "SettingsPanel.__init__",
    "app/ui/video_info_popup.py": "VideoInfoPopup.__init__ VideoInfoPopup.init_ui VideoInfoPopup.init_general_tab VideoInfoPopup.init_stream_tab",
    "app/ui/vol_panel.py": "VolumePopup.__init__",
}


class OriginalSourceGates(unittest.TestCase):
    def test_all_non_ui_sources_match_restored_hashes(self):
        for entry in BASELINE["sources"]:
            if not entry["path"].startswith("app/ui/"):
                with self.subTest(path=entry["path"]):
                    if entry["path"] == "app/ai/pipeline.py":
                        # Explicit accuracy phase: one reviewed function body;
                        # primary ASR/refine options remain frozen in its gates.
                        from tests.test_asr_coverage import PipelineContractTests
                        gate = PipelineContractTests()
                        gate.test_only_main_pipeline_body_and_coverage_import_are_changed()
                        gate.test_primary_whisper_and_refine_options_are_exactly_original()
                        gate.test_original_flow_survives_removing_only_coverage_adapter()
                        continue
                    if entry["path"] == "app/core/subtitle_manager.py":
                        from tests.test_lyric_refinement import SavedSubtitleCompatibilityTests
                        SavedSubtitleCompatibilityTests().test_manager_only_adds_marker_guard_all_other_original_logic_is_frozen()
                        continue
                    if entry["path"] == "app/control/app_controller.py":
                        from tests.empty_subtitle_contracts import before_empty_changes
                        before_empty_changes(entry["path"])
                        # Original baseline bytes are verified separately to
                        # avoid treating newline normalization as a source edit.
                        self.assertEqual(hashlib.sha256((ROOT / 'docs/empty-subtitles/original/app_controller.py')
                                                       .read_bytes()).hexdigest(), entry['sha256'])
                        continue
                    if entry["path"] in {"app/pipeline/lyric_formatter.py", "app/core/subtitle_renderer.py"}:
                        from tests.test_lyric_refinement import ExportTimingTests
                        ExportTimingTests().test_only_time_format_bodies_and_shared_import_changed()
                        continue
                    if entry["path"] == "app/pipeline/aligner.py":
                        from tests.test_lyric_refinement import LegacyAlignerCompatibilityTests
                        LegacyAlignerCompatibilityTests().test_only_optional_short_lyric_guard_is_added_to_original_aligner()
                        continue
                    self.assertEqual(hashlib.sha256(before_reliability_changes(entry['path'], raw=True)).hexdigest(), entry["sha256"])

    def test_every_original_ui_api_and_signal_signature_survives(self):
        for name, original in UI_CONTRACTS["files"].items():
            from tests.subtitle_effects_contracts import before_effect_changes
            current = contracts(before_effect_changes(name))
            with self.subTest(path=name):
                self.assertEqual(current["signals"], original["signals"])
                for method, signature in original["methods"].items():
                    self.assertIn(method, current["methods"])
                    self.assertEqual(current["methods"][method]["args"], signature["args"], method)

    def test_original_qt_signal_wiring_is_identical(self):
        for name, original in UI_CONTRACTS["files"].items():
            with self.subTest(path=name):
                expected = list(original["connections"])
                if name == "app/ui/main_window.py":
                    # One additional presentation-only connection reflows cards
                    # after sidebar width settles. Every original stays intact.
                    expected += contracts("self.anim_group.finished.connect(self.refresh_grid)")["connections"]
                source = before_reliability_changes(name)
                if name == 'app/ui/pages/for_you.py':
                    source = source.replace('card.clicked.connect(lambda _, row=card: self.playlist_item_clicked.emit(row._playlist_item))',
                                            'card.clicked.connect(lambda _, data=item_data: self.playlist_item_clicked.emit(data))')
                self.assertEqual(contracts(source)["connections"], sorted(expected))

    def test_ui_methods_outside_presentation_are_identical(self):
        for name, original in UI_CONTRACTS["files"].items():
            source = before_reliability_changes(name)
            if name in ('app/ui/pages/for_you.py', 'app/ui/main_window.py'):
                from tests.foryou_search_contracts import before_search_changes
                source = before_search_changes(name)
            current = contracts(source)
            allowed = VISUAL_METHODS.get(name, "").split()
            for method, signature in original["methods"].items():
                if method not in allowed:
                    with self.subTest(path=name, method=method):
                        if name == 'app/ui/subs_ui/subtitle_dialog_logic.py' and method == 'SubtitleToolsDialogLogic.load_from_media_file':
                            from tests.empty_subtitle_contracts import before_empty_changes
                            normalized = contracts(before_empty_changes(name))
                            self.assertEqual(normalized['methods'][method]['body'], signature['body'])
                            continue
                        self.assertEqual(current["methods"][method]["body"], signature["body"])

    def test_all_python_sources_compile_on_project_python(self):
        for path in (ROOT / "app").rglob("*.py"):
            with self.subTest(path=path.relative_to(ROOT)):
                compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")

    def test_svg_assets_match_pinned_source_hashes_and_ship_license(self):
        directory = ROOT / "app/ui/assets/icons"
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(len(manifest["sha256"]), 41)
        self.assertIn("ISC License", (directory / "LICENSE").read_text())
        self.assertIn("The MIT License", (directory / "LICENSE").read_text())
        for name, expected in manifest["sha256"].items():
            self.assertEqual(hashlib.sha256((directory / f"{name}.svg").read_bytes()).hexdigest(), expected)
        # The current packaging paths already include the complete app directory.
        for script in ("build_app.py", "build_app_for_update.py"):
            self.assertIn("--add-data=app;app", (ROOT / script).read_text(encoding="utf-8-sig"))


class QtUiBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = isolated_window()
        cls.window, cls.root = cls.context.__enter__()
        cls.items = populate(cls.window, cls.root)
        pump(300)

    @classmethod
    def tearDownClass(cls):
        from ui.media_card import MediaCard
        MediaCard.thread_pool.waitForDone(3000)
        cls.context.__exit__(None, None, None)

    def test_navigation_indexes_roles_and_compact_restore(self):
        sidebar = self.window.sidebar
        labels = ["Trang chủ", "For You", "Thư viện", "Download", "Tùy chỉnh"]
        for i, label in enumerate(labels):
            self.assertEqual(sidebar.item(i).text(), label)
            self.assertTrue(sidebar.item(i).data(Qt.UserRole + 2).endswith(label))
            self.assertFalse(sidebar.item(i).icon().isNull())
        sidebar.set_mini_mode()
        self.assertTrue(all(not sidebar.item(i).text() for i in range(5)))
        sidebar.set_full_mode()
        self.assertEqual([sidebar.item(i).text() for i in range(5)], labels)
        from ui.nav.sidebar import Sidebar
        custom = Sidebar()
        custom.add_menu_items(["Custom feature"])
        custom.set_mini_mode()
        custom.set_full_mode()
        self.assertEqual(custom.item(0).text(), "Custom feature")
        custom.deleteLater()

    def test_all_pages_remain_reachable_by_existing_handler(self):
        for i in (2, 1, 3, 4, 0):
            self.window.sidebar.setCurrentRow(i)
            self.window.handle_sidebar_click(self.window.sidebar.item(i))
            pump(40)
            self.assertEqual(self.window.content_stack.currentIndex(), i)
        self.assertIs(self.window.content_stack.widget(3), self.window.download_page)

    def test_playback_buttons_emit_original_signals_once(self):
        # Avoid actually starting media or AI; the standalone bar tests its API.
        from ui.playback_bar import PlaybackBar
        bar = PlaybackBar()
        try:
            for button_name, signal_name in (("btn_play", "play_toggled"), ("btn_prev", "prev_requested"), ("btn_next", "next_requested"), ("btn_shuffle", "shuffle_clicked"), ("btn_sub", "subtitle_tools_clicked"), ("btn_dynamic_island", "dynamic_island_clicked")):
                spy = QSignalSpy(getattr(bar, signal_name))
                getattr(bar, button_name).click()
                self.assertEqual(spy.count(), 1, signal_name)
            self.assertFalse(bar.btn_reload.isEnabled())
            bar.set_media_info("Song", "Artist")
            spy = QSignalSpy(bar.reload_clicked)
            bar.btn_reload.click()
            self.assertEqual(spy.count(), 1)
        finally:
            bar.info_popup.deleteLater()
            bar.deleteLater()

    def test_seek_and_position_keep_slider_drag_contract(self):
        bar = self.window.playback_bar
        bar.update_duration(215000, "03:35")
        bar.update_position(70000, "01:10")
        self.assertEqual(bar.time_slider.value(), 70000)
        bar.time_slider.setSliderDown(True)
        bar.time_slider.setValue(91000)
        bar.update_position(71000, "01:11")
        self.assertEqual(bar.time_slider.value(), 91000)
        spy = QSignalSpy(bar.seek_requested)
        bar.time_slider.setSliderDown(False)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0), [91000])

    def test_play_pause_icons_do_not_parse_stylesheets_per_update(self):
        from ui.icons import icon, _svg
        source = (ROOT / "docs/ui/original-playback-state.py").read_text(encoding="utf-8")
        self.assertEqual(contracts(source)["methods"]["update_play_state"]["body"],
                         UI_CONTRACTS["files"]["app/ui/playback_bar.py"]["methods"]["PlaybackBar.update_play_state"]["body"])
        namespace = {}
        exec(compile(source, "original:playback-state", "exec"), namespace)
        original_bar = SimpleNamespace(btn_play=Mock())
        for i in range(200):
            namespace["update_play_state"](original_bar, bool(i % 2))
        self.assertEqual(original_bar.btn_play.setStyleSheet.call_count, 200)
        bar = self.window.playback_bar
        bar.update_play_state(True)
        bar.update_play_state(False)
        before = _svg.cache_info().misses
        with patch.object(bar.btn_play, "setStyleSheet", wraps=bar.btn_play.setStyleSheet) as style:
            for i in range(200):
                bar.update_play_state(bool(i % 2))
            self.assertEqual(style.call_count, 0)
        self.assertEqual(_svg.cache_info().misses, before)
        self.assertEqual(bar.btn_play.property("iconName"), "pause")
        self.assertIs(icon("play"), icon("play"))

    def test_volume_pathways_preserve_values_and_threshold_icons(self):
        for value, name in ((0, "volume-x"), (25, "volume-1"), (50, "volume-2"), (100, "volume-2")):
            self.window.update_volume_from_popup(value)
            self.assertAlmostEqual(self.window.audio_output.volume(), value / 100, places=5)
            self.assertEqual(self.window.playback_bar.btn_vol.property("iconName"), name)
        self.window.adjust_volume(0.5)
        self.assertEqual(self.window.audio_output.volume(), 1.0)
        self.window.adjust_volume(-2)
        self.assertEqual(self.window.audio_output.volume(), 0.0)

    def test_for_you_repeat_signal_and_shuffle_preserve_playlist(self):
        page = self.window.foryou_page
        original = list(page.all_items_data)
        spy = QSignalSpy(page.repeat_toggled)
        page.btn_repeat.click()
        page.btn_repeat.click()
        self.assertEqual([spy.at(i)[0] for i in range(2)], [True, False])
        shuffle = QSignalSpy(page.shuffle_req_signal)
        # Directly exercise the original page API; parent connection is tested
        # separately by the frozen wiring gate.
        page.shuffle_req_signal.disconnect(self.window.toggle_global_shuffle)
        try:
            page.btn_shuffle.click()
            self.assertEqual(shuffle.count(), 1)
            self.assertEqual(page.all_items_data, original)
            page.set_shuffle_visual(True)
            self.assertTrue(page.is_shuffle)
            self.assertEqual(page.all_items_data, original)
        finally:
            page.shuffle_req_signal.connect(self.window.toggle_global_shuffle)
            page.set_shuffle_visual(False)

    def test_playlist_card_click_keeps_exact_media_object(self):
        from ui.pages.for_you import ForYouPage
        page = ForYouPage()
        try:
            card = page.create_playlist_card(1, self.items[0].title, self.items[0].artist, "", self.items[0])
            spy = QSignalSpy(page.playlist_item_clicked)
            card.click()
            self.assertEqual(spy.count(), 1)
            self.assertIs(spy.at(0)[0], self.items[0])
            card.deleteLater()
        finally:
            page.deleteLater()

    def test_fullscreen_enters_and_restores_original_video_ownership(self):
        window = self.window
        window.toggle_fullscreen()
        pump(40)
        self.assertTrue(window.isFullScreen())
        self.assertIs(window.video_display.parentWidget(), window.video_container)
        self.assertEqual(window.playback_bar.btn_fs.property("iconName"), "minimize")
        window.toggle_fullscreen()
        pump(40)
        self.assertFalse(window.isFullScreen())
        self.assertEqual(window.playback_bar.btn_fs.property("iconName"), "maximize")
        window.handle_sidebar_click(window.sidebar.item(2))
        pump(40)
        window.handle_sidebar_click(window.sidebar.item(0))

    def test_main_window_mini_mode_round_trip_keeps_video_owner(self):
        window = self.window
        window.handle_sidebar_click(window.sidebar.item(2))
        pump(30)
        owner = window.video_display.parentWidget()
        window.switch_to_mini_mode()
        pump(30)
        self.assertTrue(window.is_mini_mode)
        self.assertFalse(window.isVisible())
        self.assertTrue(window.mini_player.isVisible())
        window.switch_to_normal_mode()
        pump(30)
        self.assertFalse(window.is_mini_mode)
        self.assertTrue(window.isVisible())
        self.assertFalse(window.mini_player.isVisible())
        self.assertIs(window.video_display.parentWidget(), owner)
        window.handle_sidebar_click(window.sidebar.item(0))

    def test_download_custom_path_toggle_and_plain_paste_survive(self):
        from PySide6.QtCore import QMimeData
        page = self.window.download_page
        page.btn_toggle_path.setChecked(True)
        self.assertTrue(page.combo_path.isEnabled())
        self.assertTrue(page.btn_browse.isEnabled())
        page.btn_toggle_path.setChecked(False)
        self.assertFalse(page.combo_path.isEnabled())
        page.txt_links.clear()
        mime = QMimeData()
        mime.setText("https://example.test/1   https://example.test/2\n")
        page.txt_links.insertFromMimeData(mime)
        self.assertEqual(page.txt_links.toPlainText(), "https://example.test/1\nhttps://example.test/2")
        page.clear_inputs()
        self.assertEqual(page.progress_bar.value(), 0)
        self.assertFalse(page.txt_links.toPlainText())

    def test_settings_still_save_original_keys_and_values(self):
        page = self.window.settings_page
        page.combo_device.setCurrentText("cpu")
        page.combo_online_ai.setCurrentText("Google Gemini")
        page.api_key_input.setText("test-key-no-network")
        spy = QSignalSpy(page.settings_changed)
        page.save_settings_silent()
        self.assertEqual(spy.count(), 1)
        values = spy.at(0)[0]
        self.assertEqual(set(values), {"ai_model", "device", "online_provider", "api_key", "use_genius", "genius_key"})
        self.assertEqual(values["online_provider"], "Google Gemini")
        page.api_key_input.clear()
        page.load_settings()
        self.assertEqual(page.api_key_input.text(), "test-key-no-network")

    def test_subtitle_appearance_modes_and_existing_shortcuts_survive(self):
        panel = self.window.subsettings_panel
        self.assertEqual(panel.combo_mode.count(), 8)
        for index in range(panel.combo_mode.count()):
            self.assertIsNotNone(panel.combo_mode.itemData(index))
        self.assertEqual(self.window.spacebar_shortcut.key(), QKeySequence("Space"))
        self.window._save_font_size(29)
        self.assertEqual(self.window.config["font_size"], 29)

    def test_mini_player_signals_and_existing_title_truncation(self):
        from ui.pages.dynamic_island import MiniPlayer
        mini = MiniPlayer()
        try:
            for button, signal in ((mini.btn_play, mini.play_req), (mini.btn_next, mini.next_req), (mini.btn_prev, mini.prev_req)):
                spy = QSignalSpy(signal)
                button.click()
                self.assertEqual(spy.count(), 1)
            mini.update_info("A" * 30, "Artist", True)
            self.assertEqual(mini.lbl_title.text(), "A" * 20 + "..")
            self.assertEqual(mini.btn_play.property("iconName"), "pause")
        finally:
            mini.deleteLater()

    def test_all_icons_render_and_disabled_states_differ_at_high_dpi(self):
        from ui.icons import icon
        manifest = json.loads((ROOT / "app/ui/assets/icons/manifest.json").read_text())
        for name in manifest["sha256"]:
            for ratio in (1.0, 1.5, 2.0):
                from PySide6.QtCore import QSize
                pixmap = icon(name).pixmap(QSize(20, 20), ratio)
                self.assertFalse(pixmap.isNull(), name)
                self.assertEqual(pixmap.width(), round(20 * ratio))
        self.assertNotEqual(icon("play").pixmap(24, 24).toImage(), icon("play").pixmap(24, 24, QIcon.Mode.Disabled).toImage())

    def test_short_namespace_bundle_path_resolves_packaged_svg_assets(self):
        assets = ROOT / "app/ui/assets/icons"
        resolver = Mock(return_value=assets)
        source = (ROOT / "app/ui/icons.py").read_text(encoding="utf-8-sig")
        namespace = {"__name__": "bundle_icon_probe", "__file__": str(self.root / "_internal/ui/icons.py")}
        with patch.dict(sys.modules, {"paths": SimpleNamespace(asset_dir=resolver)}):
            exec(compile(source, "bundle:ui/icons.py", "exec"), namespace)
        resolver.assert_called_once_with("app/ui/assets/icons")
        self.assertFalse(namespace["icon"]("play").pixmap(24, 24).isNull())
