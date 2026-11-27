import json
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from core.subtitle_manager import SubtitleManager
from pipeline.word_karaoke import (
    build_unit_curve,
    collect_fa_word_pool,
    collect_whisper_word_pool,
    eval_unit_curve,
    extract_and_align_cue_words,
    load_word_timings,
    match_words_to_loaded_cues,
    save_word_timings,
)
from subtitle.mode import SubtitleMode
from subtitle.phonetics import (
    clear_phonetic_cache,
    detect_song_phonetic_script,
    transliterate_line,
)
from ui.subs_ui.sub_panel import SettingsPanel
from ui.subs_ui.subtitle_layer import SubtitleLayer
from ui.subtitle_studio import build_typography_plan, measure_box_size
from ui.video_subtitle_export import ExportSettings, SubtitleBandRenderer, snapshot_from_window


def _ensure_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class PhoneticsOfflineTests(unittest.TestCase):
    def setUp(self):
        clear_phonetic_cache()

    def test_japanese_whole_song_locks_kanji_only_lines_to_romaji(self):
        cues = [
            {"orig": "夜に駆ける"},
            {"orig": "運命"},  # pure Kanji line inside a Japanese song
            {"orig": "君の声を"},
            {"orig": "Fly me to the moon"},  # English line inside J-Pop song
        ]
        script = detect_song_phonetic_script(cues)
        self.assertEqual(script, "ja")

        rom_verb = transliterate_line("夜に駆ける", script)
        self.assertIn("yoru", rom_verb)
        self.assertIn("kakeru", rom_verb)  # okurigana attached cleanly

        # Pure Kanji line in a Japanese song must become Hepburn Romaji ('unmei'), NOT Pinyin ('yùn mìng')
        rom_kanji = transliterate_line("運命", script)
        self.assertEqual(rom_kanji.lower(), "unmei")

        rom_pronoun = transliterate_line("君の声を", script)
        self.assertTrue(rom_pronoun.lower().startswith("kimi no"))

        # English chorus line must be auto-suppressed (never duplicated)
        self.assertEqual(transliterate_line("Fly me to the moon", script), "")

    def test_chinese_mandarin_pinyin_and_korean_hangul_romanization(self):
        zh_cues = [{"orig": "月光下的海"}, {"orig": "星辰大海"}]
        zh_script = detect_song_phonetic_script(zh_cues)
        self.assertEqual(zh_script, "zh")
        pinyin_line = transliterate_line("月光下的海", zh_script)
        self.assertIn("yuè", pinyin_line)
        self.assertIn("hǎi", pinyin_line)

        ko_cues = [{"orig": "사랑해 보고 싶다"}]
        ko_script = detect_song_phonetic_script(ko_cues)
        self.assertEqual(ko_script, "ko")
        ko_rom = transliterate_line("사랑해 보고 싶다", ko_script)
        self.assertEqual(ko_rom, "saranghae bogo sipda")

    def test_english_and_vietnamese_songs_suppress_phonetic_line(self):
        en_cues = [{"orig": "Morning star and the sea"}, {"orig": "Hold me tight tonight"}]
        vi_cues = [{"orig": "Chúng ta của hiện tại"}, {"orig": "Nơi này có anh"}]
        self.assertIsNone(detect_song_phonetic_script(en_cues))
        self.assertIsNone(detect_song_phonetic_script(vi_cues))
        self.assertEqual(transliterate_line("Chúng ta của hiện tại", None), "")
        self.assertEqual(transliterate_line("Morning star and the sea", None), "")

    def test_existing_600_cues_ram_speed(self):
        cues = [{"orig": f"夜に駆ける 君の運命 {i % 7}"} for i in range(120)]
        t0 = time.perf_counter()
        script = detect_song_phonetic_script(cues)
        out = [transliterate_line(c["orig"], script) for c in cues]
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(script, "ja")
        self.assertTrue(all(out))
        self.assertLess(elapsed_ms, 500.0)


class WordKaraokeSidecarAndCurveTests(unittest.TestCase):
    def test_separate_words_sidecar_keeps_main_json_5_key_schema_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SubtitleManager(storage_root=tmp)
            media_id = "song_hash_001"
            segments = [
                {
                    "start": 10.0,
                    "end": 13.0,
                    "orig": "Fly me to the moon",
                    "en": "Fly me to the moon",
                    "vi": "Đưa em bay tới mặt trăng",
                }
            ]
            saved = mgr.save_segments(media_id=media_id, segments=segments, source_path="song.mp4")
            self.assertTrue(saved)

            word_entries = [
                {
                    "start": 10.0,
                    "end": 13.0,
                    "orig": "Fly me to the moon",
                    "words": [
                        {"s": 10.10, "e": 11.60, "w": "Fly"},   # sustained 1.5s note!
                        {"s": 11.90, "e": 12.10, "w": "me"},    # 0.3s breath before 'me'
                        {"s": 12.10, "e": 12.30, "w": "to"},
                        {"s": 12.30, "e": 12.45, "w": "the"},
                        {"s": 12.45, "e": 12.85, "w": "moon"},
                    ],
                }
            ]
            words_path = mgr.save_word_timings(media_id, word_entries)
            self.assertIsNotNone(words_path)
            self.assertTrue(words_path.is_file())
            self.assertEqual(words_path.parent.name, "words")

            # Main subtitle JSON MUST retain exact 5-key schema with zero 'words' pollution
            main_json = json.loads(mgr.get_path(media_id, "json").read_text(encoding="utf-8"))
            for seg in main_json["segments"]:
                self.assertEqual(set(seg.keys()), {"start", "end", "jp", "en", "vi"})

            # Existing 600+ songs without words sidecar return []
            self.assertEqual(mgr.get_word_timings("legacy_song_without_words"), [])
            self.assertEqual(len(mgr.get_word_timings(media_id)), 1)

    def test_nonlinear_curve_holds_on_breath_and_sustained_notes(self):
        words_ms = [
            {"s_ms": 10100.0, "e_ms": 11600.0, "w": "Fly"},   # 1/5 = 0.0 -> 0.2 over 1500ms
            {"s_ms": 11900.0, "e_ms": 12100.0, "w": "me"},    # 0.2 -> 0.4 after 300ms pause
            {"s_ms": 12100.0, "e_ms": 12300.0, "w": "to"},
            {"s_ms": 12300.0, "e_ms": 12500.0, "w": "the"},
            {"s_ms": 12500.0, "e_ms": 12900.0, "w": "moon"},
        ]
        curve = build_unit_curve(words_ms)
        # Pre-vocal lead margin holds at 0.0
        self.assertAlmostEqual(eval_unit_curve(curve, 10020.0), 0.0, places=4)
        # Halfway through 1.5s sustained first word 'Fly' (10850ms) -> 0.10 (whereas linear would be ~0.28!)
        self.assertAlmostEqual(eval_unit_curve(curve, 10850.0), 0.10, places=3)
        # Mid-sentence vocal breath (11600..11900ms) holds steady at 0.20!
        self.assertAlmostEqual(eval_unit_curve(curve, 11620.0), 0.20, places=4)
        self.assertAlmostEqual(eval_unit_curve(curve, 11880.0), 0.20, places=4)
        # Post-vocal tail hold stays at 1.0
        self.assertAlmostEqual(eval_unit_curve(curve, 12950.0), 1.0, places=4)

    def test_reference_snapped_kanji_alignment_and_editor_invalidation(self):
        raw_segments = [
            {
                "start": 10.0,
                "end": 12.2,
                "text": "夜に掛ける",
                "words": [
                    {"start": 10.05, "end": 10.45, "word": "夜に"},
                    {"start": 10.65, "end": 11.95, "word": "掛ける"},
                ],
            }
        ]
        pool = collect_whisper_word_pool(raw_segments)
        # Reference snap fixed Kanji '掛' -> '駆' without changing cue timing
        final_subs = [{"start": 10.0, "end": 12.2, "orig": "夜に駆ける"}]
        entries = extract_and_align_cue_words(final_subs, pool)
        self.assertEqual(len(entries), 1)
        self.assertEqual("".join(w["w"] for w in entries[0]["words"]), "夜に駆ける")
        # Pause between 10.45 and 10.65 is preserved across 'に' -> '駆'!
        words = entries[0]["words"]
        ni_end = next(w["e"] for w in words if "に" in w["w"])
        ka_start = next(w["s"] for w in words if "駆" in w["w"])
        self.assertGreaterEqual(ka_start - ni_end, 0.18)

        # Editor time-shift (+500ms) keeps word sync shifted cleanly; rewriting text invalidates safely
        loaded_shifted = [{"start": 10500, "end": 12700, "orig": "夜に駆ける", "en": "", "vi": ""}]
        matched_shifted = match_words_to_loaded_cues(loaded_shifted, entries)
        self.assertIn(0, matched_shifted)
        self.assertAlmostEqual(matched_shifted[0][0]["s_ms"], 10550.0, delta=5.0)

        loaded_rewritten = [{"start": 10500, "end": 12700, "orig": "全く違う歌詞", "en": "", "vi": ""}]
        self.assertEqual(match_words_to_loaded_cues(loaded_rewritten, entries), {})


class SubtitleRendererAndExportParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _ensure_app()

    def test_english_vietnamese_and_japanese_modes_plus_off_toggle_identity(self):
        layer = SubtitleLayer(initial_mode=SubtitleMode.EN_VI)
        layer.resize(900, 180)

        # 1. English original song in default EN_VI mode:
        # Phonetics ON must NOT add duplicate top line, while EN row (matching orig) gets word karaoke!
        en_subs = [
            {
                "start": 1000,
                "end": 4000,
                "orig": "Morning star and sea",
                "en": "Morning star and sea",
                "vi": "Sao mai và biển cả",
            }
        ]
        en_words = [
            {
                "start": 1.0,
                "end": 4.0,
                "orig": "Morning star and sea",
                "words": [
                    {"s": 1.1, "e": 2.9, "w": "Morning"},
                    {"s": 3.0, "e": 3.3, "w": "star"},
                    {"s": 3.3, "e": 3.5, "w": "and"},
                    {"s": 3.5, "e": 3.9, "w": "sea"},
                ],
            }
        ]
        layer.set_phonetic_enabled(True)
        layer.set_word_karaoke_enabled(True)
        layer.load_subtitles(en_subs, word_timings=en_words)
        txt, groups, phon_top, roles = layer.build_text_plan_details(layer.subtitles[0])
        self.assertIsNone(phon_top)
        self.assertEqual(txt, "Morning star and sea\nSao mai và biển cả")
        self.assertEqual(roles[0], "orig")
        self.assertEqual(roles[1], "trans")
        tp = layer.track_progresses_for_pts(0, 2000.0)
        self.assertIsNotNone(tp)
        self.assertIn(0, tp)        # English row uses true word curve (~0.125 at 2.0s)
        self.assertNotIn(1, tp)     # Vietnamese translation row uses smooth linear sweep
        self.assertLess(tp[0], 0.20)

        # 2. Vietnamese original song in EN_VI mode: VI row (matching orig) gets word karaoke!
        vi_subs = [
            {
                "start": 1000,
                "end": 4000,
                "orig": "Chúng ta của hiện tại",
                "en": "Who we are right now",
                "vi": "Chúng ta của hiện tại",
            }
        ]
        vi_words = [
            {
                "start": 1.0,
                "end": 4.0,
                "orig": "Chúng ta của hiện tại",
                "words": [
                    {"s": 1.1, "e": 2.6, "w": "Chúng"},
                    {"s": 2.6, "e": 3.0, "w": "ta"},
                    {"s": 3.0, "e": 3.3, "w": "của"},
                    {"s": 3.3, "e": 3.6, "w": "hiện"},
                    {"s": 3.6, "e": 3.9, "w": "tại"},
                ],
            }
        ]
        layer.load_subtitles(vi_subs, word_timings=vi_words)
        _txt, _groups, vi_phon_top, vi_roles = layer.build_text_plan_details(layer.subtitles[0])
        self.assertIsNone(vi_phon_top)
        self.assertEqual(vi_roles[0], "trans")
        self.assertEqual(vi_roles[1], "orig")
        vi_tp = layer.track_progresses_for_pts(0, 1850.0)
        self.assertIn(1, vi_tp)
        self.assertNotIn(0, vi_tp)

        # 3. Japanese song in VI mode: Phonetics ON adds 76%-sized Romaji top row synced word-by-word;
        # turning both toggles OFF restores 100% legacy text, layout, and linear sweep!
        jp_subs = [
            {
                "start": 1000,
                "end": 4000,
                "orig": "夜に駆ける",
                "en": "Racing into the night",
                "vi": "Lao vào màn đêm",
            }
        ]
        jp_words = [
            {
                "start": 1.0,
                "end": 4.0,
                "orig": "夜に駆ける",
                "words": [
                    {"s": 1.1, "e": 1.5, "w": "夜に"},
                    {"s": 1.7, "e": 3.8, "w": "駆ける"},
                ],
            }
        ]
        layer.set_mode(SubtitleMode.VI)
        layer.set_phonetic_enabled(False)
        layer.set_word_karaoke_enabled(False)
        layer.load_subtitles(jp_subs, word_timings=jp_words)
        off_txt, off_groups = layer.build_text_plan(layer.subtitles[0])
        self.assertEqual(off_txt, "Lao vào màn đêm")
        self.assertEqual(off_groups, (0,))
        self.assertIsNone(layer.track_progresses_for_pts(0, 2000.0))

        # Turn ON both switches -> Romaji appears on top (group 0, smaller font) + word curve active!
        # Also verify JP_VI mode syncs BOTH Romaji (group 0) AND original Japanese Kanji/Kana (group 1)!
        layer.set_mode(SubtitleMode.JP_VI)
        layer.set_phonetic_enabled(True)
        layer.set_word_karaoke_enabled(True)
        jp_vi_txt, jp_vi_groups, jp_vi_phon, jp_vi_roles = layer.build_text_plan_details(layer.subtitles[0])
        self.assertEqual(jp_vi_phon, 0)
        self.assertEqual(jp_vi_groups, (0, 1, 2))
        self.assertEqual(jp_vi_roles[0], "phonetic")
        self.assertEqual(jp_vi_roles[1], "orig")   # Original Kanji/Kana ALSO synced word-by-word!
        self.assertEqual(jp_vi_roles[2], "trans")
        jp_vi_tp = layer.track_progresses_for_pts(0, 1600.0)
        self.assertIn(0, jp_vi_tp)
        self.assertIn(1, jp_vi_tp)
        self.assertNotIn(2, jp_vi_tp)

        layer.set_mode(SubtitleMode.VI)
        on_txt, on_groups, on_phon_top, on_roles = layer.build_text_plan_details(layer.subtitles[0])
        self.assertEqual(on_phon_top, 0)
        self.assertEqual(on_groups, (0, 1))
        self.assertIn("yoru ni kakeru", on_txt.splitlines()[0].lower())
        self.assertEqual(on_txt.splitlines()[1], "Lao vào màn đêm")
        self.assertEqual(on_roles[0], "phonetic")
        plan = build_typography_plan(on_txt, layer.font(), QRect(0, 0, 800, 140), on_groups, False, phonetic_top_group=on_phon_top)
        self.assertLess(plan.lines[0].font.pixelSize(), plan.lines[1].font.pixelSize())
        self.assertTrue(plan.lines[0].is_secondary)
        self.assertFalse(plan.lines[1].is_secondary)
        on_tp = layer.track_progresses_for_pts(0, 1600.0)  # inside vocal breath 1.5s..1.7s -> holds at 2/3 ('yoru ni' / 'yoru ni kakeru')!
        self.assertAlmostEqual(on_tp[0], 2.0 / 3.0, places=3)

    def test_settings_panel_switches_and_video_export_snapshot(self):
        from ui.subtitle_studio import KARAOKE_RECOMMENDED_PROFILES
        panel = SettingsPanel()
        self.assertFalse(panel.chk_phonetic.isChecked())
        self.assertFalse(panel.chk_word_karaoke.isChecked())
        for key in KARAOKE_RECOMMENDED_PROFILES:
            self.assertFalse(bool(panel.profile_btns[key].property("karaoke_rec")))

        panel.sync_ui({"phonetic_enabled": True, "word_karaoke_enabled": True})
        self.assertTrue(panel.chk_phonetic.isChecked())
        self.assertTrue(panel.chk_word_karaoke.isChecked())
        for key in KARAOKE_RECOMMENDED_PROFILES:
            self.assertTrue(bool(panel.profile_btns[key].property("karaoke_rec")))
            self.assertTrue(panel.profile_btns[key].text().startswith("★ "))

        panel._on_reset_clicked()
        self.assertFalse(panel.chk_phonetic.isChecked())
        self.assertFalse(panel.chk_word_karaoke.isChecked())
        for key in KARAOKE_RECOMMENDED_PROFILES:
            self.assertFalse(bool(panel.profile_btns[key].property("karaoke_rec")))

        # Verify MP4 Video Subtitle Export snapshots phonetic_top_group & word_curves and renders cleanly
        host = QWidget()
        host.resize(1280, 720)
        layer = SubtitleLayer(initial_mode=SubtitleMode.EN_VI, parent=host)
        layer.set_phonetic_enabled(True)
        layer.set_word_karaoke_enabled(True)
        layer._subtitle_effects.configure({"enabled": True, "entrance": "vfx_amll_silk_pro", "trail": "karaoke_pro", "color": "gold"})
        layer.load_subtitles(
            [{"start": 1000, "end": 4000, "orig": "夜に駆ける", "en": "Racing into the night", "vi": "Lao vào màn đêm"}],
            word_timings=[{
                "start": 1.0,
                "end": 4.0,
                "orig": "夜に駆ける",
                "words": [{"s": 1.1, "e": 1.5, "w": "夜に"}, {"s": 1.8, "e": 3.8, "w": "駆ける"}],
            }],
        )

        class _DummyWin:
            sub_layer = layer
            video_display = None
            playback_bar = None
            app_controller = type("C", (), {"current_media_item": type("M", (), {"path": "dummy.mp4"})()})()

        snap = snapshot_from_window(_DummyWin())
        self.assertEqual(len(snap.cues), 1)
        self.assertEqual(snap.cues[0].phonetic_top_group, 0)
        self.assertTrue(len(snap.cues[0].word_curves) >= 1)

        renderer = SubtitleBandRenderer(
            snap, 1280, 720, ExportSettings(),
            probe={"width": 1280, "height": 720, "fps": 30.0, "duration": 5.0, "audio_codecs": ("aac",)},
        )
        frame_bytes = renderer.frame(1650.0)
        self.assertEqual(len(frame_bytes), 1280 * renderer.band_height * 4)
        self.assertTrue(any(b != 0 for b in frame_bytes))
        self.assertIsNotNone(renderer.effects.track_scan_progresses)
        self.assertAlmostEqual(renderer.effects.track_scan_progresses[0], 2.0 / 3.0, places=3)

    def test_main_window_shortcut_r_focus_guard_and_persistence(self):
        from tools.ui_preview import isolated_window
        from unittest.mock import patch
        with isolated_window() as (window, _root):
            window.show()
            QApplication.processEvents()
            self.assertFalse(window.sub_layer.phonetic_enabled)
            self.assertFalse(window.sub_layer.word_karaoke_enabled)
            orig_size = window.sub_layer.current_font_size
            orig_color = window.sub_layer.current_color

            # 1. Shortcut R MUST be blocked in mini corner video mode, Dynamic Island mini_mode, and minimized state!
            window.video_mode = "mini"
            window.toggle_phonetic_shortcut()
            self.assertFalse(window.sub_layer.phonetic_enabled)

            window.video_mode = "large"
            window.is_mini_mode = True
            window.toggle_phonetic_shortcut()
            self.assertFalse(window.sub_layer.phonetic_enabled)
            window.is_mini_mode = False

            with patch.object(window, "isMinimized", return_value=True):
                window.toggle_phonetic_shortcut()
            self.assertFalse(window.sub_layer.phonetic_enabled)

            # When actively watching in 'large' video mode (active window, no text input), R toggles cleanly
            with patch.object(window, "isActiveWindow", return_value=True):
                window.toggle_phonetic_shortcut()
            self.assertTrue(window.sub_layer.phonetic_enabled)
            self.assertTrue(window.subsettings_panel.chk_phonetic.isChecked())
            saved = json.loads(Path(window.settings_file).read_text(encoding="utf-8"))
            self.assertTrue(saved["appearance"]["phonetic_enabled"])

            # Turn R back OFF first so we also verify 1-click Karaoke Mode auto-enables Phonetics and restores it on exit!
            with patch.object(window, "isActiveWindow", return_value=True):
                window.toggle_phonetic_shortcut()
            self.assertFalse(window.sub_layer.phonetic_enabled)

            # 2. Turning ON Karaoke Mode boosts subtitle size, auto-enables Phonetics for JP/ZH/KO, applies Stage Gold Karaoke VFX, and highlights ★ recommends
            window.set_word_karaoke_enabled(True)
            self.assertTrue(window.sub_layer.word_karaoke_enabled)
            self.assertTrue(window.sub_layer.phonetic_enabled)
            self.assertTrue(window.subsettings_panel.chk_phonetic.isChecked())
            self.assertGreaterEqual(window.sub_layer.current_font_size, 32)
            self.assertGreater(window.sub_layer.current_font_size, orig_size)
            self.assertTrue(window.sub_layer._subtitle_effects.options["enabled"])
            self.assertEqual(window.sub_layer._subtitle_effects.options["trail"], "karaoke_pro")
            self.assertTrue(window.subsettings_panel.profile_btns["amll_silk_pro"].property("karaoke_rec"))

            # 3. Turning OFF Karaoke Mode restores exact pre-Karaoke size, color, phonetic=False, and effects!
            window.set_word_karaoke_enabled(False)
            self.assertFalse(window.sub_layer.word_karaoke_enabled)
            self.assertFalse(window.sub_layer.phonetic_enabled)
            self.assertFalse(window.subsettings_panel.chk_phonetic.isChecked())
            self.assertEqual(window.sub_layer.current_font_size, orig_size)
            self.assertEqual(window.sub_layer.current_color, orig_color)
            self.assertFalse(window.subsettings_panel.profile_btns["amll_silk_pro"].property("karaoke_rec"))
            saved2 = json.loads(Path(window.settings_file).read_text(encoding="utf-8"))
            self.assertFalse(saved2["appearance"]["word_karaoke_enabled"])
            self.assertNotIn("_pre_karaoke_style", saved2["appearance"])

            # Reset restores OFF for both phonetics and karaoke
            window._reset_defaults()
            self.assertFalse(window.sub_layer.phonetic_enabled)
            self.assertFalse(window.sub_layer.word_karaoke_enabled)


if __name__ == "__main__":
    unittest.main()
