# Kế hoạch đo hiệu năng và độ chính xác trên baseline đã khôi phục

Ngày 03/10/2026. Đây là kế hoạch kiểm chứng, chưa phải kết quả benchmark hoặc thay đổi model. Code `app/` giữ nguyên, source snapshot trong `restored-app-baseline.json`.

## Hai loại thay đổi

**Tối ưu thực thi giữ đầu ra:** bớt nạp model, bớt ghi cache, giảm parse lặp, chuyển orchestration khỏi GUI. So sánh dữ liệu/behavior với baseline; không đòi AI tạo lời khác để chứng minh nhanh hơn.

**Cải thiện chất lượng đầu ra:** sửa timestamp boundary, coverage/fallback hoặc cân nhắc heuristics/model/prompt. So sánh với ground truth và baseline; không coi output khác tự động là tốt hơn. Làm patch riêng với lý do và fixtures.

## Bộ dữ liệu cần ghi nhận

Chọn media hiện có, không tải/cài thêm model chỉ để tạo baseline. Ghi model/runtime/device, phiên bản EXE, settings (che API keys), source hash, kích thước/duration và reference. Giữ bản reference thủ công không bị pipeline ghi đè.

| Nhóm | Trường hợp cần có | Kiểm tra |
| --- | --- | --- |
| JP/ZH/KO | CJK, xen Latin/số, khoảng nghỉ ngắn | Nối từ, dấu cách, CER và timestamp |
| EN/VI | Speech + bài hát, có dấu và âm kéo dài | WER/CER, EN/VI layers, lời gốc không mất |
| Nhạc | Điệp khúc lặp, la/la/hey, intro không lời, credit | False deletion, hallucination, duplicate suppression |
| Khó | Nhạc nền lớn, nhiều giọng, đoạn im lặng, câu dài | Quality so với reference; độ trễ/RAM |
| Subtitle | Biên rounding, overlap, unsorted, 0/end, Unicode | SRT/ASS/JSON round-trip và highlight |
| Runtime | CPU/GPU đang dùng, local model, cache nóng/lạnh | Load time, fallback, peak memory |
| Provider | Response đủ/thiếu/lặp ID/rỗng/sai format/timeout bằng stub | Coverage và fallback trước khi gọi mạng thật |

## Độ chính xác phải đo riêng theo stage

1. **Raw ASR:** lưu text/word times trước cleanup, WER cho ngôn ngữ tách từ, CER cho CJK; cùng quy tắc normalization trên reference và output. Không xóa punctuation/word một phía để làm metric đẹp.
2. **Refine:** ghi số dòng/từ bị loại, false deletion, đoạn lặp bị mất, start/end errors và overlap. So sánh cả nhánh có words và không words; bảo toàn offset/padding hiện hành.
3. **Translation:** nguồn, mode/provider/model, cache hit/context, số dòng có EN/VI và chất lượng nghĩa được người đọc kiểm tra. Coverage đầy đủ không đồng nghĩa dịch đúng nghĩa.
4. **Export/storage:** cùng text của từng layer, units và mode; timestamp round-trip/special characters; settings và cache cũ vẫn đọc được.
5. **UI:** playback seek/rate, cue/row active, edit/undo/redo, switching media/window modes. Không suy luận sự đồng bộ trực quan từ file JSON hợp lệ.

Các probe nguồn hiện tại đã tái hiện: online response không parse được vẫn trả list truthy; adapter online phụ có keyword không khớp; SRT 1.9996s có milliseconds=1000. Đây là các case tổng hợp cho test, không phải kết quả lỗi trên media người dùng. Cache text-only và cleaner truncation là contract hiện có; chỉ đổi sau đánh giá/có migration.

## Hiệu năng phải đo trên cùng workload

| Công việc | Số đo | Kiểm tra bảo toàn |
| --- | --- | --- |
| Startup | Thời gian tới window usable; import/model init counts | Portable paths, DLL, settings/EXE startup |
| Library | 100/1.000/10.000 metadata; cold/hot cache; ffprobe calls; GUI timer gaps | Cùng ID/title/artist/duration/order và format support |
| Thumbnail | Cache hit/miss; FFmpeg count; JSON writes/bytes; decode count | Ảnh/quality/path/crop/DPR; flush/error/cancel |
| Grid/search | Thời gian page/search/scroll/resize; widget count; RAM | Click/playlist/shuffle/highlight/scroll/mode |
| Editor | Timing parses/lookup; 100/1.000/10.000 rows; undo memory | Cùng row active, precision, unsorted/overlap và mọi edit |
| AI | Extract/load/ASR/refine/translate/export riêng; latency/throughput; peak RAM/VRAM | Cùng options/fallback và output fixtures |
| Native/download | Callback/log rates, queue backlog/drop, UI latency | ABI, buffer lifetime, cancel, options và format |

Tối thiểu 3 lượt cho timing, ghi median và khoảng dao động; không dùng test deadline nhạy máy làm cam kết thương mại. Đếm thao tác là bằng chứng ổn định cho bớt công việc; timing toàn app cần máy và workload thật. Không tái sử dụng benchmark của nhánh đã rollback.

## Cổng trước khi giữ patch

- Diff nhỏ, giữ signature/signals/widget ownership và stored schema.
- Fixtures/hành vi trước-sau tương đương cho tối ưu thực thi; không đổi thuật toán AI trong cùng patch.
- Case cancel/stale result/retry/save failure/shutdown được kiểm chứng nếu chạm worker/storage.
- Ghi riêng trạng thái source/probe/mock/actual-media/GPU/native/EXE. Chỉ đánh dấu pass những gì thực sự chạy.
- Patch cải thiện accuracy có reference, không tăng mất lời, không âm thầm làm lệch timing hoặc bỏ fallback; cache migration có đường recovery.
