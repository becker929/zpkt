"""Rig settings: what Live is called on this Mac and where its sets and data live.

They differ per machine, so none of them is in the repo. Each key comes from its environment
variable, else from ~/.config/zpkt/rig.toml (or the file $ZPKT_RIG_CONFIG names), else a neutral
default:

    key             env                  default
    live_app        ZPKT_LIVE_APP        Ableton Live 12 Suite
    live_port       ZPKT_LIVE_PORT       16619                  the AbletonLiveMCP Remote Script's port; a test
                                                                points it at a FakeLive (zpkt.live.testing)
    sets_dir        ZPKT_SETS_DIR        ~/Music/zpkt/sets      the Live sets hands opens, copies, saves
    data_dir        ZPKT_DATA_DIR        ~/Music/zpkt/data      probe kits, renders, bench.jsonl
    renders_dir     ZPKT_RENDERS_DIR     ~/Music/zpkt/renders   where `hands live export NAME` writes
    set_prefixes    ZPKT_SET_PREFIXES    zpkt_                  sets the guards accept as ours (comma-
                                                                separated in the environment); new sets
                                                                are named with the first one
    live_prefs_dir  ZPKT_LIVE_PREFS_DIR  the newest ~/Library/Preferences/Ableton/Live */ (Log.txt)
    library_dir     ZPKT_LIBRARY_DIR     ~/Music/zpkt/library   work-in-progress Live projects, one folder per
                                                                track; read-only (hands library inventory)
    mixdesk_dir     ZPKT_MIXDESK_DIR     (empty: contrib/mixdesk of a source checkout)   the desk's own files
                                                                (desk.json, sources.json, pager.py)
    arranger_dir    ZPKT_ARRANGER_DIR    ~/Music/zpkt/arranger  the arranger's data, read for the Song
                                                                (ARRANGER_DATA still works)
    ask_dir         ZPKT_ASK_DIR         ~/Music/zpkt/ask       Ask's sessions and files
    records_file    ZPKT_RECORDS_FILE    <library_dir>/records.toml   what you have declared done per track,
                                                                which beats the inventory's guess
    abilities_dir   ZPKT_ABILITIES_DIR   <sets_dir>/abilities   code for Live you allowed an agent to run for good
                                                                (the app's abilities), one file each; not per set

A front set without one of the prefixes means someone else is using Live, so the session guards
stop rather than act on it. A key that is retired (RETIRED) is still accepted in the file, and ignored.
"""

from __future__ import annotations

import functools
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILE = "~/.config/zpkt/rig.toml"
DEFAULTS = {
    "live_app": "Ableton Live 12 Suite",
    "live_port": 16619,
    "sets_dir": "~/Music/zpkt/sets",
    "data_dir": "~/Music/zpkt/data",
    "renders_dir": "~/Music/zpkt/renders",
    "set_prefixes": ["zpkt_"],
    "live_prefs_dir": "",
    "library_dir": "~/Music/zpkt/library",
    "records_file": "",
    "mixdesk_dir": "",
    "arranger_dir": "~/Music/zpkt/arranger",
    "ask_dir": "~/Music/zpkt/ask",
    "abilities_dir": "",
}
# Folders an older checkout of the app used when no setting names one; kept only so an existing rig carries on.
LEGACY_DIRS = {
    "arranger_dir": "~/_agent_scratch/arranger",
    "ask_dir": "~/_agent_scratch/zpkt-app/ask",
}
RETIRED = {"plans_dir": "the plan render cache; hands plan was archived on 24 Nov 2026 (zpkt-archive)"}


@dataclass(frozen=True)
class Rig:
    live_app: str
    live_port: int
    sets_dir: Path
    data_dir: Path
    renders_dir: Path
    set_prefixes: tuple[str, ...]
    live_prefs_dir: Path | None
    library_dir: Path
    records_file: Path
    arranger_dir: Path
    ask_dir: Path
    abilities_dir: Path
    mixdesk_dir: Path | None = None  # None: contrib/mixdesk of a source checkout

    def set_path(self, name: str) -> Path:
        """The .als of a set named `name` in sets_dir."""
        return self.sets_dir / f"{name}.als"

    def is_ours(self, set_name: str) -> bool:
        return set_name.startswith(self.set_prefixes)

    @property
    def new_set_prefix(self) -> str:
        return self.set_prefixes[0]

    @property
    def live_log(self) -> Path | None:
        return self.live_prefs_dir / "Log.txt" if self.live_prefs_dir else None


def load(env: Mapping[str, str] = os.environ, path: str | Path | None = None) -> Rig:
    """Read the settings: environment over the TOML file over the defaults."""
    file = Path(path or env.get("ZPKT_RIG_CONFIG") or CONFIG_FILE).expanduser()
    values: dict[str, Any] = dict(DEFAULTS)
    if file.exists():
        loaded = tomllib.loads(file.read_text())
        unknown = loaded.keys() - DEFAULTS.keys() - RETIRED.keys()
        if unknown:
            raise ValueError(f"{file}: unknown keys {sorted(unknown)}; known: {sorted(DEFAULTS)}")
        values.update({k: v for k, v in loaded.items() if k not in RETIRED})
    if env.get("ARRANGER_DATA"):  # the arranger's own name for its folder
        values["arranger_dir"] = env["ARRANGER_DATA"]
    for key in DEFAULTS:
        if env.get(f"ZPKT_{key.upper()}"):
            values[key] = env[f"ZPKT_{key.upper()}"]
    for key, old in LEGACY_DIRS.items():
        unset = values[key] == DEFAULTS[key]  # not set anywhere: an old folder that exists still wins
        if unset and Path(old).expanduser().is_dir() and not Path(values[key]).expanduser().is_dir():
            values[key] = old
    prefixes = values["set_prefixes"]
    if isinstance(prefixes, str):
        prefixes = [p.strip() for p in prefixes.split(",")]
    prefixes = tuple(p for p in prefixes if p)
    if not prefixes:
        raise ValueError("set_prefixes is empty: the guards would accept any set")
    return Rig(
        live_app=values["live_app"],
        live_port=_port(values["live_port"]),
        sets_dir=Path(values["sets_dir"]).expanduser(),
        data_dir=Path(values["data_dir"]).expanduser(),
        renders_dir=Path(values["renders_dir"]).expanduser(),
        set_prefixes=prefixes,
        live_prefs_dir=Path(values["live_prefs_dir"]).expanduser()
        if values["live_prefs_dir"]
        else _newest_live_prefs(),
        library_dir=Path(values["library_dir"]).expanduser(),
        records_file=Path(values["records_file"] or Path(values["library_dir"]) / "records.toml").expanduser(),
        mixdesk_dir=Path(values["mixdesk_dir"]).expanduser() if values["mixdesk_dir"] else None,
        arranger_dir=Path(values["arranger_dir"]).expanduser(),
        ask_dir=Path(values["ask_dir"]).expanduser(),
        abilities_dir=Path(values["abilities_dir"] or Path(values["sets_dir"]) / "abilities").expanduser(),
    )


def _port(value: Any) -> int:
    """A TCP port from the file (a number) or the environment (text)."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        port = 0
    if isinstance(value, bool) or not 0 < port < 65536 or str(port) != str(value).strip():
        raise ValueError(f"live_port must be a TCP port number (1-65535), not {value!r}")
    return port


@functools.cache
def rig() -> Rig:
    """This process's settings, read once. Tests call rig.cache_clear() after changing them."""
    return load()


ABLETON_PREFS = Path("~/Library/Preferences/Ableton").expanduser()


def _newest_live_prefs(root: Path = ABLETON_PREFS) -> Path | None:
    """The preferences folder of the newest Live installed ("Live 12.4.6" beats "Live 12.4.5")."""

    def version(p: Path) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", p.name))

    folders = [p for p in root.glob("Live *") if p.is_dir()] if root.is_dir() else []
    return max(folders, key=version, default=None)
