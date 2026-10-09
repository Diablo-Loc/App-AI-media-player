# Online translation single-pass stabilization

## Goal

Return online lyric translation to the simple behavior that produced the most stable results: one authoritative provider translation per normal batch, with the provider seeing the full batch context. The app no longer performs a second semantic-quality review that can rewrite a valid first answer.

## Production behavior

- A normal batch makes one translation request.
- The prompt is deliberately compact, close to the earlier successful flow: natural EN/VI, complete source meaning, soft length guidance, and no title/artist invention. No few-shot block is appended.
- Repeated refrains with extra source wording are handled by the provider in the same primary request. The app does not inspect the translated wording and trigger another quality pass.
- Very long lyrics keep the existing bounded 60-cue / 12,000-source-character batching so provider context/output limits remain controlled.
- An incomplete response may still receive the existing single same-provider missing-ID repair. This is format/completeness recovery only.
- 429/502/503/504 may still receive the existing single bounded retry. This is transport recovery only.
- Genius reference verification, provider/model selection, output budgets, parser, atomic apply, Local fallback, cue text/timing/schema, ASR, player, editor, audio and video ownership are unchanged.

## API-call effect

For a normal song that fits one batch and receives a complete successful response, request count is exactly one. Extra calls happen only for an incomplete provider response, a transient provider error, or additional batches required for an unusually large lyric job.

## Compatibility

The earlier semantic-review phase remains archived as history but is superseded in production. Exact source snapshots in `docs/translation-single-pass/` restore the last completed semantic-review state before older adapters run.

No build or commit is part of this phase.
