# Video nhỏ và trạng thái nút — 03/10/2026

## Phạm vi đã sửa

- **Shuffle/repeat vẫn xanh sau khi tắt:** icon engine cũ của đợt UI dùng mint cho mọi `QIcon.Active`. Qt dùng mode đó khi hover, kể cả sau click tắt. Nay hover giữ màu của trạng thái thật; nền hover vẫn do QSS xử lý. Không đổi boolean, signal, thuật toán shuffle hoặc danh sách phát.
- **Video nhỏ lệch/ra ngoài khung:** `VideoStage` vẫn giữ tham chiếu video dùng chung sau khi video về mini/large. Timer resize 20 ms và callback metadata còn gọi `setGeometry` theo tọa độ For You. Đã tái hiện video mini thành `(0,21,140,80)` thay vì `(0,0,140,80)`. Stage nay chỉ chỉnh video khi `parentWidget()` vẫn là chính stage; công thức aspect/subtitle khi đang ở For You giữ nguyên.
- **Surface mini không refresh ngay:** thêm `MiniVideoDock` thuộc placeholder cũ, khôi phục vị trí/visibility/z-order khi chọn media, layout đổi và frame hợp lệ đầu tiên tới. Không tạo video widget/player/sink thứ hai, không đổi output, không reset source/seek/audio/subtitle, không chuyển parent thay cho router gốc. Nó bỏ qua frame khi video thuộc large/For You/mini window, dùng timer một lần thay vì polling.

Điểm gắn adapter chỉ nằm ở `MainWindow.update_video_location`, `PlaybackBar.set_media_info` và guard `VideoStage.update_layout_execution`. Test loại đúng các câu adapter/guard mới rồi so AST của toàn bộ phần còn lại với fixture Git gốc: cả ba hàm vẫn khớp. Các hàm được đưa vào allowlist có thêm gate riêng này, không chỉ mở rộng allowlist rồi bỏ kiểm tra.

## Code nào giữ, phần nào đã tối ưu?

Không phải mọi dòng code đều giữ nguyên: UI, icon, bố cục, input guard và điều kiện hiển thị đã được sửa. Đây là các sửa lỗi/tối ưu UI có chủ đích. **61/61 source ngoài `app/ui` giữ hash gốc**: AI/ASR/translation, pipeline, workers download/library, config/path/startup/native orchestration. Các thuật toán chọn/đảo playlist, timing/margin/phụ đề, parameters/prompts/fallback/model/cache/schema chưa đổi. 189 kết nối Qt gốc vẫn nguyên; kết nối reflow của đợt UI trước và các listener nội bộ helper mới chỉ phục vụ hiển thị.

Đã có tối ưu UI: cache icon, bỏ parse QSS theo update play/pause, reuse animation, bỏ thao tác layout khi component không còn sở hữu video và refresh surface theo first-frame. **Chưa triển khai** lazy NLLB, batching cache, tối ưu editor, orchestration scan hay nâng độ chính xác trong [ROADMAP.md](ROADMAP.md). Không suy từ việc source giữ nguyên rằng đã kiểm chứng đủ mọi tính năng trên mọi runtime.

## Kết quả kiểm chứng

Windows / Python **3.11.0** / PySide6 **6.10.1** / Qt **offscreen**. Unit fixtures dùng 12 bản ghi media/cover giả và settings/storage tạm, không chạy AI/mạng.

- Full discovery: **41 test hiện tại pass + 11 module lịch sử skip**, tổng 52; không phải 52 test lịch sử của refactor đã rollback.
- Toàn bộ 41 test UI/source đạt thêm ở DPI 200%. Trong test chuột For You, đưa cửa sổ về normal sau showEvent maximize gốc để đặt nút vào màn hình offscreen nhỏ 400×400; production maximize behavior không đổi.
- 9 regression mới: icon off ở hover, click shuffle ở cả hai nơi cập nhật peer và tắt trả đúng object/order gốc; signal repeat; timer stage trễ không chạm mini/large; stage thật vẫn tính aspect như cũ; chọn media khôi phục surface ẩn/lệch mà không đổi trang; frame hợp lệ đầu refresh đúng một lần; bind lặp không thêm listener; AST phần gốc sau adapter giữ nguyên.
- 200 signal frame hợp lệ sau warm-up tạo **1 lần refresh**; 100 bind cùng video không truy cập/kết nối lại sink. Đây là operation count, không phải benchmark FPS.
- `git diff --check` đạt.

Đã probe đọc/phát **câm** file có sẵn `A Small Miracle(short).mp4` (7.390.691 byte; AV1/AAC, video 1080×1080), qua `on_media_clicked`/QMediaPlayer thật và controller mock ở ranh giới AI. Nhận frame đầu hợp lệ trước khi đổi trang, decoder không báo lỗi; geometry mini `(0,0,140,80)`, surface visible. Sau chuyển For You → mini và cho timer chạy với tỷ lệ 16:9, vuông, dọc, geometry vẫn đúng/không đổi owner. [Báo cáo](ui/stability/mini-video-probe.json). Không sửa file media, nguồn subtitle hay settings người dùng.

Probe xác nhận **decode/frame/ownership/geometry** trong offscreen, chưa chứng minh toàn bộ pixel presentation native Windows/driver hay mọi codec/audio-only/EXE. Triệu chứng đen ban đầu được xử lý bằng refresh surface khi media/frame sẵn sàng; vẫn cần xác nhận việc hiển thị native trên máy đang dùng. Không coi test này là full feature parity. Giới hạn subtitle-tools offscreen cũ còn ghi tại [UI_REFRESH.md](UI_REFRESH.md).

API tham khảo chính thức cho listener first-frame và video sink dùng chung: [Qt QVideoSink](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QVideoSink.html), [Qt QVideoWidget](https://doc.qt.io/qtforpython-6/PySide6/QtMultimediaWidgets/QVideoWidget.html).

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m tools.probe_mini_video --media "video/A Small Miracle(short).mp4" --output docs/ui/stability/mini-video-probe.json
git diff --check
```
