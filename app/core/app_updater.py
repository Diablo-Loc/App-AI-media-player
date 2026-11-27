"""Commercial-grade GitHub Releases + Inno Setup auto-updater engine for BoTube.

Key guarantees:
- Zero startup overhead: pure Python stdlib networking (`urllib.request`, `hashlib`, `ssl`)
  executed strictly on background worker threads, never blocking the Qt GUI thread.
- Cryptographic & structural verification: enforces HTTPS GitHub hosts, PE header (`MZ`),
  expected byte size, and SHA-256 digest verification (via GitHub Releases API `digest`
  or companion checksum file) before atomic rename from `.part` -> `.exe`.
- UAC-safe Inno Setup handoff: launches `BoTube_Setup.exe` via Windows `ShellExecuteW`
  (avoiding `WinError 740` elevation failures on `PrivilegesRequired=admin` installers)
  and only closes BoTube cleanly after the OS confirms launch succeeded.
- User data preservation: Inno Setup upgrades in-place using the current install directory
  without ever touching `storage/` or `app_resources/` (15-20 GB offline AI models).
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import sys
import tempfile
import time
from typing import Callable
from urllib.parse import urlparse
import urllib.error
import urllib.request

from version import (
    APP_ID,
    APP_NAME,
    APP_VERSION,
    GITHUB_RELEASES_API,
    GITHUB_RELEASES_WEB,
)

_ALLOWED_DOWNLOAD_HOST_SUFFIXES = (
    'github.com',
    'githubusercontent.com',
)
_USER_AGENT = f'{APP_NAME}-Updater/{APP_VERSION}'
_UPDATE_TEMP_DIR_NAME = 'BoTube_Update'
_STALE_INSTALLER_TTL_SEC = 7 * 86400
_MIN_INSTALLER_BYTES = 64 * 1024  # Guards against truncated/HTML error pages
_RE_VERSION_CORE = re.compile(r'^[vV]?(\d+(?:\.\d+)*)(?:[-._+]?([0-9A-Za-z.-]+))?$')
_RE_SHA256_HEX = re.compile(r'^[0-9a-fA-F]{64}$')


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    title: str
    notes: str
    html_url: str
    published_at: str
    asset_name: str
    download_url: str
    asset_size: int
    sha256: str = ''
    checksum_url: str = ''


def parse_version(raw: str | None) -> tuple[tuple[int, ...], int, tuple[str, ...]]:
    """Parse SemVer string into a sortable tuple where stable > prerelease.

    Examples:
        '5.1.0' > '5.0.0'
        '5.10.0' > '5.2.0'
        '5.1.0' > '5.1.0-beta.1'
        'v5.1.0' == '5.1.0'
    """
    text = str(raw or '').strip()
    m = _RE_VERSION_CORE.match(text)
    if not m:
        nums = tuple(int(p) for p in re.findall(r'\d+', text))
        return (nums or (0,), 1, ())
    core = tuple(int(p) for p in m.group(1).split('.'))
    # Trim trailing zeros so '5.1' == '5.1.0'
    trimmed = list(core)
    while len(trimmed) > 1 and trimmed[-1] == 0:
        trimmed.pop()
    pre = (m.group(2) or '').strip().lower()
    if not pre:
        return (tuple(trimmed), 1, ())
    pre_parts = tuple(f'{int(tok):09d}' if tok.isdigit() else tok for tok in re.split(r'[.-]', pre))
    return (tuple(trimmed), 0, pre_parts)


def normalize_version_str(raw: str | None) -> str:
    text = str(raw or '').strip()
    if text.startswith(('v', 'V')) and len(text) > 1 and text[1].isdigit():
        return text[1:]
    return text


def is_newer_version(remote: str | None, current: str | None = APP_VERSION) -> bool:
    if not remote or not current:
        return False
    return parse_version(remote) > parse_version(current)


def is_allowed_https_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or '').strip())
    except Exception:
        return False
    if parsed.scheme.lower() != 'https':
        return False
    host = (parsed.hostname or '').lower()
    if not host:
        return False
    return any(host == sfx or host.endswith('.' + sfx) for sfx in _ALLOWED_DOWNLOAD_HOST_SUFFIXES)


def _extract_sha256_digest(raw_digest: str | None) -> str:
    text = str(raw_digest or '').strip()
    if text.lower().startswith('sha256:'):
        text = text[7:].strip()
    return text.lower() if _RE_SHA256_HEX.match(text) else ''


def select_installer_asset(assets: list[dict]) -> tuple[dict | None, str]:
    """Select the primary Windows Inno Setup `.exe` installer and optional checksum file URL."""
    exe_candidates: list[tuple[int, dict]] = []
    checksum_url = ''

    for asset in assets or ():
        if not isinstance(asset, dict):
            continue
        name = str(asset.get('name') or '').strip()
        url = str(asset.get('browser_download_url') or '').strip()
        if not name or not is_allowed_https_url(url):
            continue
        low = name.lower()
        if not checksum_url and (
            low.endswith('.sha256')
            or low.endswith('.sha256.txt')
            or 'sha256' in low
            or 'checksum' in low
        ):
            checksum_url = url
        if not low.endswith('.exe'):
            continue
        if low == 'botube_setup.exe':
            score = 0
        elif 'botube' in low and ('setup' in low or 'install' in low):
            score = 1
        elif 'setup' in low or 'install' in low:
            score = 2
        elif 'botube' in low:
            score = 3
        else:
            score = 4
        exe_candidates.append((score, asset))

    if not exe_candidates:
        return None, checksum_url
    exe_candidates.sort(key=lambda pair: pair[0])
    return exe_candidates[0][1], checksum_url


def parse_github_release(payload: dict, *, include_prerelease: bool = False) -> ReleaseInfo | None:
    """Parse GitHub Releases API JSON response into a validated `ReleaseInfo`."""
    if not isinstance(payload, dict):
        return None
    if payload.get('draft'):
        return None
    if payload.get('prerelease') and not include_prerelease:
        return None

    tag_name = str(payload.get('tag_name') or '').strip()
    version = normalize_version_str(tag_name)
    if not version:
        return None

    html_url = str(payload.get('html_url') or GITHUB_RELEASES_WEB).strip()
    if not is_allowed_https_url(html_url):
        html_url = GITHUB_RELEASES_WEB

    assets = payload.get('assets') if isinstance(payload.get('assets'), list) else []
    chosen, checksum_url = select_installer_asset(assets)
    asset_name = str(chosen.get('name') or '') if chosen else ''
    download_url = str(chosen.get('browser_download_url') or '') if chosen else ''
    try:
        asset_size = max(0, int(chosen.get('size') or 0)) if chosen else 0
    except (TypeError, ValueError):
        asset_size = 0
    sha256 = _extract_sha256_digest(chosen.get('digest') if chosen else '')

    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        title=str(payload.get('name') or f'{APP_NAME} v{version}').strip(),
        notes=str(payload.get('body') or '').strip(),
        html_url=html_url,
        published_at=str(payload.get('published_at') or '').strip(),
        asset_name=asset_name,
        download_url=download_url,
        asset_size=asset_size,
        sha256=sha256,
        checksum_url=checksum_url,
    )


def parse_sha256_from_checksum_text(text: str, asset_name: str) -> str:
    """Parse standard `<64-hex>  <filename>` or single-hash checksum file text."""
    target = Path(asset_name).name.lower() if asset_name else ''
    fallback_hash = ''
    for line in str(text or '').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        parts = stripped.split()
        if len(parts) == 1 and _RE_SHA256_HEX.match(parts[0]):
            fallback_hash = parts[0].lower()
            continue
        if len(parts) >= 2 and _RE_SHA256_HEX.match(parts[0]):
            fname = parts[-1].lstrip('*').strip()
            if target and Path(fname).name.lower() == target:
                return parts[0].lower()
            if not fallback_hash:
                fallback_hash = parts[0].lower()
    return fallback_hash


def _make_request(url: str, *, accept: str = '*/*') -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            'User-Agent': _USER_AGENT,
            'Accept': accept,
            'Cache-Control': 'no-cache',
        },
    )


def fetch_latest_release(
    api_url: str = GITHUB_RELEASES_API,
    *,
    timeout: float = 10.0,
    include_prerelease: bool = False,
) -> ReleaseInfo | None:
    """Query GitHub Releases API for the latest published release."""
    if not is_allowed_https_url(api_url):
        raise ValueError('Update API URL must use an approved HTTPS GitHub endpoint.')
    ctx = ssl.create_default_context()
    req = _make_request(api_url, accept='application/vnd.github+json')
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(2 * 1024 * 1024)
            payload = json.loads(raw.decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise RuntimeError(f'GitHub API HTTP {err.code}') from err
    except urllib.error.URLError as err:
        raise RuntimeError(f'Network error: {err.reason}') from err

    info = parse_github_release(payload, include_prerelease=include_prerelease)
    if info and not info.sha256 and info.checksum_url and info.asset_name:
        try:
            c_req = _make_request(info.checksum_url, accept='text/plain')
            with urllib.request.urlopen(c_req, timeout=min(6.0, timeout), context=ctx) as c_resp:
                c_txt = c_resp.read(256 * 1024).decode('utf-8', errors='replace')
            parsed_hash = parse_sha256_from_checksum_text(c_txt, info.asset_name)
            if parsed_hash:
                info = ReleaseInfo(
                    version=info.version,
                    tag_name=info.tag_name,
                    title=info.title,
                    notes=info.notes,
                    html_url=info.html_url,
                    published_at=info.published_at,
                    asset_name=info.asset_name,
                    download_url=info.download_url,
                    asset_size=info.asset_size,
                    sha256=parsed_hash,
                    checksum_url=info.checksum_url,
                )
        except Exception:
            pass
    return info


def update_cache_dir() -> Path:
    path = Path(tempfile.gettempdir()) / _UPDATE_TEMP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_stale_installers(max_age_sec: float = _STALE_INSTALLER_TTL_SEC) -> int:
    """Remove leftover downloaded `.exe`/`.part` installers older than `max_age_sec`."""
    removed = 0
    folder = Path(tempfile.gettempdir()) / _UPDATE_TEMP_DIR_NAME
    if not folder.is_dir():
        return 0
    now = time.time()
    for entry in list(folder.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in ('.exe', '.part'):
            continue
        try:
            age = now - entry.stat().st_mtime
            if entry.suffix.lower() == '.part' or age >= max_age_sec:
                entry.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    return removed


def detect_install_mode() -> tuple[str, Path]:
    """Return `(mode, base_dir)` where mode is `'installed'`, `'portable'`, or `'dev'`."""
    if not getattr(sys, 'frozen', False):
        return 'dev', Path(__file__).resolve().parents[2]

    exe_dir = Path(sys.executable).resolve().parent
    # Fast local marker created by Inno Setup alongside BoTube.exe
    if (exe_dir / 'unins000.exe').is_file() or (exe_dir / 'unins000.dat').is_file():
        return 'installed', exe_dir

    # Secondary check against Windows Inno Setup Uninstall registry key
    if os.name == 'nt':
        try:
            import winreg

            subkey = rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1'
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, subkey) as k:
                        inst_loc, _ = winreg.QueryValueEx(k, 'InstallLocation')
                        if inst_loc and Path(str(inst_loc)).resolve() == exe_dir:
                            return 'installed', exe_dir
                except OSError:
                    continue
        except Exception:
            pass
    return 'portable', exe_dir


def download_installer_atomic(
    release: ReleaseInfo,
    *,
    dest_dir: Path | None = None,
    progress_cb: Callable[[int, int, float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    timeout: float = 30.0,
    min_bytes: int = _MIN_INSTALLER_BYTES,
) -> Path:
    """Download, verify (PE header + size + SHA-256), and atomically finalize installer `.exe`."""
    if not release.download_url or not is_allowed_https_url(release.download_url):
        raise ValueError('Release does not contain a valid HTTPS GitHub installer URL.')

    target_dir = Path(dest_dir) if dest_dir is not None else update_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_ver = re.sub(r'[^0-9A-Za-z._-]', '_', release.version or 'latest')
    final_path = target_dir / f'{APP_NAME}_Setup_{safe_ver}.exe'
    part_path = target_dir / f'{APP_NAME}_Setup_{safe_ver}.exe.part'

    # Reuse already verified installer if user retried after canceling UAC
    if final_path.is_file() and release.sha256:
        try:
            h_existing = hashlib.sha256()
            with open(final_path, 'rb') as f:
                head = f.read(2)
                if head == b'MZ':
                    h_existing.update(head)
                    for chunk in iter(lambda: f.read(262144), b''):
                        h_existing.update(chunk)
                    if h_existing.hexdigest().lower() == release.sha256.lower():
                        sz = final_path.stat().st_size
                        if progress_cb:
                            progress_cb(sz, sz, 0.0)
                        return final_path
        except OSError:
            pass

    ctx = ssl.create_default_context()
    req = _make_request(release.download_url, accept='application/octet-stream')
    hasher = hashlib.sha256()
    downloaded = 0
    started = time.monotonic()
    last_emit = 0.0
    first_two = b''

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            final_url = resp.geturl()
            if final_url and not is_allowed_https_url(final_url):
                raise RuntimeError('Redirected to an untrusted host outside GitHub.')
            hdr_len = int(resp.headers.get('Content-Length') or 0)
            total = hdr_len or int(release.asset_size or 0)

            with open(part_path, 'wb') as out:
                while True:
                    if cancelled and cancelled():
                        raise InterruptedError('Download cancelled by user.')
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    if not first_two:
                        first_two = chunk[:2]
                    out.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    if progress_cb and (now - last_emit >= 0.08 or (total > 0 and downloaded >= total)):
                        elapsed = max(0.05, now - started)
                        progress_cb(downloaded, total, downloaded / elapsed)
                        last_emit = now

        if downloaded < min_bytes:
            raise RuntimeError(f'Installer download too small ({downloaded} bytes); file may be incomplete.')
        if hdr_len > 0 and downloaded != hdr_len:
            raise RuntimeError(f'Incomplete download ({downloaded} / {hdr_len} bytes).')
        if first_two != b'MZ':
            raise RuntimeError('Downloaded file is not a valid Windows executable (.exe).')
        if release.sha256:
            actual_sha = hasher.hexdigest().lower()
            if actual_sha != release.sha256.lower():
                raise RuntimeError(
                    f'SHA-256 verification failed (expected {release.sha256[:12]}…, got {actual_sha[:12]}…).'
                )

        os.replace(part_path, final_path)
        if progress_cb:
            progress_cb(downloaded, downloaded, 0.0)
        return final_path
    except Exception:
        try:
            part_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def build_inno_setup_params(install_dir: Path | None = None, *, silent: bool = True) -> str:
    """Build clean Inno Setup CLI flags for reliable in-place upgrade & auto-relaunch."""
    args = ['/SP-']
    if silent:
        args.append('/SILENT')
    args.extend(['/NORESTART', '/CLOSEAPPLICATIONS'])
    if install_dir is not None:
        clean_dir = str(Path(install_dir)).rstrip('\\/')
        if clean_dir:
            args.append(f'/DIR="{clean_dir}"')
    return ' '.join(args)


def launch_inno_installer(
    installer_path: Path,
    *,
    install_dir: Path | None = None,
    silent: bool = True,
) -> tuple[bool, str]:
    """Launch Inno Setup `.exe` via Windows `ShellExecuteW` so UAC elevation succeeds cleanly."""
    exe = Path(installer_path).resolve()
    if not exe.is_file():
        return False, 'Installer file not found.'
    if os.name != 'nt':
        return False, 'Automatic Inno Setup installation is only supported on Windows.'

    params = build_inno_setup_params(install_dir, silent=silent)
    import ctypes

    rc = int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            'open',
            str(exe),
            params,
            str(exe.parent),
            1,  # SW_SHOWNORMAL
        )
    )
    if rc > 32:
        return True, ''
    if rc == 5:
        return False, 'UAC_CANCELLED'
    return False, f'ShellExecuteW failed (code {rc}).'
