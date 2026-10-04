# Cân chỉnh For You và thanh tiêu đề — 04/10/2026

Người dùng yêu cầu search cân đối trên/dưới, giảm khoảng cách trái/phải/đáy của nội dung và làm thanh tiêu đề đồng bộ hơn, giữ chức năng. Giữ PySide6 Widgets và bộ icon hiện có. Đợt này chỉ sửa presentation; không đổi search/filter/loading, playback queue/shuffle, video/subtitle lifecycle, AI, dữ liệu hoặc cấu hình đã lưu.

## Bố cục

Gutter chung **12 logical px**: header, bốn mép body, khoảng giữa cột video/thông tin và playlist, khoảng video–metadata. Search cao 40 px trong header 64 px nên trên/dưới đều 12 px; hai vùng đầu/cuối header cùng rộng 96 px để search nằm giữa thật sự.

Lỗi khoảng cách lớn đến từ padding cộng qua hai lớp: wrapper chung trước là `(20, 18, 20, 16)`, body For You là `(16, 8, 8, 8)` và gap hai cột 20 px. `ui.foryou_spacing` bỏ padding/spacing wrapper và browser gap **chỉ khi For You đang là trang được chọn**. Chuyển sang trang khác trả lại chính các giá trị layout đã có trước khi cài helper, không áp gutter mới cho toàn app. Helper do window sở hữu và chỉ cài một lần.

Video stage, tỷ lệ ảnh/video, vị trí subtitle và các hàm resize/mode vẫn nguyên. Metadata tên bài/nghệ sĩ dưới video vẫn còn; mép đáy **toàn cột trái gồm metadata** cùng gutter 12 px với đáy playlist. Không kéo video phủ lên vùng thông tin để làm hai frame bằng chiều cao.

Header QSS được scope vào `#forYouHeader` để border/background không lan xuống children. Giữ QLineEdit hiện tại, action search, placeholder, signal và debounce. Không thêm animation hoặc tải ảnh vào GUI thread. Viewport row pool, loading overlay và hai decoder giữ nguyên.

## Thanh tiêu đề

`ui.native_frame_style` dùng `DwmSetWindowAttribute` để đổi caption sang graphite `#0D1118`, chữ `#EDF3FA`, viền `#273445`. Các thuộc tính màu được Microsoft hỗ trợ từ Windows 11 build 22000; hệ điều hành/API không hỗ trợ trả lỗi thì giữ mặc định, không ngăn startup. [Microsoft: thuộc tính DWM](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute), [DwmSetWindowAttribute](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmsetwindowattribute).

Đây là **tô màu native title bar**, không phải thay bằng frameless/custom caption buttons. Windows tiếp tục sở hữu kéo cửa sổ, resize, system menu, minimize/maximize/close và snap. Không gọi `setWindowFlags`, sửa `WS_STYLE`, sửa geometry, reparent video/subtitle, hoặc can thiệp message/hit-test. Observer/timer do MainWindow sở hữu, coalesce sự kiện show/WinId/state/palette; fullscreen/frameless bỏ qua styling. Sau restore frame được tô lại. Không có timer animation chạy liên tục.

Giữ PySide6 là lựa chọn phù hợp cho phạm vi hiện tại: Widgets có thể tùy biến trình bày/style; app đã có tích hợp sâu với video, overlay, mini/fullscreen và portable. Chưa có benchmark hoặc nhu cầu tính năng nào trong đợt này chứng minh cần thay framework. Qt cũng hỗ trợ native frame và điều khiển trang trí cửa sổ qua flags; đổi flags có thể hide/reparent widget, nên không dùng cho đợt polish này. [Qt Widgets/window flags](https://doc.qt.io/qt-6.5/qwidget.html), [Qt windows](https://doc.qt.io/qt-6/application-windows.html).

## Kiểm chứng

- **159 pass +11 skip lịch sử =170 total**, full unittest discovery bằng Python 3.11 dự án, 33,007 s. [Log](foryou-spacing/test-results.txt). `git diff --check` đạt.
- **7 regression mới** đạt default và DPI 200%: đo gutter ở 900×620, 1280×820, 1920×1080; search trên/dưới và horizontal center; restore các trang khác/idempotent install; flags/geometry/video/subtitle owners không bị observer sửa; pointer-sized HWND và COLORREF/sizeof đúng; unsupported DWM fallback; source gate. [Default](foryou-spacing/focused-tests.txt), [DPI 200%](foryou-spacing/dpi2-tests.txt).
- Chỉ `ForYouPage.init_ui` và một import gutter đổi trong file page; mọi class/function còn lại khớp AST snapshot trước phase. Design system chỉ thêm đúng bốn statement cài hai helper; CSS/font scope gốc còn lại khớp AST. **Toàn bộ `main_window.py` giữ nguyên byte hash** `89b6a2fe45e9ed825e84e815799e4dea4ecf42ca9e085c4db054bd3e599f0d6b`; các source/API/signals/playlist/ASR/subtitle gates hiện có tiếp tục đạt. [Snapshots](foryou-spacing/original/).
- Probe **Qt Windows thật, Windows 11 build 22631**, trên app có storage/settings/media giả trong thư mục tạm. DWM Set HRESULT đều 0; native `WS_CAPTION/WS_THICKFRAME/WS_MINIMIZEBOX/WS_MAXIMIZEBOX` và toàn style word giữ nguyên trước/sau apply. Thử normal/maximized/minimized/restore/fullscreen/exit fullscreen và flags của workflow mini restore. [Dữ liệu](foryou-spacing/native-frame.json), [log](foryou-spacing/native-probe-log.txt).
- Màu caption không hỗ trợ `DwmGetWindowAttribute` readback trên host (E_INVALIDARG), nên báo cáo phân biệt **Set thành công** với Get không hỗ trợ; không coi đó là lỗi app hoặc khẳng định đọc lại màu bằng Get thành công. Đã chụp và xem riêng caption của **cửa sổ test đã xác nhận foreground**, thấy màu/chữ đồng bộ: [ảnh native caption](foryou-spacing/native-caption.png). Không chụp desktop/app khác.
- Đã render và xem For You với dữ liệu tạm: [search/loading](foryou-spacing/preview/search-loading.png), [clear/ready](foryou-spacing/preview/clear-ready.png), [native client](foryou-spacing/native-client.png). Ảnh offscreen không có native caption và dùng media giả, không phải benchmark FPS hoặc phát video thật.

## Phạm vi còn chờ

Giữ native mechanics được kiểm tra bằng style bits, source gate và Qt state transitions; chưa tự động nhấn từng nút Windows, thử snap/drag trên nhiều màn hình/OS hoặc accessibility/high contrast. Chưa chạy EXE/update/portable hay playback media/audio DLL/GPU thật trong phase này. Không nâng dependencies, cài framework, commit hoặc release.

Phương án custom title bar/frameless toàn phần chưa triển khai: đó là thay đổi riêng cần giữ hit-test, resize, snap, system menu, DPI và mini/fullscreen restore. UI hiện tại đã bớt padding, cân đối hơn và caption đồng bộ mà không đổi cơ chế cửa sổ.
