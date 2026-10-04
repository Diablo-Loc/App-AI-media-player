"""Particle source gates through an owned disposable index and checkout."""
from tools import check_subtitle_effects_checkout as checkout


def main():
    checkout.checkout.checkout.checkout.PHASE_PATHS += (
        'app/ui/subtitle_particles.py', 'tests/subtitle_particles_contracts.py',
        'tests/test_subtitle_particles.py', 'docs/subtitle-particles',
    )
    checkout.checkout.checkout.checkout.gates.TARGETS += ('tests.test_subtitle_particles.ParticleScopeTests',)
    checkout.main()


if __name__ == '__main__':
    main()
