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


if __name__ == "__main__":
    unittest.main()
