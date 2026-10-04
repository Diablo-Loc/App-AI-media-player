# Chất âm Ấm và Tai nghe — 04/10/2026

Người dùng muốn nghe nguồn 128k dễ chịu, có chiều sâu và ít mỏi hơn, nhưng giữ nguyên âm gốc khi tắt. Thêm hai lựa chọn trong popup cạnh âm lượng, giữ ba lựa chọn cũ và các tùy chọn cân bằng/prefetch. **Nguyên bản/OFF vẫn mặc định**; không tự đổi profile đang lưu.

## Cách dùng và giới hạn

- **Ấm — nghe lâu**: nên thử trước cho cả loa và tai nghe. EQ cut-only nhẹ: −0,7 dB tại 280 Hz (Q 0,7), −1,5 dB tại 3,2 kHz (Q 0,8), high shelf −0,8 dB tại 8,5 kHz. Mục tiêu giảm vùng đục/chói tương đối, giữ bass thấp, tiếng hát và độ động; không áp bass boost hoặc cắt toàn dải treble mạnh.
- **Tai nghe — tự nhiên**: cùng EQ Ấm và crossfeed nhẹ dành cho nguồn stereo. Blend phần thấp giữa hai kênh để bớt tách cứng trái/phải, không phải widening. Strength 0,08, range 0,25, slope 0,5, input/output gain 1 và block_size 0. Giữ tín hiệu center, không thêm block latency, giả vang hoặc đổi tốc độ/sample rate. Mono/nhiều kênh và sample rate dưới 8 kHz chỉ chạy EQ, không ép downmix stereo.
- Chọn **Nguyên bản**, hoặc “Trở về âm thanh gốc”, để bỏ xử lý. EQ tùy chọn vẫn cần nạp nguồn dẫn xuất; chọn bài mới dùng wait/prefetch đã có, chỉnh giữa bài vẫn có khoảng ngắt. Cân bằng trực tiếp với Nguyên bản giữ cách hoạt động cũ, không reload.

Cả hai là voicing **có chủ ý**, không tương đương bit-perfect khi bật. Cảm giác dễ chịu phụ thuộc bản thu, tai nghe/loa, mức âm lượng và người nghe; không thể xác nhận “không mỏi” bằng unit test hoặc decoder mute. Nguồn sạch có thể hay nhất ở Nguyên bản. Nghe thử cùng mức cân bằng và mức âm lượng vừa phải; bản to hơn không tự chứng minh chất âm tốt hơn.

Không AI tái tạo, exciter, compressor/limiter mạnh, denoise toàn thư viện hay reverb để tạo cảm giác chi tiết giả. Codec 128k không lấy lại chi tiết đã bỏ khi nén; FLAC24 ở cache tránh thêm một lần nén mất dữ liệu sau xử lý, không làm nguồn trở thành bản thu lossless gốc.

## Kỹ thuật và bảo toàn

[FFmpeg equalizer](https://ffmpeg.org/ffmpeg-filters.html#equalizer) hỗ trợ frequency/Q/gain; preset mới dùng precision f64. [Crossfeed](https://ffmpeg.org/ffmpeg-filters.html#crossfeed) được thiết kế blend stereo khi nghe tai nghe; tùy chọn block_size khác 0 tạo delay nên giữ 0. Bin FFmpeg đang có đã hỗ trợ các options, không cài/nâng dependency. Lựa chọn mức nhỏ là thiết kế bảo thủ của app, không phải preset được chứng nhận cho mọi tai nghe.

`audio_profile` thêm hai tone token mới, giữ PROCESSOR_VERSION=1, schema normalize/tone và **filter/gain/cache keys của off/gentle/balanced y như cũ**. Token mới có key riêng; tương lai đổi DSP của token này cần invalidation có phạm vi, không dùng lại cache sai thuật toán. Sample rate/frequency clamp giữ dưới Nyquist; kênh thực từ ffprobe được dùng giống nhau trong đo và render.

Giữ đường chuẩn bị cũ: đo loudness/true peak **sau toàn bộ EQ/crossfeed**, rồi chỉ áp gain cố định để giữ ceiling −1,7 dBTP và giới hạn boost. Không suy peak từ riêng dải EQ; thực tế peak sau lọc có thể thay đổi. Không ép tăng âm để đạt target bất chấp headroom. Native normalization đọc số đo sau chuỗi này và áp user volume riêng như trước.

Chỉ ba production module đổi: `core.audio_profile` policy, `core.audio_effects.prepare_audio` truyền channels vào analysis/render, popup thêm hai lựa chọn/tooltips. MainWindow, audio controller/volume/loudness/prefetch/worker ownership, cache pruning/keys cũ, single QMediaPlayer/output/video/native owners, ASR/dịch/timing/fade/schema/file lưu cũ không sửa. Không đổi import kiến trúc hoặc reapply refactor đã rollback.

Một worker/process ưu tiên thấp, một decode/filter/encode thread và cache 1 GiB hiện có. EQ/crossfeed được render trước vào FLAC24; khi phát không chạy thêm bộ DSP Python/AI hoặc tải toàn bài vào RAM. Cancellation/foreground deadlines/AI deferral/latest/shutdown/fallback nguồn gốc dùng đường cũ. Nếu FFmpeg không hỗ trợ hoặc render lỗi, giữ âm gốc thay vì bỏ track.

## Kiểm chứng

Python 3.11.0/Qt 6.10.1/Windows; tests dùng settings/cache/media tạm và Qt decoder muted. Bảy regression mới:

1. So profile/gain/filter/cache-key cũ với module snapshot trước phase trên nhiều rate/kênh, kể cả silence/peak giới hạn.
2. Tone mới mặc định không bật, whitelist không nhận filter tùy ý, channel/rate guard.
3. Tín hiệu 60/280/1000/3200/8500 Hz: mức cắt nhẹ, bass thấp gần gốc; thay amplitude ×0,1 vẫn output ×0,1, không dynamic compression.
4. Crossfeed giữ center, số sample, không tạo âm trên silence; mono/stereo/6 kênh giữ số kênh, blend một bên ở tần thấp có mức nhỏ.
5. AAC128k/video thật với cả hai profile và normalize on/off: source/video packet bytes/PTS/audio bounds giữ trong container rounding; đo lại output peak, cache hit không process.
6. Qt decoder thật original → hai preset → original: giữ paused seek/rate/mute/user-volume/audio/video owners và tracks.
7. Exact scope gate và snapshot restore trước gate cũ. [Manifest mới](audio-listening/reviewed-sources.json) không sửa manifest v1/v2/start/prefetch; adapter hash realtime chỉ khôi phục source đã review, không nới danh sách miễn kiểm tra.

- **288 tests =277 pass +11 historical skip**, 92,905 giây: [full log](audio-listening/test-results.txt). Bảy test mới đạt riêng trong 7,521 giây: [focused log](audio-listening/focused-tests.txt).
- **107 tests đạt DPI 200%**, 71,095 giây: [DPI log](audio-listening/dpi-200-tests.txt). Full/DPI suites chạy song song, mỗi suite có dữ liệu tạm riêng; thời lượng không dùng làm benchmark.
- **31/31 saved hashes giữ nguyên**, đối chiếu baseline đầu phase: [check](audio-listening/saved-file-check.json), [before](audio-listening/saved-before.json). [Diff check](audio-listening/diff-check.txt) đạt. Synthetic ERROR trong suite là fault injection, không phải test thất bại.
- Popup thật tại DPI 200%: [Ấm](audio-listening/warm.png), [Tai nghe](audio-listening/headphones.png), word-wrap đủ chiều cao. Preview `python -m tools.preview_audio_listening` chỉ đổi UI với settings tạm.

Real-media/resource probe `python -m tools.probe_audio_listening` chỉ dùng 8 video có sẵn và cache tạm, chạy độc lập sau suites. Kết quả tại [media-probe.json](audio-listening/media-probe.json); không dùng chuẩn bị cache hit để quảng cáo DSP cold nhanh hơn.

**16/16 lượt =8 video ×2 style đạt**, normalize=False đúng đường tone chuẩn bị của controller. [Log](audio-listening/media-probe.txt). Validation loudnorm sau render chạy tuần tự qua process owner, không trộn nó vào thời gian chuẩn bị đã đo:

| Phép đo trên máy này | Ấm | Tai nghe |
| --- | --- | --- |
| Chuẩn bị lạnh | 3,607–10,098 s | 5,224–11,575 s |
| Peak child RSS khi prepare, không phải RAM toàn app | 67,18–70,44 MiB | 74,31–77,42 MiB |
| Cache hit lookup/stat, không decode playback | 10,10–22,18 ms | 10,94–15,19 ms |
| True peak output đo lại | −1,70 dBTP | −1,70 đến −1,68 dBTP |
| Source SHA/video packet bytes/count | 8/8 giữ nguyên | 8/8 giữ nguyên |

Mục tiêu gain là −1,7 dBTP; meter sau encode sai khác tối đa 0,02 dB trên tập này, vẫn dưới −1,5 dBTP được bảo vệ bằng margin 0,2 dB. Mỗi lượt tối đa **một owned process**, hit không FFmpeg; PTS video khác tối đa **0,5 ms**, audio đầu/đuôi khác dưới **2 ms** do container timebase. Không thêm sample-rate conversion/block delay trong render. Đây là phép đo source/timestamps/resource, không đo DAC hay toàn bộ CPU/RAM/FPS của app.

Không so con số mới với benchmark các phase trước để tuyên bố nhanh hơn. Nhiều bộ lọc mới có chi phí prepare lớn hơn; nếu máy/file vượt deadline, fallback âm gốc như trước. Khi phát bản đã chuẩn bị không chạy chuỗi filter Python/AI nền; Qt vẫn giải mã nguồn FLAC dẫn xuất. Giữ cache giới hạn, không nạp toàn bộ PCM vào RAM và không tiền xử lý cả thư viện.

Nghe A/B trên thiết bị thật, máy yếu, mọi container/driver/audio tracks, EXE/update vẫn cần nghiệm thu riêng. Tests khách quan không chứng minh mọi bản 128k hay hơn hoặc có chất lượng nghe FLAC gốc.
