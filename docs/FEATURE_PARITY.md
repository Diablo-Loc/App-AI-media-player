# Hợp đồng tính năng của baseline đã khôi phục

Hiển thị phụ đề 04/10/2026: chặn overlay trên editor/dialog và khi video/context không phù hợp; đóng khôi phục cue hiện hành, không hiện chữ cũ trong gap. Sửa fade restart/callback cũ và vị trí cue For You trước paint; giữ timing/fade settings/owners/flags/file cũ. 203 pass +11 skip, 33 tests DPI 200%, hash 31 data files giữ nguyên. Native screen/EXE còn chờ. Xem [SUBTITLE_PRESENTATION_FIX.md](SUBTITLE_PRESENTATION_FIX.md).

Reliability 04/10/2026: **đã sửa theo phạm vi** save/editor, dịch thiếu/cache/refrains, GUI restart/scan và shutdown download/editor. 187 pass +11 historical skip, 35 tests DPI 200%; hash 31 saved files và ASR/timing/worker/hook giữ nguyên. Failure/async cố ý nâng cấp, không migration dữ liệu cũ hoặc đổi schema/cache keys. Gates cũ normalize qua exact-reviewed snapshot; không suy ra toàn app hết lỗi/native/EXE parity. Xem [RELIABILITY_FIX.md](RELIABILITY_FIX.md).

Audit 04/10/2026: 159 pass +11 historical skip; **không production change trong audit**. 12 function AST liên quan nhánh lỗi khớp Git baseline; manager gốc cũng tái hiện JSON mới/ASS cũ. Save/editor/translation/restart/startup cần phase riêng, không kết luận parity/tối ưu toàn app từ tests đang có. 31 file saved data giữ hash qua fault probes. Xem [CURRENT_FLOW_AUDIT.md](CURRENT_FLOW_AUDIT.md).

Spacing/caption (04/10/2026): For You dùng gutter 12 px, search cân trên/dưới; wrapper/gap được restore cho trang khác. Tô màu native caption, giữ window flags/style và MainWindow hash, không đổi video/subtitle/playlist/ASR. 159 pass +11 skip; 7 regression mới đạt thêm DPI 200%, native Windows 11 Set/style/state transitions và ảnh caption đạt. Snap/drag/multi-monitor/EXE còn chờ. Xem [FORYOU_SPACING_AND_CAPTION.md](FORYOU_SPACING_AND_CAPTION.md).

Chia lyric (04/10/2026): sửa ghép câu ngắn/cắt vụn, sustained note và newline cho lượt tạo mới; giữ timing margins/finalizer/fade, bộ lọc, ASR/dịch/schema và phụ đề cũ. Full suite 152 pass +11 skip; 14 regression mới đạt thêm DPI 200%. Replay 24 bộ raw của 8 video giữ chữ/thứ tự, không overlap và save đúng time; 27 file phụ đề cũ giữ hash. Chưa có human semantic/timing reference hoặc native/EXE. Xem [LYRIC_PHRASE_GROUPING.md](LYRIC_PHRASE_GROUPING.md).

Loading For You (04/10/2026): search/clear hiện spinner trong viewport, chuẩn bị theo chunk và chỉ reveal kết quả hoàn chỉnh với ảnh visible sẵn sàng hoặc fallback. Gõ nhanh hủy query cũ; full queue/master/order/2 decoder giữ nguyên. 138 pass +11 historical skip ở default/200%, native screen/EXE chưa xác nhận. Xem [FORYOU_SEARCH_LOADING.md](FORYOU_SEARCH_LOADING.md).

For You search/performance (04/10/2026): search chỉ lọc view, full playback queue được người dùng chọn rõ; clear/query khác không mất master hoặc đổi thứ tự shuffle. Viewport pool và tối đa hai decoder ảnh visible đã kiểm tra bằng Qt thật; 133 pass +11 historical skip ở default/200%, cùng các adapter AST cụ thể. Số đo metadata 1.000/10.000 và video Qt được ghi riêng; không đánh dấu full native/EXE parity. Xem [FORYOU_SEARCH_PERFORMANCE.md](FORYOU_SEARCH_PERFORMANCE.md).

Đợt kết quả rỗng: pipeline hoàn tất với `segments: []`, JSON/ASS header-only được lưu/cache; overlay/editor clear đúng, force reload còn giữ. 123 pass +11 skip lịch sử; hai audio không lời tổng hợp chạy GPU thực và 25 subtitle file cũ giữ hash. Không đổi timing/fade sau rollback hoặc gọi đây là detector mọi instrumental. Xem [EMPTY_SUBTITLE_RESULTS.md](EMPTY_SUBTITLE_RESULTS.md).

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
