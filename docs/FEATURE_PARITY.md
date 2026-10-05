# Hợp đồng tính năng của baseline đã khôi phục

Genius 06/10/2026: hardening khi Genius search đúng nhưng trang lyric bị Cloudflare/challenge làm LyricsGenius trả rỗng. Không retry/bypass HTML; nếu còn budget thì dùng một request `referents` theo song ID, chỉ lấy fragment lyric có cấu trúc và vẫn bắt buộc qua nguyên ngưỡng whole-song ASR + cue-local trước khi đưa hint vào request dịch. Tối đa 2 search/2 retrieval và vẫn 1 request dịch; khi không đủ chắc thì log rõ và dịch từ ASR như cũ. Xem [GENIUS_REFERENTS_FALLBACK.md](GENIUS_REFERENTS_FALLBACK.md).

Dịch lyric/model 05/10/2026: nới nhẹ wording/budget để EN/VI tự nhiên, có nhịp và cảm xúc hơn nhưng vẫn giữ nghĩa; không hard-truncate hay thêm request. Settings có model dịch theo provider, giữ Gemini 2.5 Flash và GPT-4o mini làm mặc định tương thích, Claude thiếu preference chuyển sang Sonnet 4.6 vì 3.5 đã retire. GPT-5.6 dùng Responses; gpt-4o-mini vẫn Chat Completions. Genius verified-reference, timing/schema/fallback/NLLB giữ nguyên. Xem [ONLINE_TRANSLATION_MODELS.md](ONLINE_TRANSLATION_MODELS.md).

Genius 05/10/2026: chuyển nhánh tùy chọn thành reference assist có kiểm chứng. Sửa đúng response `hits`, bỏ lượt Gemini làm sạch tên bài, xếp hạng title/artist/version cục bộ, lấy lyric trực tiếp từ URL, chỉ chấp nhận bài khớp ASR và chỉ gửi hint của cue khớp mạnh vào request dịch hiện có. Không đổi cue/timing/ASR/schema/provider/model/key/temperature/timeout/parser/fallback; khi Genius không chắc thì dịch như không có reference. Focused contracts đã thêm; live Genius/API còn chờ vì venv Python 3.11 đang thiếu. Xem [GENIUS_REFERENCE_OPTIMIZATION.md](GENIUS_REFERENCE_OPTIMIZATION.md).

Dịch lyric online 05/10/2026: thêm shaping theo thời lượng cue cho Gemini/Claude/OpenAI để bản EN/VI gọn như lyric subtitle nhưng không cắt cứng hay đổi nghĩa. Mỗi cue có khoảng ký tự mềm; prompt bắt buộc giữ phủ định, sắc thái, hình ảnh, quan hệ, tên/số và repetition có chủ ý, cho phép vượt budget khi cần giữ nghĩa. Vẫn một request, output `ID===EN===VI`, parser/fallback/timing/schema/save cũ giữ nguyên. Xem [LYRIC_TRANSLATION_COMPACTION.md](LYRIC_TRANSLATION_COMPACTION.md).

Subtitle editor 05/10/2026: sửa ô nhập khi double-click trong bảng phụ đề đa ngôn ngữ để chữ hiện rõ trên dark theme, giữ nguyên model/save/undo/timing/seek và dữ liệu. Editor mới chỉ là delegate trình bày, dùng lại `Qt.EditRole`/`setData` cũ; snapshot/adapter riêng bảo toàn gate video-export trước đó. Python 3.11 của venv hiện hỏng nên Qt regression mới chưa chạy trong pass này. Xem [SUBTITLE_EDITOR_UI_FIX.md](SUBTITLE_EDITOR_UI_FIX.md).

Tối ưu tài nguyên 05/10/2026: đã triển khai batch thumbnail, queue hai decoder visible và Library card theo viewport. Giữ full queue/thứ tự search Library cũ, Home/For You, sub/audio/player/data; 821/821 data hashes giữ nguyên. Exact source snapshots phase mới nối lại gate cũ, không recapture lịch sử. Workload 1.000 metadata: 1.000 → 25 card, RSS grid khoảng 121 → 5,2 MiB; cache 50 → 3 saves và JSON cuối exact. Kiểm chứng/giới hạn native/EXE ở [RESOURCE_PERFORMANCE_FIX.md](RESOURCE_PERFORMANCE_FIX.md). Đoạn audit bên dưới là trạng thái trước triển khai.

Audit tài nguyên 05/10/2026: không đổi production/logic/UI/sub/audio. AST/compile toàn 122 Python đạt; workload Qt/cached JSON cô lập xác nhận cơ hội batch-cache/virtualized Library/bounded decoder. Source và 49 file phụ đề/output/video đã tồn tại giữ nguyên; các thay đổi cache/index/file mới giữa lần hash đầu và cuối được ghi riêng, không rollback. Chưa triển khai tối ưu và chưa đo native CPU/GPU/EXE; không nâng phạm vi parity từ các probe tổng hợp. Xem [APP_PERFORMANCE_REVIEW.md](APP_PERFORMANCE_REVIEW.md).

Lyric nhẹ 04/10/2026: sửa credit substring có thể xóa lời thật và đồng nhất decode CPU với primary, không thêm lượt Whisper theo yêu cầu cuối. Dedup/lặp/tail/grouping/coverage/data/UI/owners giữ nguyên. 385 pass +11 historical skip, 90 focused/31 checkout gates; 24 captured replays khớp exact và 817 saved hashes giữ nguyên. Brand New Sky thiếu câu ở ASR vẫn là giới hạn được giữ, không dùng retry thử làm kết quả bản cuối. Xem [LYRIC_ACCURACY_LIGHTWEIGHT.md](LYRIC_ACCURACY_LIGHTWEIGHT.md).

Audit Whisper 04/10/2026: production/ASR/model/cue/data không đổi. 24 captured-ASR replays khớp kết quả phrase đã lưu, 82 focused checks và full 377 pass +11 historical skip đạt, 39 saved subtitle hashes giữ nguyên trong probe. Phát hiện nguy cơ mất lời do credit substring và giới hạn gap/confidence/CPU options; chưa xác nhận gần lyrics ground truth. Xem [ASR_ACCURACY_REVIEW.md](ASR_ACCURACY_REVIEW.md).

Typography 04/10/2026: thêm 8 entry/bộ mẫu có chuyển động từng vùng chữ và tùy chọn lực/chia cụm. Reuse entry animation/glyph cache, <=16 tile hoặc 6 ở phối hợp nặng; old-effect pixel và cue/clock/data/owners giữ nguyên. Không word alignment/3D hoặc mở rộng cửa sổ. Kiểm chứng và giới hạn frame lạnh/native/EXE: [SUBTITLE_KINETIC.md](SUBTITLE_KINETIC.md).

Vệt quét 04/10/2026: tùy chọn ẩn chữ đã quét tới hết câu cho Phi tiêu/Sao/Sao băng/Tinh thể; timing/text/data/load/save/owners và renderer cũ khi bỏ chọn giữ nguyên. Chỉ ba helper presentation, cached mask và timer cũ. Regression pixel/seek/câu lặp/DPI/glow và snapshot riêng; không migrate preference cũ. Xem [SUBTITLE_SWEEP.md](SUBTITLE_SWEEP.md).

Hiệu ứng theo câu 04/10/2026: thêm 9 phong cách hạt/phi tiêu, 9 bộ mẫu, 3 entry mới; OFF, cue/timing/data và chủ sở hữu cũ giữ nguyên. Quét trang trí theo thời lượng câu, không giả word timing. Giới hạn hạt/layout, pause/seek/editor, Unicode/bidi và câu ngắn được kiểm tra. 357 pass +11 skip lịch sử, 48 DPI, 27 checkout gates; 814 hashes dữ liệu không đổi. Native/EXE vẫn riêng. Xem [SUBTITLE_PARTICLES.md](SUBTITLE_PARTICLES.md).

Hiệu ứng sub 04/10/2026: nhóm tùy chọn OFF mặc định, chuyển động/màu/mờ/ánh sáng và preview; giữ renderer gốc khi tắt, cue/timing/data/ASR/dịch và guard video/editor. Có regression pixel/geometry/seek/câu lặp/pause/settings, source snapshots riêng và hash dữ liệu. Native/EXE riêng. Xem [SUBTITLE_EFFECTS.md](SUBTITLE_EFFECTS.md).

Kết quả phase hiệu ứng: **343 pass +11 historical skip**, 44 DPI tests, 26 checkout gates, 814 file dữ liệu giữ hash. Không quy kết thành full native/GPU/EXE parity.

Import 04/10/2026: sửa namespace downloader/resource-cache theo entry gốc, không đổi xử lý/data. Giữ user edits, không áp refactor app.* hoặc sửa helper/test legacy không được gọi. Startup import kiểm chứng bằng process mới không có repo root; 325 pass +11 skip, 24 checkout gates và 42 data hashes đạt. Simulated frozen chưa phải EXE thật; một native runner crash trước rerun chưa xác định nguyên nhân. Xem [RUNTIME_IMPORT_FIX.md](RUNTIME_IMPORT_FIX.md).

Downloader 04/10/2026: giữ audio nguồn là cải thiện chủ ý cho file tải mới, không thay file cũ. Legacy keys/options, MP3/Low còn giữ; bounded selector/remux/UTF-8 settings. Production ngoài ba module không đổi; 42 data hashes đạt. 321 pass +11 skip, 20 DPI, 23 checkout gates; không suy ra live network/EXE parity. Xem [DOWNLOAD_QUALITY_FIX.md](DOWNLOAD_QUALITY_FIX.md).

Âm lượng/build 04/10/2026: nhớ mức người dùng, mặc định lần đầu 50%, ô phần trăm trong Cài đặt và reset; gain/DSP/nguồn/owners cũ giữ nguyên. 11 focused checks và 22 source gates đạt; không full suite theo yêu cầu. Build script đã sửa/dry-run kiểm tra, venv thiếu PyInstaller nên EXE thật chưa nghiệm thu. Xem [VOLUME_AND_BUILD.md](VOLUME_AND_BUILD.md).

Metadata 04/10/2026: **R1/R2 đã sửa**: thông số file gốc thật, đọc sidecar/ffprobe nền, một latest owned worker, RAM-only cache và shutdown. Giữ player/audio/video/lyric/ASR/save-data; không sửa hook Qt hoặc batch cache. Kiểm chứng và giới hạn nghiệm thu ở [MEDIA_INFO_FIX.md](MEDIA_INFO_FIX.md); audit phía dưới là trạng thái trước sửa.

Audit sau commit audio 04/10/2026: regression hiện hành đạt 284 pass +11 historical skip ở DPI thường/200%, 19 checkout gates, 31/31 saved hashes; entry import với portable libs đạt. Vẫn có metadata Codec hardcode và description GUI blocking đã tái hiện; hook pre-Qt còn NameError trong nhánh lỗi và được giữ ngoài scope cũ. Không gọi kết quả này là zero-bug/full native/GPU/network/EXE parity. Chưa đổi production hoặc saved data. Xem [FINAL_FLOW_REVIEW.md](FINAL_FLOW_REVIEW.md).

Dễ nghe 04/10/2026: thêm riêng hai tone loa/tai nghe, preamp −1,5 dB, EQ nhẹ và Meier stereo tùy chọn. Năm tone/filter/gain/cache key/version cũ giữ nguyên, không tự đổi normalize/target hoặc saved data. 284 pass +11 historical skip, 114 DPI tests; commit chốt chuỗi audio hiện hành theo yêu cầu. Không thêm limiter/compressor hay cam kết phục hồi 128k. Xem [AUDIO_EASY_LISTENING.md](AUDIO_EASY_LISTENING.md).

Chất âm 04/10/2026: thêm **Ấm** (EQ cut nhỏ) và **Tai nghe** (Ấm + crossfeed nhẹ cho stereo), OFF/preset/filter/gain/cache key cũ giữ nguyên. Không đổi player/controller/prefetch/ASR/dữ liệu cũ; không nén động hoặc giả vang/AI/denoise. 277 pass +11 skip, 107 DPI tests, 31/31 saved hashes; decoder thật giữ seek/pause/rate/volume/owners và quay về gốc. Cảm nhận nghe lâu/chất lượng vẫn cần nghe A/B thiết bị thật. Xem [AUDIO_LISTENING_STYLES.md](AUDIO_LISTENING_STYLES.md).

Prefetch EQ 04/10/2026: **chuẩn bị một bài kế tiếp** trên worker/cache cũ, chỉ EQ-on, có tùy chọn tắt; không áp kết quả lên bài hiện hành hoặc đổi thuật toán full queue/search/shuffle. Matching worker được promote, tác vụ khác hủy không GUI wait, AI/pause/seek/budget được kiểm tra. Sửa popup đo height-for-width để hướng dẫn hiện đủ. 270 pass +11 historical skip, 100 DPI tests; 8 video Next sau chuẩn bị 0,218–0,299 s, nguồn giữ hash. EQ/denoise mới vẫn đề xuất. Xem [AUDIO_NEXT_PREFETCH.md](AUDIO_NEXT_PREFETCH.md).

Chờ EQ khi chọn bài 04/10/2026: user cho phép khoảng nghỉ trước playback. Chỉ EQ-on chờ chuẩn bị, original/native normalization giữ phát ngay; pending pause/seek/rate/mini/hardware intent, lỗi/timeout fallback và latest requests có regression Qt thật. Nạp gốc metadata rồi derived nhưng original không playback trước. 259 pass +11 skip, 8 video cold/cache probes, 31/31 hash theo đầu phase; native/DAC/EXE còn riêng. Xem [AUDIO_START_WAIT.md](AUDIO_START_WAIT.md).

Rà soát chốt âm thanh 04/10/2026: giữ nguyên production hiện hành; EQ 5 dải/giảm nhiễu/A-B và DSP trực tiếp vẫn là phương án, không phải tính năng đã thêm. Review/test lại không thay saved data hoặc gate cũ. Xem [AUDIO_ENHANCEMENT_PLAN.md](AUDIO_ENHANCEMENT_PLAN.md).

Cân bằng trực tiếp 04/10/2026: user chọn phát liền mạch và giữ EQ riêng. Normalize + EQ Nguyên bản giữ source/clock/decoder, không thêm lần reload khi bật/tắt/chuyển bài; user volume tách gain, ramp 150 ms, target −14/−18 và headroom/Qt-volume ceiling. EQ v1 vẫn có giới hạn reload, được ghi rõ. 247 pass +11 skip, 77 DPI tests, 8 media probe và 31 saved hashes giữ nguyên; không suy ra mọi thiết bị/listening/EXE parity. Xem [AUDIO_NORMALIZATION_REALTIME.md](AUDIO_NORMALIZATION_REALTIME.md).

Âm thanh tùy chọn 04/10/2026: nút sát loa, tắt mặc định; normalize gain cố định/EQ nhẹ trên bản phát dẫn xuất, không sửa nguồn. Tắt trở về âm gốc; giữ một player/output/video, vị trí/state/rate/tracks/loops, playlist/ASR/schema/file phụ đề cũ. Có ngắt ngắn khi reload source; không quảng cáo 128k thành FLAC gốc hay uniform gain bất chấp clipping. 229 pass +11 skip, 59 DPI tests, 8 video giữ source/video bytes, 31 data file giữ SHA; native nhiều thiết bị/listening/EXE còn chờ. Xem [AUDIO_EFFECTS.md](AUDIO_EFFECTS.md).

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
# Audit downloader (04/10/2026)

Luồng tải/preset/settings/engine và media cũ chưa đổi. Kiểm tra offline 12
command và 12 fixture selector phát hiện các vấn đề chất lượng/chọn format;
chưa có xác nhận live YouTube hoặc EXE. Xem [DOWNLOAD_QUALITY_REVIEW.md](DOWNLOAD_QUALITY_REVIEW.md).

Luồng quét subtitle 05/10/2026: **đã sửa theo câu/ngôn ngữ**. Một track tiếp tục qua các hàng wrap thuộc cùng phrase; hai ngôn ngữ/4 hàng tạo hai vệt đồng thời. Hạt, phi tiêu và ẩn chữ sau quét dùng chung nhóm dòng; video export giữ nhóm khi tự wrap. Runtime Qt/export probe đạt, full suite Python 3.11 đang chờ interpreter.

Sweep-track hardening 05/10/2026: explicit logical row-group metadata is now produced by SubtitleLayer at wrap time. Track count is dynamic rather than fixed to two/three languages; the Qt probe verified 3 languages over 6 wrapped rows -> 3 tracks, a future 6-language mode -> 6 tracks, and export rewrap to 24 rows while preserving 3 groups. Existing SubtitleMode display text matched the exact pre-phase implementation. Full Python 3.11 suite remains pending because the venv interpreter is missing. See [SUBTITLE_SWEEP_TRACKS.md](SUBTITLE_SWEEP_TRACKS.md).
Playback continuity 05/10/2026: removed unused continuous PCM-to-NumPy/GUI copies from the native system-media bridge while retaining the callback ABI, SMTC/media keys, and an explicit opt-in capture path for a future real consumer. Subtitle renderer profiling kept the existing bounded sprite/layout cache because bypassing it was dramatically slower; no subtitle timing/text/effect behavior changed. Export was re-audited: displayed subtitle appearance is intentionally burned into video, while playback EQ/normalization is not baked into exported audio because export reads the original media item and keeps the existing stream-copy/AAC fallback policy. QMediaPlayer/QAudioOutput, saved data and audio policy remain unchanged. See [PLAYBACK_CONTINUITY_FIX.md](PLAYBACK_CONTINUITY_FIX.md).
