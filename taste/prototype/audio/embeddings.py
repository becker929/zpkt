"""DCLAP audio embeddings via ONNX (AudioMuse-AI-DCLAP)."""

from __future__ import annotations

import os
from pathlib import Path
import numpy as np

# Path to the downloaded ONNX models
_MODELS_DIR = Path(__file__).parent.parent.parent / "taste" / "dclap_models"
_AUDIO_MODEL = _MODELS_DIR / "model_epoch_36.onnx"

# Audio processing constants from DCLAP README
_SR = 48000
_SEGMENT_LENGTH = 480000   # 10 seconds at 48kHz
_HOP_LENGTH = 240000       # 50% overlap
_N_MELS = 128
_N_FFT = 2048
_HOP_LENGTH_MELS = 480


def embed(audio_path: str) -> np.ndarray:
    """
    Compute a 512-dim L2-normalized DCLAP embedding for an audio file.
    Segments are extracted with 50% overlap and averaged.
    Returns shape (512,) or zeros on failure.
    """
    try:
        return _embed_internal(audio_path)
    except Exception:
        return np.zeros(512, dtype=np.float32)


def _embed_internal(audio_path: str) -> np.ndarray:
    import librosa
    import onnxruntime as ort

    if not _AUDIO_MODEL.exists():
        from .download_models import download, models_present
        download()
        if not models_present():
            raise FileNotFoundError(f"DCLAP model not found at {_AUDIO_MODEL}")

    session = ort.InferenceSession(
        str(_AUDIO_MODEL),
        providers=["CPUExecutionProvider"],
    )

    audio, _ = librosa.load(audio_path, sr=_SR, mono=True)

    # Extract mel spectrogram segments with 50% overlap
    segment_embeddings = []
    start = 0
    while start + _SEGMENT_LENGTH <= len(audio):
        segment = audio[start : start + _SEGMENT_LENGTH]
        mel = _mel_spectrogram(segment)
        embedding = _run_model(session, mel)
        segment_embeddings.append(embedding)
        start += _HOP_LENGTH

    # Handle audio shorter than one segment
    if not segment_embeddings:
        segment = np.pad(audio, (0, _SEGMENT_LENGTH - len(audio)))
        mel = _mel_spectrogram(segment)
        segment_embeddings.append(_run_model(session, mel))

    # Average and L2-normalize
    avg = np.mean(segment_embeddings, axis=0)
    norm = np.linalg.norm(avg)
    return (avg / norm).astype(np.float32) if norm > 0 else avg.astype(np.float32)


def _mel_spectrogram(segment: np.ndarray) -> np.ndarray:
    import librosa
    mel = librosa.feature.melspectrogram(
        y=segment,
        sr=_SR,
        n_fft=_N_FFT,
        hop_length=_HOP_LENGTH_MELS,
        n_mels=_N_MELS,
    )
    mel_db = librosa.power_to_db(mel, ref=np.max)
    return mel_db.astype(np.float32)


def _run_model(session, mel: np.ndarray) -> np.ndarray:
    input_name = session.get_inputs()[0].name
    # Model expects (batch, channels, mels, time) — check shape and add dims
    if mel.ndim == 2:
        mel = mel[np.newaxis, np.newaxis, :, :]  # (1, 1, 128, T)
    result = session.run(None, {input_name: mel})
    return result[0].flatten()
