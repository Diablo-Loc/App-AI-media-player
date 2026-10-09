# Hiệu ứng phụ đề tùy chọn — 04/10/2026

Người dùng yêu cầu một nhóm lớn dưới Tùy chọn khác trong cài đặt sub,
nhiều hiệu ứng bật/tắt được, giữ cách hiển thị gốc và chức năng cũ.

## Sử dụng

Mở cài đặt phụ đề trên playback bar, cuộn tới **Hiệu ứng phụ đề**.
Đánh dấu tiêu đề nhóm để bật; bỏ dấu để dùng renderer gốc. Nhóm mới mặc định
**tắt**, giữ cỡ chữ/màu/nền/viền/bóng và checkbox Fade gốc của người dùng.

| Mục | Lựa chọn |
| --- | --- |
| Chuyển động | Không; chữ rơi; trượt lên; trượt trái/phải; thu phóng; nảy nhẹ; mở từ giữa |
| Màu | Màu gốc; chuyển ngọc lam; gradient ngọc lam/hoàng hôn/đại dương; cầu vồng pastel |
| Bật riêng | Mờ nhẹ khi vào câu; ánh sáng viền; dải sáng lướt một lần |
| Độ dài | Nhanh 220 ms; vừa 320 ms; êm 480 ms |
| Xem thử | Câu mẫu dùng chính renderer, không đổi video đang phát |

Chuyển động cả câu giữ shaping/dấu Unicode, không trì hoãn từng chữ.
Chọn một kiểu chuyển động/màu để tránh xung đột, kết hợp ba công tắc phụ.
Không thêm karaoke giả theo từ khi chưa có mốc từng từ đáng tin cậy.
Mờ nhẹ mới áp dụng phần chữ đầu câu; **Hiệu ứng Mờ dần (Fade)** hiện có
vẫn điều khiển hiện/ẩn toàn khung. Đặt lại trả nhóm mới về tắt cùng defaults cũ.

## Kiến trúc và bảo toàn

- `ui.subtitle_effects`: validated options, một QVariantAnimation hữu hạn,
  renderer. `ui.subtitle_effects_panel`: controls và preview. Không thêm worker,
  decoder, nguồn video/audio, framework hay dependency.
- Ba production sources hiện có: MainWindow thêm import + một install
  statement; SubtitleLayer thêm engine/sync/clear/painter hooks; SettingsPanel
  thêm group và vùng cuộn, giới hạn popup trong available screen.
- Cue identity gồm index/start/end/text, giữ câu lặp. Cùng câu không restart;
  tua vào giữa câu hiện đủ; tua ngược đầu câu dùng offset media. Câu ngắn
  rút hiệu ứng còn tối đa nửa duration, không đổi biên hoặc khoảng nghỉ.
- Pause/resume/rate theo player; hide/close/gap/OFF/load-empty dừng animation.
  Guard video/editor/dialog/mini/activation/chuyển nguồn vẫn nguyên. Giữ
  flags/parent/owner/drag/lock, 50 ms lead/80 ms tail và fade 220 ms OutCubic.
- Path gốc vẫn cache theo text/size. Màu/bóng/viền/ánh sáng mới cache raster
  theo path/style/DPR: một sprite tối đa 2 triệu pixel (8 MB buffer), quá lớn
  vẽ trực tiếp. Đổi kiểu/tắt giải phóng sprite, không cache mỗi frame/playlist.
  Gradient tĩnh không có timer; shimmer/chuyển màu chỉ chạy ở đầu câu.
- Thêm `appearance.subtitle_effects` qua save API hiện có khi người dùng
  chỉnh. Không startup rewrite/migration, không sửa subtitle JSON/ASS/SRT/LRC,
  cue schema/IDs/timing/grouping/ASR/dịch/cache.
- Build hiện có đã chứa app và QtCore/Gui/Widgets; không cần dependency mới.
  Không build/commit hoặc chỉnh script đóng gói trong phase.

## Kiểm chứng

18 regression mới: OFF so pixel/cues/visibility với source trước phase;
48 cặp chuyển động/màu qua nhiều frame; Unicode/geometry/câu lặp/seek/cue
ngắn/pause/rate/empty; raster reuse/invalidation/bounds; JSON thật ở storage
tạm; editor/startup/reset; scroll; không setSource/setPosition.

Exact snapshots mới phục hồi phase trước cho source gates; manifest cũ giữ
nguyên. Raw baseline 117 Python sources vẫn giữ; canonical hashes được suy
ra từ bytes **đã khớp raw baseline**, chỉ cho phép LF/CRLF của Git checkout.
Bỏ đúng hook mới thì toàn module SubtitleLayer khớp source trước phase.

Một fixture ban đầu gắn MagicMock vào phương thức QObject `load_config`
làm runner native crash ở connect volume cũ, tái hiện trong process mới.
Fixture đã dùng Python method thật seed JSON rồi gọi loader gốc và chạy đạt;
không sửa volume/Qt của app để che lỗi test. Giữ
[log](subtitle-effects/fixture-native-crash.txt). Không coi đây là bằng chứng
chữa lỗi native khác đã ghi ở phase import trước.

Kết quả cuối: [full](subtitle-effects/full-tests.txt),
[focused](subtitle-effects/focused-tests.txt), [DPI 200%](subtitle-effects/dpi2-tests.txt),
[checkout](subtitle-effects/checkout-tests.txt), [saved hashes](subtitle-effects/saved-check.json),
[manifest](subtitle-effects/reviewed-sources.json), [diff](subtitle-effects/reviewed.patch).

| Kiểm tra cuối | Kết quả |
| --- | --- |
| Full discovery với faulthandler | 354 total: **343 pass +11 historical skip**, 98,539 s |
| DPI 200% | **44 pass**, 13,288 s |
| Disposable Git checkout/source gates | **26 pass**, 4,762 s |
| Saved media/subtitle/settings/cache/export | **814/814 hashes unchanged** |
| `git diff --check` | Đạt; Git index người dùng giữ nguyên, không stage/commit |

Đo raster cô lập 533×44 logical px, Windows/Python 3.11/Qt offscreen/DPR 1,
500 lần/preset sau warm-up: một cached path/preset. Median OFF 7,15 ms;
chữ rơi + mint 0,04 ms; nảy + pastel + glow + shimmer 1,09 ms, p95 1,49 ms.
Đây là chi phí `render()` fixture, không phải FPS/CPU toàn app hoặc native GPU;
cache build frame đầu/video thật cần nghiệm thu riêng.
[Probe](subtitle-effects/render-probe.json).

Ảnh: [group](subtitle-effects/screenshots/settings-effects.png),
[settings](subtitle-effects/screenshots/settings-top.png),
[frames](subtitle-effects/screenshots/effect-frames.png). Font CJK có sẵn chỉ
đăng ký trong preview offscreen; không đổi font/dependency production.
Native playback, nhiều màn hình và EXE cần kiểm tra trên máy sử dụng.

Qt API: [QVariantAnimation](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QVariantAnimation.html),
[QPainter](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainter.html),
[QScrollArea](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QScrollArea.html).

## Mở rộng sau phase cơ sở

Hiệu ứng hạt/phi tiêu theo câu, 9 bộ mẫu và thêm chuyển cảnh được triển khai
riêng tại [SUBTITLE_PARTICLES.md](SUBTITLE_PARTICLES.md). Các kết quả/snapshot
phase cơ sở phía trên giữ nguyên; giới hạn chỉ entry animation được mở rộng
theo yêu cầu mới cho các style hạt tùy chọn, không thay đổi renderer OFF.
