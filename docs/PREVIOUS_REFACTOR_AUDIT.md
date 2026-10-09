# Kiểm tra đợt refactor trước

Căn onset 09/10/2026: dùng model local đã nạp, giữ chữ/chia câu/recovery/API; chỉ dời các mốc sớm có alignment đủ tin cậy, đọc WAV theo cửa sổ và giữ mốc cũ khi lỗi/hết budget. SRT chỉ là benchmark: 38 nhóm câu giảm MAE đầu 441→239 ms, cuối 600→490 ms. Ba bài giữ đủ 42/31/49 câu; đoạn 5–9 s cũ không đổi. Chưa bảo đảm timestamp đúng mọi bài.

Timing hiển thị 08/10/2026: chỉ thêm final display pass trong helper refinement và một điểm nối sau coverage ở pipeline. Không refactor UI/player/effect hay thay ASR/translation/save schema. Fixture patch mới kiểm tra toàn source trước khi peel; mọi manifest/snapshot lịch sử giữ nguyên. Regression sau sửa có cùng danh sách lỗi đã có ở baseline.

Tối ưu tài nguyên 05/10/2026: không áp architectural refactor. Chỉ bốn module tài nguyên/UI và ba helper mới; gỡ đúng năm grid adapters/import phục hồi toàn AST MainWindow trước phase. Giữ worktree edits, sub/audio/ASR/dữ liệu và frozen manifests. Snapshot/adapter mới phục hồi gate lịch sử; phạm vi và đo trước/sau ghi ở [RESOURCE_PERFORMANCE_FIX.md](RESOURCE_PERFORMANCE_FIX.md).

Audit tài nguyên 05/10/2026: chỉ thêm báo cáo/probe/snapshot mới, không áp refactor hoặc sửa code app. Quét cả tám ví dụ Python ignored; không thực thi chúng. Cache/grid được đo bằng production methods trong môi trường cô lập; toàn source và 49 file phụ đề/output/video đã tồn tại giữ nguyên. Hash 819/819 đầu probe đạt; kiểm tra cuối có cache/index/file mới cập nhật trong phiên và ghi riêng, không khẳng định cả storage bất biến. Những manifest cũ và worktree edits có sẵn không được recapture/rollback. Xem [APP_PERFORMANCE_REVIEW.md](APP_PERFORMANCE_REVIEW.md).

Lyric nhẹ 04/10/2026: chỉ hai production adapters và một pure policy helper; không refactor player/AI lifecycle/import namespaces. Gỡ toàn bộ retry/consensus thử theo yêu cầu ưu tiên hiệu năng; original/reviewed snapshots phase mới phục hồi gates cũ, không recapture lịch sử. Xem [LYRIC_ACCURACY_LIGHTWEIGHT.md](LYRIC_ACCURACY_LIGHTWEIGHT.md).

Audit Whisper 04/10/2026: không refactor hoặc thay tham số nhận dạng; chỉ thêm probe read-only và báo cáo riêng. Snapshot/manifest lịch sử, dữ liệu lưu và worktree edits giữ nguyên. Phân biệt regression với lyrics/timing ground truth ở [ASR_ACCURACY_REVIEW.md](ASR_ACCURACY_REVIEW.md).

Typography 04/10/2026: thêm một kinetic painter và sửa hai effect helpers, không architectural refactor. Baseline/manifest phase cũ giữ nguyên, source gates phục hồi exact qua adapter mới; legacy pixel, timer/decoder/window ownership và persisted sub giữ nguyên. Xem [SUBTITLE_KINETIC.md](SUBTITLE_KINETIC.md).

Vệt quét 04/10/2026: người dùng cho phép ẩn phần chữ đã quét, riêng tùy chọn presentation. Không refactor/subtitle migration; ba helper hiện có, preset/settings và masks được chụp trong phase mới, các manifest trước giữ nguyên. Pixel effect cũ khi bỏ chọn đối chiếu snapshot, cue/clock/owners unchanged. Xem [SUBTITLE_SWEEP.md](SUBTITLE_SWEEP.md).

Hiệu ứng hạt 04/10/2026: chỉ mở rộng hai helper presentation và thêm particle painter, không refactor pipeline/owners hoặc đổi dữ liệu cũ. Giữ renderer OFF; exact adapters phục hồi source trước phase để chạy toàn bộ gates cũ, không recapture manifest lịch sử. 357 pass +11 skip, 48 DPI, 27 checkout gates; giới hạn native/EXE và frame lạnh ghi tại [SUBTITLE_PARTICLES.md](SUBTITLE_PARTICLES.md).

Hiệu ứng sub 04/10/2026: thêm presentation tùy chọn, không áp refactor hoặc đổi pipeline. Chỉ ba UI adapters và hai helpers, toàn source SubtitleLayer khớp trước khi bỏ hook mới; OFF pixel comparison và source gates giữ hợp đồng cũ. Xem [SUBTITLE_EFFECTS.md](SUBTITLE_EFFECTS.md).

Import 04/10/2026: prefix app.* ở policy là lỗi đưa vào downloader phase, được sửa theo top-level namespace của baseline. Không có thay đổi entry/sys.path hoặc xử lý audio/AI. Quét thêm 5 lazy imports trỏ controller/cache thật; child process -I bắt lỗi mà test root-path cũ che. Xem [RUNTIME_IMPORT_FIX.md](RUNTIME_IMPORT_FIX.md).

Downloader 04/10/2026: pure policy +ba adapter nhỏ, không architectural refactor. Giữ codec nguồn thay vì ép AAC ở Extreme/High video, bounded fallback/remux và giữ partial của tác vụ khác. Snapshot mới restore volume phase; historical manifests, GetTitleWorker/updater/DSP/ASR/playback không đổi. Xem [DOWNLOAD_QUALITY_FIX.md](DOWNLOAD_QUALITY_FIX.md).

Âm lượng/build 04/10/2026: helper lưu user volume + UI/reset adapters được duyệt, không đổi audio DSP/controller/gain hoặc kiến trúc cũ. Exact adapter mới restore metadata phase; historical manifests frozen. Build script giữ hidden imports/data mapping và bỏ xóa output cũ, không nâng/cài runtime. Xem [VOLUME_AND_BUILD.md](VOLUME_AND_BUILD.md).

Metadata 04/10/2026: sửa riêng hai lỗi baseline R1/R2 được user duyệt, không reapply refactor. Three existing UI modules + one helper, exact new source snapshots và adapter cho gate trực tiếp; không recapture manifest lịch sử hoặc migrate data. Xem [MEDIA_INFO_FIX.md](MEDIA_INFO_FIX.md).

Audit sau commit audio 04/10/2026: AST của popup update_info/description và hook startup hiện tại khớp baseline `4148c13`; thông số Codec cố định, GUI ffprobe và pre-Qt NameError là vấn đề tồn tại từ code cũ, không chứng cứ audio/UI mới phá các hàm này. Full regression/DPI/checkout gates và saved hashes đạt; chưa sửa production hoặc architectural imports. Xem [FINAL_FLOW_REVIEW.md](FINAL_FLOW_REVIEW.md).

Dễ nghe/commit 04/10/2026: chỉ policy/popup production đổi trong phase mới; năm tone/filter/gain/key cũ giữ nguyên, không tái áp architectural refactor. Archive raw bytes và adapter newline-only đối chiếu toàn file giúp Git checkout không phá gate hash cũ; không recapture prior manifests. Commit theo yêu cầu gom chuỗi audio chưa commit và tiền đề import đã có; để build/spec/requirements/log thay đổi của user ngoài phạm vi. Xem [AUDIO_EASY_LISTENING.md](AUDIO_EASY_LISTENING.md).

Chất âm 04/10/2026: thay đổi được user cho phép chỉ ở ba production module policy/prepare/popup. Hai tone token mới không đổi profile/cache keys cũ, truyền channels trong analysis/render để không downmix mono/surround. Exact new snapshot gates phục hồi code trước style trước khi test gate lịch sử; một test raw-hash realtime dùng adapter này thay vì bỏ kiểm tra. Không architectural refactor, model/ASR/lifecycle/source-data changes. Xem [AUDIO_LISTENING_STYLES.md](AUDIO_LISTENING_STYLES.md).

Prefetch EQ 04/10/2026: thêm helper incremental, không áp refactor đã rollback. MainWindow chỉ thêm notification trong `toggle_global_shuffle`; controller dùng cùng worker và snapshot restore gate selection-wait/v2/v1. Popup thêm tùy chọn và đo nhãn theo fixed width; source xử lý EQ/gain/cache không đổi. 270 pass +11 skip, 100 DPI tests và 8 read-only video probes không chứng nhận toàn native/EXE parity. Xem [AUDIO_NEXT_PREFETCH.md](AUDIO_NEXT_PREFETCH.md).

Chờ EQ 04/10/2026: đây là thay đổi hành vi lúc chọn bài được user cho phép, không áp refactor kiến trúc. Năm MainWindow adapters + owned audio orchestration/popup note có gate riêng, phục hồi v2 cho test cũ mà không recapture v1/v2. Giữ schema/file nguồn/owner và normalization gốc. Xem [AUDIO_START_WAIT.md](AUDIO_START_WAIT.md).

Rà soát chốt âm thanh 04/10/2026: chỉ review và chạy lại kiểm tra, không đổi production hoặc recapture source manifests. Các tính năng EQ/denoise tiếp theo còn là đề xuất, không áp architectural refactor/DSP mới. Xem [AUDIO_ENHANCEMENT_PLAN.md](AUDIO_ENHANCEMENT_PLAN.md).

Cân bằng trực tiếp 04/10/2026: v1 có source reload/attenuation và EQ cut được user phản hồi; v2 chỉ thay normalization bằng gain trực tiếp, target có lựa chọn, giữ EQ riêng. Không áp architecture refactor hoặc đổi engine/clock/ASR/playlist. Exact v2 adapters phục hồi snapshot v1 cho các gate cũ, manifest cũ không được recapture. 247 pass +11 skip, 77 DPI tests; xem [AUDIO_NORMALIZATION_REALTIME.md](AUDIO_NORMALIZATION_REALTIME.md).

Âm thanh tùy chọn 04/10/2026: đây là tính năng mới được user cho phép sau các phase reliability/presentation, không áp refactor đã rollback. Thêm helper/worker/popup và adapter UI có exact snapshot gates; video/native/subtitle/playlist/ASR owners và dữ liệu gốc được giữ. Import correction + CRLF user có trước phase được normalize riêng với hash/text checks, không recapture manifest cũ. 229 pass +11 skip, 59 DPI tests, 8 media probes; xem [AUDIO_EFFECTS.md](AUDIO_EFFECTS.md).

Hiển thị phụ đề 04/10/2026: nhiều đường show overlay floating và callback hide tồn tại sau cancel fade được sửa theo yêu cầu riêng. Snapshot trước phase tái hiện restart/stale callback; không áp refactor lịch sử hoặc timestamp phase đã rollback. Source gates chỉ normalize hai source đúng hash approved; 203 pass +11 skip, 33 DPI tests, 31 saved files giữ hash. Xem [SUBTITLE_PRESENTATION_FIX.md](SUBTITLE_PRESENTATION_FIX.md).

Reliability 04/10/2026: người dùng cho phép sửa audit A1–A4/A6, giữ file cũ. Đây là phase chức năng/lifecycle có regression và exact scope snapshots, không áp kiến trúc đã rollback. 187 pass +11 skip; ID/schema/time/ASR/hook và hash 31 data files giữ nguyên. Native/GPU/API/EXE còn chờ. Xem [RELIABILITY_FIX.md](RELIABILITY_FIX.md).

Audit luồng 04/10/2026: không áp refactor hoặc sửa production. Fault probes/AST baseline xác nhận các nhánh có trước UI mới: save dở dang/editor success giả, dịch rỗng/thiếu, restart AI chờ GUI, startup hook NameError. Download/editor shutdown chỉ ghi source-level gap, chưa tái hiện crash. 159 pass +11 historical skip không chứng minh app hết lỗi. Xem [CURRENT_FLOW_AUDIT.md](CURRENT_FLOW_AUDIT.md).

Spacing/caption For You (04/10/2026): padding wrapper chung cộng với padding page gây khoảng mép lớn/không đều. Chỉnh presentation page + helper wrapper theo trang và màu native caption; không áp architectural refactor/frameless hoặc đổi MainWindow byte nào. Gates snapshot/AST và native style/state checks được ghi trong [FORYOU_SPACING_AND_CAPTION.md](FORYOU_SPACING_AND_CAPTION.md).

Chia lyric (04/10/2026): lỗi ghép hai ASR lines ngắn và cắt giữa phrase tại 8 s thuộc profile quality hiện hành. Đã chỉnh grouping riêng theo phản hồi mới, không áp refactor kiến trúc hoặc timestamp/fade bị rollback. Snapshot và bốn adapter gate giữ nguyên source còn lại; chưa coi heuristic là parser ngữ nghĩa hoàn hảo. Xem [LYRIC_PHRASE_GROUPING.md](LYRIC_PHRASE_GROUPING.md).

Loading For You bổ sung: đây là hành vi UI được người dùng yêu cầu sau phase search/performance, không áp lại refactor cũ. Chỉ đổi hai adapter search gốc; helper timer chunks/generation/overlay và completion ảnh được review riêng. Giữ synchronous load/shuffle API và toàn bộ source gates ngoài các adapter. Xem [FORYOU_SEARCH_LOADING.md](FORYOU_SEARCH_LOADING.md).

Đợt For You search/cuộn (04/10/2026): dựng toàn bộ các dòng trước bài active, lọc GUI/rebuild và decode ngoài viewport có trong code trước đợt này. Đã thay bằng viewport pool giữ API và ngân sách hai decoder; tách full queue khỏi filtered view theo lựa chọn người dùng. Không áp lại refactor lịch sử, không đổi subtitle/native lifecycle. Snapshot trước sửa, adapter source gates và số đo cùng workload: [FORYOU_SEARCH_PERFORMANCE.md](FORYOU_SEARCH_PERFORMANCE.md).

Đợt empty-result: pipeline ném exception khi hết lời, manager bỏ save/render rỗng và ASS validator bắt buộc Dialogue nằm trong luồng có trước patch mới. Đã cho completed empty được lưu/cache, clear UI/editor và kiểm tra save failure, với source gate cụ thể; không áp lại refactor hoặc timestamp/fade đã rollback. Xem [EMPTY_SUBTITLE_RESULTS.md](EMPTY_SUBTITLE_RESULTS.md).

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
