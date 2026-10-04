# Chốt cân bằng và hướng nâng cấp chất âm — 04/10/2026

**Cập nhật mới nhất:** đã thêm [hai style Ấm/Tai nghe](AUDIO_LISTENING_STYLES.md): EQ nhỏ và crossfeed nhẹ, giữ preset cũ. EQ 5 dải chỉnh tay, denoise và A/B tự động vẫn chưa triển khai. Các đề xuất/báo cáo dưới đây là lịch sử, không mô tả toàn bộ tính năng hiện tại.

**Cập nhật phase sau:** user đã cho phép chờ im lặng khi chọn bài có EQ; [AUDIO_START_WAIT.md](AUDIO_START_WAIT.md) ghi triển khai và kiểm chứng. Sau đó đã thêm [chuẩn bị trước một bài kế tiếp](AUDIO_NEXT_PREFETCH.md). EQ 5 dải/denoise/A-B ở dưới vẫn là đề xuất. Báo cáo rà soát dưới đây giữ lịch sử lượt trước.

## Kết luận rà soát

Giữ triển khai [cân bằng trực tiếp](AUDIO_NORMALIZATION_REALTIME.md). Rà `core.audio_loudness`, `control.audio_volume`, `control.audio_effects`, popup và ownership process không phát hiện thêm thay đổi hiệu năng có lợi ích rõ ràng cần thực hiện trong lượt này. Không sửa production, không recapture source gates, không sửa tùy chọn hoặc cache người dùng. Đây là quyết định giữ phạm vi đã kiểm chứng, không phải chứng nhận không còn lỗi trên mọi máy.

Đường phát EQ-off chỉ dùng gain trên output cũ, giữ source/decoder/clock. Đo lần đầu dưới nền, cache hit không chạy FFmpeg, đổi target/volume không đo lại. Một worker/process, JSON LRU 256, ramp chỉ hoạt động khi chuyển mức. Không thêm phân tích DSP liên tục vào GUI. Cache prune có đọc tối đa số record sở hữu để xác định LRU nhưng nằm trên worker; chưa có số đo cho thấy đây là bottleneck cần thêm cache/index khác.

Số đo đã có trên 8 video, 198,24 MiB: đo lạnh 2,52–4,47 giây, hit 0,53–1,10 ms, RSS child FFmpeg 59,80–69,22 MiB, một process tối đa, không media dẫn xuất. Đây là phép đo ở phase trước với source hiện hành, **không đo lại và không quảng cáo cải thiện hiệu năng mới** trong lượt rà soát này. Lần đo đầu vẫn có đoạn chưa cân bằng; Qt volume 0–1/headroom/max boost vẫn giới hạn độ đồng đều.

Chạy lại full suite: **258 total, 247 pass +11 historical skip, 53,897 giây**; `git diff --check` đạt. Log trong [audio-next/test-results.txt](audio-next/test-results.txt), [diff-check](audio-next/diff-check.txt). Không chạy lại DPI/media benchmark vì không thay production.

Đối chiếu 31 path với báo cáo phase trước: **29 hash khớp; media_index.json và translation_cache.json đã khác**. Hai file đều có mtime 13:53:36 ngày 04/10/2026, trước lượt test này (log hoàn tất 14:00:34, thời lượng 53,897 giây). Không có snapshot nội dung/hash tại đầu lượt này nên không gán hai chênh lệch cho một nguyên nhân cụ thể và không tuyên bố 31/31 vẫn khớp báo cáo trước. Giữ nguyên hai file, không khôi phục dữ liệu người dùng theo baseline cũ. Chi tiết trong [saved-file-check](audio-next/saved-file-check.json). Native listening, DAC/driver, nhiều thiết bị và EXE/update vẫn là nghiệm thu riêng.

## Phần mới khả thi

| Thứ tự | Tính năng đề xuất | Mục đích và giới hạn | Trạng thái |
| --- | --- | --- | --- |
| 1 | EQ 5 dải có nút reset, mức tác động nhỏ | Chỉnh bass/mid/treble theo tai nghe và sở thích; không mặc định tăng mọi dải, có preamp/headroom khi tăng. Mức 0 là bypass. EQ thay đổi chất âm có chủ ý, không khôi phục chi tiết nguồn đã mất. | Đề xuất; hiện chỉ có hai preset EQ nhẹ |
| 2 | Mức giảm chói có thể điều chỉnh | Cho người dùng điều chỉnh độ dịu thay vì áp một preset mạnh cho mọi bài; có thể dùng các dải EQ của bước 1 để tránh thêm xử lý trùng nhau. | Đề xuất; preset Dịu hiện có |
| 3 | Giảm tiếng xì/rè ổn định, nhẹ và chọn theo từng bài | Thử FFT denoise trên bản dẫn xuất; cần mẫu có nhiễu thật, nghe A/B cùng độ lớn và kiểm tra nhạc cụ/đuôi reverb. Không mặc định bật toàn thư viện, không tự lấy nhạc dạo làm mẫu nhiễu. | Đề xuất; chưa có lọc nhiễu trong app |
| 4 | A/B gốc–xử lý với độ lớn tương đương | Giúp phân biệt thay đổi chất âm với việc bản xử lý chỉ to hơn. Ghi rõ A/B hiện tại có thể reload do đường EQ dẫn xuất. | Đề xuất; chưa triển khai |

Không hứa mọi bản thu đều hay hơn. Nguồn sạch có thể nghe tốt nhất ở Nguyên bản. Giảm nhiễu là thay đổi nội dung tín hiệu, có thể xóa chi tiết nếu cài đặt không phù hợp; bảo toàn **file gốc** và **âm gốc khi tắt** là yêu cầu, không cam kết tín hiệu khi bật lọc giống nguyên bản.

FFmpeg có [EQ peaking](https://ffmpeg.org/ffmpeg-filters.html#equalizer) với frequency/width/gain và cảnh báo clipping khi tăng gain; đây là cơ sở cho bước 1. [afftdn](https://ffmpeg.org/ffmpeg-filters.html#afftdn) hỗ trợ FFT denoise, noise profile và gain smoothing để giảm artefact. Các thông số và mức xử lý cụ thể phải được chọn sau thử nghiệm; chưa xác nhận build FFmpeg portable hiện hành hỗ trợ mọi filter dự kiến.

Không ưu tiên bộ lọc AI speech cho toàn bài hát: [arnndn](https://ffmpeg.org/ffmpeg-filters.html#arnndn) được mô tả cho speech và cần model. Suy luận thiết kế: cần kiểm chứng nhạc riêng trước khi dùng, không coi speech denoise là enhancer an toàn cho nhạc. Không tải model hoặc thêm dependency trong lượt này.

## Hai cách triển khai và yêu cầu phát liền mạch

**Tiếp tục cache dẫn xuất hiện có:** mở rộng profile EQ/lọc nhiễu trong một phase riêng, version key mới không sửa cache cũ, stream-copy video và xử lý audio nền. Giữ một player, restore vị trí/tracks/rate/loop và fallback cũ. Ít ảnh hưởng kiến trúc nhưng bật/tắt/chỉnh EQ hoặc chọn nguồn đã xử lý vẫn cần reload; không đáp ứng mục tiêu DSP tức thì hoàn toàn. Chuẩn bị trước chỉ giảm thời gian chờ, không xóa thao tác đổi nguồn.

**DSP trực tiếp:** cần phase riêng cho audio routing/output/clock đồng bộ video, buffer, seek, tốc độ, đổi track, thiết bị, mute và shutdown. [QAudioBufferOutput](https://doc.qt.io/qt-6/qaudiobufferoutput.html) cung cấp buffer đã decode, chỉ hỗ trợ FFmpeg backend; không phải API thay sample trong QAudioOutput hiện có. Không triển khai đường phát audio thứ hai song song như một bản vá vì phải quản lý đồng bộ và ownership mới. Không cần đổi PySide6/UI framework chỉ để thiết kế phase âm thanh này, nhưng không coi đây là thay đổi nhỏ.

Ưu tiên của user hiện hành vẫn là **phát liền mạch, cân bằng trực tiếp; EQ giữ riêng và ghi rõ giới hạn**. Vì vậy chốt normalizer hiện tại; nếu mở rộng EQ theo đường cache phải giữ cảnh báo reload. Nếu muốn cả EQ/denoise bật tắt không reload, cần nghiệm thu phase DSP trước rồi mới tích hợp feature; không âm thầm đổi đường phát.

## Cổng nghiệm thu cho phase tiếp theo

- Tắt mọi xử lý: source/output/decoder/clock gốc, user volume/mute/shortcuts/devices giữ đúng; không có worker DSP chạy thừa.
- File media/phụ đề/dịch/model/schema/ID cũ giữ hash; profile mới tách biệt, cache key có version và chỉ dọn dữ liệu sở hữu.
- Kiểm tra mono/stereo, nhiều sample rate/tracks, silence, file lỗi, seek/rate/next, rapid toggles, output change và shutdown; lỗi dùng lại nguồn gốc.
- EQ: response đúng dải/mức, kiểm tra peak sau toàn chuỗi, không tự làm đồng đều bằng compressor; không suy ra peak sau EQ từ số đo raw cộng gain đơn thuần.
- Denoise: noisy fixture và clean fixture, timing/sample count, đánh giá artefact; nghe A/B volume matched trên vocal, cymbal, reverb và điệp khúc. Không đặt mức giảm nhiễu mặc định trước khi có mẫu đại diện.
- Đo CPU/RAM và độ trễ trong lúc video phát; source/PTS/PCM diagnostics riêng với nghe/native video/DAC/EXE. Không dùng test offscreen để tuyên bố phát hành đạt chuẩn thương mại hoàn toàn.

Lượt này chỉ chốt rà soát và lập phương án. Không thêm EQ 5 dải, denoise, AI enhancer hoặc đường phát mới; không commit/build/stage.
