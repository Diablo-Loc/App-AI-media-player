# Playback continuity resource fix — 05/10/2026

The native system-media bridge used to copy every PCM callback into a NumPy
array and queue it back to the Qt GUI thread. The only application receiver,
`MainWindow.process_realtime_audio()`, is currently a no-op, so those copies and
queued events had no visible or audible consumer.

PCM delivery is now opt-in. The native callback remains registered and the
SMTC/media-key engine remains owned exactly as before, but normal playback
returns from the PCM callback before dereferencing or copying the buffer.
NumPy is imported lazily only if a future real consumer explicitly calls
`set_audio_capture_enabled(True)`. The existing two-buffer queue and copy path
remain available in that opt-in mode.

This change does not alter QMediaPlayer, QAudioOutput, media source, subtitle
timing/text, audio profiles, gain, EQ filters, cache keys, playlist order, saved
settings, video export, or the native engine ABI. It removes unused Python/GIL,
memory-copy and Qt-dispatch work from continuous playback.

Focused regression tests verify that the default callback does not touch even a
null buffer pointer and that explicit capture still performs one bounded copy
and one queued dispatch. The exact before/after source is archived under
`docs/playback-continuity`; older audio manifests remain frozen.

Export ownership was audited with this playback pass. Video export snapshots
the current display-ready subtitle text/style/effect/position and therefore
burns those subtitle pixels into the re-encoded video by design. Its media
source remains the selected item's original path, not the temporary EQ audio
cache currently used by playback. Compatible audio is stream-copied; otherwise
the existing AAC 320 kbit/s fallback remains. Playback normalization/EQ is not
baked into exported audio.

Audio EQ preparation and next-track prefetch remain background-only: their
FFmpeg work is below-normal priority on Windows and limited to one worker with
one filter thread. Prefetch may still consume some CPU/disk while enabled, but
it does not alter the current player source. No policy/default was changed in
this pass without evidence that prefetch caused the reported dropout.

The subtitle painter was profiled again rather than changed speculatively. The
existing bounded sprite/layout cache remains materially faster for the active
JP+EN+VI burst/shuriken configuration; a probe after warm-up rendered at about
0.46 ms/frame, while bypassing the sprite cache was roughly 100 ms/frame. The
existing 33 ms timer, bounded particles/regions and media-clock guards therefore
remain unchanged. Historical cold-glyph probes can still show a one-frame
cache-creation spike, so native screen FPS remains a separate validation item.

The project Python 3.11 interpreter is currently missing. Verification therefore
uses the available Python 3.13 runtime with the project's PySide6 package where
possible. Tests importing the venv's NumPy 1.24.3 binary cannot run under 3.13;
that environment limitation is kept separate from application failures.
