# Roadmap sau khi khôi phục app gốc

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
| 1 | Lazy NLLB sau cache miss | Cùng text/layers/timing/cache; all-hit không load model | Chưa sửa |
| 2 | Batch ghi cache thumbnail | Cùng ảnh/path/JSON cuối; write count; flush complete/cancel/error/shutdown | Chưa sửa |
| 3 | Cache thời gian editor | Cùng precision/row active; seek/overlap/unsorted/edit/undo | Chưa sửa |
| 4 | Profile scan/grid rồi đổi orchestration nếu cần | Cùng metadata/ID/order; GUI heartbeat; save concurrency/lifecycle | Chưa sửa |
| 5 | Accuracy/completeness riêng | Reference, coverage/fallback, timestamp boundaries; migration nếu đổi cache context | Đã sửa coverage và timing/chia câu/lặp ở đường tạo mới; human reference/CER/WER, dịch và native/EXE còn chờ |
| 6 | Tách MainWindow/dialog/AI theo trách nhiệm | API/signals/ownership/modes/EXE tương đương | Chưa sửa |
| 7 | Kiểm chứng bản xuất | Full checklist media/model/provider/download/native trên runtime hiện hành | Chưa chạy trong audit |

Giữ ASR parameters, prompts, heuristics, model format/workaround, fallback và schema/key/path. Thay đổi các hợp đồng đó cần quality gate riêng, không làm kèm refactor. Tách file không tự chứng minh app nhanh hoặc chính xác hơn.

UI mới đã triển khai riêng theo yêu cầu mới; phần parity thực tế còn chờ ở `UI_REFRESH.md`. Upgrade dependency vẫn hoãn. Kết quả 52 test/benchmark trước thuộc bản đã rollback, không áp cho roadmap hiện tại.
