"""Offline command/selection, Qt preference and real FFmpeg packet checks."""
import ast
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegMergerPP, FFmpegVideoRemuxerPP, FFmpegMetadataPP, FFmpegExtractAudioPP
from tools.ui_preview import APPLICATION
from PySide6.QtWidgets import QWidget
from app.download_core.download_options import ORIGINAL, QUALITIES, build_download_command
from download_core.download_worker import DownloadWorker
from ui.pages.settings_dialog import SettingMenu
from ui.pages.download import DownloadPage
from tests.download_quality_contracts import before_download_changes

ROOT = Path(__file__).resolve().parents[1]


def parsed_command(fmt, quality=ORIGINAL, resolution='720p'):
    command = build_download_command('yt-dlp.exe', 'target', '100% Song',
                                     'https://example.invalid/watch?v=a',
                                     {'download': {'format': fmt, 'quality': quality,
                                                   'resolution': resolution}})
    return command, yt_dlp.parse_options(command[1:]).ydl_opts


def media_format(identity, ext, height=None, audio='none', video='none'):
    result = dict(format_id=identity, ext=ext, acodec=audio, vcodec=video,
                  url='https://example.invalid/' + identity, protocol='https')
    if height is not None:
        result['height'] = height
    return result


class DownloadPolicyTests(unittest.TestCase):
    def select(self, fmt, quality, formats):
        _, params = parsed_command(fmt, quality)
        with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
            return list(ydl.build_format_selector(params['format'])(
                dict(formats=formats, incomplete_formats=False)))

    def test_all_presets_parse_and_source_modes_have_no_lossy_override(self):
        for fmt in ('Video MP4', 'Video MKV', 'Audio MP3'):
            for quality in QUALITIES:
                with self.subTest(fmt=fmt, quality=quality):
                    command, params = parsed_command(fmt, quality)
                    self.assertEqual(command.count('https://example.invalid/watch?v=a'), 1)
                    self.assertEqual(command.count('-o'), 1)
                    self.assertNotIn('--ignore-config', command)
                    self.assertEqual(command[-2], '--')
                    self.assertTrue(command[command.index('-o')+1].endswith('100%% Song.%(ext)s'))
                    args = params.get('postprocessor_args', {})
                    if fmt == 'Video MP4' and 'Low' in quality:
                        self.assertEqual(list(args), ['metadata+ffmpeg_o'])
                        self.assertEqual(args['metadata+ffmpeg_o'], ['-c:a', 'aac', '-b:a', '128k'])
                    else:
                        self.assertFalse(args)
                    if fmt.startswith('Video'):
                        container = 'mkv' if fmt == 'Video MKV' else 'mp4'
                        self.assertEqual(params['merge_output_format'], container)
                        remux = next(p for p in params['postprocessors'] if p['key'] == 'FFmpegVideoRemuxer')
                        self.assertEqual(remux['preferedformat'], container)

    def test_bounded_fallback_never_selects_1080_for_720(self):
        sources = [media_format('1080', 'mp4', 1080, 'aac', 'h264')]
        for fmt in ('Video MP4', 'Video MKV'):
            for quality in QUALITIES:
                self.assertEqual(self.select(fmt, quality, sources), [])
        sources.insert(0, media_format('360', 'mp4', 360, 'aac', 'h264'))
        self.assertEqual(self.select('Video MP4', ORIGINAL, sources)[0]['format_id'], '360')

    def test_video_sources_without_aac_fall_back_to_opus_without_transcoding(self):
        sources = [media_format('opus', 'webm', audio='opus'),
                   media_format('v720', 'mp4', 720, video='h264')]
        for quality in QUALITIES:
            self.assertEqual(self.select('Video MP4', quality, sources)[0]['format_id'], 'v720+opus')

    def test_original_and_legacy_preferences_select_separate_source_audio(self):
        sources = [media_format('aac', 'm4a', audio='mp4a.40.2'),
                   media_format('opus', 'webm', audio='opus'),
                   media_format('v720', 'mp4', 720, video='h264'),
                   media_format('bundled', 'mp4', 720, 'aac', 'h264')]
        for quality, expected in ((ORIGINAL, 'opus'), ('Extreme (320k)', 'aac'),
                                  ('Standard (M4A-ACC)', 'aac'), ('High (Opus)', 'opus')):
            self.assertEqual(self.select('Video MP4', quality, sources)[0]['format_id'], 'v720+'+expected)
        self.assertEqual(self.select('Video MKV', 'High (Opus)', sources)[0]['format_id'], 'v720+opus')

    def test_audio_codec_preserving_modes_do_not_fall_back_to_lossy_encoding(self):
        opus = [media_format('opus', 'webm', audio='opus')]
        aac = [media_format('aac', 'm4a', audio='mp4a.40.2')]
        self.assertEqual(self.select('Audio MP3', 'Standard (M4A-ACC)', opus), [])
        self.assertEqual(self.select('Audio MP3', 'High (Opus)', aac), [])
        for sources in (opus, aac):
            self.assertTrue(self.select('Audio MP3', ORIGINAL, sources))
        _, params = parsed_command('Audio MP3', ORIGINAL)
        self.assertFalse(any(p['key'] == 'FFmpegExtractAudio' for p in params['postprocessors']))

    def test_flat_nested_options_default_and_input_are_unchanged(self):
        flat = {'format': 'Video MP4', 'quality': 'Standard (M4A-ACC)', 'resolution': '4K'}
        nested = {'appearance': {'theme': 'dark'}, 'download': copy.deepcopy(flat)}
        before = copy.deepcopy(nested)
        flat_cmd = build_download_command('engine', '.', 'song', 'link', flat)
        self.assertEqual(flat_cmd, build_download_command('engine', '.', 'song', 'link', nested))
        self.assertEqual(nested, before)
        default = build_download_command('engine', '.', 'song', 'link', {})
        self.assertNotIn('--postprocessor-args', default)
        self.assertIn('bv[height<=1080]+ba/b[height<=1080]', default)


class DownloadSettingsTests(unittest.TestCase):
    def test_legacy_presets_survive_ui_save_and_utf8_load(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = QWidget()
            parent.settings_file = str(Path(folder) / 'setting.json')
            for fmt, qualities in (('Video MP4', QUALITIES), ('Audio MP3', QUALITIES),
                                    ('Video MKV', (ORIGINAL, 'High (Opus)'))):
                for quality in qualities:
                    saved = {'appearance': {'unrelated': 'Tiếng Việt'},
                             'download': {'format': fmt, 'quality': quality, 'resolution': '2K',
                                          'unknown_option': 12, 'auto_update': True}}
                    menu = SettingMenu(parent, copy.deepcopy(saved))
                    self.assertEqual(menu.quality_combo.currentText(), quality)
                    menu.save_settings()
                    restored = DownloadPage.load_full_config(parent)
                    self.assertEqual(restored, saved)
                    self.assertTrue(menu.label_note.text())
                    menu.deleteLater()
            parent.deleteLater()

    def test_default_source_mode_and_notes_update_without_writing_settings(self):
        parent = QWidget()
        menu = SettingMenu(parent, {})
        self.assertEqual(menu.quality_combo.currentText(), ORIGINAL)
        menu.quality_combo.setCurrentText('Low (128k)')
        self.assertIn('128', menu.label_note.text())
        menu.format_combo.setCurrentText('Video MKV')
        self.assertEqual(menu.quality_combo.currentText(), ORIGINAL)
        self.assertIn('không ép Opus', menu.label_note.text())
        self.assertEqual(menu.settings, {})
        parent.deleteLater()


class DownloadWorkerTests(unittest.TestCase):
    def test_batch_signals_command_failure_and_resume_files(self):
        class Process:
            def __init__(self, code):
                self.stdout = io.StringIO('[download] fixture\n')
                self.code = code
            def wait(self, **kwargs): return self.code
            def poll(self): return self.code
        with tempfile.TemporaryDirectory() as folder:
            partial = Path(folder) / 'unrelated.part'
            partial.write_bytes(b'KEEP')
            worker = DownloadWorker(['first', 'second'], ['A', 'B'], folder,
                                    {'format': 'Video MKV', 'quality': ORIGINAL})
            commands, progress, failures, done, logs = [], [], [], [], []
            worker.progress_signal.connect(lambda a,b: progress.append((a,b)))
            worker.fail_signal.connect(lambda a,b: failures.append((a,b)))
            worker.finished_signal.connect(done.append)
            worker.log_signal.connect(logs.append)
            def spawn(command, **kw):
                commands.append(command)
                return Process(1 if command[-1] == 'first' else 0)
            with patch('download_core.download_worker.ensure_ytdlp_exists', return_value=True), \
                    patch('download_core.download_worker.subprocess.Popen', side_effect=spawn):
                worker.run()
            self.assertEqual(commands[0][1], '-U')
            self.assertEqual(len(commands), 3)
            self.assertEqual(progress, [(0,100), (1,2)])
            self.assertEqual(failures, [(1,2)])
            self.assertEqual(done, [1])
            self.assertFalse(worker._processes.processes)
            self.assertEqual(partial.read_bytes(), b'KEEP')
            self.assertFalse(any('Đã lưu B.mp4' in line for line in logs))


class DownloadMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='botube-download-media-')
        cls.folder = Path(cls.temporary.name)
        cls.ffmpeg = ROOT / 'bin/ffmpeg.exe'
        cls.ffprobe = ROOT / 'bin/ffprobe.exe'
        if not cls.ffmpeg.is_file() or not cls.ffprobe.is_file():
            cls.temporary.cleanup()
            raise unittest.SkipTest('portable FFmpeg required')
        cls.run_command([str(cls.ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                         'color=c=blue:s=160x90:r=15:d=2', '-c:v', 'libx264', '-an',
                         str(cls.folder/'video.mp4')])
        for codec, extension in (('aac','m4a'), ('libopus','webm')):
            cls.run_command([str(cls.ffmpeg), '-v', 'error', '-f', 'lavfi', '-i',
                             'sine=frequency=440:duration=2:sample_rate=48000', '-ac', '2',
                             '-c:a', codec, '-b:a', '160k', str(cls.folder/f'audio.{extension}')])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def run_command(command):
        return subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=20, check=True,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout

    def packets(self, path, track='a:0'):
        packets = json.loads(self.run_command([str(self.ffprobe), '-v','error', '-select_streams', track,
            '-show_packets', '-show_data_hash', 'sha256', '-show_entries', 'packet=data_hash',
            '-of','json', str(path)]))['packets']
        # Containers place skip/discard padding in different side-data fields.
        # Compare encoded payload, not that container metadata representation.
        return [packet['data_hash'] for packet in packets]

    def chain(self, container, quality, audio_ext):
        _, params = parsed_command('Video '+container.upper(), quality)
        params.update(ffmpeg_location=str(self.ffmpeg.parent), quiet=True, no_warnings=True)
        source = self.folder / ('audio.'+audio_ext)
        target = self.folder / (self._testMethodName+'-'+container+'-'+quality.split()[0]+'-'+audio_ext+'.'+container)
        info = dict(filepath=str(target), ext=container, title='Packet fixture', id='fixture',
                    requested_formats=[dict(vcodec='h264', acodec='none', protocol='https', filepath=str(self.folder/'video.mp4')),
                                       dict(vcodec='none', acodec='opus' if audio_ext=='webm' else 'aac', protocol='https', filepath=str(source))],
                    __files_to_merge=[str(self.folder/'video.mp4'), str(source)])
        with yt_dlp.YoutubeDL(params) as ydl:
            FFmpegMergerPP(ydl).run(info)
            FFmpegMetadataPP(ydl).run(info)
        return source, target

    def test_aac_opus_source_packets_and_video_survive_merge_and_metadata(self):
        for container in ('mp4','mkv'):
            for extension in ('m4a','webm'):
                source, target = self.chain(container, ORIGINAL, extension)
                self.assertEqual(self.packets(source), self.packets(target))
                self.assertEqual(self.packets(self.folder/'video.mp4','v:0'), self.packets(target,'v:0'))

    def test_progressive_remux_preserves_packets_and_expected_container(self):
        source, merged = self.chain('mkv', ORIGINAL, 'webm')
        _, params = parsed_command('Video MP4')
        params.update(ffmpeg_location=str(self.ffmpeg.parent), quiet=True, no_warnings=True)
        info = dict(filepath=str(merged), ext='mkv', title='Remux fixture')
        with yt_dlp.YoutubeDL(params) as ydl:
            _, info = FFmpegVideoRemuxerPP(ydl, preferedformat='mp4').run(info)
        self.assertTrue(info['filepath'].endswith('.mp4'))
        self.assertEqual(self.packets(source), self.packets(info['filepath']))
        self.assertEqual(self.packets(self.folder/'video.mp4','v:0'), self.packets(info['filepath'],'v:0'))

    def test_low_encodes_once_only_in_metadata_and_preserves_video(self):
        source, target = self.chain('mp4', 'Low (128k)', 'webm')
        self.assertNotEqual(self.packets(source), self.packets(target))
        details = json.loads(self.run_command([str(self.ffprobe), '-v','error','-show_streams','-of','json',str(target)]))
        audio = next(s for s in details['streams'] if s['codec_type']=='audio')
        self.assertEqual(audio['codec_name'], 'aac')
        self.assertLess(abs(int(audio['bit_rate'])-128000), 15000)
        self.assertEqual(self.packets(self.folder/'video.mp4','v:0'), self.packets(target,'v:0'))
        _, params = parsed_command('Video MP4','Low (128k)')
        with yt_dlp.YoutubeDL(params) as ydl:
            for pp in (FFmpegMergerPP(ydl), FFmpegVideoRemuxerPP(ydl)):
                self.assertEqual(pp._configuration_args('ffmpeg', ['_o1','_o','']), [])

    def test_audio_opus_and_aac_extract_keep_packet_payloads(self):
        for extension, codec in (('webm','opus'), ('m4a','m4a')):
            source = self.folder / ('audio.'+extension)
            work = self.folder / ('extract-'+extension+'.'+extension)
            work.write_bytes(source.read_bytes())
            with yt_dlp.YoutubeDL(dict(ffmpeg_location=str(self.ffmpeg.parent), quiet=True, no_warnings=True)) as ydl:
                _, info = FFmpegExtractAudioPP(ydl, preferredcodec=codec).run(dict(filepath=str(work),ext=extension))
            self.assertEqual(self.packets(source), self.packets(info['filepath']))


class DownloadSourceScopeTests(unittest.TestCase):
    def test_exact_snapshots_and_only_approved_production_methods_changed(self):
        from tools.capture_reliability_contracts import functions
        allowed = {
            'app/download_core/download_worker.py': {'DownloadWorker.__init__', 'DownloadWorker._run_download', 'DownloadWorker.cleanup_temp_files'},
            'app/ui/pages/download.py': {'DownloadPage.load_full_config'},
            'app/ui/pages/settings_dialog.py': {'SettingMenu.__init__','SettingMenu.init_ui','SettingMenu.on_format_changed'},
            'tests/volume_build_contracts.py': {'before_volume_changes'},
            'tests/test_ui_layout_polish.py': {'UiLayoutPolishTests.test_download_options_and_saved_schema_stay_original'},
        }
        manifest = json.loads((ROOT/'docs/download-quality/reviewed-sources.json').read_text(encoding='utf-8'))
        self.assertEqual(set(manifest), set(allowed))
        for relative, entry in manifest.items():
            before = before_download_changes(relative)
            current = (ROOT/relative).read_text(encoding='utf-8-sig')
            self.assertEqual(set(entry['changed_functions']), allowed[relative])
            old, new = functions(before), functions(current)
            for name in set(old)-allowed[relative]:
                self.assertEqual(old[name], new[name], name)
            additions = set(new)-set(old)
            self.assertEqual(additions, {'SettingMenu.update_quality_note'} if relative.endswith('settings_dialog.py') else set())
        helper_hash = json.loads((ROOT/'docs/download-quality/helper-hash.json').read_text(encoding='utf-8'))
        for relative, digest in helper_hash.items():
            self.assertEqual(hashlib.sha256((ROOT/relative).read_bytes()).hexdigest(), digest)
        baseline = json.loads((ROOT/'docs/download-quality/app-before.json').read_text(encoding='utf-8-sig'))
        normalized = json.loads((ROOT/'docs/download-quality/app-normalized-before.json').read_text(encoding='utf-8-sig'))
        for item in baseline:
            if item['path'] not in allowed:
                current = (ROOT/item['path']).read_bytes()
                if item['path'].endswith('.py'):
                    self.assertEqual(hashlib.sha256(current.replace(b'\r\n',b'\n')).hexdigest(), normalized[item['path']], item['path'])
                else:
                    self.assertEqual(hashlib.sha256(current).hexdigest(), item['sha256'], item['path'])


if __name__ == '__main__':
    unittest.main()
