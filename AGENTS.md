# BoTube development contract

Reliability phase (2026-10-04): read `docs/RELIABILITY_FIX.md`. User authorized A1–A4/A6, protected saved subtitles and excluded Qt hook. Save prepares JSON/ASS/index with owned recovery journals; no migration/re-alignment. Translation preserves source repeats, validates cardinality/IDs, ignores failed/blank cache on read and loads NLLB only on misses. Preserve schema/IDs/cache keys/prompts/model/ASR/timing/fade/AI spawn. AI/thumbnail restart is nonblocking/latest-request; folder scan uses owned snapshot worker, GUI commit and separate cache I/O lock; synchronous library API retained. Download/editor workers/processes owned until finished; wait at shutdown, never QThread terminate. Exact snapshots in `docs/reliability` restore prior gates only after approved hash checks. 187 pass +11 historical skip; 35 DPI tests and fixture process shutdown do not establish full native/GPU/network/EXE parity. Batch thumbnail cache/context keys remain future work.

For You spacing/caption phase (2026-10-04): read `docs/FORYOU_SPACING_AND_CAPTION.md`. Keep 12 logical px header/body gutters and column gap; search is 40 high inside a 64-high header with balanced side slots. `ui.foryou_spacing` removes wrapper/browser gaps only for the selected For You page and restores captured defaults for other pages. `ui.native_frame_style` colors the existing Windows caption via DWM; do not replace native frame/buttons, change flags/geometry/hit-test or video/subtitle owners as polish. Keep unsupported OS fallback and owned/coalesced event timers. MainWindow bytes stayed unchanged in this phase; exact snapshot gates allow only ForYou init presentation/import and four shell helper-install statements. Native Windows 11 Set/state/style probes do not prove all snap/drag/multi-monitor/EXE parity.

Lyric phrase phase (2026-10-04): read `docs/LYRIC_PHRASE_GROUPING.md`. The user confirmed fragmented/merged sentences. New generation groups accepted words with `pipeline.lyric_phrases`: useful ASR boundaries, short-fragment/continuation guards, repeated short lines, correct newline edges and balanced oversized groups. Do not cut a sustained note solely at 8 seconds or restore the removed timestamp phase. Keep 50 ms lead/80 ms tail, finalizer/fade, credit/repetition filters, ASR/coverage/translation and saved subtitle load/schema unchanged. Four exact reviewed refinement adapters restore the rollback source in the gate; do not migrate saved cues. Distinguish 24 captured-ASR replays from fresh model runs or human semantic/timing ground truth.

For You loading phase (2026-10-04): read `docs/FORYOU_SEARCH_LOADING.md`. Search and clear show a viewport-only spinner, prepare in owned timer chunks (500 metadata), then commit a complete view. Keep latest-query cancellation, GUI-thread Widgets, full playback order, and the two-decoder budget. Wait only for visible thumbnails; failures/placeholders and a 2-second post-commit deadline prevent stuck loading. Never preload all playlist images. Animation stops while hidden and keeps its angle across edits. Preserve synchronous load/shuffle APIs and exact reviewed search adapters; timing/ASR/native lifecycle remain unchanged. Measure submission and async completion separately.

For You search/performance phase (2026-10-04): read `docs/FORYOU_SEARCH_PERFORMANCE.md`. The user explicitly chose a full playback queue; search only filters the view. Preserve full master/original order, keep the selected shuffle order across search/clear and do not overwrite master with filtered results. `foryou_playlist_view` owns viewport-sized reusable Widgets; `cards_map`/`loaded_count` mean realized rows rather than prefix loading. `playlist_thumbnail_queue` owns two decoders with completion/cancellation/shutdown; preserve quality/cache keys/DPR and GUI-thread widgets. Keep the exact adapters/source gates and native/video/subtitle lifecycle. Search remains debounced in-memory metadata filtering, measured to 10,000 entries. Do not claim native screen FPS or full EXE parity from QVideoSink/offscreen probes.

Current phase (2026-10-03): after restoring and auditing the original working baseline, the user explicitly authorized a modern UI refresh while preserving functionality. Read `docs/UI_REFRESH.md`, `docs/RESTORED_APP_REVIEW.md` and `docs/ACCURACY_BASELINE_PLAN.md`. Do not reapply the previous architectural refactor or migrate imports automatically. `app/bootstrap/application.py` and the proposed new packages are absent; composition/import rules below govern future reviewed changes. Current UI tests use the restored baseline; historical refactor tests are explicitly skipped while their target architecture is absent.

Accuracy phase (2026-10-03): the user explicitly prioritized missing first-30-second Whisper lyrics. Read `docs/ASR_COVERAGE_FIX.md`. `app/ai/pipeline.py` retains the model for targeted coverage retries and fixes CPU-fallback language initialization; `app/pipeline/asr_coverage.py` is the helper. Primary ASR options remain frozen. The first coverage phase kept accepted cue text/timing unchanged; the explicitly authorized quality phase below now improves newly generated timing/splitting. Use captured source/AST gates and real-media comparisons; do not label VAD coverage as proof of perfect lyrics or reapply the historical refactor.

Subtitle quality phase (2026-10-03): the user explicitly authorized improving new subtitle boundaries/splitting/repeated lyrics while leaving saved subtitles untouched. Read `docs/SUBTITLE_QUALITY_FIX.md`. Production uses `pipeline.lyric_refinement` for primary and coverage; legacy aligner defaults remain equivalent through an optional short-lyric guard. Newly generated objects are marked after translation to prevent a second storage padding; persisted JSON/index schemas, media IDs and load/controller paths remain unchanged. Never realign/migrate existing subtitle files automatically. Shared SRT/LRC/ASS unit rounding is an intentional export correction. Keep the limited AST/source gates and distinguish real ASR/save probes from human timing/lyrics ground truth and pending native/EXE/update tests.

## Product and compatibility

Empty-result phase (2026-10-03): read `docs/EMPTY_SUBTITLE_RESULTS.md`. A completed ASR + coverage with no accepted cues exports empty SRT/LRC and returns the existing result schema with `segments: []`, skipping translation. Save empty JSON and header-only ASS; accept header-only cache only with explicit empty source JSON. Clear overlay cue list/editor rows, retain force regeneration, and keep technical errors/cancel/save failures distinct. Do not infer guaranteed instrumental classification from empty ASR. Exact four-source adapters have narrow whole-module AST gates. Timing/fade remain at the rollback profile (50 ms lead /80 ms tail); only the explicitly reviewed lyric phrase phase above supersedes grouping. Do not reapply the removed timestamp phase.

- The existing application is the behavioral baseline. Preserve every feature, media format, shortcut, subtitle mode, provider, download option, window mode and portable workflow.
- The latest user instruction authorizes improving the UI. Retain PySide6 Widgets and the existing video/subtitle/window lifecycle. Use the shared design system and offline Lucide SVG icons; adding a UI framework is outside this implementation phase.
- Separate responsibilities incrementally. Keep existing entry points and public APIs through compatibility adapters when moving implementations.
- Do not change subtitle timing/padding, ASR parameters, translation prompts, fallback order, model-loading compatibility, playlist selection/order or cache keys as a side effect of refactoring.
- A different implementation is acceptable when its externally visible result remains equivalent. Record intentional improvements and their verification.
- Use `docs/FEATURE_PARITY.md`, `docs/PREVIOUS_REFACTOR_AUDIT.md` and `docs/ROADMAP.md` before changing feature code. Update their status after each completed phase.

## Dependencies and data

- Internal imports use `app.*`. Domain rules must not depend on Qt, network providers or GPU libraries.
- Compose shared services in `app/bootstrap/application.py`; inject services rather than instantiating duplicate owners.
- Keep existing media IDs and persisted schemas. Schema/path changes need explicit migration, compatibility tests and a recovery path.
- Preserve user media, models, settings and existing worktree changes. Never clean build/dist/storage or run network downloads merely to validate a refactor.
- Use the project's Python 3.11 environment. Do not upgrade Python, CUDA, torch, transformers or packaging dependencies without a separate compatibility phase.

## Responsiveness and lifecycle

- Create/mutate Qt widgets on the GUI thread. Long file scanning, ffprobe, image decoding and model processing belong to owned background workers.
- Keep AI in a spawn process. Keep worker references until their threads finish. Ignore stale results and close resources owned by each component.
- Avoid GUI-thread waits during normal interaction. Waiting for owned workers during shutdown is allowed to prevent destroyed-running-thread crashes.
- Preserve synchronous service APIs for existing callers; add asynchronous orchestration around them.
- Batch disposable cache persistence where useful; flush on completion/cancellation. User-edited source/settings must remain durable.

## Verification and delivery

- Run `.\venv\Scripts\python.exe -m unittest discover -s tests -v` and `git diff --check` for affected phases. Tests may require execution outside the filesystem sandbox to reach the installed Python.
- Use meaningful behavior/compatibility tests, including comparisons with the captured original contracts. Compilation or mocks alone do not prove all features still work.
- Measure performance before claiming improvements. Record dataset size, environment and limitations. Deterministic operation counts are preferred to unstable timing assertions.
- Distinguish verified behavior, source-level review, and pending real-media/GPU/network/native/EXE validation. Never report complete feature parity from a partial smoke test.
- No commit, release, deployment or unrelated cleanup unless requested. Stage the roadmap in reviewable phases; do not hide unfinished phases.
