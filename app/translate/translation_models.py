"""Provider-aware model choices for online lyric translation.

The catalog is intentionally small and explicit.  UI code uses the display
labels while production requests use stable model IDs from item data.
"""
from __future__ import annotations


MODEL_CATALOG = {
    "Local Default": (),
    "Google Gemini": (
        ("Gemini 2.5 Flash · Tương thích", "gemini-2.5-flash"),
        ("Gemini 3 preview · Tiết kiệm", "gemini-3-flash-preview"),
        ("Gemini 3.5 Flash-Lite · Tiết kiệm", "gemini-3.5-flash-lite"),
        ("Gemini 3.5 Flash · Cân bằng", "gemini-3.5-flash"),
        ("Gemini 3.8 Flash · Chất lượng cao", "gemini-3.8-flash"),
    ),
    "OpenAI (GPT-4o)": (
        ("GPT-4o mini · Tương thích", "gpt-4o-mini"),
        ("GPT-5.6 Luna · Tiết kiệm", "gpt-5.6-luna"),
        ("GPT-5.6 Terra · Cân bằng", "gpt-5.6-terra"),
        ("GPT-5.6 Sol · Chất lượng cao", "gpt-5.6-sol"),
    ),
    "Claude 3.5": (
        ("Claude Haiku 4.5 · Nhanh", "claude-haiku-4-5-20251001"),
        ("Claude Sonnet 4.6 · Cân bằng", "claude-sonnet-4-6"),
        ("Claude Sonnet 5 · Chất lượng cao", "claude-sonnet-5"),
        ("Claude Sonnet 5.5 · Mới nhất", "claude-sonnet-5-5"),
    ),
}


# Preserve the existing online behavior when no new model preference exists.
# Claude 3.5 is the only exception because that API model is retired; the
# closest active Sonnet replacement is used instead of keeping a dead default.
DEFAULT_MODEL = {
    "Google Gemini": "gemini-2.5-flash",
    "OpenAI (GPT-4o)": "gpt-4o-mini",
    "Claude 3.5": "claude-sonnet-4-6",
}


def translation_model_options(provider: str):
    return MODEL_CATALOG.get(str(provider or ""), ())


def resolve_translation_model(provider: str, requested: str | None = None) -> str:
    options = translation_model_options(provider)
    valid = {model_id for _label, model_id in options}
    requested = str(requested or "").strip()
    if requested in valid:
        return requested
    return DEFAULT_MODEL.get(str(provider or ""), "")


def openai_uses_responses_api(model_id: str) -> bool:
    """Modern GPT-5.6 models are routed through the Responses API."""
    return str(model_id or "").startswith("gpt-5.6-")


def extract_openai_responses_text(payload) -> str:
    """Extract text from a raw Responses API JSON payload without SDK coupling."""
    if not isinstance(payload, dict):
        return ""
    pieces: list[str] = []
    for output in payload.get("output", ()) or ():
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        for content in output.get("content", ()) or ():
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    pieces.append(text.strip())
    return "\n".join(pieces)
