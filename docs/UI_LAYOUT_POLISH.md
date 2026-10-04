# Cân chỉnh playlist, popup tải xuống và sidebar — 03/10/2026

Phạm vi: sửa ba điểm trình bày theo ảnh người dùng, trên baseline UI hiện tại. Tiếp tục dùng PySide6 Widgets và SVG offline.

## Thay đổi

- Playlist rộng 400 px thay vì 360 px. Cột số từ 24 px xuống tối thiểu 14 px, lấy cùng độ rộng theo tổng số bài để thumbnail thẳng hàng. Khoảng cách ngang 8 px, vùng metadata nhận phần chiều rộng còn lại. Thumbnail giữ 140 × 78 px, pipeline crop/DPR và cache key gốc.
- `app/ui/elided_label.py` vẽ title tối đa hai dòng và artist một dòng; thêm dấu “…” khi thiếu chỗ, giữ toàn bộ text/tooltip. Dùng font và palette của QLabel nên highlight bài đang phát vẫn đổi màu đúng. Cache bố cục theo text/font/width; không đo hay tuyên bố tăng tốc toàn ứng dụng. Offset UTF-16 được xử lý cho emoji và chữ đa ngôn ngữ.
- Popup tải xuống rộng 380 px, cao theo layout/font. Bỏ giới hạn cứng 320 × 350 px; combobox có chiều cao tối thiểu 38 px, bỏ padding dọc gây cắt chữ, căn giữa label của form. Giữ nguyên định dạng/chất lượng/độ phân giải, hạn chế MKV, auto-update và hàm lưu settings.
- Nút ba gạch căn giữa rail cả khi rộng 160 px và thu gọn 70 px; icon và handler cũ giữ nguyên.

## Chứng cứ

Fixture Qt dùng Windows, Python 3.11.0, PySide6 6.10.1, Segoe UI, backend offscreen. 12 media tổng hợp trong storage tạm; preview playlist dùng bốn bài có metadata dài. Không tải model/media, gọi network hoặc ghi settings người dùng.

Trước sửa, popup thực tế 320 × 350 px nhưng minimum size hint 310 × 374 px; ba combo chỉ cao 24 px, font cao 17 px cùng padding dọc 8 px mỗi bên. Sau sửa, popup 380 × 381 px, combo 238 × 38 px, text và hai nút đều nằm trong khung. Nút menu ở rail 70 px đổi từ `(0, 10, 36, 36)` sang `(17, 10, 36, 36)`.

Ảnh đã kiểm tra bằng render widget thật: [playlist](ui/layout-polish/after/playlist.png), [popup](ui/layout-polish/after/download-settings.png), [sidebar](ui/layout-polish/after/sidebar.png). Tái tạo: `python -m tools.ui_layout_preview --output docs/ui/layout-polish/after`. Các ảnh `before` được chụp trước patch; riêng playlist có widget fixture cũ chờ DeferredDelete trong vòng lặp preview, không dùng phần chồng ảnh đó làm bằng chứng lỗi ứng dụng. Preview sau đã flush DeferredDelete, không thay lifecycle của app.

Sáu regression mới kiểm tra geometry, elision Unicode/resize/full tooltip, click gửi đúng media một lần qua handler cũ, thứ tự playlist/highlight, vùng edit-field đủ chứa mọi lựa chọn, schema lưu JSON và tâm icon/rail bằng pixel. Cũng đạt ở DPI 200%.

Suite bắt buộc: **47 test hiện tại pass + 11 skip lịch sử = 58 test được discover**. `git diff --check` đạt. Các source gate tiếp tục xác nhận 61 source ngoài UI khớp hash baseline, API/signal gốc và 189 kết nối Qt gốc được giữ; kết nối reflow presentation từ đợt trước vẫn còn. Không mở rộng danh sách hàm được phép đổi trong source gate.

Giới hạn: Qt offscreen và handler playback được cô lập trong fixture, không chứng minh audio/video/native Windows/EXE hay toàn bộ tính năng trên dữ liệu thật. Suite có cảnh báo NumPy được import lại giữa các context preview đã có từ trước. Các tối ưu AI/library/editor và đo hiệu năng toàn app trong roadmap còn chờ.
