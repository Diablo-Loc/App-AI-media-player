"""Capture the authorized disappearing-word phase without recapturing old gates."""
import hashlib
import json
from tools import capture_subtitle_effects_contracts as phase


def main():
    phase.DESTINATION = phase.ROOT / 'docs/subtitle-sweep'
    phase.PATHS = ('app/ui/subtitle_effects.py', 'app/ui/subtitle_effects_panel.py',
                   'app/ui/subtitle_particles.py', 'tests/subtitle_particles_contracts.py',
                   'tests/test_subtitle_particles.py')
    phase.main()
    hashes_path = phase.DESTINATION / 'helper-hash.json'
    if hashes_path.exists():
        hashes = json.loads(hashes_path.read_text())
        relative = 'app/ui/subtitle_particles.py'
        hashes[relative] = hashlib.sha256((phase.ROOT/relative).read_bytes()).hexdigest()
        hashes_path.write_text(json.dumps(hashes, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
