import os
import sys

def _parse_time_str(time_str: str) -> float:
    time_str = str(time_str).strip().replace(',', '.')
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
    try:
        return float(time_str)
    except ValueError:
        return 0.0


def _format_time(seconds: float) -> str:
    return f"{float(seconds):.2f}"


def _get_app_root() -> str:
    """Return project root (used for resolving storage paths)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        current_file_path = os.path.abspath(__file__)
        app_ui_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file_path)))
        return os.path.dirname(app_ui_dir)
