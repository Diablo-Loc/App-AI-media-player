from enum import Enum

class SubtitleMode(Enum):
    OFF = "off"
    
    JP = "jp"
    EN = "en"       # <--- Bổ sung cái này để sửa lỗi AttributeError: EN
    VI = "vi"       # <--- Bổ sung cái này để sửa lỗi AttributeError: VI
    
    JP_VI = "jp_vi"
    JP_EN = "jp_en"
    EN_VI = "en_vi"
    
    JP_EN_VI = "jp_en_vi"