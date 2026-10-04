"""Check optional subtitle effects through a disposable index/checkout."""
from tools import check_runtime_import_checkout as checkout


def main():
    checkout.checkout.checkout.PHASE_PATHS += (
        'app/ui/subs_ui/sub_panel.py', 'app/ui/subs_ui/subtitle_layer.py',
        'app/ui/subtitle_effects.py', 'app/ui/subtitle_effects_panel.py',
        'tests/subtitle_effects_contracts.py', 'tests/test_subtitle_effects.py',
        'tests/test_ui_refresh.py', 'tests/test_runtime_imports.py',
        'docs/subtitle-effects',
    )
    checkout.checkout.checkout.gates.TARGETS += ('tests.test_subtitle_effects.EffectScopeTests',)
    checkout.main()


if __name__ == '__main__':
    main()
