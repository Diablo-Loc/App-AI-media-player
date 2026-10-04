# App-AI-media-player (BoTube)

For You: gutter/search cân đối 12 px, thanh tiêu đề native đồng bộ màu trên Windows hỗ trợ. Giữ PySide6 và các luồng cửa sổ/video hiện có. [Báo cáo UI](docs/FORYOU_SPACING_AND_CAPTION.md).

Lyric: cải thiện chia câu cho phụ đề tạo mới, giữ nguyên các bài đã lưu. [Phạm vi sửa và kiểm chứng](docs/LYRIC_PHRASE_GROUPING.md).

For You: search và xóa search có vòng loading, chỉ hiện kết quả khi chuẩn bị xong; giữ toàn playlist cho Next/Previous. [Chi tiết kiểm chứng](docs/FORYOU_SEARCH_LOADING.md).

For You search/cuộn: [báo cáo và số đo](docs/FORYOU_SEARCH_PERFORMANCE.md). Search chỉ lọc hiển thị; Next/Previous giữ toàn playlist. Danh sách dùng viewport pool và hai decoder thumbnail để giảm chặn giao diện.

A media player with AI-powered subtitle, translation and processing features.
This repository contains both the application code and tooling for building
packaged executables.

## Development and architecture

Use the project Python 3.11 environment from the repository root:

```powershell
.\venv\Scripts\python.exe app/run_app.py
```

FFmpeg/FFprobe can be installed in `PATH`, `bin/`, or `app_resources/bin/`.
Portable AI libraries and models remain in `app_resources/` beside the executable.
Persistent data remains in `storage/`; existing media IDs and subtitle JSON are preserved.

The user restored `app/` to the original working baseline on 2026-10-03.
Use the script entry point above; `python -m app` belongs to the reverted refactor
and is unavailable in the restored tree. The [current review](docs/RESTORED_APP_REVIEW.md)
analyzes every directory, preserves the current UI and runtime, and proposes
incremental performance and accuracy work. See the [documentation index](docs/README.md)
for current reports and historical refactor records.

```powershell
.\venv\Scripts\python.exe tools/audit_restored_app.py
.\venv\Scripts\python.exe tools/probe_restored_contracts.py
```

`tests/` currently contains historical tests for the reverted refactor; adapt them
to the restored baseline before using discovery for validation. `app/test/` contains
legacy interactive demos that may start Qt/GPU/network work. The audit and contract
probes above do not start the application, access user settings, or call APIs/models.

The current phase keeps the UI and prioritizes architecture and responsiveness.
See [development](docs/DEVELOPMENT.md), [feature contracts](docs/FEATURE_PARITY.md),
[previous refactor audit](docs/PREVIOUS_REFACTOR_AUDIT.md),
[performance results](docs/PERFORMANCE.md), [roadmap](docs/ROADMAP.md),
and [future UI strategy](docs/UI_STRATEGY.md). Repository working rules live in
[AGENTS.md](AGENTS.md).

---

## Updating from older versions

### Manual hot-patch (v1.0.2)

This step is required once for users of the original 4 GB/66 MB installer.

1. Download `update.zip` from the **v1.0.2** release assets on GitHub.
2. Extract the archive; it contains `BoTube_patch.exe` and `version.json`.
3. **Do not copy** `BoTube_patch.exe` over the old `BoTube.exe`.
   Instead, **run `BoTube_patch.exe`**; it will overwrite the old executable and
   also update the local `version.json` file.
4. After the patcher finishes, the real application will start. Future updates
   will be handled automatically by the built-in updater.

*The patcher binary is deliberately small (__~9 MB__) and contains only the
update logic—it does not include the full app. Copying it over the original
exe will render the program unlaunchable!*

### Automatic updates (1.0.2+)

From version 1.0.2 onwards the app can check GitHub for a `version.json` and
download a tiny `update.zip` when a newer release is available.  The updater
decides whether to fetch the patcher or the full binary based on the metadata.

Configuration is stored in `config.json` (see `config.example.json`).  You may
specify:

- `version_url`: link to the remote `version.json` metadata (fallback is built in)
- `update_url`: link to the archive which should be downloaded when an update is
  found (this typically points to the same GitHub release asset).

The app will display progress, verify the ZIP integrity, and then launch the
appropriate helper script (`update_helper.bat` or `.sh`) to apply the update.

---

## Building

- `python build_app.py` produces the full `BoTube.exe` in `dist/BoTube`.
- `python patch_build.py` creates a tiny `BoTube_patch.exe` and an accompanying
  `update.zip` containing the patcher plus current `version.json`.

Refer to the source files for more details.
