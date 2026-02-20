from faster_whisper import WhisperModel
from pathlib import Path


class ASREngine:
    def __init__(self, model_size="small", device=None):
        """
        model_size: tiny / base / small / medium
        """
        self.model_size = model_size
        self.device = device
        self.model = None

    def load(self):
        if self.model is None:
            print(f"[ASR] Loading Whisper model: {self.model_size}")
            self.model = WhisperModel.load_model(
                self.model_size,
                device=self.device
            )

    def transcribe(self, audio_path: Path, language="ja"):
        self.load()

        print("[ASR] Transcribing:", audio_path)

        result = self.model.transcribe(
            str(audio_path),
            language=language,
            task="transcribe",
            verbose=False
        )

        return result
