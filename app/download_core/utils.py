import re

def sanitize_folder_name(name):
    # 1. Danh sách tên thiết bị cấm của Windows
    WINDOWS_RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5",
        "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4",
        "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }

    # 2. Thay thế ký tự cấm thành dấu gạch ngang (Chỉ lọc ký tự đặc biệt)
    # Tôi đã bỏ \s (khoảng trắng) ra khỏi danh sách bị thay thế
    forbidden_pattern = r'[\\/:*?"<>|｜／：＊？＂＜＞]'
    clean_name = re.sub(forbidden_pattern, '-', name)
    
    # 3. Loại bỏ ký tự không in được (Invisible chars)
    clean_name = "".join(char for char in clean_name if char.isprintable())
    
    # 4. Gom nhiều dấu gạch ngang liên tiếp thành 1 cái (cho đẹp)
    # NHƯNG giữ nguyên dấu cách (space)
    clean_name = re.sub(r'-+', '-', clean_name)
    
    # 5. Trim dấu chấm và khoảng trắng ở đầu/cuối (Windows cấm file kết thúc bằng dấu chấm hoặc cách)
    clean_name = clean_name.strip('. ')
    
    # 6. Xử lý tên thiết bị cấm
    name_check = clean_name.upper()
    if name_check in WINDOWS_RESERVED_NAMES or name_check.split('.')[0] in WINDOWS_RESERVED_NAMES:
        clean_name = f"video_{clean_name}"

    # 7. Xử lý tên rỗng
    if not clean_name:
        return "Video_Untitled"
        
    # 8. Giới hạn độ dài (150 ký tự là cực kỳ an toàn)
    if len(clean_name) > 150:
        clean_name = clean_name[:150].strip('. ')

    return clean_name