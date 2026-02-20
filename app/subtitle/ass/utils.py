def sec_to_ass(t):
    """
    Convert seconds to ASS timestamp format (H:MM:SS.cc)
    Example: 3661.05 -> 1:01:01.05
    """
    # Đảm bảo t không âm
    t = max(0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    
    # ASS chuẩn: H:MM:SS.cc (cc là 2 chữ số centiseconds)
    # Dùng :05.2f sẽ lấy 2 số sau dấu phẩy và đảm bảo tổng độ dài là 5 (ví dụ 01.23)
    return f"{h}:{m:02d}:{s:05.2f}"

def _escape(text):
    """
    Làm sạch text để tránh lỗi render ASS.
    """
    if not text:
        return ""
    # Loại bỏ khoảng trắng thừa ở đầu/cuối do Whisper thường hay tạo ra
    text = text.strip()
    # Thay thế dấu xuống dòng thực tế bằng thẻ xuống dòng của ASS (\N)
    text = text.replace("\n", r"\N")
    # Tránh xung đột với tag nhúng của ASS
    return text.replace("{", "｛").replace("}", "｝")