import PyInstaller.__main__

APP_NAME = "BoTube"

# Danh sách các "gã khổng lồ" cần loại bỏ khỏi bản build
# Chúng ta loại bỏ vì máy User ĐÃ CÓ SẴN trong thư mục _internal cũ rồi
excludes = [
    'torch', 
    'nvidia', 
    'faster_whisper', 
    'matplotlib', 
    'numpy', 
    'PIL', 
    'cv2',
    'PySide6' # Nếu ông muốn cực nhẹ, loại luôn cả UI (nhưng cẩn thận lỗi thiếu DLL)
]

params = [
    'app/run_app.py',
    f'--name={APP_NAME}',
    '--onedir',        # Vẫn để onedir để nó không nén đống rác vào 1 file
    '--windowed',
    '--noconfirm',
    '--clean',
    '--add-data=app;app',
]

# Thêm lệnh loại bỏ từng thằng trong danh sách excludes
for mod in excludes:
    params.append(f'--exclude-module={mod}')

print(f"🚀 Đang build bản PATCH siêu nhẹ (loại bỏ thư viện nặng)...")
PyInstaller.__main__.run(params)

print(f"\n✅ Xong! Kiểm tra dist/{APP_NAME}/{APP_NAME}.exe")
print(f"📦 File này giờ chỉ nặng vài MB vì không có Torch/Nvidia đi kèm.")