"""The desk's history: every control move, undo and redo, checkpoints, and what changed between two points.

A move is one control going from one value to another. Changes to the same control by the same person, one after
the other with nothing else in between, are one entry: a drag, then nudges, then more nudges are one step to undo,
back to where the control was before the first of them. The step ends when another control is touched, a checkpoint
is saved, something is undone, or SAME_CONTROL_S pass without a change. Controls that move at the same moment (the
parameters of a macro) are one entry together. Undo writes the "from" values back; redo the "to" values. A
revert to a checkpoint is one entry too, so it can be undone, and so is going back to just before any entry (`back`).

"Changed" counts against the base: the mix as it was at the last checkpoint saved or gone back to (`base`,
`base_name`, `changed`). Right after a save or a go back it is zero.

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

import contextlib
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zpkt.app import protocol
from zpkt.live import changes as live_changes
from zpkt.live import state as live_state

COALESCE_S = 2.0  # an entry not touched for this long is settled: it goes to the change stream
SAME_CONTROL_S = 30.0  # the same control changed again by the same person within this long: the same step
JOINERS = ("you", "minilab")  # whose changes to one control join into one step (a hand); an agent's are by group
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
    return str(entry.get("who", protocol.DEFAULT_WHO))


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
        changes: live_changes.Stream | None = None,
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
        self.named = False  # an echo gave a written value its shown text: the page's rows want the view again
        self.base: dict[str, list[Any]] | None = None  # the values "changed" counts from; None until first asked
        self.base_name = ""  # the checkpoint they are from ("": the mix as first seen)
        self.quiet: set[str] = set()  # keys that are no part of the mix (the spectrum's device): never "changed"
        self.place: Callable[[str, Any], float | None] = lambda key, raw: None  # a raw value as a place 0..1
        self._tail: dict[int, dict[str, list[Any]]] = {}  # entry id -> {key: "to" as streamed}, for a step that grew
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
                    if self.base is not None:
                        self.base.setdefault(v["key"], list(self.cur[v["key"]]))

    def baseline_flags(self, tracks: list[str], solo: list[str], mute: list[str]) -> None:
        """Every track's solo and mute as the snapshot has them ("Kick bus/solo"): a starting point, no move."""
        with self.lock:
            for flag, on in (("solo", set(solo)), ("mute", set(mute))):
                for name in tracks:
                    key = f"{name}/{flag}"
                    self.cur[key] = ["on" if name in on else "off", name in on]
                    self.first.setdefault(key, list(self.cur[key]))
                    self.labels.setdefault(key, f"{name} {flag}")
                    if self.base is not None:
                        self.base.setdefault(key, list(self.cur[key]))

    def seen(
        self, key: str | None, shown: str, raw: Any, sys: bool = False, *, who: protocol.Who | None = None
    ) -> bool:
        """A control's value as Live reports it, moved by `who` (`sys=True` is who "sys", for older callers).
        Returns True if that made or extended a history entry."""
        if not key or raw is None:
            return False
        mover = who or ("sys" if sys else protocol.DEFAULT_WHO)
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
            if self._same_control(top, [key], mover, now):  # the same control again, by the same hand: one step
                assert top is not None
                mine = top["moves"][0]
                self._grew(top)
                mine["to"] = [shown, raw]
                top["at"] = now
                if mine["from"] is not None and same(mine["from"][1], raw):  # back where it started: no step
                    self._drop_top()
                self._save()
                return True
            if (
                top
                and top["k"] == "move"
                and who_of(top) == mover
                and not top.get("group")
                and now - top["at"] < COALESCE_S
            ):
                mine = next((m for m in top["moves"] if m["key"] == key), None)
                if mine is not None and not isinstance(raw, bool):  # the same control, still moving (a macro's part)
                    mine["to"] = [shown, raw]
                    top["at"] = now
                    self._save()
                    return True
                if mine is None and now - top["at"] < TOGETHER_S:  # another control at the same moment: a macro
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

    def _same_control(self, top: dict[str, Any] | None, keys: list[str], who: str, now: float) -> bool:
        """True when a change to `keys` by `who` now belongs to the step on top: that step is one control's, these
        are changes to that control only, by the same hand, and it was last changed less than SAME_CONTROL_S ago."""
        if top is None or top["k"] != "move" or top.get("compare") or who not in JOINERS or who_of(top) != who:
            return False
        if len(top["moves"]) != 1 or any(k != top["moves"][0]["key"] for k in keys):
            return False
        if isinstance(top["moves"][0]["to"][1], bool):
            return False  # a switch thrown (a solo, a mute) is a step each time: on and off again is not "nothing"
        return bool(now - top["at"] < SAME_CONTROL_S)

    def _grew(self, entry: dict[str, Any]) -> None:
        """A step already in the change stream is about to grow: remember where the stream left each control."""
        if entry["id"] in self._streamed and entry["id"] not in self._tail:
            self._tail[entry["id"]] = {m["key"]: list(m["to"]) for m in entry["moves"]}

    def _drop_top(self) -> None:
        """The step on top moved nothing in the end: it is no step. What the stream has of it is written back."""
        entry = self.entries.pop()
        self.pos = len(self.entries)
        tail = self._tail.pop(entry["id"], None)
        if tail and self.changes is not None:
            at = live_changes.stamp(self.clock())
            self.changes.append(
                [
                    live_changes.change(m["key"], tail[m["key"]], m["to"], who_of(entry), at, group_of(entry))  # type: ignore[arg-type]
                    for m in entry["moves"]
                    if m["key"] in tail and not same(tail[m["key"]][1], m["to"][1])
                ]
            )

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
                    if m["to"][0] != shown:
                        m["to"][0] = shown
                        self.named = True
                        self._save()
                    return

    def take_named(self) -> bool:
        """True once after an echo named a written value (its shown text is in the entry now)."""
        with self.lock:
            named, self.named = self.named, False
            return named

    # ---- moves made through the command bus ------------------------------------------------------------------------
    def expect_writes(self, pairs: list[list[Any]]) -> None:
        """The desk is about to write [[key, raw], ...] into Live: the values that come back are not new moves."""
        with self.lock:
            until = self.clock() + EXPECT_S
            for key, raw, *_ in pairs:
                self._expect(key, raw, until)

    def written(self, pairs: list[list[Any]]) -> None:
        """The write of [[key, raw], ...] has come back from Live: its echoes are due from now. A write that took
        longer than EXPECT_S (Live was busy) would else have its late echo read as a new move."""
        with self.lock:
            until = self.clock() + EXPECT_S
            for key, raw, *_ in pairs:
                waiting = self.expect.get(key, [])
                for i, w in enumerate(waiting):
                    if same(w[0], raw):
                        waiting[i] = (w[0], until)

    def record(
        self,
        pairs: list[list[Any]],
        who: protocol.Who | str,
        group: str | None = None,
        compare: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Moves the desk is writing for `who`: [[key, raw] or [key, raw, shown], ...] from what Live has now. One
        entry. Moves with the same `group` and `who` as the last entry join it, so an ask undoes as one. Returns the
        entry, or None when nothing moves. `compare` names a switch of compare states ({"name", "from", "to"}): the
        entry keeps it, and it is always an entry of its own."""
        if who not in live_changes.WHO:
            raise ValueError(f"who is one of {', '.join(live_changes.WHO)}, not {who!r}")
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
            joins = group and top and top["k"] == "move" and top.get("group") == group and who_of(top) == who
            joins = joins or (not compare and self._same_control(top, [m["key"] for m in moves], str(who), now))
            if joins and top and not compare and not top.get("compare"):
                self._grew(top)
                known = {m["key"]: m for m in top["moves"]}
                for m in moves:
                    if m["key"] in known:
                        known[m["key"]]["to"] = m["to"]
                    else:
                        top["moves"].append(m)
                top["at"] = now
                # a control brought back to where the gesture found it did not move; a gesture that moved nothing
                # is no step at all
                top["moves"] = [m for m in top["moves"] if m["from"] is None or not same(m["from"][1], m["to"][1])]
                if not top["moves"]:
                    top["moves"] = list(known.values())  # what _drop_top writes back to the stream
                    self._drop_top()
                    self._save()
                    return None
                self._save()
                return top
            entry: dict[str, Any] = {"k": "move", "moves": moves, "who": who}
            if group:
                entry["group"] = group
            if compare:
                entry["compare"] = dict(compare)
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
            written: list[live_changes.Change] = []
            for i, e in enumerate(self.entries):
                if e["id"] in self._streamed or e["k"] == "checkpoint":
                    self._streamed.add(e["id"])
                    continue
                last = i == len(self.entries) - 1
                if not force and last and now - e["at"] < COALESCE_S:
                    continue
                self._streamed.add(e["id"])
                written += self._changes_of(e)
            for e in self.entries:  # a step that grew after it was streamed: the rest of it, once it has settled
                tail = self._tail.get(e["id"])
                if tail is None or (not force and e is self.entries[-1] and now - e["at"] < COALESCE_S):
                    continue
                del self._tail[e["id"]]
                at = live_changes.stamp(e["at"])
                written += [
                    live_changes.change(m["key"], tail[m["key"]], m["to"], who_of(e), at, group_of(e))  # type: ignore[arg-type]
                    for m in e["moves"]
                    if m["key"] in tail and not same(tail[m["key"]][1], m["to"][1])
                ]
            if written:
                self.changes.append(written)
            return len(written)

    def _changes_of(
        self, entry: dict[str, Any], undo: bool = False, who: str | None = None, step: str = ""
    ) -> list[live_changes.Change]:
        at = live_changes.stamp(entry["at"])
        mover = who or who_of(entry)
        group = f"{step}-of-{group_of(entry)}" if step else group_of(entry)
        return [
            live_changes.change(
                m["key"],
                m["to"] if undo else m["from"],
                m["from"] if undo else m["to"],
                mover,  # type: ignore[arg-type]
                at,
                group,
            )
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
    def _push(self, entry: dict[str, Any], keep_redo: bool = False) -> dict[str, Any]:
        """A new entry at the place undo stands. A step drops what could be redone; a checkpoint (`keep_redo`)
        changes nothing in the mix, so the undone steps after it stay and can still be redone."""
        if not keep_redo:
            del self.entries[self.pos :]
        self.seq += 1
        entry.update(id=self.seq, at=self.clock())
        self.entries.insert(self.pos, entry)
        self.pos += 1
        if len(self.entries) > KEEP:
            cut = len(self.entries) - KEEP
            self.entries = self.entries[cut:]
            self.pos = max(0, self.pos - cut)
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

    def undo(self, who: protocol.Who | str = protocol.DEFAULT_WHO) -> tuple[list[list[Any]], dict[str, Any] | None]:
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

    def redo(self, who: protocol.Who | str = protocol.DEFAULT_WHO) -> tuple[list[list[Any]], dict[str, Any] | None]:
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
        self, name: str, keys: list[str] | None = None, who: protocol.Who = protocol.DEFAULT_WHO
    ) -> tuple[list[list[Any]], dict[str, Any] | None]:
        """Every desk control (or only `keys`) back to checkpoint `name`, as one undoable entry."""
        with self.lock:
            moves = [
                {"key": k, "label": self.labels.get(k, k), "from": self.cur[k], "to": v["a"]}
                for k, v in self.compare(name, "now").items()
                if keys is None or k in keys
            ]
            if not moves:
                if keys is None:
                    self._rebase(name)  # already there: "changed" counts from this checkpoint all the same
                return [], None
            pairs, e = self._go({"k": "revert", "to": name, "moves": moves, "who": who})
            if keys is None:
                self._rebase(name)
            return pairs, e

    def _go(self, entry: dict[str, Any]) -> tuple[list[list[Any]], dict[str, Any]]:
        """Push a going-back entry (its moves' "to" are where the controls go) and hand over the writes."""
        e = self._push(entry)
        self._save()
        self._streamed.add(e["id"])
        if self.changes is not None:
            self.changes.append(self._changes_of(e))
        return self._writes(e["moves"], "to"), e

    def back(self, entry_id: int, who: protocol.Who | str = protocol.DEFAULT_WHO) -> tuple[list[list[Any]], Any]:
        """Every control back to where it was just before the entry `entry_id` (a step still in effect), as one
        undoable entry: that step and every later one are taken back together. KeyError when there is no such
        step, or it is undone already."""
        with self.lock:
            at = next(
                (i for i, e in enumerate(self.entries[: self.pos]) if e["id"] == entry_id and e["k"] != "checkpoint"),
                None,
            )
            if at is None:
                raise KeyError(entry_id)
            target: dict[str, list[Any]] = {}
            for e in reversed(self.entries[at : self.pos]):  # newest first: the oldest "from" of a control wins
                for m in e.get("moves", []):
                    if m["from"] is not None:
                        target[m["key"]] = list(m["from"])
            moves = [
                {"key": k, "label": self.labels.get(k, k), "from": self.cur[k], "to": v}
                for k, v in target.items()
                if k in self.cur and not same(self.cur[k][1], v[1])
            ]
            if not moves:
                return [], None
            first = self.entries[at]
            named = first.get("compare", {}).get("name") or (first["moves"][0]["label"] if first["moves"] else "")
            what = {"id": entry_id, "label": named, "key": first["moves"][0]["key"] if first["moves"] else ""}
            return self._go({"k": "revert", "before": what, "moves": moves, "who": who})

    # ---- what "changed" counts from --------------------------------------------------------------------------------
    def _rebase(self, name: str) -> None:
        self.base = {k: list(v) for k, v in self.cur.items()}
        self.base_name = name

    def _ensure_base(self) -> dict[str, list[Any]]:
        """The base, found on first use: the last checkpoint saved or gone back to, if its file is still there;
        else the mix as the desk first saw it."""
        if self.base is None:
            if not self.first:
                return {}  # nothing seen yet: asked again once the pager has reported
            last = next(
                (
                    e.get("name") or e.get("to")
                    for e in reversed(self.entries[: self.pos])
                    if e["k"] == "checkpoint" or (e["k"] == "revert" and e.get("to"))
                ),
                None,
            )
            base = {k: list(v) for k, v in self.first.items()}
            name = ""
            if last and self.has_checkpoint(last):
                with contextlib.suppress(OSError, ValueError, KeyError):
                    saved = self.load(last)
                    base.update({k: list(saved[k]) for k in base if k in saved})
                    name = last
            self.base, self.base_name = base, name
        return self.base

    def changed(self, now: dict[str, list[Any]] | None = None) -> list[str]:
        """The keys whose value (in `now`, default the desk's) differs from the base."""
        with self.lock:
            base = self._ensure_base()
            values = self.cur if now is None else now
            return sorted(
                k for k, v in values.items() if k in base and k not in self.quiet and not same(v[1], base[k][1])
            )

    # ---- checkpoints ----------------------------------------------------------------------------------------------
    def folder(self) -> Path:
        return self.checkpoints_dir or live_state.folder(self.set_name)

    def checkpoints(self) -> list[dict[str, Any]]:
        d = self.folder()
        out = []
        for p in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.exists() else []:
            out.append({"name": p.stem, "at": p.stat().st_mtime})
        return out

    def has_checkpoint(self, name: str) -> bool:
        return bool(NAME_RE.match(name)) and (self.folder() / f"{name}.json").exists()

    def free_name(self, name: str) -> str:
        """`name`, or `name 2`, `name 3`... when a checkpoint already has it: a new one never overwrites an old one."""
        check_name(name)
        if not self.has_checkpoint(name):
            return name
        n = 2
        while self.has_checkpoint(f"{name[:56]} {n}"):
            n += 1
        return f"{name[:56]} {n}"

    def load(self, name: str) -> dict[str, live_state.ShownRaw]:
        """A checkpoint's values for the desk's keys (all the keys it has)."""
        if not NAME_RE.match(name):
            raise ValueError(f"bad checkpoint name {name!r}")
        return live_state.flatten(live_state.load(self.folder() / f"{name}.json"))

    def checkpoint(
        self,
        name: str,
        full: live_state.State,
        main_saved: dict[str, Any] | None,
        who: protocol.Who = protocol.DEFAULT_WHO,
    ) -> dict[str, Any]:
        """Save `full` (a state just taken) as checkpoint `name`, with the desk's own values on top (they are what
        the history knows), the monitor tracks as the desk leaves them (muted, not soloed) and Main's desk devices
        as they are when nothing is monitored. Adds a checkpoint entry to the history."""
        check_name(name)
        with self.lock:
            for tname, body in full["tracks"].items():
                mix = body["mixer"]
                if tname.startswith("mon "):
                    mix["mute"], mix["solo"] = (
                        live_state.ShownRaw.of("True", True),
                        live_state.ShownRaw.of("False", False),
                    )
                if tname == "Main" and main_saved:
                    for d in body["devices"]:
                        if d["name"] in main_saved and "Device On" in d["params"]:
                            on = main_saved[d["name"]]
                            d["params"]["Device On"] = live_state.ShownRaw.of("On" if on else "Off", on)
            # hands' State does not list a checkpoint's "name" and "made_by"; its readers keep unknown keys
            marked: Any = {**full, "name": name, "made_by": "mixdesk"}
            live_state.save(marked, self.folder() / f"{name}.json", self.set_name)
            e = self._push({"k": "checkpoint", "name": name, "moves": [], "who": who}, keep_redo=True)
            self._save()
            self._rebase(name)
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

    def _preview(self, entry: dict[str, Any] | None, side: str) -> dict[str, Any] | None:
        """What undoing (`side` "from") or redoing ("to") `entry` does: its id and, per control, the key, the place
        it goes to (None when the desk does not know the control's range) and the value as Live showed it."""
        if entry is None:
            return None
        moves = [m for m in entry.get("moves", []) if m[side] is not None]
        return {
            "id": entry["id"],
            "count": len(moves),
            "values": [[m["key"], self.place(m["key"], m[side][1]), m[side][0]] for m in moves[:32]],
        }

    def view(self, last: int = 150) -> dict[str, Any]:
        with self.lock:
            start = max(0, len(self.entries) - last)
            undo = next((e for e in reversed(self.entries[: self.pos]) if e["k"] != "checkpoint"), None)
            redo = next((e for e in self.entries[self.pos :] if e["k"] != "checkpoint"), None)
            return {
                "t": "hist",
                "entries": self.entries[start:],
                "pos": self.pos - start,
                "can_undo": undo is not None,
                "can_redo": redo is not None,
                "undo": self._preview(undo, "from"),
                "redo": self._preview(redo, "to"),
                "checkpoints": self.checkpoints(),
            }
