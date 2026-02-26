import json
import os
from pathlib import Path
from paths import storage_dir

# Đổi sang app_config.json theo ý bác
CONFIG_FILE = str(storage_dir() / "app_config.json")

class ConfigManager:
    @staticmethod
    def get_config():
        """Đọc toàn bộ cấu hình hiện có"""
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                return json.loads(content) if content else {}
        except Exception as e:
            print(f"⚠️ Lỗi đọc config: {e}")
            return {}

    @staticmethod
    def save_config(new_data):
        """
        CƠ CHẾ CHỐNG GHI ĐÈ: 
        Đọc dữ liệu cũ -> Trộn dữ liệu mới -> Ghi lại toàn bộ
        """
        try:
            # 1. Lấy dữ liệu đang có trên ổ cứng
            current_data = ConfigManager.get_config()
            
            # 2. Trộn (Merge) dữ liệu mới vào dữ liệu cũ
            # Điều này giúp giữ lại các setting của Sub khi lưu Video và ngược lại
            current_data.update(new_data)
            
            # 3. Đảm bảo thư mục tồn tại và ghi file
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(current_data, f, indent=4, ensure_ascii=False)
                
        except Exception as e:
            print(f"❌ Lỗi lưu config: {e}")

    # --- Các hàm tiện ích (Sử dụng cơ chế trộn) ---
    @staticmethod
    def save_last_folder(path):
        ConfigManager.save_config({'last_folder': path})

    @staticmethod
    def get_last_folder():
        data = ConfigManager.get_config()
        return data.get('last_folder', "")