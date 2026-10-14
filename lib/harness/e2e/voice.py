"""What the virtual user says: Kokoro, in a different voice from Claude's, each line made once and kept."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import numpy as np

from harness.config import ZPKT

VOICES = Path("~/_agent_scratch/e2e/voices").expanduser()
USER_VOICE = "am_michael"
UV = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def line(text: str) -> Path:
    """A WAV of `text` with a short silence before it and a longer one after (the stop word needs the pause)."""
    import soundfile as sf

    VOICES.mkdir(parents=True, exist_ok=True)
    out = VOICES / f"{hashlib.sha256(f'{USER_VOICE}|{text}'.encode()).hexdigest()[:16]}.wav"
    if out.is_file():
        return out
    raw = out.with_suffix(".raw.wav")
    subprocess.run([UV, "run", "--project", str(ZPKT / "lib" / "voice"), "--extra", "engines", "voice", "say", text,
                    "-o", str(raw), "--voice", USER_VOICE], check=True, capture_output=True, timeout=300)
    x, sr = sf.read(raw, dtype="float32")
    sf.write(out, np.concatenate([np.zeros(sr // 5, np.float32), x, np.zeros(sr, np.float32)]), sr, subtype="PCM_16")
    raw.unlink()
    return out
