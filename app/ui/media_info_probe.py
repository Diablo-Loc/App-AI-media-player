"""Read-only original-source information, with one latest owned background job."""
from collections import OrderedDict
from datetime import datetime
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication
from control.worker_lifecycle import OwnedProcesses, WorkerOwner

UNKNOWN = 'Chưa rõ'
STREAM_KEYS = ('v_codec', 'resolution', 'fps', 'aspect', 'a_codec', 'sample_rate', 'channels', 'bitrate')
CACHE_LIMIT = 32


def item_snapshot(item):
    def value(key, default=''):
        return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)
    return {key: value(key) for key in ('title', 'artist', 'id', 'duration', 'mtime')} | {
        'path': str(value('path') or value('file_path') or ''),
        'description': str(value('description') or value('synopsis') or value('comment') or '').replace('\r\n', '\n'),
    }


def positive(value):
    try:
        number = float(Fraction(str(value)))
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None


def stream_fields(info):
    """Missing measurements are unknown; attached cover art is not a video."""
    fields = dict.fromkeys(STREAM_KEYS, UNKNOWN)
    streams = info.get('streams', [])
    def choose(kind):
        candidates = [s for s in streams if s.get('codec_type') == kind and
                      not (kind == 'video' and s.get('disposition', {}).get('attached_pic'))]
        return next((s for s in candidates if s.get('disposition', {}).get('default')), candidates[0] if candidates else None)
    video, audio = choose('video'), choose('audio')
    if video is None:
        fields.update(v_codec='Không có', resolution='N/A', fps='N/A', aspect='N/A')
    else:
        fields['v_codec'] = video.get('codec_long_name') or video.get('codec_name') or UNKNOWN
        width, height = positive(video.get('width')), positive(video.get('height'))
        if width and height:
            fields['resolution'] = f'{int(width)} × {int(height)}'
        average = positive(video.get('avg_frame_rate'))
        fps = average or positive(video.get('r_frame_rate'))
        if fps:
            kind = 'trung bình' if average else 'danh định'
            fields['fps'] = f'{fps:.3f}'.rstrip('0').rstrip('.') + f' FPS ({kind})'
        aspect = video.get('display_aspect_ratio', '')
        if positive(str(aspect).replace(':', '/')):
            fields['aspect'] = aspect
        elif width and height:
            sar = video.get('sample_aspect_ratio', '1:1')
            ratio = Fraction(int(width), int(height)) * (Fraction(str(sar).replace(':', '/')) if positive(str(sar).replace(':', '/')) else 1)
            fields['aspect'] = f'{ratio.numerator}:{ratio.denominator}'
    if audio is None:
        fields.update(a_codec='Không có', sample_rate='N/A', channels='N/A', bitrate='N/A')
    else:
        fields['a_codec'] = audio.get('codec_long_name') or audio.get('codec_name') or UNKNOWN
        rate, channels, bitrate = (positive(audio.get(key)) for key in ('sample_rate', 'channels', 'bit_rate'))
        if rate:
            fields['sample_rate'] = f'{int(rate)} Hz'
        if channels:
            layout = audio.get('channel_layout')
            fields['channels'] = f'{int(channels)} kênh' + (f' ({layout})' if layout else '')
        if bitrate:
            fields['bitrate'] = f'{bitrate / 1000:.1f} kbps'
    return fields


def sidecars(path):
    return (Path(str(path) + '.info.json'), path.with_suffix('.info.json'), path.with_suffix('.json'))


def signature(path):
    stat = path.stat()
    return (str(path), stat.st_size, stat.st_mtime_ns)


def context(path):
    entries = []
    for sidecar in sidecars(path):
        try:
            entries.append(signature(sidecar))
        except OSError:
            entries.append((str(sidecar), None, None))
    return (signature(path), tuple(entries))


def probe_file(path, processes, cancelled, timeout=3):
    from paths import project_root, asset_dir
    name = 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'
    executable = next((str(p / name) for p in (project_root() / 'bin', project_root() / 'app_resources/bin', asset_dir('bin'))
                       if (p / name).is_file()), None) or shutil.which('ffprobe')
    if not executable:
        raise OSError('Không tìm thấy ffprobe')
    if cancelled():
        raise InterruptedError()
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0
    process = processes.track(subprocess.Popen([executable, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags))
    deadline = time.monotonic() + timeout
    try:
        while not cancelled():
            try:
                output, _ = process.communicate(timeout=0.1)
                if process.returncode:
                    raise OSError('Không đọc được thông tin luồng')
                return json.loads(output)
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Đọc thông tin quá thời gian')
        raise InterruptedError()
    finally:
        if process.poll() is None:
            processes.stop()
            processes.wait()  # Worker only; cancellation never waits on the GUI.
        processes.release(process)


def read_media_info(item, cache, processes, cancelled):
    description = item['description']
    result = {'stream': dict.fromkeys(STREAM_KEYS, UNKNOWN), 'description': description, 'general': {}, 'error': ''}
    try:
        if cancelled():
            raise InterruptedError()
        if not item['path']:
            raise FileNotFoundError()
        path = Path(item['path']).resolve(strict=True)
        before = context(path)
        key = (before, description, positive(item.get('duration')))
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        result['general'].update(filename=path.name, ext=path.suffix[1:].upper(),
            size=f'{before[0][1] / (1024*1024):.2f} MB',
            mtime=datetime.fromtimestamp(before[0][2] / 1e9).strftime('%Y-%m-%d %H:%M:%S'))
        if not description.strip():
            for sidecar in sidecars(path):
                if cancelled():
                    raise InterruptedError()
                try:
                    with sidecar.open(encoding='utf-8-sig') as handle:
                        data = json.load(handle)
                    text = data.get('description') or data.get('fulldescription') or data.get('synopsis')
                    if text and str(text).strip():
                        description = str(text).replace('\r\n', '\n')
                        break
                except (OSError, ValueError, AttributeError):
                    continue
        result['description'] = description
        info = probe_file(path, processes, cancelled)
        result['stream'] = stream_fields(info)
        duration = positive(info.get('format', {}).get('duration')) or positive(item.get('duration'))
        if duration:
            result['general']['duration'] = f'{int(duration // 60):02d}:{int(duration % 60):02d} ({duration:.2f} giây)'
        tags = info.get('format', {}).get('tags', {})
        if not description.strip():
            for tag in ('description', 'DESCRIPTION', 'synopsis', 'SYNOPSIS', 'comment', 'COMMENT'):
                if tags.get(tag) and str(tags[tag]).strip():
                    result['description'] = str(tags[tag]).replace('\r\n', '\n')
                    break
        if cancelled():
            raise InterruptedError()
        if context(path) != before:
            raise OSError('Tệp thay đổi trong khi đọc; mở lại để cập nhật')
        cache[key] = result
        while len(cache) > CACHE_LIMIT:
            cache.popitem(last=False)
    except InterruptedError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, OverflowError) as error:
        result['stream'] = dict.fromkeys(STREAM_KEYS, UNKNOWN)
        result['error'] = str(error) or 'Không tìm thấy tệp'
    return result


def media_info_owner():
    application = QApplication.instance()
    owner = getattr(application, '_media_info_worker_owner', None)
    if owner is None or owner.closed:
        owner = WorkerOwner(application)
        application._media_info_worker_owner = owner
        application.aboutToQuit.connect(owner.shutdown)
    return owner


class MediaInfoWorker(QThread):
    ready = Signal(int, object)

    def __init__(self, generation, item, cache):
        super().__init__()
        self.generation, self.item, self.cache = generation, item, cache
        self.processes = OwnedProcesses()

    def stop(self):
        self.requestInterruption()
        # The worker observes cancellation within 100 ms and reaps its process.

    def run(self):
        try:
            result = read_media_info(self.item, self.cache, self.processes, self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.ready.emit(self.generation, result)
        except InterruptedError:
            pass


class MediaInfoRequests(QObject):
    ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache = OrderedDict()
        self.generation = 0
        self.worker = None
        self.pending = None
        self.owner = media_info_owner()

    def request(self, item):
        self.cancel()
        if not self.owner.closed:
            self.pending = (self.generation, dict(item))
            self._start()

    def cancel(self):
        self.generation += 1
        self.pending = None
        if self.worker is not None:
            self.worker.stop()

    def _start(self):
        if self.worker is not None or self.pending is None or self.owner.closed:
            return
        generation, item = self.pending
        self.pending = None
        self.worker = MediaInfoWorker(generation, item, self.cache)
        self.owner.own(self.worker)
        self.worker.ready.connect(self._accept)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    @Slot(int, object)
    def _accept(self, generation, result):
        if generation == self.generation and not self.owner.closed:
            self.ready.emit(result)

    @Slot()
    def _finished(self):
        self.worker = None
        self._start()
