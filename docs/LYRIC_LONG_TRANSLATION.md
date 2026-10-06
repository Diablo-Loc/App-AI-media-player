# Long-lyric online translation batching

Date: 2026-10-06.

## Goal

Keep the accuracy-first prompt stable for normal songs while preventing unusually long lyrics from depending on one provider request fitting every model's input/output limits.

## Policy

- Normal lyrics that fit the bounded batch policy still use one translation request.
- Large jobs are split only when needed: at most 60 non-empty cues or 12,000 source characters per batch.
- Cue IDs remain the original global IDs, so timing, ordering and schema are unchanged.
- Each batch receives only Genius references whose verified cue IDs belong to that batch.
- The immediately previous and next non-empty cue are supplied as context-only text at batch boundaries. They are explicitly excluded from translation/output.
- A batch response may contain only IDs requested by that batch. Duplicates, foreign IDs, blanks or missing requested IDs fail the whole online translation.
- Results are accumulated in memory and are written to subtitle objects only after every batch succeeds. A failure in any batch leaves the whole song untouched so the existing fallback can own recovery.
- Gemini client setup is reused across batches; no additional title/Genius/model-cleaning request is introduced.

The batching limits are deliberately conservative rather than provider-specific. They keep expected EN+VI output comfortably below the existing Claude 4096-token cap in ordinary lyric-length cues while leaving Gemini's explicit 8192 output cap available. A pathological single cue larger than the input budget is not split because splitting cue text would change the cue contract; if a provider rejects that cue, the existing fallback remains the safe behavior.

## Prompt size

The fixed system prompt remains the prompt-engineering version: 334 whitespace-separated words in the measured no-title/no-reference form. Long lyrics do not make the system prompt larger; only the bounded batch user content changes. Repeating the fixed prompt across multiple long-song batches costs some tokens but avoids sending an ever-growing instruction block or losing fidelity rules.

## Compatibility

- No cue text, timing, padding, IDs, saved schema or export behavior changes.
- No ASR, local NLLB, Genius search/ranking/confidence threshold, provider/model/key selection or parser fallback ownership changes.
- Normal songs preserve the single-request path.
- Only unusually large jobs may use multiple translation-provider requests, one per bounded batch.

Exact source snapshots are under `docs/lyric-long-translation/`; the adapter restores the preceding prompt-engineering phase before historical gates.

## Verification boundary

Focused tests cover count/character partitioning, global IDs, context-only boundaries, a 121-cue three-batch successful merge and a failed middle batch that leaves all subtitle objects unmodified. Provider service limits can still change externally, so no implementation can guarantee every future model/account/lyric size; this phase fails safely when a provider rejects a bounded request.
