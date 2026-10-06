# Primary ASR hallucination guard (2026-10-06)

This phase addresses subtitle text that exists on the timeline but is unrelated boilerplate or a decoder artifact, especially near song intros. It does not add a second full-song ASR pass and does not blacklist ordinary lyric words such as `hello`/`xin chao` that can be genuine lyrics.

The primary and CPU-fallback Whisper paths now use `initial_prompt=None`. The previous literal `" .+"` value was plain prompt text, not a regular expression, and had no useful lyric semantics. Model, language auto-detection, beam size, temperature, word timestamps, VAD policy and all other primary decode options stay unchanged.

Explicit credit/boilerplate already rejected by lyric refinement (for example `Subtitles by`, `Captioned by`, `Thanks for watching`, credit labels and known captured credit templates) no longer counts as acoustic coverage. Therefore a rejected fake intro cannot hide the same time span from targeted recovery. Recovery still requires the existing Silero speech gate and confidence thresholds, so removing a credit span from coverage does not itself create a subtitle.

Arbitrary high-confidence ASR hallucinations cannot be proven wrong without independent evidence. The existing targeted-recovery phase still verifies weak-confidence primary segments locally. This phase intentionally avoids deleting generic greetings or common lyric vocabulary just because those strings are frequent hallucinations.

Exact before/after snapshots live in `docs/asr-hallucination-guard`. The phase is peeled before `ASR_TARGETED_RECOVERY` and all older historical source gates. Translation, Genius, cue schema/IDs/timing, editor/save/player/audio/video/cache owners are unchanged. No commit/build unless requested.
