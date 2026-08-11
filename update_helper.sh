#!/bin/sh
# POSIX update helper: unzip and attempt to restart or run patcher
sleep 2
if [ -f "storage/update.zip" ]; then
  mkdir -p storage/temp_update
  unzip -o storage/update.zip -d storage/temp_update
  # if patcher exists, run it and exit
  if [ -f "storage/temp_update/BoTube_patch.exe" ]; then
    chmod +x "storage/temp_update/BoTube_patch.exe"
    "storage/temp_update/BoTube_patch.exe" &
    exit 0
  fi
  # otherwise copy all files (may include BoTube.exe)
  cp -r storage/temp_update/* .
  rm -rf storage/temp_update
  rm -f storage/update.zip
fi
# Try to restart using python
if command -v python3 >/dev/null 2>&1; then
  python3 app/run_app.py &
elif command -v python >/dev/null 2>&1; then
  python app/run_app.py &
else
  echo "Update applied. Please start the application manually."
fi
