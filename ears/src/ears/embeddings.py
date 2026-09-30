"""DCLAP audio embeddings via ONNX (AudioMuse-AI-DCLAP)."""
from __future__ import annotations

import os
from pathlib import Path
import numpy as np

# Set EARS_DCLAP_MODEL to the .onnx file. The default is the pre-split
# monorepo location (taste 2/dclap_models), which a standalone clone lacks.
_DEFAULT_MODEL = Path(__file__).parents[4] / "taste 2" / "dclap_models" / "model_epoch_36.onnx"


def model_path() -> Path:
    return Path(os.environ.get("EARS_DCLAP_MODEL", _DEFAULT_MODEL))

_SR = 48000
_SEGMENT_LENGTH = 480000
_HOP_LENGTH = 240000
_N_MELS = 128
_N_FFT = 2048
_HOP_LENGTH_MELS = 480


def embed(audio_path: str) -> np.ndarray:
    """Compute a 512-dim L2-normalized DCLAP embedding.

    Raises on failure (e.g. model missing) so the analyzer records the error;
    a zero vector would be indistinguishable from a real result downstream.
    """
    import librosa
    import onnxruntime as ort

    model = model_path()
    if not model.exists():
        raise FileNotFoundError(f"DCLAP model not found at {model}; set EARS_DCLAP_MODEL")

    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
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
