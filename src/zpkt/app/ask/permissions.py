"""Permission prompts: an agent in `ask` mode waits here for a yes from the page.

`ask` puts a `permission` event in the session (so every device shows it), then blocks until `answer` is called with
one of the offered options, or the run is cancelled, or `timeout_s` passes. The answer is recorded as a
`permission_answer` event. An optional `notify` is told when a question waits (the phone).

`put` is the same wait and also returns the question's id. The tool gate uses it for a batch that waits for a tap
(`propose_live`, tools.py): its `tool` is the card ({"kind": "propose_live", "title", "steps"}), it waits a shorter
time of its own, and the id lets the gate say afterwards what came of it (a `proposal` event for the same card).
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from zpkt.app.ask.events import Event

Emit = Callable[[str, Event], object]  # (session id, event)
WAIT_S = 1800.0


@dataclass
class Waiting:
    session: str
    options: set[str]
    done: threading.Event = field(default_factory=threading.Event)
    choice: str | None = None


class Permissions:
    def __init__(self, emit: Emit, notify: Callable[[str, str], None] | None = None, timeout_s: float = WAIT_S) -> None:
        self.emit, self.notify, self.timeout_s = emit, notify, timeout_s
        self.waiting: dict[str, Waiting] = {}
        self.lock = threading.Lock()

    def ask(
        self, session: str, tool: dict[str, Any], options: list[dict[str, Any]], cancel: threading.Event
    ) -> str | None:
        return self.put(session, tool, options, cancel)[1]

    def put(
        self,
        session: str,
        tool: dict[str, Any],
        options: list[dict[str, Any]],
        cancel: threading.Event,
        timeout_s: float | None = None,
    ) -> tuple[str, str | None]:
        """Ask, and wait: (the question's id, the option chosen or None). `timeout_s` is this question's own wait
        (default: the desk's)."""
        pid = secrets.token_hex(6)
        w = Waiting(session, {str(o["id"]) for o in options})
        with self.lock:
            self.waiting[pid] = w
        self.emit(session, {"type": "permission", "id": pid, "tool": tool, "options": options})
        if self.notify is not None:
            self.notify(str(tool.get("title") or "a tool"), session)
        ends = time.monotonic() + (self.timeout_s if timeout_s is None else timeout_s)
        while time.monotonic() < ends and not w.done.wait(0.05) and not cancel.is_set():
            pass
        self._resolve(pid, None)  # cancelled or timed out; a no-op when it was already answered
        return pid, w.choice

    def _resolve(self, pid: str, choice: str | None) -> bool:
        """End a question once: record the answer in the session, then wake the agent."""
        with self.lock:
            w = self.waiting.pop(pid, None)
        if w is None:
            return False
        w.choice = choice
        self.emit(w.session, {"type": "permission_answer", "id": pid, "answered": choice or "cancelled"})
        w.done.set()
        return True

    def answer(self, session: str, pid: str, option: str | None) -> bool:
        """True when a question was waiting. `option` must be one offered; None cancels."""
        with self.lock:
            w = self.waiting.get(pid)
        if w is None or w.session != session:
            return False
        if option is not None and option not in w.options:
            raise ValueError("that is not one of the offered options")
        return self._resolve(pid, option)

    def cancel_session(self, session: str) -> None:
        """A run ended: every question it still had waiting is cancelled and says so."""
        with self.lock:
            ids = [pid for pid, w in self.waiting.items() if w.session == session]
        for pid in ids:
            self._resolve(pid, None)

    def asking(self, session: str) -> bool:
        with self.lock:
            return any(w.session == session for w in self.waiting.values())
