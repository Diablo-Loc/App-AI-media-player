import os
from .utils import sec_to_ass, _escape
from subtitle.config import SubtitleConfig, LineStyle
from subtitle.mode import SubtitleMode

def render_ass(subtitles, output_path, config: SubtitleConfig, mode: SubtitleMode):
    """
    Render dữ liệu subtitles (từ JSON hoặc Object) sang định dạng ASS.
    Hỗ trợ 3 tầng: Top (JP), Middle (EN), Bottom (VI).
    """
    # 1. Đảm bảo thư mục đầu ra tồn tại
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        # --- [Script Info] ---
        f.write("[Script Info]\n")
        f.write("Title: Professional Multilingual Lyrics\n")
        f.write("ScriptType: v4.00+\n")
        f.write("PlayResX: 1920\n")
        f.write("PlayResY: 1080\n")
        f.write("ScaledBorderAndShadow: yes\n\n")

        # --- [V4+ Styles] ---
        f.write("[V4+ Styles]\n")
        f.write("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n")
        
        # Ghi Style từ config (Dùng giá trị MarginV khác nhau để không đè chữ)
        _write_style(f, "JP", config.jp_style)
        _write_style(f, "EN", config.en_style)
        _write_style(f, "VI", config.vi_style)

        # --- [Events] ---
        f.write("\n[Events]\n")
        f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

        FADE = r"{\fad(200,200)}"

        # Chuyển mode về dạng string value để so sánh chính xác
        m_val = mode.value if isinstance(mode, SubtitleMode) else mode

        for s in subtitles:
            # Kiểm tra xem s là dict (từ JSON) hay là Object
            is_dict = isinstance(s, dict)
            
            # Lấy thời gian
            start_f = s.get('start', 0) if is_dict else getattr(s, 'start', 0)
            end_f = s.get('end', 0) if is_dict else getattr(s, 'end', 0)
            
            start_str = sec_to_ass(start_f)
            end_str = sec_to_ass(end_f)

            # Hàm helper bóc tách text từ cấu trúc lồng nhau (top, middle, bottom)
            def extract_text(key):
                layer = s.get(key) if is_dict else getattr(s, key, None)
                if not layer: return ""
                # Nếu layer là dict (như trong JSON bác gửi)
                if isinstance(layer, dict):
                    return layer.get('text', '')
                # Nếu layer là Object SubtitleLine
                return getattr(layer, 'text', '')

            t_jp = extract_text('top')    # Layer tiếng Nhật
            t_en = extract_text('middle') # Layer tiếng Anh
            t_vi = extract_text('bottom') # Layer tiếng Việt

            # --- GHI DIALOGUE DỰA TRÊN CHẾ ĐỘ (MODE) ---
            
            # 1. Tiếng Nhật (Layer 2 - Ưu tiên trên cùng)
            if t_jp and m_val in ["jp", "jp_vi", "jp_en_vi"]:
                f.write(f"Dialogue: 2,{start_str},{end_str},JP,,0,0,0,,{FADE}{_escape(t_jp)}\n")

            # 2. Tiếng Anh (Layer 1 - Ở giữa)
            if t_en and m_val in ["jp_en_vi", "en_vi"]:
                f.write(f"Dialogue: 1,{start_str},{end_str},EN,,0,0,0,,{FADE}{_escape(t_en)}\n")

            # 3. Tiếng Việt (Layer 0 - Dưới cùng)
            if t_vi and m_val in ["jp_vi", "jp_en_vi", "en_vi"]:
                f.write(f"Dialogue: 0,{start_str},{end_str},VI,,0,0,0,,{FADE}{_escape(t_vi)}\n")

    print(f"✨ Xuất file ASS thành công: {output_path}")

def _write_style(f, name, style):
    """Ghi định dạng Style vào file ASS"""
    # Sử dụng getattr để tránh lỗi AttributeError nếu thuộc tính thiếu
    is_bold = 1 if getattr(style, 'bold', True) else 0
    is_italic = 1 if getattr(style, 'italic', False) else 0
    
    # style.color: &H<alpha><blue><green><red> (VD: &H00FFFFFF)
    f.write(
        f"Style: {name},{style.font},{style.size},{style.color},"
        "&H000000FF,&H00000000,&H64000000," 
        f"{is_bold},{is_italic},1,2.5,1.5," 
        f"{style.alignment},50,50,{style.margin_v},1\n"
    )
