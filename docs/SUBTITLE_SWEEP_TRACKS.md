# Explicit subtitle sweep tracks — 05/10/2026

The subtitle sweep now carries explicit logical phrase metadata from the point
where `SubtitleLayer` builds and wraps display text. Each physical QLabel row has
one integer group id. Rows with the same id belong to one logical displayed
phrase/language, so the particle emitter and `erase_passed` traverse those rows
sequentially over the cue duration.

This removes the main ambiguity in the preceding sweep-flow fix. Normal live
playback no longer has to reconstruct language boundaries by comparing wrapped
text with `orig/en/vi`. The text-reconstruction helper remains only as a
compatibility fallback for custom/test labels that do not expose explicit row
groups.

The plan is count-independent. Current modes still use the existing `jp`, `en`
and `vi` behavior, including the English-to-original fallback and duplicate
suppression. Future modes may expose `display_language_keys`, or use mode value
tokens that match cue language keys. Three displayed phrases therefore produce
three simultaneous tracks, six produce six tracks, and each track may contain
one or many wrapped rows. Adding another language does not require a change in
the particle/sweep renderer.

The change is presentation-only. Cue text/timing/IDs, stored subtitle schema,
ASR, translation, media clock, fade, player ownership, Unicode shaping and the
existing word/grapheme regions are unchanged. `build_text()` remains the public
text API and delegates to `build_text_plan()`, which returns the same text plus
row-group metadata. Loading a new subtitle source clears only this transient
metadata.

Video export calls the same display plan on the GUI thread and stores the group
tuple in each `ExportCue`. Export-only safe-area wrapping propagates the source
row group to every newly wrapped row, so live playback and burn-in export follow
the same logical tracks.

Resource bounds remain unchanged: text regions stay under the existing
`MAX_REGIONS` limit and decorative marks keep the existing 8/16/24 total particle
budget. Very large or custom inputs degrade through the established bounded
fallback rather than allocating a timer, worker or object per language/word.

Verification completed with `py_compile` and a Qt offscreen production probe.
The probe compared `build_text()` for every current `SubtitleMode` against the
exact pre-phase `SubtitleLayer`, then verified a three-language cue wrapping to
six rows as `(0, 0, 1, 1, 2, 2)`, a future six-language display producing six
tracks, and export rewrapping to 24 rows while preserving exactly three logical
groups. The normal project Python 3.11 test suite is still pending because the
venv interpreter is missing; running the suite from the available Python 3.13
interpreter reaches the venv's Python-3.11 NumPy 1.24.3 binary and fails to load
`numpy.core._multiarray_umath` before the affected tests execute.

Exact before/after copies are stored under `docs/subtitle-sweep-tracks`. The new
adapter peels this phase before the preceding sweep-flow and historical source
gates; older manifests are not recaptured. No commit/build/dependency change is
part of this phase.
