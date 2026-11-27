"""Comprehensive tests for Studio Settings scroll layout, button sizing, and 100% VI/EN i18n."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTabWidget,
    QWidget,
)

from ui.main_window import MainWindow  # noqa: F401 - keep Shiboken wrappers resident
from tools.ui_preview import isolated_window, pump
from ui.i18n import get_language, set_language
from ui.subs_ui.lyric_settings_dialog import SubtitleToolsDialog
from ui.video_subtitle_export import ExportCue, ExportSnapshot, VideoExportSettingsDialog

# Regex matching exclusively Vietnamese-specific diacritic letters (never matches English, CJK, or '–'/'—')
_RE_VI_DIACRITIC = re.compile(
    r'[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ'
    r'ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]'
)


def _collect_leftover_vietnamese(root: QWidget) -> list[str]:
    """Scan all UI controls under `root` and return any leftover Vietnamese strings in English mode."""
    leftovers: list[str] = []
    widgets = [root] + root.findChildren(QWidget)
    for w in widgets:
        cls_name = type(w).__name__
        if cls_name in ('SubtitleLayer', '_ExportLabel', 'DraggableSubtitle'):
            continue
        # Skip hidden legacy SettingsPage owner bin
        p = w
        in_legacy_bin = False
        while p is not None:
            if p.objectName() == 'legacySettingsOwnerBin':
                in_legacy_bin = True
                break
            p = p.parentWidget()
        if in_legacy_bin:
            continue

        if isinstance(w, QGroupBox):
            t = w.title()
            if _RE_VI_DIACRITIC.search(t):
                leftovers.append(f'{cls_name}.title: {t!r}')
        elif isinstance(w, (QLabel, QAbstractButton)):
            t = w.text()
            if _RE_VI_DIACRITIC.search(t) and 'Tiếng Việt' not in t:
                leftovers.append(f'{cls_name}({w.objectName()}).text: {t!r}')
        elif isinstance(w, QLineEdit):
            ph = w.placeholderText()
            if _RE_VI_DIACRITIC.search(ph):
                leftovers.append(f'QLineEdit({w.objectName()}).placeholder: {ph!r}')
        elif isinstance(w, QTabWidget):
            for idx in range(w.count()):
                tt = w.tabText(idx)
                if _RE_VI_DIACRITIC.search(tt):
                    leftovers.append(f'QTabWidget.tab[{idx}]: {tt!r}')
        elif isinstance(w, QComboBox) and not bool(w.property('_i18n_skip_combo')):
            has_data = bool(w.property('_i18n_safe_combo')) or (
                w.count() > 0 and any(w.itemData(i) is not None for i in range(w.count()))
            )
            if has_data:
                for idx in range(w.count()):
                    it = w.itemText(idx)
                    if _RE_VI_DIACRITIC.search(it) and it != 'Tiếng Việt':
                        leftovers.append(f'QComboBox({w.objectName()}).item[{idx}]: {it!r}')
    return leftovers


class UiSettingsAndI18nTests(unittest.TestCase):
    def tearDown(self):
        set_language('vi', persist=False)

    def test_maximized_settings_scroll_has_zero_phantom_bottom_void(self):
        with isolated_window() as (window, _root):
            studio = window.audio_effects.settings_studio
            settings_row = window.sidebar.row_for_page('settings')
            window.sidebar.setCurrentRow(settings_row)
            window.handle_sidebar_click(window.sidebar.item(settings_row))
            window.show()
            pump(50)

            for lang in ('vi', 'en'):
                idx = studio.language_combo.findData(lang)
                studio.language_combo.setCurrentIndex(idx)
                pump(30)

                # Test compact, laptop 125% DPI (1536x864), Full HD (1920x1080), and 2K (2560x1440)
                for width, height in ((1024, 640), (1536, 864), (1920, 1080), (2560, 1440)):
                    window.resize(width, height)
                    pump(40)
                    vp_h = studio.scroll.viewport().height()
                    host_h = studio.scroll.widget().height()
                    cards_bottom = studio.col_wrap.y() + studio.col_wrap.height() + 16
                    scroll_max = studio.scroll.verticalScrollBar().maximum()

                    if cards_bottom <= vp_h:
                        self.assertEqual(
                            scroll_max,
                            0,
                            f'Expected zero scrollbar on {width}x{height} ({lang}), got max={scroll_max}',
                        )
                    else:
                        # When scrollable, scroll_host height must match exact cards_bottom (zero blank void!)
                        self.assertLessEqual(
                            abs(host_h - cards_bottom),
                            4,
                            f'Phantom bottom void detected at {width}x{height} ({lang}): host={host_h}, cards={cards_bottom}',
                        )

                    # Strict anti-stretch contract: single-row Appearance card and badge pills must stay crisp & compact!
                    self.assertLessEqual(
                        studio.appearance_card.height(),
                        170,
                        f'Appearance card stretched vertically at {width}x{height}: {studio.appearance_card.height()}px',
                    )
                    self.assertLessEqual(
                        studio.lbl_lang_badge.height(),
                        32,
                        f'Language badge pill stretched vertically: {studio.lbl_lang_badge.height()}px',
                    )
                    self.assertLessEqual(
                        studio.lbl_audio_badge.height(),
                        32,
                        f'Audio badge pill stretched vertically: {studio.lbl_audio_badge.height()}px',
                    )
                    self.assertNotIn('LUFS · −14 LUFS', studio.lbl_audio_badge.text())
                    for card in (studio.appearance_card, studio.audio_card, studio.asr_card, studio.translation_card):
                        expected_h = card.layout().totalHeightForWidth(card.width())
                        self.assertLessEqual(
                            abs(card.height() - expected_h),
                            2,
                            f'Card {card.objectName()} height {card.height()} != exact HFW {expected_h}',
                        )

    def test_restored_fast_lyrics_proxy_combos_and_silent_autosave_keep_canonical_values(self):
        with isolated_window() as (window, _root):
            page = window.settings_page
            studio = window.audio_effects.settings_studio
            self.assertIsNotNone(studio)

            settings_row = window.sidebar.row_for_page('settings')
            window.sidebar.setCurrentRow(settings_row)
            window.handle_sidebar_click(window.sidebar.item(settings_row))
            window.show()
            pump(50)

            self.assertTrue(studio.appearance_card.isVisible())
            self.assertTrue(studio.audio_card.isVisible())
            self.assertTrue(studio.asr_card.isVisible())
            self.assertTrue(studio.translation_card.isVisible())
            self.assertTrue(studio.fast_lyrics_combo.isVisible())

            idx_off = studio.fast_lyrics_combo.findData('Tắt (Luôn dùng AI)')
            self.assertGreaterEqual(idx_off, 0)
            studio.fast_lyrics_combo.setCurrentIndex(idx_off)
            pump(20)
            self.assertEqual(page.combo_fast_lyrics.currentText(), 'Tắt (Luôn dùng AI)')
            self.assertEqual(page.settings.value('fast_lyrics_enabled'), 'Tắt (Luôn dùng AI)')
            self.assertTrue(studio.lbl_save_status.isVisible())

            idx_cuda = studio.compute_device_combo.findData('cuda')
            studio.compute_device_combo.setCurrentIndex(idx_cuda)
            pump(20)
            self.assertEqual(page.combo_device.currentText(), 'cuda')
            self.assertEqual(page.settings.value('device'), 'cuda')

            idx_claude = studio.online_ai_combo.findData('Claude 3.5')
            studio.online_ai_combo.setCurrentIndex(idx_claude)
            pump(20)
            self.assertEqual(page.combo_online_ai.currentText(), 'Claude 3.5')
            self.assertEqual(page.settings.value('online_provider'), 'Claude 3.5')
            self.assertIn('console.anthropic.com', studio.lbl_provider_link.text())

            with patch('ui.pages.settings.QMessageBox.exec', side_effect=AssertionError('Unexpected modal popup')):
                page.btn_save.click()
                pump(20)
            self.assertIn('✓', studio.lbl_save_status.text())

    def test_100_percent_english_coverage_across_all_5_screenshots_and_exact_vi_restore(self):
        with tempfile.TemporaryDirectory() as tmp_dir, isolated_window() as (window, _root):
            fake_media_file = Path(tmp_dir) / 'Morning_Star.mp4'
            fake_media_file.write_bytes(b'00')
            fake_item = SimpleNamespace(
                id='m_test_1',
                title='Morning Star and the Sea',
                artist='NTE Global',
                path=str(fake_media_file),
                file_path=str(fake_media_file),
                duration=188.0,
                thumbnail='',
                mtime=1.0,
            )

            # Seed History + Smart Resume + Most Played + ForYou queue so dynamic rows/banners exist
            store = window.user_collections
            store.record_history(fake_item)
            store.record_history(fake_item)  # watch_count == 2 -> 'Xem 2 lần' / 'Viewed 2 times'
            store.record_last_played_track(fake_item, 88_000)
            store.record_play_stat(fake_item, initial_listen_sec=125.0)
            window._restore_passive_last_played_ui()
            window.foryou_page.update_playing_status(15, 20)
            window.foryou_page.set_playlist_header_title(None)

            page = window.settings_page
            studio = window.audio_effects.settings_studio
            settings_row = window.sidebar.row_for_page('settings')
            window.sidebar.setCurrentRow(settings_row)
            window.handle_sidebar_click(window.sidebar.item(settings_row))
            window.resize(1440, 900)
            window.show()
            pump(50)

            # Switch to English
            idx_en = studio.language_combo.findData('en')
            studio.language_combo.setCurrentIndex(idx_en)
            pump(60)
            self.assertEqual(get_language(), 'en')

            # 1. Screenshot 1: PlaybackBar Smart Resume + Settings Studio
            self.assertIn('Press Play to resume at 01:28', window.playback_bar.lbl_song_info.text())
            self.assertEqual( _collect_leftover_vietnamese(window), [] )

            # 2. Screenshot 2: HistoryPage + Subtitles & Studio Effects Popup (including Outline button width!)
            hist_row = window.sidebar.row_for_page('history')
            window.sidebar.setCurrentRow(hist_row)
            window.handle_sidebar_click(window.sidebar.item(hist_row))
            pump(50)
            self.assertEqual(window.history_page.lbl_total_badge.text(), '1 video')
            self.assertIn('Paused at 01:28', window.history_page.lbl_resume_text.text())
            self.assertEqual(_collect_leftover_vietnamese(window.history_page), [])

            sub_panel = window.subsettings_panel
            sub_panel.show()
            pump(40)
            self.assertEqual(sub_panel.btn_out_color.text(), 'Outline')
            fm_out = sub_panel.btn_out_color.fontMetrics()
            self.assertGreaterEqual(
                sub_panel.btn_out_color.width(),
                fm_out.horizontalAdvance('Outline') + 10,
                'Outline button too narrow and would clip text!',
            )
            self.assertEqual(sub_panel.settings_scroll.verticalScrollBar().maximum(), 0)
            self.assertIn('Subtitle Effects', sub_panel.effects_panel.title())
            self.assertEqual(_collect_leftover_vietnamese(sub_panel), [])

            # Toggle Karaoke recommendations while in English -> zero leftover Vietnamese
            sub_panel.set_karaoke_recommendations(True)
            pump(20)
            self.assertEqual(_collect_leftover_vietnamese(sub_panel), [])
            sub_panel.set_karaoke_recommendations(False)
            sub_panel.hide()

            # 3. Collections / Most Played page
            coll_row = window.sidebar.row_for_page('collections')
            window.sidebar.setCurrentRow(coll_row)
            window.handle_sidebar_click(window.sidebar.item(coll_row))
            window.collections_page.select_collection('__most_played__')
            pump(50)
            self.assertEqual(_collect_leftover_vietnamese(window.collections_page), [])

            # 4. Screenshot 3: VideoExportSettingsDialog with cues
            snap = ExportSnapshot(
                source=str(fake_media_file),
                cues=(ExportCue(index=0, start=1000.0, end=4000.0, text="Don't cry anymore."),),
                style={'font_size': 24, 'bg_opacity': 0.5},
                effects={},
                fade_enabled=True,
                anchor_width=1280,
                anchor_height=720,
                user_moved=False,
                rel_x_offset=0,
                bottom_offset=40,
            )
            export_dlg = VideoExportSettingsDialog(window, snapshot=snap, media_item=fake_item)
            self.addCleanup(export_dlg.deleteLater)
            export_dlg.show()
            pump(40)
            self.assertEqual(export_dlg.windowTitle(), 'Export Video + Lyrics')
            self.assertTrue(export_dlg.preview_cue.itemText(0).startswith('Cue 1:'))
            self.assertTrue(export_dlg.output_summary.text().startswith('Output:'))
            self.assertEqual(_collect_leftover_vietnamese(export_dlg), [])
            export_dlg.close()

            # 5. Screenshot 4: ForYouPage + AudioEffectsPanel + AudioEqualizerDialog
            self.assertEqual(window.foryou_page.lbl_pl_title.text(), 'Up Next Queue')
            self.assertEqual(window.foryou_page.lbl_count.text(), 'Track - 15/20')
            self.assertEqual(_collect_leftover_vietnamese(window.foryou_page), [])

            audio_panel = window.audio_effects.panel
            audio_panel.show()
            pump(30)
            self.assertEqual(_collect_leftover_vietnamese(audio_panel), [])
            audio_panel.hide()

            window.audio_effects.open_equalizer()
            pump(30)
            eq_dlg = window.audio_effects.eq_dialog
            self.assertIsNotNone(eq_dlg)
            self.assertEqual(_collect_leftover_vietnamese(eq_dlg), [])
            eq_dlg.close()

            # 6. Screenshot 5: AudioBenchmarkPage (idle + rendered benchmark result!)
            window.audio_effects.open_benchmark_tab(auto_run=False)
            pump(40)
            bench_page = window.audio_effects.benchmark_page
            self.assertIsNotNone(bench_page)
            fake_bench_res = {
                'source_path': str(fake_media_file),
                'source_info': {'codec_name': 'aac', 'bit_rate': 128000},
                'in_sr': 44100,
                'out_sr': 44100,
                'out_dtype': 'float32',
                'elapsed_ms': 420,
                'source_cutoff_hz': 16500,
                'snr_db': 142.0,
                'freqs_hz': [20.0, 1000.0, 20000.0],
                'orig_spec_db': [-35.0, -20.0, -50.0],
                'proc_spec_raw_db': [-35.0, -20.0, -50.0],
                'proc_spec_matched_db': [-35.0, -20.0, -50.0],
                'delta_spec_db': [0.0, 0.0, 0.0],
                'verdict': {
                    'badge': 'ĐẠT CHUẨN BIT-PURE',
                    'headline': 'Đáp tuyến phẳng 0.00 dB · Nền nhiễu -142.0 dBFS · 32-bit Float 44.1 kHz.',
                    'findings': [
                        {
                            'level': 'good',
                            'title': 'Chuẩn hóa đỉnh EBU R128',
                            'detail': '+0.85 dBTP (1,912 mẫu clip) → -1.00 dBTP (0 clip, đạt trần ≤ -1.0 dBTP).',
                        }
                    ],
                    'listener_summary': {
                        'overall_tag': 'SẠCH HƠN BẢN GỐC',
                        'overall_tone': 'good',
                        'plain_conclusion': (
                            'Tốt hơn bản gốc về độ trong trẻo: Đã khử sạch 1,912 điểm vượt trần gây rè ở đoạn cao trào, '
                            'giữ nguyên 100% chất giọng & chi tiết gốc.'
                        ),
                        'pillars': [
                            {
                                'title': 'Độ trong trẻo',
                                'verdict': 'Tốt hơn gốc',
                                'detail': 'Đã khử sạch 1,912 điểm vượt trần về 0 clip.',
                                'tone': 'good',
                            },
                            {
                                'title': 'Độ nảy & Chi tiết',
                                'verdict': 'Giữ nguyên 100%',
                                'detail': 'Không nén động, giữ nguyên nhịp nảy gốc.',
                                'tone': 'good',
                            },
                            {
                                'title': 'Màu âm & Không gian',
                                'verdict': 'Nguyên bản 1:1',
                                'detail': 'Không đổi chất giọng hay màu nhạc cụ gốc.',
                                'tone': 'good',
                            },
                        ],
                    },
                },
                'comparison_rows': [
                    {
                        'metric': 'Mẫu vượt trần (ISP > 0 dBTP)',
                        'orig': '1,912 mẫu',
                        'proc': '0 mẫu',
                        'status': 'Sạch clip',
                        'tone': 'good',
                    }
                ],
            }
            bench_page._on_benchmark_done(bench_page._generation, fake_bench_res)
            pump(30)
            self.assertEqual(bench_page.lbl_plain_badge.text(), 'CLEANER THAN SOURCE')
            self.assertEqual(bench_page.lbl_verdict_badge.text(), 'BIT-PURE CERTIFIED')
            self.assertEqual(_collect_leftover_vietnamese(bench_page), [])

            # 7. SubtitleToolsDialog & VideoInfoPopup
            sub_dlg = SubtitleToolsDialog(parent=window)
            self.addCleanup(sub_dlg.deleteLater)
            sub_dlg.show()
            pump(30)
            self.assertEqual(_collect_leftover_vietnamese(sub_dlg), [])
            sub_dlg.close()

            info_popup = window.playback_bar.info_popup
            info_popup.show()
            pump(30)
            self.assertEqual(_collect_leftover_vietnamese(info_popup), [])
            info_popup.hide()

            # 8. Switch back to Tiếng Việt -> 100% verbatim restoration & untouched persistence keys!
            idx_vi = studio.language_combo.findData('vi')
            studio.language_combo.setCurrentIndex(idx_vi)
            pump(60)
            self.assertEqual(get_language(), 'vi')
            self.assertEqual(window.sidebar.item(0).text(), 'Trang chủ')
            self.assertIn('Bấm Phát để tiếp tục tại 01:28', window.playback_bar.lbl_song_info.text())
            self.assertEqual(window.foryou_page.lbl_pl_title.text(), 'Danh sách phát')
            self.assertEqual(window.foryou_page.lbl_count.text(), 'Bài hát - 15/20')
            self.assertEqual(bench_page.lbl_plain_badge.text(), 'SẠCH HƠN BẢN GỐC')
            self.assertEqual(bench_page.lbl_verdict_badge.text(), 'ĐẠT CHUẨN BIT-PURE')
            self.assertEqual(sub_panel.btn_out_color.text(), 'Viền')


if __name__ == '__main__':
    unittest.main()
