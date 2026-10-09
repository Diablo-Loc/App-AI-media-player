# Rà soát toàn app sau chốt âm thanh — 04/10/2026

**Cập nhật sau audit:** người dùng đã cho phép sửa R1/R2. Phase metadata thật/đọc nền được triển khai và kiểm chứng riêng ở [MEDIA_INFO_FIX.md](MEDIA_INFO_FIX.md). Nội dung dưới giữ bằng chứng trạng thái trước sửa; R3/hook Qt và batch cache vẫn chưa thay đổi.

**Đối chiếu mới trong phase âm lượng/build:** media_index.json hiện có timestamp 17:35:02, sau audit/metadata phase nhưng trước snapshot volume phase 17:54:55. Chạy lại tool compare thấy 30/31 khớp baseline audit cũ; [saved-file-check](final-flow-review/saved-file-check.json) hiện phản ánh lần đối chiếu mới này. Không rollback file hiện tại. Kiểm tra focused với baseline dữ liệu hiện tại giữ 31/31 file; xem [VOLUME_AND_BUILD.md](VOLUME_AND_BUILD.md). Các số pass/hash bên dưới mô tả lượt audit ban đầu, không khẳng định index hiện tại phải trùng mốc đó.

## Kết luận

Luồng hiện hành tiếp tục đạt regression; **chưa có bằng chứng regression mới do commit audio `74787f8`** trong các kiểm tra đã chạy. Không thể chốt “không còn lỗi” vì popup Thông tin vẫn hiển thị thông số giả định và có đường gọi ffprobe đồng bộ trên GUI. Đây là hai điểm đã có từ baseline, được tái hiện trên code hiện tại. Nên sửa chung một phase nhỏ về metadata thật/chạy nền trước khi thêm tính năng lớn.

Hook xử lý lỗi trước khi Qt import thành công vẫn có NameError; normal entry import hiện thành công. Hook này được người dùng giữ ngoài phạm vi sửa ở đợt reliability nên lượt audit không tự sửa. Batch ghi thumbnail/library grid là cơ hội tối ưu cho thư viện lớn, chưa có phép đo native để gọi là nguyên nhân lag của mọi máy.

**Lượt này chỉ audit/probe/tài liệu, không sửa production, saved-data hoặc commit thêm.** Các thay đổi build/spec/requirements/xóa log và `docs/empty-subtitles/media/` của người dùng được giữ nguyên. Không chạy build, updater, cài dependency, tải model hoặc gọi API.

## Phạm vi và kiểm chứng mới

- Toàn cây `app/`: **114 file Python /20.281 dòng/928 functions**, AST parse và compile không lỗi, không import/chạy toàn bộ functions. Bao gồm các test/demo legacy hiện có; không xóa module do chưa thấy caller. [Inventory/hash](final-flow-review/inventory.json).
- Đọc/đối chiếu các đường active từ entry: lựa chọn/chuyển bài/full queue/search, volume/normalize/EQ/prefetch/fallback, UI/overlay/window adapters, scan/thumbnail, AI spawn/cancel, ASR/refinement/coverage/translation, empty/save/render/load/editor, download/title/editor shutdown. Source-gate không thay thế chạy từng hàm với mọi đầu vào.
- **295 tests =284 pass +11 historical skip**, 80,648 s ở DPI thường. [Log](final-flow-review/test-results.txt).
- **295 tests =284 pass +11 historical skip**, 79,050 s ở DPI 200%. [Log](final-flow-review/dpi-200-tests.txt). Hai suite chạy riêng; không cộng thành 568 tính năng độc lập. Các skip chỉ dành cho kiến trúc đã rollback.
- **19/19 source/hash/AST gates** trên checkout Git độc lập của index đã commit, 3,309 s: [log](final-flow-review/checkout-gates.txt). Không reset worktree/index và không recapture manifest.
- Import entry thật `run_app` ở subprocess với portable libs/bin hiện có: **ENTRY_IMPORT_OK, Qt 6.10.1**. [Log](final-flow-review/entry-import.txt). Chỉ import; không gọi `main`, không khẳng định full native launch/EXE từ phép thử này.
- **31/31 file dữ liệu/phụ đề giữ hash** trước/sau probes: [before](final-flow-review/saved-before.json), [check](final-flow-review/saved-file-check.json). Video dùng cho metadata cũng giữ source hash; không sửa media/model/settings.
- `git diff --check` kiểm tra sau audit; không stage/commit thêm. Production `app/` không có diff so với commit audio.

Test suite gồm FFmpeg media tổng hợp/Qt decoder muted/actual owned process termination và fault injection; provider/network/model dùng fixture khi phù hợp. Không chạy Whisper/NLLB GPU fresh hoặc gọi API thật lần này. Probe 8 video ×2 preset của commit audio còn hiệu lực theo source/hash gates và không được trình bày thành một probe mới trong audit này.

## Phát hiện đã tái hiện

### R1 — P2, chính xác: thông số Codec là chuỗi cố định

`app/ui/video_info_popup.py:190`, `VideoInfoPopup.update_info` chọn thông số chỉ theo extension. MP4/MKV/WEBM đều bị ghi H.264, 1920×1080, 60 FPS, AAC, 48 kHz và khoảng 320 kbps; các extension còn lại có thể bị coi là MP3/FLAC dù là WAV/AVI. Các chuỗi này không phải metadata đo được.

Đối chứng đọc-only bằng bin ffprobe trên **A Small Miracle(short).mp4**:

| Trường | Nguồn thật | Popup hiện tại |
| --- | --- | --- |
| Video codec | AV1 | H.264/AVC |
| Resolution/aspect | 1080×1080, 1:1 | 1920×1080, 16:9 |
| FPS | 25 | 60 |
| Audio bitrate | 128 kbps | khoảng 320 kbps |
| Sample rate | 44,1 kHz | 48 kHz |

Không làm hỏng âm thanh/video gốc, nhưng thông tin hiển thị sai. Function AST khớp baseline Git `4148c13`: lỗi đã có trước đợt UI/audio hiện hành. [Kết quả](final-flow-review/fault-probes.json), [công cụ](../tools/final_flow_faults.py).

Đề xuất: một ffprobe nền cho source gốc, trả các trường đúng hoặc “Chưa rõ” khi thiếu; không dùng số chất lượng giả định. Giữ media ID/schema, thứ tự tab/controls/description fallback và decoder/window owners. Kết quả cần source identity/signature, bỏ stale khi đổi bài; không đọc codec của file EQ cache rồi gán ngược thành thông số file gốc.

### R2 — P2, đáp ứng: đọc description có thể chặn GUI

`app/ui/video_info_popup.py:264`, `get_description_for_item` gọi `subprocess.run(... timeout=1)` trực tiếp trong `update_info` trước khi popup hiện. Có description/sidecar thì không vào nhánh này; file không có thông tin đó mới ffprobe trên GUI. Timeout giới hạn mỗi lần gọi, không làm lời gọi trở thành async.

Fault probe dùng method/widget production và fake ffprobe chờ 250 ms: `update_info` **251,300 ms**, timer GUI 10 ms **0 tick** trong lời gọi; không phải benchmark ổ đĩa thật và không tuyên bố playback luôn khựng. Function AST khớp baseline `4148c13`. Đề xuất gộp với R1: owned background worker/process, GUI commit, cache theo source context, hủy/latest/shutdown không chờ trong tương tác thường. Không tạo thêm player/audio/video owners.

### R3 — P2 có điều kiện, đã nằm ngoài phạm vi trước: hook startup

`app/run_app.py:85`, hook đăng ký trước import Qt nhưng dùng tên `QApplication` không guard. Probe tách riêng function, giả lập ImportError trước Qt: **NameError `QApplication is not defined`**, không tới `sys.__excepthook__` trong function. Normal entry import ở runtime hiện có đã đạt; probe này không chứng minh DLL đang thiếu.

Function AST khớp baseline `4148c13`, không phải audio regression. [AGENTS.md](../AGENTS.md) ở reliability phase ghi “protected saved subtitles and excluded Qt hook”; lượt audit giữ phạm vi đó. Sửa guard xử lý traceback là phase nhỏ riêng; không tự đổi Python/Qt/PATH/dependency hoặc gọi đó là giải pháp mọi lỗi QtGui DLL.

## Điểm có thể tối ưu tiếp, không bắt buộc gom vào R1/R2

- **Thumbnail DB writes**: `MediaLibrary.update_thumbnail_in_db` gọi `save()` cho từng thumbnail mới; `save()` serialize toàn bộ library. Probe 100 metadata dùng ThumbnailWorker/method thật, mock FFmpeg/save/sleep: **100 lần full save**, tương đương duyệt 10.000 entry để serialize. Đây là operation count, không là số đo disk/CPU/lag. Có thể batch/coalesce cache writes, flush ở complete/cancel/shutdown và giữ synchronous API/JSON/path/key cũ. Không gộp save dữ liệu do người dùng sửa vào batch disposable cache.
- **Library grid lớn**: vẫn tạo card theo batch rồi giữ card cho toàn danh sách; khác viewport pool của For You. Có thể profile/virtualize riêng khi thư viện hàng nghìn bài và đo được áp lực widget/paint. Không thay model/selection/order chỉ để giảm số file.
- **Native/GPU/network/EXE**: driver, nhiều thiết bị/DAC, native screen FPS, nghe A/B, Whisper timing/lyrics có human reference và bản xuất/update vẫn cần nghiệm thu riêng. Không kết luận mọi lyric chính xác/full hoặc mọi bài 128k nghe hay hơn từ unit tests.

## Search For You kiểm tra lại

Workload offline **10.000 metadata, 3 rounds**, thumbnail=None, viewport 1280×820; không preload ảnh/model/audio thật. [JSON](final-flow-review/foryou-10000.json), [log](final-flow-review/foryou-10000.txt).

| Median trên máy này | Giá trị |
| --- | --- |
| Initial load API | 25,047 ms |
| Filter submission | 0,035 ms |
| Filter async completion | 86,676 ms |
| Clear submission | 0,432 ms |
| Clear async completion | 93,075 ms |
| Clear tạo thêm card | 0 |
| Live rows sau cuộn | 8 |

Submission và completion được tách; completion không bao gồm debounce của gõ phím hoặc decode ảnh thật. Cuộn có 40 ms event pump chủ động nên không dùng elapsed đó làm native FPS. Regression full queue/shuffle/search-only view/clear/latest/spinner/two decoders tiếp tục đạt. Thư viện metadata lớn không biến thành 10.000 playlist widgets, nhưng đây không phải cam kết mọi máy/driver/file chạy không lag.

## Thứ tự nên làm

1. Sửa chung **Thông tin file đúng + đọc nền** (R1/R2), với worker ownership, source context, timeout/error/close/switch tests và exact gate adapter mới; giữ mọi chức năng phát/AI/sub/save.
2. Hook startup R3 cần quyết định riêng vì trước đó được loại khỏi scope; không âm thầm sửa trong audit.
3. Qua tính năng mới sau phase nhỏ này; batch cache/library grid chỉ làm khi có nhu cầu/dataset và benchmark phù hợp. Không cần tiếp tục thay DSP âm thanh theo cảm tính.
