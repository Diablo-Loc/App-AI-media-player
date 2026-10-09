# Timing, chia câu và giữ lời lặp — 03/10/2026

04/10/2026: grouping của lần tạo mới được chỉnh tiếp để giữ ASR lines ngắn, giảm cắt vụn và xử lý newline đúng; mốc 8 giây chuyển thành gợi ý cần pause, không ép cắt sustained note. Timing margins/finalizer/fade và các filters vẫn giữ mốc rollback. Mô tả grouping/8-second hard guard phía dưới là lịch sử phase trước. Xem [LYRIC_PHRASE_GROUPING.md](LYRIC_PHRASE_GROUPING.md).

Đợt mới xử lý completed ASR rỗng mà không đổi chia câu/timing/fade sau rollback: [EMPTY_SUBTITLE_RESULTS.md](EMPTY_SUBTITLE_RESULTS.md). Source gates manager/pipeline normalize thêm các edit empty cụ thể; suite hiện tại 123 pass +11 skip. Các con số/phạm vi nguồn phía dưới mô tả phase quality trước đó.

Kiểm tra tiếp theo đã đo 8 video ×3, ghi chi phí coverage/RAM và stress lặp 30/100, giữ câu thật 2/3 lần; không đổi production code. Xem [ASR_RESOURCE_AND_REPEAT_CHECK.md](ASR_RESOURCE_AND_REPEAT_CHECK.md). Các số 103/114 dưới đây là suite của phase sửa quality; suite sau kiểm tra là 107 pass +11 skip (118 total).

Người dùng cho phép cải thiện chất lượng phụ đề mới, yêu cầu phụ đề đã lưu không bị thay đổi khi cập nhật app. Đây là thay đổi accuracy riêng, tiếp nối [coverage đầu bài](ASR_COVERAGE_FIX.md), không phải refactor kiến trúc hoặc thay model. Không có nhánh theo tên video, media ID, lời bài mẫu hoặc ngôn ngữ cụ thể để sửa một bài.

## Lỗi xác nhận từ code và regression

- Aligner gốc tính `start - start_offset`; với offset −0,2 s, câu thực tế bị **đẩy muộn 0,2 s** so với word onset.
- Aligner chia theo ký tự/pause trong từng ASR segment, rồi flush ở cuối segment. Có thể cắt cụm từ hoặc tạo mảnh câu ngắn.
- Chống overlap chia midpoint của **timestamp đã padding**, làm dịch cả onset câu sau. Sau đó ép duration ít nhất 350 ms, có thể tạo overlap trở lại ở câu ngắn.
- `SubtitleManager._clean_segment` thêm ±100 ms khi lưu object AI, dù refine đã padding. Khoảng SAFE_GAP 120 ms không đủ chống phần padding tổng cộng 200 ms này.
- Fuzzy/text-only dedup coi hai câu hát giống nhau, gần nhau là duplicate. Regex lặp mọi chuỗi 1–4 ký tự cũng có thể cắt từ/lời thật.
- Weak bad-word filter loại lời ngắn như **“I love you.”** hoặc **“Music”** dù có word timestamps; credit mạnh và lời ngắn cần khác quy tắc.
- SRT truncate float có thể xuất 14,349 thay vì 14,350. LRC/ASS làm tròn giây sau khi đã lấy phút có thể sinh `00:60.00` ở rollover.

## Đường tạo phụ đề mới

`app/pipeline/lyric_refinement.py` cung cấp `refine_lyrics`. Pipeline production dùng profile này cho lượt chính và inject cùng hàm vào lượt coverage. `refine_segments` legacy vẫn tồn tại; mặc định và toàn bộ luồng gốc giữ nguyên, chỉ thêm tham số tùy chọn `allow_short_lyrics=False` để profile mới giữ lời ngắn có word timestamps hợp lệ. Các bộ lọc credit mạnh của baseline vẫn áp dụng.

Timestamp bám vào word đầu/cuối; display lead **50 ms**, tail **80 ms** dùng chung, không dùng offset/padding lớn theo ngôn ngữ. Đây là margin trình bày, không phải phép đo onset/offset chuẩn từ waveform. Thiếu words thì fallback giữ text và segment times, không tự suy ra timestamp từng từ.

Chia câu ưu tiên punctuation kết câu, newline, pause thật; ASR segment boundary là gợi ý mềm khi cụm trước đã dài khoảng 3 s. Pause 250 ms có thể tách cụm đã dài 2 s. Character target là mềm; hard guard tối đa 8 s/128 visual units hoặc 3× target, tách ở token boundaries. Các abbreviations/initials quen thuộc không tự kết câu. CJK nối liền, Latin/Korean giữ khoảng cách; dấu câu không bị thêm khoảng trắng trước. Đây là heuristic đọc phụ đề, chưa phải bộ phân tích ngữ pháp cho mọi ngôn ngữ.

Duplicate chỉ bị loại khi text chuẩn hóa giống nhau **và** acoustic spans overlap ít nhất 85% cả hai, chênh hai endpoint không quá 20 ms. Hai câu có thời gian riêng vẫn giữ; zero-duration CJK words không bị dedup. Với token boundary trùng giữa hai ASR segments, loại cùng từ trên cùng span, không loại lần hát kế tiếp.

Lọc runaway riêng: fused filler từ 8 đơn vị như `hahahahahahahahaha` rút còn 3; filler tách từ chỉ rút khi từ 8 lần cùng token/source và timestamp bị kẹt trên cùng interval. **Ha/la có timestamp tiến dần vẫn giữ**, meaningful words/phrases không bị regex cắt lặp. Không thể phân biệt mọi hallucination và lời thật chỉ bằng text/timestamps.

Sau refine và coverage, `finalize_cue_times` kiểm tra finite/order/duration; outgoing end bị giới hạn tại incoming start, không dịch cả hai về midpoint và không ép lại 350 ms. Nếu hai cue có cùng onset không thể hiển thị tách thì nối text, không xóa lời. Tail giới hạn theo duration audio. Lượt recovery cho phép jitter tối đa 80 ms ở **từ cuối bắt đầu trong khoảng trống**; display end vẫn clip tại cue tiếp theo, gap bắt buộc 120 ms của profile legacy không áp vào profile mới. Regression giữ đủ “壊れた世界” thay vì mất “世界” khi onset câu sau được đưa sớm hơn.

`mark_final_timing` đánh dấu object **sau dịch**, dùng thuộc tính runtime `_botube_final_timing`. Marker đi qua pickle/queue của worker; không thêm field vào JSON/index. `_clean_segment` chỉ bỏ padding lần hai cho object có marker; object legacy không marker giữ đúng contract cũ. Prompts/provider/fallback/cache của dịch không đổi.

`app/subtitle/timing_format.py` làm tròn tổng đơn vị trước rồi divmod giờ/phút/giây, dùng chung ở SRT/LRC/ASS. SRT millisecond, LRC/ASS centisecond; không phải tăng độ phân giải thực của Whisper. File đã tồn tại không được tự mở để đổi format. Nếu render lại ASS từ JSON cũ, rollover được xuất hợp lệ; text và source timestamp JSON vẫn nguyên.

## Phụ đề cũ và cập nhật

- Đường đọc/cache/media ID/path/schema/index/controller không đổi; chọn bài có ASS hợp lệ vẫn READY, không chạy ASR/profile mới.
- JSON cũ không bị migrate, realign hoặc padding thêm khi đọc. Nếu thiếu ASS, render từ **timestamp đã có trong JSON**, không chạy refinement.
- Bài chưa có phụ đề sẽ dùng profile mới khi AI chạy; bài cũ chỉ thay kết quả nếu người dùng chủ động **Tạo lại Subtitle** hoặc sửa/lưu trong editor như workflow cũ. Tạo lại vẫn ghi đè phụ đề của bài đó theo chức năng hiện có.
- Cần giữ thư mục `storage` ở vị trí portable hiện tại khi thay app. Source review nhánh Windows `update_helper.bat` thay EXE/version, không di chuyển `storage/subtitles`; nhánh patcher hoặc gói cập nhật khác chưa được chạy kiểm chứng. Không build, chạy updater, phát hành hoặc đổi packaging trong đợt này.

## Kiểm chứng

Windows, venv Python 3.11.0; GPU probes dùng local large-v3, faster-whisper 1.0.2/CTranslate2 4.8.1, CUDA float16, RTX 4060 Laptop 8 GB. Không tải/cài thư viện/model, không gọi provider dịch hoặc ghi QSettings/user storage. Tất cả output thử ở `docs/subtitle-quality/` hoặc thư mục tạm.

Replay cùng raw ASR đã capture để tách tác động refine khỏi tính biến thiên của nhận diện:

| Bộ ASR thật | Cue gốc → mới (trước coverage) | Cặp overlap sau save cũ → mới | Inventory ký tự nhận được giữ nguyên |
| --- | ---: | ---: | --- |
| Brand New Sky | 49 → 37 | 38 → 0 | Có |
| Unwavering Startorch | 35 → 33 | 20 → 0 | Có |
| 人生エンドロール | 27 → 25 | 16 → 0 | Có |

Số cue giảm do nối mảnh câu, không đồng nghĩa mất lời. Inventory so theo normalization/ký tự và số lần xuất hiện, không phải WER/CER hoặc xác nhận ngữ nghĩa. Xem [comparison](subtitle-quality/replay/comparison.json), SRT/LRC/JSON/ASS ở `subtitle-quality/replay/`. 74 cặp overlap cũ ở đây tính trên **saved timing**, không phải raw ASR có 74 lần hai giọng hát chồng nhau.

Đường production **extract → model → ASR → refine → coverage → SRT/LRC → objects → JSON/ASS** chạy trên cả ba video: 28 / 33 / 37 cue tương ứng 人生エンドロール / Startorch / Brand. Video mẫu giữ 3 cue phục hồi, cue đầu 5,43 s, từ cuối gần biên giữ đầy đủ. Hai đối chứng không thêm cue recovery. Probe bypass dịch bằng adapter identity; không phải xác nhận chất lượng dịch hoặc renderer native trên màn hình. Saved JSON times bằng object times, không overlap. Kết quả cuối: `subtitle-quality/final-production/`, logs `final-*-log.txt`.

Tool multi-media production thử đầu tiên gọi nhiều job trong một interpreter gặp PyO3/tokenizers reimport ở job thứ hai. Worker app vốn mỗi job một spawn process; các probe sau chạy mỗi video bằng CLI/process riêng, giữ lifecycle thật, không sửa sys.modules/DLL cleanup của app để khắc phục tool. `production/` và `production-*-log.txt` là thử nghiệm trước biên/timestamp formatter cuối; dùng **final-production**, không dùng output thử đầu để xác nhận bản cuối.

Suite bắt buộc cuối: **103 pass + 11 skip lịch sử = 114 discover**, 29 regression mới, [log](subtitle-quality/test-results.txt); `git diff --check` đạt. Kiểm tra bao gồm lặp gần nhau/overlap ASR, filler có/không tiến timestamp, short lyrics, CJK zero-duration, câu 1 ký tự, punctuation/newline/soft boundaries, nhiều interval ngắn, nonfinite/unsorted, recovery biên, pickle marker, old subtitle bytes không đổi khi mở/lưu bài mới, missing ASS từ JSON cũ, timestamp rollover và legacy default tương đương source capture.

56 source baseline ngoài UI khác giữ hash; 5 source cũ có thay đổi được kiểm tra AST có giới hạn: pipeline chỉ orchestration accuracy, aligner chỉ optional weak-filter guard, manager chỉ final-timing marker guard, formatter/renderer chỉ time-format bodies và import. Không bỏ source gate rộng để test xanh. Primary Whisper kwargs, translation/fallback/cache/worker/controller/lifecycle và schema vẫn được đối chiếu.

## Giới hạn còn lại

Chưa có reference lyrics/onset/offset thủ công từ người dùng; **không khẳng định mọi bài hết lệch hoặc chia ngữ pháp hoàn hảo**. Word times của Whisper vẫn có thể sai, hát kéo dài/nhạc lớn/đối đáp/multiple voices khó; nguyên tắc không overlap có thể cắt một phần tail khi hai vocal thật chồng nhau. Critical credit heuristics legacy vẫn có thể loại lời thật chứa các từ đó. Recovery vẫn bảo thủ với thank-you/nonlexical-only candidates và chỉ chọn gap ≥4 s như đợt trước; không cam kết bổ sung được mọi lần lặp Whisper chưa nhận ra. Cần waveform/lyrics reference cho bước forced-alignment/threshold tuning tiếp theo; không tự cài WhisperX/stable-ts hoặc tải alignment models.

Không benchmark tốc độ hoặc tuyên bố app mượt hơn từ patch accuracy này. Kiểm chứng dịch thật/native playback/EXE/update installation còn chờ. Bản sửa chung áp dụng cho các lần tạo mới; dữ liệu đã lưu được bảo toàn theo đường đọc hiện có.
