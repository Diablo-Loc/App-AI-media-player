# Tải giữ chất lượng nguồn — 04/10/2026

Người dùng cho phép sửa downloader sau [audit](DOWNLOAD_QUALITY_REVIEW.md), giữ các luồng khác và dữ liệu cũ. Chỉ sửa policy tạo command, adapter DownloadWorker, menu chất lượng và đọc settings UTF-8. Playback, EQ/gain, playlist, ASR/dịch/phụ đề, native owners, entry/build và GetTitleWorker không đổi. Không cập nhật yt-dlp/FFmpeg, không tải mạng để thử, không commit.

## Cách dùng và compatibility

| Format / quality | Hành vi mới |
| --- | --- |
| Video MKV + Original | Ưu tiên video/audio rời, lấy audio nguồn tốt nhất yt-dlp chọn; không ép Opus, không chuyển mã |
| Video MP4 + Original | Giữ codec/audio nguồn; Opus/VP9/AV1 cần decoder hỗ trợ, không hứa tương thích mọi thiết bị cũ |
| MP4 + Standard hoặc Extreme cũ | Ưu tiên AAC nguồn; thiếu AAC giữ audio nguồn khác; **không còn ép AAC 320k** |
| MP4 + High (Opus) | Ưu tiên Opus nguồn; thiếu Opus giữ audio nguồn khác; **không còn chuyển thành AAC 160k** |
| MP4 + Low (128k) | Giữ video, chuyển audio AAC 128k đúng một lần ở Metadata; lựa chọn giảm dung lượng/chất lượng |
| Audio MP3 + Original | Giữ file audio rời gốc (ví dụ WebM/M4A), không ExtractAudio `best` vốn có thể tự fallback MP3 với codec không hỗ trợ |
| Audio + High/Standard | Chỉ nhận Opus/AAC tương ứng, extract/remux giữ payload; thiếu codec báo lỗi format, không tự chuyển codec khác thành Opus/AAC |
| Audio + Extreme/Low | Vẫn chuyển mã MP3 320k/128k để tương thích, có fallback nguồn progressive |

Original chỉ là mặc định khi chưa có quality trong settings. **Không tự ghi/migrate setting.json hoặc preset cũ**. Tên/giá trị legacy giữ nguyên để đọc/lưu tương thích; ghi chú menu cập nhật theo format/quality. Extreme video không còn nghĩa bitrate đầu ra 320k; Extreme audio MP3 vẫn là 320k. Chỉ Save của người dùng mới ghi lựa chọn mới.

Đây là cải thiện có chủ ý cho **file tải mới**. File tải trước không tự chuyển đổi hay thay thế. Downloader không normalize/EQ/denoise/đổi gain; tùy chọn nghe ở playback tiếp tục hoạt động riêng. Bitrate tăng hoặc đổi codec không khôi phục chi tiết đã mất trong nguồn lossy.

## Selector, command và dữ liệu

- Ưu tiên `bv + ba`, tránh giữ audio kém đi kèm progressive khi có video/audio rời phù hợp. Nguồn chỉ có bản ghép sẵn dùng chính bản đó; không hứa thay audio của mọi nguồn.
- Giới hạn height ở **mọi** fallback. Không có format dưới mức đã chọn thì báo lỗi, không tự vượt mức hoặc upscale. Height không biết không được tự vượt giới hạn.
- Merge kết hợp remux bảo đảm container chọn cả khi tải một file sẵn. Codec không hỗ trợ container vẫn có thể báo lỗi kỹ thuật; không lén recode video/audio để né lỗi.
- URL và output template một lần, escape `%` trong tên nhập. Log thành công không giả định `.mp4`.
- Giữ khả năng đọc yt-dlp.conf ngoài app như cũ (cookie/proxy/account workflow), không thêm `--ignore-config` hoặc migrate cấu hình đó. Command của app chọn format/chất lượng đã mô tả; postprocessor tùy chỉnh trong config ngoài app vẫn có thể thêm xử lý, không được kiểm chứng trong phase này.
- Dừng/xong giữ file tải dở để engine resume; không còn quét/xóa mọi `.part/.ytdl/.temp` trong folder của người dùng. Không thêm cleanup nền/journal/eviction hoặc sửa cleanup nơi khác.
- Worker/process tracking, cancellation, shutdown, batch counters/signals, updater và lấy tên giữ nguyên. Settings đọc `utf-8-sig`, khớp writer UTF-8 và nhận BOM; appearance/unknown keys vẫn giữ khi Save.
- MP4 Low chỉ truyền lossy args cho `Metadata+ffmpeg_o`, không đặt cho mọi postprocessor. Merger/remux/thumbnail copy nguồn, Metadata encode một lần, kể cả progressive MP4.

## Kiểm chứng

Python 3.11.0, Qt 6.10.1, yt-dlp Python 2026.06.09, FFmpeg portable có sẵn:

| Kiểm tra | Kết quả |
| --- | --- |
| Full regression | **332 total =321 pass +11 historical skip**, 88,706 s |
| Focused downloader +shutdown | **20 pass**, 3,846 s |
| Downloader +UI layout ở DPI 200% | **20 pass**, 5,746 s |
| Checkout/source gates, Git index tạm riêng | **23 pass**, 3,458 s; index người dùng không stage |
| Command parsing | 3 format ×5 quality; codec/remux/encode scope, URL/output duy nhất |
| Selector | Format rời/progressive, thiếu AAC/Opus, codec preference, bounded fallback |
| FFmpeg thật, fixture tổng hợp 2 s | AAC/Opus ×MP4/MKV merger +metadata: SHA-256 từng packet payload audio/video giữ nguyên |
| Remux/ExtractAudio thật | MKV→MP4, WebM/Opus→Opus và AAC/M4A giữ packet payload |
| Low thật | AAC gần 128k; video payload giữ nguyên; lossy args chỉ tại Metadata |
| Dữ liệu cũ | **42/42 file** settings/cache/phụ đề/export/media giữ nguyên SHA-256 |
| Phạm vi source | 3 module production cũ +1 pure policy; Python/engine cũ ngoài scope không đổi, checkout chỉ nhận LF/CRLF |
| Whitespace | `git diff --check` đạt |

Packet check so **payload đã mã hóa**, không so biểu diễn skip/discard padding giữa container. Không suy ra PCM sample-perfect, timing byte-identical hoặc nghe A/B. Chưa tải YouTube thật, thử Premium/runtime JS/geo/private video, decoder trên thiết bị cũ hoặc EXE thật. Không tuyên bố mọi nguồn có cùng chất lượng hay khôi phục lossless.

Regression đầu chỉ fail kỳ vọng UI cũ giới hạn MKV một option do thêm Original được duyệt; đã cập nhật đúng một expectation, giữ kiểm tra schema/keys/format/resolution cũ. Fixture đầu so cả side-data và trùng output; đã so payload và dùng tên riêng. Checkout nhận normalized hash **chỉ sau khi** raw source ngoài scope khớp baseline mới; không recapture manifest lịch sử để làm tests xanh.

Chứng cứ: [full](download-quality/full-tests.txt), [focused](download-quality/focused-tests.txt), [DPI](download-quality/dpi2-tests.txt), [checkout](download-quality/checkout-tests.txt), [saved hashes](download-quality/saved-check.json), [reviewed manifest](download-quality/reviewed-sources.json), [reviewed diff](download-quality/reviewed.patch). Exact adapter mới restore volume phase trước các gate cũ; prior manifests frozen.

GetTitleWorker cập nhật EXE nhưng extract bằng thư viện Python vẫn là hạng mục tương thích engine riêng trong audit. Bootstrap/network/runtime JS và updater không sửa kèm audio.
