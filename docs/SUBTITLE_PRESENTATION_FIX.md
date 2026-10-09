# Hiển thị phụ đề trên video — 04/10/2026

Phạm vi người dùng yêu cầu: phụ đề không đè lên cửa sổ sửa lyric; chữ bớt chớp/nhảy ở đầu câu. Giữ các chức năng khác, dữ liệu đã lưu, ASR/dịch/chia câu và timing hiện tại. Không đổi framework, dependency hoặc window flags/video owners.

## Nguyên nhân và thay đổi

Overlay có thể được For You tách khỏi MainWindow và đặt trên cùng. `positionChanged`, timer chuyển mode và `changeEvent` có nhiều đường gọi `show`; ẩn một lần khi mở editor không đủ vì timeline sau đó có thể hiện lại.

`ui.subtitle_presentation.SubtitlePresentationGuard` giữ tham chiếu owner gốc dù overlay bị reparent. Guard chỉ cho hiển thị trong vùng video đang hiện của cửa sổ chính, với mode/render hợp lệ và cue hiện hành. Ẩn khi dialog modal/modeless mở, popup Qt đang hoạt động, video/owner ẩn hoặc detach, cửa sổ minimized/inactive hoặc mode mini vốn không render lyric. Nó không pause player, thay window flags, đổi video parent hoặc tắt setting phụ đề của người dùng.

`SubtitleLayer.show/setVisible` chặn các lần show muộn khi context/cue không còn hợp lệ. Timeline vẫn cập nhật cache trong lúc editor mở. Đóng dialog khôi phục cue hiện hành kể cả video đang pause; đóng trong khoảng nghỉ không hiện lại chữ cũ. `MainWindow.changeEvent` giao riêng hai loại sự kiện activation/window-state cho guard; phần khác của MainWindow giữ nguyên. Filter/timer thuộc owner, coalesce event và dừng khi đóng; không có worker/poll timer mới.

Fade cũ gọi `stop()` trước khi kiểm tra animation đang chạy, khiến cập nhật gap liên tiếp khởi động fade-out lại. Mỗi lần còn nối một `finished → hide` dạng SingleShot; hủy fade không gỡ callback. Callback đó có thể chạy khi fade-in của câu mới hoàn tất và ẩn câu mới. Regression chạy snapshot trước sửa tái hiện cả reset thời gian và callback ẩn câu mới sau gap dài.

Fade mới giữ animation đang chạy cùng hướng, dùng một callback completion cố định, chỉ hide khi đích/current opacity đã về 0. Seek trở lại cùng cue trong lúc fade-out đảo về fade-in từ opacity hiện tại. Các cập nhật cùng câu không reset fade-in. **Giữ duration 220 ms, OutCubic và setting bật/tắt fade.** Khi context mất quyền hiển thị (ví dụ editor mở) thì ẩn tức thời; khi cue tự kết thúc trên video vẫn fade-out như trước.

For You có overlay parentless; `recalc_position` cũ không xử lý parentless, còn `adjustSize` có thể làm khung chữ co lại trước khi timer VideoStage đặt lại. Sau khi đổi chữ, guard dùng chính layout hiện có của VideoStage để đặt cue trước fade/paint, tránh frame đầu lệch kích thước. Chỉ áp dụng khi video còn thuộc stage và người dùng chưa kéo phụ đề; không thay margin/drag/lock hoặc thuật toán aspect ratio.

## Bảo toàn và kiểm chứng

- JSON/ASS/SRT/LRC cũ không được migrate, realign, dịch lại hoặc ghi lại. 31 file thật trong storage/output/video giữ SHA-256: [trước](subtitle-presentation/saved-before.json), [sau](subtitle-presentation/saved-after-check.json).
- Cue start/end, inclusive endpoints, khoảng nghỉ, 50 ms lead /80 ms tail, bộ chia câu, exporter/schema/cache/IDs, model/ASR/translation và AI spawn không sửa. Kiểm thử compatibility cũ vẫn chạy.
- Hai production sources được sửa: `app/ui/subs_ui/subtitle_layer.py` và riêng adapter trong `app/ui/main_window.py::changeEvent`; một helper mới. Không sửa editor save/worker lifecycle, Qt hook hoặc source ngoài UI.
- Exact source hashes/snapshots: [manifest](subtitle-presentation/reviewed-sources.json), [diff](subtitle-presentation/reviewed.patch), [helper hash](subtitle-presentation/helper-hash.json). Các gate cũ chỉ phục hồi snapshot sau kiểm tra hash approved; tests không tự capture để chấp nhận thay đổi.

| Kiểm tra | Kết quả |
| --- | --- |
| Full discovery, Python 3.11/Qt offscreen Windows | 214 total = **203 pass +11 historical skip** |
| Regression mới | **16 pass**: old-snapshot repro, fade restart/completion/reversal/opacity/geometry, inclusive endpoints, modal/modeless/nested dialogs, paused/gap restoration, hidden/detached video, inactive/minimized/mini/OFF/empty, shutdown, shell editor exec và For You parentless geometry |
| DPI 200% | **33 pass** =16 mới +10 UI stability +7 spacing/caption |
| Saved data | 31 file giữ nguyên hash |
| `git diff --check` | Đạt cho thay đổi worktree của phase; staged snapshot cũ có whitespace cố ý giữ nguyên, không trim hợp đồng |

Logs: [focused](subtitle-presentation/focused-tests.txt), [full](subtitle-presentation/test-results.txt), [DPI](subtitle-presentation/dpi2-tests.txt), [diff check](subtitle-presentation/diff-check.txt).

Test sử dụng Qt Widgets/dialog exec/animation và geometry thật với thời gian animation xác định; không gọi model/mạng hoặc đụng media/settings của người dùng. Shell editor test dùng QDialog fixture qua chính đường mở editor hiện có. Không suy kết quả này thành native video screen FPS, mọi driver/DLL/multi-monitor/EXE đều hoàn hảo; các kiểm tra đó vẫn riêng. Không build, release hoặc commit trong phase này.
