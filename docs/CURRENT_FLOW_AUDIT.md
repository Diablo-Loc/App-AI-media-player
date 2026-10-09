# Rà soát luồng hiện hành — 04/10/2026

Cập nhật sau audit: A1–A4/A6 đã được người dùng cho phép sửa và hoàn thành theo kiểm chứng trong [RELIABILITY_FIX.md](RELIABILITY_FIX.md); hook Qt ngoài phạm vi. Phần bên dưới là **chứng cứ trước-fix**, không phải kết luận các lỗi đó vẫn tồn tại ở implementation mới.

## Kết luận

**Có các nhánh lỗi cần sửa; chưa nên chốt “app đã tối ưu xong” để chuyển hoàn toàn sang thêm tính năng.** Ưu tiên an toàn lưu phụ đề, tính đầy đủ của bản dịch, rồi việc chờ worker/quét thư mục trên GUI. App vẫn có thể chạy tốt khi xử lý thành công; probe chủ động đưa vào lỗi ghi, lỗi dịch và cleanup chậm để kiểm tra nhánh biên.

Lượt này chỉ audit, thêm công cụ/chứng cứ/tài liệu. **Không sửa production code, ASR/grouping/timing, UI, model, môi trường hoặc dữ liệu đã lưu; không commit.**

Các lỗi chính không phải bằng chứng UI mới phá luồng: 12 function AST liên quan khớp baseline Git `4148c138c1e38f4959574caf925f1c86dbcca339`. Lỗi lưu JSON mới/ASS cũ được tái hiện cả trên manager hiện tại và manager nguyên bản từ Git. Các source gates của từng phase mới tiếp tục đạt trong full suite. Điều này không chứng minh mọi đường thực thi toàn app đều tương đương.

## Phạm vi và chứng cứ

- Kiểm kê/parse AST/import/function/hash/compile **103 file Python / 18.002 dòng**, bao gồm 8 file trong `app/test/`; không import hoặc chạy toàn cây. Không lỗi cú pháp. Đây là kiểm tra tĩnh toàn cây, không phải chạy từng hàm với mọi đầu vào.
- Rà các đường đang được entry point lắp ghép: startup, chọn bài/thư mục, library/thumbnail, AIController/AIWorker/spawn, ASR/refinement/coverage/translation, save/render/load/editor và điểm hủy/đóng worker. Đối chiếu docs/source gates For You/UI/lyric.
- Fault probes dùng production functions/methods, thư mục tạm và mocks tại ranh giới dịch vụ. Không gọi mạng/model/decoder thật. GUI probe dùng QCoreApplication/QThread/QTimer thật, cleanup chậm do fixture tạo ra.
- Full discovery: **170 test, 159 pass +11 historical skip**, 26,827 s, Python 3.11 môi trường dự án. Skip không tính là pass tính năng; các test đó đòi kiến trúc đã rollback.
- **31 file JSON/ASS/SRT/LRC** trong `storage/`, `output/`, `video/` giữ hash trước/sau các fault probes. Không ghi đè phụ đề thật.
- `git diff --check` đạt. Không build/updater/download hoặc đổi dependency.

Chứng cứ: [công cụ chạy lại](../tools/current_flow_audit.py), [inventory/hash/AST/probes](current-flow-audit/probe-results.json), [probe log](current-flow-audit/probe-log.txt), [unittest log](current-flow-audit/test-results.txt).

## Phát hiện cần sửa

### A1 — P1: lưu phụ đề dở dang và editor báo thành công khi lưu thất bại

Nguồn: `app/core/subtitle_manager.py:174,228,289,361`; `app/ui/subs_ui/subtitle_dialog_logic.py:840,887,905`.

`save_segments` cập nhật index, ghi JSON trực tiếp, rồi render ASS. Có phụ đề cũ + lần tạo lại render False: **JSON mới, ASS cũ, save trả None nhưng request sau đó vẫn READY**. Probe manager nguyên bản từ Git cũng cho cùng kết quả.

`_save_json_file` mở bằng `w`. Fault probe ném OSError ở thao tác ghi: trả False nhưng file hợp lệ trước đó đã thành rỗng. Đây là tình huống tổng hợp, không phải kết luận ổ đĩa người dùng đang lỗi.

Editor bỏ qua kết quả save/render: giả lập ghi thất bại và render False, JSON không thay đổi nhưng editor vẫn báo “Thành công” rồi accept. `save_raw_data` nhánh dict cũng không chuyển kết quả ghi về caller.

**Đề xuất:** ghi file tạm/replace an toàn; chuẩn bị/kiểm tra JSON và ASS trước khi publish, có recovery/rollback nếu publish một phần hoặc process bị ngắt. Giữ JSON là nguồn chuẩn, schema/ID/path/index cũ. Không coi ASS cũ là bản render mới sau lỗi. Chỉ báo lưu thành công sau xác nhận. Test file cũ + lỗi write/replace/render + empty result; không migration toàn kho.

### A2 — P2: bản dịch lỗi/thiếu vẫn được coi là hoàn tất

Nguồn: `app/translate/pipeline.py:99,137,199`; `app/translate/cache.py:41,60`; `app/translate/online_logic.py:163,199`; `app/ai/pipeline.py:363`.

- Local batch ném lỗi → trả chuỗi rỗng → cache `vi: ""`. Lần thử tiếp với translator khỏe vẫn lấy rỗng, **healthy batch calls = 0**.
- Response local ngắn không được kiểm tra cardinality. Probe 2 dòng đầu vào/1 dòng trả về vẫn được chấp nhận; zip bỏ dòng còn thiếu. Nhiều batch có thể lệch mapping nếu thiếu phần tử, nhưng audit chỉ tái hiện case 2→1, chưa thử model thật.
- Online response sai định dạng hoặc chỉ có một ID hợp lệ vẫn trả list truthy. Probe dịch **0/2 và 1/2** nhưng orchestrator chỉ kiểm tra `if result`, nên không đi vào fallback hiện có.

**Đề xuất:** kiểm tra cardinality/ID/coverage; phân biệt lỗi/rỗng với bản dịch hợp lệ; không cache lỗi như thành công; retry/fallback những dòng thiếu theo thứ tự provider cũ. Giữ lời/timing gốc, prompts/model/API keys. Đọc cache cũ tương thích, xử lý entry lỗi lúc dùng thay vì xóa toàn bộ hoặc ghi lại subtitle cũ.

### A3 — P2: cleaner nhánh dịch có thể cắt nguồn lặp hợp lệ

Nguồn: `app/translate/pipeline.py:37,111`.

`run_safe_batch` gọi cleaner trên **đầu vào**, không chỉ output model. Probe `Stay with me` lặp 4 lần bị đổi thành `Stay with me Stay...` trước khi dịch vì diversity threshold. Lời gốc/top vẫn còn; đây là tầng dịch, khác với bộ lọc ASR/refinement vừa kiểm chứng. Không có chứng cứ mọi điệp khúc 2–3 câu có timing riêng bị xóa.

**Đề xuất:** bảo toàn nguồn đã được chấp nhận; tách input hygiene khỏi chống runaway output. Có fixtures lặp hợp lệ và hallucination; không đơn giản bỏ toàn bộ chống spam. Đây là thay đổi chất lượng có chủ đích, cần patch riêng, không đổi heuristic trong audit.

### A4 — P2: còn đường khóa GUI ngoài search For You

Nguồn: `app/control/ai_controller.py:99`; `app/worker.py:173`; `app/control/app_controller.py:61,145,167`; `app/ui/main_window.py:1680,1711`; `app/core/media_library.py:108`; `app/thumbnail/thumbnail_workers.py:42`.

`AIController.start` gọi worker cũ `stop`, bên trong gọi `wait` không timeout. Đổi sang bài cần AI/force regenerate khi worker cũ còn chạy có thể chặn GUI. Probe cleanup tổng hợp 250 ms: start **280,05 ms**, timer GUI **0 tick** trong lời gọi. Đây là bằng chứng đường chờ; **không phải số đo cleanup Whisper thật** hay lag toàn app. Cancel riêng chỉ đặt cờ. Chờ worker lúc shutdown là cần thiết.

`MainWindow.load_folder_content` gọi scan recursive/ffprobe đồng bộ trên GUI, folder watcher gọi lại đường này. Restart thumbnail scanner cũng chờ worker cũ; cờ không ngắt ngay FFmpeg đang chạy. Các điểm scan/thumbnail này là source-level evidence, chưa benchmark thực trong audit.

**Đề xuất:** orchestration job/scan không block; giữ worker đến finished, identity chống stale results, chạy job mới nhất. Scan bằng owned worker/snapshot, publish GUI; giữ synchronous service API cho caller cũ. Test cancel/switch/error/shutdown, cold/hot scan và playback đồng thời. Không đổi AI spawn, playlist order hoặc native/video lifecycle.

Search/clear/cuộn For You có viewport/chunk/two-decoder riêng và regression hiện hành đạt; không đồng nghĩa scan/grid ở mọi trang đã tối ưu.

### A5 — P2: exception hook startup tự ném NameError khi Qt import lỗi

Nguồn: `app/run_app.py:80,87,90`.

Hook đăng ký trước import Qt nhưng dùng `QApplication` không guard. Probe khi tên Qt chưa tồn tại: NameError `QApplication is not defined`, không tới default hook. Khớp nhánh stack trace người dùng từng gửi.

**Đề xuất:** giữ log/traceback gốc khi Qt chưa sẵn sàng, chỉ dùng QMessageBox khi có thể. Sửa hook không chữa nguyên nhân QtGui DLL thiếu; launch bằng interpreter đúng/native/EXE phải xác minh riêng. Không tự nâng dependency hoặc thay PATH theo giả định.

### A6 — P2, source-level: teardown download/editor worker cần kiểm chứng thêm

Nguồn: `app/ui/main_window.py:383`; `app/ui/pages/download.py:485,569`; `app/download_core/download_worker.py:57,269`; `app/ui/subs_ui/subtitle_dialog_logic.py:119,752,977`.

MainWindow close dừng AI/thumbnail, chưa có đường stop/join rõ cho download/title workers. Download stop terminate `self.process`, còn tiến trình cập nhật `yt-dlp -U` giữ ở biến local `update_proc`. Editor close dừng timer/disconnect UI, chưa có cơ chế cancel/giữ owner rõ đến khi align/translation worker hoàn tất.

Đây là khoảng trống source, **chưa tái hiện crash thực tế**. Cần process fixture chậm và shutdown probe riêng; giữ references đến finished, stop owned subprocess và đợi owned workers lúc shutdown. Không dùng terminate QThread/global cleanup để che lỗi. Không kết luận app luôn crash khi đóng.

## Tối ưu sau các lỗi trên

1. **Batch thumbnail cache:** mỗi update gọi save toàn DB. Probe **1.000 metadata +100 update =100 whole-DB writes /100.000 records chuẩn bị serialize**. Đây là operation count, không phải I/O benchmark. Batch/flush completion/cancel/shutdown, snapshot đồng bộ; user-edited metadata vẫn durable, ID/cache keys/quality không đổi.
2. **Lazy NLLB sau cache lookup:** hiện `get_translator` trước khi biết có miss. Probe all-cache-hit vẫn gọi initializer một lần dù không dịch. Chuyển load đến miss, giữ device/model/fallback. Chưa đo tiết kiệm RAM/giây vì không nạp model.
3. **Tách trách nhiệm có adapters:** giữ PySide6 và các owner hiện có; ưu tiên orchestration scan/job/save sau regression tests. Không áp lại refactor cũ. Tách file không tự tăng tốc.

## Module phụ và giới hạn

Entry point dùng **AIController**, không dùng JobManager trong `app/job/` hoặc AIProcessManager. Module phụ còn API/signals lệch: JobState thiếu CANCELLED; JobManager sentinel/queue join cần sửa nếu sử dụng lại; AIProcessManager nối QThread finished với handler nhận payload. Không đổi composition để vô tình đưa chúng vào production. Static references không chứng minh mọi dynamic consumer bên ngoài repo đều vắng mặt.

Native callback có copy audio trước queue và close guard trong source; DLL/ABI/callback timing không được chạy trong audit. ASR/phraser vẫn có giới hạn thiếu punctuation/pause/hallucination có timing hợp lý; captured replay không thay thế human ground truth. Không phục hồi timestamp phase đã rollback. GPU/media/network/native/EXE/update end-to-end còn chờ.

## Thứ tự nên làm

1. An toàn save/editor **A1**: giữ file cũ khi write/render/replace lỗi.
2. Độ đầy đủ dịch **A2–A3**: mapping/ID, cache lỗi, nguồn lặp, retry/fallback.
3. Worker/scan/lifecycle **A4, A6**, batch cache/lazy model: đo và giữ ownership.
4. Startup hook **A5** có thể là patch nhỏ riêng, rồi kiểm tra launch/native/EXE.

Sau từng phase chạy lại gates/full suite và validation thực tế theo phạm vi rồi chốt mốc ổn định. Có thể tạo checkpoint hiện tại với giới hạn rõ, nhưng audit không đề nghị commit mang nghĩa **“không còn lỗi / tối ưu toàn app”**. Lượt này không tự sửa hoặc commit các phát hiện.
