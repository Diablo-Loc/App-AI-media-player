from dataclasses import dataclass

@dataclass
class SubtitleLine:
    lang: str      # 'ja', 'en', 'vi'
    text: str

@dataclass
class SubtitleSegment:
    start: float
    end: float
    top: SubtitleLine | None = None
    bottom: SubtitleLine | None = None
