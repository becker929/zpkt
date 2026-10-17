"""The rig settings for the property-testing techno set, then rummage's Live helpers (liveops), pointed at this set's folder.

Import this before hands: hands reads the rig from the environment on import.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

SCRATCH = Path("~/_agent_scratch/hiki").expanduser()
SET_NAME = "PROPTEST_techno"
SET_DIR = SCRATCH / "set" / f"{SET_NAME} Project"
os.environ.setdefault("ZPKT_SETS_DIR", str(SET_DIR))
os.environ.setdefault("ZPKT_SET_PREFIXES", "PROPTEST_,INDUS_,MARROW_,SH001_")   # the other shorts: to save one before leaving it
os.environ.setdefault("ZPKT_DATA_DIR", str(SCRATCH / "data"))
os.environ.setdefault("ZPKT_RENDERS_DIR", str(SCRATCH / "renders"))

# liveops by its path: putting rummage/ on sys.path would shadow this folder's parts.py with SH001's
_spec = importlib.util.spec_from_file_location("liveops", Path(__file__).resolve().parents[1] / "rummage" / "liveops.py")
L = importlib.util.module_from_spec(_spec)
sys.modules["liveops"] = L
_spec.loader.exec_module(L)  # after the environment above

# Exports stay staged in rummage's folder (liveops.EXPORT_DIR): the Save panel reaches a folder only through its Where
# popup (a parent of where it is, or of a Recent Place), and a new folder is neither. export() moves each file on.
L.SCRATCH = SCRATCH
L.SET_NAME = SET_NAME
L.SET_DIR = SET_DIR
