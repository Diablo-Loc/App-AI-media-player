# Online lyric prompt-engineering pass

Date: 2026-10-06.

## Goal

Improve real online lyric translation quality without changing subtitle timing, ASR, Genius confidence policy, provider/model selection, parser/fallback behavior, saved data or request count.

## Prompt policy

The translator now follows a shorter explicit priority: preserve meaning first, natural lyric phrasing second, concise subtitle wording third. Each cue must stand on its own; neighboring cues may disambiguate only the current cue and may never donate meaning to it.

The prompt keeps the high-value fidelity rules—negation, modality, relationships, names, numbers, imagery and intentional repetition—but consolidates the previous long list of negative constraints into the rule that nothing unsupported may be added. This includes invented subjects, objects, causes, events, metaphors, emotions or certainty.

Three compact few-shot examples demonstrate:

- a normal non-English lyric line with natural EN/VI wording;
- source text already in English, where the English target is preserved rather than paraphrased for novelty;
- a short `La la la` ad-lib, which stays an ad-lib rather than being padded into a sentence.

The prompt also explicitly preserves short vocalizations/refrains and keeps bracketed non-speech markers as markers. When source text is already natural English or Vietnamese, the same-language target may be copied or lightly normalized. Vietnamese pronouns remain conservative when the relationship is implicit.

The previous `silently check` wording is replaced by a direct final-output rule: each line must keep the source meaning/certainty and contain no unsupported detail. No visible reasoning or second self-review request is added.

## Provider configuration

Temperature remains `0.2` for Gemini, Claude and legacy OpenAI Chat. Raising it to `0.3–0.4` was deliberately rejected for this app because the current quality problem is occasional semantic drift; extra sampling variance would work against the accuracy-first goal. OpenAI Responses keeps its existing payload for model compatibility.

Gemini now explicitly sets `max_output_tokens=8192`. The installed `google-genai` `GenerateContentConfig` supports this field. The cap is large enough for normal full-song cue batches while protecting against silent provider defaults; the existing completeness parser still rejects partial output and falls back safely.

## Compatibility

- Normal songs remain one online translation request. The later long-lyric phase may split only unusually large jobs into bounded requests while preserving global IDs and atomic fallback.
- Output remains `ID===English===Vietnamese`.
- JSONL cue input and duration-derived soft character ranges stay unchanged.
- No hard truncation or post-translation shortening is added.
- No ASR, cue text/timing/padding/IDs/schema, Genius search/ranking/gates, NLLB, provider/model/key, editor/save/player/audio/video ownership changes.

Exact snapshots are under `docs/lyric-prompt-engineering/`; its adapter restores the preceding translation-stability phase before historical gates.

## Verification boundary

Focused unit/source tests cover the three examples, compact cue/context rule, semantic-risk markers, conservative ASR/reference policy, low-variance provider settings, explicit Gemini output budget, parser compatibility and exact source restoration. Live A/B evaluation on several songs remains the final semantic-quality check because no deterministic unit test can prove subjective translation quality for every provider response.
