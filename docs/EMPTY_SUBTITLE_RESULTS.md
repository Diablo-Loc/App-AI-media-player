# Kết quả phụ đề rỗng/nhạc không lời — 03/10/2026

04/10/2026: [phase chia lyric](LYRIC_PHRASE_GROUPING.md) đổi grouping riêng theo yêu cầu mới. Empty-result behavior, timing margins/finalizer/fade và worker giữ nguyên; gate refinement giờ normalize đúng bốn adapter grouping rồi đối chiếu toàn bộ source rollback. Không áp lại timestamp phase đã hoàn tác.

Người dùng yêu cầu video không lời hoặc không nhận được lời vẫn lưu kết quả rỗng, không báo lỗi vì thiếu câu. Thực hiện sau [rollback timestamp](timestamp-rollback/REPORT.md); không khôi phục đợt no-tail/media-clock fade đã hoàn tác.

## Hành vi mới

1. Pipeline vẫn chạy ASR và coverage để tránh bỏ qua những câu có thể phục hồi. Nếu cuối cùng không có câu hợp lệ, xuất SRT/LRC rỗng, trả đúng schema `{"media_id": ..., "segments": []}` và progress 100; không gọi dịch. Không tự chèn “Instrumental”, credit, timestamp giả hoặc dòng chữ giữ chỗ.
2. Bộ lưu chấp nhận **danh sách rỗng**: JSON giữ schema `media_id/original_name/segments`, ASS giữ header/style/events và không có Dialogue. Không thêm schema field hoặc enum status mới.
3. Header-only ASS chỉ hợp lệ khi JSON tương ứng ghi rõ `segments: []`. ASS không có chữ nhưng JSON thiếu/hỏng/null/không đúng schema không bị kết luận là kết quả không lời. JSON rỗng hợp lệ có thể tạo lại ASS bị thiếu và render khi đổi mode.
4. Cache rỗng hợp lệ dùng status READY hiện có, nên mở lại không tự chạy AI hoặc render liên tục. Người dùng vẫn có thể chủ động **Tạo lại Subtitle**; lần đó ghi đè chính bài đã chọn theo workflow cũ.
5. Khi đổi media, xóa cả danh sách cue cũ trước khi chờ AI. Khi nạp kết quả rỗng, xóa text và ẩn overlay, nên callback position không làm chữ bài trước hiện lại. Editor nạp JSON rỗng thành text trống/0 hàng, không fallback hiển thị nguyên JSON.
6. Status ghi **“chưa nhận diện được lời”**, không khẳng định chắc chắn instrumental chỉ vì ASR rỗng. Kết quả lỗi đọc media, ASR/model, xuất file hoặc hủy vẫn đi qua đường lỗi/hủy; không chuyển lỗi kỹ thuật thành empty cache. Coverage tùy chọn lỗi thì giữ kết quả chính theo chính sách đã có, kể cả kết quả chính rỗng.

Bộ lưu phân biệt `None` với `[]`; báo kết quả ghi JSON và controller chỉ báo sẵn sàng khi save trả đường dẫn. Đây là sửa xử lý lỗi ghi có chủ đích: lỗi ghi JSON/ASS không còn bị controller báo thành công. Chưa thay cơ chế persistence bằng atomic/migration hoặc cải tổ worker lifecycle.

## Phạm vi code

- `app/ai/pipeline.py`: thay nhánh “không tìm thấy lời” từ exception thành kết quả rỗng sau exports, trước lời gọi dịch.
- `app/core/subtitle_manager.py`: save/cache/render chấp nhận empty rõ ràng, phân biệt missing/malformed; trả thành công/thất bại khi ghi JSON.
- `app/control/app_controller.py`: clear cue list khi đổi bài, load/hide empty, trạng thái empty và kiểm tra save result.
- `app/ui/subs_ui/subtitle_dialog_logic.py`: nhận `segments: []` hợp lệ khi mở editor.

Snapshot trước patch ở `empty-subtitles/original/`. Source gate dựng expected AST từ các replacement **cụ thể** của bốn file rồi đối chiếu toàn module; không bỏ kiểm tra rộng. Các gate legacy tiếp tục normalize patch này trước khi so captured baseline. Original API/signals/Qt connections giữ nguyên; nguồn ASR/refine kwargs, dịch/fallback/cache keys, IDs/schema và worker không bị migrate.

## Kiểm chứng

**16 regression mới** trong `tests/test_empty_subtitles.py`:

- Empty primary + recovery; toàn credit bị lọc; optional coverage lỗi; không gọi translator; SRT/LRC rỗng; progress/result schema.
- Model/ASR lỗi, cancel và lỗi export vẫn ném lỗi tương ứng.
- JSON/ASS empty round-trip, mở lại không render lại, missing ASS, mọi subtitle mode; malformed/missing data không bị cache thành instrumental.
- `None`/lỗi ghi không tạo completed cache; lưu bài rỗng không đổi bytes bài có lời.
- Qt thật: callback empty, stale result, chuyển bài khi AI chưa xong, mở lại từ cache, force regeneration, save failure, editor 0 hàng.
- **QThread + spawn process + multiprocessing queue thật**, child wrapper trả kết quả ASR được stub thành empty: nhận `data_ready(media_id, [])`, không nhận failed, process/queue cleanup hoàn tất. Đây là kiểm tra truyền kết quả/lifecycle cho empty, không phải chạy model thật trong worker fixture.

**GPU production thật, hai audio tổng hợp 12 s**: im lặng và các hợp âm sine không có giọng. Local large-v3/CUDA, RTX 4060 Laptop; mỗi job một interpreter, không tải model/thư viện, dùng identity translation adapter để chặn dịch mạng/model. Cả hai kết quả 0 cue, SRT/LRC rỗng, JSON/ASS lưu thành công và cache hợp lệ. Chord có một retry coverage vì VAD nhận vùng nhạc là giọng, vẫn giữ empty; diagnostic không phải lỗi và không phải bằng chứng có vocal. [Summary](empty-subtitles/production-summary.json), logs trong `empty-subtitles/silence/` và `empty-subtitles/nonvocal-chords/`; tool `tools/empty_subtitle_probe.py`.

Đây là audio không lời **tổng hợp**, không phải hai video instrumental thật của người dùng. Không gắn nhãn giả cho tám video trong `video/` vốn có kết quả lời ở probe trước. Chưa có corpus instrumental thật được annotate để đo false-positive/hallucination của Whisper; khi model sinh câu giả nhưng vượt bộ lọc thì vẫn có thể có subtitle. Patch này xử lý an toàn **kết quả rỗng**, không phải bộ phân loại mọi nhạc không lời.

Suite đầy đủ: **123 pass +11 skip lịch sử =134 discover**, [test log](empty-subtitles/test-results.txt); `git diff --check` đạt. Kiểm tra SHA-256 **25 file phụ đề thật** trước/sau GPU probe bằng nhau. Toàn bộ file thử chỉ nằm trong docs/temp; không sửa user subtitles/settings/media/models, không build EXE/update. Native playback presentation, instrumental thật, provider dịch, EXE/update còn chờ kiểm chứng.

## Chia câu/hiển thị lyric hiện tại

Giữ nguyên `lyric_refinement` sau rollback: word timestamps, ưu tiên dấu câu/newline/khoảng nghỉ; ngưỡng pause 0,54 s CJK /0,6 s Latin, pause 0,25 s có thể tách cụm đã dài 2 s; chunk boundary là gợi ý mềm. Target 22/74 visual units theo ngôn ngữ, guard 8 s hoặc tối đa min(3×target, 128), tách ở token. Giữ lời lặp với thời gian riêng, không text-only dedup điệp khúc. Finalization chống overlap; onset lead **50 ms**, tail **80 ms**, minimum 20 ms và fade animation cũ không thay ở phase này.

Đây là heuristic chung đã có regression, chưa chứng minh chia đúng cấu trúc lời/nhịp/vocal cho mọi bài. Không tự xác định verse/chorus, không đảm bảo split theo ngữ pháp mọi ngôn ngữ, chưa đo onset/offset với ground truth. UI hiện wrap theo ký tự và hỗ trợ nhiều layer; chưa có metric đọc/độ rộng dòng/đồng bộ native để gọi là chuẩn hoàn chỉnh. Không reapply sửa timestamp đã rollback khi xử lý empty.
