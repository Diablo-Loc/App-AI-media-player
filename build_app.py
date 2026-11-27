"""Build the portable Windows app without deleting previous builds or user data."""
import argparse
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys

APP_NAME = 'BoTube'
ROOT = Path(__file__).resolve().parent
HIDDEN_IMPORTS = (
    'PySide6', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtSvg', 'PySide6.QtNetwork',
    'ctypes', 'multiprocessing', 'requests', 'urllib3', 'bs4', 'yt_dlp', 'lyricsgenius',
    'google.genai', 'av', 'psutil', 'cryptography', 'websockets', 'tenacity',
    'huggingface_hub', 'filelock', 'fsspec', 'pickletools', 'pickle', 'struct',
    'difflib', 'ast', 'cProfile', 'profile', 'pstats', 'modulefinder', 'pkgutil', 'importlib.metadata',
    'sounddevice', '_sounddevice_data', 'cffi', 'numpy',
    'pykakasi', 'jaconv', 'deprecated', 'pypinyin',
)
# Exclude heavy unused Qt modules, dev/test/plotting packages, and external AI
# frameworks (which live separately in app_resources/libs) so _internal stays lean.
EXCLUDED_MODULES = (
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebChannel',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput', 'PySide6.Qt3DExtras',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtDesigner', 'PySide6.QtSql',
    'PySide6.QtTest', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtSensors',
    'tkinter', '_tkinter', 'matplotlib', 'scipy', 'PIL', 'IPython', 'jupyter', 'notebook',
    'pytest', 'pydoc_data', 'torch', 'torchaudio', 'torchvision', 'transformers',
    'faster_whisper', 'ctranslate2', 'onnxruntime',
)
_UNUSED_BIN_PATTERNS = ('ffplay.exe', '*.pdb', '__pycache__', '*.pyc')


def build_plan(root=ROOT, dist_dir=None, stamp=None):
    root = Path(root).resolve()
    stamp = stamp or datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output = Path(dist_dir).resolve() if dist_dir else root / 'dist'
    # A prior portable folder may contain saved settings/media: never overwrite it.
    if (output / APP_NAME).exists():
        if dist_dir:
            raise ValueError(f'Output đã tồn tại: {output / APP_NAME}. Chọn --dist-dir mới.')
        output = root / 'dist' / ('release-' + stamp)
    if (output / APP_NAME).exists():
        raise ValueError('Output đã tồn tại; chọn thư mục khác.')
    work = root / 'build' / ('release-' + stamp)
    if work.exists():
        raise ValueError('Work directory đã tồn tại; chạy lại để dùng timestamp mới.')
    params = [str(root / 'app/run_app.py'), f'--paths={root}', f'--paths={root / "app"}',
        f'--name={APP_NAME}', '--onedir', '--windowed', '--noconfirm',
        f'--distpath={output}', f'--workpath={work}', f'--specpath={work}',
        f'--icon={root / "icon/app_icon.ico"}', f'--add-data={root / "app"};app']
    params += ['--hidden-import=' + name for name in HIDDEN_IMPORTS]
    params += ['--exclude-module=' + name for name in EXCLUDED_MODULES]
    params += ['--collect-data=pykakasi', '--collect-data=pypinyin']
    return {'root': str(root), 'output': str(output / APP_NAME), 'work': str(work), 'params': params}


def validate_sources(plan):
    root = Path(plan['root'])
    required = ('app/run_app.py', 'app/control/volume_settings.py', 'app/ui/media_info_probe.py',
        'app/ui/assets/icons/LICENSE', 'app/native/AudioEngineNative.dll',
        'icon/app_icon.ico', 'bin/ffmpeg.exe', 'bin/ffprobe.exe')
    missing = [name for name in required if not (root / name).is_file()]
    if not list((root / 'app/ui/assets/icons').glob('*.svg')):
        missing.append('app/ui/assets/icons/*.svg')
    if missing:
        raise FileNotFoundError('Thiếu tài nguyên đóng gói: ' + ', '.join(missing))


def _prune_packaged_internal_app(destination: Path) -> None:
    """Remove duplicate binaries, bytecode caches and dev-only files from _internal/app."""
    internal_app = destination / '_internal' / 'app'
    if not internal_app.is_dir():
        return
    # yt-dlp.exe is already copied to destination/yt-dlp.exe (~22.5 MB saved)
    dup_ytdlp = internal_app / 'download_core' / 'yt-dlp.exe'
    if dup_ytdlp.is_file():
        dup_ytdlp.unlink(missing_ok=True)
    for rel in ('test', 'downloader.py', 'test_build_app.py'):
        target = internal_app / rel
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.is_file():
            target.unlink(missing_ok=True)
    for cache_dir in list(internal_app.rglob('__pycache__')):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)
    for pyc in list(internal_app.rglob('*.pyc')):
        pyc.unlink(missing_ok=True)


def copy_portable_resources(plan):
    root, destination = Path(plan['root']), Path(plan['output'])
    if not (destination / (APP_NAME + '.exe')).is_file():
        raise FileNotFoundError('PyInstaller chưa tạo được BoTube.exe; không sao chép tài nguyên.')
    for name in ('icon', 'native', 'bin'):
        source = root / name
        if source.is_dir():
            ignore = shutil.ignore_patterns(*_UNUSED_BIN_PATTERNS) if name == 'bin' else shutil.ignore_patterns('__pycache__', '*.pyc')
            shutil.copytree(source, destination / name, dirs_exist_ok=True, ignore=ignore)
    # app/native is already included under _internal/app by --add-data.
    downloader = root / 'app/download_core/yt-dlp.exe'
    if downloader.is_file():
        shutil.copy2(downloader, destination / 'yt-dlp.exe')
    _prune_packaged_internal_app(destination)
    (destination / 'app_resources/libs').mkdir(parents=True, exist_ok=True)
    # Models/libs and user storage remain separate, as in the existing portable build.


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Đóng gói BoTube portable, giữ nguyên bản build cũ.')
    parser.add_argument('--dry-run', action='store_true', help='Kiểm tra cấu hình/tài nguyên, không build hoặc xóa file.')
    parser.add_argument('--dist-dir', help='Thư mục xuất mới (chứa thư mục BoTube).')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.error('Build EXE phải chạy trên Windows bằng môi trường Python của dự án.')
    plan = build_plan(dist_dir=args.dist_dir)
    validate_sources(plan)
    versions = {}
    for name in ('PyInstaller', 'PySide6'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    print(json.dumps({'versions': versions, **plan}, ensure_ascii=False, indent=2))
    if args.dry_run:
        print('DRY_RUN_OK: không build, không xóa output, không sửa dữ liệu.')
        if versions['PyInstaller'] is None:
            print('BUILD_NOT_READY: môi trường này chưa có PyInstaller; cần cài công cụ đóng gói trước khi xuất EXE.')
        return
    if any(value is None for value in versions.values()):
        raise SystemExit('Môi trường build thiếu PyInstaller/PySide6. Dùng Python 3.11 của dự án và cài công cụ đóng gói còn thiếu.')
    import PyInstaller.__main__
    Path(plan['work']).mkdir(parents=True)
    previous_directory = Path.cwd()
    try:
        os.chdir(plan['root'])  # Resolve the existing app;app data mapping from the project root.
        PyInstaller.__main__.run(plan['params'])
    finally:
        os.chdir(previous_directory)
    copy_portable_resources(plan)
    print(f'Đã xuất: {Path(plan["output"]) / (APP_NAME + ".exe")}')
    print('Giữ toàn bộ thư mục BoTube cùng _internal/bin/icon khi chạy hoặc phân phối.')


if __name__ == '__main__':
    main()
