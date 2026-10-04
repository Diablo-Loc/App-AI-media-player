import os
import requests
from pathlib import Path
from app.paths import models_dir


def download_model_if_needed(model_name, save_dir: str | None = None):
    """Download a model into `models_dir()` by default (per-user storage).

    `save_dir` can be provided to override for testing.
    """
    if save_dir is None:
        save_dir_path = models_dir()
    else:
        save_dir_path = Path(save_dir)

    os.makedirs(save_dir_path, exist_ok=True)

    model_path = os.path.join(str(save_dir_path), model_name)
    if not os.path.exists(model_path):
        print(f"📦 Đang tải model {model_name}...")
        # Link trực tiếp từ HuggingFace hoặc Drive của bác
        url = f"https://huggingface.co/guillaumekln/faster-whisper-large-v3/resolve/main/model.bin"
        # (Đây là ví dụ, bác cần tìm đúng link file .bin hoặc .onnx)
        # Viết code tải file bằng requests ở đây