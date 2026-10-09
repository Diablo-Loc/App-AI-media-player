# Genius reference optimization

Date: 2026-10-05.

## Goal

Keep Genius optional, but make enabling it useful and bounded. Genius is now a conservative reference source for the existing online translation request. It never becomes the authority for cue timing, IDs, saved subtitle schema, ASR, provider selection, or fallback.

## Problems in the preceding flow

1. `lyricsgenius.Genius.search_songs()` returns song results in `hits`; the old code looked for `songs`, so a valid search response could be ignored.
2. Enabling Genius called Gemini once only to clean the filename/title before the real translation request. That added cloud cost/latency and was provider-coupled even when the selected translation provider was Claude or OpenAI.
3. The old flow could fetch the first loosely plausible result and pass the entire remote lyric into the translation prompt. A wrong song/version or a Romanized/Translation page could bias every cue.
4. Fetching by song ID can require another song metadata request before LyricsGenius scrapes the lyric page. LyricsGenius supports fetching lyrics directly from the URL returned by search.
5. The whole lyric was sent to the translation provider even when only a few cues needed recognition help.

## New flow

`translate.genius_reference` is a local policy helper. The existing Genius setting/token remain unchanged.

1. Clean common filename/video noise deterministically. No AI/model call is used for title cleanup.
2. Search Genius with at most two deterministic query variants, five hits per search.
3. Rank returned `hits` locally by title/artist similarity. Penalize unrequested Romanized, Translation, Live, Remix, Cover, Instrumental and Karaoke variants.
4. Fetch lyrics directly from the result URL. At most two lyric candidates are fetched across the whole attempt.
5. Clean Genius wrappers/section headers without blindly deleting the first real lyric line.
6. Compare each candidate against the already accepted ASR using Unicode-normalized character bigram coverage plus sequence coverage. A weak whole-song match is discarded.
7. For a verified song, align cue text monotonically to one or two nearby lyric lines. Only strong cue-level matches become reference hints.
8. Send only those compact `ID -> verified reference` hints inside the existing single translation request. The full Genius lyric is not sent to Gemini/Claude/OpenAI.
9. If no candidate or cue passes confidence checks, online translation runs exactly as if Genius had provided no reference.

## Cost and behavior bounds

- Extra cloud translation-provider calls caused by Genius title cleanup: **0**.
- Normal online translation requests: **still 1**.
- Genius song searches: at most **2**.
- Genius lyric-page fetches: at most **2**.
- No extra model load, QThread, timer, decoder, FFmpeg process, dependency, or saved cache is added.
- No cue text, timing, padding, IDs, source ASR objects, middle/bottom schema, provider model, temperature, timeout, API key, parser, or local fallback is changed by the Genius helper.
- The production Gemini translation model present before this phase (`gemini-2.5-flash`) is preserved.

## Compatibility boundary

The implementation changes only `app/translate/online_logic.py` plus the new pure helper `app/translate/genius_reference.py`. Existing `translate.lyric_translation` shaping remains the same; Genius supplies a smaller verified reference block to that existing request builder.

The exact reviewed/source adapter under `docs/genius-reference/` covers the existing online module. The helper has focused deterministic tests for the current LyricsGenius `hits` response shape, title cleanup/ranking, wrong-song rejection, wrapper cleanup and monotonic cue hints.

## Verification limits

The project `venv` executable still points to a missing Python 3.11 installation, so Python unit tests cannot run in this environment until that interpreter is repaired. Source/hash/diff checks remain valid. Live Genius/API evaluation on a real song is still required to measure retrieval hit rate and translation quality; deterministic tests can prove rejection/mapping policy but cannot prove external catalog quality or network availability.
