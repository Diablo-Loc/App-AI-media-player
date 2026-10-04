"""Probe the authorized erase sweep with an existing video, no audible output."""
from tools.probe_subtitle_particles_media import ROOT, main

if __name__ == '__main__':
    main(ROOT/'docs/subtitle-sweep', erase_passed=True)
