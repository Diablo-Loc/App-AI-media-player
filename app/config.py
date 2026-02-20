import json
import os

CONFIG_FILE = "setting.json"

class ConfigManager:
    @staticmethod
    def get_config():
        if not os.path.exists(CONFIG_FILE):
            return {}
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    @staticmethod
    def save_config(data):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Lỗi lưu config: {e}")

    # --- Các hàm tiện ích ---
    @staticmethod
    def save_last_folder(path):
        data = ConfigManager.get_config()
        data['last_folder'] = path
        ConfigManager.save_config(data)

    @staticmethod
    def get_last_folder():
        data = ConfigManager.get_config()
        return data.get('last_folder', "")