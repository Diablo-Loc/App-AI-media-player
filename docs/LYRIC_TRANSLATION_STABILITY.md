# Lyric translation stability pass

Date: 2026-10-06.

## Goal

Reduce cases where online lyric translation sounds attractive but drifts from the recognized lyric. Keep the existing natural lyric style, cue-length readability guidance, provider/model selector, Genius verification, parser and fallback flow.

## Policy

- Semantic fidelity is the first priority; natural lyric wording is second.
- Preserve negation, modality, relationships, names, numbers, imagery and intentional repetition before style or brevity.
- Do not infer a missing subject/object, relationship, cause, event, metaphor, emotion or certainty from the song title or neighboring cues.
- Song title and surrounding cues are disambiguation context only.
- Ambiguous ASR is not silently repaired. A correction is allowed only when context is unambiguous or a verified Genius hint for the same cue ID clearly supports it.
- A verified Genius hint stays cue-local and cannot rewrite another cue.
- Character budgets remain soft; a line may exceed them when shortening would alter meaning.
- Vietnamese stays fluent and contemporary without inventing pronouns or relationships. English remains idiomatic without supplying omitted facts.

## Sampling stability

Gemini, Claude and legacy OpenAI Chat translation requests now use temperature `0.2`. OpenAI Responses requests retain their existing payload because temperature support differs by model/API path. No provider, model selection, API key, timeout, parser, fallback or request-count behavior changes.

## Compatibility

- No cue text, timing, padding, IDs or subtitle schema changes.
- No ASR parameters or retry behavior changes.
- No Genius search/ranking/confidence threshold changes.
- No local NLLB behavior changes.
- No extra cloud request is added.
- Existing translation output remains `ID===English===Vietnamese` and the same completeness/duplicate-ID parser owns acceptance.

Exact phase snapshots are under `docs/lyric-translation-stability/`. A missing historical adapter for the earlier `gemini-3-flash-preview` to `gemini-2.5-flash` compatibility change is documented separately under `docs/gemini-default-compat/`; historical manifests themselves remain frozen.

## Verification boundary

Focused lyric/Genius/model tests and the current UI baseline source gate pass after restoring the exact historical phase order. An initial full-suite run on 2026-10-06, before repairing the missing historical Gemini-default adapter, ran 474 tests with 15 failures and 11 historical skips; focused reruns then cleared the translation/UI-baseline failures, while an unrelated `subtitle_effects.py` resource snapshot mismatch remained. Live API A/B comparison on several real songs is still the final semantic-quality check because unit tests cannot prove translation quality for every model response.
