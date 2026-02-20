import torch
import soundfile as sf
import numpy as np

class VoiceActivityDetector:
    def __init__(self):
        self.model, self.utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True
        )
        self.get_speech_timestamps = self.utils[0]

    def read_wav(self, path, target_sr=16000):
        audio, sr = sf.read(path)
        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)  # stereo → mono
        if sr != target_sr:
            raise RuntimeError(f"Sample rate must be {target_sr}, got {sr}")
        return torch.from_numpy(audio).float()

    def get_segments(self, wav_path, threshold=0.5):
        wav = self.read_wav(wav_path)
        segments = self.get_speech_timestamps(
            wav,
            self.model,
            threshold=threshold
        )
        return segments
