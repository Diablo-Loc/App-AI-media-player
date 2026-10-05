"""Focused tests for provider-aware online translation model selection."""
from pathlib import Path
import unittest

from translate.translation_models import (
    MODEL_CATALOG,
    extract_openai_responses_text,
    openai_uses_responses_api,
    resolve_translation_model,
    translation_model_options,
)
from tests.online_translation_model_contracts import before_online_translation_model_changes


ROOT = Path(__file__).resolve().parents[1]


class TranslationModelPolicyTests(unittest.TestCase):
    def test_each_cloud_provider_has_multiple_unique_models(self):
        for provider in ("Google Gemini", "OpenAI (GPT-4o)", "Claude 3.5"):
            options = translation_model_options(provider)
            with self.subTest(provider=provider):
                self.assertGreaterEqual(len(options), 4)
                ids = [model_id for _label, model_id in options]
                self.assertEqual(len(ids), len(set(ids)))

    def test_invalid_or_cross_provider_model_falls_back_safely(self):
        self.assertEqual(resolve_translation_model("Google Gemini", "gpt-5.6-sol"), "gemini-2.5-flash")
        self.assertEqual(resolve_translation_model("OpenAI (GPT-4o)", "claude-sonnet-5"), "gpt-4o-mini")
        self.assertEqual(resolve_translation_model("Claude 3.5", "claude-3-5-sonnet-20240620"), "claude-sonnet-4-6")
        self.assertEqual(resolve_translation_model("Local Default", "gpt-4o-mini"), "")

    def test_valid_selection_is_preserved_exactly(self):
        for provider, options in MODEL_CATALOG.items():
            for _label, model_id in options:
                self.assertEqual(resolve_translation_model(provider, model_id), model_id)

    def test_modern_openai_models_use_responses_but_legacy_stays_chat(self):
        self.assertTrue(openai_uses_responses_api("gpt-5.6-luna"))
        self.assertTrue(openai_uses_responses_api("gpt-5.6-sol"))
        self.assertFalse(openai_uses_responses_api("gpt-4o-mini"))

    def test_raw_responses_json_text_extraction_is_ordered(self):
        payload = {
            "output": [
                {"type": "reasoning", "content": []},
                {"type": "message", "content": [
                    {"type": "output_text", "text": "0===EN===VI"},
                    {"type": "output_text", "text": "1===EN2===VI2"},
                ]},
            ]
        }
        self.assertEqual(extract_openai_responses_text(payload), "0===EN===VI\n1===EN2===VI2")


class TranslationModelSourceTests(unittest.TestCase):
    def test_exact_adapter_restores_pre_phase_sources(self):
        for relative in ("app/translate/online_logic.py", "app/ui/pages/settings.py"):
            with self.subTest(relative=relative):
                restored = before_online_translation_model_changes(relative, raw=True)
                original = (ROOT / "docs/online-translation-models/original" / relative).read_bytes()
                self.assertEqual(restored, original)

    def test_online_logic_resolves_saved_model_and_keeps_legacy_chat_path(self):
        source = (ROOT / "app/translate/online_logic.py").read_text(encoding="utf-8-sig")
        self.assertIn('settings.value("translation_model", "")', source)
        self.assertIn('model=translation_model', source)
        self.assertIn('"model": translation_model', source)
        self.assertIn('https://api.openai.com/v1/responses', source)
        self.assertIn('https://api.openai.com/v1/chat/completions', source)


if __name__ == "__main__":
    unittest.main()
