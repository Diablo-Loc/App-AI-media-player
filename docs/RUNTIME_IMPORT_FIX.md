# Import theo entry hiện tại — 04/10/2026

Người dùng báo `ModuleNotFoundError: No module named 'app'` khi chạy
`python app/run_app.py`, và yêu cầu quét toàn bộ import tương tự.

## Nguyên nhân và sửa

Entry này đưa thư mục `app/` vào sys.path, không bảo đảm repo root có mặt.
Namespace runtime hiện tại là `ui.*`, `control.*`, `download_core.*`, v.v.
Hai import policy downloader đã thêm sai prefix `app.*`. Các test trước
thêm repo root nên startup defect bị che dù regression/packet tests đạt.

Khi bắt đầu lượt này, worktree đã đổi hai import đó thành
`download_core.download_options`; giữ nguyên sửa cục bộ đó. Quét tiếp:

- Giữ hai import đúng ở DownloadWorker và SettingMenu, dùng cùng policy module.
- Sửa **5 import lazy** trong `download_source_app.py` từ
  `app.control.ai_controller` thành `control.ai_controller`. Chúng nằm trong
  nhánh thành công/thất bại cài tài nguyên và kiểm tra nhanh. Prefix sai có
  thể bị except bỏ qua hoặc cập nhật một bản cache module khác khi repo root
  tình cờ có mặt; import mới dùng đúng controller/cache đang chạy.
- Không đổi entry, bootstrap sys.path, chủ sở hữu Qt/thread, model/download
  actions, cache logic, DSP/profile/ASR hoặc schema/path dữ liệu.
- `app/downloader.py` đã có sửa của người dùng từ `app.paths` sang
  `.paths` trước lượt này; **không sửa tiếp file đó**. Adapter riêng chỉ ghi
  nhận đúng thay đổi một dòng này cho source gates lịch sử.

Không áp lại đề xuất refactor/import `app.*` đồng loạt. Quy tắc namespace
package tương lai trong AGENTS không phải lý do phá entry trực tiếp hiện tại.

## Toàn bộ cây

Scanner AST dùng rglob, gồm cả file Python bị Git ignore: **117 file,
215 local import references**. Không còn vấn đề local-module/name trong
đồ thị có thể tới từ `run_app`; đây là phân tích tĩnh, không kiểm chứng mọi
external dependency hoặc mục tiêu import được tính động.

Những tồn tại không thuộc luồng app, giữ nguyên và không báo là đã sửa:

- `app/downloader.py`: placeholder cũ, relative import cấp gốc và
  `paths.models_dir` không tồn tại. Không có caller runtime. Helper còn là
  stub, nên không bịa API/path mới hoặc sửa model workflow để làm nó import.
- `app/test/test.py`, `app/test/test_ai.py`: script thử thủ công cũ còn dùng
  `paths.temp_dir` đã bỏ; test_ai còn fallback `app.worker`. Không thuộc
  regression suite hiện hành hoặc đồ thị runtime. Không chạy chúng để tránh
  khởi động model/ghi phụ đề thật.
- `app/test_build_app.py`: harness chủ động thêm repo root trước
  `app.run_app`; có bảo đảm namespace đó, nên không đổi. Không dùng harness
  giả frozen này làm bằng chứng EXE thật.

## Kiểm chứng

- Python project 3.11, child process mới `python -I`, cwd ngoài repo,
  sys.path chỉ thêm `app/`; không dùng preview stubs hay QApp global của tests.
- Thực thi phần bootstrap/import của **run_app.py thật**, không gọi main:
  toàn bộ import MainWindow/menu/worker thành công khi package `app` không
  thể resolve. Không tạo cửa sổ, phát media, chạy/tải AI.
- Lặp với layout frozen (`sys.frozen`, `_MEIPASS`, executable ở temp dir):
  imports thành công; đây là mô phỏng layout, **không phải EXE đóng gói**.
- Kiểm tra 5 import cache lazy trỏ đúng một hàm/controller module; cập nhật
  cache/AIWorker flag trên memory của child, không ghi QSettings.
- Child cũng tái hiện việc hai prefix cũ không thể import, ngăn test bị repo
  root leak che lỗi lần nữa.
- Focused: **4 pass**. Checkout gates: **24 pass**, 4,266 s.
- Full regression cuối với faulthandler: **336 total =325 pass +11 historical
  skip**, 92,964 s. **42/42 file** media/subtitle/settings/cache/export giữ
  nguyên SHA-256 trước/sau.

Một lần full runner bị native access violation (`0xC0000005`) ở test nhớ
âm lượng; giữ [log](runtime-imports/full-tests-native-crash.txt). Rerun process
mới với faulthandler hoàn tất toàn suite; chưa có stack để xác định nguyên
nhân native của lần trước, không sửa âm lượng/Qt để quy lỗi đó cho imports
và không tuyên bố đã chữa native crash. Native GUI/EXE vẫn là nghiệm thu riêng.

Một archive downloader đã bị đổi cách kết thúc dòng sau phase trước.
Không nới hash hoặc recapture manifest: replay diff đã duyệt trên original
đã xác minh, chỉ khôi phục file khi kết quả đúng SHA cũ
`c56130604c62cfd40247755a271d4ba5e66ba7720afbd9d5698022b3c36f124c`.
Xem [record](runtime-imports/archive-restoration.json). Manifest trước giữ nguyên.
Exact snapshot/adapter mới phục hồi downloader phase cho source gates cũ.

Chứng cứ: [inventory](runtime-imports/import-inventory.json),
[focused](runtime-imports/focused-tests.txt), [checkout](runtime-imports/checkout-tests.txt),
[full](runtime-imports/full-tests.txt), [saved hashes](runtime-imports/saved-check.json),
[manifest](runtime-imports/reviewed-sources.json),
[diff](runtime-imports/reviewed.patch). Không commit/build/cài dependency.
