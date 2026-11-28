<div align="center">

# BoTube 6.0 · AI Media Player & Hi-Fi Audio Studio

**Trình phát Nhạc & Video AI thế hệ mới cho Windows — Âm thanh Hi-Fi 64-bit WASAPI Exclusive, Whisper AI CUDA, Dịch đa mô hình LLM, Karaoke từng chữ, Xuất video GPU NVENC & Cập nhật tự động**

<p>
  <a href="https://diablo-loc.github.io/App-AI-media-player/"><img src="https://img.shields.io/badge/Trang%20Web%20Ch%C3%ADnh%20Th%E1%BB%A9c-BoTube%206.0-16332B?style=for-the-badge&logo=googlechrome&logoColor=77E0BE" alt="Official Website"/></a>
  <a href="https://github.com/Diablo-Loc/App-AI-media-player/releases/latest/download/BoTube_Setup.exe"><img src="https://img.shields.io/badge/T%E1%BA%A3i%20Windows%2064--bit-BoTube__Setup.exe-77E0BE?style=for-the-badge&logo=windows&logoColor=0B1017" alt="Download Windows Installer"/></a>
</p>

<p>
  <a href="https://github.com/Diablo-Loc/App-AI-media-player/releases/latest"><img src="https://img.shields.io/github/v/release/Diablo-Loc/App-AI-media-player?style=flat-square&color=1F6FEB&label=Latest%20Release" alt="Latest Release"/></a>
  <img src="https://img.shields.io/badge/Version-6.0.2-2EA043?style=flat-square" alt="Version 6.0.2"/>
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20x64-0078D6?style=flat-square&logo=windows&logoColor=white" alt="Platform Windows"/>
  <img src="https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-41CD52?style=flat-square&logo=qt&logoColor=white" alt="PySide6 / Qt6"/>
  <img src="https://img.shields.io/badge/Audio-64--bit%20Float%20WASAPI-77E0BE?style=flat-square" alt="64-bit Float WASAPI"/>
  <img src="https://img.shields.io/badge/AI%20%26%20Export-Whisper%20CUDA%20%2B%20NVENC-76B900?style=flat-square&logo=nvidia&logoColor=white" alt="Whisper CUDA + NVENC"/>
</p>

**Tiếng Việt** · [English](README.en.md) · [🌐 Trang giới thiệu BoTube 6.0](https://diablo-loc.github.io/App-AI-media-player/) · [📦 Tải BoTube_Setup.exe](https://github.com/Diablo-Loc/App-AI-media-player/releases/latest/download/BoTube_Setup.exe)

</div>

---

**BoTube 6.0** là ứng dụng phát nhạc, video và tạo phụ đề AI thế hệ mới dành cho Windows 10/11 64-bit. Toàn bộ trải nghiệm nghe nhìn cao cấp — từ bộ xử lý âm thanh **Hi-Fi 64-bit Float + WASAPI Exclusive**, nhận diện giọng nói **Faster-Whisper CUDA**, dịch lời nhạc đa mô hình **NLLB / Gemini / OpenAI / Claude**, **Karaoke khớp từng chữ kèm phiên âm offline**, đến **xuất video tăng tốc GPU NVIDIA NVENC** và **cập nhật tự động chuẩn SHA-256** — được hội tụ gọn gàng trong một ứng dụng desktop cục bộ siêu mượt, riêng tư tuyệt đối.

![Minh họa giao diện BoTube: thanh điều hướng, trang For You và điều khiển phát](docs/images/botube-interface.png)

*Minh họa được dựng từ các thành phần giao diện thật của ứng dụng với danh sách phát trống; không chứa dữ liệu cá nhân.*

---

## Điểm đột phá trên BoTube 6.0

| Hạng mục | Nâng cấp chính trên BoTube 6.0 |
| --- | --- |
| **Âm thanh Hi-Fi 64-bit & Audio Lab** | Động cơ xử lý 64-bit Float, chuẩn hóa âm lượng **EBU R128 (−14 LUFS)** chống vỡ đỉnh 0 dBTP, **10-Band & Parametric EQ** (tương thích Squiglink/AutoEQ), **WASAPI Exclusive** cho USB DAC rời và phòng đo phổ tần số RTA đối chiếu **A/B trực tiếp**. |
| **Karaoke từng chữ & Phiên âm tức thì** | Chế độ **AMLL Sing** mượt như Apple Music, khớp **từng chữ/âm tiết thật** theo giọng hát; tạo dòng phiên âm Latinh (**Romaji, Pinyin, Revised Romanization**) hoàn toàn offline bằng phím tắt `R`. |
| **Xuất Video + Lyric bằng GPU NVIDIA** | Tự động tăng tốc phần cứng **NVIDIA NVENC (`h264_nvenc` ⚡)** khi xuất video kèm phụ đề + hiệu ứng quang học (16:9, 9:16 Shorts, 1:1, 4K), tự fallback sang `libx264` CPU khi cần và giữ nguyên luồng âm thanh gốc. |
| **Bộ sưu tập, Lịch sử & Smart Resume** | Bổ sung trang **Bộ sưu tập** (Yêu thích, Playlist tùy biến, Nghe nhiều nhất) và **Lịch sử phát** tự ghi nhớ chính xác mốc thời gian nghe dở để tiếp tục chỉ bằng một cú bấm. |
| **Cài đặt Studio & Song ngữ 100% VI/EN** | Giao diện **Cài đặt** mới gọn gàng tự động lưu; chuyển đổi tức thì **Tiếng Việt ↔ English** toàn bộ ứng dụng mà không cần khởi động lại hay thay đổi dữ liệu đã lưu. |
| **Cập nhật tự động & Tối ưu dung lượng** | Kiểm tra và nâng cấp trực tiếp qua **GitHub Releases API + Inno Setup 6**, xác thực chữ ký **SHA-256**, tự đóng mở lại ứng dụng an toàn không cần quyền Admin, giảm **>174 MB** dung lượng gói đóng gói. |

---

## Tính năng toàn diện

- **Phát media & Thư viện thông minh:** quét thư mục siêu tốc (`.mp3`, `.mp4`, `.mkv`, `.wav`, `.mov`, `.avi`), tìm kiếm tức thì, trang **For You**, hàng đợi phát, **Bộ sưu tập** (Yêu thích / Playlist / Nghe nhiều nhất), **Lịch sử phát (Smart Resume)**, toàn màn hình và **Mini Player (Dynamic Island)**.
- **Âm thanh phòng thu Hi-Fi:** ghi nhớ âm lượng phát, chuẩn hóa độ lớn giữa các bài mà không làm thay đổi file gốc, các preset tối ưu cho tai nghe & DAC rời, bộ lọc PEQ 64-bit và phòng đo phổ **Audio Lab**.
- **Nhận diện lời AI & Lấy lời nhanh:** ưu tiên sub có sẵn (`.lrc`/`.srt`/`.ass`) hoặc lời chuẩn **LRCLIB** căn nhịp giọng hát **< 1 giây**; tự chuyển sang **Faster-Whisper** (`tiny` → `large-v3`, CPU hoặc NVIDIA CUDA) với 2 chế độ **Lời bài hát** và **Hội thoại / Phim**.
- **Dịch thuật AI & Đối soát Genius:** chạy miễn phí hoàn toàn offline bằng **NLLB-200**, hoặc dịch trực tuyến chuẩn văn phong qua **Google Gemini**, **OpenAI (GPT-4o / GPT-5)** và **Anthropic Claude** kèm đối chiếu lời gốc **Genius** có bộ lọc độ tin cậy từng câu.
- **Hiển thị phụ đề, Karaoke & Biên tập:** chọn hiển thị Gốc / Anh / Việt hoặc song ngữ, hiệu ứng **AMLL Sing**, phi tiêu, sao, cánh hoa, typography, **🎤 Chế độ Karaoke** khớp từng chữ, phiên âm trên cùng (`Phiên âm (R)`), cùng trình chỉnh sửa phụ đề hỗ trợ nhập/xuất `JSON`, `SRT`, `ASS`, `LRC`.
- **Xuất video kèm phụ đề:** chọn tỉ lệ nguồn, `16:9`, `9:16`, `1:1`, `4:5`, `21:9`, độ phân giải lên tới 4K, FPS, vùng an toàn chống cắt chữ và mã hóa ưu tiên GPU **NVENC**.
- **Tải video & nhạc chất lượng gốc:** tích hợp `yt-dlp` tối ưu giữ nguyên chất lượng nguồn âm thanh AAC/Opus hoặc MP3 320 kbps, hỗ trợ nối tải dở dang.

---

## Cài đặt & Nâng cấp (Từ bản 5.0 lên 6.0 an toàn 100%)

### Cài mới hoặc nâng cấp bằng `BoTube_Setup.exe`

**[🌐 Mở trang giới thiệu BoTube 6.0](https://diablo-loc.github.io/App-AI-media-player/)** · **[⬇️ Tải BoTube_Setup.exe](https://github.com/Diablo-Loc/App-AI-media-player/releases/latest/download/BoTube_Setup.exe)** · **[📋 Tất cả bản phát hành](https://github.com/Diablo-Loc/App-AI-media-player/releases)**

1. Tải **`BoTube_Setup.exe`** từ trang [Releases](https://github.com/Diablo-Loc/App-AI-media-player/releases/latest) và chạy trình cài đặt Windows.
   - **Nếu máy đang cài BoTube 5.0:** bộ cài giữ nguyên `AppId`, tự nâng cấp đè đúng thư mục cũ, tự dọn sạch file runtime thừa của bản 5.0 và **giữ nguyên 100% thư viện, playlist, phụ đề (`storage/`) và toàn bộ mô hình AI (`app_resources/`)**.
2. Mở BoTube từ shortcut vừa tạo. Nghe nhạc Hi-Fi, tải video và xem phụ đề có sẵn hoạt động ngay lập tức.
3. **Trước lần tạo phụ đề AI đầu tiên**, mở **Cài đặt → Tải / Cập nhật mô hình & thư viện AI** để chọn model Whisper (khuyên dùng `large-v3` nếu có GPU NVIDIA) và bấm **Bắt đầu cài đặt tự động**.
4. Nếu muốn dịch hoàn toàn ngoại tuyến (hoặc làm dự phòng khi API lỗi), chọn tải kèm **NLLB-200 Offline**.
5. Chọn thiết bị tính toán (`CUDA` hoặc `CPU`), **Loại nội dung** và dịch vụ dịch thuật trong **Cài đặt** (tự động lưu tức thì).

![Các bước cài BoTube, tải tài nguyên AI, chọn cấu hình và tạo phụ đề](docs/images/botube-setup-flow.svg)

### Cơ chế cập nhật tự động (từ bản 6.0.0 trở đi)

BoTube 6.0 tích hợp bộ cập nhật trực tiếp từ **GitHub Releases**:
- Tự động kiểm tra bản phát hành mới tối đa 1 lần/ngày khi khởi động (có thể bật/tắt hoặc kiểm tra thủ công bất cứ lúc nào trong **Cài đặt → Cập nhật ứng dụng**).
- Tải `BoTube_Setup.exe` từ nguồn HTTPS chính thức của GitHub, kiểm tra định dạng thực thi (`MZ`) và **xác thực mã băm SHA-256** trước khi cài đặt.
- Tự gọi Inno Setup ở chế độ nâng cấp gọn nhẹ (`/SILENT /CLOSEAPPLICATIONS`), đóng app an toàn, cài đè sạch sẽ và tự mở lại BoTube ở quyền người dùng thường.
- Dữ liệu cá nhân (`storage/`) và kho model AI (`app_resources/`) luôn được bảo toàn nguyên vẹn.

### Lưu ý dung lượng ổ đĩa

**Dung lượng bộ cài không phải tổng dung lượng sau khi cài thêm gói AI offline:**
- Bộ cài `BoTube_Setup.exe` gọn nhẹ (chỉ gồm ứng dụng, runtime và FFmpeg/yt-dlp).
- Nếu tải thêm một model Whisper lớn (`large-v3`) cùng bộ dịch offline `NLLB-200` và thư viện PyTorch/CUDA, nên dự trù khoảng **15–20 GB dung lượng trống** trên ổ chứa thư mục cài đặt (`app_resources/`).
- Cache âm thanh xử lý (`storage/audio-playback-cache/`) có ngân sách mặc định khoảng **1 GiB**.

### Chọn loại nội dung AI

| Chế độ | Phù hợp | Cách xử lý |
| --- | --- | --- |
| **Lời bài hát** · mặc định | Nhạc, MV, lyric video | Giữ luồng chuyên biệt cho nhạc: lọc intro/credit, nhóm câu theo nhịp, căn chữ Karaoke và dịch theo văn phong lời bài hát (hỗ trợ đối soát Genius). |
| **Hội thoại / Phim** | Video, phim, podcast | Chia câu theo từ, dấu câu và khoảng nghỉ tự nhiên; bỏ qua bộ lọc nhạc/Genius và dịch theo văn phong hội thoại. |

---

## Phím tắt trình phát

| Phím | Thao tác |
| --- | --- |
| `Space` | Phát / Tạm dừng |
| `F` | Bật / Tắt toàn màn hình |
| `Esc` | Thoát chế độ toàn màn hình |
| `←` / `→` | Tua lùi / tiến 10 giây |
| `↑` / `↓` | Tăng / Giảm âm lượng |
| `R` | Bật / Tắt nhanh dòng **Phiên âm (Romaji / Pinyin / Hàn)** khi đang xem video |

---

## Chạy từ mã nguồn & Đóng gói bản phát hành

Môi trường mục tiêu: **Windows 10/11 64-bit, Python 3.11**. Đặt `ffmpeg.exe` và `ffprobe.exe` trong `bin/` ở gốc dự án (hoặc `app_resources/bin/` / PATH).

### 1. Chạy từ mã nguồn

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app/run_app.py
```

### 2. Đóng gói bản Portable & Bộ cài `BoTube_Setup.exe` (1 lệnh)

Yêu cầu đã cài `PyInstaller` (`pip install -r requirements-build.txt`) và **Inno Setup 6**:

```powershell
# Đóng gói PyInstaller portable -> tự biên dịch Inno Setup 6 -> xuất BoTube_Setup.exe & .sha256
.\packaging\build_release_installer.ps1 -BuildPortable
```

- Lệnh trên đọc phiên bản duy nhất từ `app/version.py` (`6.0.2`), chạy `build_app.py` (không ghi đè bản build cũ trong `dist/`), biên dịch `packaging/BoTube_Setup.iss` và xuất sẵn `Installer\BoTube_Setup.exe` kèm `Installer\BoTube_Setup.exe.sha256`.
- Nếu chỉ muốn kiểm tra cấu hình build mà không đóng gói: `.\venv\Scripts\python.exe build_app.py --dry-run`.

### 3. Cấu trúc dữ liệu người dùng

```text
BoTube/
├── BoTube.exe                    # Tệp thực thi chính
├── _internal/                    # Runtime PyInstaller (tự làm sạch khi nâng cấp)
├── bin/                          # FFmpeg, FFprobe
├── icon/ & resources/            # Biểu tượng ứng dụng
├── app_resources/                # Thư viện AI portable, Whisper & NLLB models (bảo toàn 100%)
└── storage/                      # Thư viện, playlist, phụ đề, tùy chỉnh & cache (bảo toàn 100%)
```

---

## Kiểm thử & Phát triển

Mã nguồn ứng dụng nằm trong `app/` (`core/`, `ui/`, `control/`, `ai/`, `pipeline/`, `translate/`, `subtitle/`, `download_core/`).

```powershell
$env:PYTHONPATH=".;app"; $env:KMP_DUPLICATE_LIB_OK="TRUE"; $env:QT_QPA_PLATFORM="offscreen"
.\venv\Scripts\python.exe -m unittest `
  tests.test_app_updater `
  tests.test_ui_settings_and_i18n `
  tests.test_app_optimization `
  tests.test_hifi_audio_engine `
  tests.test_subtitle_studio `
  tests.test_nvenc_video_export `
  tests.test_word_karaoke_and_phonetics `
  tests.test_playlists_favorites_history `
  tests.test_download_studio -v
```

Xem thêm [tài liệu dự án](docs/README.md), [hợp đồng tính năng](docs/FEATURE_PARITY.md), [hướng dẫn kiểm thử](tests/README.md) và [quy tắc phát triển](AGENTS.md).

## Giới hạn hiện tại

- Nhận diện giọng nói AI có thể lệch từ hoặc mốc thời gian khi hát quá nhanh, nhạc nền rất lớn hoặc nhiều giọng chồng nhau — nên xem lại bằng trình sửa phụ đề trước khi xuất bản.
- Dịch Online và tải nội dung phụ thuộc mạng, giới hạn API và chính sách dịch vụ bên thứ ba; hãy giữ bí mật API key và Genius token cục bộ trên máy.
- Bộ preset âm thanh tối ưu hóa độ sạch, độ cân bằng và loại bỏ clip kỹ thuật số, không thể tái tạo chi tiết gốc đã bị mất do file nguồn nén chất lượng thấp.

## Giấy phép & Tài nguyên bên thứ ba

- Biểu tượng Lucide đi kèm theo [ISC License](app/ui/assets/icons/LICENSE).
- Model dịch cục bộ [NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M) phát hành theo **CC-BY-NC-4.0**; cần kiểm tra điều kiện sử dụng khi phân phối thương mại.
- Các thư viện, FFmpeg, yt-dlp và model AI tuân theo giấy phép riêng của từng dự án gốc.
