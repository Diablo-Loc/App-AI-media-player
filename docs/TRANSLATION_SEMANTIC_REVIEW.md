# Translation semantic near-repeat review

Date: 2026-10-06

This phase fixes a lyric-specific semantic omission where a later cue contains an earlier refrain plus additional source wording, but the online model copies the shorter refrain's English/Vietnamese translation unchanged and silently drops the added wording.

After a complete online batch is parsed, the app compares normalized source cues only within that batch. If a longer source contains a shorter source with at least two additional semantic characters and either the English or Vietnamese draft is identical, only the longer cue is flagged. The same online provider then receives one semantic-review request containing the full original batch as context, the flagged source rows, and their current drafts. The reviewed translation replaces only those flagged IDs when the review returns them completely.

This is not a generic second pass for every lyric: normal distinct translations remain one provider request. It targets a high-signal repeated-refrain omission pattern such as `全て繋げてく` followed later by a longer cue that starts with the same phrase but contains extra recognized words. The prompt also explicitly requires full-string comparison for repeated refrains.

The review does not change source cue text, ASR output, timings, padding, IDs, schema, Genius gates/request caps, provider/model/key/temperature, local NLLB, editor/save/player/audio/video/cache ownership. If semantic review itself is malformed or incomplete, the already complete first online draft is retained rather than partially mixing review output.
