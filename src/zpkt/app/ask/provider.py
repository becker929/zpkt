"""What an engine is to the service: something that runs one turn and reports events.

`Turn` is everything a run needs; `emit` takes one page event; `cancel` is set when the person presses Stop or the
failure budget stops the run, and the provider must end the turn soon after. The Ask service (service.py) owns the
sessions, the budget and the numbering of events: a provider only talks to its agent.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from zpkt.app.ask.engines import ToolServer
from zpkt.app.ask.events import Event

Emit = Callable[[Event], None]
# (what the agent wants to do, the choices) -> the chosen option's id, or None when it was cancelled
AskPermission = Callable[[dict[str, Any], list[dict[str, Any]]], str | None]


@dataclass
class Turn:
    session: dict[str, Any]  # the session's record: id, cwd, engines
    prompt: str  # the whole text for the agent: the person's words, notes, the hand-off
    mode: str
    model: str
    resume: bool
    system: str = ""
    extra_dirs: list[Path] = field(default_factory=list)
    tools: ToolServer | None = None
    engine_session: str = ""  # Claude's own session id when it is not the session's (after a compaction)
    mark_started: Callable[[str], None] = lambda engine_id: None  # the engine now has a conversation; its own id
    ask_permission: AskPermission = lambda tool, options: None


@dataclass(frozen=True)
class Outcome:
    code: int | None = 0
    signal: str | None = None
    error: str | None = None


class Provider(Protocol):
    engine: str

    def run(self, turn: Turn, emit: Emit, cancel: threading.Event) -> Outcome:
        """Run the turn to its end, emitting events. Returns when the agent is done or has been stopped."""
        ...

    def available(self) -> dict[str, Any]:
        """What the page shows about this engine (name, whether it can run)."""
        ...
