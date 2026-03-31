"""DCLAP audio embeddings via ONNX (AudioMuse-AI-DCLAP)."""
from __future__ import annotations

from pathlib import Path
import numpy as np

# Models vendored from taste 2/ — absolute path resolved at import time.
_TASTE2_DIR = Path(__file__).parents[4] / "taste 2"
_MODELS_DIR = _TASTE2_DIR / "dclap_models"
_AUDIO_MODEL = _MODELS_DIR / "model_epoch_36.onnx"

_SR = 48000
_SEGMENT_LENGTH = 480000
_HOP_LENGTH = 240000
_N_MELS = 128
_N_FFT = 2048
_HOP_LENGTH_MELS = 480


def embed(audio_path: str) -> np.ndarray:
    """Compute a 512-dim L2-normalized DCLAP embedding. Returns zeros on failure."""
    try:
        return _embed_internal(audio_path)
    except Exception:
        return np.zeros(512, dtype=np.float32)


def _embed_internal(audio_path: str) -> np.ndarray:
    import librosa
    import onnxruntime as ort

    if not _AUDIO_MODEL.exists():
        raise FileNotFoundError(
            f"DCLAP model not found at {_AUDIO_MODEL}. "
            "Expected in taste 2/dclap_models/model_epoch_36.onnx"
        )

    session = ort.InferenceSession(str(_AUDIO_MODEL), providers=["CPUExecutionProvider"])
    audio, _ = librosa.load(audio_path, sr=_SR, mono=True)

    segments = []
    start = 0
    while start + _SEGMENT_LENGTH <= len(audio):
        seg = audio[start: start + _SEGMENT_LENGTH]
        segments.append(_run_model(session, _mel(seg)))
        start += _HOP_LENGTH

    if not segments:
        padded = np.pad(audio, (0, _SEGMENT_LENGTH - len(audio)))
        segments.append(_run_model(session, _mel(padded)))

    avg = np.mean(segments, axis=0)
    norm = np.linalg.norm(avg)
    return (avg / norm).astype(np.float32) if norm > 0 else avg.astype(np.float32)


def _mel(segment: np.ndarray) -> np.ndarray:
    import librosa
    mel = librosa.feature.melspectrogram(
        y=segment, sr=_SR, n_fft=_N_FFT, hop_length=_HOP_LENGTH_MELS, n_mels=_N_MELS,
    )
    return librosa.power_to_db(mel, ref=np.max).astype(np.float32)


def _run_model(session, mel: np.ndarray) -> np.ndarray:
    inp = session.get_inputs()[0].name
    if mel.ndim == 2:
        mel = mel[np.newaxis, np.newaxis, :, :]
    return session.run(None, {inp: mel})[0].flatten()
