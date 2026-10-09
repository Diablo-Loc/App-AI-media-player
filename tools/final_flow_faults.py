"""Read-only fault/accuracy probes; document findings, never freeze a defect."""
import ast
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.ui_preview import APPLICATION, ROOT, pump
from PySide6.QtCore import QTimer
from core.media_library import MediaLibrary, MediaMetadata
from thumbnail.thumbnail_workers import ThumbnailWorker
from ui.video_info_popup import VideoInfoPopup

DESTINATION = ROOT / 'docs/final-flow-review'


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1048576), b''):
            result.update(chunk)
    return result.hexdigest()


def method(source, name):
    return next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == name)


def original_matches(relative, name):
    before = subprocess.run(['git', 'show', '4148c138c1e38f4959574caf925f1c86dbcca339:' + relative],
                            cwd=ROOT, capture_output=True, check=True).stdout.decode('utf-8-sig')
    current = (ROOT / relative).read_text(encoding='utf-8-sig')
    try:
        return ast.dump(method(before, name)) == ast.dump(method(current, name))
    except StopIteration:
        return False


def early_exception():
    source = (ROOT / 'app/run_app.py').read_text(encoding='utf-8-sig')
    namespace = {'logging': Mock(), 'sys': SimpleNamespace(__excepthook__=Mock(), exit=Mock())}
    exec(compile(ast.Module(body=[method(source, 'global_exception_handler')], type_ignores=[]),
                 'app/run_app.py', 'exec'), namespace)
    error = None
    try:
        namespace['global_exception_handler'](ImportError, ImportError('synthetic pre-Qt import failure'), None)
    except Exception as failure:
        error = {'type': type(failure).__name__, 'message': str(failure)}
    return {'secondary_error': error, 'default_hook_reached': namespace['sys'].__excepthook__.called,
            'same_function_as_original': original_matches('app/run_app.py', 'global_exception_handler')}


def media_info():
    path = sorted((ROOT / 'video').glob('*.mp4'))[0]
    before = sha(path)
    data = json.loads(subprocess.run([str(ROOT / 'bin/ffprobe.exe'), '-v', 'error', '-show_streams',
        '-show_format', '-of', 'json', str(path)], capture_output=True, check=True, timeout=5).stdout)
    video = next((row for row in data['streams'] if row['codec_type'] == 'video'), {})
    audio = next((row for row in data['streams'] if row['codec_type'] == 'audio'), {})
    item = SimpleNamespace(path=str(path), title=path.stem, duration=float(data['format']['duration']),
                           mtime=path.stat().st_mtime, id='probe', artist='probe')
    popup = VideoInfoPopup()
    with patch.object(popup, 'get_description_for_item', return_value=''):
        popup.update_info(item)
    displayed = {key: label.text() for key, label in popup.fields_stream.items()}
    actual = {'v_codec': video.get('codec_name'), 'resolution': [video.get('width'), video.get('height')],
              'fps': float(Fraction(video.get('avg_frame_rate', '0/1'))), 'a_codec': audio.get('codec_name'),
              'sample_rate': audio.get('sample_rate'), 'channels': audio.get('channels'), 'audio_bitrate': audio.get('bit_rate')}
    checks = {'resolution_matches': displayed['resolution'].startswith(f"{video.get('width')} x {video.get('height')}"),
              'fps_matches': abs(float(displayed['fps'].split()[0]) - actual['fps']) < .02,
              'sample_rate_matches': displayed['sample_rate'].startswith(str(actual['sample_rate']))}
    popup.close()
    popup.deleteLater()
    pump(10)
    return {'source': path.name, 'source_unchanged': sha(path) == before, 'actual_ffprobe': actual,
            'displayed': displayed, **checks,
            'same_function_as_original': original_matches('app/ui/video_info_popup.py', 'update_info')}


def description_heartbeat():
    popup, ticks, calls = VideoInfoPopup(), [], []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    timer.start()
    pump(30)
    with tempfile.TemporaryDirectory(prefix='botube-description-probe-') as directory:
        source = Path(directory) / 'fixture.mp4'
        source.write_bytes(b'probe only: ffprobe is mocked')
        item = SimpleNamespace(path=str(source), title='fixture', duration=0, mtime=0, id='probe')

        def slow_probe(*args, **kwargs):
            calls.append({'timeout': kwargs.get('timeout')})
            time.sleep(.25)
            return SimpleNamespace(stdout=b'{"format":{"tags":{}}}')

        count = len(ticks)
        started = time.perf_counter()
        with patch('ui.video_info_popup.subprocess.run', side_effect=slow_probe):
            popup.update_info(item)
        blocked_ms, heartbeat = (time.perf_counter() - started)*1000, len(ticks)-count
    timer.stop()
    popup.close()
    popup.deleteLater()
    pump(10)
    return {'fixture': 'synthetic 250ms ffprobe, no network or real slow-disk claim',
            'update_info_ms': blocked_ms, 'gui_ticks_during_call': heartbeat, 'ffprobe_calls': calls,
            'same_function_as_original': original_matches('app/ui/video_info_popup.py', 'get_description_for_item')}


def thumbnail_saves():
    count = 100
    library = MediaLibrary.__new__(MediaLibrary)
    library.lock = threading.RLock()
    library.items = {str(i): MediaMetadata(str(i), 'unused', 'fixture') for i in range(count)}
    serialized = []
    library.save = Mock(side_effect=lambda: serialized.append(len(library.items)))
    worker = ThumbnailWorker(library)
    with patch('thumbnail.thumbnail_workers.ThumbnailManager.get_thumbnail', return_value='fixture.jpg'), \
         patch.object(worker, 'msleep'):
        worker.run()
    worker.deleteLater()
    pump(10)
    return {'items': count, 'full_library_save_calls': library.save.call_count,
            'entries_that_would_be_serialized': sum(serialized),
            'fixture': 'operation counts; save/FFmpeg/sleep mocked, no disk/CPU benchmark',
            'same_function_as_original': original_matches('app/core/media_library.py', 'update_thumbnail_in_db')}


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    report = {'early_exception': early_exception(), 'media_info': media_info(),
              'description_gui': description_heartbeat(), 'thumbnail_saves': thumbnail_saves()}
    (DESTINATION / 'fault-probes.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
