"""Verify source contracts against a temporary checkout of the staged index.

No branches/worktree files are reset or changed. Run after staging the focused
audio change; the active Python environment supplies dependencies, while exact
source/hash checks read the independent checkout with Git's real attributes.
"""
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.ui_preview import ROOT

TARGETS = (
    'tests.test_audio_easy.EasyScopeTests',
    'tests.test_audio_listening.ListeningScopeTests',
    'tests.test_audio_prefetch.ScopeTests',
    'tests.test_audio_start.SourceScopeTests',
    'tests.test_audio_realtime.SourceScopeTests',
    'tests.test_audio_effects.SourceScopeTests',
    'tests.test_subtitle_presentation.SourceScopeTests',
    'tests.test_ui_refresh.OriginalSourceGates',
    'tests.test_asr_coverage.PipelineContractTests',
    'tests.test_empty_subtitles.EmptySourceGates',
    'tests.test_reliability.ReviewedScopeTests',
)


def main():
    suite = unittest.TestSuite()
    for target in TARGETS:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(target))
    # Load the complete adapter chain before redirecting its roots.
    for name in ('audio_easy', 'audio_listening', 'audio_prefetch', 'audio_start',
                 'audio_realtime', 'audio_effects', 'subtitle_presentation',
                 'reliability', 'foryou_search', 'empty_subtitle', 'lyric_phrase'):
        importlib.import_module('tests.' + name + '_contracts')
    with tempfile.TemporaryDirectory(prefix='botube-index-check-') as directory:
        destination = Path(directory)
        subprocess.run(['git', 'checkout-index', '--all', '--prefix=' + destination.as_posix() + '/'],
                       cwd=ROOT, check=True, capture_output=True)
        redirected = {module: destination for module in tuple(sys.modules.values())
                      if module is not None and vars(module).get('ROOT') == ROOT}
        from contextlib import ExitStack
        with ExitStack() as stack:
            for module, target in redirected.items():
                stack.enter_context(patch.object(module, 'ROOT', target))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            if not result.wasSuccessful():
                raise SystemExit(1)


if __name__ == '__main__':
    main()
