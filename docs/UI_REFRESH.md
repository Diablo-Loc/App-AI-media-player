# Nâng UI trên baseline gốc — 03/10/2026

04/10/2026: For You được cân gutter 12 px và search trên/dưới; native caption đồng bộ graphite/chữ/viền qua DWM, giữ MainWindow byte hash/frame controls/video/subtitle lifecycle. Full suite 159 pass +11 skip; native Win11 và 7 regressions mới/DPI 200% đã kiểm tra. Xem [FORYOU_SPACING_AND_CAPTION.md](FORYOU_SPACING_AND_CAPTION.md); các con số phía dưới là lịch sử từng đợt.

Nâng chất lượng thu nhỏ thumbnail playlist và pixel/DPR fractional: **55 pass + 11 skip lịch sử**; tám regression mới đạt ở 125%/150%/200%. Không tạo lại cache ảnh nguồn hoặc đổi logic tính năng. Xem [PLAYLIST_THUMBNAIL_QUALITY.md](PLAYLIST_THUMBNAIL_QUALITY.md).

Cân chỉnh playlist, combobox popup tải xuống và nút menu giữa sidebar: **47 pass + 11 skip lịch sử**, sáu regression mới đạt thêm ở DPI 200%. Chỉ sửa trình bày; source/API/signals baseline vẫn đạt. Xem [UI_LAYOUT_POLISH.md](UI_LAYOUT_POLISH.md). Các con số phía dưới lưu từng đợt trước.

Kết quả mới nhất: **41 pass + 11 skip lịch sử**, sửa mini video lệch/refresh và màu hover sau tắt shuffle/repeat. Có probe decode/frame với một file có sẵn; không phải full native/EXE parity. Xem [UI_MEDIA_SURFACE.md](UI_MEDIA_SURFACE.md). Các con số 22/32 phía dưới thuộc các đợt trước.

Cập nhật sau phản hồi người dùng: đã sửa icon sidebar thu gọn, tương tác overlay/playback, auto-hide khi mở popup và bố cục cửa sổ hẹp. Kết quả hiện tại **32 pass + 11 skip lịch sử**, 10 regression mới còn chạy ở DPI 200%; xem [UI_STABILITY.md](UI_STABILITY.md). Báo cáo bên dưới lưu kết quả đợt UI đầu, trước các sửa này.

Người dùng cho phép nâng UI sau khi khôi phục và audit app gốc. Bản này nâng lớp trình bày trên **PySide6 Widgets**: sidebar, Home/Library, For You, thẻ media, thanh phát, Download, Settings, mini player và các popup/công cụ phụ đề. Giữ các component và luồng điều khiển hiện có. Những tối ưu AI/library/editor trong roadmap nền tảng chưa được áp dụng.

## Thiết kế và cấu trúc

Palette graphite/mint, chữ Segoe UI có sẵn trên Windows, heading rõ, spacing và border thống nhất. Các nút phát, điều hướng, âm lượng, fullscreen, mini, subtitle và công cụ dùng SVG cùng bộ Lucide. Icon có normal/hover/selected/disabled, render tại DPI khác nhau và cache giới hạn. Các mục sidebar giữ index và legacy UserRole; thu gọn hiện icon ở giữa, mở lại trả label. Một số chữ/status từ luồng nghiệp vụ gốc vẫn giữ ký hiệu cũ; chưa làm lại toàn bộ lời thông báo hay màn hình cài resource.

- `app/ui/design_system.py`: palette và QSS dùng chung; tránh sửa font phụ đề/overlay toàn ứng dụng.
- `app/ui/icons.py`: SVG renderer/cache, trạng thái và accessibility/tooltip cho nút. Cache tách riêng khỏi thumbnail; key thumbnail gốc không đổi.
- `app/ui/assets/icons/`: 40 SVG, license ISC/MIT đầy đủ và manifest revision/hash. App chạy offline với asset đóng gói sẵn.
- Các lớp trang/toolbar vẫn sở hữu controls, API và kết nối gốc; bỏ các block QSS bị ghi đè và definition shuffle bị shadow từ trước.

Nguồn thiết kế kỹ thuật: [Qt QIcon](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QIcon.html), [Qt stylesheet reference](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-stylesheet-reference.html). Nguồn icon/giấy phép: [Lucide revision đã ghim](https://github.com/lucide-icons/lucide/tree/500620a2e8123f8d1db191538886dc0c223f69a9), [license](https://lucide.dev/license).

## Giữ chức năng: bằng chứng theo phạm vi

Baseline Git `4148c138c1e38f4959574caf925f1c86dbcca339`; snapshot 87 source gốc tại `restored-app-baseline.json`.

| Cổng kiểm tra | Kết quả |
| --- | --- |
| Hash mọi source ngoài UI | 61/61 giống baseline, gồm AI/ASR/translation, pipeline, download workers, thư viện, paths/config/startup/native orchestration |
| Source gốc không sửa | 73/87 file giống hash; chỉ 14 file UI gốc được chỉnh và thêm 2 module trình bày |
| API/signal UI gốc | Giữ chữ ký 399 function/method được capture và 55 signal |
| Kết nối Qt gốc | 189 call `.connect` có AST giống baseline, gồm kết nối bị lặp vốn có; không đổi listener/handler |
| Hàm UI ngoài allowlist trình bày | AST giống baseline; worker/model/editor timing, shortcut, playlist, routing, scan, window lifecycle được giữ |
| Qt behavior thực tế | Điều hướng 5 trang, compact/sidebar, button signals, seek/drag, volume/clamp, For You repeat/shuffle, click giữ exact media object, fullscreen, mini/normal round trip, settings keys, plain paste/clear link và appearance |
| Asset | SHA-256 theo manifest, license đi cùng app; render 40 icon ở DPR 1 / 1.5 / 2; disabled khác normal; thử resolver đường dẫn bundle namespace ngắn |

`tests/test_ui_refresh.py` dùng Qt thật, 12 bản ghi media giả, ảnh 640×360 sinh trong thư mục tạm và QSettings INI tạm. Native audio và model/downloader được thay bằng mock ở ranh giới dịch vụ để không chạy GPU/mạng hoặc ghi settings người dùng. Những mock này không xác nhận chức năng native/AI thật.

Lệnh đã chạy bằng venv Python **3.11.0**, PySide6 **6.10.1**, Windows, platform Qt **offscreen**:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

Unittest: **22 test hiện tại đạt; 11 module test refactor cũ skip rõ lý do**, tổng discovery 33. Các test cũ yêu cầu package bootstrap/media/infrastructure đã bị người dùng rollback. Test bodies và fixtures vẫn được giữ; skip không được tính là pass tính năng. Xem `tests/README.md`.

## Hiệu năng đã đo

Phép thử xác định, không dựa vào thời gian tường: sau warm-up, gọi `update_play_state` 200 lần xen kẽ play/pause. Mã gốc gọi `setStyleSheet` mỗi lần (200); bản mới **0 lần**, không thêm cache miss đọc SVG. Icon reuse cache; theme không bị parse lại trong đường update này. Đây là giảm thao tác UI trong đường cụ thể, không chứng minh FPS chung hay tốc độ AI/scan. Chưa có benchmark GPU/media thật hoặc thư viện lớn để tuyên bố app toàn bộ mượt hơn bao nhiêu.

## Ảnh đối chiếu

Ảnh dùng cùng fixture/font và viewport 1280×820. For You vốn tự maximize; chỉ trong preview override maximize để giữ viewport bằng nhau. Màn hình trống video không chứng minh decoder/video playback. Cover là ảnh giả phục vụ so layout.

| Màn hình | Gốc | Mới |
| --- | --- | --- |
| Home | [Ảnh gốc](ui/before/home.png) | [Ảnh mới](ui/after/home.png) |
| Library | [Ảnh gốc](ui/before/library.png) | [Ảnh mới](ui/after/library.png) |
| For You | [Ảnh gốc](ui/before/for-you.png) | [Ảnh mới](ui/after/for-you.png) |
| Download | [Ảnh gốc](ui/before/download.png) | [Ảnh mới](ui/after/download.png) |
| Settings | [Ảnh gốc](ui/before/settings.png) | [Ảnh mới](ui/after/settings.png) |
| Mini player | [Ảnh gốc](ui/before/mini-player.png) | [Ảnh mới](ui/after/mini-player.png) |
| Subtitle tools | [Ảnh gốc qua adapter](ui/before/subtitle-tools.png) | [Ảnh mới qua adapter](ui/after/subtitle-tools.png) |
| Subtitle table | [Ảnh gốc qua adapter](ui/before/subtitle-table.png) | [Ảnh mới qua adapter](ui/after/subtitle-table.png) |
| Media info | [Ảnh gốc](ui/before/media-info.png) | [Ảnh mới](ui/after/media-info.png) |

Tái tạo:

```powershell
.\venv\Scripts\python.exe tools/ui_preview.py --baseline --output docs/ui/before
.\venv\Scripts\python.exe tools/ui_preview.py --output docs/ui/after
```

`--baseline` đọc source Git gốc vào thư mục tạm, không checkout/ghi đè app hiện tại. Offscreen không tự enumerate font Windows nên tool đăng ký font có sẵn chỉ trong tiến trình preview.

## Phần chưa xác nhận

**Production SubtitleToolsDialog bị Windows native access violation khi bind `combo_lang.currentTextChanged` trong phép thử offscreen ở cả code gốc và code mới**. Đã đối chiếu bằng hai tiến trình riêng với faulthandler. Bản gốc dừng tại line 161; bản mới tại line 73 sau khi chuyển QSS ra module. Chưa xác định đây có xảy ra khi chạy Windows UI bình thường hoặc bản EXE đang dùng không. Không sửa MRO/lifecycle để chữa vội khi chưa tái hiện đúng môi trường người dùng.

Để review layout, tool tạo **adapter chỉ dành cho preview** đặt QDialog trước mixin và gọi chính `init_ui`/methods gốc. Adapter này không được dùng trong app; ảnh công cụ không tính là pass khởi tạo/lifecycle/worker. Vẫn cần xác nhận mở công cụ, undo/redo, import/export/snap, đồng bộ phụ đề và AI align/translate trên app thật. Nội dung timing/model/logic của chúng giữ source gốc.

Chờ thêm real-media playback qua các format, audio hotplug/SMTC, DPI Windows ở nhiều màn hình, thư viện lớn, GPU/AI/network/download và EXE portable. Không build/clean dist/storage, không tải model/media và không nâng dependency trong lượt UI này. Build hiện có `--add-data=app;app` nên chứa SVG/license; kiểm tra resolver không thay thế việc chạy EXE thật.

## Tiếp tục lâu dài

Giữ UI mới làm một phase dễ review. Các thay đổi cải thiện accuracy/AI/cache/scanning chỉ triển khai từng bước trong `ROADMAP.md` với số đo và dataset. UI chi tiết còn có thể nâng loading/empty state, thông báo và resource installer sau khi xác nhận parity thực tế. Giữ fixture gốc và bản EXE tốt để đối chiếu trước mỗi phase; không ghi đè snapshot gốc bằng source UI mới.
