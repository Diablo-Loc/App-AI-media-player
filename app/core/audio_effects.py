"""Owned, bounded Matroska/FLAC playback cache; source files are read-only."""
from dataclasses import asdict
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from core.audio_profile import PROCESSOR_VERSION, choose_gain, tone_filter, render_filter
from core.subtitle_persistence import atomic_bytes

CACHE_LIMIT = 1024 * 1024 * 1024
OWNER_MARKER = 'botube-audio-effects'
ENTRY_PATTERN = re.compile(r'^[0-9a-f]{64}\.mkv$')
PARTIAL_PATTERN = re.compile(r'^[0-9a-f]{64}-[0-9a-f]{32}\.part\.json$')


class AudioPreparationCancelled(Exception):
    pass


def find_tool(name):
    from paths import project_root, asset_dir
    executable = name + ('.exe' if os.name == 'nt' else '')
    for directory in (project_root() / 'bin', project_root() / 'app_resources/bin', asset_dir('bin')):
        candidate = directory / executable
        if candidate.is_file():
            return str(candidate)
    tool = shutil.which(name)
    if tool:
        return tool
    raise RuntimeError(f'Không tìm thấy {name}; âm thanh gốc vẫn được giữ.')


def source_signature(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    return {'path': str(path), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def cache_key(signature, profile, track):
    data = {'source': signature, 'profile': profile.as_dict(), 'track': track, 'version': PROCESSOR_VERSION}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode('utf-8')).hexdigest()


class AudioPlaybackCache:
    def __init__(self, root, limit=CACHE_LIMIT):
        self.root = Path(root).resolve()
        self.limit = limit

    def _owned(self, path):
        path = Path(path)
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError('Audio cache path outside owned root')
        return path

    def lookup(self, key):
        target = self._owned(self.root / f'{key}.mkv')
        metadata = self._owned(target.with_suffix('.json'))
        try:
            record = json.loads(metadata.read_text(encoding='utf-8'))
            if not isinstance(record, dict):
                return None
            gain = record.get('gain')
            if (record.get('version') != PROCESSOR_VERSION or not isinstance(gain, dict)
                    or not isinstance(gain.get('gain_db'), (int, float))
                    or not math.isfinite(gain['gain_db']) or not isinstance(gain.get('peak_limited'), bool)):
                return None
            if (record.get('owner') != OWNER_MARKER or record['key'] != key
                    or target.stat().st_size != record['output_bytes'] or not target.stat().st_size):
                return None
            os.utime(metadata, None)
            return {'path': str(target), 'record': record, 'cache_hit': True}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def prune(self, protected=(), reserve=0):
        self.root.mkdir(parents=True, exist_ok=True)
        self.recover_partials()
        protected = {str(Path(path).resolve()) for path in protected}
        entries = []
        for target in self.root.glob('*.mkv'):
            if not ENTRY_PATTERN.fullmatch(target.name) or target.is_symlink():
                continue
            self._owned(target)
            metadata = self._owned(target.with_suffix('.json'))
            try:
                record = json.loads(metadata.read_text(encoding='utf-8'))
                if not isinstance(record, dict) or record.get('owner') != OWNER_MARKER or record.get('key') != target.stem:
                    continue
                touched = metadata.stat().st_mtime
                entries.append((touched, target, metadata, target.stat().st_size))
            except (OSError, ValueError, TypeError):
                continue
        total = sum(entry[3] for entry in entries)
        for _, target, metadata, size in sorted(entries):
            if total + reserve <= self.limit:
                break
            if str(target.resolve()) in protected:
                continue
            try:
                self._owned(target).unlink()
                if metadata.exists():
                    self._owned(metadata).unlink()
                total -= size
            except OSError:
                continue
        if total + reserve > self.limit:
            raise RuntimeError('Cache âm thanh đã đầy; giữ âm thanh gốc cho bài này.')

    def recover_partials(self):
        """Remove only journal-owned leftovers whose creating app has exited."""
        import psutil
        for journal in self.root.glob('*.part.json'):
            if not PARTIAL_PATTERN.fullmatch(journal.name) or journal.is_symlink():
                continue
            partial = journal.with_suffix('.mkv')
            try:
                self._owned(journal)
                self._owned(partial)
                record = json.loads(journal.read_text(encoding='utf-8'))
                if (not isinstance(record, dict) or record.get('owner') != OWNER_MARKER
                        or record.get('partial') != partial.name):
                    continue
                pid, created = int(record['pid']), float(record['created'])
                try:
                    if psutil.Process(pid).create_time() == created:
                        continue
                except psutil.NoSuchProcess:
                    pass
                if partial.exists():
                    partial.unlink()
                journal.unlink()
            except (OSError, ValueError, KeyError, TypeError, psutil.Error):
                continue


def run_tool(command, processes, cancelled, timeout=600):
    if cancelled():
        raise AudioPreparationCancelled()
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    process = processes.track(subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              creationflags=flags))
    started = time.monotonic()
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancelled() or time.monotonic() - started > timeout:
                    processes.stop()
                    processes.wait()
                    if cancelled():
                        raise AudioPreparationCancelled()
                    raise RuntimeError('Xử lý âm thanh quá thời gian; giữ bản gốc.')
        if cancelled():
            raise AudioPreparationCancelled()
        if process.returncode:
            detail = stderr.decode('utf-8', errors='replace')[-2000:]
            logging.debug('Audio preparation tool failed: %s', detail)
            raise RuntimeError('Không chuẩn bị được âm thanh cho bài này; giữ bản gốc.')
        return stdout, stderr
    finally:
        if process.poll() is None:
            processes.stop()
            processes.wait()
        processes.release(process)


def prepare_audio(source, profile, track, cache, processes, cancelled, protected=(), progress=lambda text: None):
    signature = source_signature(source)
    key = cache_key(signature, profile, track)
    hit = cache.lookup(key)
    if hit:
        return hit
    ffmpeg, ffprobe = find_tool('ffmpeg'), find_tool('ffprobe')
    stdout, _ = run_tool([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', signature['path']],
                         processes, cancelled, timeout=20)
    info = json.loads(stdout)
    streams = [stream for stream in info.get('streams', []) if stream.get('codec_type') == 'audio']
    if not streams:
        raise RuntimeError('Bài này không có luồng âm thanh; giữ bản gốc.')
    if track < 0 or track >= len(streams):
        raise RuntimeError('Luồng âm thanh đã đổi; giữ bản gốc.')
    audio = streams[track]
    duration = float(info.get('format', {}).get('duration', 0))
    # Bound preparation disk space using worst-case uncompressed 24-bit audio.
    estimate = signature['size'] + max(0, duration) * int(audio.get('sample_rate', 48000)) * int(audio.get('channels', 2)) * 3
    estimate = int(estimate * 1.05 + 1024 * 1024)
    cache.prune(protected, reserve=estimate)
    if shutil.disk_usage(cache.root).free < estimate + 64 * 1024 * 1024:
        raise RuntimeError('Không đủ dung lượng cache; giữ âm thanh gốc.')
    progress('Đang đo độ lớn và đỉnh âm thanh…')
    sample_rate = int(audio.get('sample_rate', 48000))
    channels = int(audio.get('channels', 2))
    eq = tone_filter(profile, sample_rate, channels)
    analysis = ','.join(part for part in (eq, 'loudnorm=I=-18:TP=-1.5:LRA=50:print_format=json') if part)
    _, stderr = run_tool([ffmpeg, '-nostdin', '-hide_banner', '-threads', '1', '-filter_threads', '1',
                         '-i', signature['path'], '-map', f'0:a:{track}', '-vn', '-sn', '-dn',
                         '-af', analysis, '-f', 'null', '-'], processes, cancelled)
    blocks = re.findall(rb'\{\s*"input_i".*?\}', stderr, flags=re.DOTALL)
    if not blocks:
        raise RuntimeError('Không đo được âm lượng; giữ âm thanh gốc.')
    decision = choose_gain(json.loads(blocks[-1]), profile)
    progress('Đang chuẩn bị âm thanh chất lượng cao…')
    target = cache._owned(cache.root / f'{key}.mkv')
    partial = cache._owned(cache.root / f'{key}-{uuid.uuid4().hex}.part.mkv')
    journal = cache._owned(partial.with_suffix('.json'))
    if target.exists():
        try:
            record = json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
            if not isinstance(record, dict) or record.get('owner') != OWNER_MARKER or record.get('key') != key:
                raise ValueError()
        except (OSError, ValueError, TypeError):
            raise RuntimeError('Không ghi đè file không thuộc cache âm thanh.')
    published = replaced = False
    try:
        import psutil
        atomic_bytes(journal, json.dumps({'owner': OWNER_MARKER, 'partial': partial.name,
                                          'pid': os.getpid(), 'created': psutil.Process().create_time()}).encode('utf-8'))
        run_tool([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1',
                  '-filter_threads', '1', '-i', signature['path'], '-map', '0', '-map_metadata', '0',
                  '-map_chapters', '0', '-c', 'copy', f'-c:a:{track}', 'flac', f'-filter:a:{track}',
                  render_filter(profile, decision, sample_rate, channels), f'-sample_fmt:a:{track}', 's32',
                  f'-threads:a:{track}', '1', '-compression_level', '5', '-f', 'matroska', str(partial)], processes, cancelled)
        if cancelled():
            raise AudioPreparationCancelled()
        if source_signature(source) != signature:
            raise RuntimeError('File nguồn vừa thay đổi; chưa áp dụng bản xử lý.')
        size = partial.stat().st_size
        cache.prune(protected, reserve=size)
        if not size:
            raise RuntimeError('Bản xử lý rỗng; giữ bản gốc.')
        os.replace(partial, target)
        replaced = True
        record = {'owner': OWNER_MARKER, 'key': key, 'source': signature, 'profile': profile.as_dict(), 'track': track,
                  'version': PROCESSOR_VERSION, 'output_bytes': size, 'gain': asdict(decision)}
        atomic_bytes(target.with_suffix('.json'), json.dumps(record, ensure_ascii=False).encode('utf-8'))
        published = True
        return {'path': str(target), 'record': record, 'cache_hit': False}
    finally:
        if partial.exists():
            cache._owned(partial).unlink()
        if journal.exists():
            cache._owned(journal).unlink()
        if replaced and not published and target.exists():
            cache._owned(target).unlink()
