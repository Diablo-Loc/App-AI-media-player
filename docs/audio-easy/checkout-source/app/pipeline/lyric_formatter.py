from pathlib import Path
from subtitle.timing_format import srt_time, lrc_time

def format_time_srt(seconds: float) -> str:
    return srt_time(seconds)


def format_time_lrc(seconds: float) -> str:
    return lrc_time(seconds)


def export_srt(segments, output_path):
    # Đảm bảo output_path là đối tượng Path
    path_obj = Path(output_path)
    # Tự động tạo thư mục cha (ví dụ: storage/subtitles/source/srt) nếu chưa có
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path_obj, "w", encoding="utf-8-sig") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(
                f"{format_time_srt(seg['start'])} --> "
                f"{format_time_srt(seg['end'])}\n"
            )
            f.write(seg["text"].strip() + "\n\n")


def export_lrc(segments, output_path):
    # Đảm bảo output_path là đối tượng Path
    path_obj = Path(output_path)
    # Tự động tạo thư mục cha (ví dụ: storage/subtitles/source/srt) nếu chưa có
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path_obj, "w", encoding="utf-8-sig") as f:
        for seg in segments:
            timestamp = format_time_lrc(seg["start"])
            f.write(f"[{timestamp}]{seg['text'].strip()}\n")
