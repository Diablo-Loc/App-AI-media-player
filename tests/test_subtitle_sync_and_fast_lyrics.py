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


if __name__ == "__main__":
    unittest.main()
