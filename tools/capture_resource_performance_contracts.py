"""Snapshot only this resource phase; preceding archives remain immutable."""
from tools import capture_subtitle_effects_contracts as phase
import hashlib
import json


def main():
    phase.DESTINATION = phase.ROOT / 'docs/resource-performance'
    phase.PATHS = ('app/core/media_library.py', 'app/thumbnail/thumbnail_workers.py',
                   'app/ui/media_card.py', 'app/ui/main_window.py', 'tests/lyric_accuracy_contracts.py',
                   'tests/test_subtitle_effects.py')
    phase.main()
    if (phase.DESTINATION / 'reviewed-sources.json').exists():
        helpers = ('app/thumbnail/cache_batch.py', 'app/ui/library_thumbnail_queue.py',
                   'app/ui/library_grid_view.py')
        (phase.DESTINATION / 'helper-hash.json').write_text(json.dumps({name:
            hashlib.sha256((phase.ROOT / name).read_bytes()).hexdigest() for name in helpers}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
