import PyInstaller.__main__
import os
import shutil

APP_NAME = "BoTube"

# 1. Dọn dẹp không gian build cũ
print("🧹 Đang dọn dẹp không gian build cũ...")
for folder in ['build', 'dist']:
    if os.path.exists(folder):
        shutil.rmtree(folder)

# 2. Lệnh build TINH GỌN - Đóng gói lõi giao diện và các cổng kết nối độc lập
params = [
    'app/run_app.py',
    f'--name={APP_NAME}',
    '--onedir',         # Xuất ra thư mục để dễ làm bộ cài Inno Setup
    '--windowed',       # Ẩn console đen khi chạy
    '--noconfirm',
    '--clean',
    '--icon=icon/app_icon.ico',
    
    # Gom toàn bộ mã nguồn của app vào trong gói
    '--add-data=app;app',
    
    # --- HIDDEN IMPORTS CHỐT CHẶN (Không để sót bất kỳ cổng kết nối nào từ file cũ) ---
    '--hidden-import=PySide6',
    '--hidden-import=PySide6.QtCore',
    '--hidden-import=PySide6.QtGui',
    '--hidden-import=PySide6.QtWidgets',
    '--hidden-import=ctypes',
    '--hidden-import=multiprocessing',
    '--hidden-import=requests',
    '--hidden-import=urllib3',
    '--hidden-import=bs4',              # beautifulsoup4
    '--hidden-import=yt_dlp',
    '--hidden-import=lyricsgenius',
    '--hidden-import=google.genai',
    '--hidden-import=av',               # PyAV xử lý âm thanh/video
    '--hidden-import=psutil',
    '--hidden-import=cryptography',
    '--hidden-import=websockets',
    '--hidden-import=tenacity',
    
    # Thư viện mồi bắt buộc để Download Manager tự download AI runtime sau đó
    '--hidden-import=huggingface_hub',
    '--hidden-import=filelock',
    '--hidden-import=fsspec',
    
    # 🎯 FIX TRIỆT ĐỂ LÕI HỆ THỐNG CHO TORCH / WHISPER CẮM NGOÀI
    '--hidden-import=pickletools',
    '--hidden-import=pickle',
    '--hidden-import=struct',
    '--hidden-import=difflib',
    '--hidden-import=ast', 
    '--hidden-import=cProfile',
    '--hidden-import=profile',
    '--hidden-import=pstats',
    '--hidden-import=modulefinder', 
    '--hidden-import=pkgutil',
    '--hidden-import=importlib.metadata',
]

print("🚀 Bắt đầu đóng gói khung ứng dụng (PyInstaller)...")
PyInstaller.__main__.run(params)

# =====================================================================
# 3. QUY TRÌNH ĐỒNG BỘ TÀI NGUYÊN (CHUẨN PORTABLE RỜI - CẠNH FILE EXE)
# =====================================================================
dist_path = f'dist/{APP_NAME}'
print("\n📦 Đang ghim các tài nguyên môi trường ngoài cạnh file EXE...")

# 🔹 1. ĐỒNG BỘ THƯ MỤC ICON (Chỉ đặt ngoài cạnh file EXE cho Portable / Inno Setup)
if os.path.exists('icon'):
    shutil.copytree('icon', os.path.join(dist_path, 'icon'), dirs_exist_ok=True)
    print("  ✅ Đã đồng bộ cấu trúc Icon rời nằm cạnh file EXE.")

# 🔹 2. ĐỒNG BỘ NATIVE DLL C++ (Chỉ đặt ngoài cạnh file EXE)
if os.path.exists('native'):
    shutil.copytree('native', os.path.join(dist_path, 'native'), dirs_exist_ok=True)
    print("  ✅ Đã đồng bộ cấu trúc Native DLL C++ nằm cạnh file EXE.")

# 🔹 3. ĐỒNG BỘ BỘ CÔNG CỤ GIẢI MÃ ÂM THANH HỆ THỐNG (bin/ffmpeg, bin/ffprobe)
if os.path.exists('bin'):
    shutil.copytree('bin', os.path.join(dist_path, 'bin'), dirs_exist_ok=True)
    print("  ✅ Đã ghim bộ giải mã độc lập (bin/ffmpeg.exe, bin/ffprobe.exe) cạnh file EXE.")

# 🔹 4. ĐỒNG BỘ LÕI TẢI yt-dlp.exe
yt_dlp_src = 'app/download_core/yt-dlp.exe'
if os.path.exists(yt_dlp_src):
    shutil.copy2(yt_dlp_src, os.path.join(dist_path, 'yt-dlp.exe'))
    print("  ✅ Đã đồng bộ lõi tải yt-dlp.exe nằm cạnh file EXE.")

# 🔹 5. TẠO SẴN KÉN RỖNG CHO AI RUNTIME DỰ PHÒNG
os.makedirs(os.path.join(dist_path, 'app_resources', 'libs'), exist_ok=True)
print("  ✅ Đã tạo sẵn cấu hình thư mục động cho AI Runtime: app_resources/libs.")

print(f"\n🎉 HOÀN THÀNH QUY TRÌNH ĐÓNG GÓI CHUẨN SENIOR!")
print(f"📁 Thư mục sản phẩm siêu sạch: {os.path.abspath(dist_path)}")