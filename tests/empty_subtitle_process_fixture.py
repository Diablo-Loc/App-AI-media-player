"""Spawn-safe fixture: real worker wrapper/queue, deterministic empty ASR result."""


def finish_empty_in_spawn(input_path, output_dir, media_id, queue):
    import os
    import sys
    from types import ModuleType
    os.chdir(output_dir)  # Any unexpected child error log stays in the test tree.
    from worker import _ai_process_wrapper
    pipeline = ModuleType('ai.pipeline')
    pipeline.run_ai_pipeline = lambda **kwargs: dict(media_id=media_id, segments=[])
    sys.modules['ai.pipeline'] = pipeline
    sys.modules['torch'] = ModuleType('torch')
    _ai_process_wrapper(input_path, output_dir, media_id, queue)
