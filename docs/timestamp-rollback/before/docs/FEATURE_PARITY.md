# Hợp đồng tính năng của baseline đã khôi phục

Kiểm tra chi phí/loop theo yêu cầu: đo 8 video ×3, coverage median thêm 3,83–14,39 s, 801 cue trước coverage giữ text/time, không overlap; hash 21 subtitle file thật giữ nguyên. Thêm 4 stress regressions cho 30/100 filler và 2/3 câu gần nhau; **107 pass +11 skip lịch sử**. Không đổi production code; chưa khẳng định chặn mọi ASR loop/timing hoàn hảo. Xem [ASR_RESOURCE_AND_REPEAT_CHECK.md](ASR_RESOURCE_AND_REPEAT_CHECK.md).

Đợt quality mới theo yêu cầu: sửa word-boundary timing/chia câu, giữ lời lặp có thời gian riêng, lọc runaway riêng và bỏ padding lần hai chỉ cho object AI mới; source/cache của bài cũ giữ nguyên. Replay ba bộ ASR giữ inventory ký tự, overlap sau save 74→0; production ASR/export/save chạy ba video, bypass dịch. **103 pass + 11 skip lịch sử**; chưa có ground truth onset/lyrics, native/EXE/update thực tế còn chờ. Xem [SUBTITLE_QUALITY_FIX.md](SUBTITLE_QUALITY_FIX.md). Kết quả “giữ 111 cue text/time” ở đợt coverage dưới đây thuộc phase trước; profile quality hiện tại cố ý đổi timing/grouping của lần tạo mới, không đổi dữ liệu đã lưu.

Đợt accuracy Whisper: tái hiện video mất 30 s đầu, thêm recovery chọn vùng nghi thiếu với cùng model; video mẫu 27→30 cue, cue đầu 30,2→5,68 s, giữ 111/111 cue cũ trên ba video. Hai đối chứng không thêm credit/filler. **74 pass + 11 skip lịch sử**; 60 source ngoài UI khác giữ hash, pipeline ASR đối chiếu AST sau adapter có chủ đích. Chưa khẳng định mọi bài đầy đủ/đúng 100% hoặc parity dịch/native/EXE. Xem [ASR_COVERAGE_FIX.md](ASR_COVERAGE_FIX.md).

Đợt chất lượng thumbnail: worker QImage supersampling, canvas/DPR chính xác và cache reuse theo DPR; giữ kích thước/crop/bo góc/key/path nguồn, không sửa ThumbnailManager. **55 pass + 11 skip lịch sử**, tám regression mới ở scale 125%/150%/200%; native/EXE còn chờ. Xem [PLAYLIST_THUMBNAIL_QUALITY.md](PLAYLIST_THUMBNAIL_QUALITY.md).

Đợt cân chỉnh bố cục: playlist có metadata elision, popup bỏ ép chiều cao và nút menu căn giữa. Giữ kích thước/cache thumbnail, thứ tự/click/highlight và lựa chọn/schema tải xuống; sáu regression Qt mới đạt cả DPI 200%. **47 pass + 11 skip lịch sử**; hash/API/signals gốc tiếp tục đạt, native/EXE còn chờ. Xem [UI_LAYOUT_POLISH.md](UI_LAYOUT_POLISH.md).

Đợt video nhỏ/trạng thái nút: sửa màu hover giả trạng thái bật, chặn timer For You tác động video đã chuyển owner, thêm refresh mini theo media/first-frame. 61 source ngoài UI giữ hash gốc, thuật toán playlist và subtitle không đổi; AST ba hàm gốc khớp sau khi loại đúng adapter mới. **41 pass + 11 skip lịch sử**, thêm kiểm tra DPI 200% và probe decoder/frame với một video có sẵn; native presentation/EXE chưa xác nhận toàn bộ. Xem [UI_MEDIA_SURFACE.md](UI_MEDIA_SURFACE.md).

Đợt ổn định UI sau phản hồi: đã sửa icon thu gọn và tương tác playback/overlay, thêm responsive nhưng giữ video owner, subtitle timing/margin/lock và dữ liệu gốc. **32 test hiện tại pass + 11 skip lịch sử**; 10 regression mới đạt thêm ở DPI 200%. Giữ nguyên 189 kết nối Qt gốc, thêm một kết nối reflow grid sau animation. Xem [bằng chứng và giới hạn native/EXE](UI_STABILITY.md).

03/10/2026: `app/` đã được khôi phục và audit theo code gốc `4148c13`. Sau đó người dùng cho phép nâng cấp UI. Giai đoạn UI dùng code gốc làm chuẩn hành vi; xem [kết quả và giới hạn kiểm chứng](UI_REFRESH.md). Test/benchmark của refactor cũ vẫn thuộc lịch sử.

Giai đoạn UI: kiểm tra hash mọi source ngoài `app/ui`, chữ ký API/signal, toàn bộ kết nối Qt và các hàm UI ngoài phần trình bày so với fixture gốc. Kiểm tra Qt thực tế cho điều hướng, thanh phát, seek, âm lượng, repeat/shuffle, fullscreen, mini player, settings và dán link. Đây là kiểm chứng theo phạm vi, chưa xác nhận parity đầy đủ với media/GPU/network/native/EXE. Công cụ phụ đề có lỗi native trong offscreen ở cả bản gốc và bản mới; ảnh công cụ sử dụng adapter chỉ dành cho preview, không tính là runtime pass.

| Nhóm | Phải giữ | Chứng cứ hiện tại / cần trước khi sửa |
| --- | --- | --- |
| Startup/portable | Entry script, libs/PATH, freeze support, stdout guard, DLL/model/assets/storage/QSettings | Source review; actual EXE trước/sau packaging/import migration |
| Library | Recursive; các đuôi gốc; bỏ file tạm; ID path+size; title/artist cache; probe duration 0 | Source snapshot; metadata/ID/order fixtures và media thật |
| Home/Library/For You | Mtime, home random tối đa 20, batch/search/filter/shuffle/repeat/highlight/scroll | Source review; actual UI trước/sau |
| Thumbnail/image | Metadata/file cache; cover→15s→1s; quality/path/ID/crop/DPR/cache keys | Source review; cùng ảnh/data cuối; cancel/flush/dedup |
| Playback/window | InternalMediaPlayer; seek/rate/volume/keys/playlist; mini/fullscreen/reparent/focus | Source review; actual audio/video/window modes |
| AI | Spawn, model/device/provider settings, Whisper options, fallback order, hủy/reload/cleanup | Source review; actual CPU/GPU/models/EXE và stub lỗi |
| Refine | CJK join, thresholds, duplicate/badword rules, offsets/padding/SAFE_GAP | Source review; golden raw/refined/reference outputs |
| Local translation | NLLB portable/workaround, generation/batches/pivot/direct/VI/cache keys | Source/probes; actual model/reference; migration riêng nếu đổi context |
| Online translation | Provider/prompt/Genius, ID mapping và fallback | Probe zero-coverage/adapter bằng stub; còn API thật/partial response |
| Subtitle/editor | JSON/index/ASS, orig/JP/EN/VI, giây↔ms, mode/style/fade/lock, undo/import/export/highlight | Source/SRT probe; round-trip và UI thật |
| Settings | Keys/paths/QSettings, JSON, last-folder và appearance/download options | Source review; temp-file fixtures, lỗi ghi/merge/restore |
| Download/update | Format/quality/resolution/playlist/rename, log/progress/cancel, portable installer/update | Source review; subprocess/network stub và EXE thật |
| Native Windows | DLL ABI, callback lifetime, buffer copy/queued events, SMTC/device change | Source review; DLL thật trước thay implementation |

Không có status full parity pass từ audit. `restored-app-baseline.json` ghi source hashes/calls/imports; `restored-contract-probes.json` ghi probe cô lập. Không xóa module legacy/demo khi chưa biết caller.

Quy trình: fixture hành vi cũ → patch nhỏ → so sánh data/API/signals/lifecycle → measurement → actual-media/EXE checks phù hợp. Patch giữ đầu ra khác patch sửa accuracy; ghi riêng lý do và kết quả.
