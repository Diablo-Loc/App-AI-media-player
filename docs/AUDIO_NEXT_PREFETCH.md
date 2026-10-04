# Chuẩn bị EQ cho một bài kế tiếp — 04/10/2026

Người dùng cho phép tiếp tục tối ưu và giữ âm gốc. Phase này giảm thời gian chờ khi chuyển bài có EQ bằng **chuẩn bị trước duy nhất bài kế tiếp**; không thêm bộ lọc làm đổi chất âm. EQ và cân bằng vẫn OFF mặc định. Tùy chọn mới “Chuẩn bị trước bài kế tiếp” được bật sẵn nhưng chỉ chạy khi người dùng bật EQ; có thể tắt độc lập trong popup cạnh âm lượng.

## Luồng và tài nguyên

- Sau khi playback ổn định 2 giây, lấy một ứng viên kế tiếp từ full `active_playlist`, theo phép equality/index/wrap của điều hướng cũ. Search không đổi hàng đợi; shuffle báo thay đổi cho helper. Không preload cả thư viện.
- `control.audio_prefetch.NextAudioPrefetch` dùng **worker hiện có của AudioEffectsController**, không tạo player/output/video/native owner hoặc hàng worker song song. Giữ process ưu tiên thấp và số thread FFmpeg của phase trước.
- Kết quả prefetch chỉ đi vào EQ cache hiện có. Nó không đổi source, gain, vị trí, rate, tracks hoặc trạng thái bài đang nghe. Bảo vệ file đang phát; cache vẫn 1 GiB, marker-owned eviction/journal và cache keys cũ.
- Chọn đúng ứng viên đang chuẩn bị: chuyển chính worker đó thành request foreground. Chọn bài khác/preset khác: hủy tác vụ cũ và xử lý yêu cầu mới nhất, không wait trên GUI. Chọn một bài bất kỳ chưa có cache vẫn cần chuẩn bị như phase trước.
- Pause/stall, tua bằng slider hoặc seek jump, tắt tùy chọn/EQ và shutdown hủy prefetch. Deadline nền 30 giây, mỗi context chỉ thử một lần để tránh lỗi hoặc bài chậm bị thử liên tục. Foreground vẫn giữ deadline 15 giây + decoder 8 giây và fallback âm gốc.
- Nhường cho AI worker hiện hành (`job_manager._worker` là QThread đang chạy); owned single-shot timer thử lại sau khi AI rảnh. Đây không phải scheduler cho mọi tác vụ GPU/CPU bên ngoài app.
- Không có timer phân tích phổ liên tục; theo dõi position dùng phép tính O(1) để nhận seek. Các timer settle/budget là single-shot. Không chờ worker khi thao tác; shutdown vẫn stop/wait owned worker.

Tùy chọn `prefetch_next` là boolean tùy chọn trong **audio-effects.json riêng**, đọc file cũ thiếu key vẫn được; giữ các lựa chọn normalize/tone/target đã lưu. Không sửa media, model, phụ đề, index, schema/ID, ASR/dịch, timing/fade hoặc import kiến trúc. MainWindow chỉ thêm một lời gọi trong `toggle_global_shuffle`; điều hướng cũ không bị thay thuật toán.

Popup đo chiều cao word-wrap theo fixed width 330 thay vì preferred width của `adjustSize`, tránh mất dòng hướng dẫn reload. [Ảnh Qt thực tại DPI 200%](audio-prefetch/popup.png), logical size 330 ×424; `python -m tools.preview_audio_prefetch` dùng settings tạm, không xử lý âm thanh. Gate kiểm tra các label word-wrap đủ chiều cao, không chỉ kiểm tra screenshot.

## Kiểm chứng

Windows, Python 3.11.0, Qt 6.10.1; các test dùng settings/cache tạm, decoder thật và audio muted/offscreen:

- **281 total =270 pass +11 historical skip**, 88,504 giây: [full log](audio-prefetch/test-results.txt). Mười một regression mới kiểm tra next/order/wrap, source/gain/owner invariance, worker promotion, latest selection, pause/seek/stall/budget/AI/toggle/failure/shutdown và exact scope gates. Kết quả lần chạy cuối sau sửa chiều cao popup.
- **100 tests đạt DPI 200%**, 67,738 giây: [DPI log](audio-prefetch/dpi-200-tests.txt). **31/31 saved hashes giữ nguyên** so với snapshot đầu phase: [saved-file-check](audio-prefetch/saved-file-check.json), [before](audio-prefetch/saved-before.json). [Diff check](audio-prefetch/diff-check.txt) đạt; các synthetic error logs thuộc fault injection. Hai suite cuối chạy đồng thời bằng dữ liệu tạm; probe hiệu năng riêng chạy trước, không so thời lượng suite làm benchmark.
- [Snapshot/diff/hash mới](audio-prefetch/reviewed-sources.json) phục hồi đúng source phase trước trước khi chạy gate cũ; [helper mới](audio-prefetch/new-source-hashes.json) có hash riêng. Manifest v1/v2/selection-wait không recapture. Test persist v2 giữ nguyên các key cũ và kiểm tra riêng key mới.

Probe [8 video có sẵn](audio-prefetch/media-probe.json), tách khỏi suites, cache/settings tạm và SHA nguồn trước/sau:

| Phép đo | Kết quả trên máy này |
| --- | --- |
| Next đến playback position >50 ms, sau khi prefetch xong | **0,218–0,299 giây** |
| Chuẩn bị nền, 7 ứng viên cold | **7,145–8,841 giây**, chưa tính settle 2 giây |
| Ứng viên wrap đã có cache | **0,000894 giây lookup/prepare**, không chạy process |
| RSS child tối đa khi xử lý cold | **67,01–67,93 MiB**, không phải toàn bộ RAM app |
| Audio jobs / owned tool processes chạy đồng thời tối đa | **1 / 1** |
| Source/state/volume hiện hành | Không đổi trên cả 8 lượt prefetch |
| SHA video gốc | **8/8 giữ nguyên** |
| GUI timer 16 ms: gap lớn nhất quan sát trong prefetch | **25,31–38,92 ms** tùy lượt |

Chuẩn bị nền vẫn tốn CPU/I/O/RAM và thời gian; chi phí được dời sang khi bài trước đang phát. Không so trực tiếp latency Next cache với thời gian decode/encode cold để quảng cáo xử lý EQ nhanh hơn. QVideoSink có 24,04–30,00 frame signals/s theo các nguồn, không phải phép đo Windows screen FPS; timer heartbeat không chứng minh không khựng trên mọi máy. CPU sampling của child là ước lượng, không phải benchmark CPU toàn app. Replay: `python -m tools.probe_audio_prefetch`; [stdout](audio-prefetch/media-probe.txt).

Chưa nghiệm thu nghe A/B/DAC, máy yếu, nhiều thiết bị/driver, mọi container/audio track hoặc EXE/update. Không chứng nhận toàn app đạt chuẩn thương mại chỉ từ các gate này.

## Công nghệ chất âm phù hợp tiếp theo

**Chưa triển khai DSP mới trong phase này.** Thứ tự đề xuất:

1. **EQ chỉnh theo tai nghe**, 5 dải nhẹ, reset/bypass và headroom. [FFmpeg equalizer](https://ffmpeg.org/ffmpeg-filters.html#equalizer) hỗ trợ frequency/Q/gain; gain dương có nguy cơ clipping. Khi mở tăng dải, cần đo peak sau toàn chuỗi xử lý, không suy peak chỉ từ fixed gain hoặc mặc định limiter mạnh mọi bài. Chỉnh EQ thay âm có chủ ý, không phục hồi chi tiết codec đã mất.
2. **Nghe A/B cùng độ lớn**, có giới hạn reload hiện tại, để đánh giá preset theo bài thay vì bản to hơn được cảm nhận hay hơn. Ưu tiên nghiệm thu này trước AI enhancement.
3. **Lọc nhiễu nhẹ riêng cho bản có xì/rè**, dùng [FFmpeg afftdn](https://ffmpeg.org/ffmpeg-filters.html#afftdn) có noise profile/gain smoothing. Cần mẫu sạch và nhiễu thật, kiểm tra nhạc cụ/reverb; không tự lấy nhạc dạo làm mẫu nhiễu hoặc bật cả thư viện.

[RNNoise](https://github.com/xiph/rnnoise) và [nghiên cứu gốc](https://web.jmvalin.ca/papers/rnnoise_mmsp2018.pdf) hướng speech enhancement. Vì vậy chưa có căn cứ đưa speech denoiser đó vào mọi bài nhạc; cần nghiệm thu riêng nếu áp dụng. Không thêm model/dependency/engine mới trong lượt này.

Mọi phương án phải giữ nguồn, OFF/bypass về đường phát gốc, cache có version và test source/clock/track/peak/worker. File 128k không biến thành chi tiết FLAC gốc bằng re-encode. DSP trực tiếp không reload vẫn cần phase audio-routing riêng, vì engine Qt hiện tại chưa có inline EQ của app. Xem [kế hoạch chất âm](AUDIO_ENHANCEMENT_PLAN.md).
