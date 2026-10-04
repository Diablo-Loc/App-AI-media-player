"""Accuracy and preceding gates in a disposable checkout; never user staging."""
from tools import check_subtitle_kinetic_checkout as checkout


def main():
    owner = checkout
    while hasattr(owner, 'checkout'):
        owner = owner.checkout
    owner.PHASE_PATHS += ('app/ai/pipeline.py', 'app/pipeline/lyric_refinement.py',
        'app/pipeline/lyric_accuracy.py', 'tests/lyric_accuracy_contracts.py',
        'tests/test_lyric_accuracy.py', 'tests/lyric_phrase_contracts.py',
        'tests/test_asr_coverage.py', 'docs/lyric-accuracy')
    owner.gates.TARGETS += ('tests.test_lyric_accuracy.AccuracyScopeTests',)
    checkout.main()


if __name__ == '__main__':
    main()
