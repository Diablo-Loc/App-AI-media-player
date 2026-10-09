# Rà soát CPU, RAM và I/O — 05/10/2026

**Cập nhật sau audit:** người dùng đã duyệt và đã triển khai P1/P2/P3.
Xem [RESOURCE_PERFORMANCE_FIX.md](RESOURCE_PERFORMANCE_FIX.md) cho code, số đo
before/after và kiểm chứng cuối. Nội dung/số đo dưới đây giữ mốc audit trước sửa;
P4/P5 chưa triển khai.

Đã quét **122 file Python, 21.795 dòng, 1.018 hàm** trong toàn bộ `app/`,
kể cả tám file ví dụ/test bị Git ignore. AST và compile trong RAM không phát hiện
lỗi cú pháp. Đã rà luồng khởi động → controller → playback/library/For You →
worker, cùng các điểm timer, thread, subprocess, decode ảnh và persistence.
Inventory ghi từng file/import/vị trí gọi cần xem trong
[`performance-audit-2026-10-05/sources-before.json`](performance-audit-2026-10-05/sources-before.json).

**Có cơ hội tối ưu cụ thể; chưa thay đổi production trong lượt này.** Không đổi
logic phát, playlist, UI, âm thanh, Whisper, lyric/timing/hiệu ứng, import hoặc
schema. Không chạy model, tải mạng, cập nhật yt-dlp, đóng gói hay commit.
Đợt probe đầu đối chiếu 819/819 file trong `storage/`, `output/`, `video/`
khớp SHA-256. Kiểm tra cuối có thay đổi cache/index và file mới trong lúc audit,
được ghi riêng ở cuối báo cáo; không coi cả thư mục là bất biến suốt phiên.
Snapshot mới độc lập; không ghi lại manifest của các phase trước.

## Những điểm nên làm tiếp

| Ưu tiên | Vị trí và bằng chứng | Hướng giữ nguyên chức năng | Trạng thái |
| --- | --- | --- | --- |
| P1 | `thumbnail/thumbnail_workers.py` gọi `MediaLibrary.update_thumbnail_in_db()` cho từng ảnh; hàm này `save()` toàn DB | Gom ghi riêng cache thumbnail bằng owner có checkpoint; flush khi xong/hủy/lỗi/shutdown; giữ API đồng bộ cho caller cũ | Đã đo, chưa sửa |
| P2 | `ContentController.switch_to_library()` nạp toàn bộ; `MainWindow.load_next_batch()` tạo và giữ mọi `MediaCard`, dù chia batch 12 | Grid tái sử dụng card quanh viewport, tương tự nguyên tắc For You; metadata vẫn đầy đủ | Đã đo, chưa sửa |
| P3 | `MediaCard.thread_pool` không đặt giới hạn riêng; máy đo cho phép 20 decoder, trong khi For You giới hạn 2 | Queue ảnh visible có giới hạn riêng, cancellation/completion/shutdown và QImage worker → QPixmap GUI; giữ chất lượng ảnh | Rà nguồn + đo giới hạn; chưa đo lúc cuộn với ảnh thật |
| P4 | QPixmapCache toàn cục được đặt 100 MiB khi import MediaCard, rồi 200 MiB khi tạo For You; card giữ pixmap riêng | Một owner cấu hình ngân sách, đo cache-hit/eviction/RSS trước khi chọn hạn mức | Chưa đủ bằng chứng để hạ cache |
| P5 | Editor `_sync_active_sub_for_time()` đọc/format/parse từng row mỗi position callback; còn timer 200 ms khi dialog mở | Nếu sau này cần: cache đúng giá trị thời gian đang hiển thị, invalidation theo edit/undo/import; giữ first-match và inclusive endpoints | Rà nguồn; hoãn theo yêu cầu chốt sub |

P1 chủ yếu giảm CPU serialize và ghi đĩa lúc có ảnh mới. P2 chủ yếu giảm RAM,
khởi tạo widget, reflow và chi phí dựng lại khi vào Library. P3 nhằm giảm spike
khi ảnh đang decode; không thể kết luận giảm bao nhiêu CPU từ giới hạn thread.
Các điểm này không phải bằng chứng bài nhỏ hiện tại đang chạy lỗi.

### P1: ghi cache thumbnail

Probe dùng **hàm production thật** với DB giả 1.000 metadata, tạo 50 đường dẫn
thumbnail, ba lượt; JSON chỉ ghi trong thư mục tạm riêng:

- 50 lần save → 50.000 record serialize → 9.446.820 byte ghi xuống đĩa mỗi lượt.
- Median: **1.329,56 ms wall**, **359,38 ms CPU** cho 50 update.
- Replay tham khảo gom mutation rồi save một lần: median **26,61 ms wall**,
  **15,63 ms CPU**, JSON cuối khớp từng byte cả ba lượt.

Replay một lần save **chưa phải implementation được duyệt**: chưa chứng minh
recovery, dữ liệu trung gian khi crash, cancellation hay save concurrency.
Không lấy tỉ lệ này làm cam kết app tổng thể nhanh lên tương ứng. Thumbnail
được tạo tuần tự hiện tại; chi phí FFmpeg không nằm trong probe JSON này.

### P2: grid thư viện

Chạy phương thức `MainWindow.load_next_batch()` và `MediaCard` thật trong process
Qt offscreen riêng, ba lượt mỗi kích thước, không có thumbnail:

| Số bài | Card giữ trong grid | QWidget bên dưới container | RAM RSS tăng, median | CPU dựng card, median |
| --- | --- | --- | --- | --- |
| 100 | 100 | 400 | 12,23 MiB | 46,88 ms |
| 500 | 500 | 2.000 | 55,29 MiB | 187,50 ms |
| 1.000 | 1.000 | 4.000 | 107,61 MiB | 343,75 ms |

Các khoảng nghỉ batch 10 ms được bỏ qua trong probe để đo công việc dựng card;
đây **không phải thời gian chờ UI hoàn tất**. Không vẽ màn hình native, không
phát video, không đo cuộn/FPS, và RSS delta chưa gồm metadata đã tạo trước đó
hay ảnh/cache/decoder. Không ngoại suy thành con số RAM chắc chắn cho 10.000 bài.

Home chỉ chọn tối đa 20 bài; For You dùng cơ chế khác. Vấn đề tạo tất cả card
ở đây thuộc **Library**, không đồng nghĩa các trang đều dùng 108 MiB/1.000 bài.

## Những phần đã có giới hạn hợp lý

| Phần | Luồng hiện hành | Kết luận audit |
| --- | --- | --- |
| For You | Widget quanh viewport, search 500 metadata/chunk, debounce, spinner visible; hai decoder ảnh | Giữ; không dựng toàn bộ ảnh/card khi search |
| Quét thư mục | Owned snapshot QThread, latest request, GUI commit và CacheWriter riêng | Đã tách công việc nặng khỏi GUI; cải thiện grid riêng |
| Metadata popup | Một latest worker, timeout ffprobe, RAM LRU 32 entry với signature/context | Giữ, không quay lại probe đồng bộ GUI |
| AI/Whisper/dịch | AI chạy spawn process; queue đọc có timeout, NLLB chỉ nạp khi cache miss; cache dịch flush cuối | Không giảm beam/retry/model hay giữ model trong GUI để tiết kiệm thời gian |
| Audio OFF | Giữ đường phát gốc; không chuẩn bị DSP khi profile tắt | Giữ âm thanh/player cũ |
| Normalization/EQ ON | Một owned worker, FFmpeg `threads=1`/`filter_threads=1`, measurement/cache và prefetch một bài có budget | Chi phí phát sinh theo tính năng; không giảm độ chính xác đo hoặc chất lượng codec |
| Volume | Ghi coalesced 250 ms; gain ramp hữu hạn và user volume riêng | Không cần thêm polling hoặc ghi mỗi frame |
| Download | Tải tuần tự trong worker, đọc log pipe blocking; tiến trình có owner | Không thấy busy-spin trong vòng đọc log; không tăng download concurrency |
| Subtitle effects | OFF gốc; animation hữu hạn, timer 33 ms có guard visible/playing/cue; sprite/marks/tile có budget | Giữ nguyên phần vừa chốt; không hạ FPS/chất lượng hiệu ứng |
| Window/sidebar/loading | Timer chủ yếu single-shot/coalesced; spinner stop khi hide | Không có căn cứ đổi hàng loạt timer |

Probe **For You hiện tại**: 10.000 metadata giả, khung 1280×820, ba process
offscreen riêng. Chỉ **11 hàng** realized; median RAM danh sách tăng **4,89 MiB**
(không tính metadata tạo trước đó/ảnh/video), median submission load **29,70 ms**.
Search `Track 123` trả đúng 11 bài; full playback order vẫn 10.000; clear phục hồi
exact toàn danh sách cả ba lượt. Median search completion sau setText khoảng
**423,89 ms**, gồm debounce 300 ms và timer xử lý; không phải block GUI 424 ms.
Không dùng phép đo này để cam kết native playback không giật trong mọi tải.

### PCM native: có công việc chưa dùng, chưa nên sửa vội

`SystemMediaManager._native_audio_callback()` copy PCM vào NumPy, gửi qua queue
Qt; MainWindow nối vào `process_realtime_audio()`, hiện chỉ `pass`. Queue audio
đã giới hạn hai buffer. Có thể đề xuất bật riêng PCM khi thực sự có visualizer,
nhưng **không được tắt engine/SMTC hoặc thay đường âm thanh** như một sửa phụ.

Probe buffer giả 480 frame stereo, 48 kHz: 10.000 callback copy tổng 38,4 MB,
median khoảng 19,99 ms wall. Đây chỉ là Python callback, **không đo WASAPI,
DLL hoặc dispatch Qt**; CPU timer ghi 0 ở lượt ngắn không có nghĩa không tốn CPU.
Chưa có bằng chứng đây là bottleneck; xếp sau cache/grid/ảnh, giữ nguyên lúc này.
Trong cây app chỉ có DLL native, không có nguồn C++ để audit nội bộ engine.

### Cache ảnh: ngân sách khác bộ nhớ đã dùng

200 MiB của QPixmapCache là **trần**, không phải allocation sẵn. RSS còn gồm
pixmap QLabel giữ, QWidget, decoder native, NumPy và AI process con. Hạ cache
tùy tiện có thể tăng decode/đọc đĩa khi cuộn. Cache-key MediaCard hiện chỉ có
path/media mtime; khác với For You có kiểm tra kích thước/DPR. Cần test riêng
resize/DPI/file ảnh đổi khi làm P3/P4; không đổi cache-key lưu đĩa hoặc giảm
độ nét ảnh để lấy kết quả RAM đẹp hơn.

## Roadmap bảo toàn app

1. **Gom ghi cache thumbnail**: giữ synchronous API; cache cùng path/schema;
   kiểm tra số lần ghi, JSON cuối, mutex/save đồng thời, lỗi/cancel/shutdown.
2. **Giới hạn decoder Library**: latest/visible queue và completion ownership;
   ảnh rõ như cũ, stale result không áp sai card, đóng app không mất worker owner.
3. **Virtualize grid Library**: giữ giao diện, ID/order/search/select/highlight,
   click/Next/Previous/full playlist, Home random20 và responsive/DPI. Đo số
   widget/RSS/CPU và video heartbeat trước/sau với ảnh thật.
4. **Nghiệm thu native**: cùng video, kích thước cửa sổ, số ảnh và trạng thái
   audio/sub; idle/play/scroll/search/đổi tab/minimize; đo cả process con/GPU.
   Sau đó mới quyết định ngân sách pixmap hoặc PCM gate.

Không đổi sang framework mới, không nâng dependencies, không rewrite kiến
trúc cả app và không động vào lyric/Whisper/timing như phần tối ưu phụ.

## Bằng chứng và giới hạn

- Windows build 22631, Python **3.11.0** của venv dự án, 20 logical CPU;
  Qt offscreen, dữ liệu tổng hợp, ba lượt mỗi workload.
- [`measurements.json`](performance-audit-2026-10-05/measurements.json): chín
  grid samples, ba cache samples, inventory và source/data hash invariance.
- [`playlist-reference.json`](performance-audit-2026-10-05/playlist-reference.json):
  ba For You/search/clear probes hiện hành, không ghi lại benchmark cũ.
- [`native-copy-reference.json`](performance-audit-2026-10-05/native-copy-reference.json):
  callback giả, không khởi tạo DLL/audio engine.
- [`final-verification.json`](performance-audit-2026-10-05/final-verification.json):
  toàn 122 Python vẫn khớp source trước audit; 49 file phụ đề/source/output/video
  đã tồn tại (không gồm index) vẫn khớp hash. Trong toàn storage/output/video,
  812/819 file ban đầu khớp ở kiểm tra cuối; sáu file cache audio đã biến mất,
  index đổi và tám file mới xuất hiện (cache audio, JSON/ASS/SRT/LRC). Không
  rollback chúng. Các probe này không gọi AI/audio preparation hoặc ghi vào
  storage thật; chưa xác định process đã thực hiện những cập nhật quan sát này.
- [`tools/audit_app_performance.py`](../tools/audit_app_performance.py): script
  read-only với temp cache và process riêng; không chạy app thật. Báo cáo không
  tự overwrite snapshot đã tồn tại.
- Không chạy lại full regression trong lượt audit không đổi production này.
  AST/compile/probe/hash **không phải** full feature parity hoặc zero-bug proof.
  Native/GPU/network/EXE, CPU% khi phát thật và peak RSS lúc AI chạy còn cần đo.
- Môi trường máy không được khóa thành benchmark yên tĩnh; các thay đổi dữ liệu
  quan sát được cho thấy cần thận trọng khi so wall/CPU giữa các lần chạy.
  Số card, số save, số record serialize và JSON cuối là bằng chứng ít phụ thuộc
  tải máy hơn các số thời gian/RSS này.

Kết quả bàn giao: **báo cáo + probe**, chưa triển khai P1–P5. Toàn bộ code
production được chụp trong audit giữ nguyên; những sửa worktree có từ trước
không bị rollback, stage hoặc commit.
