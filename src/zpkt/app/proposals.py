"""Options an agent proposes: a named change with a reason, kept until you pick it.

A proposal is a record in a file, nothing more: it moves nothing in Live. The app's one store of Options
(zpkt.app.renders.Options) holds this file and lists each proposal as an Option (zpkt.app.options.from_proposal).
You pick it there with `options.pick`: its moves go on Now, stamped `you`, and it is "picked" from then on, which is
what lets the agent's own command carry `approval="option:<id>"` past the bus. lib/contracts/proposal.schema.json is
the file's shape.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypedDict, cast

from zpkt.live.changes import Who


class Move(TypedDict):
    target: str  # a state key
    to: str | float  # shown text or a raw value


class Option(TypedDict, total=False):
    id: str
    title: str
    why: str
    moves: list[Move]
    made_by: Who
    at: str
    session: str | None
    state: str  # "proposed", or "picked" once you picked it


MAX_TITLE, MAX_WHY, MAX_MOVES = 80, 1000, 24


def parse(data: Any, made_by: Who, session: str | None = None, now: str = "") -> Option:
    """A proposal from its fields; ValueError says what is wrong."""
    if not isinstance(data, dict):
        raise ValueError("an option is an object with a title, a reason and its moves")
    title = " ".join(str(data.get("title", "")).split())[:MAX_TITLE]
    why = str(data.get("why", "")).strip()[:MAX_WHY]
    if not title:
        raise ValueError("an option needs a title")
    if not why:
        raise ValueError("an option needs a reason: say in a sentence why it helps")
    raw = data.get("moves", [])
    if not isinstance(raw, list) or len(raw) > MAX_MOVES:
        raise ValueError(f"'moves' is a list of at most {MAX_MOVES} {{target, to}} objects")
    moves: list[Move] = []
    for m in raw:
        if (
            not isinstance(m, dict)
            or not isinstance(m.get("target"), str)
            or not isinstance(m.get("to"), str | int | float)
        ):
            raise ValueError("each move is {target: a state key, to: a value}")
        moves.append({"target": m["target"], "to": m["to"]})
    return {
        "id": uuid.uuid4().hex[:8],
        "title": title,
        "why": why,
        "moves": moves,
        "made_by": made_by,
        "at": now,
        "session": session,
        "state": "proposed",
    }


class OptionStore:
    """options.json in `folder`: the proposals, newest last. One lock; atomic writes."""

    def __init__(self, folder: Path, clock: Callable[[], float] = time.time) -> None:
        self.file = Path(folder) / "options.json"
        self.clock = clock
        self.lock = threading.Lock()

    def all(self) -> list[Option]:
        try:
            data = json.loads(self.file.read_text())
        except (OSError, ValueError):
            return []
        return cast("list[Option]", [o for o in data if isinstance(o, dict)] if isinstance(data, list) else [])

    def propose(self, data: Any, made_by: Who, session: str | None = None) -> Option:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock()))
        option = parse(data, made_by, session, stamp)
        with self.lock:
            self._write([*self.all(), option])
        return option

    def _write(self, options: list[Option]) -> None:
        """Atomic: the caller holds the lock."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_name(self.file.name + ".tmp")
        tmp.write_text(json.dumps(options, indent=1))
        tmp.replace(self.file)

    def pick(self, option_id: str) -> Option:
        """You picked this proposal: it is "picked" from now on, which is what lets an agent's move name it."""
        with self.lock:
            options = self.all()
            for option in options:
                if option.get("id") == option_id:
                    option["state"] = "picked"
                    self._write(options)
                    return option
        raise ValueError(f"there is no proposal {option_id!r}; the proposals are in options.json")

    def is_picked(self, option_id: str) -> bool:
        return any(o.get("id") == option_id and o.get("state") == "picked" for o in self.all())
