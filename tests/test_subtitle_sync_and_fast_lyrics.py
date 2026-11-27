"""Comprehensive unit & integration tests for Master Audio Clock, Fast Lyrics Waterfall,
Empty-Intro Consensus Recovery, CJK Refinement/Credits, Worker Cancel & LRC I/O.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _write_silence_wav(path: Path, seconds: float = 10.0, sr: int = 16000) -> Path:
    nframes = int(round(seconds * sr))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * nframes)
    return path


class MasterAudioClockTests(unittest.TestCase):
    def test_audio_stream_engine_position_interpolates_smoothly_and_freezes_on_pause(self):
        from core.audio_stream_engine import AudioStreamEngine

        engine = AudioStreamEngine()
        engine._out_sr = 48000
        engine._latency_sec = 0.16
        engine._playback_rate = 1.0
        engine._start_ms = 10000.0
        engine._playing = True
        engine._paused = False

        # During initial prebuffer (played_frames <= latency), stays at exact start_ms
        engine._played_frames = 4096  # ~85 ms < 160 ms latency
        engine._last_write_mono = time.monotonic() - 0.02
        self.assertEqual(engine.position_ms(), 10000)

        # Once audio leaves DAC, interpolates smoothly with monotonic wall clock
        engine._played_frames = 48000  # 1.0s written -> 0.84s audible
        engine._last_write_mono = time.monotonic() - 0.020  # +20ms
        pos1 = engine.position_ms()
        self.assertGreaterEqual(pos1, 10855)
        self.assertLessEqual(pos1, 10885)

        # Bounded interpolation never runs away if writer stalls for 5s
        engine._last_write_mono = time.monotonic() - 5.0
        pos_capped = engine.position_ms()
        # base 840ms + max clamp (1.25 * 2048/48000 = ~53.3ms) = ~893ms
        self.assertLessEqual(pos_capped, 10905)

        # Paused freezes interpolation
        engine._paused = True
        pos_paused = engine.position_ms()
        self.assertEqual(pos_paused, 11000)

    def test_subtitle_effects_uses_authoritative_position_provider(self):
        from tools.ui_preview import APPLICATION
        from ui.subs_ui.subtitle_layer import SubtitleLayer
        from subtitle.mode import SubtitleMode

        layer = SubtitleLayer(initial_mode=SubtitleMode.JP)
        self.addCleanup(layer.deleteLater)
        fx = layer._subtitle_effects
        fx.bind_position_provider(lambda: 12345)
        self.assertEqual(fx._authoritative_pts_ms(), 12345)
        APPLICATION.processEvents()


class FastLyricsParserAndLocalTests(unittest.TestCase):
    def test_parse_lrc_multi_timestamp_offset_spacer_credit_and_hold_cap(self):
        from pipeline.fast_lyrics import parse_lrc_text

        lrc = (
            "[ti:Test Song]\n"
            "[ar:Test Artist]\n"
            "[offset:+500]\n"
            "[00:01.00] 作词：Somebody\n"
            "[00:05.50][00:30.50] 君の声\n"
            "[00:09.50]\n"
            "[00:40.50] ♫\n"
            "[00:45.50] Stay with me\n"
        )
        cues = parse_lrc_text(lrc, media_duration=90.0)
        # Credit & music-only lines removed; offset +500ms shifts earlier by 0.5s
        self.assertEqual([c["text"] for c in cues], ["君の声", "君の声", "Stay with me"])
        self.assertAlmostEqual(cues[0]["start"], 5.0, places=2)
        # Explicit blank spacer at 9.50 - 0.5 = 9.00 terminates first cue
        self.assertAlmostEqual(cues[0]["end"], 9.0, places=2)
        self.assertAlmostEqual(cues[1]["start"], 30.0, places=2)
        # No spacer between 30.0 and 45.0 -> hold duration capped <= 8.0s (not 15s!)
        self.assertLessEqual(cues[1]["end"] - cues[1]["start"], 8.0)

    def test_detect_text_language_covers_cjk_vi_en_ko(self):
        from pipeline.fast_lyrics import detect_text_language

        self.assertEqual(detect_text_language("君の声が聞こえる まだ終わらない"), "ja")
        self.assertEqual(detect_text_language("我愿意为你勇敢去飞翔"), "zh")
        self.assertEqual(detect_text_language("사랑해요 영원히 함께 있어줘"), "ko")
        self.assertEqual(detect_text_language("Đừng rời xa anh đêm nay nhé em"), "vi")
        self.assertEqual(detect_text_language("Stay with me through the midnight rain"), "en")

    def test_find_sidecar_lrc_srt_and_lrc_io_roundtrip(self):
        from pipeline.fast_lyrics import find_sidecar_subtitle
        from ui.subs_ui.subtitle_io import load_subs, save_subs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "Yorushika - Spring Thief.mp3"
            media.write_bytes(b"fake")
            lrc_path = root / "Yorushika - Spring Thief.lrc"
            cues_in = [
                {"start": 5.2, "end": 8.0, "text": "高架橋を抜けたら"},
                {"start": 8.4, "end": 11.5, "text": "雲の隙間に青が覗いた"},
                {"start": 12.0, "end": 15.2, "text": "今日だって座っている"},
            ]
            save_subs(str(lrc_path), cues_in)
            loaded = load_subs(str(lrc_path))
            self.assertEqual([c["text"] for c in loaded], [c["text"] for c in cues_in])

            hit = find_sidecar_subtitle(media, media_duration=240.0)
            self.assertIsNotNone(hit)
            self.assertEqual(hit["source"], "sidecar_lrc")
            self.assertEqual(hit["language"], "ja")
            self.assertEqual(len(hit["cues"]), 3)


class LRCLIBDualVerificationTests(unittest.TestCase):
    def _mock_response(self, payload, status_code=200):
        resp = mock.MagicMock()
        resp.status_code = status_code
        resp.json.return_value = payload
        return resp

    def test_lrclib_accepts_dual_verified_song(self):
        from pipeline.fast_lyrics import lookup_lrclib

        payload = [{
            "trackName": "春泥棒",
            "artistName": "ヨルシカ",
            "duration": 290.0,
            "instrumental": False,
            "plainLyrics": "高架橋を抜けたら\n雲の隙間に青が覗いた\n今日だって座っている",
            "syncedLyrics": (
                "[00:10.00] 高架橋を抜けたら\n"
                "[00:14.00] 雲の隙間に青が覗いた\n"
                "[00:18.00] 今日だって座っている\n"
            ),
        }]
        fake_probe = lambda _p: {
            "speech": [(9.8, 22.0)],
            "confirmed_speech": [(10.1, 21.8)],
        }
        with tempfile.TemporaryDirectory() as tmp:
            wav = _write_silence_wav(Path(tmp) / "a.wav", 20.0)
            res = lookup_lrclib(
                "ヨルシカ - 春泥棒 [Official MV]",
                media_duration=291.2,
                wav_path=wav,
                http_get=lambda *a, **kw: self._mock_response(payload),
                vad_probe_fn=fake_probe,
            )
        self.assertIsNotNone(res["synced_cues"])
        self.assertEqual(res["language"], "ja")
        self.assertTrue(res["verification"]["verified"])
        self.assertIsNotNone(res["plain_lyrics"])

    def test_lrclib_rejects_shifted_mv_intro_even_with_identical_duration_but_keeps_plain_ref(self):
        from pipeline.fast_lyrics import lookup_lrclib

        # Same duration (0.0s diff!) as studio track, but MV has 5s logo intro -> VAD starts at 15.0s!
        payload = [{
            "trackName": "春泥棒",
            "artistName": "ヨルシカ",
            "duration": 290.0,
            "instrumental": False,
            "plainLyrics": "高架橋を抜けたら\n雲の隙間に青が覗いた\n今日だって座っている",
            "syncedLyrics": (
                "[00:10.00] 高架橋を抜けたら\n"
                "[00:14.00] 雲の隙間に青が覗いた\n"
                "[00:18.00] 今日だって座っている\n"
            ),
        }]
        fake_probe = lambda _p: {
            "speech": [(15.2, 28.0)],
            "confirmed_speech": [(15.2, 28.0)],
        }
        with tempfile.TemporaryDirectory() as tmp:
            wav = _write_silence_wav(Path(tmp) / "mv.wav", 25.0)
            res = lookup_lrclib(
                "ヨルシカ - 春泥棒",
                media_duration=290.0,
                wav_path=wav,
                http_get=lambda *a, **kw: self._mock_response(payload),
                vad_probe_fn=fake_probe,
            )
        # Synced timestamps MUST be rejected!
        self.assertIsNone(res["synced_cues"])
        self.assertEqual(res["verification"]["reason"], "onset_mismatch")
        # Plain reference MUST still be preserved for translation assist!
        self.assertIn("高架橋を抜けたら", res["plain_lyrics"])

    def test_lrclib_rejects_romaji_synced_for_japanese_title(self):
        from pipeline.fast_lyrics import lookup_lrclib

        payload = [{
            "trackName": "春泥棒",
            "artistName": "ヨルシカ",
            "duration": 290.0,
            "instrumental": False,
            "syncedLyrics": (
                "[00:10.00] Koukakyou wo nuketara\n"
                "[00:14.00] Kumo no sukima ni ao ga nozoita\n"
                "[00:18.00] Kyou datte suwatte iru\n"
            ),
        }]
        res = lookup_lrclib(
            "ヨルシカ - 春泥棒",
            media_duration=290.0,
            http_get=lambda *a, **kw: self._mock_response(payload),
        )
        self.assertIsNone(res["synced_cues"])
        self.assertEqual(res["verification"]["reason"], "script_mismatch")


class EmptyIntroConsensusAndRefinementTests(unittest.TestCase):
    def _seg(self, start, end, text, logprob=-0.25, no_speech=0.05):
        words = [SimpleNamespace(start=start, end=end, word=text, probability=0.92)]
        return SimpleNamespace(
            start=start, end=end, text=text, words=words,
            avg_logprob=logprob, no_speech_prob=no_speech, compression_ratio=1.1,
        )

    def test_empty_intro_recovers_when_two_shifted_windows_agree(self):
        import numpy as np
        from pipeline.asr_intro_guard import _recover_empty_intro

        waveform = np.zeros(16000 * 35, dtype=np.float32)
        # Primary skipped 0..26s completely, only starting at 28s
        primary = [self._seg(28.0, 31.0, "Later chorus line")]
        speech = [(5.0, 18.0), (28.0, 32.0)]

        class FakeModel:
            def __init__(self):
                self.calls = 0

            def transcribe(self, clip, **kwargs):
                self.calls += 1
                # Return consistent real lyrics across shifted windows (relative to clip start)
                # Window 1 starts at 3.2s -> vocal at 5.0..12.0 is rel 1.8..8.8
                # Window 2 starts at 4.2s -> vocal at 5.0..12.0 is rel 0.8..7.8
                if self.calls == 1:
                    segs = [self._seg(1.8, 5.2, "君の声が聞こえる"), self._seg(5.4, 8.8, "まだ終わらないよ")]
                elif self.calls == 2:
                    segs = [self._seg(0.8, 4.2, "君の声が聞こえる"), self._seg(4.4, 7.8, "まだ終わらないよ")]
                else:
                    segs = []
                return iter(segs), SimpleNamespace(language="ja", language_probability=0.98)

            _seg = staticmethod(self._seg)

        merged, rep = _recover_empty_intro(FakeModel(), waveform, primary, "ja", speech, speech)
        self.assertTrue(rep.get("empty_intro_recovered"))
        self.assertGreaterEqual(rep.get("empty_intro_added", 0), 2)
        texts = [s.text for s in merged]
        self.assertIn("君の声が聞こえる", texts)
        self.assertIn("Later chorus line", texts)

    def test_empty_intro_bridges_14_to_30s_gap_using_opening_lyric_prompt(self):
        import numpy as np
        from pipeline.asr_intro_guard import _recover_empty_intro

        waveform = np.zeros(16000 * 40, dtype=np.float32)
        primary = [self._seg(30.3, 35.0, "とめどなく溢れる不安が")]
        speech = [(5.0, 36.0)]
        prompts_seen = []

        class BridgeModel:
            def __init__(self):
                self.calls = 0

            def transcribe(self, clip, **kwargs):
                self.calls += 1
                prompts_seen.append(kwargs.get("initial_prompt"))
                # Calls 1 & 2: opening 5..14s (unprompted)
                if self.calls == 1:
                    segs = [self._seg(1.8, 10.2, "明け星揺らめいてる儚い海に消えない光")]
                elif self.calls == 2:
                    segs = [self._seg(0.8, 9.2, "明け星揺らめいてる儚い海に消えない光")]
                # Calls 3 & 4: bridge 14..32s (prompted with opening lyric!)
                elif self.calls == 3:
                    segs = [self._seg(5.5, 14.5, "夢見ている未来が遠ざかってゆくような")]
                else:
                    segs = [self._seg(2.3, 11.3, "夢見ている未来が遠ざかってゆくような")]
                return iter(segs), SimpleNamespace(language="ja", language_probability=0.99)

            _seg = staticmethod(self._seg)

        merged, rep = _recover_empty_intro(BridgeModel(), waveform, primary, "ja", speech, speech)
        self.assertTrue(rep.get("empty_intro_recovered"))
        self.assertGreaterEqual(rep.get("empty_intro_bridge_added", 0), 1)
        self.assertIn("明け星揺らめいてる儚い海に消えない光", prompts_seen)
        texts = [s.text for s in merged]
        self.assertIn("明け星揺らめいてる儚い海に消えない光", texts)
        self.assertIn("夢見ている未来が遠ざかってゆくような", texts)
        self.assertIn("とめどなく溢れる不安が", texts)

    def test_empty_intro_rejects_instrumental_hallucination_disagreement(self):
        import numpy as np
        from pipeline.asr_intro_guard import _recover_empty_intro

        waveform = np.zeros(16000 * 35, dtype=np.float32)
        primary = [self._seg(28.0, 31.0, "Later chorus line")]
        speech = [(5.0, 14.0)]

        class HallucinatingModel:
            def __init__(self):
                self.calls = 0

            def transcribe(self, clip, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    segs = [self._seg(1.8, 6.0, "まったく別の幻聴テキスト")]
                else:
                    segs = [self._seg(0.8, 5.0, "全然違うノイズ文字")]
                return iter(segs), SimpleNamespace(language="ja", language_probability=0.8)

            _seg = staticmethod(self._seg)

        merged, rep = _recover_empty_intro(HallucinatingModel(), waveform, primary, "ja", speech, speech)
        self.assertFalse(rep.get("empty_intro_recovered"))
        self.assertEqual(rep.get("empty_intro_rejected"), "onset_disagreement")
        self.assertEqual([s.text for s in merged], ["Later chorus line"])

    def test_empty_intro_skips_with_zero_calls_when_intro_already_present(self):
        import numpy as np
        from pipeline.asr_intro_guard import _recover_empty_intro

        waveform = np.zeros(16000 * 35, dtype=np.float32)
        primary = [self._seg(6.0, 9.0, "Normal opening line")]
        speech = [(5.8, 12.0)]

        class NeverCalledModel:
            def transcribe(self, *args, **kwargs):
                raise AssertionError("Should never be called when intro already has lyrics")

        merged, rep = _recover_empty_intro(NeverCalledModel(), waveform, primary, "ja", speech, speech)
        self.assertEqual(rep, {})
        self.assertEqual([s.text for s in merged], ["Normal opening line"])

    def test_refinement_fillers_credits_and_orphan_cjk_particles_preserve_real_lyrics(self):
        from pipeline.lyric_accuracy import credit_text
        from pipeline.lyric_refinement import compress_fused_fillers, refine_lyrics

        # Chinese credit missed before
        self.assertTrue(credit_text("编写李宗盛", timed_words=True))
        self.assertTrue(credit_text("演唱：周杰伦", timed_words=True))
        # Ordinary lyrics preserved
        self.assertFalse(credit_text("回れ回れ回れ回れ回れ回れ回れ回れ", timed_words=True))

        # Runaway non-lexical CJK fillers compressed, real lexical repeats untouched!
        self.assertEqual(compress_fused_fillers("啦" * 15), "啦啦啦")
        self.assertEqual(compress_fused_fillers("ハイ" * 10), "ハイハイハイ")
        self.assertEqual(compress_fused_fillers("回れ" * 10), "回れ" * 10)

        # Orphan 1-char Japanese particle 'に' adjacent to previous phrase gets attached
        raw = [
            {
                "start": 10.0, "end": 12.0, "text": "君の声",
                "words": [
                    {"start": 10.0, "end": 11.0, "word": "君の"},
                    {"start": 11.0, "end": 12.0, "word": "声"},
                ],
            },
            {
                "start": 12.25, "end": 12.45, "text": "に",
                "words": [{"start": 12.25, "end": 12.45, "word": "に"}],
            },
        ]
        refined = refine_lyrics(raw, max_chars=22, min_pause=0.20)
        self.assertEqual(len(refined), 1)
        self.assertEqual(refined[0]["text"], "君の声に")


class BugFixesIntegrationTests(unittest.TestCase):
    def test_claude_corrector_sends_headers(self):
        from pipeline.lyric_corrector import correct_raw_segments_online

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            resp = mock.MagicMock()
            resp.json.return_value = {"content": [{"text": "0===Fixed line"}]}
            return resp

        with mock.patch("pipeline.lyric_corrector.requests.post", side_effect=fake_post):
            out = correct_raw_segments_online(
                [{"start": 0.0, "end": 2.0, "text": "Broken line"}],
                provider="Claude 3.5",
                key="sk-ant-test",
                master_lyric="Fixed line",
            )
        self.assertIsNotNone(captured.get("headers"))
        self.assertEqual(captured["headers"]["x-api-key"], "sk-ant-test")
        self.assertEqual(out[0]["text"], "Fixed line")

    def test_online_logic_uses_lrclib_extra_reference_through_asr_confidence_gate(self):
        from subtitle.model import Subtitle, SubtitleLine
        from translate.online_logic import translate_online_pipeline

        subs = [
            Subtitle(start=1.0, end=4.0, top=SubtitleLine(text="高架橋を抜けたら", lang="ja", style="JP")),
            Subtitle(start=4.2, end=8.0, top=SubtitleLine(text="雲の隙間に青が覗いた", lang="ja", style="JP")),
        ]
        sent_prompts = []

        def fake_post(url, **kwargs):
            sent_prompts.append(kwargs["json"]["messages"][1]["content"])
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{
                    "message": {
                        "content": (
                            "0===After passing the overpass===Sau khi qua cây cầu vượt\n"
                            "1===Blue peeked through the clouds===Sắc xanh hé qua kẽ mây"
                        )
                    }
                }]
            }
            return resp

        with mock.patch("translate.online_logic.QSettings") as qs_cls, \
             mock.patch("translate.online_logic.requests.post", side_effect=fake_post):
            qs = qs_cls.return_value
            qs.value.side_effect = lambda k, d="": {
                "subtitle_content_mode": "lyrics",
                "use_genius": "Tắt (Nhanh)",
                "genius_key": "",
                "translation_model": "gpt-4o-mini",
            }.get(k, d)
            res = translate_online_pipeline(
                subs,
                provider="OpenAI (GPT-4o)",
                key="sk-test",
                song_title_raw="ヨルシカ - 春泥棒",
                extra_reference_lyric="高架橋を抜けたら\n雲の隙間に青が覗いた",
            )
        self.assertIsNotNone(res)
        self.assertEqual(len(sent_prompts), 1)
        self.assertIn("THAM CHIẾU ĐÃ XÁC MINH", sent_prompts[0])
        self.assertEqual(res[0].bottom.text, "Sau khi qua cây cầu vượt")

    def test_asr_coverage_fast_pcm16_loader_reads_exact_samples(self):
        from pipeline.asr_coverage import _load_pcm16_fast

        with tempfile.TemporaryDirectory() as tmp:
            wav = _write_silence_wav(Path(tmp) / "t.wav", 2.0)
            arr = _load_pcm16_fast(wav)
            self.assertEqual(len(arr), 32000)
            self.assertAlmostEqual(float(arr.max()), 0.0)

    def test_anime_youtube_lrclib_query_variants(self):
        from pipeline.fast_lyrics import _lrclib_query_variants

        v1 = _lrclib_query_variants("NTE Akane Rin EP - Morning Star and the Sea")
        self.assertIn("Morning Star and the Sea", v1)
        v2 = _lrclib_query_variants("Goblin Slayer Season 2 - Ending Full - -Kasumi no Mukou e- by Yuki Nakashima")
        self.assertIn("Kasumi no Mukou e", v2)
        v3 = _lrclib_query_variants("YOASOBI「アイドル」 Official Music Video")
        self.assertIn("アイドル", v3)

    def test_seek_drag_and_ai_progress_margin_guard_in_main_window(self):
        from tools.ui_preview import APPLICATION, isolated_window, pump

        with isolated_window() as pair:
            mw = pair[0] if isinstance(pair, tuple) else pair
            mw.show()
            mw.update_video_location("large")
            pump(30)

            # While dragging slider, authoritative clock MUST follow slider (never snap back to old stream!)
            mw.audio_effects.stream._out_sr = 48000
            mw.audio_effects.stream._latency_sec = 0.16
            mw.audio_effects.stream._start_ms = 5000.0
            mw.audio_effects.stream._played_frames = 48000
            mw.audio_effects.stream._playing = True
            mw.audio_effects.stream._paused = False
            mw.audio_effects.stream._active_stream = object()
            mw.audio_effects._use_stream_engine = lambda: True

            mw.playback_bar.time_slider.setRange(0, 200000)
            mw.playback_bar.time_slider.setValue(91000)
            mw.playback_bar.time_slider.setSliderDown(True)
            self.assertEqual(mw.authoritative_subtitle_position_ms(), 91000)
            mw.playback_bar.time_slider.setSliderDown(False)
            if getattr(mw.audio_effects, "_seek_timer", None) is not None:
                mw.audio_effects._seek_timer.stop()
            # When actively playing (not dragging slider), clock includes +85ms perceptual visual lead
            raw_stream_ms = mw.audio_effects.stream.position_ms()
            self.assertEqual(mw.authoritative_subtitle_position_ms(), raw_stream_ms + mw.SUBTITLE_PERCEPTUAL_LEAD_MS)
            # When paused, perceptual visual lead is 0ms (exact raw timestamp)
            mw.audio_effects.stream._paused = True
            self.assertEqual(mw.authoritative_subtitle_position_ms(), int(mw.media_player.player.position()))
            mw.audio_effects.stream._paused = False

            # While ai_progress_bar (30px) is visible, subtitle bottom margin adds +30px to avoid PlaybackBar overlap
            mw.sync_subtitle_margin()
            idle_margin = mw.sub_layer._current_margin
            mw.ai_progress_bar.start_job("🎧 Đang xử lý...")
            pump(20)
            mw.sync_subtitle_margin()
            busy_margin = mw.sub_layer._current_margin
            self.assertEqual(busy_margin, idle_margin + 30)

            mw.ai_progress_bar.reset_idle()
            mw.audio_effects.stream._active_stream = None
            mw.audio_effects.stream._playing = False
        APPLICATION.processEvents()

    def test_audit_primary_intro_reuses_prefetched_probe_without_second_vad_call(self):
        import numpy as np
        from pipeline import asr_intro_guard

        probe = {
            "waveform": np.zeros(16000 * 20, dtype=np.float32),
            "speech": [(3.0, 15.0)],
            "confirmed_speech": [(3.0, 15.0)],
        }
        seg = SimpleNamespace(
            start=3.2, end=8.0, text="Opening lyric",
            words=[SimpleNamespace(start=3.2, end=8.0, word="Opening lyric", probability=0.95)],
            avg_logprob=-0.2, no_speech_prob=0.05, compression_ratio=1.1,
        )
        with mock.patch.object(asr_intro_guard, "_intro_speech_probe", side_effect=AssertionError("Must reuse prefetched_probe!")):
            out, lang, rep = asr_intro_guard.audit_primary_intro(
                model=None,
                audio_path="unused.wav",
                segments=[seg],
                language="en",
                language_probability=0.99,
                prefetched_probe=probe,
            )
        self.assertEqual(len(out), 1)
        self.assertEqual(lang, "en")

    def test_consume_segments_streams_live_progress_and_cancels_immediately(self):
        from ai.pipeline import _consume_segments_with_progress

        events = []

        def fake_gen():
            for i in range(1, 6):
                yield SimpleNamespace(start=float(i * 10 - 10), end=float(i * 10), text=f"Line {i}")

        segs = _consume_segments_with_progress(
            fake_gen(), wav_duration=100.0, progress_cb=lambda p, m: events.append((p, m)), cancel_cb=lambda: False
        )
        self.assertEqual(len(segs), 5)
        self.assertGreaterEqual(len(events), 1)
        self.assertGreaterEqual(events[0][0], 30)
        self.assertIn("Nhận diện lời", events[0][1])

        # Immediate mid-stream cancel check
        seen = 0

        def cancelling_gen():
            nonlocal seen
            for i in range(1, 10):
                seen += 1
                yield SimpleNamespace(start=float(i), end=float(i + 1), text=f"L{i}")

        with self.assertRaises(RuntimeError):
            _consume_segments_with_progress(
                cancelling_gen(), wav_duration=20.0, progress_cb=None, cancel_cb=lambda: seen >= 2
            )
        self.assertEqual(seen, 2)

    def test_ai_progress_bar_widget_lifecycle_and_cancel_signal(self):
        from tools.ui_preview import APPLICATION
        from ui.ai_progress_bar import AIProgressBar

        bar = AIProgressBar()
        self.addCleanup(bar.deleteLater)
        self.addCleanup(bar.shutdown)
        self.assertTrue(bar.isHidden())

        cancelled = []
        bar.cancel_requested.connect(lambda: cancelled.append(True))

        bar.start_job("🎧 Trích xuất audio...")
        self.assertFalse(bar.isHidden())
        self.assertFalse(bar.btn_cancel.isHidden())

        bar.update_progress(45, "📝 Nhận diện lời: 01:15 / 03:00 · 15 câu")
        self.assertEqual(bar.progress_bar.value(), 45)
        self.assertEqual(bar.lbl_percent.text(), "45%")
        self.assertIn("01:15", bar.lbl_status.text())

        bar.btn_cancel.click()
        self.assertEqual(cancelled, [True])

        bar.finish_job("✨ Phụ đề sẵn sàng (30 câu)", hide_delay_ms=5000)
        self.assertEqual(bar.progress_bar.value(), 100)
        self.assertTrue(bar.btn_cancel.isHidden())
        bar.reset_idle()
        self.assertTrue(bar.isHidden())
        APPLICATION.processEvents()

    def test_app_controller_cancel_current_job_on_track_click_and_user_cancel_button(self):
        from tools.ui_preview import APPLICATION, isolated_window, pump
        from control.ai_controller import AIController
        from control.app_controller import AppController

        with isolated_window() as pair:
            mw = pair[0] if isinstance(pair, tuple) else pair
            ai = AIController(tempfile.mkdtemp(), parent=mw)
            ctrl = AppController(mw, mw.media_library, ai, mw.subtitle_manager)
            mw.app_controller = ctrl
            mw.show()
            pump(20)

            # 1. Calling cancel_current_job() when idle (exact path of MainWindow.on_media_clicked) must never crash or flash error!
            ctrl.cancel_current_job()
            pump(10)
            self.assertTrue(mw.ai_progress_bar.isHidden())

            # 2. Clicking '✕ Hủy' while running cancels cleanly and shows brief notice
            ai.is_running = lambda: True
            mw.ai_progress_bar.start_job("📝 Đang chạy...")
            pump(10)
            mw.ai_progress_bar.btn_cancel.click()
            pump(10)
            self.assertFalse(mw.ai_progress_bar.isHidden())
            self.assertIn("Đã huỷ", mw.ai_progress_bar.lbl_status.text())

            # 3. Silent track-switch cancel while running hides the bar cleanly, and stale progress signals after stop do not reopen it
            mw.ai_progress_bar.start_job("📝 Đang chạy bài A...")
            ctrl.cancel_current_job(show_notice=False)
            self.assertTrue(mw.ai_progress_bar.isHidden())
            ai.is_running = lambda: False
            ctrl._on_ai_progress(45)
            self.assertTrue(mw.ai_progress_bar.isHidden())

            mw.ai_progress_bar.reset_idle()
        APPLICATION.processEvents()


class AsrCoverageContextGateTests(unittest.TestCase):
    def _make_wav(self, tmpdir, seconds=45.0):
        import wave
        wav_path = Path(tmpdir) / "sample.wav"
        nframes = int(seconds * 16000)
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * nframes)
        return wav_path

    def test_coverage_skips_context_retry_when_unprompted_decode_is_clean_empty(self):
        from pipeline.asr_coverage import repair_missing_subtitles

        calls = []

        class FakeModel:
            def transcribe(self, clip, **kwargs):
                calls.append(kwargs.get("initial_prompt"))
                return [], None

        cues = [
            {"id": 1, "start": 1.0, "end": 6.0, "text": "星が瞬く夜に", "words": []},
            {"id": 2, "start": 31.0, "end": 38.0, "text": "明日へ歩いてゆく", "words": []},
        ]
        with tempfile.TemporaryDirectory() as td:
            wav = self._make_wav(td, seconds=45.0)
            combined, report = repair_missing_subtitles(
                FakeModel(),
                str(wav),
                "ja",
                cues,
                {},
                prefetched_speech=[(1.0, 6.0), (14.0, 26.0), (31.0, 38.0)],
            )
        self.assertEqual(len(combined), 2)
        self.assertEqual(report["added_cues"], 0)
        self.assertTrue(calls)
        self.assertTrue(all(prompt is None for prompt in calls))

    def test_coverage_runs_context_retry_when_unprompted_decode_is_credit_hallucination(self):
        from pipeline.asr_coverage import repair_missing_subtitles

        prompt_calls = []

        class FakeModel:
            def transcribe(self, clip, **kwargs):
                prompt = kwargs.get("initial_prompt")
                if prompt is None:
                    seg = SimpleNamespace(
                        start=1.0,
                        end=5.0,
                        text="ご視聴ありがとうございました",
                        words=[],
                        avg_logprob=-0.25,
                        no_speech_prob=0.10,
                    )
                    return [seg], None
                prompt_calls.append(prompt)
                # Window is (4.0, 14.0) -> c1_l=6.5, c2_l=8.5; both map cleanly to abs 8.5..12.5s
                local_start = 2.0 if len(prompt_calls) == 1 else 0.0
                local_end = local_start + 4.0
                w1 = SimpleNamespace(start=local_start, end=local_start + 2.0, word="夢見ている未来が", probability=0.92)
                w2 = SimpleNamespace(start=local_start + 2.0, end=local_end, word="遠ざかってゆく", probability=0.90)
                seg = SimpleNamespace(
                    start=local_start,
                    end=local_end,
                    text="夢見ている未来が遠ざかってゆく",
                    words=[w1, w2],
                    avg_logprob=-0.20,
                    no_speech_prob=0.05,
                )
                return [seg], None

        cues = [
            {"id": 1, "start": 1.0, "end": 6.0, "text": "星が瞬く夜に", "words": []},
            {"id": 2, "start": 14.0, "end": 20.0, "text": "明日へ歩いてゆく", "words": []},
        ]
        with tempfile.TemporaryDirectory() as td:
            wav = self._make_wav(td, seconds=25.0)
            combined, report = repair_missing_subtitles(
                FakeModel(),
                str(wav),
                "ja",
                cues,
                {},
                prefetched_speech=[(1.0, 6.0), (8.0, 13.0), (14.0, 20.0)],
            )
        self.assertEqual(prompt_calls, ["星が瞬く夜に", "星が瞬く夜に"])
        self.assertEqual(report["added_cues"], 1)
        self.assertTrue(any("夢見ている未来が遠ざかってゆく" in c["text"] for c in combined))


class UniversalCommercialAsrTests(unittest.TestCase):
    def test_multilingual_credit_boilerplate_catches_korean_variants_without_banning_lyrics(self):
        from pipeline.lyric_accuracy import credit_text

        for junk in (
            "자막제공자",
            "자막 제공: 홍길동",
            "한글 자막 by 한효정",
            "한글자막 by ABC",
            "자막은 설정에서 선택하실 수 있습니다.",
            "시청해 주셔서 감사합니다",
            "MBC 뉴스 이덕영입니다",
        ):
            self.assertTrue(credit_text(junk, timed_words=True), f"Expected credit_text=True for {junk!r}")

        for real_lyric in (
            "고마워 고마워 고마워",
            "감사합니다 내 곁에 있어줘서",
            "넌 내 하나뿐인 태양",
            "I need you girl",
        ):
            self.assertFalse(credit_text(real_lyric, timed_words=True), f"False positive credit on {real_lyric!r}")

    def test_repeat_loop_pruner_strips_pathological_loops_and_keeps_real_choruses(self):
        from pipeline.asr_intro_guard import _prune_pathological_repeat_loops

        # 1. Extreme intro loop (comp=6.19, nsp=0.87)
        intro_loop = [
            SimpleNamespace(start=i * 2.0, end=i * 2.0 + 1.8, text="이 노래는", words=[], compression_ratio=6.19, no_speech_prob=0.87)
            for i in range(6)
        ] + [
            SimpleNamespace(start=28.0, end=31.0, text="잠이 멀어져만 가", words=[], compression_ratio=0.9, no_speech_prob=0.10)
        ]
        kept, removed = _prune_pathological_repeat_loops(intro_loop)
        self.assertEqual([s.text for s in kept], ["잠이 멀어져만 가"])
        self.assertEqual(len(removed), 6)

        # 2. Mid-song runaway loop with lead-in carrier segment
        mid_loop = [
            SimpleNamespace(start=342.8, end=348.8, text="아이유의 러브 앨범들 이 앨범은", words=[], compression_ratio=2.5, no_speech_prob=0.30),
        ] + [
            SimpleNamespace(start=348.8 + i * 2.1, end=350.6 + i * 2.1, text="이 앨범은", words=[], compression_ratio=2.5, no_speech_prob=0.30)
            for i in range(6)
        ] + [
            SimpleNamespace(start=365.0, end=368.0, text="곁에 머물러 줄래", words=[], compression_ratio=1.1, no_speech_prob=0.10),
        ]
        kept2, removed2 = _prune_pathological_repeat_loops(mid_loop)
        self.assertEqual([s.text for s in kept2], ["곁에 머물러 줄래"])
        self.assertEqual(len(removed2), 7)

        # 3. Real repeated chorus ("I need you girl" x5, comp=2.23, nsp=0.29) MUST survive untouched!
        real_chorus = [
            SimpleNamespace(start=74.0 + i * 1.5, end=75.4 + i * 1.5, text="I need you girl", words=[], compression_ratio=2.23, no_speech_prob=0.29)
            for i in range(5)
        ]
        kept3, removed3 = _prune_pathological_repeat_loops(real_chorus)
        self.assertEqual(len(kept3), 5)
        self.assertEqual(removed3, [])

    def test_unvoiced_outro_courtesy_filter_and_gap_priority(self):
        from pipeline.asr_coverage import _prioritize_windows, _strip_unvoiced_courtesy_hallucinations

        cues = [
            {"start": 10.0, "end": 13.0, "text": "감사합니다."},       # voiced -> MUST stay!
            {"start": 200.0, "end": 202.0, "text": "감사합니다."},     # unvoiced outro -> MUST drop!
            {"start": 205.0, "end": 207.0, "text": "Thank you."},     # unvoiced outro -> MUST drop!
        ]
        kept, removed = _strip_unvoiced_courtesy_hallucinations(cues, [(9.5, 13.5), (50.0, 180.0)], duration=210.0)
        self.assertEqual(removed, 2)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["start"], 10.0)

        # Big voiced gap (>=2.0s) later in song must be scheduled ahead of tiny breath pause earlier
        wins = [(10.0, 22.0), (120.0, 132.0)]
        voiced_gaps = [(14.0, 14.8), (122.0, 130.0)]
        ordered = _prioritize_windows(wins, voiced_gaps, [])
        self.assertEqual(ordered[0], (120.0, 132.0))

    def test_universal_title_cleanup_and_bilingual_lrclib_variants(self):
        from pipeline.fast_lyrics import _clean_query_title, _lrclib_query_variants, _script_compatible

        self.assertEqual(
            _lrclib_query_variants("MV BTS방탄소년단  I NEED U_1080p"),
            ("BTS 방탄소년단 I NEED U", "BTS I NEED U"),
        )
        self.assertEqual(
            _lrclib_query_variants("VIETSUBKARA Audio BTS 방탄소년단 Dead Leaves_v720P"),
            ("BTS 방탄소년단 Dead Leaves", "BTS Dead Leaves"),
        )
        self.assertEqual(
            _lrclib_query_variants("BLACKPINK 블랙핑크 Pink Venom Official MV 4K"),
            ("BLACKPINK 블랙핑크 Pink Venom", "BLACKPINK Pink Venom"),
        )
        self.assertEqual(
            _clean_query_title("YOASOBI ヨアソビ Idol [Official Music Video] 1080p"),
            "YOASOBI ヨアソビ Idol",
        )
        # Bilingual K-Pop lyrics with heavy English chorus pass; pure Romaji still rejected
        mixed_ko = "I need you girl\n" * 25 + "왜 혼자 사랑하고 혼자서만 이별해\n" * 6
        self.assertTrue(_script_compatible("BTS 방탄소년단 I NEED U", mixed_ko))
        pure_romaji = "Wae honja saranghago honjaseoman ibyeolhae " * 15
        self.assertFalse(_script_compatible("BTS 방탄소년단 I NEED U", pure_romaji))

    def test_intra_segment_loop_pruning_multilingual_credits_and_instrumental_intro_lrc(self):
        from pipeline.asr_intro_guard import _prune_pathological_repeat_loops
        from pipeline.lyric_accuracy import credit_text
        from pipeline.lyric_refinement import refine_lyrics
        from pipeline.fast_lyrics import verify_synced_cues_against_audio

        # 1. Intra-segment collapsed phrase loops ("I'm sorry, "*7 x5 and "啦"*28)
        sorry_loop = [
            SimpleNamespace(start=i * 3.0, end=i * 3.0 + 2.8, text="I'm sorry, " * 7, words=[], compression_ratio=3.2, no_speech_prob=0.6)
            for i in range(5)
        ] + [
            SimpleNamespace(start=38.0, end=42.0, text="Isn't it so incredible", words=[], compression_ratio=1.0, no_speech_prob=0.1)
        ]
        kept, removed = _prune_pathological_repeat_loops(sorry_loop)
        self.assertEqual([s.text for s in kept], ["Isn't it so incredible"])
        self.assertEqual(len(removed), 5)

        la_blob = [
            SimpleNamespace(start=164.0, end=173.0, text="啦" * 28, words=[], compression_ratio=4.5, no_speech_prob=0.7),
            SimpleNamespace(start=175.0, end=179.0, text="不曾低步踏碎", words=[], compression_ratio=1.1, no_speech_prob=0.1),
        ]
        kept_la, removed_la = _prune_pathological_repeat_loops(la_blob)
        self.assertEqual([s.text for s in kept_la], ["不曾低步踏碎"])
        self.assertEqual(len(removed_la), 1)

        # Joined phrase fused-filler compression (separate 1-char tokens glued by join_tokens)
        refined = refine_lyrics([{
            "start": 10.0,
            "end": 15.0,
            "text": "啦" * 20,
            "words": [{"start": 10.0 + i * 0.2, "end": 10.18 + i * 0.2, "word": "啦"} for i in range(20)],
        }])
        self.assertEqual(refined[0]["text"], "啦啦啦")

        # 2. Multilingual explicit YouTube/transcript credits
        for junk in (
            "© transcript Emily Beynon",
            "Thank you so much for watching this video, and I'll see you in the next video!",
            "由 Am ara.",
            "Terima kasih telah menonton!",
            "Cảm ơn các bạn đã xem",
        ):
            self.assertTrue(credit_text(junk, timed_words=True), f"Expected credit_text=True for {junk!r}")

        # 3. Synced LRC over brief instrumental VAD hits before sustained vocal block (>=4s)
        cues = [
            {"start": 21.65, "end": 25.48, "text": "Line 1"},
            {"start": 25.48, "end": 29.40, "text": "Line 2"},
            {"start": 29.40, "end": 33.34, "text": "Line 3"},
            {"start": 33.34, "end": 37.20, "text": "Line 4"},
            {"start": 37.20, "end": 41.00, "text": "Line 5"},
            {"start": 41.00, "end": 44.40, "text": "Line 6"},
        ]
        probe = {
            "speech": [(0.0, 60.0)],
            "confirmed_speech": [(1.78, 5.20), (9.07, 10.32), (21.42, 60.0)],
        }
        ok, info, _ = verify_synced_cues_against_audio(cues, "dummy.wav", prefetched_probe=probe)
        self.assertTrue(ok, f"Expected verified=True, got {info}")
        self.assertLessEqual(info["onset_diff"], 0.30)

        # Still REJECTS a late-shifted LRC when earlier speech was a real 10s verse (>=6s)!
        probe_real_intro = {
            "speech": [(0.0, 60.0)],
            "confirmed_speech": [(1.0, 12.0), (21.42, 60.0)],
        }
        ok2, info2, _ = verify_synced_cues_against_audio(cues, "dummy.wav", prefetched_probe=probe_real_intro)
        self.assertFalse(ok2)
        self.assertEqual(info2["reason"], "onset_mismatch")

    def test_pause_clock_has_zero_latency_jump_and_cover_query_variants_clean(self):
        from core.audio_stream_engine import AudioStreamEngine
        from pipeline.fast_lyrics import _lrclib_query_variants
        from pipeline import lyric_timing as timing

        eng = AudioStreamEngine()
        eng._playing = True
        eng._paused = False
        eng._out_sr = 48000
        eng._latency_sec = 0.16
        eng._start_ms = 10000.0
        eng._played_frames = 48000 * 2  # 2.00s written - 0.16s latency = 1.84s audible -> 11840ms
        eng._last_write_mono = 0.0
        before_pause = eng.position_ms()
        self.assertEqual(before_pause, 11840)
        eng.pause()
        after_pause = eng.position_ms()
        # Must NOT jump forward by +160ms on pause!
        self.assertEqual(after_pause, 11840)

        # Cover title strips '【歌ってみた】' and puts clean studio query FIRST (saving 1.4s wasted 0-hit query!)
        v = _lrclib_query_variants("【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！")
        self.assertEqual(v[0], "Tell Your World – kz")
        v_ep = _lrclib_query_variants("NTE Akane Rin EP - Morning Star and the Sea")
        self.assertEqual(v_ep[0], "Morning Star and the Sea")

        # High-confidence onset word snaps cleanly even when a trailing unstressed word has prob=0.10
        cues = [{"start": 10.0, "end": 12.2, "text": "See the light"}]
        cand = {0: [
            {"start": 10.72, "end": 11.1, "word": "See ", "probability": 0.92},
            {"start": 11.1, "end": 11.3, "word": "the ", "probability": 0.10},
            {"start": 11.3, "end": 12.2, "word": "light", "probability": 0.88},
        ]}
        aligned, changed = timing.apply_onsets(cues, cand)
        self.assertEqual(changed, [0])
        self.assertAlmostEqual(aligned[0]["start"], 10.67, places=2)

    def test_acoustic_lrc_ends_micro_gap_hygiene_and_zero_double_exit_strobe(self):
        from PySide6.QtCore import QAbstractAnimation
        from tools.ui_preview import APPLICATION
        from subtitle.mode import SubtitleMode
        from ui.subs_ui.subtitle_layer import SubtitleLayer
        from ui.subtitle_studio import STUDIO_PROFILES
        from pipeline.fast_lyrics import (
            parse_lrc_text,
            refine_lrc_ends_with_audio,
            close_flicker_micro_gaps,
        )

        # 1. Start-only LRC never chops sustained vocals early and never creates <550ms flicker micro-gaps
        lrc = (
            "[00:02.33]Ah-ah, ah-ah\n"
            "[00:08.77]Ah-ah, ah-ah, ah-ah\n"
            "[00:38.97]If I fall, let it be forward\n"
            "[00:42.06]If I break, let there be light\n"
            "[01:24.75]The sign is lining up like it's calling me to you\n"
            "[01:34.23]Ah-ah, ah-ah\n"
        )
        parsed = parse_lrc_text(lrc, media_duration=120.0)
        self.assertEqual(len(parsed), 6)
        # No cue may ever land in the forbidden (0, 0.55s) blink/flicker zone!
        for a, b in zip(parsed, parsed[1:]):
            gap = b["start"] - a["end"]
            self.assertTrue(gap == 0.0 or gap >= 0.55, f"Forbidden micro-gap {gap}s between {a} and {b}")

        # 2. Acoustic VAD refinement holds sustained notes (2.33..8.23s) and trims real instrumental solos (84.75..94.23s)!
        vad_spans = [
            (2.5, 8.25),    # sustained vocalise 'Ah-ah, ah-ah' -> must NOT chop at 4.3s!
            (8.8, 14.9),    # second vocalise -> stays full
            (38.9, 89.6),   # continuous singing through 89.6s, then 4.6s pure instrumental solo until 94.23s!
            (94.2, 100.0),
        ]
        refined = refine_lrc_ends_with_audio(parsed, media_duration=120.0, vad_spans=vad_spans)
        # Sustained vocalise held cleanly through singing (never cut off at 2-4s!)
        self.assertGreaterEqual(refined[0]["end"], 8.20)
        # Continuous chorus lines stay seamless (0ms gap -> zero flicker!)
        self.assertEqual(refined[3]["start"] - refined[2]["end"], 0.0)
        # Real 4.6s instrumental break after 89.6s trims cleanly around ~89.85s (leaving >4s clean visual rest!)
        self.assertAlmostEqual(refined[4]["end"], 89.85, delta=0.15)
        self.assertGreaterEqual(refined[5]["start"] - refined[4]["end"], 4.0)

        # 3. Whisper gap hygiene closes sub-520ms flicker gaps while preserving true >=520ms pauses
        whisper_cues = [
            {"start": 10.0, "end": 12.60, "text": "Line A"},
            {"start": 12.88, "end": 15.20, "text": "Line B"},  # 280ms flicker gap -> closed to 0ms
            {"start": 16.00, "end": 18.50, "text": "Line C"},  # 800ms true pause -> preserved!
        ]
        cleaned = close_flicker_micro_gaps(whisper_cues, min_clean_gap=0.52)
        self.assertEqual(cleaned[1]["start"] - cleaned[0]["end"], 0.0)
        self.assertAlmostEqual(cleaned[2]["start"] - cleaned[1]["end"], 0.80, places=2)

        # 4. SubtitleEffects.sync must NEVER double-fire _exit_ghost when SubtitleLayer is already mid-fade-out
        layer = SubtitleLayer(SubtitleMode.EN)
        self.addCleanup(layer.deleteLater)
        self.addCleanup(layer.hide)
        layer.set_fade_enabled(True)
        layer._subtitle_effects.configure(STUDIO_PROFILES["beat_char_pop"]["subtitle_effects"])
        layer.load_subtitles([
            {"start": 0, "end": 2000, "orig": "First line", "en": "First line", "vi": ""},
            {"start": 2250, "end": 4500, "orig": "Second line", "en": "Second line", "vi": ""},
        ])
        layer.show()
        layer.update_position(500)
        layer._subtitle_effects.animation.stop()
        layer._subtitle_effects.progress = 1.0
        layer.repaint()
        # Enter 250ms gap -> fade-out starts and drops opacity below 0.90
        layer.update_position(2100)
        self.assertEqual(layer.fade_anim.state(), QAbstractAnimation.State.Running)
        layer.set_opacity(0.45)
        # Cue 2 arrives mid-fade -> must NOT teleport Cue 1 back into _exit_ghost, and opacity restores to 1.0!
        layer.update_position(2260)
        self.assertIsNone(layer._subtitle_effects._exit_ghost)
        self.assertEqual(layer._opacity, 1.0)
        APPLICATION.processEvents()

    def test_apply_lrc_ends_refines_real_vocal_end_respects_spacer_and_closes_micro_gaps(self):
        from pipeline.lyric_timing import apply_lrc_ends

        cues = [
            {"start": 2.33, "end": 8.77, "text": "Ah-ah, ah-ah"},
            {"start": 8.77, "end": 15.32, "text": "Ah-ah, ah-ah, ah-ah"},
            {"start": 15.32, "end": 21.45, "text": "I was standing in the quiet"},
            {"start": 21.45, "end": 24.50, "text": "Explicit spacer line"},
            {"start": 26.00, "end": 29.00, "text": "Tight continuous chorus"},
            {"start": 29.00, "end": 32.00, "text": "Next tight line"},
        ]
        spacer_flags = [False, False, False, True, False, False]
        candidates = {
            0: [{"start": 2.70, "end": 5.89, "word": "Ah-ah", "probability": 0.65}],
            1: [{"start": 8.60, "end": 13.57, "word": "Ah-ah", "probability": 0.80}],
            2: [{"start": 15.20, "end": 19.83, "word": "quiet", "probability": 0.85}],
            3: [{"start": 21.40, "end": 22.80, "word": "line", "probability": 0.90}],  # spacer=True -> MUST stay 24.50!
            4: [{"start": 26.05, "end": 28.35, "word": "chorus", "probability": 0.90}],  # 28.35+0.40=28.75 -> gap 0.25s < 0.52s -> closed to 29.00!
            5: [{"start": 29.10, "end": 30.80, "word": "line", "probability": 0.10}],  # low prob -> rejected, keeps 32.00!
        }
        out, changed = apply_lrc_ends(cues, candidates, language="en", duration=35.0, spacer_flags=spacer_flags)
        # LRC starts stay untouched
        self.assertEqual([c["start"] for c in out], [c["start"] for c in cues])
        # Real vocal ends trimmed cleanly with +0.40s Latin singing tail
        self.assertAlmostEqual(out[0]["end"], 6.29, places=2)
        self.assertAlmostEqual(out[1]["end"], 13.97, places=2)
        self.assertAlmostEqual(out[2]["end"], 20.23, places=2)
        # Explicit LRC spacer preserved untouched
        self.assertAlmostEqual(out[3]["end"], 24.50, places=2)
        # Sub-520ms micro-gap closed cleanly to 29.00 (0 flicker!)
        self.assertAlmostEqual(out[4]["end"], 29.00, places=2)
        # Low-confidence word rejected safely
        self.assertAlmostEqual(out[5]["end"], 32.00, places=2)
        self.assertIn(0, changed)
        self.assertNotIn(3, changed)
        self.assertNotIn(5, changed)

    def test_derivative_cover_blocks_lrclib_synced_and_alignment_gate_fixes_offset_or_rejects_drift(self):
        from pipeline.fast_lyrics import evaluate_lrclib_items
        from pipeline.lyric_timing import _apply_lrc_alignment

        # 1. Cover song ('【歌ってみた】... covered by ...') MUST NEVER inherit original studio synced timestamps!
        items = [{
            "trackName": "Tell Your World",
            "artistName": "kz (livetune)",
            "duration": 255.8,
            "instrumental": False,
            "plainLyrics": "形のない気持ち忘れないように\n決まりきったレイアウトを消した",
            "syncedLyrics": (
                "[00:26.16] 形のない気持ち忘れないように\n"
                "[00:32.51] 決まりきったレイアウトを消した\n"
                "[00:38.97] ふと口ずさんだフレーズをつかまえて\n"
            ),
        }]
        res = evaluate_lrclib_items(
            "【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！",
            items,
            effective_query="Tell Your World – kz",
            media_duration=255.2,
            wav_path=None,
        )
        self.assertIsNone(res["synced_cues"])
        self.assertEqual(res["verification"]["reason"], "derivative_performance_skip_synced")
        # Plain reference is STILL preserved for online translation!
        self.assertIn("形のない気持ち忘れないように", res["plain_lyrics"])

        # 2. Constant master offset (-0.31s YouTube vs Spotify) is corrected cleanly across all cues
        cues = [
            {"start": 12.16, "end": 17.41, "text": "See how far we've come"},
            {"start": 17.41, "end": 23.25, "text": "And we are stronger now"},
            {"start": 23.25, "end": 29.45, "text": "Memories we will cherish"},
            {"start": 29.45, "end": 34.73, "text": "Walk as one with dawn"},
        ]
        cands = {
            0: [{"start": 11.85, "end": 15.86, "word": "See", "probability": 0.85}],
            1: [{"start": 17.10, "end": 20.52, "word": "And", "probability": 0.90}],
            2: [{"start": 22.94, "end": 27.80, "word": "Memories", "probability": 0.92}],
            3: [{"start": 29.14, "end": 31.84, "word": "Walk", "probability": 0.95}],
        }
        aligned, changed, diag = _apply_lrc_alignment(cues, cands, language="en", duration=40.0)
        self.assertTrue(diag["sync_verified"])
        # Includes ONSET_LEAD (0.05s) so subtitles appear crisply right ahead of acoustic vocal onset
        self.assertAlmostEqual(diag["global_shift"], -0.36, places=2)
        self.assertAlmostEqual(aligned[0]["start"], 11.80, places=2)
        self.assertAlmostEqual(aligned[0]["end"], 16.26, places=2)

        # 3. Wildly drifted LRC (erratic +/-1.5s errors) MUST fail sync_verified so pipeline falls back to Whisper!
        bad_cands = {
            0: [{"start": 10.10, "end": 14.00, "word": "See", "probability": 0.80}],
            1: [{"start": 19.30, "end": 22.00, "word": "And", "probability": 0.80}],
            2: [{"start": 21.50, "end": 26.00, "word": "Memories", "probability": 0.80}],
            3: [{"start": 31.40, "end": 33.00, "word": "Walk", "probability": 0.80}],
        }
        _out_bad, _ch_bad, bad_diag = _apply_lrc_alignment(cues, bad_cands, language="en", duration=40.0)
        self.assertFalse(bad_diag["sync_verified"])

    def test_foryou_black_stage_stays_fixed_and_video_fits_inside(self):
        from tools.ui_preview import APPLICATION, isolated_window, pump

        with isolated_window() as pair:
            mw = pair[0] if isinstance(pair, tuple) else pair
            mw.showMaximized = lambda: None
            mw.show()
            mw.sidebar.setCurrentRow(1)
            mw.handle_sidebar_click(mw.sidebar.item(1))
            pump(60)
            vs = mw.foryou_page.video_container
            # Black VideoStage stays unconstrained (fixed full left-column stage, never shrinks to video height)
            self.assertGreater(vs.maximumHeight(), 10000)
            for w, h in ((1920, 1040), (1536, 920), (1280, 720), (1100, 750)):
                mw.resize(w, h)
                pump(50)
                sg = vs.geometry()
                vg = mw.video_display.geometry()
                # Video fits tightly inside the fixed black stage along its limiting edge (letterbox/pillarbox black)
                self.assertTrue(
                    abs(sg.width() - vg.width()) <= 1 or abs(sg.height() - vg.height()) <= 1,
                    f"Video did not fit fixed stage at {w}x{h}: {sg} vs {vg}",
                )
                self.assertLessEqual(vg.width(), sg.width())
                self.assertLessEqual(vg.height(), sg.height())
                self.assertAlmostEqual(vg.width() / float(vg.height()), 16.0 / 9.0, delta=0.02)
        APPLICATION.processEvents()

    def test_foryou_hides_top_toolbar_when_idle_and_subtitles_sit_grounded_near_bottom(self):
        from PySide6.QtCore import QPoint
        from tools.ui_preview import APPLICATION, isolated_window, pump
        from subtitle.mode import SubtitleMode

        with isolated_window() as pair:
            mw = pair[0] if isinstance(pair, tuple) else pair
            mw.resize(1100, 750)
            mw.show()
            pump(25)

            # 1. Switching to For You (index 1) MUST hide top_toolbar_container even when ai_progress_bar is idle!
            mw.sidebar.setCurrentRow(0)
            mw.handle_sidebar_click(mw.sidebar.item(0))
            pump(15)
            self.assertFalse(mw.top_toolbar_container.isHidden())

            mw.sidebar.setCurrentRow(1)
            mw.handle_sidebar_click(mw.sidebar.item(1))
            pump(25)
            self.assertTrue(mw.top_toolbar_container.isHidden())

            # Returning to Home (index 0) restores top_toolbar_container
            mw.sidebar.setCurrentRow(0)
            mw.handle_sidebar_click(mw.sidebar.item(0))
            pump(25)
            self.assertFalse(mw.top_toolbar_container.isHidden())

            # 2. Subtitle glyphs sit grounded close to PlaybackBar / video bottom across modes
            sub = mw.sub_layer
            sub.set_mode(SubtitleMode.EN_VI)
            sub.load_subtitles([
                {"start": 0, "end": 5000, "orig": "We keep moving", "en": "We keep moving", "vi": "Chúng ta vẫn tiến bước"},
            ])
            mw.update_video_location("large")
            pump(25)
            sub.update_position(500)
            pump(10)
            pb_top = mw.playback_bar.mapToGlobal(QPoint(0, 0)).y()
            plan, _ = sub._plan_for(sub.text(), sub.contentsRect(), sub.size(), sub.sweep_row_groups)
            glyph_bot = sub.geometry().y() + plan.full_bounds.bottom()
            self.assertLessEqual(pb_top - glyph_bot, 16.0)
            self.assertGreaterEqual(pb_top - glyph_bot, 2.0)
        APPLICATION.processEvents()

    def test_snap_asr_cues_to_reference_covers_merged_split_homophone_medley_and_wrong_song(self):
        from pipeline.lyric_reference_snap import snap_asr_cues_to_reference

        # 1. Cover / MV with 1:2 merged Kana->Kanji cues + 2:1 split English cues -> preserves 100% Whisper times!
        ja_ref = (
            "叶えられなくて 涙零れ\n"
            "下を向いても\n"
            "明け星 揺らめいてる\n"
            "儚い海に 消えない光\n"
        )
        ja_asr = [
            {"start": 5.15, "end": 9.49, "text": "叶えられなくて涙こぼれ下を向いても"},
            {"start": 9.49, "end": 14.59, "text": "明け星揺らめいてる儚い海に消えない光"},
        ]
        snapped_ja, rep_ja = snap_asr_cues_to_reference(ja_asr, ja_ref, lang="ja")
        self.assertEqual(rep_ja["snapped_cues"], 2)
        self.assertEqual([c["start"] for c in snapped_ja], [5.15, 9.49])
        self.assertEqual([c["end"] for c in snapped_ja], [9.49, 14.59])
        self.assertEqual(snapped_ja[0]["text"], "叶えられなくて 涙零れ 下を向いても")
        self.assertEqual(snapped_ja[1]["text"], "明け星 揺らめいてる 儚い海に 消えない光")

        # 2. Chinese Traditional reference vs Simplified homophone ASR + sandwich rescue + 2:1 split!
        zh_ref = (
            "風抖落雪霜 傘骨吱呀響\n"
            "墨跡暈染處掩埋著神明溫熱的心臟\n"
            "一步一風景 一步一迷局\n"
            "未完的誓言沉入暗青水面\n"
        )
        zh_asr = [
            {"start": 21.60, "end": 25.10, "text": "风抖落雪霜 三股炙鸭响"},
            {"start": 25.10, "end": 29.22, "text": "墨镜云燃出掩埋着生命温热的心脏"},
            {"start": 29.93, "end": 33.01, "text": "一步一附近一步一迷去"},
            {"start": 33.01, "end": 36.11, "text": "未完的誓言沉入安静水面"},
        ]
        snapped_zh, rep_zh = snap_asr_cues_to_reference(zh_asr, zh_ref, lang="zh")
        self.assertEqual(rep_zh["snapped_cues"], 4)
        self.assertEqual(snapped_zh[1]["text"], "墨跡暈染處掩埋著神明溫熱的心臟")
        self.assertEqual(snapped_zh[2]["text"], "一步一風景 一步一迷局")

        # 3. Multi-candidate selection ('Run BTS' wrong song vs 'Run' true song!) + split 2:1 English line
        wrong_cand = {
            "track_name": "Run BTS",
            "artist_name": "BTS",
            "plain_lyrics": "Yeah yeah\nOkay\nRun run\nLet's go\nMake it move left and right",
        }
        true_cand = {
            "track_name": "Run",
            "artist_name": "BTS",
            "plain_lyrics": (
                "넌 내 하나뿐인 태양 세상에 딱 하나\n"
                "널 향해 피지만 난 자꾸 목말라\n"
                "And these are memories we'll cherish more and more\n"
                "다시 Run Run Run 난 멈출 수가 없어\n"
            ),
        }
        story_mv_asr = [
            {"start": 42.0, "end": 44.5, "text": "형 어디 가?"},  # Spoken MV acting dialogue -> MUST stay untouched!
            {"start": 55.1, "end": 59.2, "text": "넌 내 하나뿐인 태양 세상에 딱 하나"},
            {"start": 59.2, "end": 63.4, "text": "널향해 피지만 난 자꾸 목말라"},
            {"start": 64.0, "end": 66.2, "text": "And these are memories"},
            {"start": 66.2, "end": 69.0, "text": "we will cherish more and more"},
            {"start": 70.0, "end": 74.0, "text": "다시 런런런 난 멈출 수가 없어"},
        ]
        snapped_mv, rep_mv = snap_asr_cues_to_reference(story_mv_asr, [wrong_cand, true_cand], lang="ko")
        self.assertIn("Run - BTS", rep_mv["selected_track"])
        self.assertEqual(snapped_mv[0]["text"], "형 어디 가?")  # MV dialogue untouched!
        self.assertEqual(snapped_mv[3]["text"], "And these are memories")
        self.assertEqual(snapped_mv[4]["text"], "we'll cherish more and more")
        self.assertEqual(snapped_mv[5]["text"], "다시 Run Run Run 난 멈출 수가 없어")
        # Timestamps 100% unchanged
        self.assertEqual([(c["start"], c["end"]) for c in snapped_mv], [(c["start"], c["end"]) for c in story_mv_asr])

        # 4. Medley partial mode: snaps Tell Your World lines, leaves English medley song untouched!
        medley_asr = [
            {"start": 1.0, "end": 5.0, "text": "形のない気持ち忘れないように"},
            {"start": 5.2, "end": 9.5, "text": "決まりきったれいあうとを決した"},
            {"start": 12.0, "end": 15.0, "text": "You can surely know how the wind blows"},
            {"start": 15.2, "end": 18.5, "text": "Where the blue is taking me to roll"},
        ]
        tyw_ref = (
            "形のない気持ち忘れないように\n"
            "決まりきったレイアウトを消した\n"
            "ふと口ずさんだフレーズをつかまえて\n"
            "胸に秘めた言葉乗せ 空に解き放つの\n"
            "君に伝えたいことが\n"
            "君に届けたいことが\n"
            "たくさんの点は線になって\n"
            "遠く彼方へと響く\n"
        )
        snapped_med, rep_med = snap_asr_cues_to_reference(medley_asr, tyw_ref, lang="ja")
        self.assertEqual(rep_med["mode"], "partial_medley")
        self.assertEqual(snapped_med[0]["text"], "形のない気持ち忘れないように")
        self.assertEqual(snapped_med[1]["text"], "決まりきったレイアウトを消した")
        self.assertEqual(snapped_med[2]["text"], "You can surely know how the wind blows")
        self.assertEqual(snapped_med[3]["text"], "Where the blue is taking me to roll")

    def test_subtitle_io_export_vfx_and_editor_sync_audit(self):
        import tempfile
        from ui.subs_ui.subtitle_io import _format_srt_time, load_subs, save_subs
        from ui.video_subtitle_export import ExportCue, ExportSettings, ExportSnapshot, SubtitleBandRenderer

        # 1. SRT time rounding never overflows to ,1000ms
        self.assertEqual(_format_srt_time(12.9996), "00:00:13,000")
        self.assertEqual(_format_srt_time(0.0), "00:00:00,000")

        # 2. save_subs / load_subs fallback handles 'orig'-only dicts for SRT, ASS, and LRC
        segs = [{"start": 1.25, "end": 4.50, "orig": "First line\nSecond line", "en": "EN", "vi": "VI"}]
        with tempfile.TemporaryDirectory() as tmp:
            for ext in (".srt", ".ass", ".lrc"):
                p = os.path.join(tmp, "out" + ext)
                save_subs(p, segs)
                loaded = load_subs(p)
                self.assertTrue(loaded, ext)
                self.assertIn("First line", loaded[0]["text"], ext)

        # 3. Video burn-in export advances beat clock (_smooth_pts_ms) & matches PER_CHAR_MODES duration
        snap = ExportSnapshot(
            source="fixture.mp4",
            cues=(ExportCue(0, 1000, 4000, "Beat sync lyric"),),
            style={
                "font_size": 24, "font_color": "#FFFFFF", "bg_color": "#090D16",
                "bg_opacity": 0.0, "outline_enabled": True, "outline_width": 3,
                "outline_color": "#050811", "shadow_enabled": True, "shadow_alpha": 210,
            },
            effects={
                "enabled": True, "entrance": "vfx_beat_char_pop", "color": "cyber_neon",
                "trail": "bass_visualizer", "intensity": "normal", "duration": 540,
                "glow": True, "soft_fade": False,
            },
            fade_enabled=True,
            anchor_width=1280, anchor_height=720, user_moved=False,
            rel_x_offset=0, bottom_offset=12,
        )
        renderer = SubtitleBandRenderer(snap, 1280, 720, ExportSettings())
        # PER_CHAR_MODES extends 540ms -> 837ms on a 3000ms cue (matching live SubtitleEffects!)
        self.assertLess(renderer._effect_phase(snap.cues[0], 1600), 1.0)
        f1 = renderer.frame(2000)
        p1 = renderer.effects._smooth_pts_ms
        f2 = renderer.frame(2240)
        p2 = renderer.effects._smooth_pts_ms
        self.assertAlmostEqual(p1, 2000.0, places=1)
        self.assertAlmostEqual(p2, 2240.0, places=1)
        self.assertNotEqual(f1, f2)

    def test_video_export_keeps_subtitles_centered_after_large_mini_and_foryou_transitions(self):
        import numpy as np
        from subtitle.mode import SubtitleMode
        from tools.ui_preview import APPLICATION, isolated_window, pump
        from ui.video_subtitle_export import ExportSettings, SubtitleBandRenderer, snapshot_from_window

        with isolated_window() as pair:
            mw = pair[0] if isinstance(pair, tuple) else pair
            mw.showMaximized = lambda: None
            mw.move(220, 100)
            mw.resize(1280, 720)
            mw.show()
            mw.sub_layer.set_mode(SubtitleMode.EN_VI)
            mw.sub_layer.load_subtitles([
                {"start": 1000, "end": 4000, "orig": "Centered export", "en": "Centered export", "vi": "Căn giữa khi xuất"},
            ])
            pump(40)

            def assert_centered(tag):
                snap = snapshot_from_window(mw)
                r = SubtitleBandRenderer(snap, 1920, 1080, ExportSettings(), probe={"width": 1920, "height": 1080})
                self.assertAlmostEqual(r.center_x, 960.0, delta=2.0, msg=tag)
                raw = r.frame(2000)
                arr = np.frombuffer(raw, dtype=np.uint8).reshape(r.band_height, 1920, 4)
                ys, xs = np.where(arr[:, :, 3] > 20)
                self.assertGreater(len(xs), 0, tag)
                cx = (int(xs.min()) + int(xs.max())) / 2.0
                self.assertAlmostEqual(cx, 960.0, delta=3.0, msg=f"{tag}: px=[{xs.min()}..{xs.max()}]")

            # 1. ForYou -> Large (sub.setParent(self) makes isWindow() == False -> previously shifted -361px left!)
            mw.update_video_location("normal")
            pump(50)
            mw.update_video_location("large")
            pump(50)
            assert_centered("normal_to_large_windowed")

            # 2. Mini/Home mode (140x80 dock -> previously exploded center_x to 5472px!)
            mw.update_video_location("mini")
            pump(50)
            assert_centered("home_mini_dock")

            # 3. ForYou with unset anchor_rect_global -> still centered on video stage
            mw.sidebar.setCurrentRow(1)
            mw.handle_sidebar_click(mw.sidebar.item(1))
            pump(80)
            mw.sub_layer.reset_anchor_state()
            assert_centered("foryou_anchor_none")
        APPLICATION.processEvents()


if __name__ == "__main__":
    unittest.main()
