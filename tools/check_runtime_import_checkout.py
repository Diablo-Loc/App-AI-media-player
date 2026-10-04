"""Extend the owned temporary-index source checks for runtime imports."""
from tools import check_download_quality_checkout as checkout


def main():
    checkout.checkout.PHASE_PATHS += (
        'app/download_core/download_source_app.py', 'app/downloader.py',
        'tests/runtime_import_contracts.py', 'tests/test_runtime_imports.py',
        'docs/runtime-imports',
    )
    checkout.checkout.gates.TARGETS += ('tests.test_runtime_imports.ImportScopeTests',)
    checkout.main()


if __name__=='__main__':
    main()
