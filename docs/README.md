# Tài liệu hiện hành sau khi khôi phục

- [Tối ưu đã triển khai: batch thumbnail, hai decoder và grid Library theo viewport; số đo và bảo toàn dữ liệu](RESOURCE_PERFORMANCE_FIX.md).

- [Audit CPU/RAM/I/O toàn app: cache thumbnail, grid Library, decoder và lộ trình giữ nguyên chức năng](APP_PERFORMANCE_REVIEW.md).

- [Sửa lyric nhẹ theo ưu tiên hiệu năng: credit/CPU, dữ liệu cũ và những hướng nặng đã bỏ](LYRIC_ACCURACY_LIGHTWEIGHT.md).

- [Rà soát Whisper/lyric: giới hạn accuracy, credit filter và phase đối chứng đề xuất](ASR_ACCURACY_REVIEW.md).

- [Typography động kiểu edit: 8 chuyển cảnh mạnh, preview, cache/DPR và bảo toàn luồng cũ](SUBTITLE_KINETIC.md).

- [Ẩn chữ sau phi tiêu/vệt quét: cách bật, bảo toàn dữ liệu và kiểm tra pixel/DPI](SUBTITLE_SWEEP.md).

- [Phi tiêu, sao lấp lánh và 9 bộ mẫu phụ đề: preview, Unicode, giới hạn hạt và kiểm chứng](SUBTITLE_PARTICLES.md).

- [Hiệu ứng phụ đề tùy chọn, cách dùng, hiệu năng và bảo toàn timing/dữ liệu](SUBTITLE_EFFECTS.md).

- [Sửa import direct-entry, quét toàn cây và kiểm tra process cô lập](RUNTIME_IMPORT_FIX.md).

- [Sửa tải giữ audio nguồn: codec/fallback/container, preset cũ và kiểm chứng](DOWNLOAD_QUALITY_FIX.md).

- [Rà soát chất lượng tải YouTube: giữ nguồn, chuyển mã và lỗi selector cần sửa](DOWNLOAD_QUALITY_REVIEW.md).

- [Nhớ âm lượng, Cài đặt phần trăm và build EXE không xóa bản cũ](VOLUME_AND_BUILD.md).

- [Thông tin file đúng, đọc metadata nền, cache/cancel/shutdown và bảo toàn dữ liệu cũ](MEDIA_INFO_FIX.md).

- [Rà soát toàn app sau chốt audio: kiểm chứng hiện hành và lỗi metadata/popup còn sót](FINAL_FLOW_REVIEW.md).

- [Dễ nghe cho loa/tai nghe và commit chốt phần âm thanh, giữ preset/dữ liệu cũ](AUDIO_EASY_LISTENING.md).

- [Chất âm Ấm và Tai nghe: EQ nhẹ/crossfeed tùy chọn, giữ âm gốc khi tắt](AUDIO_LISTENING_STYLES.md).

- [Chuẩn bị EQ trước cho một bài kế tiếp: giảm chờ, giữ âm gốc và giới hạn tài nguyên](AUDIO_NEXT_PREFETCH.md).

- [Chọn bài có EQ: chờ im lặng trước playback, cache và fallback](AUDIO_START_WAIT.md).

- [Chốt cân bằng và phương án EQ/giảm nhiễu, giới hạn phát liền mạch](AUDIO_ENHANCEMENT_PLAN.md).

- [Cân bằng trực tiếp: không reload, user volume riêng, −14/−18 LUFS và EQ có giới hạn](AUDIO_NORMALIZATION_REALTIME.md).

- [Âm thanh tùy chọn: cân bằng độ lớn, EQ nhẹ, cache nền và giới hạn chất lượng](AUDIO_EFFECTS.md).

03/10/2026: người dùng đã khôi phục `app/` về bản gốc. Tài liệu hiện hành:

- [Đánh giá từng thư mục](RESTORED_APP_REVIEW.md).
- [Audit luồng hiện hành và các lỗi cần sửa trước khi chốt](CURRENT_FLOW_AUDIT.md).
- [Sửa save/dịch/GUI wait và đóng app khi tải/dịch, bảo toàn file cũ](RELIABILITY_FIX.md).
- [Ẩn phụ đề trên editor và sửa fade/nhảy vị trí câu For You](SUBTITLE_PRESENTATION_FIX.md).
- [Baseline source/cây/import/function/hash](restored-app-baseline.json).
- [Contract probes offline](restored-contract-probes.json).
- [Kế hoạch đo hiệu năng và accuracy](ACCURACY_BASELINE_PLAN.md).
- [Sửa Whisper mất lời đầu bài: kết quả GPU thật và giới hạn coverage](ASR_COVERAGE_FIX.md).
- [Timing/chia câu/giữ lời lặp cho lần tạo mới, bảo toàn phụ đề cũ](SUBTITLE_QUALITY_FIX.md).
- [Nhạc không lời/kết quả rỗng: lưu, cache, worker và overlay/editor](EMPTY_SUBTITLE_RESULTS.md).
- [Đo chi phí coverage trên 8 video ×3, kiểm tra loop 30/100 và điệp khúc 2/3](ASR_RESOURCE_AND_REPEAT_CHECK.md).
- [Hợp đồng giữ tính năng](FEATURE_PARITY.md), [roadmap](ROADMAP.md), [development](DEVELOPMENT.md).

Tài liệu lưu lịch sử refactor đã rollback: `ARCHITECTURE_REVIEW.md` (có inventory code gốc nhưng kết quả refactor phần 7 là lịch sử), `PREVIOUS_REFACTOR_AUDIT.md`, `PERFORMANCE.md`, `inventory-current.json` (119 source), `benchmarks/library-cache.json`. Không dùng status/test/benchmark của chúng để mô tả app hiện tại.

UI mới đã được người dùng cho phép: [quyết định công nghệ](UI_STRATEGY.md), [kết quả/kiểm chứng/ảnh trước–sau](UI_REFRESH.md). `tests/test_ui_refresh.py` kiểm tra baseline hiện tại; các module test refactor cũ được giữ nguyên nội dung kiểm tra và có guard skip khi kiến trúc đích đã rollback.
