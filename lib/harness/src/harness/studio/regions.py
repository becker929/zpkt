"""The regions' permanent state (docs/rummage.md): a region is a place in the world you play to finish a short, and
what stays when you leave it is kept here, one JSON file per region.

    <root>/<id>.json        root is <studio_dir>/regions

A state is the option committed at each machine, the artifact the wanderer carries, the artifacts on the plinths
(the Gramophone's three slots), every time the short was completed, and a small object of the page's own. The page
replaces it whole (POST), and it is validated first: a state the page could not have made is refused, so a bug never
writes something the next visit has to survive. Regions come from an allowlist. Everything runs on the event loop's
thread; the writes are tiny and atomic (a temporary file, then a rename).

    {"region": "rummage", "updated": 1760400000.0,
     "committed": {"bed": 2, "drums": null, "bass": 1},       # an option id 1..3, or null
     "carrying": "bass-1",                                     # an artifact id <part>-<option>, or null
     "plinths": {"bed": "bed-2", "drums": null, "bass": null}, # each slot holds an artifact of its own part
     "completions": [{"at": 1760400000.0, "combo": "2-3-1", "plate": "pl_..."}],   # combo is bed-drums-bass
     "page": {}}                                               # the page's own small things (<= 4 KB of JSON)
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REGIONS = ("rummage",)                   # the allowlist: a region id the page may read and write
PARTS = ("bed", "drums", "bass")         # the machines, in the order a combo names them
OPTIONS = (1, 2, 3)
ARTIFACT = re.compile(r"(bed|drums|bass)-([1-3])")
COMBO = re.compile(r"[1-3]-[1-3]-[1-3]")
KEYS = {"region", "updated", "committed", "carrying", "plinths", "completions", "page"}
COMPLETION_KEYS = {"at", "combo", "plate"}
COMPLETIONS_MAX = 1000                   # the newest are kept
PAGE_MAX = 4096                          # bytes of the page's own JSON


class Invalid(ValueError):
    """A state the page could not have made."""


def empty(region: str) -> dict[str, Any]:
    return {"region": region, "updated": None, "committed": dict.fromkeys(PARTS), "carrying": None,
            "plinths": dict.fromkeys(PARTS), "completions": [], "page": {}}


def _option(value: Any, where: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value not in OPTIONS:
        raise Invalid(f"{where}: {value!r} is not an option id (1, 2 or 3) or null")
    return value


def _artifact(value: Any, where: str, part: str | None = None) -> str | None:
    if value is None:
        return None
    m = ARTIFACT.fullmatch(value) if isinstance(value, str) else None
    if not m:
        raise Invalid(f"{where}: {value!r} is not an artifact id (<part>-<option>, e.g. bed-2) or null")
    if part is not None and m.group(1) != part:
        raise Invalid(f"{where}: {value!r} is not a {part} artifact")
    return value


def _by_part(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return dict.fromkeys(PARTS)
    if not isinstance(value, dict):
        raise Invalid(f"{where}: expected an object with bed, drums and bass")
    if extra := set(value) - set(PARTS):
        raise Invalid(f"{where}: unknown {sorted(extra)}")
    return {p: value.get(p) for p in PARTS}


def validate(state: Any) -> dict[str, Any]:
    """The state as it will be kept (missing keys at their defaults; region and updated are the server's), or
    Invalid naming the first problem."""
    if not isinstance(state, dict):
        raise Invalid("state: expected a JSON object")
    if extra := set(state) - KEYS:
        raise Invalid(f"state: unknown {sorted(extra)}")
    committed = {p: _option(v, f"committed.{p}") for p, v in _by_part(state.get("committed"), "committed").items()}
    plinths = {p: _artifact(v, f"plinths.{p}", p) for p, v in _by_part(state.get("plinths"), "plinths").items()}
    carrying = _artifact(state.get("carrying"), "carrying")
    completions = state.get("completions") or []
    if not isinstance(completions, list):
        raise Invalid("completions: expected a list")
    done = []
    for i, c in enumerate(completions):
        where = f"completions[{i}]"
        if not isinstance(c, dict):
            raise Invalid(f"{where}: expected an object")
        if extra := set(c) - COMPLETION_KEYS:
            raise Invalid(f"{where}: unknown {sorted(extra)}")
        at = c.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not at > 0:
            raise Invalid(f"{where}.at: expected a time (seconds since 1970)")
        combo = c.get("combo")
        if not isinstance(combo, str) or not COMBO.fullmatch(combo):
            raise Invalid(f"{where}.combo: {combo!r} is not <bed>-<drums>-<bass> (each 1, 2 or 3)")
        item = {"at": at, "combo": combo}
        if c.get("plate") is not None:
            if not isinstance(c["plate"], str) or not 0 < len(c["plate"]) <= 64:
                raise Invalid(f"{where}.plate: expected a plate id")
            item["plate"] = c["plate"]
        done.append(item)
    page = state.get("page") or {}
    if not isinstance(page, dict):
        raise Invalid("page: expected an object")
    if len(json.dumps(page, separators=(",", ":")).encode()) > PAGE_MAX:
        raise Invalid(f"page: more than {PAGE_MAX} bytes")
    return {"region": None, "updated": None, "committed": committed, "carrying": carrying, "plinths": plinths,
            "completions": done[-COMPLETIONS_MAX:], "page": page}


class RegionStore:
    def __init__(self, root: Path):
        self.root = root

    def path(self, region: str) -> Path:
        """The region's file; KeyError for a region not on the allowlist."""
        if region not in REGIONS:
            raise KeyError(region)
        return self.root / f"{region}.json"

    def get(self, region: str) -> dict[str, Any]:
        """The kept state, or an empty one. A file that can't be read is set aside, not lost, and the region starts
        empty."""
        path = self.path(region)
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            return empty(region)
        except (OSError, ValueError):
            log.warning("region %s: unreadable state, set aside", region, exc_info=True)
            path.replace(path.with_name(f"{region}.bad-{int(time.time())}.json"))
            return empty(region)
        try:
            state = validate({k: v for k, v in raw.items() if k in KEYS} if isinstance(raw, dict) else raw)
        except Invalid:
            log.warning("region %s: a kept state no longer validates, set aside", region, exc_info=True)
            path.replace(path.with_name(f"{region}.bad-{int(time.time())}.json"))
            return empty(region)
        return {**state, "region": region, "updated": raw.get("updated")}

    def put(self, region: str, state: Any) -> dict[str, Any]:
        """Replace the region's state; returns it as kept. Invalid if the page could not have made it."""
        path = self.path(region)
        kept = {**validate(state), "region": region, "updated": time.time()}
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        part.write_text(json.dumps(kept, separators=(",", ":")))
        part.replace(path)
        return kept
