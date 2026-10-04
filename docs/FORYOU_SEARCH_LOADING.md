# Loading khi search và xóa search For You

04/10/2026. Đây là phần bổ sung theo yêu cầu người dùng, sau [pha tối ưu playlist](FORYOU_SEARCH_PERFORMANCE.md).

## Hành vi

- Khi gõ hoặc xóa search, vùng danh sách hiển thị vòng xoay màu accent và “Đang tìm kiếm…” / “Đang khôi phục danh sách…”. Ô search và playback vẫn hoạt động; các dòng bị khóa thao tác trong lúc chuẩn bị.
- Gõ giữ debounce 300 ms. Clear không chờ debounce; chuẩn bị bắt đầu ở nhịp event loop tiếp theo. Không thêm độ trễ giả để giữ spinner lâu hơn.
- Chuẩn bị danh sách và index theo từng chunk tối đa 500 metadata, nhường event loop giữa các chunk. Đây là xử lý hợp tác bằng Qt timers trên GUI thread, không phải worker search mới. Không đọc video/ffprobe hoặc tải toàn bộ thumbnail.
- Không hiện từng phần kết quả: giữ dữ liệu view cũ dưới loading cho đến khi lọc xong, rồi đổi danh sách một lần. Trong lúc gõ tiếp, query cũ bị hủy; callback readiness không được làm lộ view đang chuẩn bị. Nếu thanh cuộn làm đổi chiều rộng viewport sau commit, căn lại các dòng dưới overlay trước khi reveal.
- Sau khi đổi data, vẫn giữ overlay trong lúc thumbnail của **vùng nhìn thấy** được áp lên Qt. Chỉ dùng tối đa hai decoder của phase trước. Thumbnail lỗi/không có ảnh được phép dùng placeholder; nếu decode chậm quá 2 giây kể từ commit thì bỏ loading để không kẹt vô hạn, ảnh có thể hiện sau. Không hủy thread bằng cưỡng bức hoặc chờ thread trên GUI.
- Vòng xoay không reset góc mỗi phím, tự dừng animation khi ẩn. Overlay theo kích thước viewport, không che video/playback. Load playlist hoặc shuffle đồng bộ vẫn giữ API cũ và hủy search đang chờ; các cập nhật đó áp query hiện tại.
- Full playback queue, master/original và thứ tự shuffle giữ nguyên; xóa search khôi phục đủ danh sách. Whisper, subtitle timing/fade, nguồn/schema đã lưu, ID và window/native lifecycle không đổi trong phase này.

## Code và giới hạn thay đổi

`app/ui/playlist_loading_overlay.py`: QWidget vẽ vòng bằng QPainter, timer 33 ms chỉ chạy khi visible. `app/ui/foryou_playlist_view.py`: generation/cancellation, chuẩn bị chunk, commit, chờ ảnh visible và xử lý lỗi. `playlist_thumbnail_queue.completed` đánh dấu completion trên GUI sau image delivery để phân biệt lỗi decode với ảnh còn chờ apply. Không đổi decode quality/cache keys/DPR.

Trong file UI gốc, chỉ đổi hai adapter `on_search_text_changed` và `execute_filter`; giữ chữ ký và wiring. Source gate tiếp tục đối chiếu body adapter chính xác ở `docs/foryou-search/approved-adapters.json`, không mở allowlist cho playlist hoặc native. Snapshot trước loading: `foryou-loading/original/`.

## Kiểm chứng

5 regression mới cộng 10 regression playlist trước: spinner cho search/clear, không publish kết quả từng phần, query supersession, animation liên tục, resize/ẩn/dừng timer, đồng bộ reload hủy search, lỗi metadata giữ view cũ và retry, chờ ảnh visible và ảnh lỗi không kẹt. Các test trước đã điều chỉnh chờ async completion, tiếp tục kiểm tra exact media object, Next/Previous full queue, shuffle/clear, số widget giới hạn và hai decoder.

Full discovery: **138 pass +11 historical skip (149 tổng)** ở scale mặc định và 200%. Source/API/signature/signal/connection gates và decode AST giữ nguyên ngoài adapter được review. `git diff --check` đạt. Log ở [test-results.txt](foryou-loading/test-results.txt) và [dpi2-tests.txt](foryou-loading/dpi2-tests.txt).

Đã render và xem cả loading/kết quả bằng Qt thật, dữ liệu/settings tạm: [search loading](foryou-loading/screenshots/search-loading.png), [search ready](foryou-loading/screenshots/search-ready.png), [clear loading](foryou-loading/screenshots/clear-loading.png), [clear ready](foryou-loading/screenshots/clear-ready.png). Video đen trong preview là fixture, không phải phép thử decoder.

## Số đo hiện hành

Windows, venv Python 3.11.0, PySide6 6.10.1, Qt offscreen, 3 lần mỗi workload, median. Metadata không có ảnh để tách chi phí khỏi decoder. Probe chờ `is_busy` kết thúc; không nhầm thời gian nhận thao tác với thời gian hoàn tất async. Search đo sau debounce, không cộng 300 ms chờ ngừng gõ.

| Workload | Nhận thao tác trên GUI | Hoàn tất chuẩn bị/reveal |
| --- | ---: | ---: |
| Search 1.000 mục | 0,08 ms | 42,5 ms |
| Clear 1.000 mục | 0,67 ms | 49,4 ms |
| Search 10.000 mục | 0,05 ms | 93,2 ms |
| Clear 10.000 mục | 0,87 ms | 108,7 ms |

Hai workload đều tái sử dụng dòng khi clear, 0 widget mới, 8 dòng đang dựng ở cuối. Tổng thời gian reveal cao hơn filter đồng bộ của phase trước vì nhường event loop và chờ readiness; mục tiêu phase này là trạng thái loading rõ ràng và không hiện kết quả dở dang, không tuyên bố cải thiện thêm thời gian hoàn tất. [1.000](foryou-loading/after-1000.json), [10.000](foryou-loading/after-10000.json).

Ba lần decoder thật với `video/Brand New Sky.mp4`, 1.000 mục và JPEG 1280×720 trong thư mục tạm, cùng 8 thao tác của probe trước, mỗi filter được thực thi một lần rồi chờ loading hoàn tất trong event loop: median khoảng ngắt nhận frame Qt tối đa **51,5 ms**, khoảng ngắt heartbeat 10 ms tối đa **25,0 ms**, tổng workload gồm các pump chủ động **2,986 s**, 11 dòng live. Cả ba nhận frame thật, không có player error. [Tổng hợp](foryou-loading/video-summary.json), dữ liệu riêng `video-after-1/2/3.json`.

Không so số frame thô thành FPS, không coi đây là native screen presentation hoặc kiểm chứng EXE/âm thanh DLL. CPU/GPU đang xử lý AI đồng thời, nhiều máy/codec và thư viện lớn hơn 10.000 mục chưa đo. Không kết luận mọi điều kiện đều không khựng. Không chạy model, mạng, updater hoặc sửa media/settings/subtitle người dùng để kiểm tra.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
.\venv\Scripts\python.exe -m tools.foryou_loading_preview --output docs/foryou-loading/screenshots
.\venv\Scripts\python.exe -m tools.foryou_search_probe --output docs/foryou-loading/after-1000.json
.\venv\Scripts\python.exe -m tools.foryou_search_probe --count 10000 --output docs/foryou-loading/after-10000.json
.\venv\Scripts\python.exe -m tools.foryou_video_probe --media 'video/Brand New Sky.mp4' --output docs/foryou-loading/video-after-1.json
```
