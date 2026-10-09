"""Conservative Genius reference matching for online lyric translation.

Genius is treated as an optional reference source.  Nothing from Genius is
trusted until it matches the already accepted ASR text strongly enough, and
only cue-local hints are exposed to the translation prompt.
"""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re
import unicodedata


_SPACE_RE = re.compile(r"\s+")
_MEDIA_EXT_RE = re.compile(r"\.(?:mp3|m4a|aac|flac|wav|ogg|opus|mp4|mkv|webm|mov|avi)$", re.IGNORECASE)
_TRACK_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-._)]\s*")
_BRACKET_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")
_NOISE_BRACKET_TOKENS = {
    "official", "mv", "pv", "lyric", "lyrics", "audio", "amv", "4k", "hd", "visualizer", "karaoke"
}
_SECTION_RE = re.compile(r"^\s*\[[^\]]{1,80}\]\s*$")
_EMBED_RE = re.compile(r"\s*\d*Embed\s*$", re.IGNORECASE)
_HEADER_RE = re.compile(r"^\s*\d*\s*Contributors?.*?Lyrics\s*$", re.IGNORECASE)

_VERSION_MARKERS = (
    "romanized",
    "translation",
    "english translation",
    "live",
    "remix",
    "cover",
    "instrumental",
    "karaoke",
)


def clean_search_title(raw_title: str) -> str:
    """Remove common filename/video noise without guessing artist or title."""
    text = unicodedata.normalize("NFKC", str(raw_title or "")).strip()
    text = _MEDIA_EXT_RE.sub("", text)
    text = _TRACK_PREFIX_RE.sub("", text)
    text = text.replace("_", " ")

    def remove_noise_bracket(match: re.Match) -> str:
        value = match.group(0).casefold()
        tokens = set(re.findall(r"[a-z0-9]+", value))
        noisy = bool(tokens & _NOISE_BRACKET_TOKENS) or "music video" in value
        return " " if noisy else match.group(0)

    text = _BRACKET_RE.sub(remove_noise_bracket, text)
    text = re.sub(r"\s+[-|]\s+(?:official\s*)?(?:music\s*)?(?:video|audio|lyrics?)\s*$", "", text, flags=re.IGNORECASE)
    return _SPACE_RE.sub(" ", text).strip(" -|")


def search_query_variants(raw_title: str) -> tuple[str, ...]:
    """Return at most two deterministic Genius queries; no cloud title cleanup."""
    cleaned = clean_search_title(raw_title)
    raw = _SPACE_RE.sub(" ", str(raw_title or "")).strip()
    variants: list[str] = []
    for value in (cleaned, raw):
        if value and value not in variants:
            variants.append(value)
    return tuple(variants[:2])


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def _token_set(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return set(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def extract_song_results(payload) -> list[dict]:
    """Normalize LyricsGenius search payloads to song dictionaries.

    Current LyricsGenius returns ``hits``; the legacy ``songs`` shape is kept
    as a compatibility fallback for callers/tests that captured older data.
    """
    if not isinstance(payload, dict):
        return []
    hits = payload.get("hits")
    if not isinstance(hits, list):
        hits = payload.get("songs")
    if not isinstance(hits, list):
        return []
    results: list[dict] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        result = hit.get("result", hit)
        if isinstance(result, dict):
            results.append(result)
    return results


def candidate_score(raw_title: str, result: dict, rank: int = 0) -> float:
    """Score a Genius search result using only local title/artist metadata."""
    query = clean_search_title(raw_title)
    title = str(result.get("title") or result.get("title_with_featured") or "")
    primary_artist = result.get("primary_artist")
    primary_name = primary_artist.get("name", "") if isinstance(primary_artist, dict) else ""
    artist = str(result.get("artist_names") or primary_name or "")
    full = str(result.get("full_title") or f"{title} {artist}")

    q_compact = normalize_for_match(query)
    title_compact = normalize_for_match(title)
    full_compact = normalize_for_match(full)
    if not q_compact or not title_compact:
        return 0.0

    full_ratio = SequenceMatcher(None, q_compact, full_compact, autojunk=False).ratio()
    title_ratio = SequenceMatcher(None, q_compact, title_compact, autojunk=False).ratio()
    containment = 1.0 if title_compact in q_compact or q_compact in full_compact else 0.0

    q_tokens = _token_set(query)
    c_tokens = _token_set(f"{title} {artist}")
    token_overlap = len(q_tokens & c_tokens) / max(1, len(c_tokens)) if c_tokens else 0.0

    score = 0.42 * full_ratio + 0.24 * title_ratio + 0.22 * containment + 0.12 * token_overlap
    score += max(0.0, 0.035 - 0.007 * max(0, rank))

    query_folded = unicodedata.normalize("NFKC", query).casefold()
    candidate_folded = unicodedata.normalize("NFKC", f"{title} {artist}").casefold()
    for marker in _VERSION_MARKERS:
        if marker in candidate_folded and marker not in query_folded:
            score -= 0.34 if marker in {"romanized", "translation", "english translation"} else 0.22
    if "genius english translations" in candidate_folded or "genius romanizations" in candidate_folded:
        score -= 0.45
    return max(0.0, min(1.0, score))


def rank_song_results(raw_title: str, results: list[dict]) -> list[tuple[float, dict]]:
    ranked = [(candidate_score(raw_title, result, rank), result) for rank, result in enumerate(results)]
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def clean_genius_lyrics(lyrics: str) -> str:
    """Remove Genius wrappers/headers while preserving real lyric wording."""
    text = unicodedata.normalize("NFKC", str(lyrics or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = _EMBED_RE.sub("", text).strip()
    kept: list[str] = []
    for raw_line in text.split("\n"):
        line = _SPACE_RE.sub(" ", raw_line).strip()
        if not line:
            continue
        if _SECTION_RE.fullmatch(line) or _HEADER_RE.fullmatch(line):
            continue
        if line.casefold() == "you might also like":
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def extract_referent_fragments(payload, *, max_referents: int = 50, max_chars: int = 12000) -> str:
    """Build a bounded lyric reference from Genius referent fragments.

    Genius' supported API does not expose full lyrics.  Referents do expose the
    exact lyric fragments that annotations attach to, so they are useful as a
    conservative fallback when the public song page is blocked by anti-bot
    protection.  Description referents and duplicate fragments are ignored.

    The returned text is still only a candidate: callers must run the existing
    whole-song ASR confidence gate before trusting it.
    """
    if not isinstance(payload, dict):
        return ""
    referents = payload.get("referents")
    if not isinstance(referents, list):
        return ""

    seen: set[str] = set()
    fragments: list[str] = []
    total_chars = 0
    limit = max(0, min(int(max_referents), 50))
    char_limit = max(0, int(max_chars))

    for referent in referents[:limit]:
        if not isinstance(referent, dict) or referent.get("is_description"):
            continue
        fragment = referent.get("fragment")
        if not fragment:
            range_data = referent.get("range")
            fragment = range_data.get("content") if isinstance(range_data, dict) else ""
        fragment = clean_genius_lyrics(str(fragment or ""))
        key = normalize_for_match(fragment)
        if len(key) < 3 or key in seen:
            continue
        if char_limit and total_chars + len(fragment) > char_limit:
            break
        seen.add(key)
        fragments.append(fragment)
        total_chars += len(fragment)

    return clean_genius_lyrics("\n".join(fragments))


def _char_ngrams(text: str, size: int = 2) -> Counter:
    if len(text) < size:
        return Counter({text: 1}) if text else Counter()
    return Counter(text[i:i + size] for i in range(len(text) - size + 1))


def _ngram_coverage(source: str, reference: str) -> float:
    source_grams = _char_ngrams(source)
    reference_grams = _char_ngrams(reference)
    total = sum(source_grams.values())
    if not total:
        return 0.0
    return sum((source_grams & reference_grams).values()) / total


def reference_match_metrics(asr_text: str, lyrics: str) -> dict[str, float]:
    """Measure whether fetched lyrics are plausibly the same song as the ASR."""
    source = normalize_for_match(asr_text)
    reference = normalize_for_match(lyrics)
    if len(source) < 16 or len(reference) < 16:
        return {"score": 0.0, "ngram_coverage": 0.0, "sequence_coverage": 0.0}

    matcher = SequenceMatcher(None, source, reference, autojunk=False)
    significant = sum(block.size for block in matcher.get_matching_blocks() if block.size >= 3)
    sequence_coverage = significant / max(1, len(source))
    ngram_coverage = _ngram_coverage(source, reference)
    score = 0.68 * ngram_coverage + 0.32 * sequence_coverage
    return {
        "score": max(0.0, min(1.0, score)),
        "ngram_coverage": ngram_coverage,
        "sequence_coverage": sequence_coverage,
    }


def reference_is_confident(asr_text: str, lyrics: str) -> bool:
    metrics = reference_match_metrics(asr_text, lyrics)
    return metrics["score"] >= 0.42 and metrics["sequence_coverage"] >= 0.20


def source_text_from_subs(subs) -> str:
    parts: list[str] = []
    for cue in subs or ():
        top = getattr(cue, "top", None)
        text = getattr(top, "text", "") if top is not None else ""
        text = _SPACE_RE.sub(" ", str(text or "")).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _line_similarity(source: str, reference: str) -> tuple[float, float, float]:
    a = normalize_for_match(source)
    b = normalize_for_match(reference)
    if len(a) < 3 or len(b) < 3:
        return 0.0, 0.0, 0.0
    ratio = SequenceMatcher(None, a, b, autojunk=False).ratio()
    coverage = _ngram_coverage(a, b)
    length_fit = min(len(a), len(b)) / max(len(a), len(b))
    score = 0.52 * ratio + 0.38 * coverage + 0.10 * length_fit
    return score, ratio, coverage


def build_reference_hints(subs, lyrics: str) -> dict[int, str]:
    """Align only high-confidence local lyric snippets to individual cue IDs."""
    lines = [line for line in clean_genius_lyrics(lyrics).splitlines() if normalize_for_match(line)]
    if not lines:
        return {}

    hints: dict[int, str] = {}
    cursor = 0
    for cue_id, cue in enumerate(subs or ()):
        top = getattr(cue, "top", None)
        source = getattr(top, "text", "") if top is not None else ""
        if len(normalize_for_match(source)) < 3:
            continue

        start_min = max(0, cursor - 2)
        end_max = min(len(lines), cursor + 18) if hints else len(lines)
        best: tuple[float, float, float, int, int, str] | None = None
        for start in range(start_min, end_max):
            for span in (1, 2):
                if start + span > len(lines):
                    continue
                reference = " ".join(lines[start:start + span])
                score, ratio, coverage = _line_similarity(source, reference)
                item = (score, ratio, coverage, start, span, reference)
                if best is None or item[0] > best[0]:
                    best = item

        if best is None:
            continue
        score, ratio, coverage, start, span, reference = best
        if score < 0.56 or (ratio < 0.50 and coverage < 0.45):
            continue
        if len(reference) > 180:
            continue
        hints[cue_id] = reference
        cursor = max(cursor, start + span)
    return hints
