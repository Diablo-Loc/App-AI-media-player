# Phát triển trên bản app đã khôi phục

03/10/2026: `app/` đã về baseline gốc. Đọc `AGENTS.md`, `RESTORED_APP_REVIEW.md`, `FEATURE_PARITY.md` và `ROADMAP.md` trước khi sửa.

UI sau audit đã được nâng cấp trên Widgets theo yêu cầu mới; đọc `UI_REFRESH.md` và `UI_STRATEGY.md`. `tests/test_ui_refresh.py` là bộ gate hiện tại; các module test kiến trúc rollback giữ lại với điều kiện skip rõ lý do. Snapshot audit gốc phải được giữ, không chạy tool audit ghi đè nó bằng source UI mới.

Chạy source từ repo root bằng entry script hiện có:

```powershell
.\venv\Scripts\python.exe app/run_app.py
```

`python -m app` thuộc bản refactor đã rollback; hiện không có `app/__main__.py`. Import ngắn và portable setup đang là hợp đồng entry script. Migration `app.*` và composition root mới chưa triển khai lại.

Audit không import app hoặc chạy model/network/registry:

```powershell
.\venv\Scripts\python.exe tools/audit_restored_app.py
.\venv\Scripts\python.exe tools/probe_restored_contracts.py
git diff --check
git diff HEAD -- app
```

Audit compile/AST/hash toàn bộ source, ghi `docs/restored-app-baseline.json`; chỉ chạy lại khi chủ đích chụp baseline mới, giữ bản chuẩn cũ để so sánh patch. Probe dùng snippets nguồn tin cậy và settings/API stub, không phải kiểm thử toàn app.

`tests/` còn test của refactor đã rollback, tham chiếu module hiện không tồn tại. Chưa chạy discovery suite này cho baseline khôi phục. Cần thích ứng hoặc thêm characterization tests cho đúng baseline từng phase trước khi dùng:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Không coi import failure của test lịch sử là bằng chứng app hỏng; không xóa test để đạt pass. Giữ test/demo để đối chiếu, rồi cập nhật theo scope.

Dùng Python 3.11 hiện có; không nâng dependency, model/runtime, schema/cache key/path. Không chạy build/updater/download/cleanup để audit. Nếu sandbox không đọc được base Python của venv, cần quyền truy cập runtime đó; không tạo lại venv.

Build config ngoài app còn sửa từ lượt trước; xác minh packaging thực tế trước release, không chạy script dọn output chỉ để kiểm tra source. Source snapshot không thay thế backup dữ liệu người dùng hoặc actual EXE smoke.
