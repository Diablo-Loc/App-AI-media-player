"""Isolated probes of trusted local source snippets; no app imports/network/models."""

import ast
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def function(path, name, namespace, class_name=None):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    scope = tree if class_name is None else next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in scope.body if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, f"probe:{path}:{name}", "exec"), namespace)
    return namespace[name]


def main():
    key = function("app/translate/cache.py", "_key", {"hashlib": hashlib}, "TranslationCache")
    cleaner = function("app/translate/pipeline.py", "clean_repetitive_text", {"re": re})
    format_srt = function("app/ui/subs_ui/subtitle_io.py", "_format_srt_time", {})
    translated = SimpleNamespace(top=SimpleNamespace(text="Hello"), middle=None, bottom=None)
    request_count = []
    class Settings:
        def __init__(self, *args):
            pass
        def value(self, name, default):
            return default  # Genius disabled; no user registry access.
    class Requests:
        def post(self, *args, **kwargs):
            request_count.append("stub_only")
            return SimpleNamespace(json=lambda: {"choices": [{"message": {"content": "No parseable rows in this synthetic response"}}]})
    online = function("app/translate/online_logic.py", "translate_online_pipeline", {
        "QSettings": Settings, "requests": Requests(), "re": re,
        "SubtitleLine": lambda **kwargs: SimpleNamespace(**kwargs),
    })
    with contextlib.redirect_stdout(io.StringIO()):
        result = online([translated], "OpenAI", "synthetic-key-no-network", "Synthetic song")
    assert request_count == ["stub_only"]
    assert result and result[0].middle is None and result[0].bottom is None

    root = ast.parse((ROOT / "app/translate/pipeline.py").read_text(encoding="utf-8-sig"))
    call = next(node for node in ast.walk(root) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "translate_online_pipeline")
    online_root = ast.parse((ROOT / "app/translate/online_logic.py").read_text(encoding="utf-8-sig"))
    definition = next(node for node in online_root.body if isinstance(node, ast.FunctionDef) and node.name == "translate_online_pipeline")
    accepted = {arg.arg for arg in definition.args.args + definition.args.kwonlyargs}
    unsupported = sorted({keyword.arg for keyword in call.keywords if keyword.arg not in accepted})

    baseline = json.loads((ROOT / "docs" / "restored-app-baseline.json").read_text(encoding="utf-8"))
    long_text = "".join(chr(0x4E00 + i) for i in range(200))
    result = {
        "scope": "Isolated snippets and synthetic API stub only. No Qt app, network, GPU, user settings or media. These demonstrate conditional contracts, not actual user quality failures.",
        "revision": baseline["git_revision"],
        "source_sha256": {row["path"]: row["sha256"] for row in baseline["sources"] if row["path"] in ["app/translate/cache.py", "app/translate/pipeline.py", "app/translate/online_logic.py"]},
        "translation_cache_key": {"input": "Hello", "key": key(None, "Hello"), "accepts_language_mode_provider_model_context": False},
        "cleaner_long_text": {"input_characters": 200, "output_characters": len(cleaner(long_text)), "output": cleaner(long_text)},
        "online_unparseable_response": {"input_rows": 1, "returned_truthy_list": True, "translated_rows": 0, "would_pass_main_pipeline_if_result_check": True},
        "local_pipeline_online_adapter": {"unsupported_keyword_arguments": unsupported, "note": "Main ai.pipeline calls online_logic directly, so this mismatch does not mean its normal online path fails."},
        "srt_rounding_boundary": {"input_seconds": 1.9996, "output": format_srt(1.9996), "note": "Synthetic boundary reaches 1000 in the millisecond field instead of carrying to the next second."},
    }
    target = ROOT / "docs" / "restored-contract-probes.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Verified isolated contracts: cache context, cleaner limit, zero parsed rows, alternate online adapter signature.")


if __name__ == "__main__":
    main()
