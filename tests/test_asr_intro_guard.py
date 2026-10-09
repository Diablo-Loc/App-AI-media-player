"""Regression tests for conservative first-30-second ASR validation."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from pipeline.asr_intro_guard import (
    _agreement_ratio,
    _anchored_no_prompt_recovery,
    _credit_contamination,
    _first_window_domination,
    _has_intro_credit_signal,
    _language_probe_bounds,
    _language_probe,
    _language_consensus_probe,
    _merge_recovery_primary_first,
    _preserve_vad_backed_consensus_intro,
    _onset_speech,
    _stitch_intro_recovery,
    _verify_prevoice_text,
    audit_primary_intro,
    filter_instrumental_intro_segments,
)


def word(start, end, text="x", probability=0.9):
    return SimpleNamespace(start=start, end=end, word=text, probability=probability)


def segment(start, end, text, words=None):
    return SimpleNamespace(start=start, end=end, text=text, words=words or [word(start, end, text)])


def confident_segment(start, end, text, probability=0.9):
    item = segment(start, end, text, [word(start, end, text, probability)])
    item.avg_logprob = -0.2
    item.no_speech_prob = 0.05
    item.compression_ratio = 1.0
    return item


class FakeWaveform:
    def __init__(self, samples=30 * 16000):
        self.samples = samples

    def __len__(self):
        return self.samples

    def __getitem__(self, item):
        if isinstance(item, slice):
            start = 0 if item.start is None else item.start
            stop = self.samples if item.stop is None else min(self.samples, item.stop)
            return FakeWaveform(max(0, stop - start))
        return 0.0


class IntroFilterTests(unittest.TestCase):
    def test_generic_segments_before_first_voice_are_preserved(self):
        fake_a = segment(0.1, 1.8, "invented intro")
        fake_b = segment(4.0, 6.0, "more invented text")
        real = segment(9.85, 11.2, "real lyric")
        later = segment(14.0, 16.0, "next lyric")
        kept, removed = filter_instrumental_intro_segments(
            [fake_a, fake_b, real, later],
            [(9.7, 12.0), (13.8, 16.5)],
            verified_segments=[],
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, [fake_a, fake_b, real, later])
        self.assertEqual(removed, [])

    def test_one_local_verification_miss_cannot_delete_primary_text(self):
        maybe_real = segment(0.3, 1.5, "quiet opening lyric")
        kept, removed = filter_instrumental_intro_segments(
            [maybe_real],
            [(8.0, 11.0)],
            verified_segments=[],
        )
        self.assertEqual(kept, [maybe_real])
        self.assertEqual(removed, [])

    def test_two_independent_verification_misses_still_keep_prevoice_text(self):
        fake = segment(0.3, 1.5, "invented instrumental text")
        fake.avg_logprob = -1.20
        fake.no_speech_prob = 0.62
        kept, removed = filter_instrumental_intro_segments(
            [fake],
            [(8.0, 11.0)],
            verified_segments=[],
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, [fake])
        self.assertEqual(removed, [])

    def test_two_verification_misses_do_not_delete_confident_primary_text(self):
        maybe_real = confident_segment(0.3, 1.5, "quiet opening lyric")
        kept, removed = filter_instrumental_intro_segments(
            [maybe_real],
            [(8.0, 11.0)],
            verified_segments=[],
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, [maybe_real])
        self.assertEqual(removed, [])

    def test_one_weak_primary_metric_cannot_delete_real_opening(self):
        maybe_real = confident_segment(0.3, 1.5, "quiet opening lyric")
        maybe_real.avg_logprob = -1.20
        kept, removed = filter_instrumental_intro_segments(
            [maybe_real],
            [(8.0, 11.0)],
            verified_segments=[],
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, [maybe_real])
        self.assertEqual(removed, [])

    def test_repeated_high_compression_prevoice_text_is_preserved(self):
        repeated = [
            confident_segment(0.3, 1.0, "same invented phrase"),
            confident_segment(1.2, 1.9, "same invented phrase"),
            confident_segment(2.1, 2.8, "same invented phrase"),
        ]
        for item in repeated:
            item.compression_ratio = 5.0
        kept, removed = filter_instrumental_intro_segments(
            repeated,
            [(8.0, 11.0)],
            verified_segments=[],
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, repeated)
        self.assertEqual(removed, [])

    def test_repeated_real_lyric_survives_when_local_decode_reproduces_it(self):
        repeated = [
            confident_segment(0.3, 1.0, "same real refrain"),
            confident_segment(1.2, 1.9, "same real refrain"),
            confident_segment(2.1, 2.8, "same real refrain"),
        ]
        for item in repeated:
            item.compression_ratio = 5.0
        verified = [segment(0.0, 3.0, "same real refrain")]
        kept, removed = filter_instrumental_intro_segments(
            repeated,
            [(8.0, 11.0)],
            verified_segments=verified,
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, repeated)
        self.assertEqual(removed, [])

    def test_vad_alone_never_deletes_generic_prevoice_text(self):
        maybe_real = segment(0.3, 1.5, "quiet opening lyric")
        kept, removed = filter_instrumental_intro_segments(
            [maybe_real],
            [(8.0, 11.0)],
        )
        self.assertEqual(kept, [maybe_real])
        self.assertEqual(removed, [])

    def test_explicit_credit_can_be_removed_without_generic_verification(self):
        credit = segment(0.3, 1.5, "字幕志愿者 杨茜茜")
        kept, removed = filter_instrumental_intro_segments(
            [credit],
            [(8.0, 11.0)],
        )
        self.assertEqual(kept, [])
        self.assertEqual(removed[0][4], "credit")

    def test_matching_local_verification_preserves_prevoice_text(self):
        primary = segment(0.3, 1.5, "夜空の月")
        verified = segment(0.1, 1.4, "夜空の月")
        kept, removed = filter_instrumental_intro_segments(
            [primary],
            [(8.0, 11.0)],
            verified_segments=[verified],
            verified_offset=0.2,
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, [primary])
        self.assertEqual(removed, [])

    def test_single_character_refrain_survives_exact_verification(self):
        primary = segment(0.3, 0.9, "啊")
        verified = segment(0.1, 0.7, "啊")
        kept, removed = filter_instrumental_intro_segments(
            [primary],
            [(8.0, 11.0)],
            verified_segments=[verified],
            verified_offset=0.2,
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, [primary])
        self.assertEqual(removed, [])

    def test_vad_failure_or_immediate_voice_never_deletes_primary_segments(self):
        cues = [segment(0.2, 1.2, "hello"), segment(2.0, 3.0, "world")]
        self.assertEqual(filter_instrumental_intro_segments(cues, [])[0], cues)
        self.assertEqual(filter_instrumental_intro_segments(cues, [(0.1, 1.4)])[0], cues)

    def test_segment_touching_sensitive_vad_is_preserved(self):
        fake = segment(0.3, 1.2, "fake")
        quiet_vocal = segment(4.85, 5.4, "quiet real lyric")
        kept, removed = filter_instrumental_intro_segments(
            [fake, quiet_vocal],
            [(4.95, 5.15)],
            verified_segments=[],
            verified_segments_secondary=[],
        )
        self.assertEqual(kept, [fake, quiet_vocal])
        self.assertEqual(removed, [])

    def test_weak_next_video_boilerplate_is_removed_even_with_continuous_sensitive_vad(self):
        boilerplate = segment(26.7, 29.6, "I'll see you in the next video.")
        boilerplate.avg_logprob = -1.32
        boilerplate.no_speech_prob = 0.49
        kept, removed = filter_instrumental_intro_segments(
            [boilerplate],
            [(0.0, 30.0)],
        )
        self.assertEqual(kept, [])
        self.assertEqual(removed[0][4], "media_boilerplate")

    def test_degenerate_sensitive_vad_uses_later_confirmed_onset_after_long_gap(self):
        result = _onset_speech(
            [(0.0, 60.0)],
            [(0.05, 1.87), (16.82, 45.0)],
        )
        self.assertEqual(result, [(16.82, 45.0)])

    def test_near_zero_degenerate_vad_also_uses_later_confirmed_onset(self):
        result = _onset_speech(
            [(0.87, 60.0)],
            [(1.07, 16.78), (32.62, 60.0)],
        )
        self.assertEqual(result, [(32.62, 60.0)])

    def test_credit_repetition_over_real_voice_triggers_late_intro_recovery(self):
        credits = [
            segment(0.0, 1.8, "mixing: name"),
            segment(14.8, 18.0, "mixing: name"),
            segment(18.0, 22.0, "mixing: name"),
            segment(22.0, 27.0, "mixing: name"),
        ]
        trigger = _credit_contamination(
            credits,
            [(0.05, 1.87), (16.82, 45.0)],
        )
        self.assertEqual(trigger, (16.82, "credit_over_voice"))

    def test_repetition_alone_never_marks_real_lyrics_as_contamination(self):
        repeated = [
            segment(3.0, 6.0, "singer name"),
            segment(6.0, 9.0, "singer name"),
            segment(9.0, 12.0, "singer name"),
        ]
        self.assertIsNone(_first_window_domination(repeated))
        credits = [
            segment(1.0, 5.0, "Lyrics: someone"),
            segment(5.0, 9.0, "Music: someone"),
            segment(9.0, 13.0, "Producer: someone"),
        ]
        self.assertEqual(
            _first_window_domination(credits),
            ("credit_dominated_window", set()),
        )

    def test_high_compression_repetition_can_trigger_bounded_recovery(self):
        repeated = [
            segment(3.0, 6.0, "same impossible phrase"),
            segment(6.0, 9.0, "same impossible phrase"),
            segment(9.0, 12.0, "same impossible phrase"),
        ]
        for item in repeated:
            item.compression_ratio = 5.0
        self.assertEqual(
            _first_window_domination(repeated),
            ("repeated_high_compression_window", {"sameimpossiblephrase"}),
        )

    def test_short_high_compression_repeat_does_not_trigger_recovery(self):
        repeated = [
            segment(3.0, 3.8, "same phrase"),
            segment(4.0, 4.8, "same phrase"),
            segment(5.0, 5.8, "same phrase"),
        ]
        for item in repeated:
            item.compression_ratio = 5.0
        self.assertIsNone(_first_window_domination(repeated))

    def test_consensus_stitch_gives_thirty_second_seam_to_seam_pass(self):
        onset = [
            segment(16.7, 18.7, "line one"),
            segment(18.7, 20.3, "line two"),
            segment(20.3, 23.0, "line three"),
            segment(23.7, 27.7, "split seam fragment"),
        ]
        seam = [
            segment(20.0, 23.0, "line three"),
            segment(23.0, 25.9, "line four"),
            segment(25.9, 27.7, "line five"),
            segment(27.7, 30.8, "complete seam line"),
        ]
        stitched = _stitch_intro_recovery(onset, seam, 20.0, 27.0)
        self.assertEqual(
            [item.text for item in stitched],
            ["line one", "line two", "line three", "line four", "line five", "complete seam line"],
        )
        self.assertGreater(_agreement_ratio(onset, seam, 20.0, 27.0), 0.30)

    def test_consensus_stitch_trims_words_already_covered_by_onset_pass(self):
        onset = [
            segment(11.2, 16.5, "first line"),
            segment(16.5, 23.9, "忘れられない"),
        ]
        seam = [
            segment(21.8, 24.7, "忘れられない君と", [
                word(21.8, 23.7, "忘れられない"),
                word(23.7, 24.7, "君と"),
            ]),
            segment(24.7, 27.4, "next line"),
        ]
        stitched = _stitch_intro_recovery(onset, seam, 20.0, 24.0)
        self.assertEqual([item.text for item in stitched], ["first line", "忘れられない", "君と", "next line"])
        self.assertGreaterEqual(stitched[2].start, 23.7)


class LanguageProbeTests(unittest.TestCase):
    def test_probe_window_stops_after_vad_backed_voice(self):
        bounds = _language_probe_bounds(
            FakeWaveform(),
            [(8.0, 9.5), (10.0, 11.2)],
        )
        self.assertIsNotNone(bounds)
        left, right = bounds
        self.assertAlmostEqual(left, 7.85, places=2)
        self.assertAlmostEqual(right, 11.35, places=2)

    def test_high_confidence_primary_language_skips_probe(self):
        model = Mock()
        result = _language_probe(
            model, FakeWaveform(), [(8.0, 12.0)], "ja", 0.91
        )
        self.assertIsNone(result)
        model.transcribe.assert_not_called()

    def test_low_confidence_long_intro_accepts_only_strong_different_language(self):
        model = Mock()
        model.transcribe.return_value = (
            iter(()),
            SimpleNamespace(language="zh", language_probability=0.91),
        )
        result = _language_probe(
            model, FakeWaveform(), [(8.0, 12.0)], "cy", 0.31
        )
        self.assertEqual(result, ("zh", 0.91))
        kwargs = model.transcribe.call_args.kwargs
        self.assertIsNone(kwargs["language"])
        self.assertIsNone(kwargs["initial_prompt"])
        self.assertFalse(kwargs["vad_filter"])

    def test_weak_language_probe_does_not_override_primary(self):
        model = Mock()
        model.transcribe.return_value = (
            iter(()),
            SimpleNamespace(language="zh", language_probability=0.66),
        )
        self.assertIsNone(
            _language_probe(model, FakeWaveform(), [(8.0, 12.0)], "cy", 0.31)
        )


class VerificationDecodeTests(unittest.TestCase):
    def test_local_verifier_uses_native_silence_hallucination_guards(self):
        model = Mock()
        model.transcribe.return_value = (iter(()), SimpleNamespace())
        result = _verify_prevoice_text(
            model,
            FakeWaveform(),
            [segment(0.3, 1.5, "possibly invented intro")],
            [(8.0, 11.0)],
            "ja",
        )
        self.assertEqual(result[0], [])
        kwargs = model.transcribe.call_args.kwargs
        self.assertEqual(kwargs["no_speech_threshold"], 0.60)
        self.assertEqual(kwargs["log_prob_threshold"], -1.0)
        self.assertEqual(kwargs["hallucination_silence_threshold"], 1.0)
        self.assertIsNone(kwargs["initial_prompt"])
        self.assertFalse(kwargs["vad_filter"])


class AnchoredRecoveryTests(unittest.TestCase):
    def test_portuguese_subtitle_credit_is_high_signal(self):
        self.assertTrue(_has_intro_credit_signal([
            segment(9.9, 21.7, "Transcrição e Legendas Pedro Negri")
        ]))

    def test_sustained_vocal_after_credit_uses_zero_anchored_no_prompt_retry(self):
        primary = [
            segment(22.9, 25.0, "Thanks for watching!"),
            segment(49.0, 51.0, "later primary lyric"),
        ]
        recovered = [
            confident_segment(15.5, 19.0, "real opening line"),
            confident_segment(19.0, 27.0, "real continuation"),
        ]
        model = Mock()
        model.transcribe.return_value = (iter(recovered), SimpleNamespace())
        result, report = _anchored_no_prompt_recovery(
            model,
            FakeWaveform(60 * 16000),
            primary,
            "en",
            [(0.0, 5.8), (15.5, 40.0)],
        )
        self.assertTrue(report["anchored_recovery"])
        self.assertEqual([item.text for item in result[:2]], [
            "real opening line", "real continuation"
        ])
        self.assertEqual(len(model.transcribe.call_args.args[0]), 40 * 16000)
        self.assertIsNone(model.transcribe.call_args.kwargs["initial_prompt"])
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "en")

    def test_sparse_intro_speech_does_not_trigger_anchored_retry(self):
        model = Mock()
        original = [segment(13.7, 15.0, "Thanks for watching!")]
        result, report = _anchored_no_prompt_recovery(
            model,
            FakeWaveform(60 * 16000),
            original,
            "en",
            [(0.1, 2.1), (7.3, 8.5), (12.5, 14.9), (16.5, 20.0)],
        )
        self.assertEqual(result, original)
        self.assertEqual(report, {})
        model.transcribe.assert_not_called()

    def test_recovery_never_replaces_non_suspicious_primary_cue(self):
        primary = [
            confident_segment(17.0, 21.0, "trusted opening lyric"),
            segment(22.9, 25.0, "Thanks for watching!"),
            confident_segment(49.0, 51.0, "later primary lyric"),
        ]
        recovered = [
            confident_segment(15.5, 19.0, "retry opening"),
            confident_segment(19.0, 27.0, "retry continuation"),
        ]
        model = Mock()
        model.transcribe.return_value = (iter(recovered), SimpleNamespace())
        result, report = _anchored_no_prompt_recovery(
            model,
            FakeWaveform(60 * 16000),
            primary,
            "en",
            [(15.5, 40.0)],
        )
        self.assertTrue(report["anchored_recovery"])
        self.assertIn(primary[0], result)
        self.assertNotIn(primary[1], result)

    def test_primary_first_merge_only_fills_uncovered_time(self):
        primary = [confident_segment(17.0, 21.0, "trusted primary")]
        recovered = [
            confident_segment(15.0, 18.0, "overlapping retry"),
            confident_segment(22.0, 24.0, "missing lyric"),
        ]
        result, added = _merge_recovery_primary_first(primary, recovered)
        self.assertEqual(added, 1)
        self.assertEqual(
            [item.text for item in result],
            ["trusted primary", "missing lyric"],
        )


class IntroAuditTests(unittest.TestCase):
    def test_later_language_consensus_can_fix_immediate_count_in_language(self):
        original = [segment(0.0, 1.2, "um dois tres quatro"),
                    segment(68.0, 72.0, "wrong language lyric")]
        rerun = [segment(0.0, 1.2, "um dois tres quatre"),
                 segment(68.0, 72.0, "paroles correctes")]
        model = Mock()
        model.transcribe.return_value = (
            iter(rerun), SimpleNamespace(language="fr", language_probability=0.98)
        )
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(60 * 16000),
            "speech": [(0.0, 1.3), (55.0, 60.0)],
            "confirmed_speech": [(0.0, 1.3), (55.0, 60.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=None), patch(
            "pipeline.asr_intro_guard._language_consensus_probe",
            return_value=("fr", 0.94, [("fr", 0.93, 68.0, 76.0), ("fr", 0.95, 82.0, 90.0)]),
        ), patch("pipeline.asr_intro_guard._verify_prevoice_text", return_value=None):
            result, language, report = audit_primary_intro(model, "audio.wav", original, "pt", 0.73)
        self.assertEqual(
            [item.text for item in result],
            ["um dois tres quatro", "paroles correctes"],
        )
        self.assertEqual(language, "fr")
        self.assertTrue(report["language_rerun"])
        self.assertEqual(report["language_probe_mode"], "later_consensus")
        self.assertEqual(report["language_intro_preserved"], 1)

    def test_later_language_consensus_does_not_preserve_unvoiced_intro_hallucination(self):
        fake = segment(5.0, 7.0, "invented intro")
        later = segment(68.0, 72.0, "correct main lyric")
        result, preserved = _preserve_vad_backed_consensus_intro(
            [fake],
            [later],
            [(0.0, 1.2), (55.0, 60.0)],
        )
        self.assertEqual(result, [later])
        self.assertEqual(preserved, 0)

    def test_consensus_never_flips_from_one_later_window(self):
        model = Mock()
        with patch("pipeline.asr_intro_guard._audio_duration", return_value=120.0), patch(
            "pipeline.asr_intro_guard._language_consensus_windows",
            return_value=[(60.0, 68.0), (80.0, 88.0)],
        ), patch("pipeline.asr_intro_guard._read_pcm16_window", return_value=FakeWaveform(8 * 16000)):
            model.transcribe.side_effect = [
                (iter(()), SimpleNamespace(language="fr", language_probability=0.94)),
                (iter(()), SimpleNamespace(language="en", language_probability=0.91)),
            ]
            self.assertIsNone(_language_consensus_probe(
                model, "audio.wav", [segment(60, 64, "later")], "pt", 0.70
            ))

    def test_consensus_requires_strong_probability_gain(self):
        model = Mock()
        with patch("pipeline.asr_intro_guard._audio_duration", return_value=120.0), patch(
            "pipeline.asr_intro_guard._language_consensus_windows",
            return_value=[(60.0, 68.0), (80.0, 88.0)],
        ), patch("pipeline.asr_intro_guard._read_pcm16_window", return_value=FakeWaveform(8 * 16000)):
            model.transcribe.side_effect = [
                (iter(()), SimpleNamespace(language="fr", language_probability=0.84)),
                (iter(()), SimpleNamespace(language="fr", language_probability=0.85)),
            ]
            self.assertIsNone(_language_consensus_probe(
                model, "audio.wav", [segment(60, 64, "later")], "pt", 0.80
            ))

    def test_strong_language_correction_reruns_full_song_once_and_keeps_generic_intro(self):
        fake = segment(0.2, 1.6, "invented")
        real = segment(8.1, 10.0, "real")
        rerun_real = segment(8.0, 10.1, "correct language lyric")
        model = Mock()
        model.transcribe.return_value = (
            iter([fake, rerun_real]),
            SimpleNamespace(language="zh", language_probability=0.97),
        )
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(),
            "speech": [(7.8, 11.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=("zh", 0.92)), patch(
            "pipeline.asr_intro_guard._verify_prevoice_text", return_value=([], 0.0)
        ):
            result, language, report = audit_primary_intro(
                model, "audio.wav", [fake, real], "cy", 0.28
            )
        self.assertEqual(result, [fake, rerun_real])
        self.assertEqual(language, "zh")
        self.assertTrue(report["language_rerun"])
        self.assertEqual(report["removed"], [])
        self.assertEqual(model.transcribe.call_count, 1)
        self.assertEqual(model.transcribe.call_args.args[0], "audio.wav")
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "zh")
        self.assertEqual(model.transcribe.call_args.kwargs["initial_prompt"], " .+")
        self.assertFalse(model.transcribe.call_args.kwargs["vad_filter"])
        self.assertEqual(model.transcribe.call_args.kwargs["temperature"], 0.0)

    def test_empty_language_rerun_is_rejected_and_keeps_primary(self):
        original = [segment(8.1, 10.0, "keep original")]
        model = Mock()
        model.transcribe.return_value = (
            iter([]),
            SimpleNamespace(language="zh", language_probability=1.0),
        )
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(),
            "speech": [(7.8, 11.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=("zh", 0.92)), patch(
            "pipeline.asr_intro_guard._verify_prevoice_text", return_value=None
        ):
            result, language, report = audit_primary_intro(
                model, "audio.wav", original, "cy", 0.28
            )
        self.assertEqual(result, original)
        self.assertEqual(language, "cy")
        self.assertFalse(report["language_rerun"])
        self.assertEqual(report["language_rerun_rejected"], "empty_result")

    def test_first_voice_language_rerun_restores_only_omitted_primary_intro_gap(self):
        opening = confident_segment(8.1, 9.6, "keep opening lyric")
        old_overlap = confident_segment(12.0, 14.0, "old wrong wording")
        rerun_overlap = confident_segment(12.0, 14.0, "correct rerun wording")
        model = Mock()
        model.transcribe.return_value = (
            iter([rerun_overlap]),
            SimpleNamespace(language="zh", language_probability=0.97),
        )
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(),
            "speech": [(7.8, 15.0)],
            "confirmed_speech": [(7.8, 15.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=("zh", 0.92)), patch(
            "pipeline.asr_intro_guard._verify_prevoice_text", return_value=None
        ):
            result, language, report = audit_primary_intro(
                model, "audio.wav", [opening, old_overlap], "cy", 0.28
            )
        self.assertEqual(
            [item.text for item in result],
            ["keep opening lyric", "correct rerun wording"],
        )
        self.assertEqual(language, "zh")
        self.assertEqual(report.get("language_intro_restored"), 1)

    def test_language_rerun_restores_vad_backed_primary_even_when_primary_confidence_is_weak(self):
        opening = confident_segment(8.1, 9.6, "quiet but real opening")
        opening.avg_logprob = -1.20
        opening.no_speech_prob = 0.62
        opening.words[0].probability = 0.35
        rerun_later = confident_segment(12.0, 14.0, "rerun later lyric")
        model = Mock()
        model.transcribe.return_value = (
            iter([rerun_later]),
            SimpleNamespace(language="zh", language_probability=0.97),
        )
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(),
            "speech": [(7.8, 15.0)],
            "confirmed_speech": [(7.8, 15.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=("zh", 0.92)), patch(
            "pipeline.asr_intro_guard._verify_prevoice_text", return_value=None
        ):
            result, language, report = audit_primary_intro(
                model, "audio.wav", [opening], "cy", 0.28
            )
        self.assertEqual(
            [item.text for item in result],
            ["quiet but real opening", "rerun later lyric"],
        )
        self.assertEqual(language, "zh")
        self.assertEqual(report.get("language_intro_restored"), 1)

    def test_language_rerun_does_not_drop_primary_gap_when_vad_misses_quiet_vocal(self):
        opening = confident_segment(2.1, 3.6, "quiet opening missed by vad")
        rerun_later = confident_segment(12.0, 14.0, "rerun later lyric")
        model = Mock()
        model.transcribe.return_value = (
            iter([rerun_later]),
            SimpleNamespace(language="zh", language_probability=0.97),
        )
        verified = [segment(2.0, 3.5, "quiet opening missed by vad")]
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(),
            "speech": [(8.0, 15.0)],
            "confirmed_speech": [(8.0, 15.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=("zh", 0.92)), patch(
            "pipeline.asr_intro_guard._verify_prevoice_text",
            return_value=(verified, 0.0),
        ):
            result, language, report = audit_primary_intro(
                model, "audio.wav", [opening], "cy", 0.28
            )
        self.assertEqual(
            [item.text for item in result],
            ["quiet opening missed by vad", "rerun later lyric"],
        )
        self.assertEqual(language, "zh")
        self.assertEqual(report.get("language_intro_restored"), 1)

    def test_intro_audit_does_not_verify_generic_primary_text_for_deletion(self):
        original = [segment(0.2, 1.6, "possibly quiet real lyric")]
        model = Mock()
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(),
            "speech": [(8.0, 11.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=None), patch(
            "pipeline.asr_intro_guard._verify_prevoice_text",
            side_effect=ValueError("verification unavailable"),
        ) as verifier:
            result, language, report = audit_primary_intro(
                model, "audio.wav", original, "ja", 0.91
            )
        self.assertEqual(result, original)
        self.assertEqual(language, "ja")
        self.assertEqual(report["removed"], [])
        verifier.assert_not_called()

    def test_degenerate_sensitive_vad_does_not_delete_generic_intro(self):
        fake = segment(4.0, 7.0, "invented instrumental text")
        fake.avg_logprob = -1.25
        fake.no_speech_prob = 0.66
        model = Mock()
        with patch("pipeline.asr_intro_guard._intro_speech_probe", return_value={
            "waveform": FakeWaveform(60 * 16000),
            "speech": [(0.0, 60.0)],
            "confirmed_speech": [(16.8, 45.0)],
        }), patch("pipeline.asr_intro_guard._language_probe", return_value=None), patch(
            "pipeline.asr_intro_guard._language_consensus_probe", return_value=None
        ), patch(
            "pipeline.asr_intro_guard._verify_prevoice_text",
            side_effect=[([], 0.0), ([], 0.0)],
        ):
            result, language, report = audit_primary_intro(
                model, "audio.wav", [fake], "ja", 0.95
            )
        self.assertEqual(result, [fake])
        self.assertEqual(language, "ja")
        self.assertEqual(report["first_voice"], 16.8)
        self.assertEqual(report["removed"], [])

    def test_vad_error_fails_open_with_original_objects(self):
        original = [segment(0.2, 1.6, "keep me")]
        model = Mock()
        with patch(
            "pipeline.asr_intro_guard._intro_speech_probe",
            side_effect=RuntimeError("vad unavailable"),
        ):
            result, language, report = audit_primary_intro(
                model, "audio.wav", original, "en", 0.42
            )
        self.assertEqual(result, original)
        self.assertIs(result[0], original[0])
        self.assertEqual(language, "en")
        self.assertIn("vad unavailable", report["error"])
        model.transcribe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
