# Nhớ âm lượng và chuẩn bị build EXE — 04/10/2026

Người dùng chốt các preset hiện có, không thêm preset Moondrop; chỉ yêu cầu nhớ âm lượng, thêm thông số trong Cài đặt và kiểm tra `build_app.py`. Theo yêu cầu trực tiếp, phase này **không chạy lại toàn bộ suite và không build EXE thật**. Không commit, cài dependency, sửa Qt hook, updater hoặc DSP.

## Âm lượng

- Lần đầu hoặc cấu hình thiếu/không hợp lệ: **50%**. Những phiên sau khôi phục mức cuối người dùng chọn, gồm 0% và 100%.
- Thêm ô **Cài đặt → Âm thanh · Âm lượng**, nhập 0–100%. Chỉnh ở đây, popup loa hoặc phím ↑/↓ đều đồng bộ cùng `AudioVolumeControl` hiện có.
- Lưu riêng `storage/playback-volume.json`, dạng `{"volume_percent": 50.0}`. Path dựa trên storage của controller, nên bản portable lưu cạnh EXE. Không sửa QSettings AI, subtitle config, `audio-effects.json`, schema/cache key cũ hoặc âm gốc.
- Chỉ theo dõi signal **user_changed**, không lấy `QAudioOutput.volume()` đã nhân gain. Normalization/EQ ramp/mute/device refresh không ghi âm lượng hiệu dụng thành lựa chọn người dùng.
- Timer thuộc owner gộp thao tác trong 250 ms; thả slider/kết thúc nhập và shutdown flush ngay. Ghi atomic qua helper hiện có; lỗi ghi giữ dirty để retry và có thông báo ngay tại Cài đặt. Startup không ghi đè setting. Reset Cài đặt được xác nhận trả về 50%; hủy reset giữ mức cũ.
- Hiển thị popup/phím tắt dùng round, tránh trường hợp 29% thành 28% do float truncation. Không pause, seek, setSource hoặc tạo output/decoder mới.

Production: helper `control.volume_settings`, bốn MainWindow adapters nhỏ và một adapter reset SettingsPage. Policy/controller/measurement/cache/audio_volume cũ không sửa. Snapshot/hashes ở [manifest](volume-build/reviewed-sources.json), [patch](volume-build/reviewed.patch), [helper](volume-build/helper-hash.json). `volume_build_contracts` kiểm tra reviewed bytes rồi phục hồi preceding metadata phase cho các gate cũ; không recapture historical manifests. Gate AST metadata trước đó cũng dùng adapter này để phân biệt thay đổi mới được duyệt.

## Build

`build_app.py` có main guard, plan/preflight/dry-run và paths neo vào repo; chạy từ folder khác cũng resolve app từ root khi giao cho PyInstaller. Giữ `--onedir`, `--windowed`, `--add-data=app;app`, toàn bộ hidden imports trước; thêm Qt Multimedia/MultimediaWidgets/Svg/Network. Assets/icon license, DLL ở `app/native`, helper mới được bao gồm; ffmpeg/ffprobe/bin, icon và yt-dlp portable được copy theo cách cũ. Chỉ tạo libs rỗng, không mang storage/media/models/AI runtime của người dùng vào bản phân phối.

Không còn xóa `build/dist`. Nếu `dist/BoTube` chưa tồn tại, dùng output đó; nếu đã có thì chọn `dist/release-<timestamp>/BoTube` để giữ bản cũ. Work/spec cũng riêng theo timestamp. `--dist-dir` cho phép chỉ định folder xuất khác, từ chối folder đã có BoTube. Root `BoTube.spec`, `build_app_for_update.py` và các thay đổi requirements của người dùng giữ nguyên; script tạo spec mới trong work folder.

**Môi trường đã đọc: Python 3.11 /PySide6 6.10.1; chưa có PyInstaller trong venv.** `--dry-run` kiểm tra cấu hình/tài nguyên đạt và báo `BUILD_NOT_READY` vì thiếu tool. Chưa có bằng chứng actual frozen EXE/Qt plugins/spawn/portable AI chạy thành công ở phase này.

Đã thêm `requirements-build.txt` pin riêng công cụ PyInstaller 6.22.3 theo [bản công bố chính thức](https://pypi.org/project/pyinstaller/6.22.3/) và [hướng dẫn cài](https://pyinstaller.org/en/stable/installation.html). Không tự cài hoặc nâng dependency. Người dùng chạy:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\venv\Scripts\python.exe build_app.py --dry-run
.\venv\Scripts\python.exe build_app.py
```

Script in đường dẫn EXE/output cuối. Giữ toàn bộ folder BoTube cùng `_internal`, `bin`, `icon`; runtime AI/model vẫn do resource manager hoặc môi trường portable cung cấp như cũ. Sau khi build cần mở EXE thật để nghiệm thu startup/media/volume nhớ lại/icon/sub/AI spawn. Dry-run và handoff compiler giả lập không thay thế nghiệm thu đó.

## Kiểm chứng theo phạm vi nhỏ

- **11 pass**, 6,953 s: 9 mới (5 volume, 3 packaging, 1 scope) +2 volume/device regressions cũ. [Log](volume-build/focused-tests.txt). Qt/player thực, storage/settings/media tạm; compiler handoff dùng fixture, không tạo EXE thật.
- **22 source/hash/AST gates pass**, 3,766 s, checkout Git từ index tạm; không stage vào index thật. [Log](volume-build/checkout-gates.txt). Không chạy full discovery theo yêu cầu user.
- [Dry-run](volume-build/build-dry-run.txt) gồm plan/output/resource validation, xác nhận missing PyInstaller. Không build/cài/xóa output trong kiểm tra.
- **31/31 file giữ hash trước/sau lượt kiểm tra cuối** theo baseline hiện tại: [before](volume-build/saved-current-before.json), [check](volume-build/saved-current-check.json). Mức volume test chỉ ghi trong thư mục tạm. Baseline lịch sử được copy lúc đầu từ audit cũ: [historical before](volume-build/saved-before.json), [historical check](volume-build/saved-file-check.json); 30/31 còn khớp. Riêng `storage/subtitles/media_index.json` có CreationTime/LastWriteTime 17:35:02, trước snapshot phase này 17:54:55, nên đã thay đổi trước các edits/tests này. Giữ nguyên index hiện tại, không rollback/ghi đè hoặc sửa baseline lịch sử để làm hash khớp. Kiểm tra lại 11 test với baseline mới xác nhận không thay 31 file trong lượt đó.
- `git diff --check` và source compile/source gates đạt. Các sửa build/spec/requirements/xóa logs có từ trước và dữ liệu người dùng được giữ nguyên.
