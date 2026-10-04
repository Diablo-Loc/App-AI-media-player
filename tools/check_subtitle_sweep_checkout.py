"""Sweep source gates through a disposable Git index; no user index staging."""
from tools import check_subtitle_particles_checkout as checkout


def main():
    checkout.checkout.checkout.checkout.checkout.PHASE_PATHS += (
        'tests/subtitle_sweep_contracts.py', 'tests/test_subtitle_sweep.py',
        'docs/subtitle-sweep',
    )
    checkout.checkout.checkout.checkout.checkout.gates.TARGETS += ('tests.test_subtitle_sweep.SweepScopeTests',)
    checkout.main()


if __name__ == '__main__':
    main()
