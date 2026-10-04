"""Review phase sources in a disposable Git index; user index stays untouched."""
import os
from pathlib import Path
import subprocess
import tempfile

from tools import check_audio_checkout as gates

ROOT = Path(__file__).resolve().parents[1]
PHASE_PATHS = (
    '.gitattributes', 'app/ui/media_info_probe.py', 'app/ui/video_info_popup.py',
    'app/ui/playback_bar.py', 'app/ui/main_window.py', 'tests/media_info_contracts.py',
    'tests/audio_easy_contracts.py', 'tests/test_media_info.py', 'tests/test_ui_media_surface.py',
    'docs/media-info', 'app/control/volume_settings.py', 'build_app.py',
    'app/ui/pages/settings.py',
    'tests/volume_build_contracts.py', 'tests/test_volume_build.py', 'docs/volume-build',
)


def main():
    with tempfile.TemporaryDirectory(prefix='botube-metadata-index-') as directory:
        index = str(Path(directory) / 'review.index')
        env = dict(os.environ, GIT_INDEX_FILE=index)
        subprocess.run(['git', 'read-tree', 'HEAD'], cwd=ROOT, env=env, capture_output=True, check=True)
        subprocess.run(['git', 'add', '--', *PHASE_PATHS], cwd=ROOT, env=env, capture_output=True, check=True)
        whitespace = subprocess.run(['git', 'diff', '--cached', '--check'], cwd=ROOT, env=env, capture_output=True)
        if whitespace.returncode:
            raise RuntimeError(whitespace.stdout.decode('utf-8', errors='replace') + whitespace.stderr.decode('utf-8', errors='replace'))
        previous = os.environ.get('GIT_INDEX_FILE')
        os.environ['GIT_INDEX_FILE'] = index
        try:
            gates.TARGETS += ('tests.test_media_info.MetadataScopeTests',
                             'tests.test_ui_media_surface.PresentationAdapterSourceGate',
                             'tests.test_volume_build.VolumeSourceScopeTests')
            gates.main()
        finally:
            if previous is None:
                os.environ.pop('GIT_INDEX_FILE', None)
            else:
                os.environ['GIT_INDEX_FILE'] = previous


if __name__ == '__main__':
    main()
