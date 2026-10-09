# Preset Dễ nghe và chốt phần âm thanh — 04/10/2026

Người dùng cho phép triển khai preset tùy chọn sau khi đối chiếu đề xuất Dễ nghe, hoặc chốt commit để chuyển tính năng khác. Bản này thêm **Dễ nghe — loa** và **Dễ nghe — tai nghe**, giữ nguyên năm tone off/gentle/balanced/warm/headphones, mặc định OFF, lựa chọn mức cân bằng đang lưu và cache key/version cũ. Không chỉnh phụ đề, AI, full playlist/search/shuffle, player/native/window owners hoặc dữ liệu đã lưu.

## Cách dùng

Trong nút Âm thanh cạnh âm lượng, chọn Dễ nghe — loa khi nghe loa, hoặc Dễ nghe — tai nghe khi dùng tai nghe. Có thể bật Cân bằng và chọn −18 LUFS để thử cùng mức âm lượng; chọn tone không tự bật cân bằng hoặc đổi −14/−18 đang lưu. Nguyên bản/Trở về âm thanh gốc bỏ toàn bộ EQ/crossfeed. Cân bằng riêng với Nguyên bản tiếp tục dùng gain trực tiếp, không reload.

EQ vẫn cần nguồn dẫn xuất: chọn bài có EQ đợi chuẩn bị trước khi phát, một bài kế tiếp được prefetch nếu đủ điều kiện. Đổi EQ giữa bài vẫn reload. Không thêm engine hoặc dependency để hứa realtime EQ. Lỗi/budget/FFmpeg không hỗ trợ bs2b dùng fallback gốc hiện có.

## Chuỗi xử lý mới

1. Preamp cố định −1,5 dB trước các bộ lọc, không tự thay user volume.
2. Riêng tai nghe stereo, rate ≥8 kHz: `bs2b=profile=jmeier` (Meier 650 Hz / 9,5 dB). Mono/nhiều kênh/rate thấp bỏ crossfeed, giữ EQ và số kênh gốc. Đây là preset bs2b, khác tham số strength của crossfeed FFmpeg trong tone Tai nghe cũ.
3. EQ f64: low shelf 100 Hz +1,5 dB Q 0,707; peaking 3,5 kHz −1 dB Q 0,8; peaking 7 kHz −1,5 dB Q 1; high shelf 10 kHz −1 dB Q 0,707. Frequency được clamp dưới Nyquist như cũ.
4. Pipeline đo loudness và true peak **sau chuỗi giống hệt render**, sau đó áp gain cố định với ceiling −1,7 dBTP hiện có. Cân bằng bổ sung dùng đường controller/native hiện hành và mức người dùng đã chọn. Headroom có thể không đủ để đạt target; không ép tăng hoặc nén động để đạt bằng mọi giá.

Không thêm limiter, compressor, denoise, reverb, widening, exciter hay khôi phục chi tiết codec. Shelf +1,5 và preamp −1,5 không chứng minh peak bị chặn chính xác: đáp ứng vùng chuyển tiếp và crossfeed có thể đổi peak, nên vẫn bắt buộc đo toàn chuỗi. FLAC24 cache tránh thêm nén mất dữ liệu, không biến bản 128k thành master lossless.

[bs2b chính thức](https://bs2b.sourceforge.net/) mô tả preset Meier; bin hiện có hỗ trợ `profile=jmeier`, kiểm tra bằng tín hiệu và media thực, không tải/nâng FFmpeg. [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html#bs2b) là tham chiếu API. Các mức EQ là lựa chọn để nghe thử, không phải đường hiệu chỉnh Harman/AutoEq cho mọi thiết bị. Cần nghe A/B trên đúng tai nghe/loa, cùng mức âm lượng, để xác nhận sở thích và cảm giác nghe lâu.

## Phạm vi và bảo toàn

Chỉ hai production module đổi trong phase này: `core.audio_profile` thêm hai token và nhánh tone_filter; `ui.audio_effects_panel` thêm hai lựa chọn/tooltips. Phép đo/render/cache/process/controller/prefetch/volume/loudness/fallback không sửa. Profile cũ được so chính xác filter/gain/schema/cache key với snapshot trước phase ở rate 4/8/44,1/48 kHz, mono/stereo/6 kênh và gain/silence cases. PROCESSOR_VERSION=1 giữ nguyên, hai token mới có key riêng. Không migration preferences hoặc saved subtitles.

[Manifest mới](audio-easy/reviewed-sources.json) giữ byte trước/sau và AST scope; hai test adapter rõ ràng: whitelist listening nhận đúng bảy tone, và audio v1 dùng adapter newline-only trước khi so nguyên hash nguồn không đổi. `audio_easy_contracts` khôi phục snapshot đã review rồi chạy chuỗi gate cũ; không recapture manifest của các phase trước. `.gitattributes` giữ nguyên byte helper có raw hash, SVG và source archives. [Checkout adapter](audio-easy/checkout-sources.json) đối chiếu **toàn bộ byte nội dung của 52 path chỉ chuẩn hóa CRLF/LF**, rồi phục hồi snapshot raw cho gate cũ; [danh sách đóng băng](audio-easy/checkout-paths.json). Không miễn kiểm tra AST hoặc bỏ hash; thay bất kỳ nội dung nào đều bị từ chối.

Kiểm tra index phát hiện vấn đề baseline vốn có: các source/snapshot Windows newline hỗn hợp bị autocrlf chuẩn hóa, và `app/test/test_aligner_optimizations.py` có trong baseline/hash nhưng bị rule `test/` ignore nên thiếu trên checkout. Commit giữ script đó đúng byte, bảo toàn LF của 19 helper đã LF trong index, và lưu lại raw bytes các archive đã có bằng `git add --renormalize` chỉ trên archive. Không đổi nội dung/manifests snapshot trong worktree hoặc sửa production ngoài audio. Diff archive ở Git là newline-only, không đổi AST/text logic. Whitespace cũ trong source archives/diagnostic logs được giữ vì là evidence, không làm code-cleanup kèm.

Commit chốt gồm toàn bộ chuỗi âm thanh đã được phép nhưng còn chưa commit: nút/popup/EQ/cache nền, native normalization, selection wait, prefetch, warm/headphones và Dễ nghe; kèm test, exact snapshots, tài liệu và evidence. Hai sửa import `ui.subtitle_presentation` / `subtitle.mode` đã tồn tại trước audio v1 được giữ làm tiền đề runtime/gate, không rollback hoặc nhân đôi module. Các thay đổi build/spec/requirements và xóa log của người dùng để ngoài commit này.

## Kiểm chứng

Python 3.11, Qt runtime dự án; settings/cache/media tạm, decoder muted. Bảy regression mới kiểm tra old profile exactness, whitelist/filter order/channel guard, EQ response và linearity, Meier blend/sample count/silence/layout, AAC128k source/video/PTS/bounds/peak/cache, Qt pause/seek/rate/tracks/mute/user-volume/owners/return-to-original, và exact scope. Test tín hiệu xác nhận tính tuyến tính, không chứng minh đánh giá cảm quan.

- Full suite cuối sau checkout adapters: **295 tests =284 pass +11 historical skip**, 98,916 s. [Log](audio-easy/test-results.txt).
- DPI 200%: **114/114 đạt**, 79,306 s khi chạy riêng. [Log](audio-easy/dpi-200-tests.txt). Lượt đồng thời với full suite có một sai khác 1 pixel ở test offscreen geometry của phụ đề, không phải DSP; chạy lại test đó và bộ DPI riêng đạt, không sửa production/test để bỏ assertion. [Lượt đầu](audio-easy/dpi-200-initial-tests.txt), [recheck](audio-easy/dpi-geometry-recheck.txt).
- Popup DPI 200% đủ chiều cao nhãn wrap: [loa](audio-easy/easy.png), [tai nghe](audio-easy/easy_headphones.png).
- **31/31 saved-file hashes giữ nguyên** so với đầu phase: [before](audio-easy/saved-before.json), [check](audio-easy/saved-file-check.json). Media/models/settings của user không ghi hoặc migration trong kiểm tra.
- **16/16 lượt trên 8 video ×2 preset đạt**, normalize=False đúng tone-prepare của controller. [Kết quả](audio-easy/media-probe.json), [log](audio-easy/media-probe.txt). Source SHA, video packet bytes/count giữ nguyên; PTS video khác tối đa 0,5 ms, audio đầu/đuôi khác dưới 2 ms do container rounding. True peak output đo lại **−1,70 dBTP** tất cả lượt. Cache hit không FFmpeg; mỗi lượt tối đa **một owned process**. Cache/source/render tạm, không đổi file gốc.

| Phép đo trên máy này | Dễ nghe — loa | Dễ nghe — tai nghe |
| --- | --- | --- |
| Chuẩn bị lạnh | 3,926–8,831 s | 4,258–8,030 s |
| Child peak RSS trong prepare | 67,37–68,68 MiB | 67,52–70,77 MiB |
| Cache hit lookup/stat | 8,48–13,97 ms | 8,13–14,35 ms |

Probe chạy riêng sau suites; output validation không tính vào thời gian prepare. Không dùng cache lookup để hứa decode/playback tức thì hoặc so khác dataset/load để khẳng định DSP nhanh hơn. RSS này là child process, không phải RAM toàn app; chưa đo CPU/FPS/native toàn app.

Kiểm tra staged checkout bằng `python -m tools.check_audio_checkout`: Git export index sang thư mục tạm với attributes/autocrlf thật, rồi source/hash/AST gates đọc bản checkout độc lập. **19/19 đạt**, gồm audio/UI/presentation/ASR/empty-results/reliability: [log](audio-easy/index-check.txt). Công cụ không reset branch hoặc sửa worktree và không thay thế test nghe/native playback. `git diff --cached --check` đạt: [log](audio-easy/staged-diff-check.txt).

Native DAC/thiết bị thật, nghe mù/A-B, máy yếu, mọi driver/container và EXE/update vẫn cần nghiệm thu riêng. Không tuyên bố 100% mọi bài hay hơn, không mỏi, hoặc mọi bài EQ không cần chờ.
