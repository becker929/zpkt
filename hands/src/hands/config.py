"""Rig settings: what Live is called on this Mac and where its sets and data live.

They differ per machine, so none of them is in the repo. Each key comes from its environment
variable, else from ~/.config/zpkt/rig.toml (or the file $ZPKT_RIG_CONFIG names), else a neutral
default:

    key             env                  default
    live_app        ZPKT_LIVE_APP        Ableton Live 12 Suite
    sets_dir        ZPKT_SETS_DIR        ~/Music/zpkt/sets      the Live sets hands opens, copies, saves
    data_dir        ZPKT_DATA_DIR        ~/Music/zpkt/data      probe kits, renders, bench.jsonl
    renders_dir     ZPKT_RENDERS_DIR     ~/Music/zpkt/renders   where `hands live export NAME` writes
    set_prefixes    ZPKT_SET_PREFIXES    zpkt_                  sets the guards accept as ours (comma-
                                                                separated in the environment); new sets
                                                                are named with the first one
    live_prefs_dir  ZPKT_LIVE_PREFS_DIR  the newest ~/Library/Preferences/Ableton/Live */ (Log.txt)

A front set without one of the prefixes means someone else is using Live, so the session guards
stop rather than act on it.
"""

from __future__ import annotations

import functools
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILE = "~/.config/zpkt/rig.toml"
DEFAULTS = {
    "live_app": "Ableton Live 12 Suite",
    "sets_dir": "~/Music/zpkt/sets",
    "data_dir": "~/Music/zpkt/data",
    "renders_dir": "~/Music/zpkt/renders",
    "set_prefixes": ["zpkt_"],
    "live_prefs_dir": "",
}


@dataclass(frozen=True)
class Rig:
    live_app: str
    sets_dir: Path
    data_dir: Path
    renders_dir: Path
    set_prefixes: tuple[str, ...]
    live_prefs_dir: Path | None

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
    values = dict(DEFAULTS)
    if file.exists():
        loaded = tomllib.loads(file.read_text())
        unknown = loaded.keys() - DEFAULTS.keys()
        if unknown:
            raise ValueError(f"{file}: unknown keys {sorted(unknown)}; known: {sorted(DEFAULTS)}")
        values.update(loaded)
    for key in DEFAULTS:
        if env.get(f"ZPKT_{key.upper()}"):
            values[key] = env[f"ZPKT_{key.upper()}"]
    prefixes = values["set_prefixes"]
    if isinstance(prefixes, str):
        prefixes = [p.strip() for p in prefixes.split(",")]
    prefixes = tuple(p for p in prefixes if p)
    if not prefixes:
        raise ValueError("set_prefixes is empty: the guards would accept any set")
    return Rig(
        live_app=values["live_app"],
        sets_dir=Path(values["sets_dir"]).expanduser(),
        data_dir=Path(values["data_dir"]).expanduser(),
        renders_dir=Path(values["renders_dir"]).expanduser(),
        set_prefixes=prefixes,
        live_prefs_dir=Path(values["live_prefs_dir"]).expanduser() if values["live_prefs_dir"] else _newest_live_prefs(),
    )


@functools.cache
def rig() -> Rig:
    """This process's settings, read once. Tests call rig.cache_clear() after changing them."""
    return load()


def _newest_live_prefs(root: Path = Path("~/Library/Preferences/Ableton").expanduser()) -> Path | None:
    """The preferences folder of the newest Live installed ("Live 12.4.6" beats "Live 12.4.5")."""
    def version(p: Path) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", p.name))
    folders = [p for p in root.glob("Live *") if p.is_dir()] if root.is_dir() else []
    return max(folders, key=version, default=None)
