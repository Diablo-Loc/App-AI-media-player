# Roadmap sau khi khôi phục app gốc

Đo accuracy/performance hiện hành: 8 video local ×3 matched ASR/coverage, coverage thêm median 3,83–14,39 s; model reuse, hash phụ đề cũ và cue preservation đạt. 107 pass +11 skip lịch sử. Đây là đo chi phí, chưa phải tối ưu tốc độ; chống meaningful hallucination loops, human ground truth và benchmark playback đồng thời còn chờ. Xem [ASR_RESOURCE_AND_REPEAT_CHECK.md](ASR_RESOURCE_AND_REPEAT_CHECK.md). Không cắt retry/đổi threshold chỉ để giảm thời gian mà thiếu kiểm tra mất lời.

Ưu tiên mới—timing/chia câu/lời lặp: **đã sửa đường tạo phụ đề mới theo phạm vi**, 103 pass + 11 skip lịch sử; replay ba raw ASR và production ASR→save ba video đạt, không tự đổi phụ đề đã lưu. Lượt mới dùng profile word boundaries nên số cue/timing cố ý khác baseline. Human onset/lyrics reference, CER/WER, forced alignment và native/EXE/update còn chờ. Xem [SUBTITLE_QUALITY_FIX.md](SUBTITLE_QUALITY_FIX.md).

Ưu tiên mới—coverage Whisper: **đã sửa trường hợp mất đầu bài tái hiện trên video thật**, thêm targeted retries đầu/giữa/cuối và diagnostics, 74 pass + 11 skip lịch sử. Giữ nguyên 111 cue cũ trên ba video. Reference lyrics/CER/WER, trường hợp giọng nhỏ/nhạc lớn và full native/EXE còn chờ; không đánh dấu mọi video full/correct. Xem [ASR_COVERAGE_FIX.md](ASR_COVERAGE_FIX.md).

Chất lượng thumbnail playlist: **hoàn thành phần decode/hiển thị theo phạm vi**, 55 pass + 11 skip lịch sử và kiểm tra scale 125%/150%/200%. Có đo sai số ảnh trên một JPEG tổng hợp; chưa đo hiệu năng toàn app hoặc xác nhận native/EXE. Xem [PLAYLIST_THUMBNAIL_QUALITY.md](PLAYLIST_THUMBNAIL_QUALITY.md).

Đợt cân chỉnh ba ảnh phản hồi: **hoàn thành theo phạm vi trình bày** playlist/popup/menu, 47 pass + 11 skip lịch sử và sáu regression mới ở DPI 200%. Chưa tính là hoàn thành tối ưu nền tảng hoặc full native/EXE parity. Xem [UI_LAYOUT_POLISH.md](UI_LAYOUT_POLISH.md).

Đợt video nhỏ/trạng thái nút: **đã sửa theo phạm vi UI**, 41 pass + 11 skip lịch sử; DPI 200% và decode/frame/geometry một video có sẵn được kiểm tra. Native presentation/EXE và tối ưu nền tảng vẫn chờ. Không đánh dấu các bước lazy model/cache/editor/accuracy là đã làm. Xem [UI_MEDIA_SURFACE.md](UI_MEDIA_SURFACE.md).

Giai đoạn ổn định UI sau phản hồi: **đã sửa và kiểm chứng tự động** sidebar mất icon, playback bị overlay nhận click, auto-hide khi popup mở, responsive và animation chạy chồng. 32 pass + 11 skip lịch sử; thêm 10/10 regression ở DPI 200%. Các kiểm tra media/native/EXE vẫn chờ, tối ưu AI/library/editor bên dưới chưa triển khai. Xem [UI_STABILITY.md](UI_STABILITY.md).

03/10/2026: người dùng đã khôi phục toàn bộ `app/`, sau đó cho phép nâng cấp UI. Các giai đoạn refactor nền tảng trước không còn được triển khai. Model, môi trường và hành vi gốc tiếp tục làm chuẩn.

Giai đoạn UI mới: **đã triển khai phần trình bày trên Qt Widgets**, bộ icon SVG offline, palette/typography/spacing, các trang và popup. Kiểm tra tự động UI + source đạt theo phạm vi; test thực tế media/GPU/network/native/EXE và lifecycle công cụ phụ đề còn chờ. Xem [UI_REFRESH.md](UI_REFRESH.md). Không đánh dấu các tối ưu nền tảng bên dưới là hoàn thành.

Baseline: 87 file Python / 16.517 dòng, Git `4148c13`. Xem [đánh giá từng phần](RESTORED_APP_REVIEW.md), [kế hoạch đo](ACCURACY_BASELINE_PLAN.md) và `restored-app-baseline.json`.

| Bước | Công việc | Cổng kiểm chứng | Trạng thái |
| --- | --- | --- | --- |
| 0 | Snapshot, audit từng thư mục, probe hợp đồng | AST/compile/hash/diff; app/EXE thực tế làm chuẩn | Audit/probe xong; hiệu năng và chất lượng thực tế chưa đo |
| 1 | Lazy NLLB sau cache miss | Cùng text/layers/timing/cache; all-hit không load model | Chưa sửa |
| 2 | Batch ghi cache thumbnail | Cùng ảnh/path/JSON cuối; write count; flush complete/cancel/error/shutdown | Chưa sửa |
| 3 | Cache thời gian editor | Cùng precision/row active; seek/overlap/unsorted/edit/undo | Chưa sửa |
| 4 | Profile scan/grid rồi đổi orchestration nếu cần | Cùng metadata/ID/order; GUI heartbeat; save concurrency/lifecycle | Chưa sửa |
| 5 | Accuracy/completeness riêng | Reference, coverage/fallback, timestamp boundaries; migration nếu đổi cache context | Đã sửa coverage và timing/chia câu/lặp ở đường tạo mới; human reference/CER/WER, dịch và native/EXE còn chờ |
| 6 | Tách MainWindow/dialog/AI theo trách nhiệm | API/signals/ownership/modes/EXE tương đương | Chưa sửa |
| 7 | Kiểm chứng bản xuất | Full checklist media/model/provider/download/native trên runtime hiện hành | Chưa chạy trong audit |

Giữ ASR parameters, prompts, heuristics, model format/workaround, fallback và schema/key/path. Thay đổi các hợp đồng đó cần quality gate riêng, không làm kèm refactor. Tách file không tự chứng minh app nhanh hoặc chính xác hơn.

UI mới đã triển khai riêng theo yêu cầu mới; phần parity thực tế còn chờ ở `UI_REFRESH.md`. Upgrade dependency vẫn hoãn. Kết quả 52 test/benchmark trước thuộc bản đã rollback, không áp cho roadmap hiện tại.
