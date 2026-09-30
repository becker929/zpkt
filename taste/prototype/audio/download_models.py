"""
Download DCLAP ONNX model weights from GitHub release v1.
Run once before first use: uv run python -m taste.audio.download_models
"""

from __future__ import annotations

import sys
from pathlib import Path

MODELS_DIR = Path(__file__).parent.parent / "dclap_models"
REPO = "NeptuneHub/AudioMuse-AI-DCLAP"
TAG = "v1"

# Only the audio encoder is needed for embedding. Text model is 331MB and unused.
REQUIRED_FILES = [
    "model_epoch_36.onnx",
    "model_epoch_36.onnx.data",
]


def models_present() -> bool:
    return all((MODELS_DIR / f).exists() for f in REQUIRED_FILES)


def download():
    if models_present():
        print("DCLAP models already present.")
        return

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading DCLAP audio encoder from {REPO} release {TAG}...")

    try:
        import subprocess
        result = subprocess.run(
            [
                "gh", "release", "download", TAG,
                "--repo", REPO,
                "--dir", str(MODELS_DIR),
                "--pattern", "model_epoch_36*",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        print("Download complete.")
    except FileNotFoundError:
        # gh CLI not available — fall back to direct HTTP download
        _download_http()


def _download_http():
    import urllib.request

    base = f"https://github.com/{REPO}/releases/download/{TAG}"
    for fname in REQUIRED_FILES:
        dest = MODELS_DIR / fname
        if dest.exists():
            continue
        url = f"{base}/{fname}"
        print(f"  Downloading {fname} ...", end="", flush=True)
        urllib.request.urlretrieve(url, dest)
        print(f" {dest.stat().st_size // 1024}KB")

    print("Download complete.")


if __name__ == "__main__":
    download()
