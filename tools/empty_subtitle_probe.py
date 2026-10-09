"""Actual offline ASR/export/save on synthetic silence and nonvocal music.

Each GPU job uses a fresh interpreter, output only in docs/empty-subtitles.
This is not an instrumental classifier or annotated real-video benchmark.
"""
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/empty-subtitles'


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def fixtures():
    directory = OUTPUT / 'media'
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ('silence', 'nonvocal-chords'):
        path = directory / f'{name}.wav'
        samples = array('h')
        for index in range(12 * 16000):
            time = index / 16000
            value = 0.0
            if name == 'nonvocal-chords':
                frequencies = ((261.63, 329.63, 392), (293.66, 349.23, 440),
                               (329.63, 392, 493.88), (261.63, 349.23, 440))[int(time / 3)]
                local = time % 3
                envelope = min(1.0, local / .1, (3 - local) / .25)
                value = envelope * sum(math.sin(2 * math.pi * f * time) for f in frequencies) / 3
            samples.append(round(value * 6000))
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(samples.tobytes())
        paths.append(path)
    return paths


def child(media, output):
    from asr_coverage_probe import production_probe
    from faster_whisper import WhisperModel
    from unittest.mock import patch
    def local_model(model_path, **kwargs):
        if not (Path(model_path) / 'model.bin').is_file() or not kwargs.get('local_files_only'):
            raise RuntimeError('Probe refuses model downloads or nonlocal fallback')
        return WhisperModel(model_path, **kwargs)
    with patch('faster_whisper.WhisperModel', side_effect=local_model):
        production_probe([media], output, 'large-v3', 'cuda')


def main():
    if not (ROOT / 'app_resources/whisper_models/large-v3/model.bin').is_file():
        raise SystemExit('Local large-v3 is missing; probe never downloads it')
    before = digest(ROOT / 'storage/subtitles')
    reports = []
    for media in fixtures():
        output = OUTPUT / media.stem
        output.mkdir(parents=True, exist_ok=True)
        with (output / 'run-log.txt').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', str(media),
                '--output', str(output)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        rows = json.loads((output / f'{media.stem}-production.json').read_text(encoding='utf-8'))
        sys.path.insert(0, str(ROOT / 'app'))
        from core.subtitle_manager import SubtitleManager, SubtitleStatus
        manager = SubtitleManager(str(output / 'probe-storage'))
        result = manager.request_subtitle(media)
        # Production probe uses the synthetic ID 'probe-0', so check that cache
        # explicitly as well as a normal ID through a separate isolated save.
        probe_ass = manager.get_path('probe-0', 'ass')
        cache = manager._is_valid_ass(probe_ass)
        saved = manager.get_raw_data('probe-0')['segments']
        if not rows:
            normal_id = manager.get_reliable_id(media)
            manager.save_segments(normal_id, [], str(media))
            result = manager.request_subtitle(media)
        report = dict(fixture=media.name, duration=12, cues=len(rows), saved_cues=len(saved),
                      header_cache_valid=cache, empty_result=(not rows),
                      normal_id_cached_ready=(result.status == SubtitleStatus.READY),
                      reference='Synthesized silence/nonvocal sine chords, not an annotated user video')
        reports.append(report)
        print(json.dumps(report), flush=True)
    summary = dict(reports=reports, old_subtitle_files=len(before),
                   old_subtitle_bytes_unchanged=(before == digest(ROOT / 'storage/subtitles')))
    (OUTPUT / 'production-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    if not summary['old_subtitle_bytes_unchanged'] or not all(
            r['empty_result'] and r['header_cache_valid'] and r['normal_id_cached_ready'] for r in reports):
        raise SystemExit('Unexpected recognition/cache result; inspect production-summary.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.output)
    else:
        main()
