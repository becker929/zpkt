"""The desk's history: every control move, undo and redo, checkpoints, and what changed between two points.

A move is one control going from one value to another; moves of the same control within COALESCE_S of each other
are one entry (a fader sweep is one step to undo), and controls that move at the same moment (the parameters of a
macro) are one entry together. Undo writes the "from" values back; redo the "to" values. A
revert to a checkpoint is one entry too, so it can be undone.

A checkpoint is the whole mix (hands.live.state: every fader, send, mute and device value of the set), saved as
<sets_dir>/state/<set>/<name>.json, so `hands live state put NAME` and `diff NAME` work on it as well. Every state
file there is a checkpoint here, including ones made outside the desk (B, the recipe; working-0854). Keys are the
state's keys ("Hats bus/desk EQ/1 Gain A", "Kick bus/volume"), which is what the pager reports for each control.

The history itself is kept in HISTORY_DIR/<set>.json, so it outlives a server restart.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from hands import config
from hands.live import state as S

COALESCE_S = 2.0          # one control moved again within this long: the same step
TOGETHER_S = 0.3          # another control moved within this long of the step: the same gesture (a macro's parameters)
EXPECT_S = 2.0            # a value the desk wrote itself (undo, redo, revert) is not a new move for this long
KEEP = 500                # entries kept on disk
HISTORY_DIR = Path("~/_agent_scratch/mixdesk/history").expanduser()
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}$")


def same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), abs_tol=1e-6)


class History:
    def __init__(self, set_name: str, labels: dict[str, str]) -> None:
        self.set_name, self.labels = set_name, labels
        self.lock = threading.RLock()
        self.cur: dict[str, list] = {}           # key -> [shown, raw], as Live has it now
        self.expect: dict[str, tuple[float, float]] = {}   # key -> (raw the desk wrote, until)
        self.file = HISTORY_DIR / f"{set_name}.json"
        try:
            d = json.loads(self.file.read_text())
            self.entries, self.pos, self.seq = d["entries"], d["pos"], d.get("seq", len(d["entries"]))
        except (FileNotFoundError, ValueError, KeyError):
            self.entries, self.pos, self.seq = [], 0, 0

    # ---- what Live reports ---------------------------------------------------------------------------------------
    def baseline(self, values: dict) -> None:
        """The snapshot's values ({"page:slot": {"key", "s", "r"}}): the starting point, recorded as no move."""
        with self.lock:
            for v in values.values():
                if v.get("key") and v.get("r") is not None:
                    self.cur[v["key"]] = [str(v.get("s", "")).strip(), v["r"]]

    def seen(self, key: str | None, shown: str, raw: Any, sys: bool = False) -> bool:
        """A control's value as Live reports it. Returns True if that made or extended a history entry."""
        if not key or raw is None:
            return False
        with self.lock:
            shown = str(shown).strip()
            before = self.cur.get(key)
            self.cur[key] = [shown, raw]
            if before is None or same(before[1], raw):
                return False
            exp = self.expect.get(key)
            if exp and time.time() < exp[1]:
                if same(exp[0], raw):
                    self.expect.pop(key, None)
                return False
            if sys:
                return False
            now = time.time()
            top = self.entries[-1] if self.entries and self.pos == len(self.entries) else None
            if top and top["k"] == "move" and now - top["at"] < COALESCE_S:
                mine = next((m for m in top["moves"] if m["key"] == key), None)
                if mine is not None:                       # the same control, still moving
                    mine["to"] = [shown, raw]
                    top["at"] = now
                    if same(mine["from"][1], raw) and len(top["moves"]) == 1:   # back where it started: no step
                        self.entries.pop()
                        self.pos -= 1
                    self._save()
                    return True
                if now - top["at"] < TOGETHER_S:           # another control at the same moment: one gesture (a macro)
                    top["moves"].append({"key": key, "label": self.labels.get(key, key), "from": before, "to": [shown, raw]})
                    top["at"] = now
                    self._save()
                    return True
            self._push({"k": "move", "moves": [{"key": key, "label": self.labels.get(key, key),
                                                "from": before, "to": [shown, raw]}]})
            self._save()
            return True

    # ---- undo, redo -----------------------------------------------------------------------------------------------
    def _push(self, entry: dict) -> dict:
        del self.entries[self.pos:]           # a new step drops what could be redone
        self.seq += 1
        entry.update(id=self.seq, at=time.time())
        self.entries.append(entry)
        if len(self.entries) > KEEP:
            cut = len(self.entries) - KEEP
            self.entries = self.entries[cut:]
        self.pos = len(self.entries)
        return entry

    def _writes(self, moves: list[dict], side: str) -> list[list]:
        until = time.time() + EXPECT_S
        out = []
        for m in moves:
            raw = m[side][1]
            self.expect[m["key"]] = (raw, until)
            out.append([m["key"], raw])
        return out

    def undo(self) -> tuple[list[list], dict | None]:
        """[[key, raw], ...] to write, and the entry undone; checkpoints are passed over."""
        with self.lock:
            i = self.pos - 1
            while i >= 0 and self.entries[i]["k"] == "checkpoint":
                i -= 1
            if i < 0:
                return [], None
            e = self.entries[i]
            self.pos = i
            self._save()
            return self._writes(list(reversed(e["moves"])), "from"), e

    def redo(self) -> tuple[list[list], dict | None]:
        with self.lock:
            i = self.pos
            while i < len(self.entries) and self.entries[i]["k"] == "checkpoint":
                i += 1
            if i >= len(self.entries):
                return [], None
            e = self.entries[i]
            self.pos = i + 1
            self._save()
            return self._writes(e["moves"], "to"), e

    def revert(self, name: str, keys: list[str] | None = None) -> tuple[list[list], dict | None]:
        """Every desk control (or only `keys`) back to checkpoint `name`, as one undoable entry."""
        with self.lock:
            moves = [{"key": k, "label": self.labels.get(k, k), "from": self.cur[k], "to": v["a"]}
                     for k, v in self.compare(name, "now").items() if keys is None or k in keys]
            if not moves:
                return [], None
            e = self._push({"k": "revert", "to": name, "moves": moves})
            self._save()
            return self._writes(moves, "to"), e

    # ---- checkpoints ----------------------------------------------------------------------------------------------
    def folder(self) -> Path:
        return S.folder(self.set_name)

    def checkpoints(self) -> list[dict]:
        d = self.folder()
        out = []
        for p in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []:
            out.append({"name": p.stem, "at": p.stat().st_mtime})
        return out

    def load(self, name: str) -> dict[str, list]:
        """A checkpoint's values for the desk's keys (all the keys it has)."""
        if not NAME_RE.match(name):
            raise ValueError(f"bad checkpoint name {name!r}")
        return S.flatten(S.load(self.folder() / f"{name}.json"))

    def checkpoint(self, name: str, full: dict, main_saved: dict | None) -> dict:
        """Save `full` (a state just taken) as checkpoint `name`, with the desk's own values on top (they are what
        the history knows), the monitor tracks as the desk leaves them (muted, not soloed) and Main's desk devices
        as they are when nothing is monitored. Adds a checkpoint entry to the history."""
        if not NAME_RE.match(name):
            raise ValueError("a checkpoint name is letters, digits, space . _ - (up to 60)")
        with self.lock:
            for tname, body in full["tracks"].items():
                mix = body["mixer"]
                if tname.startswith("mon "):
                    mix["mute"], mix["solo"] = ["True", True], ["False", False]
                if tname == "Main" and main_saved:
                    for d in body["devices"]:
                        if d["name"] in main_saved and "Device On" in d["params"]:
                            on = main_saved[d["name"]]
                            d["params"]["Device On"] = ["On" if on else "Off", on]
            S.save({**full, "name": name, "made_by": "mixdesk"}, self.folder() / f"{name}.json", self.set_name)
            e = self._push({"k": "checkpoint", "name": name, "moves": []})
            self._save()
            return e

    # ---- what changed ----------------------------------------------------------------------------------------------
    def compare(self, a: str, b: str = "now") -> dict[str, dict]:
        """{key: {"a": [shown, raw], "b": [shown, raw]}} for the desk's controls that differ between checkpoint `a`
        and `b` (a checkpoint, or "now"). Keys a checkpoint does not hold (a recipe holds only part) are left out."""
        with self.lock:
            va = self.load(a)
            vb = dict(self.cur) if b == "now" else self.load(b)
            out = {}
            for k in self.cur:
                x, y = va.get(k), vb.get(k)
                if x is not None and y is not None and not same(x[1], y[1]):
                    out[k] = {"a": x, "b": y}
            return out

    # ---- disk, and what the page shows -----------------------------------------------------------------------------
    def _save(self) -> None:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_name(f".{self.file.name}.tmp")
        tmp.write_text(json.dumps({"entries": self.entries, "pos": self.pos, "seq": self.seq}))
        os.replace(tmp, self.file)

    def view(self, last: int = 150) -> dict:
        with self.lock:
            start = max(0, len(self.entries) - last)
            return {"t": "hist", "entries": self.entries[start:], "pos": self.pos - start,
                    "can_undo": any(e["k"] != "checkpoint" for e in self.entries[:self.pos]),
                    "can_redo": any(e["k"] != "checkpoint" for e in self.entries[self.pos:]),
                    "checkpoints": self.checkpoints()}
