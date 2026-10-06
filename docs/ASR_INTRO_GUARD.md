# Conservative first-window ASR guard (2026-10-06)

This phase keeps the established full-song Whisper decode unchanged, including
`language=None`, `temperature=0.0`, `vad_filter=False`, word timestamps, beam
size and the existing primary prompt.  It adds an independent audit of only the
first ASR window because long instrumental intros can produce plausible text or
an unreliable first-window language decision.  The VAD probe may scan up to 60
seconds only to locate the first real voice; deletion candidates remain limited
to the first 30-second Whisper window.

Silero VAD is evidence only. A normal lyric cue is never deleted merely because
VAD reports no speech. Explicit credit/boilerplate already rejected by the lyric
policy may be removed when it lies wholly before the independently detected
first voice. Other pre-voice cues require two bounded no-prompt checks with
different context padding; both must fail to reproduce the cue before deletion.
A single retry miss, VAD failure or verification failure keeps the primary cue.
The verifier also uses
faster-whisper's native silence guards (`no_speech_threshold=0.60`,
`log_prob_threshold=-1.0`, `hallucination_silence_threshold=1.0`) so the
independent check is less likely to repeat a silence hallucination.  These
options are not enabled on the authoritative full-song decode.

The intro audit now keeps two VAD views.  The original sensitive map remains the
fail-open deletion guard, while faster-whisper's default VAD is positive onset
evidence.  If the sensitive map degenerates into almost continuous speech, an
isolated early default-VAD island followed by at least four seconds of silence
does not force the whole song to start there; the next confirmed vocal region
may own language/onset probing.  Default VAD alone still never deletes a lyric.

When the first 30-second Whisper window is demonstrably contaminated, the guard
may perform a bounded local reconciliation before normal refinement. The normal
path is unchanged. Reconciliation requires explicit credit/boilerplate evidence
continuing across a later confirmed vocal onset, or a first window dominated by
explicit credit material. Repetition by itself is never a deletion trigger
because repeated refrains and chants are valid lyrics. It then uses overlapping fixed-language,
no-prompt local decodes and accepts the repair only when the onset passes agree,
the 20-32 second seam pass agrees with them, confidence is adequate, and local
segments are backed by speech.  The early onset pass owns natural phrase
boundaries; the seam pass owns the 30-second boundary.  Overlapping seam words
already covered by the onset pass are removed using word timestamps, preventing
duplicate text. Accepted local recovery is primary-first: it may remove only
explicitly suspicious credit/repeated material and may fill uncovered time, but
it cannot replace an unrelated primary cue just because the crop produced
different wording or line boundaries. Any disagreement, decode error or
insufficient coverage keeps the primary result unchanged.

For a VAD-degenerate intro that is nevertheless dominated by explicit
credit-like ASR, a fallback uses two bounded 10-24/12-26 second onset windows
plus the same 20-32 second seam window.  The earliest output segment must be
supported by the overlapping verifier.  This catches instrumental intros where
both sensitive and default VAD treat music as speech, without turning global VAD
on or changing recognition for ordinary songs.

Language is reconsidered only when the first detected voice is at least four
seconds into the file, the primary language probability is below 0.60, and a
short probe around real voice identifies a different language with probability
at least 0.80 and the required confidence gain.  Only that rare case permits
one full-song rerun with the corrected language while retaining the established
primary decode options.  An empty corrective rerun is rejected and the original
primary result is kept.  The language probe remains one contiguous decode but
stops after the last VAD-backed speech span inside its nine-second budget,
instead of always feeding trailing instrumental audio.  `faster-whisper 1.0.2`
performs language detection before returning `TranscriptionInfo`, so the
language probe does not need to consume or display decoded probe text.

If language correction comes from later-window consensus instead of the first
vocal probe, real default-VAD-backed first-window primary cues are retained
before the corrected-language rerun owns the remainder of the song. This keeps
count-ins, spoken intros and legitimate code-switching from disappearing merely
because the main song language is different. Credit/boilerplate, weak silence
hypotheses and unvoiced intro text are not preserved by this merge.

The guard does not enable global VAD, alter refinement/grouping/timing, change
cue schema/IDs, or touch translation, Genius, editor, save, player, audio,
video or cache owners.  Exact source snapshots are stored in
`docs/asr-intro-guard`; `tests/asr_intro_guard_contracts.py` peels this phase
before older frozen gates.  No build or commit belongs to this phase unless
separately requested.

Native regression probes on 2026-10-06 used the bundled large-v3 CUDA model.
`This Night, Lanterns and the Moon` moved from a saved first cue at 19.95s with
the 27.7-30.8 phrase split across the Whisper seam to a first recovered cue at
16.706s and one 27.71-30.88 cue.  Coverage retries dropped from eight to six in
that production probe.  `Hanaori-san ... Very good encount` no longer emitted
the repeated `歌初音ミク` first-window hallucination and recovered lyrics from
11.13s.  `From the Heart, Dare the Heavens` retained its evidence-backed onset
near 21.17s.  `Brand New Sky` exercised the normal no-reconciliation path.
