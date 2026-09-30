"""ears' output must match lib/contracts/audio-profile.schema.json."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "lib" / "contracts" / "audio-profile.schema.json"
sys.path.insert(0, str(ROOT / "ears" / "scripts"))


def test_committed_schema_is_current() -> None:
    import gen_schema
    assert json.loads(SCHEMA.read_text()) == gen_schema.build(), \
        "stale contract: run `uv run python scripts/gen_schema.py` in ears/"


def test_cli_output_validates(tmp_path) -> None:
    sr = 48000
    t = np.arange(sr * 2) / sr
    tone = 0.5 * np.sin(2 * np.pi * 220 * t)
    wav = tmp_path / "tone.wav"
    sf.write(wav, np.stack([tone, tone], axis=1), sr)
    out = subprocess.run([sys.executable, "-m", "ears.cli", "analyze", str(wav), "--json", "--no-embeddings"],
                         capture_output=True, text=True, check=True).stdout
    jsonschema.validate(json.loads(out), json.loads(SCHEMA.read_text()))
