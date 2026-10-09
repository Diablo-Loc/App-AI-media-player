"""Read-only source inventory and isolated fault probes; no models or network.

These probes document current defects, rather than requiring them to stay broken.
Run with the project Python: python tools/current_flow_audit.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "4148c138c1e38f4959574caf925f1c86dbcca339"
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def saved_hashes():
    result = {}
    for directory in ("storage", "output", "video"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix.lower() in {".json", ".ass", ".srt", ".lrc"}:
                result[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    return result


def function(source, name):
    return next(node for node in ast.walk(ast.parse(source))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def isolated_function(relative, name, namespace):
    node = function((ROOT / relative).read_text(encoding="utf-8"), name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), relative, "exec"), namespace)
    return namespace[name]


def inventory():
    files = {}
    for path in sorted((ROOT / "app").rglob("*.py")):
        data = path.read_bytes()
        source = data.decode("utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        compile(tree, str(path), "exec")  # No imports, bytecode files or application execution.
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append("." * node.level + (node.module or ""))
        files[path.relative_to(ROOT).as_posix()] = {
            "lines": len(source.splitlines()), "sha256": digest(data),
            "imports": sorted(set(imports)),
            "functions": sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)),
        }
    return {"source_count": len(files), "lines": sum(f["lines"] for f in files.values()),
            "syntax_errors": 0, "files": files}


def original_contracts():
    checks = {}
    targets = {
        "app/run_app.py": ["global_exception_handler"],
        "app/control/ai_controller.py": ["start"],
        "app/worker.py": ["stop"],
        "app/core/media_library.py": ["scan_folder", "update_thumbnail_in_db", "save"],
        "app/ui/main_window.py": ["load_folder_content"],
        "app/ui/subs_ui/subtitle_dialog_logic.py": ["save_subtitle_content"],
        "app/translate/pipeline.py": ["translate_pipeline", "run_safe_batch", "clean_repetitive_text"],
        "app/translate/online_logic.py": ["translate_online_pipeline"],
    }
    for relative, names in targets.items():
        original = subprocess.run(["git", "show", f"{BASELINE}:{relative}"], cwd=ROOT,
                                  capture_output=True, check=True).stdout.decode("utf-8-sig")
        current = (ROOT / relative).read_text(encoding="utf-8-sig")
        checks[relative] = {name: ast.dump(function(original, name)) == ast.dump(function(current, name))
                            for name in names}
    return checks


def exception_probe():
    namespace = {"logging": Mock(), "sys": SimpleNamespace(__excepthook__=Mock(), exit=Mock())}
    hook = isolated_function("app/run_app.py", "global_exception_handler", namespace)
    try:
        hook(ImportError, ImportError("synthetic QtGui DLL import failure"), None)
    except NameError as error:
        return {"secondary_error": str(error), "original_hook_reached": namespace["sys"].__excepthook__.called}
    raise AssertionError("Expected the recorded early-import defect; update this probe after a fix.")


def save_probe(root):
    from core.subtitle_manager import SubtitleManager
    from subtitle.model import Subtitle, SubtitleLine
    manager = SubtitleManager(str(root / "subtitle-storage"))
    media = root / "song.mp4"
    media.write_bytes(b"synthetic ID fixture, not decoded")
    media_id = manager.get_reliable_id(media)

    def cues(text):
        return [Subtitle(1, 2, top=SubtitleLine(text, "en", "EN"))]

    assert manager.save_segments(media_id, cues("Original lyric"), str(media))
    json_path, ass_path = manager.get_path(media_id, "json"), manager.get_path(media_id, "ass")
    old_json, old_ass = json_path.read_bytes(), ass_path.read_bytes()
    with patch("core.subtitle_renderer.ASSRenderer.generate", return_value=False):
        failed_result = manager.save_segments(media_id, cues("Replacement lyric"), str(media))
    partial = {"save_returned": failed_result, "json_changed": json_path.read_bytes() != old_json,
               "ass_kept_old": ass_path.read_bytes() == old_ass,
               "subsequent_request_status": manager.request_subtitle(media).status}
    assert partial["json_changed"] and partial["ass_kept_old"] and failed_result is None
    baseline_source = subprocess.run(["git", "show", f"{BASELINE}:app/core/subtitle_manager.py"],
                                     cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    baseline_namespace = {"__name__": "isolated_original_subtitle_manager"}
    exec(compile(baseline_source, "baseline-subtitle-manager.py", "exec"), baseline_namespace)
    original = baseline_namespace["SubtitleManager"](str(root / "original-storage"))
    assert original.save_segments(media_id, cues("Original lyric"), str(media))
    original_json = original.get_path(media_id, "json").read_bytes()
    original_ass = original.get_path(media_id, "ass").read_bytes()
    with patch("core.subtitle_renderer.ASSRenderer.generate", return_value=False):
        original_failure = original.save_segments(media_id, cues("Replacement lyric"), str(media))
    original_partial = {
        "save_returned": original_failure,
        "json_changed": original.get_path(media_id, "json").read_bytes() != original_json,
        "ass_kept_old": original.get_path(media_id, "ass").read_bytes() == original_ass,
        "subsequent_request_status": original.request_subtitle(media).status,
    }
    assert partial == original_partial
    bad_path = root / "failed-json.json"
    bad_path.write_text('{"old": "valid"}', encoding="utf-8")
    with patch("core.subtitle_manager.json.dump", side_effect=OSError("synthetic interrupted write")):
        saved = manager._save_json_file(bad_path, {"new": "data"})
    dialogs = Mock()
    editor = SimpleNamespace(
        sync_context_from_parent=Mock(), _resolve_subtitle_path=Mock(return_value=str(json_path)),
        tabs=SimpleNamespace(currentIndex=lambda: 0),
        _parse_tab_orig=lambda: [{"start": 1, "end": 2, "text": "Editor replacement"}],
        parent=lambda: SimpleNamespace(app_controller=SimpleNamespace(subtitle_mgr=manager)),
        media_id=media_id, detected_lang="en", accept=Mock(),
    )
    save_editor = isolated_function("app/ui/subs_ui/subtitle_dialog_logic.py", "save_subtitle_content",
                                    {"QMessageBox": dialogs})
    before_editor = json_path.read_bytes()
    with patch.object(manager, "_save_json_file", return_value=False), \
            patch.object(manager, "render_ass_from_json", return_value=False):
        save_editor(editor)
    return {"partial_pair": partial, "original_baseline_partial_pair": original_partial, "json_write_failure": {
        "return_value": saved, "original_file_now_empty": bad_path.read_bytes() == b""},
        "editor_failed_save": {"json_unchanged": json_path.read_bytes() == before_editor,
                               "reported_success": dialogs.information.called,
                               "closed_as_accepted": editor.accept.called}}


def translation_probe(root):
    from translate import pipeline
    from translate.cache import TranslationCache
    from subtitle.model import Subtitle, SubtitleLine
    cache = TranslationCache(root / "translation-cache.json")
    fake_torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))

    def cues(text="A distinct sentence"):
        return [Subtitle(1, 2, top=SubtitleLine(text, "en", "EN"))]

    broken = Mock()
    broken.translate_batch.side_effect = RuntimeError("synthetic translator failure")
    healthy = Mock()
    healthy.translate_batch.return_value = ["Một câu đã dịch"]
    with patch.dict(sys.modules, {"torch": fake_torch}), \
            patch.object(pipeline, "TranslationCache", side_effect=lambda: TranslationCache(cache.path)):
        with patch.object(pipeline, "get_translator", return_value=broken):
            first = pipeline.translate_pipeline(cues(), src_lang="en")
        with patch.object(pipeline, "get_translator", return_value=healthy) as init:
            second = pipeline.translate_pipeline(cues(), src_lang="en")
        persistent = {"first_vi": first[0].bottom.text, "retry_vi": second[0].bottom.text,
                      "healthy_batch_calls": healthy.translate_batch.call_count,
                      "translator_initialized_despite_all_cache_hits": init.call_count}
        with patch.object(pipeline, "get_translator", return_value=healthy):
            short_batch = pipeline.run_safe_batch(healthy, ["First sentence", "Second sentence"], "en", "vi")
    repeated = "Stay with me " * 4
    cleaner = {"original": repeated.strip(), "translator_input": pipeline.clean_repetitive_text(repeated)}
    assert persistent["retry_vi"] == "" and persistent["healthy_batch_calls"] == 0
    online = []
    for response in ("Unable to produce the required format", "0===English line===Dòng tiếng Việt"):
        qsettings = Mock()
        qsettings.value.side_effect = lambda key, default=None: default
        namespace = {"QSettings": Mock(return_value=qsettings), "requests": Mock(),
                     "re": __import__("re"), "SubtitleLine": SubtitleLine}
        namespace["requests"].post.return_value.json.return_value = {
            "choices": [{"message": {"content": response}}]}
        translate = isolated_function("app/translate/online_logic.py", "translate_online_pipeline", namespace)
        rows = cues("First sentence") + cues("Second sentence")
        result = translate(rows, "OpenAI (GPT-4o)", "synthetic-key", "Synthetic title")
        online.append({"response": response, "truthy_result": bool(result),
                       "translated_rows": sum(bool(s.bottom and s.bottom.text) for s in result),
                       "total_rows": len(rows)})
    return {"failed_translation_cached": persistent, "local_short_batch": {
        "input_rows": 2, "output_rows": len(short_batch)}, "repeated_source_cleaner": cleaner,
        "online_invalid_and_partial": online}


def cache_write_probe(root):
    from core import media_library
    with patch.object(media_library, "SubtitleManager", return_value=Mock()):
        library = media_library.MediaLibrary(str(root / "library-cache.json"))
    library.items = {str(i): media_library.MediaMetadata(str(i), f"{i}.mp4", f"Song {i}")
                     for i in range(1000)}
    writes = []
    with patch.object(media_library.json, "dump", side_effect=lambda data, *a, **k: writes.append(len(data))):
        for i in range(100):
            library.update_thumbnail_in_db(str(i), f"{i}.jpg")
    return {"metadata_rows": 1000, "thumbnail_updates": 100, "whole_database_writes": len(writes),
            "records_prepared_for_serialization": sum(writes), "timing_claim": False}


def gui_wait_probe(root):
    from PySide6.QtCore import QCoreApplication, QTimer, QThread
    from control.ai_controller import AIController
    from worker import AIWorker
    application = QCoreApplication.instance() or QCoreApplication([])
    entered = threading.Event()

    class DelayedCleanup(AIWorker):
        def run(self):
            entered.set()
            while not self._cancelled:
                self.msleep(1)
            self.msleep(250)  # Synthetic cleanup, not a measured production ASR duration.

    class NoProcess(AIWorker):
        def run(self):
            self.msleep(5)

    controller = AIController(str(root))
    old = DelayedCleanup("old", "unused", str(root))
    controller._worker = old
    controller._current_media_id = "old"
    old.start()
    assert entered.wait(2)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start()
    deadline = time.perf_counter() + 0.05
    while time.perf_counter() < deadline:
        application.processEvents()
        time.sleep(0.001)
    before = len(ticks)
    cache = {"checked": True, "ready": True}
    # Avoid importing or invoking the resource installer/checker at all.
    installer = SimpleNamespace(check_resource_status=Mock(), _set_resource_ready_flag=Mock(),
                                _get_resource_ready_flag=Mock())
    with patch.dict(sys.modules, {"download_core.download_source_app": installer}), \
            patch("control.ai_controller._RESOURCE_CHECK_CACHE", cache), \
            patch("control.ai_controller.AIWorker", NoProcess):
        start = time.perf_counter()
        controller.start("new", "unused")
        elapsed = time.perf_counter() - start
        result = {"synthetic_cleanup_ms": 250, "start_call_ms": round(elapsed * 1000, 2),
                  "gui_timer_ticks_during_call": len(ticks) - before,
                  "called_on_gui_thread": QThread.currentThread() == application.thread()}
    timer.stop()
    if controller._worker:
        controller._worker.wait()  # Probe teardown only.
    application.processEvents()
    assert result["start_call_ms"] >= 240 and result["gui_timer_ticks_during_call"] == 0
    return result


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    before = saved_hashes()
    result = {"baseline": BASELINE, "python": sys.version, "inventory": inventory(),
              "unchanged_original_function_asts": original_contracts()}
    with tempfile.TemporaryDirectory(prefix="botube-flow-audit-") as temp:
        root = Path(temp)
        result["probes"] = {"early_exception": exception_probe(), "subtitle_save": save_probe(root),
                            "translation": translation_probe(root), "library_cache": cache_write_probe(root),
                            "gui_worker_restart": gui_wait_probe(root)}
    after = saved_hashes()
    result["saved_data"] = {"count": len(before), "unchanged": before == after, "hashes": before}
    assert before == after, "Audit must not alter user data"
    destination = ROOT / "docs/current-flow-audit"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "probe-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sources": result["inventory"]["source_count"], "probes": result["probes"],
                      "saved_files": len(before), "saved_unchanged": before == after}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    main()
