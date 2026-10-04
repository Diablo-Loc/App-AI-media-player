"""Read-only existing media clock probe with the new strong typography."""
from tools.probe_subtitle_particles_media import ROOT, main

if __name__ == '__main__':
    main(ROOT/'docs/subtitle-kinetic', effects=dict(entrance='kinetic_drop',
        kinetic_strength='bold', kinetic_parts='glyph', duration=480, soft_fade=False))
