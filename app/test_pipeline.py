from pathlib import Path
from ai.pipeline import run_ai_pipeline


def main():
    root = Path(__file__).resolve().parents[1]

    ass = run_ai_pipeline(
        media_id= "1111",
        input_path=root / "input" / "【歌ってみた】Tell Your World – kz - covered by 月見ヤチヨ(cv.早見沙織) from 超かぐや姫！.mp4",
        output_dir="output"
    )
    print("OK:", ass)


if __name__ == "__main__":
    main()
