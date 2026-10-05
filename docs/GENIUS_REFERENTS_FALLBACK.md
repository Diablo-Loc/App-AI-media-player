# Genius referents fallback

Date: 2026-10-06.

## Problem

Genius search can succeed while `lyricsgenius.Genius.lyrics()` returns no lyrics. A live check of the reported `Brand New Sky` page returned Genius' Cloudflare human-verification page to a non-browser request, so retrying the same page with another HTML parser is not a reliable fix.

## Behavior

The existing Genius search, ranking and confidence policy stays intact.

1. Try the selected Genius lyric URL normally through LyricsGenius.
2. If the page is empty or the scraper raises, and the search hit has a song ID, spend the one remaining bounded reference-fetch attempt on `Genius.referents(..., per_page=50, text_format="plain")`.
3. Keep only lyric referent fragments; drop description referents, duplicates, section-only rows and malformed entries. Bound the extracted reference to 50 referents / 12,000 characters.
4. Run the unchanged whole-song ASR confidence gate (`score >= 0.42` and `sequence_coverage >= 0.20`).
5. Run the unchanged cue-local hint gate before any fragment reaches the translation prompt.
6. If either validation fails, continue the normal one-request online translation using ASR only.

This fallback does not try to bypass Cloudflare, does not use Client Secret/OAuth, does not add a translation-provider call, and does not send full Genius lyrics to the translator.

## Request and compatibility bounds

- Genius searches remain at most 2.
- Reference retrieval attempts remain at most 2 total. A failed/empty page scrape plus one referents request consumes the full budget for that attempt.
- Translation-provider calls remain 1.
- Existing metadata score and whole-song/cue confidence thresholds are unchanged.
- Cue text/timing/padding/IDs/schema, ASR, provider/model/key behavior, local NLLB, editor/save/player/audio/video and cache owners are unchanged.
- Failure remains fail-safe: no usable Genius reference means normal ASR-based translation.

The exact snapshots under `docs/genius-referents-fallback/` restore the immediately preceding Genius state before historical source gates. Historical manifests are not recaptured.

## Verification limits

The local project venv still points at a missing Python 3.11 installation, so focused Python tests may be source-reviewed but cannot be executed until that interpreter is repaired. Live Genius referent coverage varies by song because only annotated fragments are returned; this phase improves graceful recovery and does not claim Genius can supply complete lyrics for every track.
