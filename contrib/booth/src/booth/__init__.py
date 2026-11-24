"""The booth: scores in, Live renders out, for the Bluesky music bot (contrib/docs/design/bluesky-bot.md).

hands reads its rig from the environment once, when it is first used. `use_booth_rig()` points it at the booth's own:
its sets live in the booth's folder and only `booth_` sets count as ours, so no guard ever lets it act on one of
Anthony's sets. The CLI calls it first thing; nothing changes the environment on import.
"""

import os
from pathlib import Path

HOME = Path(os.environ.get("BOOTH_HOME", Path.home() / "_agent_scratch" / "booth")).expanduser()
SETS_DIR = HOME / "sets" / "booth Project"  # Live keeps a set in "<name> Project/"; every job set shares it
PREFIX = "booth_"
TEMPLATE = "booth_template"

RIG_ENV = {
    "ZPKT_SETS_DIR": str(SETS_DIR),
    "ZPKT_SET_PREFIXES": PREFIX,
    "ZPKT_DATA_DIR": str(HOME / "data"),
    "ZPKT_RENDERS_DIR": str(HOME / "renders"),
}


def use_booth_rig() -> None:
    """Point hands' rig settings at the booth's folders and prefix, for this process."""
    from zpkt.live import config

    os.environ.update(RIG_ENV)
    config.rig.cache_clear()
