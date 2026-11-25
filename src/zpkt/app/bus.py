"""The command bus: every change to Live, whoever asks, goes through here.

Adapters (the web page, the MiniLab, an agent, the API) turn what they hear into a Command: a kind, who is asking
(you, minilab, agent, booth, demo, cli, sys) and arguments. The bus finds the handler in its dispatch table and runs
these checks first:

- who: it must be one of zpkt.live.changes.WHO.
- the agent rule: an agent may make pages and propose Options and may read; a change to Live from an agent needs an
  Option pick or your word (`approval`). An agent's changes always belong to a group, and the first change of a group
  makes an automatic version first, so one undo takes the whole group back.
- the wrong-set guard: Live must have open the set the page is for. Nothing is sent otherwise.
- the lock: Live takes one job at a time. A command that cannot get it in time is refused with a reason.

The bus holds no state about Live or the mix; the handlers and their services (zpkt.app.desk) do. It keeps a short log
of what was asked and what came of it. Handlers return a reply: (HTTP-style status, JSON object).
"""

from __future__ import annotations

import contextlib
import dataclasses
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Literal

from zpkt.app.connections import LiveBusy
from zpkt.live.changes import WHO, Who
from zpkt.live.transport import LiveError

Reply = tuple[int, dict[str, Any]]
Effect = Literal[
    "read", "make", "move"
]  # what a command does: nothing to Live's mix, makes pages and files, moves Live
OK: Reply = (200, {"ok": True})

APPROVED_BY_USER = "user"
OPTION_PREFIX = "option:"
KEEP_LOG = 200


class BadRequest(ValueError):
    """A request the handler cannot use: the caller gets 400 and this message."""


class Refused(Exception):
    """A check said no. `code` is the HTTP-style status; the message says why and what to do."""

    def __init__(self, message: str, code: int = 403) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Command:
    """One thing asked of the app."""

    kind: str  # "mix.set", "history.undo", ...
    who: Who = "you"
    args: Mapping[str, Any] = field(default_factory=dict)
    approval: str | None = None  # "user" (you said so) or "option:<id>" (an Option was picked)
    group: str | None = None  # changes made together; an agent's changes always have one


@dataclass(frozen=True)
class Spec:
    """A command kind: its handler and what it does (which decides the checks)."""

    handler: Callable[[Command], Reply]
    effect: Effect = "read"
    touches_live: bool = False  # it calls Live, so it takes the lock
    guarded: bool = True  # a move is held by the wrong-set guard; a job that names its own set turns this off
    callers: tuple[str, ...] | None = None  # who may ask for it; None is anyone (the web is "you", the API is not)
    for_set: str | None = None  # a move for another set than the page's (the Song builds the mix set): that one


def approved(cmd: Command) -> bool:
    """True when the command carries your word or an Option pick."""
    return cmd.approval == APPROVED_BY_USER or bool(cmd.approval and cmd.approval.startswith(OPTION_PREFIX))


def check_who(cmd: Command) -> None:
    if cmd.who not in WHO:
        raise BadRequest(f"who is one of {', '.join(WHO)}, not {cmd.who!r}")


def check_caller(cmd: Command, spec: Spec) -> None:
    """Some commands are for the API's callers only: the web page may not run code in Live."""
    if spec.callers is not None and cmd.who not in spec.callers:
        raise Refused(f"{cmd.kind!r} is not open to {cmd.who!r}; it is for {', '.join(spec.callers)}")


def check_agent(cmd: Command, spec: Spec) -> None:
    """The agent rule."""
    if cmd.who == "agent" and spec.effect == "move" and not approved(cmd):
        raise Refused(
            f"An agent cannot change Live with {cmd.kind!r} on its own. Propose it as an Option, or ask the user "
            f"to approve it."
        )


class SetGuard:
    """The wrong-set guard: Live must have open the set this app is for. The answer is kept for `ttl_s` seconds,
    since asking Live costs a call; a set that Live does not name (an unsaved one) passes."""

    def __init__(
        self,
        page_set: str,
        open_set: Callable[[], str],
        ttl_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.page_set, self.open_set, self.ttl_s, self.clock = page_set, open_set, ttl_s, clock
        self._seen: tuple[float, str] | None = None
        self._forgot = 0  # counts forget() calls, so an answer asked for before one is not kept after it
        self._lock = threading.Lock()

    def forget(self) -> None:
        with self._lock:
            self._seen = None
            self._forgot += 1

    def check(self, for_set: str | None = None) -> None:
        """Refuse when Live has another set open than the page's, or than `for_set` for a move that names its own."""
        want = for_set or self.page_set
        name = self._name()
        if name and name != want:
            raise Refused(f"Live has {name} open; this page is for {want}. Open that set first.", 409)

    def _name(self) -> str:
        """The open set's name, from the kept answer or from Live. Live is asked with no lock of ours held: a job
        that holds Live (opening a set) calls `forget`, and would wait for that lock for ever."""
        with self._lock:
            seen, forgot = self._seen, self._forgot
        if seen is not None and self.clock() - seen[0] < self.ttl_s:
            return seen[1]
        name = self.open_set()
        with self._lock:
            if self._forgot == forgot:
                self._seen = (self.clock(), name)
        return name


class Bus:
    """The dispatch table and the checks. One per app."""

    def __init__(
        self,
        guard: SetGuard | None = None,
        lock: Callable[[], AbstractContextManager[Any]] | None = None,
        version_before: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """`guard` is the wrong-set guard (None: no check); `lock()` gives the context that holds Live for a command;
        `version_before(group)` saves an automatic version before an agent's first change of a group."""
        self.table: dict[str, Spec] = {}
        self.guard, self._lock, self.version_before, self.clock = guard, lock, version_before, clock
        self.log: deque[dict[str, Any]] = deque(maxlen=KEEP_LOG)
        self._versioned: set[str] = set()
        self._mutex = threading.Lock()

    def register(self, kind: str, spec: Spec) -> None:
        if kind in self.table:
            raise ValueError(f"the command {kind!r} is already registered")
        self.table[kind] = spec

    def kinds(self, who: str | None = None) -> list[str]:
        """The command kinds, or those `who` may ask for."""
        return sorted(k for k, s in self.table.items() if who is None or s.callers is None or who in s.callers)

    def submit(self, cmd: Command) -> Reply:
        """Check the command, run its handler, log it. Never raises for a refused or failed command: it answers."""
        reply = self._run(cmd)
        with self._mutex:
            self.log.append(
                {"at": self.clock(), "kind": cmd.kind, "who": cmd.who, "status": reply[0], "group": cmd.group}
            )
        return reply

    def _run(self, cmd: Command) -> Reply:
        spec = self.table.get(cmd.kind)
        if spec is None:
            return 404, {"error": f"no command {cmd.kind!r}; the commands are {', '.join(self.kinds(cmd.who))}"}
        try:
            check_who(cmd)
            check_caller(cmd, spec)
            check_agent(cmd, spec)
            if spec.effect == "move" and spec.guarded and self.guard is not None:
                self.guard.check(spec.for_set)
            with self._held(spec):
                cmd = self._grouped(cmd, spec)
                return spec.handler(cmd)
        except BadRequest as exc:
            return 400, {"error": str(exc)}
        except Refused as exc:
            return exc.code, {"error": str(exc)}
        except LiveBusy as exc:
            return 503, {"error": str(exc)}
        except (LiveError, OSError) as exc:
            return 503, {"error": str(exc)}

    def _held(self, spec: Spec) -> AbstractContextManager[Any]:
        if spec.touches_live and self._lock is not None:
            return self._lock()
        return contextlib.nullcontext()

    def _grouped(self, cmd: Command, spec: Spec) -> Command:
        """An agent's change always has a group, and the group's first change saves a version first."""
        if cmd.who != "agent" or spec.effect != "move":
            return cmd
        group = cmd.group or f"agent-{cmd.kind}-{int(self.clock())}"
        with self._mutex:
            first = group not in self._versioned
            self._versioned.add(group)
        if first and self.version_before is not None:
            self.version_before(group)
        return dataclasses.replace(cmd, group=group)
