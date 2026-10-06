"""Lightweight lyric policy for new generation; no audio decoding or retries."""
import re
import unicodedata

_CREDIT_PHRASES = (
    "thanks for watching", "thank you for watching", "subtitles by",
    "captioned by", "translated by", "corrected by", "synced by", "subs by",
    "all rights reserved", "resemblance to actual persons", "work of fiction",
    "ご視聴ありがとうございました", "視聴ありがとうございました", "チャンネル登録",
    "高評価をお願い", "ご覧いただきありがとうございます", "시청해주셔서 감사합니다",
    "구독과 좋아요", "한글자막 by", "자막 제작", "다음 영상에서 만나요",
)
_EXPLICIT_CREDIT = re.compile(r"\b(?:please subscribe|amara\.org)\b")
_CREDIT_LABEL = re.compile(r"^(?:lyrics?|music|copyright|subtitles?|作詞|作曲|編曲|歌詞)\s*[:：]")
_COMBINED_JP_LABEL = re.compile(r"^(?:作詞|作曲|編曲)(?:\s*[・/、&]\s*(?:作詞|作曲|編曲))+")
_SPACES = re.compile(r"\s+")
_COMPACT = re.compile(r"[\W_]+")
_CREDIT_BRANDS = ("soundhodori", "사운드호돌이", "サウンドゥホドリ")


def primary_options():
    """Match the established primary decode, also when CUDA falls back to CPU."""
    return dict(language=None, word_timestamps=True, condition_on_previous_text=False,
                beam_size=3, temperature=0.0, vad_filter=False,
                vad_parameters=dict(min_silence_duration_ms=1000), initial_prompt=None)


def credit_text(text, timed_words=False):
    """Recognize explicit credit boilerplate, not ordinary lyric vocabulary.

    Generic words such as tiger/fiction/Instagram/copyright/音楽/歌詞 may be lyrics.
    Preserve the old weak short-text fallback when ASR supplied no word times.
    No filter can distinguish every spoken/sung credit from hallucination.
    """
    normalized = _SPACES.sub(" ", unicodedata.normalize("NFKC", text).casefold().strip())
    if any(phrase in normalized for phrase in _CREDIT_PHRASES):
        return True
    if _EXPLICIT_CREDIT.search(normalized):
        return True
    if _CREDIT_LABEL.match(normalized) or _COMBINED_JP_LABEL.match(normalized):
        return True
    # Keep known multilingual/social credit templates out. Blocking a bare
    # generic 'tiger' or 'Instagram' would also erase unrelated real lyrics.
    compact = _COMPACT.sub("", normalized)
    if sum(brand in compact for brand in _CREDIT_BRANDS) >= 2 or compact in _CREDIT_BRANDS:
        return True
    if compact == "instagramtwitterホドリ":
        return True
    if not timed_words:
        if normalized.rstrip(".!。！ ") in {"bgm", "subtitles", "music"}:
            return True
        if len(normalized) < 15 and any(word in normalized for word in
                                         ("peace.", "bye.", "watching.", "you.")):
            return True
    return False
