"""Comprehensive tests for BoTube GitHub Releases + Inno Setup auto-updater."""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QSettings

from ui.main_window import MainWindow  # noqa: F401 - keep Shiboken wrappers resident
from core.app_updater import (
    ReleaseInfo,
    build_inno_setup_params,
    cleanup_stale_installers,
    download_installer_atomic,
    is_allowed_https_url,
    is_newer_version,
    launch_inno_installer,
    normalize_version_str,
    parse_github_release,
    parse_sha256_from_checksum_text,
    parse_version,
    select_installer_asset,
)
from tests.test_ui_settings_and_i18n import _collect_leftover_vietnamese
from tools.ui_preview import isolated_window, pump
from ui.i18n import set_language
from ui.update_dialog import AppUpdateController, UpdateDialog
from version import APP_ID, APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


class _FakeHTTPResponse:
    def __init__(self, payload: bytes, *, url: str, content_length: int | None = None):
        self._buf = io.BytesIO(payload)
        self._url = url
        self.headers = {}
        if content_length is not None:
            self.headers['Content-Length'] = str(content_length)

    def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class AppUpdaterCoreTests(unittest.TestCase):
    def test_semver_parsing_and_comparison(self):
        self.assertEqual(normalize_version_str('v6.0.0'), '6.0.0')
        self.assertEqual(normalize_version_str('V6.1.0-beta.1'), '6.1.0-beta.1')
        self.assertEqual(parse_version('v6.0.0'), parse_version('6.0'))
        self.assertTrue(is_newer_version('6.0.0', '5.0.0'))
        self.assertTrue(is_newer_version('6.1.0', '6.0.0'))
        self.assertTrue(is_newer_version('6.10.0', '6.2.0'))
        self.assertTrue(is_newer_version('v6.0.0', '6.0.0-beta.2'))
        self.assertTrue(is_newer_version('6.0.0-beta.2', '6.0.0-beta.1'))
        self.assertFalse(is_newer_version('v6.0.0', '6.0.0'))
        self.assertFalse(is_newer_version('5.9.9', '6.0.0'))
        self.assertFalse(is_newer_version('', '6.0.0'))

    def test_https_host_allowlist(self):
        self.assertTrue(is_allowed_https_url('https://api.github.com/repos/Diablo-Loc/App-AI-media-player/releases/latest'))
        self.assertTrue(is_allowed_https_url('https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v5.2.0/BoTube_Setup.exe'))
        self.assertTrue(is_allowed_https_url('https://objects.githubusercontent.com/github-production-release-asset/123'))
        self.assertFalse(is_allowed_https_url('http://github.com/Diablo-Loc/App-AI-media-player/releases/latest'))
        self.assertFalse(is_allowed_https_url('https://evil-github.com/BoTube_Setup.exe'))
        self.assertFalse(is_allowed_https_url('https://github.com.evil.org/BoTube_Setup.exe'))
        self.assertFalse(is_allowed_https_url('file:///C:/Temp/BoTube_Setup.exe'))

    def test_parse_github_release_and_asset_priority(self):
        sha = 'a' * 64
        payload = {
            'tag_name': 'v5.2.0',
            'name': 'BoTube v5.2.0',
            'body': '### Highlights\n- Faster startup\n- Commercial auto-updater',
            'html_url': 'https://github.com/Diablo-Loc/App-AI-media-player/releases/tag/v5.2.0',
            'published_at': '2026-11-28T10:00:00Z',
            'draft': False,
            'prerelease': False,
            'assets': [
                {
                    'name': 'BoTube_Portable.zip',
                    'size': 200_000_000,
                    'browser_download_url': 'https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v5.2.0/BoTube_Portable.zip',
                },
                {
                    'name': 'helper_tool.exe',
                    'size': 500_000,
                    'browser_download_url': 'https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v5.2.0/helper_tool.exe',
                },
                {
                    'name': 'BoTube_Setup.exe',
                    'size': 152_000_000,
                    'digest': f'sha256:{sha}',
                    'browser_download_url': 'https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v5.2.0/BoTube_Setup.exe',
                },
                {
                    'name': 'BoTube_Setup.exe.sha256',
                    'size': 90,
                    'browser_download_url': 'https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v5.2.0/BoTube_Setup.exe.sha256',
                },
            ],
        }
        info = parse_github_release(payload)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.version, '5.2.0')
        self.assertEqual(info.asset_name, 'BoTube_Setup.exe')
        self.assertEqual(info.sha256, sha)
        self.assertTrue(info.checksum_url.endswith('BoTube_Setup.exe.sha256'))

        # Drafts and prereleases are excluded by default
        self.assertIsNone(parse_github_release({**payload, 'draft': True}))
        self.assertIsNone(parse_github_release({**payload, 'prerelease': True}))
        self.assertIsNotNone(parse_github_release({**payload, 'prerelease': True}, include_prerelease=True))

        # Untrusted asset hosts are ignored
        chosen, _ = select_installer_asset(
            [{'name': 'BoTube_Setup.exe', 'browser_download_url': 'https://evil.example/BoTube_Setup.exe'}]
        )
        self.assertIsNone(chosen)

    def test_checksum_text_parsing(self):
        h1 = '1' * 64
        h2 = '2' * 64
        txt = f'# comment\n{h1}  other.zip\n{h2}  *BoTube_Setup.exe\n'
        self.assertEqual(parse_sha256_from_checksum_text(txt, 'BoTube_Setup.exe'), h2)
        self.assertEqual(parse_sha256_from_checksum_text(h1 + '\n', 'BoTube_Setup.exe'), h1)

    def test_download_installer_atomic_verification_reuse_and_failure_cleanup(self):
        valid_exe = b'MZ' + (b'BOTUBE' * 16000)
        valid_sha = hashlib.sha256(valid_exe).hexdigest()
        url = 'https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v5.2.0/BoTube_Setup.exe'

        release = ReleaseInfo(
            version='5.2.0',
            tag_name='v5.2.0',
            title='BoTube v5.2.0',
            notes='Release notes',
            html_url='https://github.com/Diablo-Loc/App-AI-media-player/releases/tag/v5.2.0',
            published_at='2026-11-28T00:00:00Z',
            asset_name='BoTube_Setup.exe',
            download_url=url,
            asset_size=len(valid_exe),
            sha256=valid_sha,
        )

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            progress_events = []

            # 1. Valid download succeeds atomically and leaves no .part
            with patch(
                'core.app_updater.urllib.request.urlopen',
                return_value=_FakeHTTPResponse(valid_exe, url=url, content_length=len(valid_exe)),
            ):
                out = download_installer_atomic(
                    release,
                    dest_dir=dest,
                    progress_cb=lambda d, t, s: progress_events.append((d, t)),
                    min_bytes=1024,
                )
            self.assertTrue(out.is_file())
            self.assertEqual(out.read_bytes(), valid_exe)
            self.assertEqual(list(dest.glob('*.part')), [])
            self.assertTrue(progress_events)
            self.assertEqual(progress_events[-1][0], len(valid_exe))

            # 2. Cached verified installer is reused without network call (e.g. after UAC cancel)
            with patch('core.app_updater.urllib.request.urlopen', side_effect=AssertionError('Should reuse cache')):
                cached = download_installer_atomic(release, dest_dir=dest, min_bytes=1024)
            self.assertEqual(cached, out)

            # 3. Corrupted SHA-256 fails and deletes .part
            out.unlink()
            bad_sha_rel = ReleaseInfo(**{**release.__dict__, 'sha256': 'f' * 64})
            with patch(
                'core.app_updater.urllib.request.urlopen',
                return_value=_FakeHTTPResponse(valid_exe, url=url, content_length=len(valid_exe)),
            ):
                with self.assertRaises(RuntimeError):
                    download_installer_atomic(bad_sha_rel, dest_dir=dest, min_bytes=1024)
            self.assertEqual(list(dest.glob('*.part')), [])
            self.assertFalse(out.exists())

            # 4. Non-PE payload (e.g. HTML error page) fails and cleans up .part
            html_bytes = b'<!DOCTYPE html>' + b'x' * 5000
            html_rel = ReleaseInfo(**{**release.__dict__, 'sha256': '', 'asset_size': len(html_bytes)})
            with patch(
                'core.app_updater.urllib.request.urlopen',
                return_value=_FakeHTTPResponse(html_bytes, url=url, content_length=len(html_bytes)),
            ):
                with self.assertRaises(RuntimeError):
                    download_installer_atomic(html_rel, dest_dir=dest, min_bytes=1024)
            self.assertEqual(list(dest.glob('*.part')), [])

            # 5. Redirect outside GitHub is blocked
            with patch(
                'core.app_updater.urllib.request.urlopen',
                return_value=_FakeHTTPResponse(valid_exe, url='https://untrusted.example/setup.exe', content_length=len(valid_exe)),
            ):
                with self.assertRaises(RuntimeError):
                    download_installer_atomic(release, dest_dir=dest, min_bytes=1024)
            self.assertEqual(list(dest.glob('*.part')), [])

            # 6. Cancellation deletes .part cleanly
            with patch(
                'core.app_updater.urllib.request.urlopen',
                return_value=_FakeHTTPResponse(valid_exe, url=url, content_length=len(valid_exe)),
            ):
                with self.assertRaises(InterruptedError):
                    download_installer_atomic(release, dest_dir=dest, cancelled=lambda: True, min_bytes=1024)
            self.assertEqual(list(dest.glob('*.part')), [])

    def test_inno_setup_cli_params_and_uac_handoff(self):
        silent_args = build_inno_setup_params(Path(r'C:\Program Files\BoTube'), silent=True)
        self.assertIn('/SP-', silent_args)
        self.assertIn('/SILENT', silent_args)
        self.assertIn('/NORESTART', silent_args)
        self.assertIn('/CLOSEAPPLICATIONS', silent_args)
        self.assertIn('/DIR="C:\\Program Files\\BoTube"', silent_args)

        interactive_args = build_inno_setup_params(None, silent=False)
        self.assertNotIn('/SILENT', interactive_args)
        self.assertNotIn('/DIR=', interactive_args)

        with tempfile.TemporaryDirectory() as td:
            fake_exe = Path(td) / 'BoTube_Setup.exe'
            fake_exe.write_bytes(b'MZfake')
            fake_shell32 = MagicMock()
            fake_shell32.ShellExecuteW.return_value = 42
            with patch('ctypes.windll', MagicMock(shell32=fake_shell32), create=True):
                ok, err = launch_inno_installer(fake_exe, install_dir=Path(r'C:\Program Files\BoTube'), silent=True)
            self.assertTrue(ok)
            self.assertEqual(err, '')
            fake_shell32.ShellExecuteW.assert_called_once()

            fake_shell32.ShellExecuteW.return_value = 5  # SE_ERR_ACCESSDENIED / UAC cancelled
            with patch('ctypes.windll', MagicMock(shell32=fake_shell32), create=True):
                ok2, err2 = launch_inno_installer(fake_exe, silent=True)
            self.assertFalse(ok2)
            self.assertEqual(err2, 'UAC_CANCELLED')

    def test_cleanup_stale_installers(self):
        with tempfile.TemporaryDirectory() as td:
            upd_dir = Path(td) / 'BoTube_Update'
            upd_dir.mkdir()
            old_exe = upd_dir / 'BoTube_Setup_5.0.0.exe'
            new_exe = upd_dir / 'BoTube_Setup_5.2.0.exe'
            part_file = upd_dir / 'BoTube_Setup_5.2.0.exe.part'
            old_exe.write_bytes(b'MZ')
            new_exe.write_bytes(b'MZ')
            part_file.write_bytes(b'MZ')
            old_ts = time.time() - (10 * 86400)
            os.utime(old_exe, (old_ts, old_ts))

            with patch('core.app_updater.tempfile.gettempdir', return_value=td):
                removed = cleanup_stale_installers(max_age_sec=7 * 86400)
            self.assertEqual(removed, 2)
            self.assertFalse(old_exe.exists())
            self.assertFalse(part_file.exists())
            self.assertTrue(new_exe.exists())


class InstallerAndLegacyCleanupContractTests(unittest.TestCase):
    def test_legacy_v102_updater_files_are_removed(self):
        obsolete = (
            'app/updater.py',
            'update_helper.bat',
            'update_helper.sh',
            'patch_build.py',
            'BoTube_patch.spec',
            'build_app_for_update.py',
            'version.json',
        )
        for rel in obsolete:
            self.assertFalse((ROOT / rel).exists(), f'Obsolete legacy updater file still exists: {rel}')

    def test_inno_setup_script_matches_version_appid_and_data_safety_rules(self):
        iss_path = ROOT / 'packaging' / 'BoTube_Setup.iss'
        self.assertTrue(iss_path.is_file())
        text = iss_path.read_text(encoding='utf-8')

        # 1. Exact legacy AppId & canonical version match app/version.py
        self.assertIn(f'AppId={{{APP_ID}', text)
        self.assertIn(f'#define AppVersion "{APP_VERSION}"', text)
        self.assertIn('UsePreviousAppDir=yes', text)
        self.assertIn('DisableDirPage=no', text)
        self.assertIn('CloseApplications=yes', text)

        # 2. User data write permissions under Program Files
        self.assertIn('Name: "{app}\\storage"; Permissions: users-modify', text)
        self.assertIn('Name: "{app}\\app_resources"; Permissions: users-modify', text)

        # 3. [InstallDelete] cleans stale _internal but NEVER deletes user data folders
        m_del = re.search(r'\[InstallDelete\](.*?)\n\[', text, flags=re.S)
        self.assertIsNotNone(m_del)
        del_block = m_del.group(1) if m_del else ''
        self.assertIn('{app}\\_internal', del_block)
        for line in del_block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue
            low = stripped.lower()
            self.assertNotIn('storage', low)
            self.assertNotIn('app_resources', low)
            self.assertNotIn('video', low)
            self.assertNotIn('setting.json', low)

        # 4. Dual [Run] guarantees non-elevated relaunch in both interactive and /SILENT auto-updates
        self.assertIn('skipifsilent runasoriginaluser', text)
        self.assertIn('skipifnotsilent runasoriginaluser', text)


class AppUpdaterUiAndLifecycleTests(unittest.TestCase):
    def tearDown(self):
        set_language('vi', persist=False)

    def test_settings_update_card_and_bilingual_update_dialog(self):
        release = ReleaseInfo(
            version='6.1.0',
            tag_name='v6.1.0',
            title='BoTube v6.1.0',
            notes='### New in v6.1.0\n- Commercial auto-updater\n- Faster startup',
            html_url='https://github.com/Diablo-Loc/App-AI-media-player/releases/tag/v6.1.0',
            published_at='2026-11-28T09:00:00Z',
            asset_name='BoTube_Setup.exe',
            download_url='https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v6.1.0/BoTube_Setup.exe',
            asset_size=148 * 1024 * 1024,
            sha256='a' * 64,
        )

        with isolated_window() as (window, _root):
            studio = window.audio_effects.settings_studio
            self.assertTrue(hasattr(window, 'update_controller'))
            self.assertTrue(hasattr(studio, 'update_card'))
            self.assertFalse(window.update_controller._startup_timer.isActive())  # Never ticks in offscreen tests

            settings_row = window.sidebar.row_for_page('settings')
            window.sidebar.setCurrentRow(settings_row)
            window.handle_sidebar_click(window.sidebar.item(settings_row))
            window.show()
            pump(40)

            self.assertTrue(studio.update_card.isVisible())
            self.assertEqual(studio.lbl_version_badge.text(), f'v{APP_VERSION}')
            self.assertLessEqual(studio.lbl_version_badge.height(), 32)
            expected_h = studio.update_card.layout().totalHeightForWidth(studio.update_card.width())
            self.assertLessEqual(abs(studio.update_card.height() - expected_h), 2)

            # Switch UI to English and verify zero leftover Vietnamese in Settings + UpdateDialog
            studio.language_combo.setCurrentIndex(studio.language_combo.findData('en'))
            pump(40)
            self.assertEqual(_collect_leftover_vietnamese(studio.update_card), [])

            launched_paths: list[str] = []
            launch_results = [(False, 'UAC_CANCELLED'), (True, '')]

            def fake_download(rel, progress_cb=None, cancelled=None):
                if progress_cb:
                    progress_cb(500, 1000, 100_000.0)
                    progress_cb(1000, 1000, 100_000.0)
                return Path(r'C:\Temp\BoTube_Setup_5.2.0.exe')

            def fake_launch(path, install_dir=None, silent=True):
                return launch_results.pop(0)

            dlg = UpdateDialog(
                release,
                current_version=APP_VERSION,
                install_mode='installed',
                install_dir=Path(r'C:\Program Files\BoTube'),
                download_fn=fake_download,
                launch_fn=fake_launch,
                parent=window,
            )
            self.addCleanup(dlg.deleteLater)
            dlg.install_launched.connect(launched_paths.append)
            dlg.show()
            pump(30)

            self.assertEqual(dlg.lbl_version_pill.text(), f'v{APP_VERSION} → v6.1.0')
            self.assertIsNotNone(dlg.lbl_sha_pill)
            self.assertEqual(_collect_leftover_vietnamese(dlg), [])

            # First click: UAC cancelled -> shows clear English error and stays open
            dlg.btn_install.click()
            pump(120)
            self.assertTrue(dlg.lbl_error.isVisible())
            self.assertIn('UAC', dlg.lbl_error.text())
            self.assertEqual(launched_paths, [])
            self.assertEqual(_collect_leftover_vietnamese(dlg), [])

            # Second click: UAC approved -> emits install_launched cleanly
            dlg.btn_install.click()
            pump(120)
            self.assertEqual(len(launched_paths), 1)

            # Switch back to Vietnamese
            studio.language_combo.setCurrentIndex(studio.language_combo.findData('vi'))
            pump(30)
            self.assertEqual(studio.btn_check_updates.text(), 'Kiểm tra cập nhật ngay')

    def test_controller_throttle_skip_version_and_manual_override(self):
        release = ReleaseInfo(
            version='6.2.0',
            tag_name='v6.2.0',
            title='BoTube v6.2.0',
            notes='Notes',
            html_url='https://github.com/Diablo-Loc/App-AI-media-player/releases/tag/v6.2.0',
            published_at='2026-12-01T00:00:00Z',
            asset_name='BoTube_Setup.exe',
            download_url='https://github.com/Diablo-Loc/App-AI-media-player/releases/download/v6.2.0/BoTube_Setup.exe',
            asset_size=120_000_000,
        )
        with tempfile.TemporaryDirectory() as td, isolated_window() as (window, _root):
            ini_settings = QSettings(str(Path(td) / 'upd.ini'), QSettings.Format.IniFormat)
            fetch_calls: list[str] = []

            def fake_fetch(url):
                fetch_calls.append(url)
                return release

            ctrl = AppUpdateController(
                window,
                settings=ini_settings,
                current_version='6.0.0',
                fetch_fn=fake_fetch,
            )
            self.addCleanup(ctrl.shutdown)

            # 1. Recent check within 24h throttles background startup timer
            ini_settings.setValue('last_update_check_ts', time.time() - 60.0)
            ctrl._on_startup_timer()
            self.assertEqual(fetch_calls, [])

            # 2. Skipped version suppresses background popup
            ctrl.set_skipped_version('6.2.0')
            ini_settings.setValue('last_update_check_ts', time.time() - 90_000.0)
            ctrl._on_startup_timer()
            pump(120)
            self.assertEqual(len(fetch_calls), 1)
            self.assertIsNone(ctrl._active_dialog)

            # 3. Manual check overrides both 24h throttle and skipped version
            ctrl.check_now(manual=True)
            pump(120)
            self.assertEqual(len(fetch_calls), 2)
            self.assertIsNotNone(ctrl._active_dialog)
            ctrl.shutdown()


if __name__ == '__main__':
    unittest.main()
