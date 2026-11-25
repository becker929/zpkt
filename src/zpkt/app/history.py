"""The desk's history: every control move, undo and redo, checkpoints, and what changed between two points.

A move is one control going from one value to another; moves of the same control within COALESCE_S of each other
are one entry (a fader sweep is one step to undo), and controls that move at the same moment (the parameters of a
macro) are one entry together. Undo writes the "from" values back; redo the "to" values. A
revert to a checkpoint is one entry too, so it can be undone.

A checkpoint is the whole mix (zpkt.live.state: every fader, send, mute and device value of the set), saved as
<sets_dir>/state/<set>/<name>.json, so `hands live state put NAME` and `diff NAME` work on it as well. Every state
file there is a checkpoint here, including ones made outside the desk (B, the recipe; working-0854). Keys are the
state's keys ("Hats bus/desk EQ/1 Gain A", "Kick bus/volume"), which is what the pager reports for each control.

Each entry says who made it ("who": you, minilab, agent or sys; protocol.Who). A move by "sys" (the desk itself, a
monitor switch) is not a mix change and makes no entry, as before. An entry without "who" (every one written before
the field) is "you"; it is read and written back as it is.

The history itself is kept in HISTORY_DIR/<set>.json, so it outlives a server restart.

Moves made through the app's command bus (`record`) are entries too, and carry the bus's "who" (any of
zpkt.live.changes.WHO) and an optional "group": moves made together by one ask share a group and are one entry, so they
undo as one. Every settled entry also goes to the set's change stream (zpkt.live.changes.Stream) as one Change per
control, with the entry's group (or "gesture-<id>"), so "what did the agent touch" reads one file.

The history is shared by the UDP thread, the web threads and the supervisor, so every method takes its one lock,
including the label table it shares with the desk.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zpkt.app import protocol as P
from zpkt.live import changes as C
from zpkt.live import state as S

COALESCE_S = 2.0  # one control moved again within this long: the same step
TOGETHER_S = 0.3  # another control moved within this long of the step: the same gesture (a macro's parameters)
EXPECT_S = 2.0  # a value the desk wrote itself (undo, redo, revert) is not a new move for this long
KEEP = 500  # entries kept on disk
HISTORY_DIR = Path("~/_agent_scratch/mixdesk/history").expanduser()
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,60}$")


def check_name(name: str) -> str:
    """A checkpoint name as it may be saved; ValueError says what a name may hold."""
    if not NAME_RE.match(name):
        raise ValueError("a checkpoint name is letters, digits, space . _ - (up to 60)")
    return name


def group_of(entry: dict[str, Any]) -> str:
    """The group a history entry belongs to: the one it was recorded with, else one per gesture."""
    return str(entry.get("group") or f"gesture-{entry['id']}")


def who_of(entry: dict[str, Any]) -> str:
    """Who made a history entry; an entry from before the field was "you"."""
    return str(entry.get("who", P.DEFAULT_WHO))


def same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), abs_tol=1e-6)


class History:
    def __init__(
        self,
        set_name: str,
        labels: dict[str, str],
        directory: Path | None = None,
        checkpoints: Path | None = None,
        clock: Callable[[], float] = time.time,
        changes: C.Stream | None = None,
    ) -> None:
        """`directory` holds <set>.json (default HISTORY_DIR); `checkpoints` the set's hands states (default
        zpkt.live.state.folder(set_name)); `clock` gives seconds (tests pass their own); `changes` is the set's change
        stream (None: no stream is written)."""
        self.clock = clock
        self.changes = changes
        self._streamed: set[int] = set()  # ids of entries already in the stream
        self.first: dict[
            str, list[Any]
        ] = {}  # key -> [shown, raw] as first seen: the starting point "changed" counts from
        self.set_name, self.labels = set_name, labels
        self.directory = directory or HISTORY_DIR
        self.checkpoints_dir = checkpoints
        self.lock = threading.RLock()
        self.cur: dict[str, list[Any]] = {}  # key -> [shown, raw], as Live has it now
        self.expect: dict[str, list[tuple[float, float]]] = {}  # key -> [(raw the desk wrote, until)]: due back
        self.file = self.directory / f"{set_name}.json"
        try:
            d = json.loads(self.file.read_text())
            self.entries, self.pos, self.seq = d["entries"], d["pos"], d.get("seq", len(d["entries"]))
        except (FileNotFoundError, ValueError, KeyError):
            self.entries, self.pos, self.seq = [], 0, 0
        self._streamed = {e["id"] for e in self.entries}  # what was on disk before this run is not written again

    # ---- the label table the desk shares ------------------------------------------------------------------------
    def add_labels(self, labels: dict[str, str]) -> None:
        """Names for keys the history has not named yet (the desk learns them from the pager's snapshot)."""
        with self.lock:
            for key, label in labels.items():
                self.labels.setdefault(key, label)

    # ---- what Live reports ---------------------------------------------------------------------------------------
    def baseline(self, values: dict[str, Any]) -> None:
        """The snapshot's values ({"page:slot": {"key", "s", "r"}}): the starting point, recorded as no move."""
        with self.lock:
            for v in values.values():
                if v.get("key") and v.get("r") is not None:
                    self.cur[v["key"]] = [str(v.get("s", "")).strip(), v["r"]]
                    self.first.setdefault(v["key"], list(self.cur[v["key"]]))

    def seen(self, key: str | None, shown: str, raw: Any, sys: bool = False, *, who: P.Who | None = None) -> bool:
        """A control's value as Live reports it, moved by `who` (`sys=True` is who "sys", for older callers).
        Returns True if that made or extended a history entry."""
        if not key or raw is None:
            return False
        mover = who or ("sys" if sys else P.DEFAULT_WHO)
        with self.lock:
            shown = str(shown).strip()
            before = self.cur.get(key)
            self.cur[key] = [shown, raw]
            if before is not None and same(before[1], raw) and self._due(key, raw, consume=True):
                self._show(key, raw, shown)  # the echo of a write the desk made: it names the value
            if before is None or same(before[1], raw):
                return False
            if self.awaiting(key):  # the desk wrote this control a moment ago: what comes back is its echo
                if self._due(key, raw, consume=True):
                    self._show(key, raw, shown)
                return False
            if mover == "sys":
                return False
            now = self.clock()
            top = self.entries[-1] if self.entries and self.pos == len(self.entries) else None
            if (
                top
                and top["k"] == "move"
                and who_of(top) == mover
                and not top.get("group")
                and now - top["at"] < COALESCE_S
            ):
                mine = next((m for m in top["moves"] if m["key"] == key), None)
                if mine is not None:  # the same control, still moving
                    mine["to"] = [shown, raw]
                    top["at"] = now
                    if same(mine["from"][1], raw) and len(top["moves"]) == 1:  # back where it started: no step
                        self.entries.pop()
                        self.pos -= 1
                    self._save()
                    return True
                if now - top["at"] < TOGETHER_S:  # another control at the same moment: one gesture (a macro)
                    top["moves"].append(
                        {"key": key, "label": self.labels.get(key, key), "from": before, "to": [shown, raw]}
                    )
                    top["at"] = now
                    self._save()
                    return True
            self._push(
                {
                    "k": "move",
                    "moves": [{"key": key, "label": self.labels.get(key, key), "from": before, "to": [shown, raw]}],
                    "who": mover,
                }
            )
            self._save()
            return True

    def _due(self, key: str, raw: Any, consume: bool = False) -> bool:
        """True while a value the desk wrote for `key` (this raw value) is still due back from Live. Writes in a row
        are all due, since Live's echoes come late and in their own time."""
        waiting = self.expect.get(key, [])
        hit = next((w for w in waiting if raw is not None and same(w[0], raw)), None)
        if hit is not None and consume:
            waiting.remove(hit)
            if not waiting:
                self.expect.pop(key, None)
        return hit is not None

    def _expect(self, key: str, raw: Any, until: float) -> None:
        self.expect.setdefault(key, []).append((raw, until))

    def _show(self, key: str, raw: Any, shown: str) -> None:
        """Live reported what `shown` text a value the desk wrote has: put it in the entry that wrote it."""
        for e in reversed(self.entries[-5:]):
            for m in e.get("moves", []):
                if m["key"] == key and same(m["to"][1], raw):
                    m["to"][0] = shown
                    self._save()
                    return

    # ---- moves made through the command bus ------------------------------------------------------------------------
    def expect_writes(self, pairs: list[list[Any]]) -> None:
        """The desk is about to write [[key, raw], ...] into Live: the values that come back are not new moves."""
        with self.lock:
            until = self.clock() + EXPECT_S
            for key, raw, *_ in pairs:
                self._expect(key, raw, until)

    def record(self, pairs: list[list[Any]], who: P.Who | str, group: str | None = None) -> dict[str, Any] | None:
        """Moves the desk is writing for `who`: [[key, raw] or [key, raw, shown], ...] from what Live has now. One
        entry. Moves with the same `group` and `who` as the last entry join it, so an ask undoes as one. Returns the
        entry, or None when nothing moves."""
        if who not in C.WHO:
            raise ValueError(f"who is one of {', '.join(C.WHO)}, not {who!r}")
        with self.lock:
            now = self.clock()
            moves = []
            for key, raw, *rest in pairs:
                before = self.cur.get(key)
                shown = str(rest[0]) if rest else str(raw)
                if before is not None and same(before[1], raw):
                    continue
                moves.append({"key": key, "label": self.labels.get(key, key), "from": before, "to": [shown, raw]})
                self.cur[key] = [shown, raw]
            if not moves:
                return None
            self.expect_writes([[m["key"], m["to"][1]] for m in moves])
            top = self.entries[-1] if self.entries and self.pos == len(self.entries) else None
            if group and top and top["k"] == "move" and top.get("group") == group and who_of(top) == who:
                known = {m["key"]: m for m in top["moves"]}
                for m in moves:
                    if m["key"] in known:
                        known[m["key"]]["to"] = m["to"]
                    else:
                        top["moves"].append(m)
                top["at"] = now
                self._save()
                return top
            entry: dict[str, Any] = {"k": "move", "moves": moves, "who": who}
            if group:
                entry["group"] = group
            self._push(entry)
            self._save()
            return entry

    def value(self, key: str) -> list[Any] | None:
        """[shown, raw] of a control as the desk last saw it."""
        with self.lock:
            v = self.cur.get(key)
            return None if v is None else list(v)

    def forget(self, entry: dict[str, Any] | None) -> None:
        """Take back an entry `record` just made when the write it stood for failed: the values go back too."""
        if entry is None:
            return
        with self.lock:
            if self.entries and self.entries[-1] is entry:
                self.entries.pop()
                self.pos = len(self.entries)
                for m in entry["moves"]:
                    if m["from"] is not None:
                        self.cur[m["key"]] = list(m["from"])
                    self.expect.pop(m["key"], None)
                self._save()

    def awaiting(self, key: str) -> bool:
        """True while a value the desk wrote itself is still due back from Live for `key`."""
        with self.lock:
            now = self.clock()
            waiting = [w for w in self.expect.get(key, []) if now < w[1]]
            if waiting:
                self.expect[key] = waiting
            else:
                self.expect.pop(key, None)
            return bool(waiting)

    def rebase(self, key: str, value: list[Any]) -> None:
        """Say a control was at `value` (not what it reads now) before its next move: a move made while the pinned
        version was heard counts from where Now was."""
        with self.lock:
            self.cur[key] = list(value)

    # ---- the change stream -----------------------------------------------------------------------------------------
    def flush_changes(self, force: bool = False) -> int:
        """Write the settled entries (not moved for COALESCE_S, or all when `force`) to the change stream: one Change
        per control, from where the gesture started to where it ended. Returns how many Changes were written."""
        if self.changes is None:
            return 0
        with self.lock:
            now = self.clock()
            written: list[C.Change] = []
            for i, e in enumerate(self.entries):
                if e["id"] in self._streamed or e["k"] == "checkpoint":
                    self._streamed.add(e["id"])
                    continue
                last = i == len(self.entries) - 1
                if not force and last and now - e["at"] < COALESCE_S:
                    continue
                self._streamed.add(e["id"])
                written += self._changes_of(e)
            if written:
                self.changes.append(written)
            return len(written)

    def _changes_of(
        self, entry: dict[str, Any], undo: bool = False, who: str | None = None, step: str = ""
    ) -> list[C.Change]:
        at = C.stamp(entry["at"])
        mover = who or who_of(entry)
        group = f"{step}-of-{group_of(entry)}" if step else group_of(entry)
        return [
            C.change(m["key"], m["to"] if undo else m["from"], m["from"] if undo else m["to"], mover, at, group)  # type: ignore[arg-type]
            for m in entry["moves"]
        ]

    def _stream_step(self, entry: dict[str, Any], undo: bool, who: str) -> None:
        """An undo or redo is its own Change per control, by the one who asked for it."""
        self.flush_changes(force=True)
        if self.changes is not None:
            self.changes.append(
                self._changes_of({**entry, "at": self.clock()}, undo=undo, who=who, step="undo" if undo else "redo")
            )

    # ---- undo, redo -----------------------------------------------------------------------------------------------
    def _push(self, entry: dict[str, Any]) -> dict[str, Any]:
        del self.entries[self.pos :]  # a new step drops what could be redone
        self.seq += 1
        entry.update(id=self.seq, at=self.clock())
        self.entries.append(entry)
        if len(self.entries) > KEEP:
            cut = len(self.entries) - KEEP
            self.entries = self.entries[cut:]
        self.pos = len(self.entries)
        return entry

    def _writes(self, moves: list[dict[str, Any]], side: str) -> list[list[Any]]:
        until = self.clock() + EXPECT_S
        out = []
        for m in moves:
            raw = m[side][1]
            self._expect(m["key"], raw, until)
            self.cur[m["key"]] = list(m[side])  # what Live will have: counts are right before its echo comes back
            out.append([m["key"], raw])
        return out

    def undo(self, who: P.Who | str = P.DEFAULT_WHO) -> tuple[list[list[Any]], dict[str, Any] | None]:
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
            self._stream_step(e, True, str(who))
            return self._writes(list(reversed(e["moves"])), "from"), e

    def redo(self, who: P.Who | str = P.DEFAULT_WHO) -> tuple[list[list[Any]], dict[str, Any] | None]:
        with self.lock:
            i = self.pos
            while i < len(self.entries) and self.entries[i]["k"] == "checkpoint":
                i += 1
            if i >= len(self.entries):
                return [], None
            e = self.entries[i]
            self.pos = i + 1
            self._save()
            self._stream_step(e, False, str(who))
            return self._writes(e["moves"], "to"), e

    def revert(
        self, name: str, keys: list[str] | None = None, who: P.Who = P.DEFAULT_WHO
    ) -> tuple[list[list[Any]], dict[str, Any] | None]:
        """Every desk control (or only `keys`) back to checkpoint `name`, as one undoable entry."""
        with self.lock:
            moves = [
                {"key": k, "label": self.labels.get(k, k), "from": self.cur[k], "to": v["a"]}
                for k, v in self.compare(name, "now").items()
                if keys is None or k in keys
            ]
            if not moves:
                return [], None
            e = self._push({"k": "revert", "to": name, "moves": moves, "who": who})
            self._save()
            self._streamed.add(e["id"])
            if self.changes is not None:
                self.changes.append(self._changes_of(e))
            return self._writes(moves, "to"), e

    # ---- checkpoints ----------------------------------------------------------------------------------------------
    def folder(self) -> Path:
        return self.checkpoints_dir or S.folder(self.set_name)

    def checkpoints(self) -> list[dict[str, Any]]:
        d = self.folder()
        out = []
        for p in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []:
            out.append({"name": p.stem, "at": p.stat().st_mtime})
        return out

    def load(self, name: str) -> dict[str, S.ShownRaw]:
        """A checkpoint's values for the desk's keys (all the keys it has)."""
        if not NAME_RE.match(name):
            raise ValueError(f"bad checkpoint name {name!r}")
        return S.flatten(S.load(self.folder() / f"{name}.json"))

    def checkpoint(
        self, name: str, full: S.State, main_saved: dict[str, Any] | None, who: P.Who = P.DEFAULT_WHO
    ) -> dict[str, Any]:
        """Save `full` (a state just taken) as checkpoint `name`, with the desk's own values on top (they are what
        the history knows), the monitor tracks as the desk leaves them (muted, not soloed) and Main's desk devices
        as they are when nothing is monitored. Adds a checkpoint entry to the history."""
        check_name(name)
        with self.lock:
            for tname, body in full["tracks"].items():
                mix = body["mixer"]
                if tname.startswith("mon "):
                    mix["mute"], mix["solo"] = S.ShownRaw.of("True", True), S.ShownRaw.of("False", False)
                if tname == "Main" and main_saved:
                    for d in body["devices"]:
                        if d["name"] in main_saved and "Device On" in d["params"]:
                            on = main_saved[d["name"]]
                            d["params"]["Device On"] = S.ShownRaw.of("On" if on else "Off", on)
            # hands' State does not list a checkpoint's "name" and "made_by"; its readers keep unknown keys
            marked: Any = {**full, "name": name, "made_by": "mixdesk"}
            S.save(marked, self.folder() / f"{name}.json", self.set_name)
            e = self._push({"k": "checkpoint", "name": name, "moves": [], "who": who})
            self._save()
            return e

    # ---- what changed ----------------------------------------------------------------------------------------------
    def compare(self, a: str, b: str = "now") -> dict[str, dict[str, Any]]:
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
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_name(f".{self.file.name}.tmp")
        tmp.write_text(json.dumps({"entries": self.entries, "pos": self.pos, "seq": self.seq}))
        os.replace(tmp, self.file)

    def view(self, last: int = 150) -> dict[str, Any]:
        with self.lock:
            start = max(0, len(self.entries) - last)
            return {
                "t": "hist",
                "entries": self.entries[start:],
                "pos": self.pos - start,
                "can_undo": any(e["k"] != "checkpoint" for e in self.entries[: self.pos]),
                "can_redo": any(e["k"] != "checkpoint" for e in self.entries[self.pos :]),
                "checkpoints": self.checkpoints(),
            }
