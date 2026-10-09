"""Kinetic source gates in a disposable checkout/index, not the user index."""
from tools import check_subtitle_sweep_checkout as checkout


def main():
    checkout.checkout.checkout.checkout.checkout.checkout.PHASE_PATHS += (
        'app/ui/subtitle_kinetic.py', 'tests/subtitle_kinetic_contracts.py',
        'tests/test_subtitle_kinetic.py', 'docs/subtitle-kinetic',
    )
    checkout.checkout.checkout.checkout.checkout.checkout.gates.TARGETS += ('tests.test_subtitle_kinetic.KineticScopeTests',)
    checkout.main()


if __name__ == '__main__':
    main()
