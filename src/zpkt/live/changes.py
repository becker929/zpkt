"""Changes: one value of the mix going from one shown value to another, and who moved it. The one interface's
history, undo and "what did the agent touch" all read this stream.

A Change names its value by state key (zpkt.live.inlive.keys) and holds ShownRaw pairs, as states do:

    {"n": 12, "at": "2026-11-24 16:40:02", "who": "agent", "key": "Kick bus/desk EQ/1 Gain A",
     "was": ["0.00 dB", 0.0], "now": ["-3.00 dB", -3.0], "group": "make the kick sit back"}

`between` makes the changes that turn one state into another. A Stream is the changes of one set, kept as one JSON
object per line in <sets_dir>/changes/<set>.jsonl: append-only, so a reader that remembers the last "n" it saw asks
only for what came after. A line this code cannot read is skipped and counted, never fatal.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, get_args

from zpkt.live import config
from zpkt.live import state as S

# Who moved it: Anthony (on a page or in Live), the MiniLab, an agent, the music bot's booth, the demo tools, the
# `zpkt` command line, or the app itself ("sys": a monitor switch, which is not a mix change). The pager
# reports you, minilab, agent and sys (zpkt.app.protocol); the app's command bus stamps all seven.
Who = Literal["you", "minilab", "agent", "booth", "demo", "cli", "sys"]
WHO: tuple[str, ...] = get_args(Who)


class Change(TypedDict):
    key: str
    was: S.ShownRaw | None  # None: the value did not exist before (a device was added)
    now: S.ShownRaw | None  # None: the value is gone
    who: Who
    at: str  # "YYYY-MM-DD HH:MM:SS"
    n: NotRequired[int]  # its place in a stream, from 1; set by Stream.append
    group: NotRequired[str]  # changes made together share it (one ask to an agent, one revert)


def stamp(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def change(
    key: str, was: list[Any] | None, now: list[Any] | None, who: Who, at: str | None = None, group: str | None = None
) -> Change:
    """One change; ValueError for a `who` that is not one of WHO."""
    if who not in WHO:
        raise ValueError(f"who is one of {', '.join(WHO)}, not {who!r}")
    c: Change = {
        "key": key,
        "was": None if was is None else S.ShownRaw(was),
        "now": None if now is None else S.ShownRaw(now),
        "who": who,
        "at": at or stamp(),
    }
    if group:
        c["group"] = group
    return c


def between(
    a: S.State, b: S.State, who: Who, at: str | None = None, group: str | None = None, ignore: tuple[str, ...] = ()
) -> list[Change]:
    """The changes that turn state `a` into `b`, in key order: one per value that differs (zpkt.live.state.diff has
    the rule, so a partial state is compared on its own keys alone)."""
    fa, fb = S.flatten(a), S.flatten(b)
    at = at or stamp()
    return [change(key, fa.get(key), fb.get(key), who, at, group) for key, _, _ in S.diff(a, b, ignore)]


def by_who(changes: list[Change]) -> dict[str, int]:
    """How many changes each mover made, for "the agent moved 57 controls"."""
    out: dict[str, int] = {}
    for c in changes:
        out[c["who"]] = out.get(c["who"], 0) + 1
    return out


def latest(changes: list[Change]) -> dict[str, Change]:
    """The last change of each key, in the order the keys were first touched."""
    out: dict[str, Change] = {}
    for c in changes:
        out[c["key"]] = c
    return out


def path_for(set_name: str) -> Path:
    return config.rig().sets_dir / "changes" / f"{set_name}.jsonl"


class Stream:
    """One set's changes on disk, oldest first."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.skipped = 0  # lines the last read could not parse

    def read(self, since: int = 0, who: Who | None = None) -> list[Change]:
        """The changes after number `since` (0: all of them), optionally only one mover's."""
        self.skipped = 0
        if not self.path.exists():
            return []
        out: list[Change] = []
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                c = json.loads(line)
                c["was"] = None if c["was"] is None else S.ShownRaw(c["was"])
                c["now"] = None if c["now"] is None else S.ShownRaw(c["now"])
                n, mover = int(c["n"]), c["who"]
                str(c["key"]), str(c["at"])
            except (ValueError, KeyError, TypeError):
                self.skipped += 1
                continue
            if n > since and (who is None or mover == who):
                out.append(c)
        return out

    def last(self) -> int:
        """The number of the newest change; 0 for an empty stream."""
        changes = self.read()
        return changes[-1]["n"] if changes else 0

    def append(self, changes: list[Change]) -> list[Change]:
        """Add changes to the end, numbering them on from the last; returns them with their "n"."""
        if not changes:
            return []
        n = self.last()
        numbered: list[Change] = []
        for c in changes:
            if c["who"] not in WHO:
                raise ValueError(f"who is one of {', '.join(WHO)}, not {c['who']!r}")
            n += 1
            numbered.append({**c, "n": n})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write("".join(json.dumps(c) + "\n" for c in numbered))
        return numbered
