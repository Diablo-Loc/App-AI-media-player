"""Capture this accuracy phase only; never recapture historical manifests."""
from tools import capture_subtitle_effects_contracts as phase
import hashlib
import json


def main():
    phase.DESTINATION = phase.ROOT / 'docs/lyric-accuracy'
    phase.PATHS = ('app/ai/pipeline.py', 'app/pipeline/lyric_refinement.py',
                   'tests/subtitle_kinetic_contracts.py', 'tests/lyric_phrase_contracts.py',
                   'tests/test_asr_coverage.py')
    phase.main()
    hashes = phase.DESTINATION / 'helper-hash.json'
    if hashes.exists():
        relative = 'app/pipeline/lyric_accuracy.py'
        hashes.write_text(json.dumps({relative: hashlib.sha256((phase.ROOT / relative).read_bytes()).hexdigest()},
                                     indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
