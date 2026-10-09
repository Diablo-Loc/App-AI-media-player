# Chia lyric theo câu/cụm hát — 04/10/2026

Người dùng xác nhận lỗi cần sửa là **một câu bị cắt vụn hoặc hai câu bị ghép chung**. Đợt này chỉ thay quy tắc nhóm các từ đã được ASR chấp nhận cho **lần tạo phụ đề mới**. Không sửa renderer, chế độ ngôn ngữ, fade, Whisper options, coverage/VAD, bộ lọc credit/lặp, dịch hoặc cache/load/schema. Không phục hồi timestamp phase đã rollback.

## Nguyên nhân và sửa đổi

Profile trước chỉ tách ở ranh giới ASR nếu cụm trước dài ít nhất 3 giây. Hai dòng hát ngắn hơn có thể bị nối lại. Trong một ASR segment, pause 250 ms sau 2 giây hoặc đạt character target cũng có thể cắt một câu thành mảnh. Hard guard dùng **end của từ sắp thêm** khi vượt 8 giây khiến từ kéo dài bị đẩy sang cue khác ngay giữa câu.

`app/pipeline/lyric_phrases.py` đảm nhiệm nhóm từ; `lyric_refinement.py` vẫn sở hữu việc nhận/lọc/dedup và hoàn thiện thời gian:

- Dấu kết câu, newline ở đúng đầu/cuối token và pause rõ theo threshold hiện có được ưu tiên. Viết tắt như `Dr.` vẫn giữ quy tắc cũ.
- Ranh giới ASR được giữ khi hai bên là cụm đủ dài: duration 1,5 giây và ít nhất 4 visual units. Fragment rất ngắn được nối lại; đoạn ASR tiếp nối có từ trùng trên cùng acoustic span không bị xem là câu mới. Hai câu lặp giống nhau có thời gian riêng có thể tách dù ngắn hơn 1,5 giây.
- Không cắt chỉ vì một breath nhỏ 250 ms hoặc chạm 8 giây trong một câu. Mốc 8 giây là gợi ý mềm, cần thêm pause ít nhất 120 ms. Điều này có thể giữ một cue dài hơn 8 giây khi ASR thiếu mọi tín hiệu chia câu.
- Character target vẫn mềm; cụm quá dài được chia cân đối tại word boundaries, ưu tiên dấu phẩy/khoảng nghỉ, thay vì để lại vài từ ở cuối. Giới hạn đọc hiện có là `min(3 × max_chars, 128)`, tối thiểu 8 visual units. Từ không thể chia hoặc các onset không phân biệt được có thể vượt giới hạn; không bịa timestamp.
- Newline đứng trước từ tách **trước từ đó**, không tách sau như profile trước. Newline nằm giữa một token không có timing riêng được chuyển thành khoảng trắng; không đoán timing cho hai phần.
- Khi không có word timestamps, giữ nguyên text/time cả segment. Không chia đều thời gian để tạo cảm giác chính xác giả.

Việc đổi grouping cố ý đổi số cue và thời điểm chuyển giữa những cue mới. Onset vẫn lấy từ đầu trừ **50 ms**, end từ cuối cộng **80 ms**; `finalize_cue_times`, marker tránh padding lần hai, chống overlap và fade **giữ nguyên source**. Khoảng nghỉ rõ giữa các cụm vẫn để trống, không nối dài end qua vài giây im lặng.

## Đối chiếu cụ thể

| Dữ liệu raw ASR | Trước | Sau |
| --- | --- | --- |
| Brand New Sky, khoảng 44,89–50,27 s | `There's a world behind the fear So it can make me feel alive` chung một cue | Hai cue theo hai đoạn ASR: `There's a world behind the fear` / `So it can make me feel alive` |
| 人生エンドロール, 87,77–92,64 s | `主人公じゃないから` / `見合わないのに` bị cắt tại breath 280 ms | Giữ chung `主人公じゃないから見合わないのに` |
| Unwavering Startorch, 55,99–67,21 s | Cắt ngay giữa `I'll tell` / `it our hardship is to learn` do mốc 8 s | Giữ toàn bộ đoạn ASR; **chưa xác định được ranh giới hai mệnh đề** vì raw words không có pause/dấu câu |

Các ví dụ là kiểm tra grouping dựa vào ASR có sẵn, không phải lời hoặc onset/offset đã được người nghe gán nhãn.

## Kiểm chứng

- Full discovery bằng Python 3.11 của dự án: **152 pass +11 skip lịch sử, 163 total**, 22,452 s; `git diff --check` đạt. [Log](lyric-phrases/test-results.txt).
- 14 regression mới: EN/VI/JP/KO, câu ngắn liền nhau, điệp khúc ngắn không dấu câu, fragment đầu/cuối, sustained note, breath nhỏ, khoảng nghỉ thật, newline trước/trong token, cân đối cụm dài, fallback thiếu word times, hai trường hợp raw thật, source gate và Qt active cue/multilanguage. Cả 14 đạt thêm ở DPI 200%: [log](lyric-phrases/dpi2-tests.txt).
- Replay **24 bộ ASR đã ghi từ 8 video local**, ba lần/video. Giữ nguyên chữ chuẩn hóa **và thứ tự** so với profile trước trên cả 24 bộ; không overlap; thời gian nằm trong media duration; SRT/LRC export và object→JSON/ASS save riêng đạt, timestamp đã lưu bằng timestamp refined. Tổng cue 801→921 do đổi grouping, không phải thêm lời. [Bảng dữ liệu](lyric-phrases/comparison.json), [trước/sau và bản xuất](lyric-phrases/replay/).
- **27 file** trong `storage/subtitles` giữ hash trước/sau probe. Probe chỉ ghi output ở docs và save ở thư mục tạm; không tự sửa dữ liệu bài cũ. [Hash](lyric-phrases/saved-hashes.json).
- Median chạy refinement 5 lần/dataset: **2,37–63,65 ms** trên môi trường local, không gồm ASR/dịch/coverage. Đây là số đo chi phí của profile mới, không phải benchmark cải thiện tốc độ hoặc FPS.
- Snapshot trước sửa trùng source rollback; gate chỉ bỏ đúng bốn adapter đã review (import helper, docstring, newline event, grouping) rồi yêu cầu toàn bộ source khớp snapshot. Bộ lọc, 50/80 ms, finalizer/marker còn bị gate nguyên vẹn. [Manifest](lyric-phrases/reviewed-edits.json). Các gates cũ cho ASR options, storage/controller, API/signals/UI/playlist tiếp tục đạt.

## Bài đã lưu và giới hạn

Mở bài đã có phụ đề tiếp tục dùng cue đã lưu; cập nhật app **không tự chia lại**. Bài tạo mới dùng grouping mới. Muốn áp dụng cho một bài cũ thì chủ động dùng **Tạo lại Subtitle** của app; thao tác này chạy lại AI và thay kết quả của chính bài đó theo workflow hiện có.

Renderer hiện đã chọn một active cue mỗi lượt, nên không cần đổi lifecycle. Chọn 2–3 ngôn ngữ vẫn có thể hiện nhiều dòng của **cùng một cue**; cue dài cũng có thể wrap. Đợt này không ép mọi mode thành một hàng chữ.

Không có cơ sở hứa mọi câu hát đều tách đúng ngữ nghĩa khi ASR thiếu dấu câu, sai words hoặc thiếu timestamp. Các cue dài, hai mệnh đề liên tục không có dấu nghỉ, nghĩa/dịch và timing tai người vẫn cần reference/listen review. Replay không chạy mới model/GPU hoặc online translation; native/EXE/update chưa kiểm chứng trong đợt này. Không thêm dependency/model/parser hay lượt nhận diện lại để chia câu.
