"""The booth: scores in, Live renders out, for the Bluesky music bot (docs/design/bluesky-bot.md).

hands reads its rig from the environment when it is first used, so the booth's own rig is set here, before anything
imports hands: its sets live in the booth's folder and only `booth_` sets count as ours, so no guard ever lets it
act on one of Anthony's sets.
"""

import os
from pathlib import Path

HOME = Path(os.environ.get("BOOTH_HOME", Path.home() / "_agent_scratch" / "booth")).expanduser()
SETS_DIR = HOME / "sets" / "booth Project"          # Live keeps a set in "<name> Project/"; every job set shares it
PREFIX = "booth_"
TEMPLATE = "booth_template"

os.environ["ZPKT_SETS_DIR"] = str(SETS_DIR)
os.environ["ZPKT_SET_PREFIXES"] = PREFIX
os.environ["ZPKT_DATA_DIR"] = str(HOME / "data")
os.environ["ZPKT_RENDERS_DIR"] = str(HOME / "renders")
