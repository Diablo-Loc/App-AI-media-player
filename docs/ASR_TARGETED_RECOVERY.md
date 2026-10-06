# Targeted ASR recovery phase (2026-10-06)

This phase broadens the existing post-primary coverage check without changing the primary Whisper model, decode options, refinement profile, cue schema, timing ownership, translation, editor, player, audio, video, save or cache flows.

The old coverage path only retried uncovered regions of at least 4 seconds. The new audit can notice uncovered regions from 0.22 seconds, but a short region is retried only when local Silero VAD confirms at least 0.20 seconds of speech. When primary word timestamps are available, audit coverage uses the first/last recognized word span instead of display-padded cue timing, so a 50-80 ms presentation lead/tail cannot hide a real omitted prefix or suffix. Recovery may overlap that known presentation padding by at most the existing boundary tolerance; final cue timing ownership remains unchanged. Regions below the old 4-second gate use stricter local-ASR acceptance: mean word probability at least 0.58, average log probability at least -0.72, and no-speech probability at most 0.35. Long-gap recovery retains the preceding 0.35-second VAD selection and existing candidate thresholds.

Primary segments with clearly weak confidence may receive one bounded local verification. A retry can replace text only when its word/log-probability confidence is materially stronger, it aligns to the same primary span, and exactly one accepted cue owns that span. Only text is replaced; the accepted cue's start/end stay unchanged. Confident primary segments are not re-decoded. A weak segment without VAD speech is not rewritten.

Every local decode remains at most 12 seconds with the existing 2-second overlap. The additional retry budget scales gently by duration and is capped at 24 windows. A second round is reserved for still-uncovered voiced regions and never repeatedly rewrites low-confidence text. The three user-provided songs are regression samples only; no title, lyric text or timestamp is hard-coded into production.

Snapshots in `docs/asr-targeted-recovery/original` and `reviewed` preserve the exact before/after source. `tests/asr_targeted_recovery_contracts.py` peels this phase before older frozen source gates, so historical manifests are not recaptured.

Native fresh-ASR validation of the sample videos remains dependent on a working Python/faster-whisper runtime. No build or commit belongs to this phase unless separately requested.
