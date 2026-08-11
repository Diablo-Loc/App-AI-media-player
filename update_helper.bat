@echo off
set EXE_NAME=BoTube.exe
set PATCH_EXE_NAME=BoTube_patch
set ZIP_FILE=storage\update.zip

echo ===========================================
echo       DANG CAP NHAT BOTUBE - VUI LONG CHO
echo ===========================================

:: Doi 2 giay de App chinh tat han (tranh loi File in Use)
timeout /t 2 /nobreak > nul

:: Kiem tra file update co ton tai ko
if not exist "%ZIP_FILE%" (
    echo [LOI] Khong tim thay file update.zip!
    pause
    exit
)

:: Giai nen de lay BoTube.exe moi vao thu muc tam
echo [*] Dang giai nen...
powershell -Command "Expand-Archive -Path '%ZIP_FILE%' -DestinationPath 'storage\temp_update' -Force"

:: Nếu zip chứa bản vá lớn (BoTube.exe), ghi đè như trước
if exist "storage\temp_update\%EXE_NAME%" (
    echo [*] Dang ghi de file code moi...
    move /y "storage\temp_update\%EXE_NAME%" "%EXE_NAME%"
    if exist "storage\temp_update\version.json" (
        copy /y "storage\temp_update\version.json" "version.json"
    )
) else if exist "storage\temp_update\%PATCH_EXE_NAME%.exe" (
    echo [*] Phat hien patcher, se chay de cap nhat...
    set PATCH_STARTED=1
    start "" "storage\temp_update\%PATCH_EXE_NAME%.exe"
) else (
    echo [LOI] Khong tim thay file %EXE_NAME% hoac patcher trong ban va!
)

:: Don dep
echo [*] Dang don dep file tam...
rd /s /q "storage\temp_update"
del "%ZIP_FILE%"

if defined PATCH_STARTED (
    echo [OK] Cap nhat bang patcher da duoc thuc hien. BoTube.exe da duoc khoi dong.
) else (
    echo [OK] Cap nhat thanh cong! Dang khoi dong lai...
    start "" "%EXE_NAME%"
)
exit