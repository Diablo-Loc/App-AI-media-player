# Online translation authority

Date: 2026-10-06

When the user selects an online translation model, that model is allowed to use the complete supplied song/batch context, song title and language knowledge to repair likely ASR mistakes even when Genius is disabled. A same-ID verified Genius hint remains strong evidence, not a prerequisite for correction.

The model must translate the complete intended cue. It may not keep only the understandable prefix of an odd ASR line. If an uncertain fragment cannot be confidently repaired from context, it must remain represented in the translation rather than being silently dropped. Cue IDs, source text and timings remain unchanged.

Normal successful batches still use one provider request. If a provider response omits cue IDs, the same online provider gets one bounded repair pass containing only the missing cue rows plus the original batch as context-only text. Results remain atomic: nothing is applied until the full batch is complete. This repair pass supersedes the earlier immediate Local fallback for this specific incomplete-output case. Existing transient HTTP/SDK retry rules remain unchanged.

Gemini's output allowance is raised to 16,384 tokens and Claude's to 8,192 tokens to reduce truncation on full-song translation. Provider/model/key/temperature selection, Genius search/ranking/confidence/request caps, ASR, timing, schema, NLLB implementation, editor/save/player/audio/video/cache owners remain otherwise unchanged.
