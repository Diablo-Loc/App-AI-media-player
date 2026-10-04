# Kiểm chứng hiệu năng và tương thích — 03/10/2026

> Lịch sử của bản refactor đã rollback. App hiện tại không có các thay đổi được đo bên dưới; 52 test và số đo 11,8x không áp dụng cho baseline đã khôi phục. Báo cáo hiện hành: [RESTORED_APP_REVIEW.md](RESTORED_APP_REVIEW.md).

## Đã thay đổi

- `LibraryController` giữ một scan worker, xếp yêu cầu mới nhất và hủy scan cũ theo từng filesystem entry. `scan_folder()` đồng bộ vẫn dùng được như cũ; Qt nhận kết quả qua signal sau khi worker kết thúc. UI không gọi ffprobe trực tiếp khi chọn/refresh thư mục.
- Restart thumbnail yêu cầu dừng rồi đợi signal `finished`, không gọi `wait()` trên GUI trong đường restart. Shutdown vẫn chờ tài nguyên được sở hữu.
- Thumbnail metadata hiện ngay trong RAM; cache JSON flush mỗi 12 cập nhật và ở `finally` khi hoàn tất/hủy. Mặc định API `update_thumbnail_in_db()` vẫn ghi ngay cho caller cũ. Không thay thuật toán/file ảnh thumbnail.
- Library có lock/snapshot để scan, cache update và save dùng chung không thay đổi dictionary khi đang serialize.

## Đo phần ghi cache

Windows build 22631, Python 3.11.0; metadata tổng hợp 1.000 mục, cập nhật 120 thumbnail, lặp 3 lần trong thư mục tạm. Hai phương án đều dùng cùng atomic writer để tách riêng lợi ích batching; đây không phải benchmark toàn app hoặc bản EXE cũ.

| Phương án | Lần ghi / lượt | Thời gian median |
| --- | ---: | ---: |
| Ghi sau từng thumbnail | 120 | 1,961 giây |
| Batch 12 + flush cuối | 10 | 0,166 giây |

Giảm **91,7% số lần ghi**; phần persistence trong benchmark này nhanh khoảng **11,8 lần**. Hash dữ liệu JSON cuối giống nhau trên cả 6 lượt. Không suy ra FPS hoặc tốc độ Whisper/FFmpeg từ số liệu này. Kết quả thô: [library-cache.json](benchmarks/library-cache.json).

```powershell
.\venv\Scripts\python.exe -m tools.benchmark_library --output docs/benchmarks/library-cache.json
```

## Tương thích và lifecycle

Các contract lấy từ Git `4148c13` nằm trong `tests/fixtures/legacy_contracts.json`, có tool capture riêng. Test đối chiếu đầu ra scan recursive/cache/duration-zero, metadata tags/fallback, subtitle object timing/text, điều hướng playlist với ID trùng và biên. Worker tests kiểm tra GUI timer vẫn chạy khi scan chưa xong, thread khác GUI, chỉ xuất kết quả mới nhất, không scan song song, lỗi rồi retry, hủy/đóng, thumbnail flush và restart không wait.

Smoke cửa sổ dùng composition thật, settings/media tổng hợp tạm và scan nền; native DLL bị mock. Quét lại toàn `app/`: **119 file Python, 16.667 dòng** (bao gồm package markers và legacy demos). Danh sách source/import và file trong cây (bỏ bytecode): [inventory-current.json](inventory-current.json).

Final validation: **52/52 test pass**, không skip, trên Python 3.11.0 / PySide6 6.10.1; **137 file Python** ở app/tests/tools và hai build entrypoints compile thành công; `git diff --check` pass. Chưa có kiểm chứng playback media thật, GPU/NLLB portable, online/download/native DLL và build EXE. Theo dõi trong `FEATURE_PARITY.md` trước release.

## Giới hạn của batch/cancel

Nếu process bị crash trước flush, tối đa 11 cập nhật đường dẫn cache thumbnail chưa nằm trong JSON; file ảnh vẫn còn và manager có thể dùng lại ở lượt sau. Khi hủy bình thường luôn flush. Scan đang hủy có thể lưu các metadata đã hoàn tất vào cache chung nhưng không đưa kết quả cũ lên UI. Mỗi ffprobe có timeout 3 giây; hủy không giết probe đang chạy, chờ hết entry rồi dừng. Đây là tối ưu thao tác UI, chưa phải tối ưu tất cả filesystem traversal/layout/model loading.
