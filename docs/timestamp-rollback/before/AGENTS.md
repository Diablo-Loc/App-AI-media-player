# BoTube development contract

Current phase (2026-10-03): after restoring and auditing the original working baseline, the user explicitly authorized a modern UI refresh while preserving functionality. Read `docs/UI_REFRESH.md`, `docs/RESTORED_APP_REVIEW.md` and `docs/ACCURACY_BASELINE_PLAN.md`. Do not reapply the previous architectural refactor or migrate imports automatically. `app/bootstrap/application.py` and the proposed new packages are absent; composition/import rules below govern future reviewed changes. Current UI tests use the restored baseline; historical refactor tests are explicitly skipped while their target architecture is absent.

Accuracy phase (2026-10-03): the user explicitly prioritized missing first-30-second Whisper lyrics. Read `docs/ASR_COVERAGE_FIX.md`. `app/ai/pipeline.py` retains the model for targeted coverage retries and fixes CPU-fallback language initialization; `app/pipeline/asr_coverage.py` is the helper. Primary ASR options remain frozen. The first coverage phase kept accepted cue text/timing unchanged; the explicitly authorized quality phase below now improves newly generated timing/splitting. Use captured source/AST gates and real-media comparisons; do not label VAD coverage as proof of perfect lyrics or reapply the historical refactor.

Subtitle quality phase (2026-10-03): the user explicitly authorized improving new subtitle boundaries/splitting/repeated lyrics while leaving saved subtitles untouched. Read `docs/SUBTITLE_QUALITY_FIX.md`. Production uses `pipeline.lyric_refinement` for primary and coverage; legacy aligner defaults remain equivalent through an optional short-lyric guard. Newly generated objects are marked after translation to prevent a second storage padding; persisted JSON/index schemas, media IDs and load/controller paths remain unchanged. Never realign/migrate existing subtitle files automatically. Shared SRT/LRC/ASS unit rounding is an intentional export correction. Keep the limited AST/source gates and distinguish real ASR/save probes from human timing/lyrics ground truth and pending native/EXE/update tests.

## Product and compatibility

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
