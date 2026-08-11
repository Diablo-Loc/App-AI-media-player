"""patch_build.py – tạo một patch updater siêu nhẹ

Phiên bản tối ưu: script này sẽ xây dựng 1 file EXE duy nhất (onefile)
chỉ chứa logic cập nhật, không chứa bất kỳ thư viện nặng nào. Khi chạy
trên máy người dùng, EXE này sẽ ghi đè vào tệp `BoTube.exe` (hoặc tên
mục tiêu khác) và khởi động lại ứng dụng.

1. Chạy: `python patch_build.py` → tạo `dist/BoTube_patch.exe` và
   đồng thời `update.zip` chứa exe plus version.json.
2. Đăng `update.zip` (hoặc chỉ `BoTube_patch.exe`) lên GitHub Release/website.
3. Trong config (hoặc updater), trỏ `update_url` vào file `update.zip`.
4. Ứng dụng chính tải zip, giải nén/hoặc helper chạy, và cấp nhật:
   - patcher copy chính nó lên `BoTube.exe` và cũng ghi đè `version.json`.
   - helper script (BAT/SH) xử lý cả trường hợp patcher lẫn full-binary.

Bản patch nhẹ nên không cần cài thêm thư viện, chỉ cần môi trường Python
và PyInstaller để build.
"""

import os
import PyInstaller.__main__
from pathlib import Path
import textwrap

# --- cấu hình ---
MAIN_EXE_NAME = "BoTube.exe"        # tên file ứng dụng chính
PATCH_EXE_NAME = "BoTube_patch"     # tên file vá được tạo (không có .exe)

# Mã nguồn patcher (được nhúng trong EXE)
PATCHER_SOURCE = textwrap.dedent("""
import sys, os, shutil
from pathlib import Path

def main():
    # thư mục chạy
    cur = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    target = cur / "{MAIN_EXE_NAME}"
    try:
        # ghi đè file chính
        shutil.copy2(sys.executable, target)
        # nếu version.json đi kèm thì cập nhật luôn
        try:
            data_dir = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).parent
            src_version = data_dir / "version.json"
            if src_version.exists():
                shutil.copy2(src_version, cur / "version.json")
        except Exception:
            pass
        # khởi động phiên bản mới
        if sys.platform.startswith('win'):
            os.startfile(str(target))
        else:
            os.system(f'"{{{{target}}}}" &')
    except Exception as e:
        print(f"Patch failed: {{{{e}}}}")
    sys.exit(0)

if __name__ == '__main__':
    main()
""").format(MAIN_EXE_NAME=MAIN_EXE_NAME)

def build_patch():
    args = [
        # cấu hình PyInstaller
        '--onefile',
        '--noconsole',
        f'--name={PATCH_EXE_NAME}',
        '--clean',
        # gói script nhúng từ biến "patcher.py" tạo tạm bên dưới
        '--add-data=patcher.py;.',
        # embed version.json so patcher can update the file
        '--add-data=version.json;.',
        # cuối cùng là tên script cần build
        'patcher.py',
    ]
    # tạo file tạm patcher.py
    with open('patcher.py', 'w', encoding='utf-8') as f:
        f.write(PATCHER_SOURCE)

    print(f"[*] Building patcher exe ({PATCH_EXE_NAME}.exe) ...")
    PyInstaller.__main__.run(args)
    print(f"[OK] Patch exe generated at dist/{PATCH_EXE_NAME}.exe")
    # zip file để upload dễ dàng
    try:
        import zipfile
        zip_name = Path('update.zip')
        with zipfile.ZipFile(zip_name, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(Path('dist') / f"{PATCH_EXE_NAME}.exe", arcname=f"{PATCH_EXE_NAME}.exe")
            # include version metadata so updater can refresh local file
            if Path('version.json').exists():
                zf.write('version.json', arcname='version.json')
        print(f"[OK] Created {zip_name} containing patch executable and version.json")
    except Exception as ex:
        print(f"[WARN] Could not create update.zip: {ex}")

    # dọn file tạm
    try:
        os.remove('patcher.py')
    except:
        pass


if __name__ == '__main__':
    build_patch()
