# Chất lượng thumbnail playlist — 03/10/2026

Theo yêu cầu làm ảnh nét hơn, cải thiện bước decode/thu nhỏ trong playlist. Giữ khung 140 × 78 logical px, crop giữa, bo góc 8 px, metadata, đường dẫn, mtime và cache key gốc. `ThumbnailManager` gốc đã chụp frame rộng 800 px bằng Lanczos/JPEG q=2; không cần tạo lại hay xóa thumbnail của người dùng.

## Thực hiện

`app/ui/playlist_thumbnail.py` đọc ảnh bằng QImageReader trong QRunnable, yêu cầu độ phân giải trung gian gấp hai lần kích thước pixel đích mỗi chiều, rồi thu nhỏ bằng Qt SmoothTransformation. Không phóng nguồn nhỏ lên trước bước lọc. Ảnh QImage được gửi về GUI thread; tại đó mới tạo QPixmap và giữ cách crop/bo góc gốc.

Backing bitmap dùng `ceil(width × devicePixelRatioF)` và `ceil(height × devicePixelRatioF)`. Khung 140 × 78 cần 175 × 98 pixel ở 125%, 210 × 117 ở 150%, 280 × 156 ở 200%. Kiểm tra DPR/kích thước trước khi dùng cache RAM; đổi màn hình sẽ yêu cầu refresh, kết quả thuộc DPR cũ được bỏ qua. Không thay cache key/schema hoặc ghi ảnh nguồn/settings/media. Cache đúng DPR tiếp tục tránh decode lại.

Source gate cho phép thêm đúng hai hàm trình bày `LazyThumb._start_async_loading` và `LazyThumb._on_loaded`. API và kết nối finished cũ giữ nguyên; thêm handler event DPR không thêm Qt signal binding. Worker decode Home/Library gốc và mọi source ngoài UI không thay đổi.

## Kiểm chứng

Windows, Python 3.11.0, PySide6 6.10.1, Segoe UI, Qt offscreen. Tám regression kiểm tra JPEG thật so với reference, decode nền/QImage/nhận ở GUI thread, canvas fractional DPR, crop/bo góc/cache key, cache reuse và đổi DPR, kết quả stale, nguồn nhỏ/cancel, ảnh thực tế trong widget. Đạt 8/8 ở scale 100%, 125%, 150%; ở 200% đạt thêm cả sáu regression bố cục (14/14).

Probe offline dùng một JPEG tổng hợp 1120 × 624, output 140 × 78. Reference là decode JPEG nguyên kích thước rồi Qt SmoothTransformation. Sai số RGB trung bình ở vùng trong ảnh: **0,6958 cũ → 0,3348 mới**. Đây là khoảng cách với reference trên một fixture, không phải tăng độ nét gấp hai lần hoặc kết quả tổng quát với mọi cover. Không có benchmark tốc độ; ảnh trung gian lớn hơn tăng công việc decode/lọc, được thực hiện nền và chỉ lưu output theo pixel màn hình. Tùy codec, QImageReader có thể cần decode ảnh nguồn đầy đủ.

Chạy lại probe: `python -m tools.playlist_thumbnail_probe --output docs/ui/thumbnail-quality/probe`. [Dữ liệu đo](ui/thumbnail-quality/probe/probe.json), [ảnh cũ phóng 4×](ui/thumbnail-quality/probe/before-4x.png), [ảnh mới phóng 4×](ui/thumbnail-quality/probe/after-4x.png), [playlist sau sửa](ui/thumbnail-quality/after/playlist.png). Preview được kiểm tra bằng ảnh widget thật với media tổng hợp và storage tạm.

Suite bắt buộc: **55 pass + 11 skip lịch sử = 66 test discover**, `git diff --check` đạt. 61 source ngoài UI tiếp tục khớp hash gốc; API/signals và 189 kết nối Qt gốc còn nguyên, cùng một kết nối reflow từ đợt UI trước. Không thay pipeline phát/playlist/download/AI/subtitle.

Ảnh nguồn mờ hoặc thiếu chi tiết vẫn giới hạn chất lượng cuối cùng. Chưa xác nhận trải nghiệm trên mọi ảnh/media thật, chuyển giữa màn hình Windows vật lý hay EXE; không đánh dấu full parity hoặc hiệu năng toàn app đã hoàn thành.
