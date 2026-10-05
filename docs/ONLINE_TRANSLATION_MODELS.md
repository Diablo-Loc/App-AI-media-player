# Online lyric polish and translation model selection

Date: 2026-10-05.

## Goal

Make the online translation less rigid and more lyric-like, then expose a provider-aware translation-model selector in Settings without changing subtitle timing, source text, Genius matching, parser/fallback semantics, or local NLLB behavior.

## Lyric wording policy

The existing duration budget remains a soft readability guide. It is loosened slightly:

- English: about 17.5 characters/second, preferred maximum 26–64 characters.
- Vietnamese: about 18.5 characters/second, preferred maximum 28–68 characters.
- The lower preferred edge is 50% of the upper target.

The prompt now favors fluent lyric language, rhythm, emotional color and idiomatic target-language wording. It explicitly avoids mechanical word-for-word translation and allows a modest poetic turn only when the source directly supports it. Meaning, negation, modality, names, relationships, imagery and intentional repetition still take priority. Budgets remain soft; there is no truncation or second shortening request.

## Model selector

Settings adds `translation_model`, populated from `translate.translation_models` according to the existing provider value.

- Google Gemini: `gemini-2.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.5-flash`, `gemini-3.8-flash`.
- OpenAI: `gpt-4o-mini`, `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`.
- Claude: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-sonnet-5`, `claude-sonnet-5-5`.
- Local Default: selector is disabled and local NLLB remains unchanged.

Existing Gemini and OpenAI users without the new preference keep `gemini-2.5-flash` and `gpt-4o-mini`. Claude's old hard-coded `claude-3-5-sonnet-20240620` is retired, so a missing/invalid Claude model safely resolves to active `claude-sonnet-4-6`.

New GPT-5.6 choices use OpenAI's Responses API. The existing `gpt-4o-mini` path retains Chat Completions and its temperature setting, so the legacy behavior is still available. Gemini continues through `google-genai.generate_content`; Claude continues through `/v1/messages`.

## Genius interaction

The preceding verified-reference Genius flow is unchanged. Genius runs before translation model selection, checks at most two lyric candidates against ASR, and supplies only strong cue-local hints. Whichever translation model the user selects receives the same verified hint block. If Genius is uncertain, the translation request receives no Genius reference.

## Compatibility

- No cue timing, padding, IDs or subtitle schema change.
- No ASR/model-generation settings change.
- No local NLLB model or fallback-order change.
- No Genius token/setting or confidence-policy change.
- No extra translation request is added.
- Provider model choice is validated against its own catalog; stale/cross-provider values fall back safely.

Exact source snapshots for `online_logic.py` and `settings.py` are under `docs/online-translation-models/`. The adapter restores these two files before older frozen source gates.

## Verification boundary

Pure tests cover model catalogs, provider fallback, OpenAI Responses parsing, prompt looseness, setting persistence and source routing. The project venv still points to a missing Python 3.11 installation, so runtime unit/Qt tests cannot execute until that interpreter is repaired. Live provider quality/cost and account-specific model access remain external validation.
