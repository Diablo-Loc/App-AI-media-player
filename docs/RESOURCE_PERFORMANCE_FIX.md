# Tối ưu CPU/RAM/I/O giữ nguyên chức năng — 05/10/2026

Đã triển khai ba ưu tiên P1/P2/P3 của [audit toàn app](APP_PERFORMANCE_REVIEW.md).
Phạm vi production chỉ gồm bốn module hiện có và ba helper mới. Không nâng
dependency, đổi kiến trúc entry/import, build hoặc commit trong phase này.

## Thay đổi

| Phần | Cách tối ưu | Hợp đồng giữ nguyên |
| --- | --- | --- |
| Thumbnail DB | Worker cập nhật RAM ngay, checkpoint mỗi 20 path thay đổi hoặc sau 2 giây khi có hoạt động; flush trong `finally` | Ảnh/path/ID/schema và JSON cuối; API `update_thumbnail_in_db()` cũ vẫn ghi đồng bộ |
| Decode ảnh Home/Library | Queue visible dùng tối đa hai decoder; cancel ảnh ngoài viewport/recycled/resize, giữ worker đến completion | Cùng chất lượng/scale/aspect/DPR; không giảm độ phân giải thumbnail |
| Grid Library | Giữ toàn metadata, dựng lại và tái sử dụng card quanh viewport với một hàng dự phòng | Cùng card/title/date/click/search và toàn queue phát; không thay grid Home hoặc For You |

`thumbnail.cache_batch` dùng worker scan hiện có, không thêm timer/thread. Checkpoint
thất bại giữ dirty và hạn chế retry; complete/cancel/error đều đi qua flush cuối.
Save cũ vẫn có lock/snapshot/atomic replace và giữ API trả về cũ. Nếu mất điện hoặc
process bị kill trước checkpoint, chỉ path cache thumbnail chưa ghi có thể phải
khôi phục ở lần scan sau; JPEG đã tạo vẫn còn. Đây không phải dữ liệu phụ đề hay
chỉnh sửa người dùng. Không thể bảo đảm ghi được nếu ổ đĩa lỗi/hết chỗ.

`ui.library_thumbnail_queue` thuộc QApplication, xử lý completion trên GUI,
shutdown cancel rồi đợi pool kết thúc tại `aboutToQuit`. Worker đọc QImage;
QPixmap/cache/widget cập nhật trên GUI. Không chờ decoder ở tương tác thông
thường. Ảnh lỗi không được decode lại mỗi lần repaint; update/hide-show/context
mới cho phép retry. RAM key gồm path, signature file ảnh, mtime media, kích thước
đích và DPR; không đổi key/path cache lưu đĩa. Cache budget toàn cục giữ nguyên.

`ui.library_grid_view` thuộc LibraryPage. Render coalesced 16 ms, filter theo
chunk 500 metadata bằng single-shot timer; không polling khi idle. Map card chỉ
chứa widget đang realized; queue phát lấy toàn metadata. Search Library cũ có
đặc điểm `QGridLayout.addWidget()` đưa các item khớp về cuối thứ tự nội bộ.
Helper giữ đúng stable partition đó qua từng query, kể cả gõ nhanh rồi xóa;
không tự sửa thứ tự này trong phase hiệu năng. Search For You/full master queue,
shuffle, selected media và nguồn phát giữ nguyên.

## Phạm vi nguồn và dữ liệu

Module sửa: `core/media_library.py`, `thumbnail/thumbnail_workers.py`,
`ui/media_card.py`, `ui/main_window.py`. Helper mới: `thumbnail/cache_batch.py`,
`ui/library_thumbnail_queue.py`, `ui/library_grid_view.py`.

MainWindow chỉ thêm một import và năm adapter grid. Gỡ đúng các adapter này
phục hồi toàn AST MainWindow trước phase. Những method/API ngoài tài nguyên của
bốn module được đối chiếu với snapshot. Toàn source `app/` còn lại khớp baseline;
không thay Whisper, dịch, cue/timing/hiệu ứng sub, audio/DSP, downloader,
video/window/native owners hoặc saved-data load/save.

Đối chiếu sau kiểm thử: **821/821 file `storage/`, `output/`, `video/` giữ hash**,
không file mất/thay đổi/thêm trong lần kiểm tra này. Xem
[saved-final.json](resource-performance/saved-final.json).

Snapshot mới ở `resource-performance/original/` và `reviewed/`, có hash nguồn/helper
và patch riêng. Adapter exact-source phục hồi phase trước rồi chạy các gate lịch
sử; không recapture/ghi đè manifest cũ. Một gate effect đọc raw MainWindow được
đưa qua adapter mới; phép kiểm tra scope lịch sử vẫn giữ nguyên. Fixture Qt giữ
MainWindow module resident qua các context patch để tránh unload/reimport wrapper.

Khi chốt commit, gate inventory mới dùng manifest normalized được suy ra từ
original bytes đã xác minh lúc capture; chỉ chấp nhận Git đổi CRLF/LF, không
chấp nhận đổi nội dung. Archive raw/helper hashes và các manifest cũ giữ nguyên.
`python -m tools.check_resource_performance_checkout` kiểm tra đúng staged tree
trong checkout tạm với Git attributes thật; không ghi index/branch/worktree.

## Đo trước/sau

Python 3.11.0 hiện có, Windows, 20 logical CPU. Ba process Qt offscreen mới cho
mỗi phía; Library 1.000 metadata, viewport 1280×820, không ảnh/video/AI. Bản trước
chạy class MediaCard và ba method grid đã chụp trước sửa; bản sau chạy code mới.
Con số là trung vị, tính từ sau khi chuẩn bị metadata.

| Workload | Trước | Sau |
| --- | ---: | ---: |
| Card Library giữ ở viewport đầu | 1.000 | 25 |
| RSS tăng do grid | 121,18 MiB | 5,18 MiB |
| CPU time dựng grid | 875 ms | 15,625 ms |
| Số save cho 50 thumbnail/DB 1.000 item | 50 | 3 |
| Số record serialize trong workload cache | 50.000 | 3.000 |
| CPU time cập nhật cache | 406,25 ms | 31,25 ms |

Cache before/after cuối khớp từng byte ở cả ba lượt. Scroll bốn vị trí xa giữ
25–30 card, item cuối và queue 1.000 metadata đúng. Báo cáo gắn SHA của bảy file
production: [measurements-final.json](resource-performance/measurements-final.json).
Probe chạy temp-only, không scan/ghi thư viện thật hoặc tải mạng.

Đây là workload tổng hợp, không phải giảm RSS/CPU toàn app hay FPS khi phát video.
CPU timer Windows bị lượng tử hóa; sample 0 ms không có nghĩa không dùng CPU.
Chưa hạ cache budget vì chưa đo hit/eviction với ảnh thực tế. Ảnh trước/sau đã
kiểm tra bố cục trực quan; không pixel-identical (khác 24.031/1.049.600 pixel,
phân bố từ cột thứ hai do layout/rounding). Style, kích thước card và nội dung
giữ nguyên; không dùng kết quả này để chứng nhận native pixel parity.

## Kiểm chứng

- 21 test resource: batch/flush/cancel/error/retry/concurrent-save, Qt decode
  hai worker/shutdown, DPR/resize/stale-result, 10.000 metadata/bounded widget,
  click/search/clear/full queue và đối chiếu legacy/source.
- 58 kiểm tra resource/UI/For You ở DPI 200% đạt:
  [dpi-200-final.log](resource-performance/dpi-200-final.log).
- Full discovery: **417 test, 406 pass +11 historical skip**, 134,664 giây,
  không failure/error unittest: [unittest-final.log](resource-performance/unittest-final.log).
  `git diff --check` đạt. Fixture Qt còn cảnh báo GC hai uncollectable objects
  tại shutdown; kết quả không chứng nhận không có leak native.
- Khi người dùng yêu cầu gom commit các phase: **34 staged-checkout source
  gates đạt**, [commit-checkout-final.log](resource-performance/commit-checkout-final.log).
  Sửa gate mới chấp nhận riêng CRLF/LF; **21 resource tests chạy lại đạt**,
  [commit-resource-tests.log](resource-performance/commit-resource-tests.log).
  Code production đúng các hash của `measurements-final.json`; không đổi trong
  lúc chuẩn bị commit. Binary yt-dlp có sẵn được include theo baseline downloader
  để checkout khớp phiên bản đã kiểm chứng; không tải/cập nhật binary ở lượt này.
- Full native playback/GPU/FPS, ổ mạng chậm, nhiều màn hình và EXE vẫn là kiểm
  chứng phát hành riêng. Không kết luận app không thể có bug từ bộ test này.

Không còn thay đổi triển khai trong P1/P2/P3. Editor/sub/P4 cache budget và các
thay đổi thuật toán âm thanh/ASR không thuộc phase đã được duyệt này.
