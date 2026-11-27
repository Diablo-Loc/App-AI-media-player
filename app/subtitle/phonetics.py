"""Offline top-line lyric phonetics (Hepburn Romaji, Pinyin, Korean Revised Romanization).

Designed for 600+ existing saved songs as well as new songs:
- Runs 100% offline in RAM (< 3 ms per song) with zero API calls and zero disk mutations.
- Whole-song script detection prevents Kanji-only lines in Japanese songs (e.g. '運命')
  from being misread as Mandarin Pinyin, while suppressing redundant phonetic lines on
  pure Latin / English / Vietnamese lyrics even when the toggle is left ON.
"""
from __future__ import annotations

from collections import OrderedDict
import re
from typing import Iterable

_RE_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_RE_HANGUL = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")
_RE_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
_RE_NON_LATIN_LYRIC = re.compile(
    r"[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\uff66-\uff9f"
    r"\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f"
    r"\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]"
)
_RE_MULTI_SPACE = re.compile(r"\s+")
_RE_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?~…)\]\}”’»、。！？）」』】])")
_RE_SPACE_AFTER_OPEN = re.compile(r"([(\[\{“‘«（「『【])\s+")

_JA_PARTICLES_HIRA = frozenset({
    "は", "が", "を", "に", "へ", "と", "で", "の", "も", "や",
    "か", "ね", "よ", "な", "わ", "ぞ", "ぜ", "さ", "から", "まで",
    "より", "だけ", "ほど", "くらい", "ぐらい", "ばかり", "でも", "とか",
    "けれど", "けど", "のに", "ので", "なら", "たり", "だり",
})

_PUNCT_TRANSLATION = str.maketrans({
    "。": ".",
    "、": ",",
    "！": "!",
    "？": "?",
    "（": "(",
    "）": ")",
    "「": '"',
    "」": '"',
    "『": '"',
    "』": '"',
    "【": "[",
    "】": "]",
    "〜": "~",
    "～": "~",
    "・": " ",
    "　": " ",
})

# Korean Revised Romanization tables (Ministry of Culture, 2000)
_KO_CHOSEONG = (
    "g", "kk", "n", "d", "tt", "r", "m", "b", "pp",
    "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h",
)
_KO_JUNGSEONG = (
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o",
    "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu",
    "eu", "ui", "i",
)
_KO_JONGSEONG = (
    "", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m",
    "p", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng",
    "t", "t", "k", "t", "p", "t",
)

_KAKASI_INSTANCE = None
_PYPINYIN_BUNDLE = None
_LINE_CACHE: OrderedDict[tuple[str, str], str] = OrderedDict()
_MAX_LINE_CACHE = 4096


def _get_kakasi():
    global _KAKASI_INSTANCE
    if _KAKASI_INSTANCE is None:
        try:
            import pykakasi as _pykakasi
            _KAKASI_INSTANCE = _pykakasi.kakasi()
        except Exception:
            _KAKASI_INSTANCE = False
    return _KAKASI_INSTANCE if _KAKASI_INSTANCE else None


def _get_pypinyin():
    global _PYPINYIN_BUNDLE
    if _PYPINYIN_BUNDLE is None:
        try:
            from pypinyin import Style as _PinyinStyle, pinyin as _pypinyin_fn
            _PYPINYIN_BUNDLE = (_pypinyin_fn, _PinyinStyle)
        except Exception:
            _PYPINYIN_BUNDLE = False
    return _PYPINYIN_BUNDLE if _PYPINYIN_BUNDLE else (None, None)


def clear_phonetic_cache() -> None:
    """Clear the bounded RAM transliteration cache."""
    _LINE_CACHE.clear()


def has_non_latin_script(text: str) -> bool:
    """Return True only when the line contains Kana, Kanji/Hanzi, or Hangul characters."""
    if not text:
        return False
    return bool(_RE_NON_LATIN_LYRIC.search(text))


def detect_song_phonetic_script(cues: Iterable[dict] | None) -> str | None:
    """Infer a consistent phonetic target script ('ja', 'zh', 'ko', or None) across all cues.

    Rules:
    - Any Hiragana/Katakana in the song locks CJK lines to Japanese ('ja') so Kanji-only
      lines like '運命' or '永遠' become Hepburn Romaji ('unmei', 'eien') instead of Pinyin.
    - Dominant Hangul selects Korean ('ko').
    - CJK Hanzi with zero Kana across the song selects Mandarin Pinyin ('zh').
    - Pure Latin / English / Vietnamese / European songs return None (auto-suppressed).
    """
    if not cues:
        return None
    kana_count = 0
    hangul_count = 0
    cjk_count = 0
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        orig = str(cue.get("orig", "") or "")
        if not orig:
            continue
        kana_count += len(_RE_KANA.findall(orig))
        hangul_count += len(_RE_HANGUL.findall(orig))
        cjk_count += len(_RE_CJK.findall(orig))

    if kana_count == 0 and hangul_count == 0 and cjk_count == 0:
        return None
    if hangul_count > (kana_count + cjk_count):
        return "ko"
    if kana_count > 0:
        return "ja"
    if cjk_count > 0:
        return "zh"
    return None


def _detect_line_override_script(text: str, song_script: str | None) -> str | None:
    """Handle mixed-script edge cases while respecting the whole-song primary script."""
    if not text or not has_non_latin_script(text):
        return None
    if _RE_HANGUL.search(text) and not _RE_KANA.search(text) and not _RE_CJK.search(text):
        return "ko"
    if _RE_KANA.search(text):
        return "ja"
    if song_script in ("ja", "zh", "ko"):
        return song_script
    if _RE_HANGUL.search(text):
        return "ko"
    if _RE_CJK.search(text):
        return "zh"
    return None


def _clean_spacing(text: str) -> str:
    cleaned = text.translate(_PUNCT_TRANSLATION)
    cleaned = _RE_SPACE_BEFORE_PUNCT.sub(r"\1", cleaned)
    cleaned = _RE_SPACE_AFTER_OPEN.sub(r"\1", cleaned)
    cleaned = _RE_MULTI_SPACE.sub(" ", cleaned).strip()
    return cleaned


def _is_pure_hiragana(text: str) -> bool:
    return bool(text) and all("\u3040" <= ch <= "\u309f" or ch == "ー" for ch in text)


def _ends_with_hiragana(text: str) -> bool:
    return bool(text) and ("\u3040" <= text[-1] <= "\u309f")


def _romaji_ja(text: str) -> str:
    kakasi = _get_kakasi()
    if kakasi is None:
        return ""
    tokens = kakasi.convert(text)
    if not tokens:
        return ""

    pieces: list[str] = []
    prev_orig = ""
    for idx, tok in enumerate(tokens):
        orig = str(tok.get("orig", "") or "")
        hira = str(tok.get("hira", "") or "")
        rom = str(tok.get("hepburn", "") or "").strip()
        if not orig:
            continue
        if not rom:
            if orig.isspace() and pieces and not pieces[-1].endswith(" "):
                pieces.append(" ")
            prev_orig = orig
            continue

        # J-Pop lyric disambiguation: standalone pronoun '君' -> 'kimi' (not suffix '-kun')
        if orig == "君" and rom == "kun":
            prev_is_name_kanji = bool(prev_orig and _RE_CJK.search(prev_orig[-1]))
            if not prev_is_name_kanji:
                rom = "kimi"
        # Particle 'は' -> 'wa', 'へ' -> 'e', 'を' -> 'o' for natural sing-along pronunciation
        elif orig == "は" and rom == "ha" and idx > 0:
            rom = "wa"
        elif orig == "へ" and rom == "he" and idx > 0:
            rom = "e"
        elif orig == "を" and rom == "wo":
            rom = "o"

        rom_clean = rom.translate(_PUNCT_TRANSLATION).strip()
        if not rom_clean:
            prev_orig = orig
            continue

        # Attach conjugated verb/adjective okurigana suffixes (e.g. '駆け' + 'る' -> 'kakeru')
        attach_to_prev = False
        if pieces:
            last = pieces[-1]
            if last.endswith((" ", "(", "[", '"', "'")):
                attach_to_prev = True
            elif rom_clean[0] in ",.;:!?~…)]}\"'":
                attach_to_prev = True
            elif (
                _ends_with_hiragana(prev_orig)
                and _is_pure_hiragana(orig)
                and hira not in _JA_PARTICLES_HIRA
                and len(hira) <= 3
            ):
                attach_to_prev = True

        if attach_to_prev or not pieces:
            pieces.append(rom_clean)
        else:
            pieces.append(" " + rom_clean)
        prev_orig = orig

    return _clean_spacing("".join(pieces))


def _pinyin_zh(text: str) -> str:
    pypinyin_fn, pinyin_style = _get_pypinyin()
    if pypinyin_fn is None or pinyin_style is None:
        return ""
    # Pass non-CJK runs through intact while spacing syllables cleanly
    raw_items = pypinyin_fn(text, style=pinyin_style.TONE, errors="default", heteronym=False)
    pieces: list[str] = []
    for item in raw_items:
        syl = str(item[0] if item else "")
        if not syl:
            continue
        syl_norm = syl.translate(_PUNCT_TRANSLATION)
        if not syl_norm.strip():
            if pieces and not pieces[-1].endswith(" "):
                pieces.append(" ")
            continue
        if pieces and not pieces[-1].endswith(" ") and syl_norm[0] not in ",.;:!?~…)]}\"'":
            pieces.append(" ")
        pieces.append(syl_norm.strip())
    return _clean_spacing("".join(pieces))


def _romanize_hangul_word(word: str) -> str:
    out: list[str] = []
    n = len(word)
    for i, ch in enumerate(word):
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            offset = code - 0xAC00
            cho = offset // 588
            jung = (offset % 588) // 28
            jong = offset % 28
            ini = _KO_CHOSEONG[cho]
            med = _KO_JUNGSEONG[jung]
            fin = _KO_JONGSEONG[jong]
            # Basic intervocalic liaison: 'ㄹ' before vowel -> 'r'
            if jong == 8 and i + 1 < n:
                nxt = ord(word[i + 1])
                if 0xAC00 <= nxt <= 0xD7A3 and ((nxt - 0xAC00) // 588) == 11:
                    fin = "r"
            out.append(ini + med + fin)
        else:
            out.append(ch)
    return "".join(out)


def _romanize_ko(text: str) -> str:
    parts = re.split(r"(\s+)", text.translate(_PUNCT_TRANSLATION))
    out = [_romanize_hangul_word(part) if not part.isspace() else " " for part in parts if part]
    return _clean_spacing("".join(out))


def transliterate_line(text: str, song_script: str | None) -> str:
    """Return top-line romanization for `text`, or '' if Latin/empty/unsupported."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    script = _detect_line_override_script(raw, song_script)
    if script is None:
        return ""

    cache_key = (script, raw)
    cached = _LINE_CACHE.get(cache_key)
    if cached is not None:
        _LINE_CACHE.move_to_end(cache_key)
        return cached

    try:
        if script == "ja":
            result = _romaji_ja(raw)
        elif script == "zh":
            result = _pinyin_zh(raw)
        elif script == "ko":
            result = _romanize_ko(raw)
        else:
            result = ""
    except Exception:
        result = ""

    # Never emit a phonetic row that is visually identical to the original text
    if result and result.strip().lower() == raw.lower():
        result = ""

    _LINE_CACHE[cache_key] = result
    if len(_LINE_CACHE) > _MAX_LINE_CACHE:
        _LINE_CACHE.popitem(last=False)
    return result


def transliterate_word_token(token_text: str, song_script: str | None) -> str:
    """Transliterate a single timed karaoke token so phonetic sweep speed matches syllables."""
    raw = str(token_text or "").strip()
    if not raw:
        return ""
    if not has_non_latin_script(raw):
        return raw
    out = transliterate_line(raw, song_script)
    return out if out else raw
