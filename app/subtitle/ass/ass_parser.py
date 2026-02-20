import os
import re

class ASSParser:
    @staticmethod
    def time_to_ms(time_str):
        try:
            h, m, s = time_str.split(':')
            return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
        except:
            return 0

    @classmethod
    def parse_file(cls, file_path):
        if not os.path.exists(file_path):
            return []
        
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()

        segments_map = {}
        # Regex khớp start, end, style, text
        pattern = re.compile(r"Dialogue: \d+,(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),([^,]+),.*?,.*?,.*?,.*?,.*?,(.*)")
        
        for line in content.split('\n'):
            match = pattern.match(line)
            if match:
                start_str, end_str, style, raw_text = match.groups()
                start_ms = cls.time_to_ms(start_str)
                end_ms = cls.time_to_ms(end_str)
                
                # Clean text: xóa tag {}, đổi \N thành xuống dòng
                clean_text = re.sub(r'\{.*?\}', '', raw_text).replace(r'\N', '\n').strip()
                
                time_key = (start_ms, end_ms)
                if time_key not in segments_map:
                    # Tạo khung chứa
                    segments_map[time_key] = {'start': start_ms, 'end': end_ms, 'jp': '', 'vi': '', 'en': ''}
                
                style_upper = style.upper()
                if "JP" in style_upper:
                    segments_map[time_key]['jp'] = clean_text
                elif "VI" in style_upper:
                    segments_map[time_key]['vi'] = clean_text
                elif "EN" in style_upper:
                    segments_map[time_key]['en'] = clean_text
                else:
                    # Fallback: nếu chưa có VI thì nhét vào VI
                    if not segments_map[time_key]['vi']:
                        segments_map[time_key]['vi'] = clean_text

        return sorted(segments_map.values(), key=lambda x: x['start'])