import subprocess
from pathlib import Path


def separate_vocals(
    audio_path: Path,
    output_dir: Path,
    enable: bool = True
):
    """
    Nếu enable = False → trả về audio gốc
    Nếu enable = True → cố gắng tách vocal bằng demucs
    """

    if not enable:
        print("[Vocal] Skip Demucs, use original audio")
        return audio_path

    vocals_path = output_dir / "vocals.wav"

    if vocals_path.exists():
        print("[Vocal] Cache found:", vocals_path)
        return vocals_path

    print("[Vocal] Running Demucs...")

    try:
        subprocess.run(
            [
                "demucs",
                "-n", "htdemucs",
                "--two-stems=vocals",
                "-o", str(output_dir),
                str(audio_path),
            ],
            check=True
        )

        # demucs output path mặc định
        demucs_out = (
            output_dir / "htdemucs" / audio_path.stem / "vocals.wav"
        )

        if demucs_out.exists():
            demucs_out.rename(vocals_path)
            print("[Vocal] Vocal extracted")
            return vocals_path

    except Exception as e:
        print("[Vocal] Demucs failed:", e)

    print("[Vocal] Fallback to original audio")
    return audio_path
