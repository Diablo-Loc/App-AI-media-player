# Current UI tests and historical refactor tests

Latest coverage/resource verification: 4 `test_asr_repeat_stress.py` regressions exercise 30/100 fused or stalled fillers, 2/3 adjacent timed refrains and deliberate preservation of 100 progressing words without proof of hallucination. Discovery: **107 passes +11 historical skips (118 total)**. Eight real local videos ×3 were measured separately before the test suite; all 801 pre-coverage cues and 21 existing subtitle file hashes were preserved. No production code/options changed in this verification turn. See `docs/ASR_RESOURCE_AND_REPEAT_CHECK.md` for timing/RAM measurements and limits. Counts below describe earlier phases.

Latest subtitle quality phase: `test_lyric_refinement.py` adds 29 new generation/storage/export/legacy regressions; discovery is **103 passes + 11 historical skips (114 total)**. Five original non-UI sources now have narrow reviewed accuracy/format adapters checked against captured AST; the other 56 source hashes stay frozen. Primary Whisper options and unrelated orchestration remain original. Old subtitle JSON/ASS bytes are checked unchanged across read/cache/new-song save; marker pickle and new saves are checked without second padding. Replay three captured ASR datasets and real production ASR/export/save probes are recorded in `docs/SUBTITLE_QUALITY_FIX.md`; human lyric/timing ground truth, translation/native/EXE/update validation remains pending. Counts below describe prior phases.

Latest accuracy phase: `test_asr_coverage.py` adds 19 coverage/pipeline/source regressions. Current discovery is **74 passes + 11 historical skips (85 total)**. One original non-UI source (`app/ai/pipeline.py`) has an explicitly reviewed accuracy adapter; its full original flow is checked after normalizing that adapter, with primary ASR/refine options frozen. Other non-UI hashes remain unchanged. Real large-v3/CUDA probes on three local videos and the production ASR/export path are documented in `docs/ASR_COVERAGE_FIX.md`; translation/native/EXE and perfect lyric coverage are not claimed.

Latest thumbnail phase: `test_playlist_thumbnail_quality.py` adds 8 tests for real JPEG reference error, QImage decoding on a pool thread/GUI delivery, fractional-DPR backing pixels/crop/cache, stale results, cancellation/small sources and actual widget resolution. Full discovery: 55 passes + 11 historical skips (66 total). Eight tests pass at scale 125%/150%/200%; scale 200% also includes the 6 layout regressions. See `docs/PLAYLIST_THUMBNAIL_QUALITY.md`.

Latest layout phase: `test_ui_layout_polish.py` adds 6 real Qt regressions for playlist elision/geometry/click/highlight, download edit-field bounds/options/JSON schema, and centered menu pixels. Full discovery is 47 passes + 11 historical skips (58 total); the 6 new tests also pass at DPI 200%. See `docs/UI_LAYOUT_POLISH.md`. Counts below describe earlier phases.

Latest phase: `test_ui_media_surface.py` adds 9 tests for truthful toggle colours, real mouse shuffle/order parity, shared-video ownership and first-frame refresh, plus normalization of only the three new adapters against captured original AST. Current full discovery is 41 passes + 11 historical skips (52 total); all current UI tests also run at DPI 200%. See `docs/UI_MEDIA_SURFACE.md` for the read-only actual-decoder probe and native presentation limits. Counts below describe earlier UI phases.

The user restored `app/` to the original working baseline on 2026-10-03. These tests target the reverted refactor and still reference removed modules such as `app.bootstrap`, `app.media` and `app.infrastructure`.

The earlier 52 passing tests do not apply to the restored application. Keep the tests and captured legacy contracts for comparison. The eleven old test modules now raise an explicit module-level SkipTest when `app/bootstrap/application.py` is absent; their test bodies/fixtures are preserved. This is a version prerequisite, not a passing compatibility result. Removing the guard or restoring that architecture makes them run again.

`test_ui_refresh.py` tests the current baseline: frozen source hashes/API/signals/connections and real Qt widgets with synthetic media and isolated settings. Run the mandated command from the project root:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Report actual passes and historical skips separately. Full GPU/network/native/media/EXE checks remain pending. Subtitle-tools production construction crashes in this offscreen runtime in BOTH original and refreshed sources; the preview-only adapter must not be counted as a lifecycle test. See `docs/UI_REFRESH.md`.

`test_ui_stability.py` adds rendered-pixel checks for all collapsed navigation icons, real mouse dispatch to volume with/without a floating subtitle, responsive control bounds, popup/seek auto-hide protection, animation ownership, and unchanged HTML metadata. It also runs at `QT_SCALE_FACTOR=2`. Current discovery: 32 passes + 11 historical skips. The connection gate retains every original binding and explicitly allows one additional sidebar-animation/grid-reflow binding. See `docs/UI_STABILITY.md` for environment, focus simulation and native limitations.

Current read-only source audit and isolated contract probes are documented in `docs/RESTORED_APP_REVIEW.md` and `docs/DEVELOPMENT.md`.
