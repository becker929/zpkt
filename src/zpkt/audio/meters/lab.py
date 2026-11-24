"""Where the mastering lab keeps its files: ears/mlab in the repo.

The lab folder holds the guides, hypotheses and their results, the reports, the calibration checks and the audio
the commands write (audio/renders/). The code lives in this package; the files stay in the lab folder.
"""

from __future__ import annotations

from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[3] / "mlab")  # ears/src/ears/meters -> ears/mlab
