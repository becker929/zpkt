"""The rig settings for the Juice Box sound set, then rummage's Live helpers (liveops), pointed at this set's folder.

Import this before hands: hands reads the rig from the environment on import.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

SCRATCH = Path("~/_agent_scratch/juicebox").expanduser()
SET_NAME = "JUICE_sounds"
SET_DIR = SCRATCH / "set" / f"{SET_NAME} Project"
os.environ.setdefault("ZPKT_SETS_DIR", str(SET_DIR))
os.environ.setdefault("ZPKT_SET_PREFIXES", "JUICE_,PROPTEST_,INDUS_,MARROW_,SH001_")   # the others: to save one before leaving it
os.environ.setdefault("ZPKT_DATA_DIR", str(SCRATCH / "data"))
os.environ.setdefault("ZPKT_RENDERS_DIR", str(SCRATCH / "renders"))

# liveops by its path, as proptest does (rummage/ on sys.path would shadow modules here)
_spec = importlib.util.spec_from_file_location("liveops", Path(__file__).resolve().parents[1] / "rummage" / "liveops.py")
L = importlib.util.module_from_spec(_spec)
sys.modules["liveops"] = L
_spec.loader.exec_module(L)  # after the environment above

L.SCRATCH = SCRATCH
L.SET_NAME = SET_NAME
L.SET_DIR = SET_DIR
