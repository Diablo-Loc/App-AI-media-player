# Báo cáo hoàn tác đợt sửa timestamp — 03/10/2026

Người dùng yêu cầu hoàn tác toàn bộ patch **16 files changed, +361 / −28** trong file đính kèm. Link vscode.dev gửi sau bị lặp URL và công cụ không mở được; phạm vi hoàn tác được xác định bằng nội dung file đính kèm và snapshot local, không suy đoán revision từ link.

## Mốc đã khôi phục

Code trở về trước đợt bỏ tail 80 ms/chuyển fade sang media clock. Đây là mốc đã có sửa coverage đầu bài và subtitle quality, tương ứng phase kiểm tra tài nguyên/lời lặp; không phải code Git gốc trước mọi lần sửa UI/Whisper. Lượt kiểm tra tài nguyên 8 video ×3 chỉ thêm đo/test/docs, không đổi production code, nên production trước/sau lượt đó giống nhau.

Các thay đổi của patch 16 file đã được loại khỏi code/tài liệu hiện hành. Khi bắt đầu rollback, 11 file đã ở trạng thái trước patch hoặc không còn tồn tại; còn 5 file cần hoàn tác:

| File | Kết quả |
| --- | --- |
| `app/pipeline/lyric_refinement.py` | Khôi phục nguyên byte snapshot: onset lead 0,05 s, offset tail 0,08 s; finalization dùng minimum 20 ms như trước patch. Bỏ nhánh mới dành riêng cho interval dương rất ngắn/sub-ms. |
| `app/ui/subs_ui/subtitle_layer.py` | Khôi phục nguyên byte snapshot, cũng không còn diff với Git cho file này. Active interval lại gồm end; dùng fade animation cũ, bỏ `_apply_cue_opacity` và toàn bộ adapter media-clock mới. |
| `app/ai/pipeline.py` | Comment trở lại 50 ms lead / 80 ms tail. Patch trong file đính kèm chỉ sửa comment ở file này; giữ orchestration accuracy có trước đó. |
| `tests/test_asr_coverage.py` | Kỳ vọng production/export trở lại end `4.08`. |
| `tests/test_lyric_refinement.py` | Kỳ vọng cue trở lại end `12.08`. |

11 file còn lại đã được kiểm tra: `tests/test_ui_refresh.py` không còn adapter/exception timestamp mới; `tests/test_subtitle_timing.py`, `tools/subtitle_timing_probe.py`, `docs/SUBTITLE_TIMING_BOUNDARIES.md` không tồn tại; `AGENTS.md`, `docs/FEATURE_PARITY.md`, `docs/PREVIOUS_REFACTOR_AUDIT.md`, `docs/README.md`, `docs/ROADMAP.md`, `docs/SUBTITLE_QUALITY_FIX.md`, `tests/README.md` không còn phần trạng thái của patch timestamp mới. Không xóa các test/report coverage/resource có trước patch.

## Những gì còn giữ

- UI/thumbnail và các sửa layout/playback có trước đợt timestamp.
- Coverage retry khi nghi thiếu lời, cùng model và primary ASR options có trước đợt timestamp.
- Profile chia câu/giữ điệp khúc/lọc filler có trước patch, marker tránh storage padding lần hai, định dạng export và schema/path/media IDs có trước patch.
- Media, models, settings, phụ đề đã lưu và các thay đổi workspace ngoài patch. Không chạy Git reset toàn repository, build/update, download hoặc migrate phụ đề.

Yêu cầu xử lý nhạc không lời/lưu phụ đề rỗng đã được người dùng dừng để ưu tiên rollback; chưa triển khai fix đó trong đợt này.

## Bằng chứng

- `lyric_refinement.py` và `subtitle_layer.py` khớp SHA-256 với `docs/subtitle-timing/original/`; đây là bằng chứng chính xác cho hai implementation đã hoàn tác, không phải cam kết toàn cây giống một revision Git khác.
- **25 file** thật trong `storage/subtitles` có số lượng và SHA-256 giữ nguyên trước/sau rollback: [verification.json](verification.json).
- Full suite bắt buộc: **107 pass +11 skip lịch sử =118 discover**, [test-results.txt](test-results.txt). Skip là kiến trúc refactor đã rollback, không được tính là feature pass.
- `git diff --check` đạt. Source/API/Qt wiring/legacy/storage gates hiện hành đạt theo phạm vi test; chưa chạy lại toàn bộ GUI native/GPU/network/EXE sau rollback, không khẳng định full feature parity bằng unit tests.

Backup các file đang tồn tại trước thao tác rollback nằm trong `before/`. Dữ liệu thử của phase timestamp trong `docs/subtitle-timing/` giữ lại làm lịch sử; các số 118 pass/129 total ở đó không mô tả code hiện hành sau rollback. Báo cáo này là tài liệu mới, không thêm hành vi vào app.
