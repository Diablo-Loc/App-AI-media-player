from dataclasses import dataclass, field

@dataclass
class LineStyle:
    font: str
    size: int
    color: str      # Định dạng ASS: &HAABBGGRR
    alignment: int  # 2 là căn giữa dưới
    margin_v: int   # Khoảng cách so với mép
    bold: bool = True    # Khai báo chuẩn dataclass
    italic: bool = False # Khai báo chuẩn dataclass

@dataclass
class SubtitleConfig:
    show_jp: bool = True
    show_en: bool = True
    show_vi: bool = True

    # Khởi tạo mặc định cho từng Style
    jp_style: LineStyle = field(default_factory=lambda: LineStyle(
        font="MS Mincho", 
        size=22, 
        color="&H00FFFFFF", 
        alignment=2,
        margin_v=180,
        bold=True
    ))
    
    en_style: LineStyle = field(default_factory=lambda: LineStyle(
        font="Arial", 
        size=16, 
        color="&H00AAAAAA", 
        alignment=2,
        margin_v=145,
        bold=True
    ))
    
    vi_style: LineStyle = field(default_factory=lambda: LineStyle(
        font="Arial", 
        size=18, 
        color="&H0000FFFF", 
        alignment=2,
        margin_v=90,
        bold=True
    ))