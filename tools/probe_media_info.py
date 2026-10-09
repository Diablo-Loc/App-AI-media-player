"""Read-only real-video popup checks and a separate slow-reader GUI workload."""
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time
from unittest.mock import patch

from tools.ui_preview import APPLICATION, pump
from PySide6.QtCore import QTimer
from ui.video_info_popup import VideoInfoPopup
from ui import media_info_probe as probe

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'docs/media-info'


def wait(predicate, timeout=10):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        pump(5)
    if not predicate():
        raise RuntimeError('Metadata did not complete')


def main():
    popup = VideoInfoPopup()
    rows, calls = [], []
    original_probe = probe.probe_file
    def tracked(*args, **kwargs):
        calls.append(str(args[0]))
        return original_probe(*args, **kwargs)
    try:
        with patch.object(probe, 'probe_file', side_effect=tracked):
            for path in sorted((ROOT / 'video').glob('*.mp4')):
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                start = time.perf_counter()
                popup.update_info({'path': str(path), 'title': path.stem})
                submitted = time.perf_counter()
                wait(lambda: popup._info_requests.worker is None)
                complete = time.perf_counter()
                fields = {key: label.text() for key, label in popup.fields_stream.items()}
                oracle = json.loads(subprocess.run([str(ROOT / 'bin/ffprobe.exe'), '-v', 'error',
                    '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True,
                    check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout)
                streams = oracle['streams']
                video = next(s for s in streams if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic'))
                audio = next(s for s in streams if s['codec_type'] == 'audio')
                assert fields['resolution'] == f"{video['width']} × {video['height']}"
                assert fields['sample_rate'] == f"{audio['sample_rate']} Hz"
                assert fields['v_codec'] == (video.get('codec_long_name') or video['codec_name'])
                assert fields['a_codec'] == (audio.get('codec_long_name') or audio['codec_name'])
                count = len(calls)
                popup.update_info({'path': str(path), 'title': path.stem})
                wait(lambda: popup._info_requests.worker is None)
                assert len(calls) == count
                assert fields == {key: label.text() for key, label in popup.fields_stream.items()}
                assert hashlib.sha256(path.read_bytes()).hexdigest() == before
                rows.append({'source': str(path), 'sha256': before, 'unchanged': True,
                    'submission_ms': (submitted-start)*1000, 'completion_ms': (complete-start)*1000,
                    'cached_reopen_probe_calls': 0, 'fields': fields})
        # Slow reader is a distinct fault workload, not a native screen benchmark.
        ticks, started = [], threading.Event()
        def slow(path, processes, cancelled):
            started.set()
            end = time.monotonic() + .25
            while time.monotonic() < end:
                if cancelled():
                    raise InterruptedError()
                time.sleep(.005)
            return {'streams': [], 'format': {}}
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        try:
            with patch.object(probe, 'probe_file', side_effect=slow):
                begin = time.perf_counter()
                popup.update_info({'path': str(ROOT / 'video/A Small Miracle(short).mp4'), 'description': 'uncached fault context'})
                submitted = time.perf_counter()
                wait(started.is_set)
                wait(lambda: popup._info_requests.worker is None)
                fault = {'injected_reader_ms': 250, 'submission_ms': (submitted-begin)*1000,
                         'completion_ms': (time.perf_counter()-begin)*1000, 'gui_10ms_ticks': len(ticks)}
                assert len(ticks) > 5
        finally:
            timer.stop()
        before_saved = json.loads((DESTINATION / 'saved-before.json').read_text(encoding='utf-8'))
        checks = [dict(row, unchanged=hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() == row['sha256']) for row in before_saved]
        assert all(row['unchanged'] for row in checks)
        (DESTINATION / 'saved-file-check.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
        (DESTINATION / 'real-media-probe.json').write_text(json.dumps({'videos': rows, 'probe_calls': len(calls), 'slow_reader': fault}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'videos': len(rows), 'first_open_probe_calls': len(calls), 'cached_reopen_probe_calls': 0,
                          'saved_hashes_unchanged': len(checks), 'slow_reader': fault}, ensure_ascii=False))
    finally:
        popup.reject()
        popup._info_requests.owner.shutdown()
        popup.deleteLater()
        pump(20)


if __name__ == '__main__':
    main()
