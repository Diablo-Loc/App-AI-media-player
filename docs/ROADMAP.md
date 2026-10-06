# Roadmap sau khi khôi phục app gốc

Online translation single-pass 06/10/2026: **đã ưu tiên lại tính ổn định và chi phí API**. Normal one-batch success chỉ gọi provider đúng một lần và dùng thẳng output đó; semantic near-repeat quality review đã được gỡ khỏi production. Chỉ incomplete-ID, transient 429/502/503/504 hoặc lyric quá lớn mới có thể phát sinh request bổ sung theo các giới hạn đã có. Xem [TRANSLATION_SINGLE_PASS.md](TRANSLATION_SINGLE_PASS.md).

Semantic near-repeat review 06/10/2026: **đã khóa pattern model copy bản dịch refrain cũ cho cue dài hơn và làm mất phần source bổ sung**. Chỉ cue bị nghi mới có một same-provider review; full batch context vẫn được gửi để model tự sửa ASR/dịch nghĩa. Xem [TRANSLATION_SEMANTIC_REVIEW.md](TRANSLATION_SEMANTIC_REVIEW.md).

Online authority 06/10/2026: **đã chuyển quyền sửa ASR/dịch ngữ nghĩa cho provider Online thay vì ép no-reference quá bảo thủ**. Full batch/song context được dùng để sửa wording khả nghi; response thiếu ID được chính provider bổ sung một lượt, không rơi ngay xuống Local. Không đổi source/timing/ID/schema/Genius gate. Xem [ONLINE_TRANSLATION_AUTHORITY.md](ONLINE_TRANSLATION_AUTHORITY.md).

Verified-reference binding 06/10/2026: **đã khóa lỗi translator tự nuốt phần source nghi ASR sai**. Reference Genius đã xác minh giờ nằm trong chính row/ID của cue và chỉ được dùng để sửa phần recognition mà nó thật sự giải quyết; cue không có reference phải giữ/dịch bảo thủ toàn bộ source. Không thêm request, không đổi ASR/timing/schema/Genius gate/provider/model/batching/fallback. Xem [TRANSLATION_REFERENCE_BINDING.md](TRANSLATION_REFERENCE_BINDING.md).

Lyric clause completeness 06/10/2026: **đã sửa nguy cơ mất vế khi model cố rút ngắn lyric**. Prompt ưu tiên giữ đủ mọi clause/quan hệ nghĩa trước độ dài hiển thị; soft budget được phép vượt và few-shot đa vế chứng minh quy tắc đó. Không thêm API call hay đổi timing/schema/ASR/Genius/provider/model/batching/fallback. Xem [LYRIC_CLAUSE_COMPLETENESS.md](LYRIC_CLAUSE_COMPLETENESS.md).

API pacing 06/10/2026: **đã thêm bounded pacing/retry cho lỗi tạm thời**. Genius giữ nguyên cap và chỉ giãn request; translation batch có khoảng nghỉ 0,65s, provider retry đúng một lần cho 429/502/503/504 rồi trả quyền cho fallback. Không loop retry hay đổi chất lượng dịch. Xem [API_REQUEST_PACING.md](API_REQUEST_PACING.md).

Dịch lyric dài 06/10/2026: **đã thêm bounded batching fail-safe** cho bài cực dài. Bài thường giữ 1 request; bài lớn chia 60 cue/12k source chars, ID vẫn global, Genius hint lọc theo batch và có context-only ở biên. Kết quả chỉ commit vào subtitle khi toàn bộ batch thành công nên không có trạng thái nửa bài. Prompt không dài thêm theo số cue. Xem [LYRIC_LONG_TRANSLATION.md](LYRIC_LONG_TRANSLATION.md).

Dịch lyric prompt 06/10/2026: **đã tinh gọn prompt + thêm few-shot/edge cases có kiểm soát**. Ba ví dụ nhỏ dạy tone/format mà không buộc theo một bài; cue lân cận chỉ disambiguate, ad-lib/marker/source đã là EN-VI không bị model tự làm dài hay paraphrase cho khác. Giữ temperature 0.2 để ưu tiên ổn định thay vì tăng độ sáng tạo; Gemini có output cap 8192 để giảm nguy cơ cắt bài dài. Không thêm API call hay đổi ASR/Genius/timing/schema/fallback. Xem [LYRIC_PROMPT_ENGINEERING.md](LYRIC_PROMPT_ENGINEERING.md).

Dịch lyric ổn định 06/10/2026: **đã siết semantic fidelity mà vẫn giữ chất lyric tự nhiên**. Prompt ưu tiên đúng nghĩa trước, cấm suy diễn chủ thể/quan hệ/nguyên nhân/ẩn dụ/cảm xúc/độ chắc chắn không có nguồn; context/title chỉ gỡ mơ hồ và Genius chỉ sửa đúng cue đã xác minh. Gemini/Claude/OpenAI Chat dùng temperature 0.2 để giảm dao động; không thêm request hay đổi ASR/Genius gate/timing/schema/provider/model/fallback. Focused translation/Genius/model gates đạt; live A/B nhiều bài vẫn là bước đánh giá chất lượng cuối. Xem [LYRIC_TRANSLATION_STABILITY.md](LYRIC_TRANSLATION_STABILITY.md).

Genius 06/10/2026: **đã harden fallback khi lyric page bị Cloudflare**. Giữ search/ranking/ngưỡng cũ; scrape rỗng/lỗi chỉ được dùng lượt retrieval còn lại để lấy Genius referent fragments theo song ID, rồi vẫn phải khớp ASR/cue mạnh. Không bypass Cloudflare, không thêm call Gemini/Claude/OpenAI, không đổi timing/schema/ASR/provider/model. Failure log rõ và quay về dịch ASR. Xem [GENIUS_REFERENTS_FALLBACK.md](GENIUS_REFERENTS_FALLBACK.md).

Dịch lyric/model 05/10/2026: **đã nới commercial lyric shaping và thêm model selector**. Prompt ưu tiên câu mượt/idiomatic/có nhịp hơn thay vì ép ngắn, budget chỉ tăng nhẹ và vẫn giữ semantic fidelity. Settings chọn model riêng theo Gemini/OpenAI/Claude; stale model bị chặn theo provider, Local không đổi. OpenAI model mới dùng Responses trong khi gpt-4o-mini giữ đường cũ. Focused tests/source gates đã thêm; runtime/live API còn chờ vì Python 3.11 venv đang thiếu. Xem [ONLINE_TRANSLATION_MODELS.md](ONLINE_TRANSLATION_MODELS.md).

Genius 05/10/2026: **đã tối ưu lại nhánh reference** theo hướng fail-safe. Không còn request Gemini riêng để đoán tên bài; LyricsGenius dùng đúng `hits`, candidate/version được chấm cục bộ, tối đa hai lyric được tải và phải khớp ASR trước khi dùng. Request dịch chỉ nhận các reference theo cue đã xác minh thay vì toàn bộ lyric, nên giảm token và giảm nguy cơ kéo sai bài/version. Provider/model/key/temperature/timeout/parser/fallback và cue/timing không đổi. Unit/source contracts đã thêm; live catalog/network/API còn chờ do Python 3.11 venv bị thiếu. Xem [GENIUS_REFERENCE_OPTIMIZATION.md](GENIUS_REFERENCE_OPTIMIZATION.md).

Dịch lyric online 05/10/2026: **đã thêm commercial lyric shaping** cho API ngoài. Độ dài EN/VI giờ có mục tiêu mềm theo duration, ưu tiên câu tự nhiên vừa đọc nhưng nghĩa luôn thắng giới hạn; không hard-truncate, không request rút gọn lần hai, không đổi cue/timing/fallback/save. Focused regression đã thêm; runtime Python 3.11 hiện thiếu nên live/API A-B vẫn là bước nghiệm thu thực tế. Xem [LYRIC_TRANSLATION_COMPACTION.md](LYRIC_TRANSLATION_COMPACTION.md).

Subtitle editor 05/10/2026: **đã sửa UI inline edit** của bảng đa ngôn ngữ. Double-click dùng editor có màu chữ/nền/selection rõ và vừa hàng hiện có; không đổi timing, seek, save/undo, schema hay subtitle ngoài player. Có focused regression + exact compatibility adapter; Python 3.11 của venv đang thiếu nên runtime Qt test còn chờ. Xem [SUBTITLE_EDITOR_UI_FIX.md](SUBTITLE_EDITOR_UI_FIX.md).

Sweep lyric lúc kết câu 05/10/2026: **đã sửa nguyên nhân cue bị hiện lại trong fade-out**. Với preset ẩn chữ đã quét, `_smart_hide()` trước đây clear mặt nạ ngay khi hết cue trong khi QLabel vẫn fade 220 ms, làm cả câu lóe lại. Giờ chốt mask ở endpoint, giữ nó trong fade rồi dọn khi widget ẩn; cue/timing/fade và các chế độ khác giữ nguyên. Regression được thêm; chưa chạy được vì Python 3.11 trong venv đã bị gỡ. Xem [SUBTITLE_SWEEP_FADE_FIX.md](SUBTITLE_SWEEP_FADE_FIX.md).

Xuất video + lyric 05/10/2026: **đã triển khai đường xuất độc lập + canvas settings**. Mỗi lần export có cấu hình MP4/MKV, tỉ lệ nguồn/16:9/9:16/1:1/4:5/4:3/3:2/21:9, source/720/1080/1440/2160/custom W×H, Fit/Fill/Stretch, nền, FPS và CRF. Dialog editor hai cột có preview thumbnail tức thời rồi thay bằng một frame nguồn rõ hơn lấy qua `QProcess`/FFmpeg trong RAM, preset Source/YouTube/Shorts/Vuông, đổi W×H, chọn câu preview, reset và tóm tắt đầu ra; không seek/reload player và không gọi AI. Preview đã chuyển sang HiDPI-native: ảnh nguồn không bị scale xuống logical QWidget trước, subtitle preview raster ở backing-store DPR thật và rebuild khi đổi DPI màn hình. Đường encode thật cũng đã tăng ổn định/nét chữ: Lanczos khi resize, composite subtitle ở YUV 4:4:4 rồi hạ một lần về `yuv420p`, và sample fade/effect ở tâm frame để giảm bước alpha do lượng tử FPS; MP4 cuối vẫn H.264 4:2:0 tương thích rộng. Nhóm override export-only thêm cỡ chữ 10–96 px, dịch sub ngang/dọc theo % canvas và opacity nền, tất cả opt-in/0 mặc định nên không đổi style live khi không bật. Safe subtitle bật mặc định với lề 0% để giữ vị trí live khi đã nằm trong khung; chỉ wrap/clamp khi thật sự chạm mép và người dùng có thể tăng lề đến 20%. Snapshot đọc thêm font Qt đã resolve, padding thật, anchor và geometry/aspect mode của `QVideoWidget` để map font/box/vị trí theo đúng viewport app; cue/style/effect, worker RGBA + FFmpeg, playback và dữ liệu cũ vẫn read-only. `Brand New Sky.mp4` đã qua graph smoke thật với đường Lanczos + 4:4:4 → 4:2:0; regression Python/native/EXE còn chờ vì venv trỏ tới Python 3.11 đã thiếu trên máy. Xem [VIDEO_SUBTITLE_EXPORT.md](VIDEO_SUBTITLE_EXPORT.md).

Tối ưu tài nguyên 05/10/2026: **P1/P2/P3 đã triển khai và đối chứng**: batch thumbnail 20 path/2 giây + flush cuối, hai decoder visible, Library grid tái sử dụng card quanh viewport. Full queue/search cũ, For You/sub/audio giữ nguyên; 821 data hashes khớp. Đã đo workload before/after và chạy regression/DPI; native FPS/GPU/EXE riêng. Chưa mở P4 cache budget hoặc editor/sub optimization. Xem [RESOURCE_PERFORMANCE_FIX.md](RESOURCE_PERFORMANCE_FIX.md); audit ngay dưới là mốc trước sửa.

Audit hiệu năng 05/10/2026: **đã quét/đo, chưa sửa production**. 122 Python/21.795 dòng/1.018 hàm và source giữ nguyên; workload cô lập xác nhận cache thumbnail ghi toàn DB mỗi ảnh, Library giữ mọi card và decoder Library dùng giới hạn mặc định 20 trên máy đo. Ưu tiên batch cache → bounded decoder → virtualized Library, giữ mọi ID/order/UI/playback/sub/audio. For You 10.000 metadata chỉ realized 11 hàng; không áp sửa grid vào logic search đã chốt. Hash đầu 819/819 khớp; kiểm tra cuối ghi riêng cache/index/file mới phát sinh trong phiên, 49 file phụ đề/output/video đã tồn tại vẫn khớp. Native CPU/GPU/FPS/EXE cần đo riêng. Xem [APP_PERFORMANCE_REVIEW.md](APP_PERFORMANCE_REVIEW.md).

Lyric nhẹ 04/10/2026: hoàn thành triển khai policy credit và CPU options; các kiểm chứng cuối ghi ở [LYRIC_ACCURACY_LIGHTWEIGHT.md](LYRIC_ACCURACY_LIGHTWEIGHT.md). User hoãn nhận dạng lại, phục hồi câu lặp thiếu ở model và alignment/vocal separation. Không tự kéo đuôi ngân hoặc thay phụ đề đã lưu; tính năng khác cần phạm vi riêng.

Audit Whisper 04/10/2026: hoàn tất kiểm tra read-only, chưa mở phase sửa accuracy. Ưu tiên tiếp theo là credit filter có thể xóa lời thật, đối chứng lyrics/timing, rồi mới retry confidence/ngôn ngữ/CPU options. Không tăng model/beam hoặc đổi phụ đề cũ một cách mặc định. Xem [ASR_ACCURACY_REVIEW.md](ASR_ACCURACY_REVIEW.md).

Typography 04/10/2026: đã triển khai 8 bộ mẫu chuyển cảnh mạnh (mưa chữ/domino/bung/xoáy/lật/sóng/máy chữ/nhịp), lực/chia cụm và cache bounded. Giữ cơ chế sub/video/timing trước; entry gốc được reuse, không thêm engine/worker hoặc dependency. Nghiệm thu native/EXE riêng. Xem [SUBTITLE_KINETIC.md](SUBTITLE_KINETIC.md).

Vệt quét 04/10/2026: triển khai ẩn chữ sau emitter và tan dần từ hiện tại, checkbox riêng và 4 bộ mẫu chọn mới bật sẵn. Câu mới/tua/OFF phục hồi hình vẽ theo media time; không đổi cue hoặc video source. Native/EXE vẫn riêng. Xem [SUBTITLE_SWEEP.md](SUBTITLE_SWEEP.md).

Hiệu ứng hạt theo câu 04/10/2026: hoàn thành 9 style/9 bộ mẫu/3 entry mới trên renderer hiện có; giới hạn tài nguyên và giữ OFF/data/timing. 357 pass +11 historical skip, 48 DPI/27 checkout gates và 814 hashes giữ nguyên. Video Qt thật kiểm tra clock/seek/pause/rate; native màn hình/GPU/EXE cần nghiệm thu riêng. Không thêm word alignment hay ASR trong phase này. Xem [SUBTITLE_PARTICLES.md](SUBTITLE_PARTICLES.md).

Hiệu ứng sub 04/10/2026: đã triển khai nhóm OFF mặc định, chuyển động/màu/mờ/ánh sáng kết hợp, preview và scroll có giới hạn màn hình. Bảo toàn renderer OFF/cues/timing/data; native playback/DPI nhiều màn hình/EXE vẫn nghiệm thu riêng. Xem [SUBTITLE_EFFECTS.md](SUBTITLE_EFFECTS.md).

Nghiệm thu tự động: 343 pass +11 skip lịch sử; 44 DPI/26 checkout gates và 814 hashes giữ nguyên. Không còn việc triển khai trong phase này; nghiệm thu app/EXE thật vẫn riêng.

Import 04/10/2026: sửa prefix gây lỗi direct entry và resource-cache lazy; audit 117 Python/215 local references, child import checks không leak repo root. 325 pass +11 skip, 24 checkout gates và 42 data hashes đạt. Helper/test thủ công legacy được ghi rõ; native Qt runner từng bị dừng, rerun đạt, nguyên nhân chưa xác định; GUI/EXE riêng. Không architectural refactor/data migration. Xem [RUNTIME_IMPORT_FIX.md](RUNTIME_IMPORT_FIX.md).

Downloader 04/10/2026: **hoàn thành phase giữ audio nguồn**; legacy MP4 Extreme/High sửa chuyển mã, selector/container/giới hạn rõ ràng; MP3/Low tùy chọn còn giữ. 321 pass +11 skip, 20 DPI, 23 checkout gates và 42 protected hashes không đổi. Live YouTube/JS/accounts/EXE và đồng bộ title engine còn riêng. Xem [DOWNLOAD_QUALITY_FIX.md](DOWNLOAD_QUALITY_FIX.md).

Âm lượng/build 04/10/2026: hoàn thành lưu/khôi phục 50%/mức cuối và Cài đặt đồng bộ. Chốt preset hiện có, không thêm Moondrop. Build script không xóa bản cũ, resource/paths đã kiểm tra; cần cài tool đóng gói rồi build/smoke EXE thật. 11 focused +22 source gates, không chạy full suite theo yêu cầu. Xem [VOLUME_AND_BUILD.md](VOLUME_AND_BUILD.md).

Metadata 04/10/2026: **hoàn thành R1/R2 theo phạm vi**, source information thật và đọc nền/cancel/cache/shutdown. Không thêm DSP, migration hoặc architectural refactor; sau regression có thể chuyển tính năng mới. Hook Qt và batch thumbnail/library grid vẫn là các phase riêng khi được yêu cầu. Xem [MEDIA_INFO_FIX.md](MEDIA_INFO_FIX.md).

Audit sau chốt audio 04/10/2026: 114 Python sources compile; 284 pass +11 skip ở cả DPI thường/200%, 19 checkout gates và 31 saved hashes đạt. Xác nhận popup Codec hiển thị thông số cố định sai và description ffprobe đồng bộ GUI; nên sửa chung phase metadata nền trước tính năng lớn. Hook startup vẫn trong phạm vi loại trừ trước; batch thumbnail/library virtualization là tùy chọn cần profile. Chỉ audit, chưa sửa production/commit thêm. Xem [FINAL_FLOW_REVIEW.md](FINAL_FLOW_REVIEW.md).

Dễ nghe/commit 04/10/2026: **đã thêm hai preset loa/tai nghe riêng**; bass shelf nhẹ, preamp, Meier stereo tùy chọn và post-chain peak/fixed gain hiện có. Năm tone cũ/OFF/preferences giữ nguyên. 284 pass +11 historical skip, 114 DPI tests. Chốt audio theo phạm vi; tính năng tiếp theo cần yêu cầu riêng. EQ theo mẫu thiết bị, chỉnh tay 5 dải, denoise và A/B tự động vẫn là đề xuất. Xem [AUDIO_EASY_LISTENING.md](AUDIO_EASY_LISTENING.md).

Chất âm 04/10/2026: **đã thêm hai style tùy chọn Ấm/Tai nghe**, cut EQ và crossfeed nhẹ bằng FFmpeg có sẵn, không sửa preset/file gốc hoặc thêm engine/dependency. 277 pass +11 historical skip, 107 DPI tests; cần nghe A/B trên thiết bị user để chọn preset phù hợp. EQ 5 dải chỉnh tay/denoise/A-B tự động vẫn chưa làm; không tự bật lọc nhiễu hay tăng chất âm bằng AI toàn thư viện. Xem [AUDIO_LISTENING_STYLES.md](AUDIO_LISTENING_STYLES.md).

Prefetch EQ 04/10/2026: **đã triển khai** một bài kế tiếp sau settle 2 giây, dùng cùng worker/cache, cancel/promotion/AI deferral và budget 30 giây; tùy chọn chỉ hoạt động khi EQ-on. 270 pass +11 historical skip và 100 DPI tests; 8 media probes nguồn không đổi, Next đã chuẩn bị 0,218–0,299 s. Tối ưu không thêm DSP/chất âm mới. Ưu tiên tiếp theo: EQ chỉnh theo tai nghe có headroom và A/B cùng độ lớn; denoise chỉ sau mẫu nhiễu/nghe đối chứng. Xem [AUDIO_NEXT_PREFETCH.md](AUDIO_NEXT_PREFETCH.md).

Chờ EQ 04/10/2026: **đã triển khai trạng thái chuẩn bị trước playback** cho chọn/qua bài khi bật EQ, spinner/status, queued intent và bounded fallback; normalization-only không thêm delay. Phase đó có 259 pass +11 skip, 8 video/cached probes; prefetch được triển khai ở phase kế tiếp nêu trên. EQ 5 dải/denoise/DSP trực tiếp vẫn chưa triển khai. Xem [AUDIO_START_WAIT.md](AUDIO_START_WAIT.md).

Rà soát âm thanh tiếp 04/10/2026: giữ normalizer trực tiếp, chưa có bottleneck cần sửa thêm sau review. EQ 5 dải/giảm chói, denoise chọn theo bài và A/B được ghi thành phương án **chưa triển khai**; EQ cache vẫn reload, DSP trực tiếp cần phase riêng. Không sửa production/cache/data hoặc đổi engine. Xem [AUDIO_ENHANCEMENT_PLAN.md](AUDIO_ENHANCEMENT_PLAN.md).

Cân bằng trực tiếp 04/10/2026: **đã thay đường normalize theo lựa chọn user** bằng native output gain, tách EQ, không đổi engine/dependency/clock. Bài chưa đo phát ngay; JSON-only measurement cache, target −14/−18, user volume/shortcuts và ownership được kiểm chứng. 247 pass +11 skip, 77 DPI tests, 8 video source probes. EQ trực tiếp cần phase routing/latency riêng và được user hoãn; nghiệm thu native listening/DAC/EXE còn riêng. Xem [AUDIO_NORMALIZATION_REALTIME.md](AUDIO_NORMALIZATION_REALTIME.md).

Âm thanh tùy chọn 04/10/2026: **hoàn thành triển khai theo phạm vi** nút gần volume, normalize/EQ nhẹ và reset âm gốc, mặc định tắt. Owned background cache/restore/fallback giữ player và nguồn cũ; không AI audio enhancement/dependency upgrade. 229 pass +11 skip, 59 DPI tests, probe 8 video và 31 saved hashes. Nghiệm thu nghe/native thiết bị/EXE là bước phát hành riêng, không chứng nhận chất lượng FLAC từ lossy. Xem [AUDIO_EFFECTS.md](AUDIO_EFFECTS.md).

Hiển thị phụ đề 04/10/2026: **hoàn thành theo phạm vi** overlay trên editor, context video và fade chớp/For You cue geometry. Giữ dữ liệu/timing/ASR/translation/owners/flags; 203 pass +11 skip, 33 DPI tests và 31 saved-file hashes. Native screen/driver/multi-monitor/EXE còn chờ. Xem [SUBTITLE_PRESENTATION_FIX.md](SUBTITLE_PRESENTATION_FIX.md). Không mở rộng tối ưu/dependency/refactor khác trong phase này.

Reliability 04/10/2026: **A1–A4/A6 đã triển khai theo phạm vi**, hook Qt không sửa theo yêu cầu. Save recovery; dịch đầy đủ/cache/refrains/lazy NLLB; restart AI/thumbnail không GUI wait, async scan và separate cache I/O lock; shutdown owned. 187 pass +11 skip, 35 DPI tests, hash 31 file cũ giữ nguyên. Batch thumbnail writes, lớn hóa editor/grid, context cache keys và native/GPU/network/EXE còn chờ. Xem [RELIABILITY_FIX.md](RELIABILITY_FIX.md).

Audit luồng (04/10/2026): **hoàn thành rà soát, chưa sửa các phát hiện**. 103 source compile/AST, 159 pass +11 historical skip; fault probes xác nhận save/editor, bản dịch rỗng/thiếu, GUI wait restart AI và hook Qt chưa import. Đối chiếu các nhánh chính với bản gốc; dữ liệu cũ giữ nguyên. Ưu tiên save → translation → worker/scan/lifecycle; startup hook patch riêng. Batch cache/lazy model chưa triển khai. Xem [CURRENT_FLOW_AUDIT.md](CURRENT_FLOW_AUDIT.md).

Spacing/caption For You (04/10/2026): **hoàn thành theo phạm vi** gutter/search/layout restore và màu native caption, giữ frame controls/lifecycle. 159 pass +11 skip, 7 tests mới đạt DPI 200%; native Windows 11 Set/style/state và caption image đạt. Framework migration hoặc custom frameless caption chưa triển khai; snap/drag/multi-monitor/EXE còn chờ. Xem [FORYOU_SPACING_AND_CAPTION.md](FORYOU_SPACING_AND_CAPTION.md).

Chia lyric (04/10/2026): **hoàn thành các lỗi grouping đã tái hiện** ghép câu ngắn/cắt vụn/sustained note/newline cho generation mới. 152 pass +11 skip; replay 24 raw ASR/8 video giữ chữ/thứ tự/save time và hash 27 file cũ. Câu thiếu punctuation/pause, human reference, online dịch và native/EXE vẫn chờ; không đánh dấu mọi câu mọi bài đã đúng. Xem [LYRIC_PHRASE_GROUPING.md](LYRIC_PHRASE_GROUPING.md).

Loading For You: **hoàn thành theo phạm vi** search/clear, xử lý hợp tác, commit đầy đủ, chờ ảnh visible với error/deadline fallback, giữ full queue/order. 138 pass +11 skip ở default/200%; metadata tới 10.000 và ba probe video decoder đạt. Native/EXE và tải AI đồng thời vẫn chờ. Xem [FORYOU_SEARCH_LOADING.md](FORYOU_SEARCH_LOADING.md).

For You search/cuộn (04/10/2026): **hoàn thành theo phạm vi playlist**. Full playback queue/search-only view; tái sử dụng các dòng quanh viewport; tối đa hai decoder visible; clear không dựng toàn bộ hoặc trộn shuffle lần nữa. 133 pass +11 skip ở default/200%; metadata 1.000/10.000 và ba cặp video Qt đã đo. Scan/grid ở trang khác, native presentation/EXE và tải AI đồng thời vẫn chờ. Xem [FORYOU_SEARCH_PERFORMANCE.md](FORYOU_SEARCH_PERFORMANCE.md).

Kết quả không lời/rỗng: **đã xử lý theo phạm vi**, lưu empty có schema cũ và ASS header, cache không chạy lại AI, Qt/editor clear và save failure không báo ready. 123 pass +11 skip, spawn/queue empty thật và hai audio tổng hợp GPU đạt. Timing/fade giữ mốc rollback; instrumental thật/hallucination classification/native/EXE chưa hoàn thành. Xem [EMPTY_SUBTITLE_RESULTS.md](EMPTY_SUBTITLE_RESULTS.md).

Đo accuracy/performance hiện hành: 8 video local ×3 matched ASR/coverage, coverage thêm median 3,83–14,39 s; model reuse, hash phụ đề cũ và cue preservation đạt. 107 pass +11 skip lịch sử. Đây là đo chi phí, chưa phải tối ưu tốc độ; chống meaningful hallucination loops, human ground truth và benchmark playback đồng thời còn chờ. Xem [ASR_RESOURCE_AND_REPEAT_CHECK.md](ASR_RESOURCE_AND_REPEAT_CHECK.md). Không cắt retry/đổi threshold chỉ để giảm thời gian mà thiếu kiểm tra mất lời.

Ưu tiên mới—timing/chia câu/lời lặp: **đã sửa đường tạo phụ đề mới theo phạm vi**, 103 pass + 11 skip lịch sử; replay ba raw ASR và production ASR→save ba video đạt, không tự đổi phụ đề đã lưu. Lượt mới dùng profile word boundaries nên số cue/timing cố ý khác baseline. Human onset/lyrics reference, CER/WER, forced alignment và native/EXE/update còn chờ. Xem [SUBTITLE_QUALITY_FIX.md](SUBTITLE_QUALITY_FIX.md).

Ưu tiên mới—coverage Whisper: **đã sửa trường hợp mất đầu bài tái hiện trên video thật**, thêm targeted retries đầu/giữa/cuối và diagnostics, 74 pass + 11 skip lịch sử. Giữ nguyên 111 cue cũ trên ba video. Reference lyrics/CER/WER, trường hợp giọng nhỏ/nhạc lớn và full native/EXE còn chờ; không đánh dấu mọi video full/correct. Xem [ASR_COVERAGE_FIX.md](ASR_COVERAGE_FIX.md).

Chất lượng thumbnail playlist: **hoàn thành phần decode/hiển thị theo phạm vi**, 55 pass + 11 skip lịch sử và kiểm tra scale 125%/150%/200%. Có đo sai số ảnh trên một JPEG tổng hợp; chưa đo hiệu năng toàn app hoặc xác nhận native/EXE. Xem [PLAYLIST_THUMBNAIL_QUALITY.md](PLAYLIST_THUMBNAIL_QUALITY.md).

Đợt cân chỉnh ba ảnh phản hồi: **hoàn thành theo phạm vi trình bày** playlist/popup/menu, 47 pass + 11 skip lịch sử và sáu regression mới ở DPI 200%. Chưa tính là hoàn thành tối ưu nền tảng hoặc full native/EXE parity. Xem [UI_LAYOUT_POLISH.md](UI_LAYOUT_POLISH.md).

Đợt video nhỏ/trạng thái nút: **đã sửa theo phạm vi UI**, 41 pass + 11 skip lịch sử; DPI 200% và decode/frame/geometry một video có sẵn được kiểm tra. Native presentation/EXE và tối ưu nền tảng vẫn chờ. Không đánh dấu các bước lazy model/cache/editor/accuracy là đã làm. Xem [UI_MEDIA_SURFACE.md](UI_MEDIA_SURFACE.md).

Giai đoạn ổn định UI sau phản hồi: **đã sửa và kiểm chứng tự động** sidebar mất icon, playback bị overlay nhận click, auto-hide khi popup mở, responsive và animation chạy chồng. 32 pass + 11 skip lịch sử; thêm 10/10 regression ở DPI 200%. Các kiểm tra media/native/EXE vẫn chờ, tối ưu AI/library/editor bên dưới chưa triển khai. Xem [UI_STABILITY.md](UI_STABILITY.md).

03/10/2026: người dùng đã khôi phục toàn bộ `app/`, sau đó cho phép nâng cấp UI. Các giai đoạn refactor nền tảng trước không còn được triển khai. Model, môi trường và hành vi gốc tiếp tục làm chuẩn.

Giai đoạn UI mới: **đã triển khai phần trình bày trên Qt Widgets**, bộ icon SVG offline, palette/typography/spacing, các trang và popup. Kiểm tra tự động UI + source đạt theo phạm vi; test thực tế media/GPU/network/native/EXE và lifecycle công cụ phụ đề còn chờ. Xem [UI_REFRESH.md](UI_REFRESH.md). Không đánh dấu các tối ưu nền tảng bên dưới là hoàn thành.

Baseline: 87 file Python / 16.517 dòng, Git `4148c13`. Xem [đánh giá từng phần](RESTORED_APP_REVIEW.md), [kế hoạch đo](ACCURACY_BASELINE_PLAN.md) và `restored-app-baseline.json`.

| Bước | Công việc | Cổng kiểm chứng | Trạng thái |
| --- | --- | --- | --- |
| 0 | Snapshot, audit từng thư mục, probe hợp đồng | AST/compile/hash/diff; app/EXE thực tế làm chuẩn | Audit/probe xong; hiệu năng và chất lượng thực tế chưa đo |
| 1 | Lazy NLLB sau cache miss | Cùng text/layers/timing/cache; all-hit không load model | Đã triển khai ở reliability phase; audit hiện tại xác nhận nhánh to_translate |
| 2 | Batch ghi cache thumbnail | Cùng ảnh/path/JSON cuối; write count; flush complete/cancel/error/shutdown | Đã triển khai 05/10/2026; workload 50 → 3 saves, JSON cuối exact |
| 3 | Cache thời gian editor | Cùng precision/row active; seek/overlap/unsorted/edit/undo | Chưa sửa |
| 4 | Profile scan/grid rồi đổi orchestration nếu cần | Cùng metadata/ID/order; GUI heartbeat; save concurrency/lifecycle | Scan nền ở reliability; Library virtualized/two decoders 05/10, source/legacy queue/10k bounds đạt; native FPS riêng |
| 5 | Accuracy/completeness riêng | Reference, coverage/fallback, timestamp boundaries; migration nếu đổi cache context | Đã sửa coverage và timing/chia câu/lặp ở đường tạo mới; human reference/CER/WER, dịch và native/EXE còn chờ |
| 6 | Tách MainWindow/dialog/AI theo trách nhiệm | API/signals/ownership/modes/EXE tương đương | Chưa sửa |
| 7 | Kiểm chứng bản xuất | Full checklist media/model/provider/download/native trên runtime hiện hành | Chưa chạy trong audit |

Giữ ASR parameters, prompts, heuristics, model format/workaround, fallback và schema/key/path. Thay đổi các hợp đồng đó cần quality gate riêng, không làm kèm refactor. Tách file không tự chứng minh app nhanh hoặc chính xác hơn.

UI mới đã triển khai riêng theo yêu cầu mới; phần parity thực tế còn chờ ở `UI_REFRESH.md`. Upgrade dependency vẫn hoãn. Kết quả 52 test/benchmark trước thuộc bản đã rollback, không áp cho roadmap hiện tại.
# Audit downloader (04/10/2026)

Đã rà soát chất lượng audio và kiểm tra offline 12 command +12 tổ hợp selector;
**chưa sửa luồng tải**. MP4 Standard giữ nguồn AAC; Extreme/High MP4 chuyển mã,
fallback có thể vượt độ phân giải hoặc thiếu định dạng và command lặp URL.
Phase tiếp theo cần giữ nguồn, tách lựa chọn chuyển mã, sửa selector/container
và ownership file tạm. Xem [DOWNLOAD_QUALITY_REVIEW.md](DOWNLOAD_QUALITY_REVIEW.md).

Luồng quét subtitle 05/10/2026: **đã sửa cách chia vệt theo câu/ngôn ngữ**. Mỗi ngôn ngữ có một luồng đi tuần tự qua các hàng wrap; hai ngôn ngữ/4 hàng tạo hai vệt đồng thời. Hạt và erase_passed dùng cùng kế hoạch. Probe Qt/export và source gates liên quan đạt; full suite Python 3.11 còn chờ vì interpreter của venv không tồn tại. Xem [SUBTITLE_SWEEP_FLOW_FIX.md](SUBTITLE_SWEEP_FLOW_FIX.md).

Sweep-track hardening 05/10/2026: completed explicit layout metadata for subtitle sweep grouping. Particle emitters, erase masks and video export consume the same dynamic group ids, so future additional displayed languages do not require renderer-specific grouping logic. Current-mode text parity plus 3-language, 6-language and export-rewrap probes passed; historical manifests remain frozen. Full Python 3.11 suite remains pending because the venv interpreter is missing. See [SUBTITLE_SWEEP_TRACKS.md](SUBTITLE_SWEEP_TRACKS.md).
Playback continuity 05/10/2026: completed a narrow hot-path cleanup in the native system-media bridge. Unused PCM copies and GUI dispatch are off by default. Subtitle painter profiling retained the existing bounded sprite/layout cache; bypassing it was much slower, so no speculative renderer change was kept. Export source ownership was checked: subtitle appearance is burn-in state, playback EQ/normalize does not replace original export audio. Native SMTC/media-key ownership and audio/export policies remain unchanged. Full Python 3.11/native listening/FPS validation remains separate. See [PLAYBACK_CONTINUITY_FIX.md](PLAYBACK_CONTINUITY_FIX.md).
