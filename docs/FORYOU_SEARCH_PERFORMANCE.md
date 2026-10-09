# For You: search, hàng đợi phát và cuộn danh sách

Loading bổ sung hiện hành: xem [FORYOU_SEARCH_LOADING.md](FORYOU_SEARCH_LOADING.md). Báo cáo dưới đây giữ số đo và hành vi của phase trước loading; clear hiện dùng spinner và chuẩn bị hợp tác trước reveal, thay cho việc đổi view ngay. Queue/order, viewport pool và ngân sách decoder vẫn giữ.

Ngày 04/10/2026. Phạm vi: playlist For You trên baseline đang chạy; giữ Qt Widgets, không áp lại refactor kiến trúc trước.

## Hành vi sau sửa

- Search chỉ lọc danh sách hiển thị theo tên bài hoặc nghệ sĩ, không phân biệt hoa/thường như trước. Gõ có debounce 300 ms; xóa hết hoặc chỉ còn khoảng trắng khôi phục danh sách ngay.
- Người dùng đã chọn **Next/Previous chạy toàn playlist**. Click kết quả search giữ exact media object, cập nhật bài đang phát; kết quả lọc không ghi đè master hoặc hàng đợi phát.
- Tìm query khác vẫn giữ bài đang phát và hàng đợi đầy đủ. Bài đang phát không khớp query sẽ không có dòng highlight trong kết quả đó.
- Xóa search hiện đủ danh sách theo thứ tự phát hiện tại. Đang shuffle thì giữ chính thứ tự đã trộn; không trộn lại khi clear. Tắt shuffle trở về thứ tự master, giữ cơ chế đưa bài hiện tại lên đầu khi bật shuffle như trước.
- Playlist rỗng thực sự xóa các dòng cũ. Không có kết quả search chỉ làm rỗng view.

## Nguyên nhân đã xác nhận

Code trước sửa lọc metadata trên GUI thread rồi xóa/dựng lại các widget. Khi bài đang phát ở cuối, `refresh_playlist_ui`/`mark_playing_item` dựng mọi batch từ đầu đến vị trí bài đó. Search không chạy toàn bộ dưới nền: chỉ phần decode thumbnail chạy nền.

`isVisible()` của thumbnail không kiểm tra ảnh có bị viewport cắt hay không, nên các dòng ngoài vùng nhìn vẫn có thể decode. Các decode dùng global thread pool; `_is_loaded` không được đặt sau thành công, có thể gửi lại công việc. Mỗi lần gõ còn tạo graphics opacity effect cho danh sách.

## Thay đổi thực thi

`app/ui/foryou_playlist_view.py` quản lý một nhóm QPushButton được tái sử dụng quanh viewport, với chiều cao canvas đại diện toàn danh sách. Cuộn gộp cập nhật trong timer 16 ms, không dựng từng dòng từ đầu tới bài đang phát. Số widget phụ thuộc chiều cao viewport lớn nhất đã dùng, không phụ thuộc số bài. API cũ trên `ForYouPage` giữ chữ ký và chuyển tiếp sang helper; `loaded_count`/`cards_map` biểu diễn các dòng đang dựng, không còn prefix của danh sách. Đã tìm callers trong `app/`: không có caller ngoài page phụ thuộc layout/prefix đó.

Search vẫn quét metadata đã nằm trong RAM, không đọc video/ffprobe hoặc nạp tất cả ảnh. Đây là phép lọc O(N) đồng bộ sau debounce, **không phải worker search mới**; 10.000 mục đã đo bên dưới. Widget được tạo và đổi nội dung trên GUI thread; QImage được decode nền.

`app/ui/playlist_thumbnail_queue.py` sở hữu pool tối đa **2 decoder**, chỉ nhận ảnh thực sự cắt qua viewport. Rebind/scroll hủy yêu cầu cũ; kết quả sai key/DPR hoặc ngoài viewport bị bỏ. `done` được phát cả khi lỗi/hủy để giải phóng ngân sách; queue giữ worker đến completion và đợi pool khi ứng dụng shutdown. Không chờ pool khi search/cuộn. Thumbnail standalone giữ đường gọi global pool để tương thích callers cũ. Giữ nguồn ảnh, cache key, kích thước 140×78, supersampling, crop, bo góc và fractional DPR; body decode được đối chiếu AST với snapshot trước sửa. Giữ độ nét đã nâng ở pha trước.

`MainWindow.on_media_clicked` lấy full playback order khi nguồn là For You và không thay master bằng kết quả search. `toggle_global_shuffle` cập nhật full queue rồi áp lại query cho view. Phần native video/source/play, navigation wrap, subtitle/AI/download/settings và window lifecycle ngoài hai adapter này giữ source gates cũ. `LazyThumb` ghi nhận trạng thái tải/DPR; đổi màn hình vẫn yêu cầu ảnh đúng DPR.

## Số đo

Windows, Python 3.11.0 của `venv`, PySide6 6.10.1, Qt **offscreen**. Mỗi workload chạy 3 lần; bảng là median. Không dùng số đo refactor lịch sử.

| Workload | Trước sửa | Sau sửa |
| --- | ---: | ---: |
| Nạp 1.000 metadata, current ID ở cuối | 1.052 ms | 28,9 ms |
| Xóa search khôi phục 1.000 mục | 1.130 ms | 13,6 ms |
| Widget mới được dựng trong thao tác clear | 1.000 | 0 (tái sử dụng) |
| Dòng được giữ sau workload trên | 1.000 | 8 |
| Nạp 10.000 metadata sau sửa | Chưa đo | 21,3 ms |
| Clear 10.000 metadata sau sửa | Chưa đo | 12,0 ms |

Metadata workload không có ảnh, tách chi phí dựng widget khỏi decoder. Thời gian thao tác gồm xử lý đồng bộ; không phải cam kết thời gian hiện pixel trên màn hình. Workload scroll trong JSON có 40 ms pump chủ động, không coi toàn số đó là chi phí cuộn. Kết quả: [before-1000.json](foryou-search/before-1000.json), [after-1000.json](foryou-search/after-1000.json), [after-10000.json](foryou-search/after-10000.json).

Video thật `video/Brand New Sky.mp4` (11.431.119 bytes; AV1 1080×1080, 25 fps theo log Qt), cùng 1.000 mục và cover JPEG 1280×720 trong thư mục tạm; 8 thao tác mark cuối/search/clear/cuộn/query/clear, mỗi thao tác có pump 300 ms. Probe dừng timer khi gọi filter trực tiếp để mỗi search/clear chỉ lọc một lần; các số dưới đây là lần chạy lại sau chuẩn hóa này, thay số sơ bộ trước đó. Dùng QMediaPlayer + QVideoSink thật, âm lượng 0, không AI/network. Ba cặp process riêng, không chạy benchmark song song:

| Median của giá trị lớn nhất mỗi lần chạy | Trước sửa | Sau sửa |
| --- | ---: | ---: |
| Khoảng ngắt nhận decoded frame trên GUI | 1.843 ms | 47,4 ms |
| Khoảng ngắt heartbeat GUI (timer 10 ms) | 2.495 ms | 27,4 ms |
| Tổng workload với pump chủ động | 12,30 s | 2,83 s |
| Dòng đang dựng ở cuối workload | 1.000 | 11 |

Sáu lần đều nhận frame thật và `player_error` rỗng. [Tổng hợp](foryou-search/video-summary.json); JSON/log từng lần ở `foryou-search/video-before-*` và `video-after-*`. Khác nhau về tổng thời gian nên **không so số frame thô như FPS**. Đây là bằng chứng giảm chặn GUI khi có decoder thật; chưa đo native screen presentation, âm thanh qua DLL của app, nhiều codec/máy/GPU, tải AI đồng thời hoặc EXE.

## Kiểm chứng và giới hạn

10 regression mới kiểm tra full queue, search/clear/query khác, Next/Previous, shuffle không đổi thứ tự khi clear, exact media object sau tái sử dụng dòng, highlight, 10.000 mục với số dòng giới hạn, bài cuối ngay sau reload/resize, debounce/latest query/empty playlist, chỉ ảnh visible được decode và tối đa hai worker, error/cancel completion, body decode giữ nguyên.

Discovery ở scale mặc định và 200%: **133 pass + 11 historical skip (144 tổng)**. Source/API/signature/signal/connection gates cũ giữ nguyên ngoài các adapter được capture chính xác tại `foryou-search/approved-adapters.json`; không mở allowlist rộng cho toàn bộ playlist. Body decode giữ AST cũ. `git diff --check` đạt. Render Qt được xem tại [for-you.png](foryou-search/screenshots/for-you.png), dữ liệu/settings giả lập trong thư mục tạm.

Các phép thử nhiều fixture UI trong một process nhỏ có thể gặp lỗi tái import Qt của helper cô lập; full discovery ở cả hai scale đã hoàn tất. Không coi mock native player trong regression là xác nhận playback thật: probe decoder tách riêng bên trên. Bản EXE/native presentation và thư viện lớn hơn 10.000 mục chưa kiểm chứng; không tuyên bố toàn app/full feature parity. Saved subtitle, Whisper options, timestamp rollback 50/80 ms, fade, media IDs và schemas không thay đổi trong pha này.

Chạy lại:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
.\venv\Scripts\python.exe -m tools.foryou_search_probe --before --output docs/foryou-search/before-1000.json
.\venv\Scripts\python.exe -m tools.foryou_search_probe --output docs/foryou-search/after-1000.json
.\venv\Scripts\python.exe -m tools.foryou_search_probe --count 10000 --output docs/foryou-search/after-10000.json
.\venv\Scripts\python.exe -m tools.foryou_video_probe --media 'video/Brand New Sky.mp4' --before --output docs/foryou-search/video-before-1.json
.\venv\Scripts\python.exe -m tools.foryou_video_probe --media 'video/Brand New Sky.mp4' --output docs/foryou-search/video-after-1.json
```

Snapshot pre-phase ở `foryou-search/original/`; worktree đang có các thay đổi của pha trước nên không dùng `git checkout` toàn app để rollback riêng phase này.
