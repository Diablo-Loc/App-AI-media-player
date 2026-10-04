# Lưu/dịch/worker — 04/10/2026

Người dùng cho phép sửa audit A1–A4 và kiểm chứng/sửa A6, với điều kiện file phụ đề/dịch cũ không bị tự sửa. **Hook Qt ngoài phạm vi, giữ nguyên theo yêu cầu.** Không áp lại refactor kiến trúc, đổi framework/model/dependency hoặc commit.

## Dữ liệu cũ

- Không migration, realign, dịch lại hoặc ghi lại subtitle có sẵn. Bài đã có JSON/ASS hợp lệ tiếp tục load bản cũ.
- **31 file JSON/ASS/SRT/LRC** trong `storage/`, `output/`, `video/` giữ nguyên SHA-256 trước/sau các kiểm tra. [Hash trước](reliability/saved-before.json), [đối chiếu sau](reliability/saved-after-check.json).
- Media ID, tên/thư mục file, JSON/index schema, cache key giữ nguyên. ASR/coverage/phraser/timing/fade/AI worker spawn và hook giữ nguyên hash.
- Quy tắc mới áp dụng khi tạo bài mới hoặc **người dùng chủ động** dịch/chỉnh sửa/lưu/tạo lại bài cũ. Save/regenerate vẫn thay file đích theo hành động đó; khi lỗi, giữ bản trước.
- Đọc cache dịch cũ rỗng/sai chỉ bỏ qua entry, không sửa file cache. Chỉ lưu cache khi có kết quả mới hợp lệ; không xóa toàn bộ cache.
- Recovery chỉ xử lý journal do save mới tạo khi một lần lưu bị ngắt; không dò/sửa các cặp JSON/ASS cũ vốn đã lệch trước phase này.

## Thay đổi

### Save/editor

`core.subtitle_persistence` ghi file tạm cùng filesystem, flush/fsync và replace. Manager chuẩn bị JSON + ASS + index trước khi publish; journal có bản trước của từng đích. Render/encoding/replace lỗi rollback; process ngắt giữa các replace thì lần mở sau phục hồi giao dịch dở. Đây là **publication có recovery**, không phải atomic rename đồng thời ba file. Permission/ổ đĩa hỏng khiến rollback cũng không ghi được vẫn cần khôi phục quyền/ổ đĩa; manager không báo READY khi recovery lỗi. Không có thử mất điện thật.

`save_raw_data` trả kết quả; editor chỉ báo thành công/accept sau True, không ghi thẳng để lách lỗi manager. File import bên ngoài cũng atomic replace. Rerender ASS khi người dùng đổi mode vẫn giữ nội dung/timing cũ, chuẩn bị bản render trước khi thay file.

### Translation/cache/refrains

- Local kiểm tra số lượng/nonempty từng batch. Response lỗi/ngắn/rỗng retry từng dòng gốc để tránh trượt mapping sang batch sau. Một batch lỗi có tối đa một retry riêng mỗi dòng; vẫn thiếu thì báo lỗi kỹ thuật, không cache rỗng hay nhận là completed empty ASR.
- Online kiểm tra đủ IDs/EN/VI và không trùng ID, rồi mới gán subs. Invalid/partial trả failure cho **fallback online → local hiện có**; không gán dở. Fallback local hiện xử lý cả danh sách như trước, chưa tối ưu gọi riêng dòng thiếu.
- Nguồn ASR được đưa vào translator đầy đủ, bỏ cleaner/truncation riêng trên input. Không đổi tokenizer token limits/model/generation parameters, nên không chứng minh model không bao giờ giới hạn input nội bộ.
- Cleaner output giữ refrain 2–4 lần, bỏ hard cap 150 ký tự; vẫn rút gọn chuỗi lặp dài cực nghèo từ vựng/lặp cụm nhiều lần. Cache validator không loại câu dài/refrain ngắn chỉ vì length/diversity cũ. Heuristic không chứng minh chặn mọi hallucination.
- Chỉ load NLLB khi cache miss. All-cache-hit không load model/ghi lại cache. Cache write atomic/dirty-only; source-language/mode chưa thêm vào key vì cần phase compatibility riêng.

### GUI/scan

- `AIController.start` cancel bằng cờ, giữ worker đến finished rồi chạy **yêu cầu mới nhất**. Bỏ progress/data/error cũ theo worker/media identity; cancel/shutdown xóa pending restart. `AIWorker`/spawn/process cleanup không đổi.
- Restart thumbnail scanner không wait GUI; giữ worker đến finished. Shutdown vẫn đợi owned workers.
- `LibraryScanQueue` quét snapshot metadata trên QThread, cancel kết quả folder cũ, commit folder mới nhất trên GUI. ffprobe cùng hàm/options/timeout; synchronous `MediaLibrary.scan_folder` còn giữ cho caller cũ. Merge giữ title/artist/thumbnail được edit trong lúc scan, cập nhật field scan-owned/duration thiếu. Empty folder trả playlist rỗng thay vì view folder trước.
- Library cache persist bằng owned writer. Metadata lock chỉ giữ khi snapshot/merge; disk write/retry có lock riêng, tránh GUI chờ I/O khi commit scan. **Chưa batch thumbnail writes**: API update thumbnail vẫn durable như trước.

### Đóng khi tải/dịch

- Download/title workers thuộc WorkerOwner, giữ reference đến QThread.finished. Track updater và download subprocess; stop dừng cây process của job sở hữu, xử lý race stop trước registration. Worker reaps processes trong finally; không terminate QThread.
- Bootstrap yt-dlp nhận cancellation callback/read timeout 10 s cho các caller có cancellation; title extraction có socket timeout 10 s. Các caller cũ không truyền callback vẫn giữ API/default cũ. Không đổi lựa chọn format/chất lượng; không tải/update engine để thử phase này.
- Editor align/translation worker thuộc owner cấp QApplication để dialog đóng không hủy worker đang chạy. Close/accept request interruption và bỏ callback muộn; app shutdown đợi workers.
- Giữ thứ tự stop player/native gốc trước khi đợi owner mới, chờ trước cleanup temp/quit. **Có thể đợi request/model call đang thực hiện kết thúc**; interruption không ép dừng HTTP/PyTorch đang chạy. Live API/GPU/EXE còn chờ.

## Kiểm chứng

Project Python 3.11, Qt offscreen trên Windows:

| Kiểm tra | Kết quả |
| --- | --- |
| Full discovery | **198 total =187 pass +11 historical skip**, 28,397 s |
| Tests mới | **28 pass**: fault save/render/replace/recovery, schema/timing/read-only load, editor/cache cũ, retry/mapping/IDs/refrains, latest-job, scan/merge/metadata lock, shutdown |
| DPI 200% | **35 pass** =28 mới +7 spacing/caption gates |
| Saved data | 31 file giữ nguyên SHA-256 |
| Source scope | 15 original snapshots +3 helper hashes, manifest/diff; phase cũ chỉ normalize sau exact-approved hash check |
| ASR/timing/worker/hook | Hash unchanged; không fresh ASR/model run |
| Whitespace | `git diff --check` đạt |

Qt threads/timers và subprocess Python ngủ thật kiểm chứng updater, download stage, stop-registration race và đóng MainWindow khi tải/dịch fixture còn chạy. Restart test giữ worker cũ cleanup 150 ms sau khi start trả về, timer GUI tiếp tục tick. Metadata scan được xác nhận ở background thread; disk I/O không giữ metadata lock. Đây không phải số đo native video FPS/GPU cleanup thật hoặc chất lượng nghĩa dịch.

Log: [full](reliability/test-results.txt), [focused](reliability/focused-tests.txt), [DPI](reliability/dpi2-tests.txt), [diff check](reliability/diff-check.txt). [Manifest](reliability/reviewed-sources.json), [diff đã review](reliability/reviewed.patch), [helper hashes](reliability/new-source-hashes.json). Capture script chỉ chạy khi developer review, không được tests tự gọi để chấp nhận thay đổi bất kỳ.

Focused fixture ban đầu dùng sai tên API và làm wrapper Qt bị re-import khi teardown `patch.dict(sys.modules)` giữa hai cửa sổ. Đã sửa API/giữ modules resident; focused/full/DPI cuối đạt. Không quy crash runner này thành crash native app hoặc thay dependency. Auditor trước-fix có asserts mô tả defects; `tests/test_reliability.py` thay thế việc chạy auditor đó trên code đã sửa.

## Còn lại

Không kết luận app hết mọi lỗi/tối ưu. Batch thumbnail cache, editor/library rất lớn, context cache keys và orchestration phụ chưa kích hoạt còn trong roadmap. Human lyrics/timing, API thật, AI/playback đồng thời, native/EXE/portable validation còn chờ. Không build/release/commit/dọn dữ liệu trong phase này.
