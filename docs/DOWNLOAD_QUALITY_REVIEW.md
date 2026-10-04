# Rà soát chất lượng tải — 04/10/2026

Phạm vi: kiểm tra DownloadPage, SettingMenu, DownloadWorker, GetTitleWorker,
bootstrap yt-dlp và đường FFmpeg portable. Đây là audit, chưa sửa production,
đổi preset mặc định, settings, engine hoặc file media/subtitle đã lưu.

## Kết luận sử dụng hiện tại

- **Video MP4 + Standard (M4A-ACC)**: ưu tiên M4A nguồn, không đặt bộ mã hóa
  âm thanh. Đây là lựa chọn MP4 phù hợp nhất hiện tại để tránh thêm một lần
  nén mất dữ liệu. Không bảo đảm là luồng chất lượng cao nhất trong mọi nguồn.
- **Video MKV + High (Opus)**: chọn audio tốt nhất theo yt-dlp, ghép bằng stream
  copy; không ép mã hóa audio. Tên High (Opus) chưa chính xác vì audio được
  chọn có thể là AAC hoặc codec khác. Không bảo đảm luôn chọn audio rời tốt
  nhất khi video tốt nhất đã có audio: selector dùng `bv*`, không phải `bv`.
- **MP4 + Extreme (320k)**: chọn M4A rồi ép AAC 320k qua postprocessor FFmpeg.
  Đây là mã hóa lại, không phải lấy một bản YouTube 320k. Bitrate đầu ra lớn
  hơn không khôi phục chi tiết đã mất ở bản nguồn.
- **MP4 + High (Opus)**: cũng ưu tiên M4A rồi ép AAC 160k; tên gọi đang gây hiểu
  nhầm. Không phải giữ Opus gốc.
- **Audio MP3** có thể xuất MP3, Opus hoặc M4A tùy quality. Extreme/Low chuyển
  thành MP3 320k/128k; High dùng audio tốt nhất rồi yêu cầu Opus, nên có thể
  phải chuyển mã nếu nguồn tốt nhất không phải Opus. Standard chỉ chọn M4A.

Chất lượng có thể giữ bằng cách lấy đúng luồng nguồn và chỉ đổi container/ghép
luồng. Không có lựa chọn tải nào khôi phục bản lossless ban đầu từ nguồn lossy.
Nguồn tham chiếu: [format selection và tùy chọn yt-dlp](https://github.com/yt-dlp/yt-dlp#format-selection),
[FFmpeg postprocessors chính thức](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/postprocessor/ffmpeg.py).
Merger mặc định dùng `-c copy`; cấu hình FFmpeg bổ sung được chèn sau các tùy
chọn đầu ra nên lệnh ép `-c:a aac` có thể thay thế copy audio. Các tùy chọn áp
cho FFmpeg chung cũng có thể tác động đến nhiều postprocessor, không chỉ merger.

## Những điểm cần sửa ở một phase riêng

1. **Chế độ giữ nguồn rõ ràng**: MP4/AAC gốc và MKV/audio nguồn tốt nhất; giữ
   riêng MP3/chuyển mã cho nhu cầu tương thích. Không tự đổi lựa chọn đã lưu.
   Tên/giải thích UI phải phân biệt codec nguồn và bitrate khi chuyển mã.
2. **Selector/fallback**: ưu tiên video rời cộng audio rời, giữ giới hạn độ
   phân giải trong từng nhánh fallback; xử lý nguồn không có M4A và thông báo
   rõ giới hạn tương thích thay vì hứa mọi nguồn xuất MP4 như nhau.
3. **Container**: `--merge-output-format` chỉ có tác dụng khi ghép. Nguồn
   progressive có thể giữ đuôi gốc dù người dùng chọn MKV/MP4. Cần remux đúng
   container nếu muốn cam kết đuôi file, không dùng recode video để đổi đuôi.
4. **Lệnh/log**: bỏ URL và `-o` thêm lần thứ hai cuối command. Không coi đó
   là bằng chứng mọi lần đều tải hai bản: yt-dlp có thể deduplicate/bỏ qua file
   tồn tại. Log thành công hiện luôn nói `.mp4` dù kết quả có thể khác.
5. **Dữ liệu tạm**: `cleanup_temp_files` quét toàn thư mục đích và xóa mọi
   `.part/.ytdl/.temp`, kể cả file không thuộc job. Cần journal/ownership và giữ
   khả năng resume, tránh sửa kèm chỉ vì mục tiêu audio.
6. **Engine lấy tên**: GetTitleWorker cập nhật EXE nhưng gọi thư viện Python
   `yt_dlp`. `ffmpeg_location=self.ytdlp_exe` không khiến thư viện sử dụng EXE
   vừa cập nhật làm engine. Cần giải quyết đồng bộ ở phase downloader tương
   thích/portable, không tải/update dependency để thử audit này.

Worker ownership/cancellation/shutdown của reliability vẫn hiện diện. FFmpeg
được bootstrap đưa vào PATH từ thư mục `bin` portable. Những điểm đó không
chứng minh tất cả lỗi mạng, nguồn, codec hoặc bản EXE đã được kiểm chứng.

## Kiểm chứng đã thực hiện

- Python dự án **3.11.0**, thư viện yt-dlp **2026.06.09**.
- Chạy `_run_download()` với bootstrap/update/download subprocess bị thay
  bằng fixture và cleanup bị chặn: **12 cấu hình** (3 format ×4 quality).
  Xác nhận selector, extract codec, tùy chọn chuyển mã và URL xuất hiện hai
  lần trong cả 12 command. Bốn quality của MKV cho cùng một command selection;
  UI hiện chỉ cho chọn High (Opus) ở MKV.
- Gọi selector thật của thư viện trên **12 tổ hợp fixture metadata**:
  3 nguồn ×4 selector. Không gọi mạng hoặc thực hiện tải.
- Nguồn chỉ có progressive 1080p: yêu cầu MP4 720p vẫn chọn 1080p qua `/b`.
- Nguồn video 720p rời +audio Opus, không M4A/progressive: selector MP4
  Standard/Extreme/High không tìm được format; selector MKV chọn `v720+opus`.
- Nguồn video tốt nhất có audio AAC 96k và có audio rời AAC 192k: `bv*+ba/b`
  chọn video có audio 96k, không thay bằng audio 192k. Đây là fixture selector,
  không phải kết luận tất cả video YouTube thực tế có phân bố format này.
- Đối chiếu README và FFmpeg postprocessor chính thức của yt-dlp.

Chưa tải YouTube thật, chưa so sánh packet/hash nguồn–đích hoặc nghe A/B,
chưa thử tài khoản Premium/runtime JS/nguồn giới hạn quyền và chưa chạy EXE.
Không chạy full suite vì audit này không thay production. Không thay đổi
file engine đã được người dùng sửa hoặc tự cập nhật dependency.
