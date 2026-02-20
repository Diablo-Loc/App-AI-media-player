from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class SubtitleStyle:
    font: str = "Noto Sans JP"
    size: int = 42
    color: str = "#FFFFFF"
    outline: str = "#000000"
    shadow: int = 0
    bold: bool = False
    italic: bool = False
    align: str = "center"   # center / left / right
    pos: Tuple[int, int] = (960, 900)  # X, Y (1080p)


@dataclass
class SubtitleLine:
    text: str
    lang: str               # "ja", "vi", "en"
    style: str


@dataclass
class Subtitle:
    start: float
    end: float
    top: Optional[SubtitleLine] = None    # Tiếng Nhật (Gốc)
    middle: Optional[SubtitleLine] = None # Tiếng Anh
    bottom: Optional[SubtitleLine] = None # Tiếng Việt
