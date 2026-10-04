"""Measure sweep rendering and saved hashes without altering prior reports."""
from tools.probe_subtitle_particles import ROOT, main

if __name__ == '__main__':
    main(ROOT/'docs/subtitle-sweep', erase_passed=True)
