"""
Stem separation stub. mlx-audio-separator requires macOS 26+.
For agent-generated material, clean stems come directly from the DAW session.
This module provides the interface; actual separation is deferred to Phase 2
or when mlx-audio-separator becomes compatible with the current OS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Stems:
    available: bool = False
    source: str = "none"          # "daw" | "separated" | "none"
    stem_paths: dict[str, str] = field(default_factory=dict)
    # If embedded numpy arrays are available in memory
    stem_arrays: dict[str, object] = field(default_factory=dict)


def separate(audio_path: str) -> Stems:
    """
    Attempt source separation. Returns Stems with available=False if not possible.

    Priority:
    1. Check if a DAW stems directory exists alongside the audio file
    2. Attempt mlx-audio-separator (macOS 26+)
    3. Return empty Stems if neither available
    """
    import os
    from pathlib import Path

    # Check for pre-rendered stem directory (DAW-generated material)
    stem_dir = Path(audio_path).parent / (Path(audio_path).stem + "_stems")
    if stem_dir.exists():
        stem_paths = {}
        for stem_name in ("kick", "bass", "drums", "vocals", "other"):
            for ext in (".wav", ".mp3", ".aiff"):
                p = stem_dir / f"{stem_name}{ext}"
                if p.exists():
                    stem_paths[stem_name] = str(p)
        if stem_paths:
            return Stems(available=True, source="daw", stem_paths=stem_paths)

    # Attempt mlx-audio-separator (will fail gracefully on macOS <26)
    try:
        from audio_separator.separator import Separator
        sep = Separator()
        output_files = sep.separate(audio_path)
        stem_paths = {}
        for path in output_files:
            name = Path(path).stem.lower()
            for key in ("vocals", "drums", "bass", "other"):
                if key in name:
                    stem_paths[key] = path
        if stem_paths:
            return Stems(available=True, source="separated", stem_paths=stem_paths)
    except Exception:
        pass

    return Stems(available=False, source="none")
