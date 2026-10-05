# Logical phrase sweep flow — 05/10/2026

Follow-up hardening: [SUBTITLE_SWEEP_TRACKS.md](SUBTITLE_SWEEP_TRACKS.md) now
carries explicit logical row-group metadata from `SubtitleLayer`. Normal live
playback no longer reconstructs group boundaries from text; inference remains
only as a compatibility fallback.

Decorative subtitle sweeps now follow each displayed language phrase instead of
treating every wrapped QLabel row as an independent sweep.

For example, when two displayed languages each wrap to two physical rows, the
renderer owns two simultaneous sweep tracks. Each track traverses its first row
and then continues through the second row over the same cue duration. Particle
styles, the shuriken/comet/star trails and `erase_passed` all use the same track
plan, so hidden glyphs advance in the same order as the visible emitter.

The change is presentation-only:

- cue text, timing, IDs, saved subtitle data and language selection are unchanged;
- no timer, thread, decoder or word-timestamp inference was added;
- ambiguous/custom preview text falls back to the previous one-track-per-row
  behavior instead of guessing a language boundary;
- Unicode shaping and the existing grapheme/word regions stay unchanged;
- region and particle budgets remain bounded by the existing limits.

Live playback reconstructs the logical phrase groups from the active cue and
current subtitle mode. Video export snapshots the resulting row-group map on the
GUI thread. If export-only wrapping adds more rows, those rows inherit the same
logical phrase group, preserving the live sweep behavior in burn-in output.

Only `app/ui/subtitle_particles.py` and `app/ui/video_subtitle_export.py` change
production behavior. Exact before/after copies under `docs/subtitle-sweep-flow`
feed a new adapter before the frozen sweep manifests. The video-export contract
now peels only its own newer phase after the flow adapter, avoiding the circular
test-only fallback through the sweep contract. Older manifests are not recaptured.

Verification on the available machine used the existing project PySide6 package
with an independent Python 3.13 interpreter because the project venv points to a
missing Python 3.11 executable. `py_compile`, `git diff --check`, an offscreen
runtime probe for one- and two-language wrapped cues, four focused export tests,
and the frozen sweep/particle app-source manifests passed. The normal Python 3.11
full suite remains pending until that interpreter is restored.
