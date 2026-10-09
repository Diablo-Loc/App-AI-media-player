"""Focused contracts for conservative Genius reference assistance."""
from pathlib import Path
from types import SimpleNamespace
import unittest

from translate.genius_reference import (
    build_reference_hints,
    candidate_score,
    clean_genius_lyrics,
    clean_search_title,
    extract_referent_fragments,
    extract_song_results,
    reference_is_confident,
    reference_match_metrics,
    search_query_variants,
)
from tests.genius_reference_contracts import before_genius_reference_changes


ROOT = Path(__file__).resolve().parents[1]


def cue(text):
    return SimpleNamespace(top=SimpleNamespace(text=text))


class GeniusReferencePolicyTests(unittest.TestCase):
    def test_search_title_cleanup_is_local_and_conservative(self):
        raw = "01 - YOASOBI - 夜に駆ける (Official Music Video).mp4"
        cleaned = clean_search_title(raw)
        self.assertEqual(cleaned, "YOASOBI - 夜に駆ける")
        self.assertEqual(search_query_variants(raw)[0], cleaned)

    def test_lyricsgenius_hits_shape_is_supported(self):
        result = {"id": 7, "title": "Song", "artist_names": "Artist", "url": "https://genius.com/x"}
        payload = {"hits": [{"type": "song", "result": result}]}
        self.assertEqual(extract_song_results(payload), [result])

    def test_original_candidate_beats_unrequested_translation_variant(self):
        raw = "Artist - 星の歌"
        original = {"title": "星の歌", "artist_names": "Artist", "full_title": "星の歌 by Artist"}
        translated = {
            "title": "星の歌 (English Translation)",
            "artist_names": "Genius English Translations",
            "full_title": "星の歌 (English Translation) by Genius English Translations",
        }
        self.assertGreater(candidate_score(raw, original), candidate_score(raw, translated))

    def test_reference_validation_accepts_same_song_and_rejects_wrong_song(self):
        asr = "君の声が聞こえる 夜の空を見上げる まだここにいるよ 君を探している"
        same = "[Verse]\n君の声が聞こえる\n夜の空を見上げる\nまだここにいるよ\n君を探している\n12Embed"
        wrong = "朝の電車に乗って 新しい町へ行こう 雨が降っても笑って歩いていこう"
        self.assertTrue(reference_is_confident(asr, same))
        self.assertFalse(reference_is_confident(asr, wrong))
        self.assertGreater(reference_match_metrics(asr, same)["score"], reference_match_metrics(asr, wrong)["score"])

    def test_cleaning_does_not_drop_first_real_lyric_line(self):
        raw = "23 Contributors Song Lyrics\n最初の歌詞\n[Chorus]\n次の歌詞\n4Embed"
        self.assertEqual(clean_genius_lyrics(raw), "最初の歌詞\n次の歌詞")

    def test_referent_fallback_uses_only_bounded_lyric_fragments(self):
        payload = {
            "referents": [
                {"fragment": "First lyric line", "is_description": False},
                {"fragment": "First lyric line", "is_description": False},
                {"range": {"content": "Second lyric line"}, "is_description": False},
                {"fragment": "Song description", "is_description": True},
                {"fragment": "[Chorus]", "is_description": False},
            ]
        }
        self.assertEqual(
            extract_referent_fragments(payload),
            "First lyric line\nSecond lyric line",
        )

    def test_referent_fallback_rejects_invalid_payload(self):
        self.assertEqual(extract_referent_fragments(None), "")
        self.assertEqual(extract_referent_fragments({"referents": "bad"}), "")

    def test_only_confident_monotonic_cues_receive_reference_hints(self):
        subs = [
            cue("君の声が聞こえる"),
            cue("夜の空を見上げる"),
            cue("completely unrelated recognition noise"),
            cue("まだここにいるよ"),
        ]
        lyrics = "君の声が聞こえる\n夜の空を見上げる\nまだここにいるよ\n君を探している"
        hints = build_reference_hints(subs, lyrics)
        self.assertEqual(hints[0], "君の声が聞こえる")
        self.assertEqual(hints[1], "夜の空を見上げる")
        self.assertNotIn(2, hints)
        self.assertEqual(hints[3], "まだここにいるよ")


class GeniusReferenceSourceTests(unittest.TestCase):
    def test_exact_adapter_restores_pre_genius_online_logic(self):
        relative = "app/translate/online_logic.py"
        restored = before_genius_reference_changes(relative, raw=True)
        original = (ROOT / "docs/genius-reference/original" / relative).read_bytes()
        self.assertEqual(restored, original)

    def test_online_flow_does_not_use_cloud_title_cleanup_or_full_reference_prompt(self):
        source = (ROOT / "app/translate/online_logic.py").read_text(encoding="utf-8-sig")
        self.assertNotIn("ask_ai_for_clean_title(song_title_raw, key)", source)
        self.assertIn("lyricsgenius.Genius(token)", source)
        self.assertNotIn("verbose=False", source)
        self.assertIn("search_songs(query, per_page=5)", source)
        self.assertIn("genius.lyrics(song_url=url)", source)
        self.assertIn("genius.referents(", source)
        self.assertIn("reference_fetches < 2", source)
        self.assertIn("reference_by_id = build_reference_hints", source)
        self.assertIn("verified_references=batch_references", source)
        self.assertNotIn("VERIFIED CUE REFERENCES", source)
        self.assertNotIn("reference_lyric=reference_lyric", source)
        self.assertIn("resolve_translation_model", source)
        self.assertIn("model=translation_model", source)
        self.assertIn('"model": translation_model', source)


if __name__ == "__main__":
    unittest.main()
