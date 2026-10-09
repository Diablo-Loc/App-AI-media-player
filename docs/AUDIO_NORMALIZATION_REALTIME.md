# Cân bằng âm lượng không nạp lại video — 04/10/2026

Phase sau: [chờ EQ khi chọn bài](AUDIO_START_WAIT.md) dời playback của EQ-on đến sau chuẩn bị; normalization EQ-off vẫn giữ hành vi phát ngay trong tài liệu này. Đổi EQ giữa bài vẫn có reload.

User báo âm nghe thiếu chi tiết và thêm một lần load khi bật/chuyển bài. User đã chọn **ưu tiên phát liền mạch, cân bằng trực tiếp; EQ giữ riêng và ghi rõ giới hạn**. Phase này thay đường cân bằng bằng gain trên chính `QAudioOutput` đang phát. Tính năng vẫn tắt mặc định; file nguồn, phụ đề/dịch, cấu hình cũ và model không migrate/ghi lại.

## Cách dùng

Trong nút **Âm thanh** cạnh loa:

1. Đặt **EQ tùy chọn → Nguyên bản** để không có thao tác đổi nguồn do EQ.
2. Bật **Cân bằng âm lượng giữa các bài**.
3. Chọn **Thông thường −14 LUFS** hoặc **Nhỏ hơn −18 LUFS**; −14 là mặc định mới, giảm ít hơn 4 dB so với mục tiêu cũ khi không bị giới hạn.

Bật/tắt cân bằng hoặc đổi mức trên cùng bài **không setSource, không seek, không pause/play, không tạo video/FLAC mới**. Chuyển bài có một lần nạp file do thao tác chọn bài như đường phát gốc; không nạp lại bản xử lý lần hai. Volume popup/phím tắt vẫn hiển thị và chỉnh mức người dùng đã chọn; gain cân bằng là một lớp riêng. Tắt cân bằng trả về mức người dùng đó, không lấy mức vật lý đã giảm rồi giảm lần nữa.

**Bài chưa đo vẫn phát ngay với âm hiện tại.** FFmpeg đo toàn bài dưới nền, sau đó áp gain bằng ramp 150 ms. Vì vậy lần đầu có một đoạn đầu chưa cân bằng hoàn chỉnh; không có màn chờ phát hoặc cam kết mọi bài cân ngay từ sample đầu. Kết quả có sẵn dùng cache trên worker, được yêu cầu ngay khi đổi nguồn; không chạy lại đo chỉ vì sửa mức −14/−18 hoặc volume. Đổi bài/tùy chọn hủy job cũ và bỏ kết quả stale.

EQ **Dịu/Cân bằng nhẹ** vẫn giữ được chọn riêng. EQ này cắt dải cao theo preset, có thể nghe bớt sáng; cần chuẩn bị bản dẫn xuất và nạp lại nguồn như phase v1. Popup ghi rõ giới hạn này. Nếu EQ đã được lưu từ phiên cũ, user chọn **Nguyên bản** để dùng đường phát liền mạch; không âm thầm đổi lựa chọn đã lưu. Reset toàn bộ trong lúc đang phát EQ cũng cần trở về nguồn gốc. Không quảng cáo EQ trực tiếp khi engine chưa hỗ trợ.

## Chất lượng và giới hạn

Cân bằng mới không lọc EQ, không compressor/AGC, không mã hóa lại và không thay sample rate/channels. Gain cố định sau phép đo chỉ thay độ lớn; PCM được chính decoder cũ giải mã. Phép test bắt `QAudioBufferOutput` trên hai decoder khởi tạo tương đương cho thấy ít nhất tám buffer chung khớp raw-byte SHA giữa tắt/bật normalization. Đây là bằng chứng giữ dữ liệu giải mã, không phải phép đo output DAC hoặc xác nhận tai người nghe mọi bài đều hay hơn.

Cảm giác thiếu chi tiết ở v1 **có thể** đến từ preset giảm treble hoặc mức −18 LUFS nhỏ hơn nhiều so với bài gốc; chưa có nghe A/B với volume matched để kết luận nguyên nhân duy nhất. Tách EQ khỏi cân bằng và cho chọn −14/−18 giúp xử lý hai khả năng đó. Giảm âm lượng có thể thay đổi cảm nhận; không tuyên bố khôi phục chi tiết đã mất do nén 128k.

Gain tăng tối đa 12 dB, giữ true-peak headroom dự kiến −1,7 dBTP có tính cả mức volume vật lý. `QAudioOutput` giới hạn volume tuyến tính **0–1**, vì vậy không tăng vượt full-volume nguồn gốc. Bài rất nhỏ, volume đang tối đa hoặc có peak cao có thể chưa đạt mục tiêu; popup nói rõ giới hạn đầu ra. Không âm thầm compressor để ép các bài đồng đều tuyệt đối. Xem [tài liệu QAudioOutput](https://doc.qt.io/qt-6/qaudiooutput.html#volume-prop).

## Phân chia trách nhiệm và tài nguyên

| Thành phần | Hành vi |
| --- | --- |
| `core.audio_loudness` | Một null-output FFmpeg pass, LUFS/true peak, native gain policy, cache measurement |
| `control.audio_volume` | Tách user volume/gain, ramp 150 ms, bỏ timeout stale, giữ mute/device/owner |
| `control.audio_effects` | Latest measurement worker, không đổi source khi normalize; EQ v1 được giữ riêng |
| MainWindow | Chỉ ba adapter popup/volume/phím tắt đi qua user-volume control |
| Popup | Target −14/−18, EQ riêng và thông báo điều kiện phát liền mạch |

Một owned worker và một FFmpeg tối đa; below-normal priority, một decode/filter thread. Không GUI wait khi tương tác; shutdown hủy và chờ worker/process kết thúc, không terminate QThread. Ramp chỉ chạy khoảng 150 ms khi cần, không timer xử lý DSP liên tục sau khi ổn định. Mute, thiết bị, player và video output cũ được giữ.

Cache `storage/audio-loudness-cache` chỉ lưu JSON, tối đa **256 owned records theo LRU**. Key gồm nguồn resolved path/size/mtime, audio ordinal và measurement version; không gắn target/user volume vì dùng chung số đo. Validate context và số đo, từ chối bool/NaN/thiếu field hoặc giá trị không hợp lý. Cache hit giữ bản hay dùng; chỉ evict file hash đúng owner/key, bỏ qua symlink/file lạ. Cache không ghi được vẫn dùng số đo hợp lệ trong phiên. Số đo raw EQ-off từ cache v1 được đọc lại khi hợp lệ, không cần và không chạm file media cache cũ. Cache v1/nguồn cũ không tự bị dọn.

Không thêm engine hoặc dependency. Native gain dùng API có trong Qt 6.7; `QAudioBufferOutput` từ Qt 6.8 chỉ xuất hiện trong test chẩn đoán có guard, không là dependency của app. EQ trực tiếp thực sự cần một phase audio-routing/clock/latency riêng; user đã chọn hoãn phương án đó. [QAudioBufferOutput](https://doc.qt.io/qt-6/qaudiobufferoutput.html) cung cấp buffer cho xử lý ngoài, không phải callback thay thế audio của output hiện có.

## Kiểm chứng

Môi trường có sẵn: Python 3.11.0, Qt/PySide6 6.10.1, Windows, 20 logical CPUs. **258 total: 247 pass +11 historical skip**; **77 tests đạt DPI 200%**. Thêm 18 realtime regressions bên cạnh 26 audio v1. Log: [full suite](audio-realtime/test-results.txt), [DPI](audio-realtime/dpi-200-tests.txt). `git diff --check` đạt. Test lỗi save/read-only trong log là fault injection có chủ ý, không phải test thất bại.

Qt decoder thật, có mute, kiểm tra:

- Normalize/target edits không sourceChanged/playbackStateChanged/muteChanged, không tua lại; giữ rate/device/video/audio outputs và paused position.
- Hai video thật trong `video/` được chọn liên tiếp: **hai source changes tổng cộng**, không source cache dẫn xuất hoặc lần reload thứ hai.
- PCM raw bytes khớp ở buffer timestamps chung giữa bật/tắt.
- Popup/phím tắt volume không bị gain làm trôi user level; device-refresh trong ramp giữ user level; tắt trả volume đúng.
- Ramp giảm monotonic, timeout sau reset/shutdown an toàn; measurement error, silence/cancel, cache malformed/foreign/context/LRU và EQ measurement sai không làm crash GUI hoặc đổi nguồn.
- Test EQ v1 tiếp tục chạy: source restore, lỗi decoder/reentrant next, tracks/loops/lyric guard và nguyên dữ liệu video.

Đo riêng **8 video** hiện có, tổng 198,24 MiB, sau khi test suites đã kết thúc; cache trong TemporaryDirectory, không chạy GPU/model:

| Phép đo | Kết quả trên máy này |
| --- | --- |
| Cold measurement, bài vẫn có thể phát trong lúc đo | **2,52–4,47 s/bài** |
| Cache-hit, assertion không FFmpeg | **0,53–1,10 ms** |
| RSS child FFmpeg max, sampling 20 ms | **59,80–69,22 MiB**, không phải RAM toàn app |
| Owned processes đồng thời | **1** |
| Cache 8 bài | **3.294 byte JSON**, **0 media files** |
| Source SHA | **8/8 giữ nguyên** |
| Native gain ở target −14/user volume 50% | −7,97 đến −0,53 dB; cả 8 không bị ceiling giới hạn |

[Chi tiết](audio-realtime/media-probe.json), replay `python -m tools.probe_audio_realtime`. Con số 3.294 byte chưa bao gồm block-size/metadata filesystem; không dùng để suy ra thời gian/RAM mọi máy. Đây là measurement cost, không phải thời gian phải chờ phát. Qt tests source/state/PCM là kiểm chứng riêng; probe FFmpeg không chứng minh FPS hoặc mọi thiết bị/âm thanh DAC.

**31 file dữ liệu cũ giữ SHA**: [saved-file-check](audio-realtime/saved-file-check.json). Source gates/snapshots v1 vẫn frozen; v2 có [exact adapters](audio-realtime/reviewed-sources.json) và helper hashes riêng. Prior gates chỉ nhận v2 sau hash check rồi phục hồi snapshot v1 để kiểm tra, không recapture manifest cũ. ASR/translation/schema/timing/fade/playlist/window/video/native lifecycle không được sửa kèm.

[Ảnh popup hiện tại](audio-realtime/audio-panel.png). Chưa xác nhận nghe A/B volume matched, mọi thiết bị/driver/native screen, tất cả container/tracks, bản EXE/update. Không build, commit hoặc nâng framework trong phase này; giữ các thay đổi build/spec/requirements của user.
