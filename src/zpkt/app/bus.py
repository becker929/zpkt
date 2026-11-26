"""The command bus: every change to Live, whoever asks, goes through here.

Adapters (the web page, the MiniLab, an agent, the API) turn what they hear into a Command: a kind, who is asking
(you, minilab, agent, booth, demo, cli, sys) and arguments. The bus finds the handler in its dispatch table and runs
these checks first:

- who: it must be one of zpkt.live.changes.WHO.
- the agent rule: an agent may make pages and may read; a change to Live from an agent needs your word
  (`approval`), except by a command the table lets an agent ask for on its own (`Spec.agent_may`: `live.change`
  alone, zpkt.app.effects says why). Your word reaches the bus one way from an agent: its `propose_live` tool
  shows you the batch in the chat, and after your tap the Ask gate sends `live.propose` with it
  (zpkt.app.propose). An agent's changes always belong to a group, and the first change of a group makes an
  automatic version first, so one undo takes the whole group back.
- the wrong-set guard: every move is held to a set, and nothing is sent when Live has another open. The desk's moves
  are for the page's set. A job (zpkt.app.jobs) is for the set its caller names (`expect_set`), or else for the set
  the app last saw open. Only opening a set is let through.
- the lock: Live takes one job at a time. A command that cannot get it in time is refused with a reason.

The bus holds no state about Live or the mix; the handlers and their services (zpkt.app.desk) do. It keeps a short log
of what was asked and what came of it. Handlers return a reply: (HTTP-style status, JSON object).
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import threading
import time
import traceback
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
KEEP_LOG = 200
VERSIONED_KEEP = 500  # groups remembered as already checkpointed


log = logging.getLogger(__name__)


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
    approval: str | None = None  # "user": you said so
    group: str | None = None  # changes made together; an agent's changes always have one


@dataclass(frozen=True)
class Spec:
    """A command kind: its handler and what it does (which decides the checks)."""

    handler: Callable[[Command], Reply]
    effect: Effect = "read"
    touches_live: bool = False  # it calls Live, so it takes the lock
    guarded: bool = True  # a move is held by the wrong-set guard; only opening a set turns this off
    own_set: bool = False  # a job: held to the set its caller names (`expect_set`), or the one the app last saw open
    callers: tuple[str, ...] | None = None  # who may ask for it; None is anyone (the web is "you", the API is not)
    for_set: str | None = None  # a move for another set than the page's (the Song builds the mix set): that one
    agent_may: bool = False  # an agent may ask for this move on its own (zpkt.app.effects.AGENT_MAY: the decision)
    checks_first: bool = False  # the handler checks the whole ask, then saves the version itself (Bus.version)


def approved(cmd: Command) -> bool:
    """True when the command carries your word. Nothing else approves: the API never takes that word from an agent
    (zpkt.app.adapters.api), so an agent that reaches the app from outside cannot move Live."""
    return cmd.approval == APPROVED_BY_USER


def check_who(cmd: Command) -> None:
    if cmd.who not in WHO:
        raise BadRequest(f"who is one of {', '.join(WHO)}, not {cmd.who!r}")


def check_caller(cmd: Command, spec: Spec) -> None:
    """Some commands are for the API's callers only: the web page may not run code in Live."""
    if spec.callers is not None and cmd.who not in spec.callers:
        raise Refused(f"{cmd.kind!r} is not open to {cmd.who!r}; it is for {', '.join(spec.callers)}")


def check_agent(cmd: Command, spec: Spec) -> None:
    """The agent rule: an agent's move needs your word, unless the command is one an agent may ask for itself."""
    if cmd.who == "agent" and spec.effect == "move" and not spec.agent_may and not approved(cmd):
        raise Refused(
            f"An agent cannot change Live with {cmd.kind!r} on its own. To set values, or add, bypass or reorder "
            f"devices, use the app's change_live tool (the command live.change). To remove a device, make a track, "
            f"or change routing or clips with code, use the app's propose_live tool: the user sees the steps in "
            f"the chat and taps Do it, and only then does the app run them (live.propose). To let the user hear "
            f"an alternative, make a page with the change as a compare state (page.draft) and give them its link."
        )


EXPECT_SET = "expect_set"  # the argument in which a job's caller names the set the call is for


class SetGuard:
    """The wrong-set guard: Live must have open the set a move is for. A set that Live does not name (an unsaved
    one) passes.

    The desk's moves are for the page's set (`check`); that answer is kept for `ttl_s` seconds, since asking Live
    costs a call and a knob sends many. A job is for the set its caller names, or for `believed`, the set the app
    last saw open (`check_job`): the page's set at the start, then whatever set the app opened or a caller named
    and Live had."""

    def __init__(
        self,
        page_set: str,
        open_set: Callable[[], str],
        ttl_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.page_set, self.open_set, self.ttl_s, self.clock = page_set, open_set, ttl_s, clock
        self.believed = page_set
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

    def believe(self, name: str) -> None:
        """The app saw `name` open (it opened it, or a caller named it and Live had it)."""
        if name:
            with self._lock:
                self.believed = name

    def check_job(self, named: str | None) -> None:
        """Refuse a job when Live has another set open than the one its caller names, or, for a caller that names
        none, than the one the app last saw open. Live is asked afresh: a job may follow a change of set at once."""
        have = self.open_set()
        if not have:
            return
        if named is not None:
            if have != named.removesuffix(".als"):
                raise Refused(f"Live has {have} open; this call is for {named}. Open that set first.", 409)
            self.believe(have)
        elif have != self.believed:
            raise Refused(
                f"Live has {have} open, but the app last saw {self.believed} open, and this call names no set. "
                f"If {have} is the set you mean, say so (`zpkt live open {have}`, or 'expect_set' in the call's "
                f"args); otherwise open {self.believed} first.",
                409,
            )

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
        self._versioned: dict[str, None] = {}  # recent groups, oldest first
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
            if spec.effect == "move" and spec.guarded and not spec.own_set and self.guard is not None:
                self.guard.check(spec.for_set)
            with self._held(spec):
                self._check_job_set(cmd, spec)
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
        except Exception as exc:  # a handler's own bug: the caller still gets an answer, and the log has the type
            where = traceback.extract_tb(exc.__traceback__)[-1]  # the place, never the message: it may hold arguments
            log.error(
                "app: command %r failed with %s at %s:%s", cmd.kind, type(exc).__name__, where.filename, where.lineno
            )
            return 500, {"error": f"{cmd.kind} failed inside the app ({type(exc).__name__}); see the app's log"}

    def _check_job_set(self, cmd: Command, spec: Spec) -> None:
        """The wrong-set guard for a job, asked while Live is held. A read that names no set looks at whatever is
        open; a move never does."""
        if self.guard is None or not (spec.own_set and spec.guarded):
            return
        named = cmd.args.get(EXPECT_SET)
        if named is not None and not isinstance(named, str):
            raise BadRequest(f"{EXPECT_SET!r} must be text: the name of the set this call is for")
        if named is not None or spec.effect == "move":
            self.guard.check_job(named)

    def _held(self, spec: Spec) -> AbstractContextManager[Any]:
        if spec.touches_live and self._lock is not None:
            return self._lock()
        return contextlib.nullcontext()

    def _grouped(self, cmd: Command, spec: Spec) -> Command:
        """An agent's change always has a group, and the group's first change saves a version first. A command that
        checks first gets a group whoever asks, and saves the version itself once its checks pass (`version`), so
        an ask that is refused leaves nothing behind."""
        if spec.checks_first and spec.effect == "move":
            return dataclasses.replace(cmd, group=cmd.group or f"{cmd.who}-{cmd.kind}-{int(self.clock() * 1000)}")
        if cmd.who != "agent" or spec.effect != "move":
            return cmd
        group = cmd.group or f"agent-{cmd.kind}-{int(self.clock())}"
        self.version(group)
        return dataclasses.replace(cmd, group=group)

    def version(self, group: str) -> None:
        """Save the automatic version before a group's first change; a group that has one is left alone."""
        with self._mutex:
            first = group not in self._versioned
        if first and self.version_before is not None:
            self.version_before(group)  # marked only after it worked: a failed checkpoint is tried again
        with self._mutex:
            self._versioned[group] = None
            while len(self._versioned) > VERSIONED_KEEP:
                del self._versioned[next(iter(self._versioned))]
