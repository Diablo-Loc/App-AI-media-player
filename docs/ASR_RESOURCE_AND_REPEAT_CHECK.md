# Chi phí coverage và kiểm tra lời lặp — 03/10/2026

Người dùng hỏi chi phí của “Vùng có giọng nghi thiếu lời, cần kiểm tra”, khả năng mất chữ/lệch các câu sau, runaway 30–100 từ và lời lặp thật 2–3 lần sát nhau. Đã đo toàn bộ 8 MP4 hiện có trong `video/`, mỗi video 3 lượt. Đợt này thêm tool/test/báo cáo, **không đổi production ASR/refine/coverage/translation/storage code** hoặc cắt giảm retry để đổi accuracy lấy tốc độ.

## Chi phí thật

Dòng cảnh báo chỉ in diagnostic sau khi xử lý xong; không tự khởi động thêm một công việc khi hiện trên màn hình. Công việc có chi phí là `repair_missing_subtitles` trước đó:

- Không có gap ≥4 s: trả kết quả ngay sau kiểm tra header WAV/timeline, không decode waveform/VAD/retry.
- Có gap: decode audio toàn bài ở 16 kHz và dùng VAD local chọn vùng nghi có giọng. VAD có thể nhầm nhạc/echo.
- Retry Whisper bằng model đang dùng, trên clip tối đa 12 s, tối đa 2 vòng; số clip phụ thuộc video, không có ngân sách tổng cố định cho mọi duration. Không nạp model Whisper thứ hai, nhưng CPU/GPU vẫn làm việc thêm.
- Sau 2 vòng, vùng nghi còn lại được ghi log. “Nghi thiếu lời” không đồng nghĩa đã chứng minh đoạn đó có lời thật chưa được nhận ra.
- Bài đã có phụ đề được đọc/cache như trước, không chạy coverage mỗi lần playback. Tạo lại Subtitle vẫn chạy AI/recovery.

Kết quả matched stages, median 3 lượt trên cùng video/model/options:

| Video | Audio (s) | ASR chính (s) | Coverage thêm (s) | Retry/lượt | Cue bổ sung/lượt |
| --- | ---: | ---: | ---: | ---: | ---: |
| A Small Miracle(short) | 143,16 | 10,81 | 6,42 | 7 | 2 |
| Brand New Sky | 217,07 | 13,88 | 5,35 | 5 | 0 |
| Empty old City - Looma | 202,48 | 12,84 | 9,79 | 11 | 2 |
| Maware! Setsugetsuka | 236,54 | 31,50 | 14,39 | 7 | 5 |
| Unwavering Startorch | 232,99 | 8,02 | 3,83 | 6 | 0 |
| Tell Your World (cover) | 255,23 | 11,36 | 6,19 | 10 | 1 |
| ロンリーユニバース (cover) | 221,43 | 18,82 | 7,39 | 8 | 0 |
| 人生エンドロール | 203,49 | 13,21 | 8,01 | 9 | 3 |

Coverage trong dataset tăng khoảng **38–76%** so với riêng ASR chính; đây là chi phí đáng kể, không gọi là “miễn phí/rất nhẹ”. Không bao gồm trích WAV, import/nạp model, refine ngoài stage đo, dịch, export/save hoặc UI. Vùng nghi nhưng không thêm được cue vẫn tốn retry. Không dùng bảng này để suy ra thời gian của CPU, model khác, video dài hay cold startup.

RAM tiến trình tăng thêm cao nhất quan sát trong stage coverage: **57,56 MiB**. Đây là RSS sampled 100 ms, so với RSS trước stage, không phải giới hạn RAM tuyệt đối. Peak bộ nhớ **toàn GPU** trong các stage ASR/coverage khoảng 4.197–4.229 MiB (4,10–4,13 GiB); gồm ứng dụng khác trên GPU, không phải memory riêng của model. GPU utilization có thể tăng trong retry. Sampling NVIDIA khoảng 500 ms có thể bỏ lỡ burst. Không suy ra “không ảnh hưởng FPS” từ phép đo này; UI playback chạy đồng thời chưa được benchmark.

Tool: `tools/asr_resource_probe.py`. Windows, venv Python 3.11.0, local large-v3/CUDA float16, faster-whisper 1.0.2, psutil 5.9.6, RTX 4060 Laptop 8 GB. Tool chỉ dùng thư viện/model đã có, tắt download và không gọi dịch/API. Một model owner được nạp cho cả workload; đo 3 lượt matched ASR→coverage, các lượt sau model/cache ấm, app thực tế vẫn mỗi job một spawn process như cũ. Không gọi cleanup/reset DLL production giữa các media trong cùng interpreter để tránh vấn đề PyO3 đã ghi ở đợt trước. WAV vào thư mục tạm và output vào docs.

Số liệu đầy đủ, CPU seconds/RSS/GPU samples, raw ASR, cue trước/sau và diagnostic: [summary.json](asr-resources/summary.json), `asr-resources/*-round-*.json/.srt`, [run-log](asr-resources/run-log.txt). Timing có overhead sampler và phụ thuộc tải máy/clocks; chưa coi đây là benchmark tăng tốc.

## Có cắt chữ hoặc làm lệch câu sau không?

Trên **24 lượt thực tế**:

- Inventory ký tự/số lần xuất hiện sau refine khớp raw ASR được chấp nhận theo chính sách lọc hiện tại, cả 24 lượt. Không phải so với lyrics ground truth; các đoạn bị credit policy loại không được tính là “lời đúng đã nhận”.
- **801 cue** trước coverage (267 cue mỗi bộ 8 video ×3) có text/start/end giữ nguyên sau coverage và finalization. Input cue list không bị sửa. Không có overlap trong kết quả cuối.
- Candidate recovery chỉ được thêm trong khoảng trống; không đổi cue tiếp theo để nhường chỗ. Timestamp clip được cộng offset về timeline gốc. Những từ biên jitter được xử lý theo profile đã kiểm tra ở phase trước.
- Hash của **21 file thật** trong `storage/subtitles/` trước/sau toàn bộ phép đo bằng nhau. Không overwrite/migrate/re-align dữ liệu cũ. Các file thử độc lập trong docs.

Đây là kiểm chứng preservation của stage recovery, không phải chứng minh Whisper nhận đủ mọi lời hay timestamp đều khớp vocal. Các bước refine mới đã cố ý đổi cách chia/margin **khi tạo mới** theo yêu cầu trước; phụ đề lưu cũ vẫn đọc theo schema/path/ID cũ. Nếu chủ động Tạo lại Subtitle, kết quả cũ của chính bài đó được thay theo workflow hiện có.

Cue bổ sung được model/VAD/confidence/filter chấp nhận vẫn có thể sai. Chưa nghe/đối chiếu lyrics ground truth từng cue bổ sung trên cả 8 video, chưa đo CER/WER/onset error. Không gọi số cue tăng là bằng chứng lời đã “full chuẩn”.

## Lặp 30–100 lần và điệp khúc thật

Thêm 4 regression stress trong `tests/test_asr_repeat_stress.py`:

| Trường hợp | Kết quả được kiểm tra |
| --- | --- |
| `ha` dính thành chuỗi 30/100 đơn vị | Rút còn `hahaha` |
| `ha` tách từ 30/100 lần cùng source, timestamp bị kẹt trên cùng interval | Rút còn 3 từ |
| Câu có nghĩa “I love you.” hát 2/3 lần, các interval riêng; gap 0 / 20 / 100 ms | Giữ đủ cả 2/3 câu, không giữ chỉ câu đầu |
| 2/3 tiếng `ha`, kể cả word times bị kẹt | Giữ đủ 2/3, dưới ngưỡng runaway |
| 100 tiếng/từ với timestamp tiến dần (`ha` hoặc `love`) | Giữ số lần xuất hiện; không cắt chỉ vì tần suất lớn |

Đây là dữ liệu tổng hợp kiểm tra quy tắc, không phải 100 lần thật được nghe trong video. Dataset video kiểm tra inventory/preservation, gồm bài có nhiều đoạn lặp như Maware, nhưng không có annotation để phân loại mọi repetition là lời thật/hallucination.

**Bộ lọc hiện tại không chặn được mọi dạng hallucination loop.** Câu/từ có nghĩa lặp nhiều lần, hoặc Whisper bịa cả timestamp tiến dần hợp lý, có thể vẫn qua; text-only không đủ chứng cứ để loại mà không cắt nhầm điệp khúc thật. Quy tắc hiện tại chỉ rút runaway filler/fused/stalled và loại bản sao trên gần như cùng acoustic span. Khi ASR trả metadata sai, dedup vẫn có khả năng false deletion; không cam kết mọi câu lặp được phân biệt hoàn hảo.

Không áp giới hạn “mọi câu giống nhau chỉ giữ 1/3 lần” vào playback hoặc subtitle source. Nếu mở rộng chống loop cho meaningful phrases, cần so audio/lyrics, targeted retry hoặc alignment evidence và đo false deletions; không bật regex cắt lặp tất cả 1–4 ký tự như code gốc.

## Kết quả và phạm vi

Suite bắt buộc: **107 pass + 11 skip lịch sử = 118 discover**, [test log](asr-resources/test-results.txt), `git diff --check` đạt. Các source/API/UI/legacy/storage gates tiếp tục đạt. Đợt này chỉ thêm đo/test/docs; không đổi production behavior, ASR kwargs, retry/VAD thresholds, models, providers, timing profile hoặc cache/schema. Không build, chạy updater hoặc phát hành EXE. Full GPU/ASR data khác human ground truth; translation/native/UI playback đồng thời/EXE/update installation vẫn chưa được xác nhận đầy đủ.
