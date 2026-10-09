# Typography động cho phụ đề — 04/10/2026

Theo yêu cầu nâng hiệu ứng lên kiểu ứng dụng edit, thêm **8 chuyển cảnh và
8 bộ mẫu**: Mưa chữ mạnh, Domino bật nảy, Bùng nổ typography, Xoáy ngân hà,
Lật chữ điện ảnh, Sóng chữ neon, Máy chữ ánh sáng và Nhịp chữ mạnh. Các từ/
cụm ký tự có dịch chuyển, xoay, phóng lớn, bật nảy hoặc lật riêng; không chỉ
dịch nhẹ cả câu như trước. Chúng là typography 2D, không phải engine 3D.

Vào **Cài đặt phụ đề → Hiệu ứng phụ đề**, bật nhóm và chọn **Mưa chữ mạnh**.
**Lực chuyển động** chọn Nhẹ/Rõ/Mạnh; **Chia chuyển động** chọn Tự động/Theo từ/
Theo cụm ký tự. Hai ô này chỉ có hiệu lực với 8 kiểu mới. Độ dài 220/320/480 ms
vẫn là entry duration, tự rút ngắn còn tối đa nửa cue. Bộ mới chọn 480 ms và
bỏ soft fade phụ để chuyển động rõ; Fade cửa sổ gốc vẫn giữ. Bộ cũ giữ nguyên.

[GIF 8 bộ mẫu, xem chậm 2×](subtitle-kinetic/screenshots/kinetic.gif) ·
[Giữa chuyển cảnh](subtitle-kinetic/screenshots/kinetic-mid.png) ·
[Sau chuyển cảnh](subtitle-kinetic/screenshots/kinetic-settled.png) ·
[Cài đặt](subtitle-kinetic/screenshots/settings-kinetic.png).

## Rendering và trường hợp biên

Ảnh glyph của cả dòng được shape bằng Qt như trước. Typography chỉ dùng
các vùng của sprite đó, không ghép lại text bằng từng font glyph rời. Grapheme
UTF-16 giữ dấu tổ hợp, emoji/ZWJ/cờ; RTL/cursive chuyển động theo cụm từ ngay
cả khi chọn cụm ký tự. Auto dùng cụm ký tự với dòng ngắn, từ với dòng dài.
Đây không phải tách từ đúng ngữ nghĩa mọi ngôn ngữ hoặc karaoke vocal timing.

Tối đa 16 cụm toàn khung; câu dày gom thành cụm lớn. Dòng cực dài dùng band
qua guard đã có; quá nhiều dòng hiện được thì dùng một band toàn chữ thay
vì bỏ sót dòng. Cue dưới 160 ms hoặc không có sprite hợp lệ dùng glyph tĩnh
với đường hiệu ứng gốc; không ép chuyển cảnh mạnh lên cue quá ngắn.

Vùng clip và window geometry giữ nguyên. Vì vậy chữ bay/rơi từ ngoài khung
sẽ bị clip ở mép khung cho tới khi vào trong, không bay lên khu vực editor
hay ra ngoài video. Tới cuối entry, bỏ các tile transform và vẽ glyph bình
thường, cho pixel toàn chữ đúng như static renderer. Cue text/timing không
đổi; entry có thể có chữ chưa xuất hiện đủ ở đầu câu theo chủ ý bộ mẫu.

Kết hợp màu/vệt quét/ẩn chữ được hỗ trợ: mask vẫn áp dụng với từng vùng glyph,
cuối cue erase_passed vẫn không vẽ lại chữ. Các bộ mới không tự bật erase;
người dùng có thể bật checkbox đó riêng. Màu shift/shimmer hoặc erase chủ động
giảm còn tối đa 6 cụm để chặn nhân số lượt fill/mask.

## Hiệu năng và sở hữu

Tái sử dụng **QVariantAnimation entry đã có**, không thêm timer/thread/decoder.
Một plan tối đa 16 ô, không một QObject animation cho mỗi chữ. Chuyển động
là hàm thuần theo entry phase; pause/rate/seek/hide/source/end dùng những hook
cũ. Câu lặp kế tiếp dùng index identity cũ; OFF/reset dọn plan cùng cache.

Không thêm ảnh clone/cache ảnh cho mỗi tile; sprite cũ vẫn giới hạn 2 triệu
pixel (~8 MB). Vẽ đúng source rectangle của tile, tính DPR, hạn chế resample
toàn sprite khi lật/co chữ. Scale lật tối thiểu .12 để tránh transform gần
suy biến. Sau entry, không chạy tile render nữa; particle timer đã có chỉ
chạy nếu người dùng chọn hiệu ứng dọc câu.

Probe Windows/Python 3.11/Qt offscreen/DPR 1, 900×240, JP+EN+VI dài, 120
frame entry sau warm-up/bộ mẫu: median **0,37–1,81 ms**, p95 cao nhất **4,31 ms**;
max 15–16 tile, một plan và glyph path/bộ mẫu. Frame lạnh **41–49 ms** chủ yếu
tạo glyph cache/plan; không cam kết hết khựng trên mọi máy. Đây là fixture
raster, không phải CPU toàn app, FPS native, GPU hoặc EXE.
[Kết quả đầy đủ](subtitle-kinetic/render-probe.json).

## Tương thích và source scope

- Mặc định OFF và entry cũ không đổi. Hai key appearance mới
  `kinetic_strength`/`kinetic_parts` có default RAM normal/auto; không migration,
  không tự đổi lựa chọn cũ hoặc ghi settings lúc load.
- Chỉ hai helper production hiện có (`subtitle_effects`, `subtitle_effects_panel`)
  thay đổi, thêm `subtitle_kinetic`. Particle/sweep helper, shell hooks,
  SubtitleLayer, font/window/drag/lock/video/audio/playlist/ASR/dịch/export/
  schema/save/load/timing/padding/fade không đổi.
- Snapshot phase mới phục hồi hai helper cho các gate cũ, manifest trước
  giữ nguyên; không recapture. Không stage/commit/build/install.

## Kiểm chứng

12 regression mới: **1.152 tổ hợp render** text/duration/mode/parts/phase;
Unicode/cursive/dense/multiline/one-word, <=16/6 tile/cache reuse, motion
deterministic và endpoint chính xác, pixel source crop ở identity/DPR,
settled pixel bằng static, cue ngắn đọc được, erase/OFF, pause/rate/seek/câu
lặp/hide/clear, settings thật/editor/reset/preset round-trip và legacy pixel
so snapshot trước phase.

Full discovery: **377 pass +11 historical skip**; DPI 200%: **68 pass**;
disposable checkout/source gates: **29 pass**. Log:
[full](subtitle-kinetic/full-tests.txt), [DPI](subtitle-kinetic/dpi-tests.txt),
[checkout](subtitle-kinetic/checkout-tests.txt).

**814 file dữ liệu/subtitle/video/settings/export giữ SHA-256**:
[báo cáo](subtitle-kinetic/saved-check.json). QMediaPlayer/QVideoSink thật với
một video có sẵn và Mưa chữ mạnh, pause/seek ngược/2×/stop đạt, nguồn giữ hash:
[probe](subtitle-kinetic/media-probe.json). Probe không QAudioOutput/offscreen;
nghiệm thu màn hình/native GPU/đa màn hình/EXE vẫn riêng.

API Qt: [QPainter source/target image rectangles](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainter.html)
và [QTextBoundaryFinder graphemes](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QTextBoundaryFinder.html).
