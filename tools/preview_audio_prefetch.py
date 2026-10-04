"""Render the existing audio popup with prefetch; settings/storage are temporary."""
from pathlib import Path

from tools.ui_preview import isolated_window, pump


def main():
    destination = Path(__file__).resolve().parents[1] / 'docs/audio-prefetch/popup.png'
    with isolated_window() as (window, root):
        panel = window.audio_effects.panel
        # UI-only selection: no audio processing or persistent user settings.
        panel.set_profile(False, 'gentle')
        panel.open_at(window.playback_bar.btn_audio)
        pump(100)
        assert panel.rect().contains(panel.prefetch_next.geometry())
        assert panel.rect().contains(panel.reset.geometry())
        from PySide6.QtWidgets import QLabel
        for label in panel.findChildren(QLabel):
            if label.wordWrap():
                assert label.height() >= label.heightForWidth(label.width())
        assert panel.grab().save(str(destination))
        print('Popup logical size:', panel.size().width(), panel.size().height())
        print('Saved:', destination)


if __name__ == '__main__':
    main()
