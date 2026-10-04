# Hiệu ứng phụ đề theo câu — 04/10/2026

Đã mở rộng nhóm hiệu ứng tùy chọn theo yêu cầu: phi tiêu xoay qua từng vùng
từ, sao lấp lánh, sao băng, đom đóm, tuyết, cánh hoa, bong bóng, tinh thể và
dải cực quang. Có **9 bộ mẫu**, 3 mức mật độ và 3 chuyển cảnh mới: bừng sao,
lắc nhẹ, lượn nhẹ. Các hiệu ứng chuyển động/màu/mờ của phase trước vẫn dùng được.

Vào **Cài đặt phụ đề → Tùy chọn khác → Hiệu ứng phụ đề**, bật nhóm rồi chọn
**Bộ mẫu → Phi tiêu ánh bạc** để thử phong cách gần hình tham khảo. Chọn bộ
mẫu không tự bật công tắc chính; từng thành phần vẫn chỉnh riêng được. Mật độ
Nhẹ phù hợp khi muốn ưu tiên đọc chữ. Preview sử dụng renderer thật và dừng
khi đóng khung. Không thêm font, asset tải mạng hay thư viện mới.

[Ảnh các bộ mẫu](subtitle-particles/screenshots/presets.png) ·
[GIF xem chuyển động](subtitle-particles/screenshots/presets.gif) ·
[Khung cài đặt](subtitle-particles/screenshots/settings-particles.png).

## Phạm vi và tính tương thích

- OFF mặc định. Khi tắt, dùng renderer gốc; cấu hình cũ thiếu `trail` vẫn là
  `none`, không tự nâng cấp hiệu ứng đã lưu hoặc ghi lại settings lúc load.
- Chỉ mở rộng `ui.subtitle_effects`, `ui.subtitle_effects_panel` và thêm
  `ui.subtitle_particles`. MainWindow, SubtitleLayer, SettingsPanel, audio,
  playlist, ASR, dịch, export và load/save phụ đề không đổi trong phase này.
- Thời gian cue, padding 50/80 ms, inclusive endpoints, Fade/220 ms OutCubic,
  mode, font, drag/lock và chủ sở hữu cửa sổ/video giữ nguyên. Không sửa file
  subtitle hoặc video; dữ liệu appearance chỉ lưu khi người dùng chỉnh.
- Lượt quét hiệu ứng là **trang trí theo thời lượng câu**, không phải timing
  từng từ hát. Sub hiện tại không có word timestamps đáng tin cậy để khẳng định
  ngôi sao tới đúng từ đang hát. Phi tiêu làm mờ vùng từ rồi trả về nguyên chữ;
  opacity thấp nhất 70%/50%/35% tùy mật độ, không xóa nội dung chữ.
- Yêu cầu mới cho phép một lượt hạt chạy trong thời lượng cue. Điều này mở rộng
  giới hạn chỉ entry animation của phase [SUBTITLE_EFFECTS](SUBTITLE_EFFECTS.md),
  không thay đổi đường render khi tắt hoặc hiệu ứng cũ không chọn hạt.

## Câu dài, ngắn và Unicode

Dùng biên grapheme UTF-16 của Qt để không cắt dấu tổ hợp, emoji ZWJ, cặp
surrogate hoặc cờ. Ngôn ngữ có khoảng trắng dùng vùng từ; CJK/emoji dùng cụm
grapheme. Toàn dòng vẫn được shape bằng Qt, giữ bidi/RTL; không render lại từng
chữ rời. Đây không phải bộ phân tích ngôn ngữ để tìm từ đúng ngữ nghĩa ở mọi
ngôn ngữ không có dấu cách.

Vùng trang trí chỉ nằm trong khung chữ hiện có. Câu nhiều từ tự gom nhóm,
tối thiểu khoảng 90 ms/slot và tối đa 256 vùng cache; dòng bệnh lý trên 8192
UTF-16 units dùng một dải. Câu dưới 160 ms không chạy hạt/biến hình gây chớp;
chữ vẫn hiện và entry cũ vẫn rút ngắn theo thời lượng cue. Câu một ký tự,
một từ, dấu câu, nhiều dòng, khoảng trắng/rỗng đều có kiểm tra riêng. Chữ gốc
không thay đổi, cuối câu trở về đủ chữ, không kéo dài cue hoặc lấn câu sau.

## Hiệu năng và lifecycle

Một timer thuộc renderer, interval 33 ms, chỉ chạy khi có cue đang phát và
khung sub đang hiển thị. Pause giữ nguyên frame; stop, nguồn mới, ẩn, editor,
OFF và hết cue dừng timer. Seek ngược và rate 2× lấy lại phase từ media clock.
Nội suy giữa các cập nhật position chỉ tối đa 100 ms × rate; stalled/loading
ngừng quét. Preview không có player kết thúc bằng clock riêng có giới hạn.

Tối đa **8/16/24 dấu/hạt trên toàn khung mỗi frame**, không một animation/worker
cho mỗi từ. Cache một layout và sprite DPR tối đa 2 triệu pixel (~8 MB); path
hình dùng lại. Không decoder mới, không thread mới, không setSource/seek từ
renderer. Timer chỉ update khi phase thực sự thay đổi.

Probe Windows/Python 3.11/Qt offscreen/DPR 1, khung 900×240, JP+EN+VI dài,
mật độ Rực rỡ, 120 frame/style sau warm-up: median render các style hạt khoảng
**0,30–0,49 ms**, p95 cao nhất **0,59 ms**, một layout/path cache. Frame lạnh
tạo glyph cache mất **40–47 ms** trong fixture này; chưa đảm bảo không khựng
khi cache mới trên mọi máy. Đây là chi phí render cô lập, không phải FPS hoặc
CPU toàn app. [Số đo đầy đủ](subtitle-particles/render-probe.json).

## Kiểm chứng

- 14 regression mới, gồm ma trận **6.000 tổ hợp frame/độ dài/font/style**;
  Unicode, bidi, dữ liệu cực dài, một ký tự/từ, câu dưới 160 ms, cue lặp,
  pause/stall/rate/seek, preview/hide/editor và round-trip preset/settings.
- Full discovery: **357 pass +11 historical skip**; DPI 200%: **48 pass**;
  disposable checkout/source gates: **27 pass**. Log trong
  [subtitle-particles](subtitle-particles/full-tests.txt).
- 119 source trước phase được đối chiếu toàn module qua adapter exact đã review.
  Snapshot/manifest các phase cũ không recapture; chỉ thêm snapshot phase này.
- **814/814 file dữ liệu/media/settings/export giữ nguyên SHA-256**;
  [báo cáo](subtitle-particles/saved-check.json).
- Probe một video VP9/Opus có sẵn với QMediaPlayer/QVideoSink thật, 73 frame:
  pause đứng yên, seek ngược, tiếp tục 2×, stop sạch, hash nguồn không đổi.
  [Kết quả](subtitle-particles/media-probe.json). Probe không có QAudioOutput,
  không chứng minh FPS native trên màn hình, mọi GPU/màn hình hay EXE.

Đã giữ index người dùng, không stage/commit/build/install. Đóng gói EXE và
nghiệm thu trực tiếp trên thiết bị vẫn riêng; không tuyên bố mọi case có thể
xảy ra hoặc toàn app đạt parity chỉ từ bộ regression.

Tham khảo [Aegisub karaoke effect templates](https://aegisub.org/docs/latest/automation/karaoke_templater/)
cho cách tổ chức hiệu ứng theo dòng/từ;
[Qt grapheme boundaries](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTextBoundaryFinder.html)
và [QTextLine cursorToX](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QTextLine.html)
cho Unicode và vị trí vùng chữ. Implementation là Qt painter trực tiếp,
không đưa template Lua hay pipeline ASS vào playback.
