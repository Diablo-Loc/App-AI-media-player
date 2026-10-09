# Khôi phục lời bị mất đầu bài — 03/10/2026

Tiếp nối theo yêu cầu: [SUBTITLE_QUALITY_FIX.md](SUBTITLE_QUALITY_FIX.md) cải thiện timing/chia câu/lặp cho các lần tạo mới, giữ phụ đề đã lưu. Các số liệu và lời khẳng định “cue cũ giữ nguyên text/time” trong tài liệu này mô tả **đợt coverage đầu tiên**, không phải profile quality mới. ASR chính vẫn giữ kwargs; coverage hiện được inject profile mới và biên mềm, mặc định API helper vẫn tương thích profile legacy.

Người dùng yêu cầu ưu tiên accuracy Whisper trước việc tối ưu/refactor toàn app. Đã tái hiện trên `video/人生エンドロール.mp4`, người dùng xác nhận có lời hát trước giây 30. Đây là thay đổi accuracy có chủ đích; không áp lại refactor kiến trúc đã rollback.

## Nguyên nhân được tái hiện

Whisper large-v3 trả về một dòng giống credit ở 5,52–28,36 s, thay vì lời hát. Bộ lọc gốc loại dòng đó vì chứa các từ credit, nên cue đầu sau refine bắt đầu **30,2 s**. Xác suất no-speech của segment đó chỉ 0,0664: lỗi video mẫu không phải nhánh no-speech skip. Không sửa bằng cách giữ credit hoặc kéo cue ở giây 30 về giây 0.

Nhận diện cùng audio bằng clip 0–12 s và 10–24 s lấy được hai câu hát đầu. Bỏ prompt hoặc tắt word timestamps trên một cửa sổ 30 s vẫn không khắc phục đầy đủ. Runtime được đối chiếu cả mã cài sẵn và [source chính thức faster-whisper v1.0.2](https://github.com/SYSTRAN/faster-whisper/blob/v1.0.2/faster_whisper/transcribe.py): ASR có thể fast-forward cả cửa sổ khi nhận định không có giọng nói; đây là một nguyên nhân khác cần cover, không phải nguyên nhân đã xác nhận của file mẫu.

## Bản sửa

`app/pipeline/asr_coverage.py` nhận model đang dùng và cue đã refine. Tìm khoảng trống từ 4 s ở đầu/giữa/cuối, dùng Silero VAD local để chọn vùng nghi có giọng; VAD không cắt audio của lượt ASR chính. Nhận diện lại bằng clip tối đa 12 s, chồng 2 s; một vòng thứ hai dùng clip sát vùng giọng ngắn còn thiếu. Slice waveform thực tế, kiểm tra words không vượt audio clip và quy đổi offset về timeline gốc.

Lượt bổ sung dùng ngôn ngữ đã phát hiện, beam 3/temperature 0/word timestamps; bỏ prompt ` .+` và không áp no-speech skip. Các tham số của lượt ASR chính, model-loading/fallback order và refine gốc giữ nguyên. Cũng sửa nhánh CPU fallback lấy `language` từ info của lần fallback, tránh biến chưa được gán khi CUDA lỗi sớm.

Cue cũ luôn được giữ nguyên text/time, kể cả điệp khúc. Candidate chỉ được thêm vào vùng trống, qua filter gốc, confidence và kiểm tra giọng hỗ trợ ít nhất nửa duration. Không thêm credit cảm ơn/xem video hoặc những chuỗi chỉ có tiếng ngân không đủ chứng cứ; không xóa các câu như vậy nếu chúng đã có trong kết quả gốc. Có đánh đổi: một câu hát thật chỉ gồm “Thank you” hoặc toàn “la/oh” bị bỏ sót ở lượt chính sẽ không tự được bổ sung bằng heuristic này.

Giữ offsets/padding/SAFE_GAP của refine gốc. Đệm cuối của **cue bổ sung** được giới hạn tại biên khoảng trống để không đẩy timestamp cue cũ; tail mới giới hạn theo duration audio. Giữ ký tự CJK có word duration bằng 0, bỏ timestamp đảo/NaN và kết quả vượt clip. Không đổi cache key/schema/subtitle mode, prompts dịch, provider, AI spawn hay UI lifecycle.

Model chỉ được giải phóng sau khi kiểm tra coverage; cùng model dùng cho retries, không nạp model thứ hai. Nếu không có khoảng trống thì không decode audio/VAD/ASR bổ sung. Có gap nhưng không có giọng thì không gọi lại Whisper. Retry lỗi giữ kết quả chính và ghi diagnostic; hủy vẫn được truyền ra và WAV tạm vẫn được cleanup. Đây không phải tối ưu tốc độ: retries tăng công việc khi cần accuracy.

## Kiểm chứng

Windows, Python 3.11.0, portable faster-whisper 1.0.2/CTranslate2 4.8.1, local large-v3, CUDA float16, RTX 4060 Laptop 8 GB. Không cài/nâng thư viện hay tải model. Chỉ đọc media hiện có; audio vào thư mục tạm, output thử vào `docs/asr-coverage/`, không sửa phụ đề/settings/media người dùng.

| Video thực tế | Duration | Cue gốc → mới | Cue gốc giữ nguyên | Cue đầu trước → sau |
| --- | ---: | ---: | --- | ---: |
| 人生エンドロール | 203,487 s | 27 → 30 | 27/27, cả text/time | 30,2 → **5,68 s** |
| Unwavering Startorch | 232,989 s | 35 → 35 | 35/35 | Không đổi |
| Brand New Sky | 217,070 s | 49 → 49 | 49/49 | Không đổi |

Xem [so sánh cuối](asr-coverage/comparison-strict.json) và `asr-coverage/verified-strict/`. Các thư mục `intro-tests`, `slices`, `verified`, `recovery-prefix` là thử nghiệm trước validator cuối. `recovery-prefix` ban đầu dùng ASR prefix 45 s nhưng recovery đọc WAV toàn bài; đã sửa tool để WAV cũng bị giới hạn khi dùng `--prefix-seconds`. Không dùng kết quả đó làm so sánh baseline toàn bài cuối.

Probe đầu tiên có 197,2 s ASR, các lượt sau warmed có 8–9 s; GPU/memory/runtime thay đổi nên không coi đây là benchmark tăng tốc. Operation counts cuối: video lỗi 9 retries, hai đối chứng 6 và 5 retries. Các retries đối chứng bị loại, tránh thêm “Thank you”/credit/“Oh” do model sinh trong đoạn nhạc. Cần đo workload rộng hơn trước điều chỉnh budget hoặc threshold.

Đường production thật **extract → model → ASR → refine → coverage → SRT/LRC → Subtitle objects** đã chạy trên video lỗi, cho 30 cue. Probe bypass translation để không gọi API/NLLB và không dùng API key. [SRT thử](asr-coverage/production/subtitles/source/srt/人生エンドロール.srt), [objects thử](asr-coverage/production/人生エンドロール-production.json). Không coi đây là kiểm chứng dịch toàn pipeline hoặc UI/native/EXE.

Suite bắt buộc: **74 pass + 11 skip lịch sử = 85 test discover**, `git diff --check` đạt. 19 regression ASR mới: đầu/giữa/cuối, empty pass, nhạc dạo, credit/filler, confidence/timestamp, CJK zero duration, giữ cue cũ, cancel/error, exports/schema/model count, CPU fallback. Fixture source khớp hash baseline; normalizer loại đúng adapter/move cleanup/fallback language rồi đối chiếu toàn bộ AST luồng gốc. 60 source gốc ngoài UI khác giữ nguyên hash; `app/ai/pipeline.py` chỉ có thay đổi accuracy được review trong hàm chính và import helper.

## Giới hạn và bước dùng

Không cam kết 100% chữ đúng/đủ cho mọi video. VAD có thể nhận nhạc/echo là giọng hoặc bỏ sót giọng hát nhỏ; model có thể nhận sai với confidence cao. Các probe còn ghi `unresolved_speech`: vùng nghi vấn, không tự khẳng định đều là lời bị mất. Cần nghe/đối chiếu lyrics reference để xác nhận, đo CER/WER và đánh giá soft vocals/nhạc lớn/multi-language trước mở rộng patch. Không thay thuật toán bằng cách chèn phụ đề vào mọi khoảng im lặng.

Mở lại app từ thư mục gốc bằng `.\venv\Scripts\python.exe app\run_app.py`, chọn video và dùng **Tạo lại Subtitle** để chạy lại AI; subtitle đã lưu không tự bị ghi đè trong đợt sửa code. Startup plain `python` trước đó trỏ tới Python hệ thống bị lỗi QtGui; venv import Qt sau bootstrap đã kiểm tra đạt. `run_app.py` chưa được sửa, lỗi phụ excepthook được hoãn khi người dùng chuyển ưu tiên sang ASR.
