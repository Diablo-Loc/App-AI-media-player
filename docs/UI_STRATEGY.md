# Công nghệ cho UI mới

Quyết định theo yêu cầu mới ngày 03/10/2026: **PySide6 Qt Widgets + design system riêng + Lucide SVG offline**. Giữ các widget, signal, media/video và lifecycle gốc; nâng lớp trình bày. Không cài thêm framework hay nâng dependency. Kết quả triển khai và ảnh: [UI_REFRESH.md](UI_REFRESH.md).

| Hướng | Lợi ích | Chi phí / điều kiện |
| --- | --- | --- |
| Nâng cấp Qt Widgets hiện tại | Ít rủi ro cho video widget, subtitle overlay, mini/fullscreen và native Windows; tái dùng services | Cần design tokens, spacing/type/color nhất quán; profile grid widget trước |
| Qt Quick/QML | Animation, declarative state, model/view phù hợp UI media hiện đại | Prototype video/overlay/reparent/native; bridge Python, lifecycle và đóng gói; không chuyển một lần |
| QFluentWidgets | Có components phong cách Fluent, hỗ trợ PySide6 | Kiểm tra license và điều kiện thương mại từ repo; benchmark và kiểm tra tương thích trước khi chọn |

Đã triển khai nền graphite, accent mint, Segoe UI, heading rõ, khoảng cách nhất quán và icon cùng nét. `app/ui/design_system.py` sở hữu theme dùng chung; `app/ui/icons.py` sở hữu rendering/cache icon. Các trang giữ các API/controls hiện có. Qt Quick/QML vẫn là lựa chọn cho một prototype tương lai nếu cần animation/model-view; chưa có lý do kiểm chứng để chuyển toàn bộ video/overlay/mini/fullscreen sang kiến trúc mới.

SVG lấy từ revision Lucide `500620a2e8123f8d1db191538886dc0c223f69a9`; 40 icon có manifest SHA-256 và giấy phép ISC/MIT đầy đủ tại `app/ui/assets/icons/`. App không tải icon qua mạng lúc chạy. Nguồn: [Lucide license](https://lucide.dev/license), [revision và license nguồn](https://github.com/lucide-icons/lucide/blob/500620a2e8123f8d1db191538886dc0c223f69a9/LICENSE), [Qt QIcon](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QIcon.html), [Qt Widgets style sheets](https://doc.qt.io/qtforpython-6/overviews/qtwidgets-stylesheet-reference.html).

Nguồn framework chính thức đã tham khảo:

- [Qt for Python: tích hợp QML](https://doc.qt.io/qtforpython-6/tutorials/qmlapp/qmlapplication.html).
- [Qt Quick: animation và model/view](https://doc.qt.io/qtforpython-6.8/PySide6/QtQuick/index.html).
- [Qt Quick Controls FluentWinUI3](https://doc.qt.io/qt-6.8/qtquickcontrols-fluentwinui3.html): style có từ Qt 6.8, một số control fallback; cần kiểm tra trên runtime đang đóng gói.
- [QFluentWidgets repository](https://github.com/zhiyiYo/PyQt-Fluent-Widgets): đọc license/điều kiện của phiên bản định dùng trước khi thêm dependency.
