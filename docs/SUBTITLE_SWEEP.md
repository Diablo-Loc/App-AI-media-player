# Ẩn chữ sau vệt quét — 04/10/2026

Theo yêu cầu mới, phi tiêu đi qua đâu thì phần chữ đã quét ở đó giữ ẩn tới
hết câu. Từ đang quét tan dần, phần chưa quét vẫn hiện; câu mới hiện lại đủ
chữ rồi bắt đầu lượt mới. Không hiện lại toàn bộ câu ở endpoint cũ.

Trong **Cài đặt phụ đề → Hiệu ứng phụ đề**, chọn lại **Phi tiêu ánh bạc** hoặc
bật **Ẩn chữ sau vệt quét**. Bộ Bầu trời sao, Sao băng xanh và Tinh thể tím
cũng bật kiểu này khi chọn bộ mẫu. Các bộ tuyết/cánh hoa/đom đóm/bong bóng/
cực quang giữ chữ mặc định, nhưng có thể bật ô ẩn riêng. Không chọn Dọc câu
hoặc cue dưới 160 ms thì giữ chữ, tránh hiện tượng chớp ở câu quá ngắn.

[GIF bộ mẫu mới](subtitle-sweep/screenshots/presets.gif) ·
[Ảnh giữa câu](subtitle-sweep/screenshots/frames/frame-015.png) ·
[Cài đặt](subtitle-sweep/screenshots/settings-particles.png).

## Bảo toàn và thay đổi chủ ý

- Đây là thay đổi **hình vẽ**, không xóa hoặc sửa text của QLabel/cue/file.
  Timing, padding, fade cửa sổ, inclusive endpoints, xử lý ASR/dịch/load/save,
  video/audio/playlist và window owners giữ nguyên.
- Tùy chọn mới `appearance.subtitle_effects.erase_passed` mặc định false.
  Settings đã lưu thiếu key vẫn render như trước; không migration hoặc tự
  bật ẩn chữ. Cần chọn lại bộ mẫu hoặc đánh dấu checkbox để dùng kiểu mới.
- OFF hoặc bỏ Ẩn chữ khôi phục cách vẽ trước. Seek ngược phục hồi phần chữ
  theo media time; pause giữ frame, câu lặp kế tiếp có lượt quét riêng, đổi
  nguồn/ẩn/editor/OFF vẫn qua những guard đã có.
- Chỉ sửa ba helper presentation `subtitle_effects`, `subtitle_particles`,
  `subtitle_effects_panel`. Không sửa hook MainWindow/SubtitleLayer hoặc clock/
  lifecycle, không thêm timer/thread/decoder. Exact snapshot phase riêng phục
  hồi các gate cũ; snapshot/manifest trước đây không recapture.
- Theo yêu cầu mới, checkbox/bộ mẫu này supersede giới hạn “không ẩn hết chữ /
  cuối câu trả đủ chữ” của [phase hạt trước](SUBTITLE_PARTICLES.md). Khi checkbox
  false thì hành vi cũ vẫn giữ, gồm shimmer và morph nhẹ.

## Cách render và giới hạn

Dùng vùng chữ theo grapheme/word đã có; câu dày vẫn gom nhóm theo giới hạn
90 ms/slot và tối đa 256 vùng. Các dòng hiển thị quét song song theo cùng
phase thời lượng câu. Đây là trang trí theo câu, không phải word timing hát.
RTL giữ thứ tự logical; các ô hình vẽ xếp theo vị trí thực để không chồng alpha.
Chữ bidi/ligature vẫn shape toàn dòng như trước; không khẳng định các ô hình
vẽ là ranh giới từ đúng ngữ nghĩa của mọi ngôn ngữ.

Mask prefix được tạo một lần khi cần ẩn chữ, dùng lại ở từng frame. Phần đã
quét bị loại khỏi vùng vẽ; phần đang quét dùng smoothstep alpha từ 1 tới 0.
Mask áp dụng cả bóng, viền, màu và shimmer để dải sáng không làm chữ cũ hiện
lại. Cuối cue bỏ toàn bộ glyph passes, gồm glow DPR-scaled ngoài contentsRect;
hạt cũng kết thúc. Regression DPI đã bắt pixel glow còn sót và được sửa;
nền khung/fade gốc giữ
nguyên. Bật lại chữ hoặc sang câu mới không phải load lại video/subtitle.

Timer 33 ms và ngân sách 8/16/24 hạt giữ nguyên. Đo fixture Qt offscreen/DPR 1,
900×240 JP+EN+VI dài, mật độ Rực rỡ, 120 frame/style sau warm-up: median các
style hạt **0,37–0,55 ms**, p95 lớn nhất **0,63 ms**, một layout/glyph path.
Frame lạnh tạo cache vẫn khoảng **40–43 ms**, không cam kết hết khựng trên
mọi máy. [Số đo](subtitle-sweep/render-probe.json) không đại diện FPS/CPU
toàn app hoặc GPU native.

## Kiểm chứng

8 regression mới: pixel chữ đã qua bằng 0 trong vùng mask, phần chưa qua còn
hiện, endpoint không hồi chữ, seek/câu lặp/OFF phục hồi, mask đơn điệu/không
chồng/bounded/cache reuse, pause/nguồn mới, tất cả trail với cue 1–3000 ms,
Unicode/one-word/câu dài, preset/checkbox/legacy preferences và source scope.
So sánh pixel với renderer snapshot trước phase khi checkbox false giữ đúng
shimmer/glow/morph cũ; test mới đã bắt việc shimmer vô tình bypass mask và
được sửa chỉ cho chế độ mới.

Full discovery: **365 pass +11 historical skip**; DPI 200%: **56 pass**;
disposable checkout/source gates: **28 pass**. Log:
[full](subtitle-sweep/full-tests.txt), [DPI](subtitle-sweep/dpi-tests.txt),
[checkout](subtitle-sweep/checkout-tests.txt).

814 file dữ liệu/video/subtitle/settings/export giữ nguyên SHA-256:
[báo cáo](subtitle-sweep/saved-check.json). Một video Qt decoder thật có
73 frame, pause/seek ngược/rate 2×/stop đạt và hash nguồn không đổi:
[probe](subtitle-sweep/media-probe.json). Probe offscreen không có QAudioOutput;
native màn hình/GPU/EXE vẫn nghiệm thu riêng.

Không stage/commit/build/install; giữ mọi thay đổi sẵn có của người dùng.
