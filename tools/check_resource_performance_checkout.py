"""Verify staged resource/preceding source contracts in a fresh checkout.

Reads the staged index; never changes it, branches or worktree files.
The existing runner supplies Git attributes and temporary cleanup.
"""
from tools import check_audio_checkout as gates


def main():
    gates.TARGETS += (
        'tests.test_media_info.MetadataScopeTests',
        'tests.test_ui_media_surface.PresentationAdapterSourceGate',
        'tests.test_volume_build.VolumeSourceScopeTests',
        'tests.test_download_quality.DownloadSourceScopeTests',
        'tests.test_runtime_imports.ImportScopeTests',
        'tests.test_subtitle_effects.EffectScopeTests',
        'tests.test_subtitle_particles.ParticleScopeTests',
        'tests.test_subtitle_sweep.SweepScopeTests',
        'tests.test_subtitle_kinetic.KineticScopeTests',
        'tests.test_lyric_accuracy.AccuracyScopeTests',
        'tests.test_resource_performance.ResourceSourceGates',
    )
    gates.main()


if __name__ == '__main__':
    main()
