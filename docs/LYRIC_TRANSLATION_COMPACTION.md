# Commercial lyric translation shaping

Date: 2026-10-05.

## Goal

Online translation already produced semantically strong English/Vietnamese text, but some lines were too prose-like for lyric display. This phase makes online API translations more compact without hard-truncating text, changing cue timing, or adding a second API request.

## Policy

- Applies only to online translation through the existing Gemini, Claude and OpenAI path.
- Every non-empty cue receives a duration-derived **soft** preferred character range for English and Vietnamese.
- The model is told to preserve meaning, emotional tone, imagery, negation, modality, relationships, names, numbers and meaningful repetition.
- Each cue remains one-to-one with its original ID. Context from surrounding cues may resolve ambiguity but must not move meaning between cues.
- The model may exceed the preferred range when shortening would omit, weaken or change meaning.
- The model is explicitly told not to make naturally short lines longer and not to make a line unnaturally terse just to hit a lower bound.
- Vietnamese may omit a pronoun only when the source leaves it implicit and the relationship stays unambiguous. English should avoid adding subjects/explanations absent from the source.
- Intentional refrains/repeated lyric words stay intact.
- No post-translation substring cut, ellipsis insertion, token deletion or second "shorten" API pass is used.

## Readability budget

`translate.lyric_translation` calculates the preferred range from actual cue duration. English targets roughly 16 characters/second with a 24-58 preferred maximum; Vietnamese roughly 17 characters/second with a 26-62 preferred maximum. The lower edge is 55% of that preferred maximum. These numbers are guidance for the model, not validators or clipping thresholds.

Both production `Subtitle(start/end)` and editor-worker `DummySub(start_ms/end_ms)` timing are supported. Invalid/zero duration uses a 2.5 second fallback. Empty cues are omitted from the API request while preserving their original IDs for all non-empty rows.

## Request format and compatibility

Input cues are JSONL with ID, duration, EN/VI preferred ranges and source text. This avoids collisions with the existing `===` output delimiter. Output remains exactly `ID===EN===VI`, so the existing completeness/duplicate-ID parser, fallback behavior, subtitle objects and editor/save path stay unchanged.

The same single request is used for Gemini, Claude and OpenAI. Genius reference lyrics, when enabled, remain context for correcting recognition mistakes before translation.

The only existing production module changed is `app/translate/online_logic.py`; the shaping policy lives in the new pure helper `app/translate/lyric_translation.py`. Historical source manifests are frozen and the new adapter restores the pre-phase online translation source before older gates.

## Verification boundary

Focused tests cover seconds/milliseconds timing, bounded monotonic budgets, Unicode/JSONL/empty-cue handling, semantic-fidelity prompt requirements and exact source restoration. The project Python 3.11 executable is currently missing on this machine, so those tests cannot be executed in this pass. `git diff --check`, source hashes and static inspection remain available; live API A/B evaluation on real songs is still the final quality check because semantic quality cannot be proven by unit tests alone.
