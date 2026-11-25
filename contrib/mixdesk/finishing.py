"""The HW002 finishing set's settings for the desk's Live scripts (match.py, workspace.py, recipe.py).

The sets live in their own folder with their own prefix, not the rig's, so each script's command line calls
`use_rig()` before it talks to Live: that points hands' rig settings there for this process. Importing changes
nothing; tests pass their own LiveOps instead.
"""

from __future__ import annotations

import os
from pathlib import Path

from zpkt.live import config
from zpkt.live.export import SavePanel
from zpkt.live.ops import LiveOps
from zpkt.live.transport import LiveClient

SETS_DIR = Path("~/_agent_scratch/HW002").expanduser()
SET_PREFIX = "HW002_121_pp_"
MIX_SET = "HW002_121_pp_mix"  # contrib/arranger/mixset.py's mix set
SET = "HW002_121_pp_finish"  # the finishing workspace the desk drives
OUT = Path("~/_agent_scratch/mixdesk").expanduser()
RENDERS = OUT / "renders"
SNAPSHOTS = OUT / "snapshots"
# the Save panel opens where the last export went; this folder is one it has reached before. It is reached by the Go
# to Folder sheet when it is not already there: the Where popup's menu does not open by accessibility on this Mac
# (2026-11-22).
STAGING = Path("~/_agent_scratch/arranger/raw").expanduser()


def rig_env() -> dict[str, str]:
    """The environment hands reads its rig from, for the finishing sets (data and renders only by default)."""
    env = {"ZPKT_SETS_DIR": str(SETS_DIR), "ZPKT_SET_PREFIXES": SET_PREFIX}
    env["ZPKT_DATA_DIR"] = os.environ.get("ZPKT_DATA_DIR", str(OUT / "data"))
    env["ZPKT_RENDERS_DIR"] = os.environ.get("ZPKT_RENDERS_DIR", str(RENDERS))
    return env


def use_rig() -> None:
    """Point this process's hands rig at the finishing sets (a command line's first step)."""
    os.environ.update(rig_env())
    config.rig.cache_clear()


def ops(staging: Path | None = None) -> LiveOps:
    """The Live these scripts drive, with the Save panel reached by Go to Folder."""
    return LiveOps(LiveClient.via_app("cli"), staging=staging, save_panel=SavePanel(reach="go_to_folder"))
