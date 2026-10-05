# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app\\run_app.py'],
    pathex=['.'],
    binaries=[],
    datas=[('app', 'app')],
    hiddenimports=['PySide6', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'ctypes', 'multiprocessing', 'requests', 'urllib3', 'bs4', 'yt_dlp', 'lyricsgenius', 'google.genai', 'av', 'psutil', 'cryptography', 'websockets', 'tenacity', 'huggingface_hub', 'filelock', 'fsspec', 'pickletools', 'pickle', 'struct', 'difflib', 'ast', 'cProfile', 'profile', 'pstats', 'modulefinder', 'pkgutil', 'importlib.metadata'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BoTube',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon\\app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BoTube',
)
