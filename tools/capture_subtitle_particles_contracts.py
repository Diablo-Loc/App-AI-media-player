"""Capture particle additions in a new phase, leaving old manifests frozen."""
import hashlib
import json
from tools import capture_subtitle_effects_contracts as phase


def main():
    phase.DESTINATION = phase.ROOT / 'docs/subtitle-particles'
    phase.PATHS = ('app/ui/subtitle_effects.py', 'app/ui/subtitle_effects_panel.py',
                   'tests/subtitle_effects_contracts.py', 'tests/test_subtitle_effects.py')
    phase.main()
    helper = phase.ROOT / 'app/ui/subtitle_particles.py'
    if helper.exists() and (phase.DESTINATION / 'helper-hash.json').exists():
        path = phase.DESTINATION / 'helper-hash.json'
        hashes = json.loads(path.read_text())
        hashes['app/ui/subtitle_particles.py'] = hashlib.sha256(helper.read_bytes()).hexdigest()
        path.write_text(json.dumps(hashes, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
