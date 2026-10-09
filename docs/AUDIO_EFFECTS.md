# Âm thanh tùy chọn — 04/10/2026

**Đường cân bằng đã được thay bằng gain trực tiếp**, theo lựa chọn mới của user để tránh reload và giữ phổ âm. Xem [AUDIO_NORMALIZATION_REALTIME.md](AUDIO_NORMALIZATION_REALTIME.md) cho hành vi hiện tại, target −14/−18 và kiểm chứng mới. Bản dẫn xuất/EQ và số đo dưới đây mô tả **phase v1**; EQ vẫn giữ riêng với giới hạn reload được ghi rõ. Mặc định tính năng vẫn tắt.

Người dùng yêu cầu thêm nút cạnh âm lượng, cân bằng độ lớn giữa video và chỉnh chất âm, giữ chức năng cũ; đã chọn **tắt mặc định, bật khi cần**. Đã triển khai trong baseline hiện hành, không áp lại refactor lịch sử hoặc nâng dependency.

## Sử dụng

Nhấn icon thanh chỉnh **Âm thanh** ngay bên phải nút loa. Popup có:

- **Cân bằng âm lượng giữa các bài**: gain cố định theo độ lớn cảm nhận toàn bài, không compressor/AGC đẩy–hạ âm lượng trong từng câu.
- **Nguyên bản / Dịu — giảm chói / Cân bằng nhẹ**: hai EQ nhẹ chỉ cắt các dải cao, không tăng bass/treble cực đoan.
- Trạng thái chuẩn bị nền và nút **Trở về âm thanh gốc** để tắt cả hai tùy chọn. Icon xanh khi tùy chọn bật, trở lại màu thường khi tắt.

Bài đang phát tiếp tục dùng bản hiện tại trong lúc chuẩn bị; chỉ áp dụng khi hoàn tất. Tùy chọn ghi riêng trong `storage/audio-effects.json`. Khi bật, được giữ cho các bài tiếp theo/lần mở sau; cài đặt cũ không bị ghi lại. File không có audio, nguồn không phải file local, lỗi tool/định dạng, hết dung lượng hoặc cache không nạp được đều giữ/trở về đường phát gốc, không báo thành công giả.

## Quyết định chất lượng và kiến trúc

128 kbps không thể khôi phục thành chất lượng của bản FLAC gốc đã thu: thông tin bị loại khi nén không còn để khôi phục. EQ làm thay đổi màu âm theo sở thích, không chứng minh mọi bài/tai nghe đều hay hơn. UI ghi rõ giới hạn này.

Chọn bản phát dẫn xuất thay vì thay engine/đổi tuyến audio sang player thứ hai. FFmpeg đo và xử lý trên worker; video, audio track khác, metadata và chapters được stream-copy, chỉ audio track đang chọn được áp gain/EQ và lưu FLAC 24-bit trong Matroska. Không thêm vòng mã hóa mất dữ liệu; không đổi sample rate hay cố upsample để quảng cáo chất lượng. Với sample rate thấp, tần số EQ được giới hạn dưới Nyquist. Không sửa file nguồn hoặc bản tải xuống. Matroska dùng đơn vị timestamp 1 ms; phép làm tròn có thể khác dưới 1 ms so với container nguồn.

Giữ đúng một `QMediaPlayer`, `QAudioOutput` và video output của app. Nút mới không đổi thiết bị, volume, mute hay native engine/SMTC. Giữ source gốc riêng để playlist/ID/cache phụ đề tiếp tục theo media gốc. Chuyển bản phát giữ vị trí, tốc độ, play/pause, audio/video/subtitle tracks và loops; xử lý lựa chọn mới nhất, lỗi trong callback restore và callback sang bài tiếp theo. **Bật/tắt giữa bài có một lần nạp lại source và có thể ngắt ngắn**; đây không phải crossfade DSP tức thời. Floating lyric được ẩn trong khoảng chuyển rồi trở lại câu tại vị trí khôi phục, không lóe câu đầu bài. Popup âm thanh cũng chặn overlay theo guard hiện có.

| Thành phần | Trách nhiệm |
| --- | --- |
| `app/core/audio_profile.py` | Profile hợp lệ, gain/headroom/EQ; không Qt/network/model |
| `app/core/audio_effects.py` | Probe/measurement/render, chữ ký cache, publish atomic, bounded eviction và journal partial |
| `app/control/audio_effects.py` | Worker/process ownership, latest request, original/source transition, preference riêng |
| `app/ui/audio_effects_panel.py` | Popup Widgets, trạng thái và reset |
| PlaybackBar/MainWindow | Thêm nút, install/shutdown, giữ thanh hiện khi popup mở |

Giữ namespace import mà entry point baseline đang chạy dùng (`core`, `control`, `ui`); không tự migrate sang kiến trúc `app/bootstrap/application.py` đã rollback. API Qt mới như `QAudioBufferOutput` không được yêu cầu. Không nâng Qt/Python/CUDA hoặc sửa hook.

## Chính sách âm lượng

- Mục tiêu **−18 LUFS**, đo loudness/true peak sau EQ bằng `loudnorm`; đầu ra chỉ dùng EQ + `volume` cố định, **không** chạy dynamic loudnorm/compressor/limiter.
- Gain tăng tối đa **12 dB**; headroom **−1,7 dBTP** (0,2 dB dự phòng so với mức −1,5). Nếu đỉnh giới hạn gain, popup nói rõ chưa tới mục tiêu. Bài rất nhỏ hoặc có dynamic range lớn có thể vẫn nhỏ hơn bài khác; ưu tiên tránh clipping và giữ độ động.
- Silence hợp lệ giữ gain 0; số đo thiếu/NaN không được coi là thành công. EQ “Dịu”: −2,5 dB quanh 3,2 kHz và treble −1,5 dB từ 8 kHz; “Cân bằng nhẹ”: −1,2 dB quanh 3,5 kHz, treble −0,7 dB từ 10 kHz.

Tham khảo chính thức: [FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm), [equalizer](https://ffmpeg.org/ffmpeg-filters.html#equalizer), [QMediaPlayer Qt 6.7](https://doc.qt.io/archives/qt-6.7/qmediaplayer.html). Icon `sliders-horizontal` vendored từ revision Lucide đã dùng; 40 icon trước giữ nguyên SHA và license.

## Tài nguyên và cache

Một worker, tối đa một ffprobe/FFmpeg tại một thời điểm; cấu hình một decode/filter/audio-encode thread và Windows below-normal priority, không cửa sổ console. Không chờ worker/process trên GUI khi dùng bình thường; shutdown hủy rồi chờ owner kết thúc, không `QThread.terminate`. Hủy/đổi bài/tùy chọn bỏ kết quả cũ. Cache-hit không khởi động FFmpeg; Qt giải mã file dẫn xuất như một nguồn phát bình thường, không giữ toàn bộ PCM trong RAM.

`storage/audio-playback-cache` có giới hạn **1 GiB bản hoàn tất** và LRU; bảo vệ bản đang phát. Dự toán cả video + PCM 24-bit trước khi chạy và kiểm tra dung lượng trống. Một partial có thể dùng thêm tới giới hạn đó trong lúc render; FLAC/container tăng dung lượng so với audio nén gốc. Bài/file quá lớn hoặc không đủ headroom ổ đĩa giữ nguồn gốc. Chữ ký gồm resolved path, size, mtime_ns, profile, audio ordinal và processor version; đổi nguồn/tùy chọn/track không dùng nhầm cache.

Chỉ evict file tên hash có sidecar đúng marker/key trong đúng cache root; không xóa file lạ/symlink/file nguồn. Partial có journal gắn tên chính xác và PID/create_time của app; lần chuẩn bị tiếp theo dọn partial của app đã thoát, giữ job còn sống và journal/file lạ. Nếu xóa không được, giữ lại an toàn. Sidecar publish atomic; JSON malformed/thiếu gain/version là cache miss. Cache hỏng khi Qt nạp sẽ fallback gốc. Một số codec subtitle/data không mux được vào Matroska có thể fallback; không âm thầm bỏ track để ép thành công.

## Kiểm chứng

Môi trường có sẵn: Python 3.11.0, Qt/PySide6 6.10.1, Windows, 20 logical CPUs; không cài/nâng dependency. **240 tests: 229 pass +11 skip lịch sử**; **59 tests đạt DPI 200%** (26 audio + stability/spacing/subtitle presentation). Log: [discovery](audio-effects/test-results.txt), [DPI](audio-effects/dpi-200-tests.txt), [audio](audio-effects/focused-tests.txt). `git diff --check` đạt.

26 audio regressions gồm policy gain/silence/malformed metadata; LRU/current/foreign/path protections và crash partial ownership; nguồn 128k thực sinh qua FFmpeg; video packet hash giữ nguyên, đo lại loudness/peak; giảm dải 3,2 kHz bằng tín hiệu hai tone; audio 8 kHz/cancel/bad file; Qt worker supersession/shutdown và popup/lyric/restore callbacks. **Qt decoder thật**, có mute, xác nhận original → cache → original giữ vị trí, pause/play/rate, volume/mute/device và cùng video/audio owners; không chỉ dựa vào FakePlayer.

Probe riêng đọc đủ **8 video hiện có**, tổng nguồn **198,24 MiB**, dài 143–255 s/bài, profile normalize + gentle; file dẫn xuất nằm trong TemporaryDirectory, đã dọn. Lượt đo cuối chạy sau test suites, không cùng một suite đang chạy:

| Kết quả | Số đo trên máy này |
| --- | --- |
| Chuẩn bị nền mỗi bài | **2,94–5,20 s** |
| RSS lớn nhất của tiến trình con, lấy mẫu 20 ms | **67,02–69,93 MiB**; không phải tổng RAM app |
| Owned process đồng thời | **1** |
| Cache-hit | **1,54–2,90 ms**, không FFmpeg |
| Loudness đo lại cả 8 | **−18,0 LUFS** |
| True peak đầu ra | **−9,98 đến −3,66 dBTP** |
| File nguồn/video packet bytes/count | **8/8 giữ nguyên** |
| PTS hình khác lớn nhất | **0,5 ms**, mọi frame đầu vẫn ở 0 |
| Audio decode đầu/đuôi | Mọi đầu vẫn 0; khác đuôi lớn nhất **0,408 ms** do timebase container |
| Tổng cache 8 bài | **460,83 MiB** |

Chi tiết/replay: [media-probe.json](audio-effects/media-probe.json), `python -m tools.probe_audio_effects`. CPU seconds trong JSON là tổng các mẫu child process còn sống, có thể thiếu phần cuối rất ngắn sau process exit; không dùng để quảng cáo phần trăm CPU chính xác. Không suy ra mọi CPU/ổ đĩa đều đạt thời gian này hoặc không bao giờ khựng. Không có AI/model/GPU DSP cho tính năng này.

**31 file dữ liệu cũ giữ nguyên SHA**: [saved-file-check.json](audio-effects/saved-file-check.json). Giữ ASR/translation/timing/fade/grouping/schema/load/save/search/shuffle/ID/cache keys cũ. Scope gates kiểm tra mọi production Python ngoài ba UI adapters giữ raw hash; helper mới có SHA riêng. MainWindow chỉ thay install/import/shutdown/popup visibility; PlaybackBar chỉ thêm nút và thu utility targets 36→32 logical px khi cửa sổ nhỏ để giữ minimum 760. Guard chỉ nhận popup và chặn lyric trong source transition.

Hai sửa import namespace của user có trước phase được giữ nguyên. Một file đã được chuyển toàn bộ CRLF trước phase, khác raw bytes snapshot presentation cũ. Adapter test kiểm tra SHA hiện tại và snapshot đầu phase, rồi chỉ phục hồi import + line endings qua canonical artifact tái dựng từ **patch cũ**, SHA `ae21c5ba…`; đối chiếu toàn bộ text sau normalize trước khi cho gate cũ chạy. Không recapture/sửa manifest phase cũ để hợp thức hóa thay đổi.

Ảnh Qt thật: [popup](audio-effects/audio-panel.png), [playback 1280](audio-effects/playback-1280.png), [cửa sổ nhỏ](audio-effects/playback-760.png). Kiểm tra native screen/tai nghe nhiều thiết bị/seek tất cả container/HDR/snap/multi-monitor/EXE/update vẫn cần nghiệm thu riêng; offscreen/native decoder probe không chứng minh toàn app hoặc mọi bài đã đạt chất lượng nghe hoàn hảo. Chưa build hoặc commit trong phase này; các thay đổi user trong build/spec/requirements/deleted logs giữ nguyên, không được gộp vào phase âm thanh.
