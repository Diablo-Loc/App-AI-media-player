# Kiểm tra đợt refactor trước

Đợt kiểm tra tiếp: 8 video ×3 đo coverage và preservation, 4 stress regressions giữ điệp khúc gần nhau/chặn filler loops xác định. Không thay production code hoặc áp refactor lịch sử. Hash subtitle source thật và các source/API gates đạt; các loop có timestamp bịa hợp lý chưa bảo đảm bị chặn. Xem [ASR_RESOURCE_AND_REPEAT_CHECK.md](ASR_RESOURCE_AND_REPEAT_CHECK.md).

Đợt subtitle quality: offset đảo dấu, midpoint/min-duration overlap, padding lần hai và text-only dedup nằm trong code baseline gốc, không phải do UI refresh. Đã cải thiện đường tạo mới theo yêu cầu, giữ default legacy và đọc source JSON cũ; không áp refactor lịch sử. Các fixture/source gates và giới hạn thực tế: [SUBTITLE_QUALITY_FIX.md](SUBTITLE_QUALITY_FIX.md).

Đợt Whisper accuracy theo yêu cầu mới: lỗi file mẫu có trong pipeline gốc—ASR nhận đoạn đầu thành credit rồi filter bỏ nó. Sửa bằng retry vùng nghi thiếu, không giữ credit hoặc kéo timestamp giả. Không áp refactor lịch sử; primary options/luồng cũ được đối chiếu AST, toàn bộ cue đã chấp nhận giữ nguyên. Xem [ASR_COVERAGE_FIX.md](ASR_COVERAGE_FIX.md).

Đợt nâng chất lượng thumbnail playlist: cải thiện decode/thu nhỏ và backing bitmap fractional DPR theo yêu cầu mới, giữ nguồn ảnh/cache key/feature logic. Không áp lại refactor nền tảng; hash ngoài UI, API và wiring gốc vẫn đạt. Xem [PLAYLIST_THUMBNAIL_QUALITY.md](PLAYLIST_THUMBNAIL_QUALITY.md).

Đợt cân chỉnh bố cục: popup bị ép 350 px dưới minimum hint 374 px, nút menu dùng AlignLeft và playlist chia khoảng trống chưa hợp lý đều nằm trong phần trình bày UI. Đã sửa trên baseline hiện tại, không áp lại refactor nền tảng; toàn bộ source gate gốc đạt. Xem [UI_LAYOUT_POLISH.md](UI_LAYOUT_POLISH.md).

Đợt video nhỏ/trạng thái nút: lỗi màu hover xanh thuộc icon engine của đợt UI; lỗi timer `VideoStage` giữ tham chiếu video sau đổi parent có trong luồng gốc và được tái hiện. Sửa UI bằng ownership guard/refresh dock, không áp lại refactor nền tảng. Đối chiếu riêng phần gốc của ba hàm sau adapter đạt AST baseline. Xem [UI_MEDIA_SURFACE.md](UI_MEDIA_SURFACE.md).

Đợt sửa tiếp theo UI: lỗi icon compact thuộc delegate mới của đợt UI, đã tái hiện bằng pixel test và sửa tham chiếu `QIcon`. Overlay nhận click và auto-hide popup được tái hiện riêng; sửa bằng input guard và điều kiện giữ bar, không đổi window flags/parent hay các pipeline gốc. Kiểm tra source ngoài UI vẫn đạt hash baseline. Xem [UI_STABILITY.md](UI_STABILITY.md); không dùng kết quả lịch sử phía dưới để xác nhận parity hiện tại.

Đợt UI sau rollback: triển khai trên code gốc, không khôi phục các package/refactor lịch sử. Chứng cứ giữ luồng và giới hạn test nằm tại [UI_REFRESH.md](UI_REFRESH.md) và `ui/original-contracts.json`.

> Lịch sử: người dùng đã khôi phục `app/` về code gốc ngày 03/10/2026. Các dòng “giữ lại/đã sửa” dưới đây mô tả bản refactor trước rollback, không phải trạng thái hiện tại. Xem [RESTORED_APP_REVIEW.md](RESTORED_APP_REVIEW.md).

Mốc đối chiếu: Git `4148c13` (BoTube v3.1.0). Đây là kiểm tra code trong workspace, không phải toàn bộ lịch sử trò chuyện ngoài phiên hiện tại. Các sửa đổi có sẵn ở `requirements1.txt`, các file bị xóa và thư mục `video/` được giữ nguyên.

## Phát hiện và xử lý

| Điểm | Kết luận / xử lý |
| --- | --- |
| Loader NLLB bị bỏ workaround của transformers | Đã khôi phục đúng workaround cũ. Model portable hiện dùng `pytorch_model.bin`; bỏ workaround khi chưa kiểm thử runtime portable có thể làm mất khả năng dịch offline. Migration sang safetensors/runtime mới cần một giai đoạn riêng. |
| Điều hướng playlist đổi sang khớp ID | Đã trả về so sánh đối tượng/equality như `list.index` cũ. Hai mục cùng ID nhưng khác metadata không được chọn nhầm. |
| Tách appearance/player làm mất tên API cũ | Khôi phục các adapter trên `MainWindow` và alias `InternalMediaPlayer`. Phần thực thi nằm trong module mới. |
| Startup / exception hook | Khôi phục `PYTHONIOENCODING`, thoát khi có exception không xử lý, và tiếp tục startup nếu khởi tạo cache tạm thất bại như trước. |
| Import `app.*`, composition root, media identity chung | Giữ lại. Tách cấu trúc, giữ công thức ID và schema dữ liệu. |
| Atomic JSON và merge settings | Giữ lại. File cũ được giữ nếu ghi thất bại; một nhóm settings không ghi đè nhóm khác. |
| Worker AI trả kết quả muộn | Giữ kiểm tra worker hiện tại/media hiện tại; kết quả job đã hủy không được ghi vào bài mới. |
| Subtitle object timing | Giữ padding cũ (-0.1/+0.1 giây). Đầu vào dict được hỗ trợ thêm, không áp padding lần nữa. |
| Báo thành công khi lưu subtitle thất bại | Sửa đường lỗi: không báo sẵn sàng khi chưa lưu được. Đây là cải thiện xử lý lỗi, không thay thuật toán tạo/dịch subtitle. |

## Giới hạn chứng cứ

38 test ở đợt đầu xác nhận các hợp đồng cơ sở và smoke UI, **không chứng minh mọi tính năng chạy tương đương trên media thật**. Đợt hiện tại có 52/52 test pass, gồm các test bổ sung đối chiếu code gốc và worker; chi tiết được ghi trong `PERFORMANCE.md` và `FEATURE_PARITY.md`.

Không đổi ASR parameters, prompt/provider dịch, định dạng tải, thiết kế UI hoặc cài/upgrade dependency trong giai đoạn này. GPU, NLLB portable, mạng, DLL native, đóng gói EXE vẫn cần chạy checklist thực tế trước release. Không kết luận rằng toàn bộ app đã đạt chất lượng thương mại chỉ từ compilation hoặc mock.
