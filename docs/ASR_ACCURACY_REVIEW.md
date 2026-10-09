# Rà soát độ chính xác Whisper/lyric — 04/10/2026

Sau audit: đã triển khai bản sửa nhẹ theo yêu cầu ưu tiên hiệu năng, credit policy và CPU options được sửa; không triển khai thêm Whisper retries/tail alignment. Trạng thái cuối và regression: [LYRIC_ACCURACY_LIGHTWEIGHT.md](LYRIC_ACCURACY_LIGHTWEIGHT.md). Các phát hiện bên dưới mô tả trước sửa.

## Checklist hiện tại — sau bản sửa nhẹ

| Mục trong danh sách audit | Trạng thái production |
| --- | --- |
| 1. Credit filter xóa nhầm từ thuộc lyric | **Đã sửa.** Giữ từ thông thường, chặn mẫu credit rõ ràng và signature đã kiểm chứng; tests giữ lời thật/credit riêng. Không bảo đảm mọi câu dùng chính credit phrase đều được phân loại đúng. |
| 2. Dò gap ngắn/câu sai bằng confidence và nhận dạng lại | **Không triển khai theo yêu cầu ưu tiên hiệu năng.** Coverage cũ giữ nguyên; toàn bộ retry/consensus bổ sung đã gỡ. Không claim đã phục hồi câu lặp thiếu ở Brand New Sky. |
| 3. Decode CPU fallback khác lượt chính | **Đã sửa.** Dùng cùng primary options, giữ medium fallback và ưu tiên portable model sẵn có. Không đổi model/primary options ở lượt chạy bình thường. |
| 4. Chọn ngôn ngữ/confidence diagnostics | **Chưa thêm.** Auto-language vẫn như cũ; không tự ép ngôn ngữ dựa vào tên bài, không thêm field vào schema hoặc đổi settings. Tùy chọn ngôn ngữ có thể là một tính năng riêng, chưa có đối chứng để tự đổi default. |
| 5. Lời chuẩn/forced alignment/vocal separation và kiểm soát mọi hallucination | **Hoãn.** Cần đối chứng lời/vocal và thường thêm công việc/model. Giữ grouping/dedup/timestamp đã kiểm chứng; không kéo đuôi ngân tùy tiện hoặc loại mọi điệp khúc giống nhau. |

Phạm vi chốt: hoàn thành các sửa nhẹ đã có căn cứ, không phải triển khai toàn bộ roadmap nghiên cứu. Lặp có thời điểm riêng, ngân dài có word end hợp lệ, khoảng nghỉ, empty-result, save/load và source preservation đều có regression. 385 pass +11 skip lịch sử, 90 focused/31 checkout gates, 24 captured replays khớp exact và 817 saved hashes không đổi. Không có benchmark lyrics/timing ground truth để chứng nhận chuẩn mọi bài/trường hợp. Bổ sung checklist này chỉ sửa tài liệu, không thêm thay đổi production sau bản cuối.

Kết luận: pipeline có bảo vệ và regression tốt, nhưng **chưa đủ cơ sở gọi là gần bản lời gốc hoặc timing chính xác ±50 ms cho mọi bài**. Nên làm một phase accuracy có đối chứng, ưu tiên tránh mất lời do bộ lọc rồi mới tăng retry/model. Đợt này chỉ audit, không thay production, tham số/model, dữ liệu hoặc manifest lịch sử; không tạo lại phụ đề của bài thật.

## Đã kiểm tra trực tiếp

- Đọc extraction → model/CPU fallback → primary ASR → refinement → coverage → finalization → export/translation/runtime timing marker. Audio cho ASR là PCM mono 16 kHz, không phải sửa âm thanh file/playback. FFmpeg đang tự chọn audio stream; chưa có map theo track được người nghe chọn. Với file nhiều track hoặc stereo vocal lệch pha, cần mẫu riêng trước khi thay extraction.
- Primary giữ `word_timestamps=True`, beam 3, temperature 0, không previous-text conditioning, không VAD cắt primary và prompt ` .+`. Mặc định settings thiếu model là medium; benchmark cũ dùng local large-v3/CUDA. Không suy benchmark đó sang mọi model/CPU.
- Recovery dùng lại model, VAD chỉ chọn vùng retry; giữ cue đã chấp nhận. Tối đa hai vòng clip 12 giây nhưng không có tổng ngân sách retry cố định cho mọi độ dài video.
- Refine dựa trên word boundaries; giữ lặp có thời điểm riêng, chỉ thu gọn filler dính/kẹt dài hoặc bỏ duplicate gần như cùng acoustic interval. Finalizer loại overlap; fallback không có word times giữ nguyên toàn đoạn.
- Lead 50 ms/tail 80 ms là margin hiển thị quanh **ước lượng của Whisper**, không phải kết quả đo độ lệch so với giọng hát thật. Không có bước đối chiếu lyrics chuẩn hoặc căn chỉnh lại với lời đã xác nhận trong production. `correct_raw_segments_online` chỉ được import, không được gọi ở pipeline đang chạy.
- Phụ đề cũ vẫn load/cache theo luồng cũ; UI effects không chạy lại ASR hoặc đổi timing. Nếu chủ động Tạo lại Subtitle thì bài được chọn sẽ được thay kết quả theo workflow hiện có.

## Những điểm nên cải thiện

| Ưu tiên | Phát hiện | Hướng xử lý cần kiểm chứng |
| --- | --- | --- |
| 1 | Credit policy dùng substring mạnh, ví dụ `tiger`, `fiction`, `音楽`. Probe có word timestamps vẫn loại `Eye of the tiger.`, `This is fiction.`, `音楽が好きだ`. Đây là dữ liệu tổng hợp tái hiện policy, chưa khẳng định video nào có đúng những câu này. | Tách credit phrase rõ ràng với từ có thể thuộc lyric; dùng metadata/audio/retry làm chứng cứ, giữ regression credit thật. Không bỏ toàn bộ lọc để nhận lại hallucination. |
| 2 | Coverage chỉ dò khoảng trống ≥4 giây. Gap tổng hợp 3 giây không được lập retry. Câu nhận sai nhưng vẫn phủ timeline cũng không được phát hiện. Retry riêng loại pure oh/la/na và Thank you, nên có thể bỏ cả phần hát thật như vậy. | Theo dõi confidence và vùng đáng nghi, retry có ngân sách, giữ abstention/diagnostic khi chưa đủ chứng cứ. Không giảm ngưỡng và chèn lời vào mọi nhạc dạo một cách mù quáng. |
| 3 | Nhánh lỗi CUDA trong lúc transcribe gọi CPU với chỉ `word_timestamps=True`. faster-whisper 1.0.2 khi đó dùng beam 5, previous-text=True và temperature fallback 0→1, khác primary; model chuyển medium theo logic cũ và không chỉ rõ local path. | Một phase riêng thống nhất decoding options giữa các thiết bị, giữ CPU/model fallback và offline recovery; test cả lỗi khi duyệt generator. Đây là hành vi baseline đang được source gates bảo vệ, chưa sửa trong audit. |
| 4 | Auto-language dựa vào cửa sổ đầu, coverage khóa theo ngôn ngữ đã nhận. Dữ liệu cũ A Small Miracle(short) trả `jw` cả ba lượt. Chưa có ground truth để kết luận ngôn ngữ đó sai, nhưng cần đối chiếu. Primary bỏ word probability/segment confidence khi chuyển sang raw refine. | Tùy chọn ngôn ngữ gốc cho generation mới và lưu diagnostic RAM riêng; kiểm thử intro dài/bài đa ngôn ngữ. Không mặc định ép mọi bài thành tiếng Nhật/Anh hoặc sửa schema phụ đề. |
| 5 | Cắt câu theo punctuation/pause/ASR line là heuristic, không phân tích được mọi câu hát dài. Lặp có nghĩa với timestamp do model bịa vẫn có thể qua. | Dùng lời chuẩn/corrected text làm đối chứng, thử alignment trên một tập nhỏ trước khi đưa vào chế độ chất lượng cao. Không cắt mọi điệp khúc giống nhau để chống loop. |

## Đối chứng và tài nguyên

Probe mới: [review.json](asr-accuracy-review/review.json), chạy bằng `venv\Scripts\python.exe tools/review_lyric_accuracy.py`.

- Replay **24 captured ASR / 8 video**: toàn bộ cue output khớp exact với artifact phrase phase đã lưu; text/order, bounds và không overlap đều đạt. Đây là kiểm tra regression, **không phải 24 lượt Whisper mới**, không phải CER/WER hoặc human timing ground truth.
- **39/39 file** hiện có trong `storage/subtitles` giữ hash trước/sau probe. Manifest audit mới: [saved-hashes.json](asr-accuracy-review/saved-hashes.json). Không ghi đè manifest/data cũ.
- **82 focused tests đạt**: coverage/repeat 23, refinement/grouping/empty 59. Lỗi ASS read-only trong log test empty là fault injection dự kiến.
- Full regression: **377 pass +11 historical skip =388 tests**, 134,693 giây, exit 0; [test-results.txt](asr-accuracy-review/test-results.txt). `git diff --check` đạt. Log có `gc: 2 uncollectable objects at shutdown` đã thấy ở các phase trước; chưa xác định owner, không coi kết quả suite là chứng nhận native/GPU/EXE không lỗi. Không chạy fresh Whisper, download/model update hoặc nghe/annotation mới trong audit.
- Benchmark cũ trên 8 video ×3 lượt large-v3/RTX 4060: coverage thêm 3,83–14,39 giây, khoảng 38–76% ASR-only, không gồm load model/dịch/save. Không đo lại GPU/CPU/FPS đợt này. Chi tiết: [ASR_RESOURCE_AND_REPEAT_CHECK.md](ASR_RESOURCE_AND_REPEAT_CHECK.md).

## Phase accuracy đề xuất

1. Lập tập lời thật/corrected text cho vài bài đa ngôn ngữ, gồm intro có hát, điệp khúc sát nhau, câu ngắn, nhạc không lời. Đánh dấu một số onset/end bằng nghe thật. Đo CER/WER, từ bị xóa/thêm và sai số timing; không dùng số cue tăng làm thước đo chất lượng.
2. Sửa credit policy trước; thêm tests chứng minh lời có từ khóa vẫn giữ và credit/hallucination vẫn bị chặn. Chỉ đường tạo mới, không migration/re-align phụ đề lưu.
3. Đối chiếu CPU decoding và bổ sung ngôn ngữ/confidence diagnostics; đánh giá targeted retry có budget. Giữ default/mô hình hiện có cho tới khi A/B chứng minh thay đổi tốt hơn và không tăng false deletion.
4. Nếu timestamp vẫn lệch đáng kể, đánh giá alignment với lời đã xác nhận hoặc vocal separation tùy chọn. Chỉ triển khai sau đo accuracy/tài nguyên/compatibility; không nâng dependency hoặc xử lý AI nặng toàn thư viện trong audit.

Whisper được công bố cho speech recognition/translation; model card ghi nhận hallucination, repetitive text và chất lượng khác nhau theo ngôn ngữ, đồng thời yêu cầu đánh giá theo lĩnh vực ứng dụng. Vì vậy cần đối chứng riêng cho lyric: [OpenAI Whisper model card](https://github.com/openai/whisper/blob/main/model-card.md). Defaults đối chiếu bằng source portable đã cài 1.0.2 và [source faster-whisper 1.0.2](https://github.com/SYSTRAN/faster-whisper/blob/v1.0.2/faster_whisper/transcribe.py).
