# Xuất video kèm phụ đề / lyric — 05/10/2026

Tính năng này là đường xuất độc lập, chỉ đọc video hiện tại, cue đã nạp và trạng thái
hiển thị phụ đề tại thời điểm bấm **Xuất video + lyric** trong Công cụ phụ đề.

Mỗi lần xuất đều mở **Thiết lập xuất video** trước khi chọn nơi lưu. Thiết lập chỉ áp dụng
cho lần export đó, không ghi đè setting phát video hoặc setting phụ đề của app.

Dialog export dùng bố cục editor hai cột: preview canvas lớn ở trái và thiết lập ở phải. Preview
hiện thumbnail có sẵn ngay lập tức, sau đó một `QProcess` export-only lấy đúng **một frame** từ file
nguồn qua FFmpeg và pipe PNG trong RAM để thay bằng ảnh rõ hơn; không tạo file ảnh tạm, không seek/
reload `QMediaPlayer` và không gọi AI. Khi đổi câu preview, frame mẫu được lấy lại tại timestamp câu
đó. Các thay đổi Aspect/Fit/Fill/Stretch/background/safe area/font/position cập nhật ngay trên khung
mẫu. Preset nhanh Nguồn/YouTube/Shorts/Vuông chỉ điền các `ExportSettings` sẵn có, không tạo policy
render riêng.

Preview giữ ảnh nguồn ở độ phân giải decode và để `QPainter` resample trực tiếp vào canvas thay vì
scale ảnh xuống kích thước logic trước. Subtitle preview được raster theo kích thước backing-store
(`devicePixelRatioF`) rồi gắn DPR vào `QImage`, nên Windows 125/150/200% DPI không phải phóng lại
một bitmap chữ/ảnh đã giảm độ phân giải. DPR nằm trong render key để chuyển dialog giữa hai màn hình
DPI khác nhau sẽ rebuild preview đúng độ nét; thay đổi này chỉ thuộc `ExportPreviewWidget`, không đổi
pixel pipeline của bản video xuất thật.

## Hành vi

- Giữ nguyên text, mode ngôn ngữ, timing cue, font size, màu chữ/nền, opacity,
  outline, shadow, fade và `subtitle_effects` đang dùng.
- Các effect painter hiện có (gradient, glow, shimmer, particle/sweep và kinetic)
  được tái sử dụng với progress tính trực tiếp từ media timestamp; export không seek
  hoặc reload `QMediaPlayer`.
- Cue không có text trong mode hiện tại vẫn được giữ mốc `previous source end` trong
  snapshot để quyết định fade của câu kế tiếp giống `SubtitleLayer` live.
- Video nguồn và file subtitle đã lưu là read-only. Bản xuất đi qua file `.botube-exporting-<id>`
  rồi `os.replace` khi FFmpeg hoàn tất, nên hủy/lỗi không ghi đè bản đích hoàn chỉnh.
- MP4/MKV mặc định dùng H.264 CRF 18. Audio được stream-copy khi container hỗ trợ; MP4 chỉ
  fallback AAC 320 kb/s khi codec nguồn không thuộc nhóm tương thích đã biết.
- Canvas có các tỉ lệ nguồn, 16:9, 9:16, 1:1, 4:5, 4:3, 3:2, 21:9; độ phân giải nguồn,
  720p, 1080p, 1440p, 2160p hoặc W×H tùy chỉnh. Kích thước luôn được làm chẵn cho
  H.264/yuv420p.
- UI có preset nhanh cho nguồn/YouTube/Shorts/vuông, nút đổi W×H tùy chỉnh, reset về cấu hình
  khuyến nghị và tóm tắt container/kích thước/FPS/CRF trước khi chọn file đích. Đây chỉ là adapter
  giao diện trên cùng policy export hiện có.
- Nhóm **Ghi đè riêng khi xuất** là opt-in: cỡ chữ 10–96 px, dịch ngang/dọc theo % canvas và độ
  trong nền subtitle 0–100%. Khi checkbox cỡ chữ/opacity tắt và offset bằng 0, renderer dùng đúng
  style/vị trí snapshot từ app như trước; không ghi ngược các giá trị này vào setting subtitle live.
- Có thể chọn một trong vài cue đại diện (đầu/giữa/cuối) để xem preview. Việc này chỉ thay câu/frame
  mẫu trong dialog, không đổi cue text, timing hay thứ tự xuất.
- Cách đặt video gồm **Vừa khung** (mặc định, giữ toàn bộ hình và thêm nền khi cần),
  **Lấp đầy** (có thể crop mép) và **Kéo giãn**. Nền fit có đen/xám đậm/trắng.
- FPS mặc định theo nguồn, có thể chọn 24/25/30/50/60. Chất lượng hình có CRF
  16/18/20/23, mặc định CRF 18.
- **Vùng chống cắt lyric/sub bật mặc định với lề 0%**: nếu vị trí live đã nằm trong phần video
  nhìn thấy thì export giữ nguyên vị trí đó; renderer chỉ wrap/clamp tối thiểu khi chữ/effect thực sự
  vượt mép. Người dùng có thể tăng lề ngang/dọc đến 20% để tạo title-safe area rộng hơn, hoặc tắt
  hoàn toàn nếu muốn giữ clipping đúng vị trí kéo cũ.
- Worker chạy `QThread` LowPriority và FFmpeg BelowNormalPriority trên Windows; overlay
  là một dải RGBA nhỏ pipe trực tiếp, không sinh hàng nghìn PNG tạm.
- Đường scale của bản xuất dùng Lanczos + accurate rounding/full chroma interpolation. Subtitle
  RGBA được composite ở trung gian YUV 4:4:4 rồi mới hạ một lần về `yuv420p` ở đầu ra H.264;
  cách này giữ mép glyph/outline màu ổn định hơn và giảm hiện tượng chữ mềm/rung do composite trực
  tiếp ở chroma 4:2:0, trong khi file MP4 cuối vẫn tương thích rộng.
- Trạng thái effect/fade được sample tại tâm mỗi frame encode thay vì mép trái frame. Cue timestamp
  không đổi; đây chỉ là lượng tử hóa theo FPS chính xác hơn, giúp bước alpha đầu tiên của fade/entry
  nhỏ hơn khi cue bắt đầu giữa hai frame. Khi effect đã ổn định, raster subtitle tĩnh vẫn được tái dùng
  byte-for-byte như trước.
- RGBA chỉ cần render tới hết cue cuối (+ fade nếu bật). Overlay dùng
  `eof_action=pass:repeatlast=0`, nên phần outro của video tiếp tục nguyên vẹn ngay cả khi
  container không báo duration đáng tin cậy.
- Khoảng trống dùng một blank frame bất biến; cue đã ổn định và không có effect động
  tái dùng cùng raster RGBA thay vì vẽ lại font/outline/glow ở mọi frame. Timing FFmpeg
  vẫn giữ nguyên vì raw frame bytes vẫn được gửi đúng nhịp video.
- Painter snapshot font Qt đã resolve, padding thật của `QLabel`, anchor màn hình và geometry/aspect
  mode của `QVideoWidget`, rồi map từ viewport live sang source/canvas export. Font/box/outline/glow/
  particle vì vậy giữ cùng tỉ lệ nhìn thấy trong app thay vì suy ra từ chiều cao cửa sổ.
- Vị trí người dùng kéo vẫn được snapshot theo offset có dấu. Khi vùng an toàn bật, offset
  được giới hạn vào safe area của canvas xuất; khi tắt, clipping giữ hành vi cũ.
- Mỗi lần export dùng snapshot read-only. Thay đổi setting sau khi export đã bắt đầu
  chỉ áp dụng cho lần export kế tiếp.
- Nếu renderer/FFmpeg lỗi hoặc người dùng hủy, process vẫn thuộc worker cho tới khi dừng
  và chờ xong; file `.botube-exporting-*` được xóa, file đích hoàn chỉnh không bị thay.

## Bảo toàn

Không thay đổi ASR/Whisper, dịch, grouping, 50 ms lead/80 ms tail, subtitle schema/ID,
cache, playback source, audio DSP, playlist, download, saved settings hoặc renderer đang
phát. UI cũ chỉ thêm một action trong `SubtitleToolsDialog.init_ui`; API/signature cũ giữ nguyên.

Video phải encode lại để burn-in pixel là điều bắt buộc. Audio không bị encode lại nếu
container cho phép. Frame overlay lấy FPS trung bình của nguồn và giới hạn 60 fps để tránh
chi phí renderer bất hợp lý ở nguồn HFR; cue timestamp vẫn lấy theo milliseconds.

## Cần nghiệm thu thực tế

Automated tests có thể kiểm tra snapshot bất biến, painter deterministic, audio policy,
cancel/partial ownership và một video tổng hợp ngắn. Chất lượng cảm nhận, HDR/rotation lạ,
font fallback trên máy khác, tốc độ video 4K dài và EXE đóng gói vẫn cần smoke test native.

Đã smoke FFmpeg trên `video/Brand New Sky.mp4`: canvas 16:9 1920×1080 và portrait
9:16 720×1280 đều chạy qua pipeline fit + overlay, đầu ra H.264 và audio AAC stream-copy
hợp lệ. Bộ unit test Python chưa chạy được trong phiên này vì `venv/pyvenv.cfg` vẫn trỏ
tới Python 3.11 đã bị thiếu khỏi máy.
