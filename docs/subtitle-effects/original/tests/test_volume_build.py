"""Focused playback-volume persistence and packaging configuration checks."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import patch

from tools.ui_preview import isolated_window, pump
from PySide6.QtWidgets import QMessageBox
from control.volume_settings import VolumeSettings
from tests.volume_build_contracts import before_volume_changes
import build_app

ROOT = Path(__file__).resolve().parents[1]


class VolumePersistenceTests(unittest.TestCase):
    def test_first_start_fifty_popup_keyboard_settings_and_coalesced_save(self):
        with isolated_window() as (window, root):
            owner = window._volume_settings
            self.assertAlmostEqual(window.audio_effects.volume(), .5)
            self.assertEqual(window.settings_page.volume_percent.value(), 50)
            self.assertEqual(window.vol_popup.slider.value(), 50)
            self.assertFalse(owner.path.exists())  # No startup overwrite/migration.
            window.update_volume_from_popup(29)
            window.show_volume_popup()
            self.assertEqual(window.vol_popup.slider.value(), 29)  # Avoid 0.29 -> 28 truncation.
            window.vol_popup.hide()
            self.assertEqual(owner.spin.value(), 29)
            window.adjust_volume(.05)
            self.assertEqual(owner.spin.value(), 34)
            owner.spin.setValue(61)
            self.assertAlmostEqual(window.audio_effects.volume(), .61)
            self.assertEqual(window.vol_popup.slider.value(), 61)
            pump(300)
            self.assertEqual(json.loads(owner.path.read_text())['volume_percent'], 61)
            self.assertFalse(owner.dirty)

    def test_new_window_restores_last_level_including_zero_and_hundred(self):
        for percent in (0, 29, 100):
            with isolated_window() as (window, root):
                owner = window._volume_settings
                owner.spin.setValue(percent)
                window.close()  # Flush before the 250-ms timer, including 0%.
                saved = owner.path.read_bytes()
            def restore(window):
                path = Path(window.audio_effects.settings_path).with_name('playback-volume.json')
                path.write_bytes(saved)
                return VolumeSettings(window)
            with patch('ui.main_window.install_volume_settings', side_effect=restore):
                with isolated_window() as (window, root):
                    self.assertAlmostEqual(window.audio_effects.volume(), percent / 100)
                    self.assertEqual(window.settings_page.volume_percent.value(), percent)
                    self.assertEqual(window.vol_popup.slider.value(), percent)

    def test_gain_ramp_mute_and_device_refresh_do_not_save_effective_volume(self):
        with isolated_window() as (window, root):
            owner, controller = window._volume_settings, window.audio_effects
            player = window.media_player.player
            source, output, video, state = player.source(), player.audioOutput(), player.videoOutput(), player.playbackState()
            controller.set_volume(.73)
            owner.flush()
            saved = owner.path.read_bytes()
            controller.volume_control.set_gain(-6, True)
            pump(200)
            self.assertLess(window.audio_output.volume(), .4)
            window.audio_output.setMuted(True)
            window.media_player.refresh_audio_output()
            pump(200)
            self.assertAlmostEqual(controller.volume(), .73)
            self.assertEqual(owner.spin.value(), 73)
            self.assertEqual(owner.path.read_bytes(), saved)
            self.assertFalse(owner.dirty)
            self.assertEqual(player.source(), source)
            self.assertEqual(player.playbackState(), state)
            self.assertIs(player.audioOutput(), output)
            self.assertIs(player.videoOutput(), video)

    def test_invalid_settings_default_and_read_only_failure_retry(self):
        with isolated_window() as (window, root):
            owner = window._volume_settings
            for value in (True, '80', None, -1, 101, float('nan'), 10**1000):
                owner.path.write_text(json.dumps({'volume_percent': value}), encoding='utf-8')
                self.assertEqual(owner._load(), 50)
            owner.path.write_text('bad JSON', encoding='utf-8')
            self.assertEqual(owner._load(), 50)
            owner.spin.setValue(42)
            with patch('control.volume_settings.atomic_bytes', side_effect=PermissionError('read only')):
                owner.flush()
            self.assertTrue(owner.dirty)
            self.assertIn('Không lưu được', owner.hint.text())
            owner.flush()
            self.assertEqual(json.loads(owner.path.read_text())['volume_percent'], 42)
            self.assertFalse(owner.dirty)

    def test_settings_reset_confirmed_restores_fifty_without_changing_audio_profile(self):
        with isolated_window() as (window, root):
            owner = window._volume_settings
            owner.spin.setValue(80)
            profile = window.audio_effects.profile
            with patch('ui.pages.settings.QMessageBox.question', return_value=QMessageBox.No):
                window.settings_page.reset_to_defaults()
            self.assertEqual(owner.spin.value(), 80)
            with patch('ui.pages.settings.QMessageBox.question', return_value=QMessageBox.Yes), \
                 patch('ui.pages.settings.QMessageBox.information'):
                window.settings_page.reset_to_defaults()
            owner.flush()
            self.assertEqual(owner.spin.value(), 50)
            self.assertEqual(window.audio_effects.profile, profile)
            self.assertEqual(json.loads(owner.path.read_text())['volume_percent'], 50)


class BuildConfigurationTests(unittest.TestCase):
    def test_build_handoff_uses_project_directory_and_restores_callers_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app').mkdir()
            plan = build_app.build_plan(root, stamp='handoff')
            previous = Path.cwd()
            package = types.ModuleType('PyInstaller')
            package.__path__ = []
            main_module = types.ModuleType('PyInstaller.__main__')
            package.__main__ = main_module
            calls = []
            def fake_compiler(params):
                calls.append(params)
                self.assertEqual(Path.cwd(), root)
                output = Path(plan['output'])
                output.mkdir(parents=True)
                (output / 'BoTube.exe').write_bytes(b'fixture, not a real exe')
            main_module.run = fake_compiler
            with patch.dict(sys.modules, {'PyInstaller': package, 'PyInstaller.__main__': main_module}), \
                 patch('build_app.build_plan', return_value=plan), patch('build_app.validate_sources'), \
                 patch('build_app.importlib.metadata.version', return_value='fixture'):
                build_app.main([])
            self.assertEqual(Path.cwd(), previous)
            self.assertEqual(calls, [plan['params']])
            self.assertTrue((Path(plan['output']) / 'app_resources/libs').is_dir())

    def test_existing_portable_and_build_outputs_remain_and_hidden_imports_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saved = root / 'dist/BoTube/storage/data.json'
            saved.parent.mkdir(parents=True)
            saved.write_text('keep me')
            plan = build_app.build_plan(root, stamp='test')
            self.assertEqual(plan['output'], str(root / 'dist/release-test/BoTube'))
            self.assertEqual(saved.read_text(), 'keep me')
            self.assertFalse((root / 'build').exists())
            self.assertIn('--paths=' + str(root / 'app'), plan['params'])
            self.assertIn('--hidden-import=PySide6.QtMultimedia', plan['params'])
            self.assertIn('--hidden-import=PySide6.QtSvg', plan['params'])
            old = ast.parse((ROOT / 'docs/volume-build/original/build_app.py').read_bytes())
            old_hidden = {n.value.split('=', 1)[1] for n in ast.walk(old) if isinstance(n, ast.Constant)
                          and isinstance(n.value, str) and n.value.startswith('--hidden-import=')}
            self.assertTrue(old_hidden <= set(build_app.HIDDEN_IMPORTS))
            with self.assertRaises(ValueError):
                build_app.build_plan(root, dist_dir=root / 'dist', stamp='test')

    def test_real_assets_valid_and_copy_keeps_runtime_empty_user_data_out(self):
        build_app.validate_sources(build_app.build_plan())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for file in ('icon/app.ico', 'bin/ffmpeg.exe', 'app/download_core/yt-dlp.exe',
                         'storage/private.json', 'app_resources/libs/model.bin'):
                path = root / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            plan = build_app.build_plan(root, stamp='test')
            output = Path(plan['output'])
            output.mkdir(parents=True)
            (output / 'BoTube.exe').write_bytes(b'build fixture')
            build_app.copy_portable_resources(plan)
            self.assertTrue((output / 'bin/ffmpeg.exe').exists())
            self.assertTrue((output / 'yt-dlp.exe').exists())
            self.assertEqual(list((output / 'app_resources/libs').iterdir()), [])
            self.assertFalse((output / 'storage').exists())


class VolumeSourceScopeTests(unittest.TestCase):
    def test_only_approved_main_settings_adapters_and_helper_changed(self):
        manifest = json.loads((ROOT / 'docs/volume-build/reviewed-sources.json').read_text())
        for relative, changed in (
            ('app/ui/main_window.py', ['MainWindow.__init__', 'MainWindow.closeEvent',
                                      'MainWindow.show_volume_popup', 'MainWindow.adjust_volume']),
            ('app/ui/pages/settings.py', ['SettingsPage.reset_to_defaults'])):
            self.assertEqual(manifest[relative]['changed_functions'], changed)
            before = ast.parse(before_volume_changes(relative))
            after = ast.parse((ROOT / relative).read_bytes())
            old_classes = {n.name: n for n in before.body if isinstance(n, ast.ClassDef)}
            for cls in [n for n in after.body if isinstance(n, ast.ClassDef)]:
                old_methods = {n.name: n for n in old_classes[cls.name].body if isinstance(n, ast.FunctionDef)}
                cls.body = [old_methods[n.name] if isinstance(n, ast.FunctionDef) and f'{cls.name}.{n.name}' in changed else n for n in cls.body]
            if relative.endswith('main_window.py'):
                after.body = [n for n in after.body if not (isinstance(n, ast.ImportFrom) and n.module == 'control.volume_settings')]
            self.assertEqual(ast.dump(before), ast.dump(after))
        self.assertEqual(manifest['tests/test_media_info.py']['changed_functions'],
            ['MetadataScopeTests.test_exact_three_source_adapters_and_no_other_ast_changes'])
        helper = json.loads((ROOT / 'docs/volume-build/helper-hash.json').read_text())
        for relative, sha in helper.items():
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), sha)


if __name__ == '__main__':
    unittest.main()
