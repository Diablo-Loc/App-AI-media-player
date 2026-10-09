# Lyric clause completeness

Date: 2026-10-06

This phase fixes online lyric translations that compress a multi-clause cue so aggressively that a later clause, qualifier, or logical relation disappears.

The translation prompt now makes semantic completeness the first priority. Every meaningful clause and relation such as contrast, cause, condition, concession, time, or sequence must remain in both English and Vietnamese. Character ranges remain soft display guidance and may be exceeded when a faithful translation needs more room.

The first compact example intentionally contains two clauses and exceeds its stated English soft budget. This demonstrates that a complete meaning is preferred over artificial shortening without adding another API call.

This phase changes only `app/translate/lyric_translation.py`. It does not change cue text, timing, padding, IDs, schemas, ASR, Genius search/ranking/confidence, provider/model/key selection, temperature, request counts, long-song batching, local NLLB, parsing/fallback, editor/save/player/audio/video/cache ownership, or persisted data.

Exact original/reviewed snapshots and `tests/lyric_clause_completeness_contracts.py` keep the historical source-gate chain intact.

Deterministic tests can prove the prompt and compatibility contracts, but live semantic quality across every provider/song still requires representative API A/B listening and reading.
