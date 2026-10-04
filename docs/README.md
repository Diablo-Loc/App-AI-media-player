# Tài liệu hiện hành sau khi khôi phục

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
