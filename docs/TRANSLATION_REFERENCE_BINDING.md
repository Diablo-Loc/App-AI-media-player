# Translation verified-reference binding

Date: 2026-10-06

This phase fixes a failure where an online translator could silently drop an odd ASR fragment instead of preserving its meaning or using a verified Genius correction.

Verified Genius hints remain subject to the existing whole-song and cue-local confidence gates. When a hint is available, it is now embedded as `verified_reference` in the exact JSONL row for that global cue ID. The translator may use it only to repair recognition corruption that the same cue reference clearly resolves. Unmatched source meaning must still be preserved, and reference wording may never move across cue IDs.

When no verified reference exists, suspicious or ungrammatical ASR wording is translated conservatively instead of being deleted or silently rewritten. This avoids hiding source content while also avoiding unsupported guesses.

The change does not mutate source cue text, timings, padding, IDs, schemas, saved subtitles or ASR output. It adds no Genius/provider request, does not loosen Genius matching thresholds, and does not change provider/model/key/temperature, batching, parser/fallback, NLLB, editor/save/player/audio/video/cache ownership.

Exact original/reviewed snapshots and `tests/translation_reference_binding_contracts.py` preserve the historical source-gate chain.
