import logging
from pathlib import Path
from subtitle.timing_format import ass_time

class ASSRenderer:
    @staticmethod
    def generate(segments, output_path, primary_lang='jp', secondary_lang='vi'):
        """
        segments: List các dict [{'start': 0.0, 'end': 2.5, 'jp': '...', 'vi': '...'}]
        """
        header = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1280",  # Tăng độ phân giải để font mượt hơn
            "PlayResY: 720",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            # Style cho tiếng Nhật (To, rõ)
            "Style: Main,MS UI Gothic,45,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,1,2,30,30,50,1",
            # Style cho tiếng Việt (Nhỏ hơn, nằm dưới)
            "Style: Sub,Arial,28,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1.5,1,2,30,30,15,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        lines = header.copy()
        
        for s in segments:
            try:
                start = ASSRenderer.format_time(s.get('start', 0))
                end = ASSRenderer.format_time(s.get('end', 0))
                
                # Lấy nội dung text
                main_text = s.get(primary_lang) or s.get('text') or ""
                sub_text = s.get(secondary_lang) or ""

                if not main_text:
                    continue

                # Tạo dòng Dialogue cho tiếng Nhật
                lines.append(f"Dialogue: 0,{start},{end},Main,,0,0,0,,{main_text.strip()}")
                
                # Nếu có tiếng Việt, chèn thêm một dòng Dialogue đè lên nhưng dùng Style khác (Sub)
                if sub_text:
                    lines.append(f"Dialogue: 1,{start},{end},Sub,,0,0,0,,{sub_text.strip()}")
                    
            except Exception as e:
                logging.error(f"Lỗi render segment: {e}")

        try:
            with open(output_path, "w", encoding="utf-8-sig") as f: # Dùng utf-8-sig để BOM giúp Windows nhận diện tốt hơn
                f.write("\n".join(lines))
            return True
        except Exception as e:
            logging.error(f"Không thể ghi file ASS: {e}")
            return False

    @staticmethod
    def format_time(seconds):
        """Định dạng chuẩn ASS: H:MM:SS.cs (centiseconds)"""
        return ass_time(seconds)
