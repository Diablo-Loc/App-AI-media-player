# Sửa lyric nhẹ, giữ hiệu năng — 04/10/2026

Theo yêu cầu cuối cùng, **không triển khai nhận dạng lại nhiều đoạn để tìm câu lặp hoặc căn đuôi ngân**. Bản cuối chỉ sửa policy text và cấu hình CPU fallback. Lượt ASR chính và coverage đã có trước phase giữ nguyên; không thêm vòng/cửa sổ Whisper, model, VAD, waveform decode, timer/thread hoặc dependency. Phụ đề đã lưu không được migrate/re-align.

## Thay đổi được giữ

1. `pipeline.lyric_accuracy.credit_text` phân biệt từ có thể thuộc lời hát với mẫu credit rõ ràng. Không xóa cả câu chỉ vì chứa `tiger`, `fiction`, `Instagram`, `copyright`, `音楽`, `歌詞`. Vẫn chặn boilerplate, nhãn metadata và mẫu credit đa ngôn ngữ/Instagram–Twitter–ホドリ đã xuất hiện trong captured ASR. Regex/phrase tables tạo một lần; không gọi cả legacy aligner để hỏi một câu có phải credit không. Quy tắc lời ngắn không có word timestamps vẫn bảo thủ như trước.
2. Nhánh lỗi CUDA khi transcribe chuyển CPU vẫn dùng medium theo fallback cũ, ưu tiên thư mục medium portable nếu có `model.bin`. Decode CPU dùng cùng options của lượt chính: word timestamps, beam 3, temperature 0, previous-text=False, primary VAD=False và prompt cũ. Không còn tự rơi vào beam 5/previous-text=True/temperature fallback mặc định của thư viện. Không thay model người dùng đã chọn ở lượt chính, không nâng/cài model.
3. Đường mới chỉ gọi từ generation/refinement. Text/timing schema, translation/prompts/cache, media ID, export/save/load, marker tránh padding lần hai, audio/video/player/UI effects và ownership không đổi.

Production chỉ thay hai module cũ (`ai/pipeline.py`, `pipeline/lyric_refinement.py`) và thêm một helper thuần Python. `aligner.py` legacy, temporal dedup/filler filter, `lyric_phrases.py`, finalizer và 50 ms lead/80 ms tail giữ nguyên source. Các adapter test mới phục hồi exact source phase này trước các gates cũ; manifest lịch sử không recapture.

## Câu lặp và ngân dài

- Regression giữ đủ 2/3/4 lần “The sign is lightening up” với các thời điểm riêng, gồm gap 0/20/200 ms. Filler runaway 30/100 lần và duplicate cùng acoustic span vẫn được kiểm tra bằng suite cũ. Không thêm regex chỉ giữ một câu giống nhau.
- Với **Brand New Sky**, captured primary ASR chỉ nhận một câu ở 80,99–83,26 rồi bỏ khoảng ngắn; không tìm thấy lần thứ hai bị text dedup xóa. Nhận dạng clip thử đã tìm được lần thứ hai, nhưng bước đó cần thêm công việc và có lệch từ/timestamp giữa các crops. **Phần thử đã gỡ khỏi production theo yêu cầu ưu tiên hiệu năng.** Bản cuối không tự phục hồi lần hát mà model chưa nhận ra, không áp workaround riêng cho bài này.
- Dữ liệu word timestamps còn đuôi ngân thì grouping hiện có giữ tới đuôi đó +80 ms, không cắt chỉ vì vượt 8 giây; khoảng nghỉ nhiều giây vẫn rỗng. Khi model cắt word end sớm, không có căn cứ kéo tự động thêm một thời lượng cố định mà vẫn biết đúng giọng hát. Bản cuối giữ timing hiện có, không tăng padding để che lỗi hoặc nối vào câu sau. Regression sustained note 12 giây xác nhận đường này giữ thời gian đã có; không phải đo vocal end thật.

## Kiểm chứng bản cuối

- **90 focused tests đạt**: policy/coverage/repeat/grouping/empty/save; [focused-tests.txt](lyric-accuracy/focused-tests.txt).
- **385 pass +11 historical skip =396 full tests**, 159,392 giây, exit 0; [test-results.txt](lyric-accuracy/test-results.txt). Log read-only/synthetic save failures là fault injection; warning gc hai object đã có ở phase trước, chưa xác định owner.
- **31 checkout/source gates đạt** qua index và checkout tạm, không dùng index người dùng; `git diff --check` đạt. [checkout-gates.txt](lyric-accuracy/checkout-gates.txt). Snapshot mới: `lyric-accuracy/original/`, `reviewed/`, `reviewed-sources.json`, `helper-hash.json`.
- **24 captured ASR /8 video** replay bản cuối khớp exact toàn bộ cue output của baseline phase này; text/order/times/bounds/no-overlap không đổi trên tập đó. Các lời có từ khóa trước đây bị xóa được kiểm tra bằng dữ liệu tổng hợp, không gọi việc giữ chữ là lyrics ground truth. [policy-review.json](lyric-accuracy/policy-review.json).
- **817/817 file** đã chụp ở storage/output/video giữ nguyên SHA-256; không chạy updater, build, commit hoặc ghi settings. [saved-before.json](lyric-accuracy/saved-before.json).
- Microbenchmark 10.000 lần filter/5 lượt trên cùng interpreter Python 3.11: median policy cũ ~78,27 ms, mới ~37,13 ms, tổng hợp 8 loại text. Tập này có số câu được giữ khác nhau do sửa policy. Chỉ đo chi phí lọc text; không suy ra Whisper nhanh hơn hai lần, tổng thời gian AI/RAM/FPS hay native/EXE parity.

## Dữ liệu thử đã bỏ

`lyric-accuracy/experiments/`, `production/` và `*-production-log.txt` ghi quá trình thử nhận dạng lại **trước yêu cầu bỏ hướng nặng**. Chúng không phải output của bản cuối và không chứng minh app hiện phục hồi câu lặp. Các tools thử cùng toàn bộ helper retry/consensus đã gỡ; chỉ giữ evidence riêng để tránh nhầm rằng lỗi mẫu đã được sửa trong production. Không dùng các SRT/JSON này thay phụ đề người dùng.

Giới hạn model còn nguyên: có thể thiếu lời, nghe sai từ, nhận nhầm ngôn ngữ hoặc word end. Bộ lọc không bảo đảm phân biệt mọi lyric/credit/hallucination. Những nâng cấp yêu cầu retry, vocal separation/forced alignment hoặc lời chuẩn được hoãn; không tự bật cho toàn thư viện.
