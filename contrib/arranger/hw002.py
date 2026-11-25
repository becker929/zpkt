"""What every arranger script shares about HW002: its tempo and bar, the one-minute arrangement's span and drop, the
Live sets the scripts work in, and where the data lives. One definition each, so the drop is not written in three
units in five files.

Standard library only: the server, and scripts run under hands' or ears' environment, all import it. The data folder
is $ARRANGER_DATA (default ~/_agent_scratch/arranger), read once at import; nothing here changes the environment
until `live_ops` is called, and only for the process that asks for Live.
"""

from __future__ import annotations

import atexit
import os
import subprocess
from pathlib import Path
from typing import Any

# ---- time -----------------------------------------------------------------------------------------------------------

TEMPO_BPM = 160.0
BEATS_PER_BAR = 4.0  # Live's arrangement beats in a bar: positions in the sets are in beats
BAR_SECONDS = BEATS_PER_BAR * 60 / TEMPO_BPM  # 1.5 s
RATE = 44100  # every bounce and render is 44.1 kHz
BAR_SAMPLES = 66150  # BAR_SECONDS at RATE

# ---- the one-minute arrangement (the canonical 8d2a2) ---------------------------------------------------------------

SHORT_BARS = 40  # bars 1-40
SPAN = (1, SHORT_BARS)  # 1-based, inclusive: a whole render of the arrangement
DROP_BAR = 17  # 1-based: the drop; lined up with each reference's own drop
DROP_SECONDS = (DROP_BAR - 1) * BAR_SECONDS  # 24.0 s into a render of SPAN
CANONICAL = "short-8d2a2"  # Anthony, 12 Nov 2026: "8d2a2 is the best. That is the canonical version."

# ---- Live sets ------------------------------------------------------------------------------------------------------

SETS_DIR = Path("~/_agent_scratch/HW002").expanduser()
SET_PREFIX = "HW002_121_pp_"  # the guards accept only these sets as ours
LOOPS_SET = "HW002_121_pp_loops"  # the working copy the loops and kick options are bounced from
MIX_SET = "HW002_121_pp_mix"  # built from the arrangement by mixset.py
FX_SET = "HW002_121_pp_fx"  # the transition sounds, built through the LOM (fxset.py)
FX_AUTOMATED_SET = "HW002_121_pp_fxa"  # the same with automation written into the .als; rendered from
REFERENCE_WAVS = Path("~/_agent_scratch/refs/HW002").expanduser()  # the four HW002 references

# ---- data -----------------------------------------------------------------------------------------------------------

DEFAULT_DATA = "~/_agent_scratch/arranger"
DATA = Path(os.environ.get("ARRANGER_DATA", DEFAULT_DATA)).expanduser()
# The folder Live's Save panel writes exports into before they move to their target: one the panel already knows,
# whatever ARRANGER_DATA says (zpkt.live.export.SavePanel).
STAGING = Path(DEFAULT_DATA).expanduser() / "raw"


def bars_to_beats(first: int, last: int) -> tuple[float, float]:
    """1-based inclusive bars as (start beat, length in beats) in the arrangement."""
    return (first - 1) * BEATS_PER_BAR, (last - first + 1) * BEATS_PER_BAR


# ---- Live -----------------------------------------------------------------------------------------------------------

_focus_armed = False


def _front_app() -> str:
    return subprocess.run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first application process whose frontmost is true',
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()


def give_back_focus() -> None:
    """Anthony uses this Mac while Live works (13 Nov 2026: "Refocus whatever is on top when you're done in case you
    take focus"). Remember the front app now, and at exit, if Live has taken the front, hand it back."""
    global _focus_armed
    if _focus_armed:
        return
    _focus_armed = True
    was = _front_app()
    if not was or was == "Live":
        return

    def back() -> None:
        if _front_app() == "Live":
            subprocess.run(["osascript", "-e", f'tell application "{was}" to activate'], capture_output=True)

    atexit.register(back)


def live_ops(work: Path, renders: Path | None = None, staging: Path = STAGING) -> Any:
    """hands' LiveOps for the HW002 sets: hands' rig settings pointed at the HW002 sets folder and at `work` (hands'
    data in work/data, its renders in `renders`, default work/raw), the focus handed back at exit. Call it from a command, never at
    import: it changes this process's environment, which is how hands reads its rig settings."""
    give_back_focus()
    os.environ["ZPKT_SETS_DIR"] = str(SETS_DIR)
    os.environ["ZPKT_SET_PREFIXES"] = SET_PREFIX
    os.environ["ZPKT_DATA_DIR"] = str(work / "data")
    os.environ["ZPKT_RENDERS_DIR"] = str(renders or work / "raw")
    from zpkt.live import config
    from zpkt.live.ops import LiveOps
    from zpkt.live.transport import LiveClient

    config.rig.cache_clear()  # settings read before this call would name another rig's sets
    return LiveOps(LiveClient.via_app("cli"), staging=staging)  # through the app: its lock, its log


def stop_unless_front(live: Any, where: str, want: str) -> None:
    """Stop the script unless `want` is the set in front (hands' session guard)."""
    import sys

    if live.guard(where) != want:
        sys.exit(f"STOP: {want} is not in front")
