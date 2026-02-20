from subtitle.model import Subtitle, SubtitleLine
def refined_to_subtitles(refined_segments, lang="ja"):
    subs = []

    for seg in refined_segments:
        # Tạo object Subtitle cơ bản
        sub = Subtitle(start=seg["start"], end=seg["end"])

        jp_text = seg.get("text", "").strip()
        
        # Luôn khởi tạo Top Line để các hàm sau (như translate) dễ truy cập .top.text
        # ✅ FIX: SubtitleLine.style phải là string, không phải SubtitleStyle object
        sub.top = SubtitleLine(
            text=jp_text,
            lang=lang,
            style="JP"  # String identifier cho styling
        )
        
        # Khởi tạo sẵn Middle và Bottom là None (hoặc Object rỗng)
        # Điều này cực kỳ quan trọng để hàm save_subtitles không bị "bất ngờ"
        sub.middle = None 
        sub.bottom = None

        subs.append(sub)

    return subs
