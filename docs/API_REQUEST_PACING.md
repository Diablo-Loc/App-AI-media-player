# Online API request pacing and transient retry

Date: 2026-10-06.

## Goal

Reduce avoidable burst traffic from Genius and multi-batch online translation without changing lyric quality, cue timing, ASR, Genius confidence rules or normal fallback behavior.

## Behavior

- Genius keeps the existing maximum search/retrieval counts. It does **not** gain an automatic retry. Existing Genius network calls are simply spaced by at least 0.40 seconds when they occur back-to-back.
- Long online translation batches wait 0.65 seconds before each batch after the first, so a long song no longer fires provider requests immediately one after another.
- Gemini SDK calls retry exactly once after 1.35 seconds only when the exception exposes transient status 429, 502, 503 or 504.
- Claude/OpenAI HTTP calls retry exactly once for the same transient status set. A numeric `Retry-After` header is respected and clamped to 0.25–4.0 seconds; otherwise the 1.35 second delay is used.
- Non-transient provider errors are not retried. A second transient failure leaves the existing outer fallback/error path in control.

This intentionally avoids exponential or unlimited retries. The objective is to absorb a brief provider overload/rate-limit condition without turning one user action into a retry storm.

## Compatibility

- No changes to prompt text, temperature, model selection, API keys, cue IDs/text/timing/schema, Genius ranking/confidence thresholds, local NLLB, save/editor/player/audio/video/cache owners.
- Normal one-batch translation pays no inter-batch delay.
- Genius request-count caps remain unchanged.
- Long-lyric atomic apply/fallback remains unchanged.

Exact source snapshots are under `docs/api-request-pacing/`; its adapter restores the preceding long-lyric source before historical source gates.
