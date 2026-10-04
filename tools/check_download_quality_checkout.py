"""Check downloader and preceding contracts after a disposable Git checkout."""
from tools import check_media_info_checkout as checkout


def main():
    checkout.PHASE_PATHS += (
        'app/download_core/download_options.py', 'app/download_core/download_worker.py',
        'app/download_core/yt-dlp.exe',
        'app/ui/pages/download.py', 'app/ui/pages/settings_dialog.py',
        'tests/download_quality_contracts.py', 'tests/test_download_quality.py',
        'tests/test_ui_layout_polish.py',
        'docs/download-quality',
    )
    checkout.gates.TARGETS += ('tests.test_download_quality.DownloadSourceScopeTests',)
    checkout.main()


if __name__ == '__main__':
    main()
