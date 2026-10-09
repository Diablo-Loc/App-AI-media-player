# Ổn định sidebar và playback bar — 03/10/2026

Đợt tiếp theo bổ sung sửa mini video và trạng thái hover: xem [UI_MEDIA_SURFACE.md](UI_MEDIA_SURFACE.md), kết quả hiện tại 41 pass + 11 skip lịch sử. Phần dưới lưu kết quả 32 test của đợt ổn định trước.

Đợt này sửa các lỗi người dùng báo sau khi nâng UI. Giữ PySide6 Widgets, video widget dùng chung, luồng phát, phụ đề, shortcut, model và dữ liệu gốc. Không thay framework hay dựng lại kiến trúc nghiệp vụ.

## Lỗi đã tái hiện và cách sửa

| Vấn đề | Bằng chứng trước sửa | Bản sửa |
| --- | --- | --- |
| Mất icon khi thu sidebar | `styled.icon` là wrapper tham chiếu; xoá property khiến wrapper đã giữ cũng thành icon null. Ảnh thu gọn trống icon | Sao chép `QIcon(styled.icon)` trước khi xoá decoration; tự vẽ icon ở giữa, selected có màu mint |
| Click playback bị lớp phụ đề nhận | Qt hit-test trả `SubtitleLayer` khi phụ đề nổi nằm trên nút loa | Guard loại vùng control khỏi mask của overlay; chuyển tiếp press/move/release tới control nếu platform vẫn đưa sự kiện cho overlay |
| Bar tự ẩn khi mở volume/settings/info | Gọi `hide_controls()` lúc popup mở làm bar biến mất | Giữ bar hiện khi popup mở, đang kéo seek hoặc đang nhấn nút; vẫn tự ẩn khi kết thúc thao tác |
| Cửa sổ bị ép rộng | Download có status tối thiểu 400 px, progress 300 px và nhiều control cùng một hàng; stack dùng minimum hint lớn nhất của các trang | Header/footer Download tự dàn lại khi hẹp; progress/path linh hoạt, status xuống dòng; search toolbar co giãn |
| Playback chật khi thu cửa sổ | Info 300 px, utilities 310 px cố định | Grid thích nghi ở 1000 px: màn rộng dùng ba cụm; màn hẹp đặt seek trên hàng điều khiển, giữ đủ 12 nút và thumbnail 140×80 |
| Bấm menu nhanh gây animation chồng | Mỗi lần tạo một group mới; min/max width dùng easing khác nhau, target dựa vào độ rộng giữa animation | Một group sở hữu hai animation, cùng OutCubic/200 ms; đảo target từ vị trí hiện tại; reflow grid sau khi hoàn tất |

Chiều cao playback vẫn **110 px**, quy tắc subtitle margin **140/40/0** và toàn bộ timing/fade/drag/lock vẫn thuộc code gốc. Không chuyển parent hay thay window flags của subtitle/video. Metadata vẫn giữ HTML và tooltip đầy đủ; phần vẽ tự elide title/artist khi thiếu chỗ. Nút phụ có vùng bấm 36×36, play 40×40.

`app/ui/overlay_input_guard.py` chỉ xử lý vùng input giữa overlay và control; có timer một lần để cập nhật sau native Show/reparent, không polling. Mask giống nhau không ghi lại. `app/ui/track_label.py` xử lý phần vẽ metadata. Tất cả control và signal cũ vẫn thuộc component cũ.

## Kiểm chứng và giới hạn

Môi trường: Windows, venv Python **3.11.0**, PySide6 **6.10.1**, Qt **offscreen**. Fixture 12 media giả, cover 640×360, storage/settings tạm; không tải model, phát media, chạy download hay ghi dữ liệu người dùng.

- Full discovery: **32 test hiện tại pass, 11 module lịch sử skip**, tổng 43. Test lịch sử thuộc bản refactor đã rollback, không tính là feature pass.
- 10 regression mới chạy thêm ở `QT_SCALE_FACTOR=2`: **10/10 pass**. Quét pixel cả 5 icon sidebar; kiểm tra vị trí/hit target/không chồng lấn của 12 nút qua các chiều rộng 760–1280 px; click chuột Qt thật mở volume; click khi overlay đè lên nút; giữ drag bên ngoài control; popup/seek/button chống auto-hide; Download không cắt control.
- 61/61 source ngoài UI vẫn giữ hash gốc; chữ ký 399 API và 55 signal giữ nguyên. 189 kết nối Qt gốc giữ nguyên, thêm đúng **một** kết nối presentation `anim_group.finished → refresh_grid`. Fixture gốc không bị viết lại. `hide_controls` được bổ sung vào allowlist UI, có test riêng cho hành vi mới.
- `git diff --check` đạt. Ảnh được render lại sau khi debounce/animation hoàn tất và được xem trực tiếp.

Offscreen chưa chứng minh input/window stacking native trên Windows hay playback/decoder thật. Platform này không áp window mask như desktop; regression gửi chuột tới widget mà Qt hit-test thực sự chọn và xác nhận đường chuyển tiếp mở popup đúng một lần. Focus của main window được giả lập active chỉ trong ca overlay để tách việc Alt+Tab khỏi kiểm tra input; production activation handling giữ nguyên. Cần kiểm tra media thật, kéo phụ đề, fullscreen/mini, nhiều màn hình/DPI và bản EXE trước khi xác nhận parity toàn bộ. Lỗi native của production subtitle-tools dialog trong offscreen ở cả gốc và mới vẫn ghi tại [UI_REFRESH.md](UI_REFRESH.md), không được tính là đã sửa.

## Đo tối ưu cụ thể

Phép đo dùng Qt thật, trích nguyên function `toggle_nav_animation` từ Git `4148c13`, fixture widget tối giản, 50 lần toggle. [Kết quả](ui/stability/operation-counts.json): bản gốc giữ **50 group / 100 animation**, bản mới **1 group / 2 animation**. Test rapid-click riêng còn chạy event loop giữa các lần bấm và kiểm tra target/width cuối. Đây là số object được giữ lại, không phải benchmark FPS hoặc CPU/GPU.

200 lần gọi lại guard với hình học không đổi: **0 lần `setMask`**. Kết quả 200 update play/pause không parse lại QSS ở đợt UI trước tiếp tục được test. Chưa có đo tải media lớn hoặc FPS để tuyên bố toàn bộ app nhanh hơn một tỷ lệ nào.

## Ảnh và lệnh chạy

- Sidebar: [trước sửa](ui/stability/before-collapsed.png) → [sau sửa](ui/stability/after-collapsed.png).
- Layout: [1280 px](ui/stability/layout-1280.png), [900 px](ui/stability/layout-900.png), [760 px](ui/stability/layout-760.png).
- Download: [màn rộng](ui/stability/download-wide.png), [màn hẹp](ui/stability/download-compact.png).

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m tools.ui_stability_preview
git diff --check
```

Ảnh dùng dữ liệu giả để xem bố cục; khung video đen không chứng minh decoder hoạt động. Bộ ảnh `ui/after/` và con số 22 test trong báo cáo UI trước là kết quả lịch sử của đợt đó; bộ `ui/stability/` và kết quả ở đây là đợt sửa hiện tại.
