# ASR metadata-credit hallucination guard (2026-10-06)

Whisper can emit plausible-looking production credits during instrumental or difficult vocal regions. Examples include role/name bylines (`作词`, `作曲`, `编曲`, `制作人`, `混音`) and runaway repetitions such as many consecutive `混音` tokens. Those strings are not evidence that the corresponding audio span contains valid lyrics.

`credit_text()` now recognizes the *role structure*, not any song-specific artist/title/timestamp. Repeated CJK production-role labels are rejected. A single leading CJK production role is rejected only when the remaining text is a short, non-sentence-like byline; sentence-like lyric text containing words such as `制作人` or `作曲` is retained. Explicit English production bylines such as `Produced by ...` and `Mixed by ...` are also rejected.

The same predicate is already used by lyric refinement and primary acoustic coverage. Therefore metadata hallucinations are removed from displayed source lyrics and do not claim coverage; the existing bounded Silero-VAD/confidence recovery can inspect those spans again. Local recovery still has to pass the existing speech/confidence/refinement gates, so filtering metadata does not automatically create replacement text.

This phase does not alter the Whisper model, language auto-detection, `initial_prompt=None`, beam/temperature, full-song decode count, recovery windows/budget, cue timing/schema, translation, Genius, editor/save/player/audio/video/cache flows. No song name or timestamp is hard-coded.
