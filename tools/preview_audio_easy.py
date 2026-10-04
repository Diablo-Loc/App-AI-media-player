"""Preview new audio styles with isolated settings and no audio processing."""
from pathlib import Path
from PySide6.QtWidgets import QLabel
from tools.ui_preview import isolated_window, pump

ROOT = Path(__file__).resolve().parents[1]


def main():
    with isolated_window() as (window, root):
        panel = window.audio_effects.panel
        for tone in ('easy', 'easy_headphones'):
            panel.set_profile(False, tone)  # presentation only; no settings writes
            panel.set_status('Đang dùng chất âm đã chọn')
            panel.open_at(window.playback_bar.btn_audio)
            pump(80)
            for label in panel.findChildren(QLabel):
                if label.wordWrap():
                    assert label.height() >= label.heightForWidth(label.width())
            assert panel.grab().save(str(ROOT / f'docs/audio-easy/{tone}.png'))


if __name__ == '__main__':
    main()
