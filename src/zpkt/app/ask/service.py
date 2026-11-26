"""The Ask service: sessions, engines, the failure budget, notes and the permission desk, tied together.

`send` starts one turn of one engine in a session and returns at once; the run goes on in its own thread and every
event is stored and streamed (so it survives the page closing). A session may change engine between turns: the
other engine gets the turns it missed. Each workspace has one main conversation (`main`) that goes on for good: when
it is past an engine's budget the run first compacts it (compaction.py), then starts the engine on the summary and the
last turns. The service holds no Live connection. Agents get the app's tools through the
MCP server (mcp.py); `tools.ToolGate` runs their calls on the bus as `agent`.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zpkt.app.ask import compaction
from zpkt.app.ask import notes as notes_module
from zpkt.app.ask.engines import DEFAULT_MODE, MODEL_NAME, MODES, ToolServer
from zpkt.app.ask.events import ENGINE_NAME, ENGINES, Budget, Event, handoff_context
from zpkt.app.ask.permissions import Permissions
from zpkt.app.ask.provider import Outcome, Provider, Turn
from zpkt.app.ask.store import Refused, SessionStore
from zpkt.app.ask.tools import ToolGate
from zpkt.app.ask.workspaces import Workspaces

MAX_LIVE = 4
MAX_TITLE = 80
COMPACT_TIMEOUT_S = 180.0  # a summary that takes longer is given up; the turn goes on with the last turns only


@dataclass
class Run:
    cancel: threading.Event
    thread: threading.Thread | None = None


class Ask:
    def __init__(
        self,
        data_dir: Path,
        providers: dict[str, Provider],
        gate: ToolGate,
        guide: str = "",
        attach_dir: Path | None = None,
        write_notes: notes_module.Writer | None = None,
        notify: Callable[[str, str], None] | None = None,
        max_live: int = MAX_LIVE,
        tool_python: str = sys.executable,
        home: Path | None = None,
        budgets: dict[str, int] | None = None,
    ) -> None:
        self.dir = Path(data_dir)
        self.budgets = compaction.budgets(os.environ, budgets)  # tokens per engine before a compaction
        self.compact_timeout = COMPACT_TIMEOUT_S
        self.store = SessionStore(self.dir)
        self.providers, self.gate, self.guide = providers, gate, guide
        self.attach_dir = attach_dir or self.dir / "attachments"
        self.workspaces = Workspaces(self.dir, home)
        self.permissions = Permissions(self.store.emit, notify)
        self.notes = notes_module.Notes(self.store.emit, self.store.save, write_notes)
        self.max_live, self.tool_python = max_live, tool_python
        self.app_url = ""  # where the agents' tool server reaches this app; the routes set it from each request
        self.runs: dict[str, Run] = {}
        self.threads: list[threading.Thread] = []
        self.lock = threading.Lock()
        self.store.taps.append(self._tap)

    # ---- what the page asks for ------------------------------------------------------------------------------
    def engines(self) -> list[dict[str, Any]]:
        return [
            {**self.providers[e].available(), "id": e, "name": ENGINE_NAME[e]} for e in ENGINES if e in self.providers
        ]

    def is_live(self, sid: str) -> bool:
        return sid in self.runs

    def sessions(self) -> list[dict[str, Any]]:
        return [{**s, "asking": self.permissions.asking(s["id"])} for s in self.store.all_sessions(self.is_live)]

    def main(self, workspace: str = "") -> dict[str, Any]:
        """The one conversation of a workspace (the first workspace when none is named), made on first use, empty.
        Older sessions there are the archive."""
        w = self.workspaces.get(workspace) if workspace else next(iter(self.workspaces.all()), None)
        if w is None:
            raise Refused("Unknown workspace")
        self.workspaces.ensure(w)
        s = self.store.main(w["id"], w["path"])
        return {**s, "running": self.is_live(s["id"]), "asking": self.permissions.asking(s["id"])}

    def archive(self, workspace: str = "") -> list[dict[str, Any]]:
        w = self.workspaces.get(workspace) if workspace else next(iter(self.workspaces.all()), None)
        if w is None:
            raise Refused("Unknown workspace")
        return self.store.archive(w["id"], w["path"], self.is_live)

    def stop(self, sid: str) -> bool:
        run = self.runs.get(sid)
        if run is None:
            return False
        run.cancel.set()
        return True

    def remove(self, sid: str) -> None:
        self.store.remove(sid, running=self.is_live(sid))

    # ---- sessions and turns ----------------------------------------------------------------------------------
    def create(self, workspace: str, prompt: str, **turn: Any) -> dict[str, Any]:
        """A new session in a workspace, with its first turn."""
        w = self.workspaces.get(workspace)
        if w is None:
            raise Refused("Unknown workspace")
        if not prompt.strip():
            raise Refused("Empty prompt")
        self.workspaces.ensure(w)
        first = next((ln for ln in prompt.split("\n") if ln.strip()), "Session")
        title = (str(turn.pop("title", "") or "").strip() or first.strip())[:MAX_TITLE]
        s = self.store.create(title, w["id"], w["path"])
        try:
            self.send(s, prompt, **turn)
        except Exception:
            self.store.discard(s["id"])  # its first turn was refused: no empty session in the list
            raise
        return s

    def send(
        self,
        s: dict[str, Any],
        prompt: str,
        mode: str = DEFAULT_MODE,
        engine: str = "claude",
        model: str = "",
        extra: str = "",
        attachments: list[str] | None = None,
    ) -> None:
        """Start a turn of `engine` in the session `s`. Raises Refused when it cannot start."""
        if not prompt.strip():
            raise Refused("Empty prompt")
        if mode not in MODES:
            raise Refused("Invalid mode")
        if mode == "plan":  # an older page's default: it could not make a page, so it is the new default now
            mode = DEFAULT_MODE
        if engine not in ENGINES or engine not in self.providers:
            raise Refused("Invalid engine")
        if model and not MODEL_NAME.match(model):
            raise Refused("Invalid model")
        with self.lock:
            if s["id"] in self.runs:
                raise Refused("This session is already running", 409)
            if len(self.runs) >= self.max_live:
                raise Refused(f"At most {self.max_live} sessions can run at once", 429)
            run = self.runs[s["id"]] = Run(threading.Event())
        sid = s["id"]
        try:
            plan = compaction.plan(
                self.store.replay(sid), self.budgets.get(engine, 0), project=str(s.get("project") or "")
            )
            context = turn = None
            if plan is None:
                context = self.notes.context(s, prompt)
                turn = self._turn(s, prompt, mode, engine, model, extra, context.text if context else "")
        except Exception:
            self.runs.pop(sid, None)
            raise
        asked = self.store.emit(
            sid,
            {"type": "prompt", "text": prompt, "mode": mode, "model": model or "auto", "engine": engine, "auto": False}
            | ({"attachments": attachments} if attachments else {})
            | ({"extra": True} if extra else {}),
        )
        s["engine"] = engine
        self.store.touch(s)
        self.notes.seen(s, context)

        def make() -> Turn | None:
            """The turn to run. Past the budget, the conversation is compacted first, here in the run's thread."""
            if turn is not None or plan is None:
                return turn
            if not self._compact(s, engine, model, plan, run):
                return None  # stopped while the summary was being written
            notes = self.notes.context(s, prompt)
            made = self._turn(s, prompt, mode, engine, model, extra, notes.text if notes else "", upto=asked["seq"])
            self.notes.seen(s, notes)
            return made

        run.thread = threading.Thread(target=self._run, args=(s, make, engine, run), daemon=True, name=f"ask-{sid[:8]}")
        self.threads.append(run.thread)
        run.thread.start()

    def _compact(self, s: dict[str, Any], engine: str, model: str, plan: compaction.Plan, run: Run) -> bool:
        """Have the engine write the summary of the older turns, then start every engine afresh. The transcript
        gains a `compacted` event. A summary that fails is recorded and the turn goes on with the last turns only.
        False when the person stopped it."""
        sid = s["id"]
        self.store.emit(sid, {"type": "compacting", "engine": engine, "turns": plan.turns, "tokens": plan.tokens})
        said: list[str] = []
        errors: list[str] = []

        def collect(ev: Event) -> None:
            if ev.get("parent"):
                return
            if ev.get("type") == "message" and ev.get("role") != "user":
                said.append(str(ev.get("content") or ""))
            elif ev.get("type") == "error":
                errors.append(str(ev.get("message") or ""))

        stop, done = threading.Event(), threading.Event()
        ends = time.monotonic() + self.compact_timeout

        def watch() -> None:
            while not done.wait(0.05):
                if run.cancel.is_set() or time.monotonic() > ends:
                    stop.set()
                    return

        threading.Thread(target=watch, daemon=True).start()
        fresh = {**s, "engines": {}, "started": False}  # the summary is written in a session of its own
        ask = Turn(fresh, compaction.summary_prompt(plan), "plan", model, False, engine_session=str(uuid.uuid4()))
        try:
            outcome = self.providers[engine].run(ask, collect, stop)
        except Exception as exc:
            outcome = Outcome(None, None, f"{type(exc).__name__}: {exc}")
        finally:
            done.set()
        if run.cancel.is_set():
            return False
        summary = compaction.clean("".join(said))
        error = ""
        if outcome.error or outcome.code or outcome.signal or not summary:
            error = (
                outcome.error
                or next(iter(errors), "")
                or ("the summary took too long" if stop.is_set() else "the engine wrote no summary")
            )
            summary = plan.earlier
        self.store.emit(sid, compaction.compacted(plan, engine, summary, error))
        s["engines"] = {e: {"started": False} for e in ENGINES}
        s["started"] = False
        s.pop("notesSeen", None)  # the engines forget the notes too
        self.store.save()
        return True

    def _turn(
        self,
        s: dict[str, Any],
        prompt: str,
        mode: str,
        engine: str,
        model: str,
        extra: str,
        context: str,
        upto: int | None = None,
    ) -> Turn:
        """`upto` is the seq of this turn's prompt when it is already in the transcript (after a compaction)."""
        engines = self.store.engine_state(s)
        resume = bool(engines.get(engine, {}).get("started"))
        text = prompt + (f"\n\n{context}" if context else "") + (f"\n\n{extra}" if extra else "")
        events = self.store.replay(s["id"])
        compacted = compaction.base(events) is not None
        if resume:
            # Back to an engine after the other one had turns: it gets those turns (it remembers its own).
            last = max(
                (i for i, e in enumerate(events) if e.get("type") == "prompt" and e.get("engine") == engine), default=-1
            )
            after = events[last + 1 :]
            mine = next((i for i, e in enumerate(after) if e.get("type") == "prompt"), -1)
            if mine >= 0 and any(
                e.get("type") == "prompt" and e.get("engine") in ENGINES and e.get("engine") != engine for e in after
            ):
                text = (
                    handoff_context(
                        [e for e in after[mine:] if not (e.get("type") == "prompt" and e.get("engine") == "instant")],
                        since=True,
                    )
                    + text
                )
        else:
            if compacted:
                text = compaction.preamble(events, upto) + text  # the summary and the turns kept word for word
                if engine == "claude":  # a new Claude session: the old one holds the whole conversation
                    engines[engine] = {**engines.get(engine, {}), "sid": str(uuid.uuid4())}
                    self.store.save()
            elif any(engines.get(o, {}).get("started") for o in ENGINES if o != engine):
                text = handoff_context(events) + text  # joining a conversation the other engine started
            if engine == "gemini" and self.guide:
                text = f"{self.guide}\n\n---\n\n{text}"  # Gemini has no system-prompt flag: it gets the guide once
        return Turn(
            session=s,
            prompt=text,
            mode=mode,
            model=model,
            resume=resume,
            system=self.guide if engine == "claude" else "",
            extra_dirs=[self.attach_dir],
            tools=self._tool_server(s["id"]),
            engine_session=str(engines.get(engine, {}).get("sid") or "") if engine == "claude" else "",
        )

    def _tool_server(self, sid: str) -> ToolServer | None:
        if not self.app_url:
            return None
        env = {"ZPKT_DESK_URL": self.app_url, "ZPKT_APP_SESSION": sid, "ZPKT_APP_TOKEN": self.gate.token(sid)}
        return ToolServer(self.tool_python, ("-m", "zpkt.app.ask.mcp"), env)

    def _run(self, s: dict[str, Any], make: Callable[[], Turn | None], engine: str, run: Run) -> None:
        sid = s["id"]
        budget = Budget()

        def emit(ev: Event) -> None:
            ev = {k: v for k, v in ev.items() if k not in ("seq", "t")}
            self.store.emit(sid, ev)
            why = budget.watch(ev)
            if why and not run.cancel.is_set():
                self.store.emit(sid, {"type": "error", "message": why})
                run.cancel.set()

        def mark_started(engine_id: str) -> None:
            state = self.store.engine_state(s)
            if not state.get(engine, {}).get("started") or (engine_id and state[engine].get("acp") != engine_id):
                state[engine] = {**state.get(engine, {}), "started": True, **({"acp": engine_id} if engine_id else {})}
                if engine == "gemini":
                    s["started"] = True
                self.store.save()

        outcome = Outcome(None, None, "the engine did not run")
        try:
            turn = make()
            if turn is None:
                outcome = Outcome(None, "SIGTERM")
            else:
                turn.mark_started = mark_started
                turn.ask_permission = lambda tool, options: self.permissions.ask(sid, tool, options, run.cancel)
                outcome = self.providers[engine].run(turn, emit, run.cancel)
        except Exception as exc:  # a provider bug must end the run cleanly, not leave the session "running" forever
            outcome = Outcome(None, None, f"{type(exc).__name__}: {exc}")
        finally:
            self.permissions.cancel_session(sid)
            self.runs.pop(sid, None)
            self.store.touch(s)
            signal = outcome.signal or ("SIGTERM" if run.cancel.is_set() and outcome.code else None)
            self.store.emit(
                sid,
                {"type": "run_end", "code": outcome.code, "signal": signal, "error": outcome.error, "engine": engine},
            )

    def _tap(self, sid: str, e: Event) -> None:
        turn = self.notes.on_event(sid, e)
        if turn is not None and self.notes.write is not None:
            s = next((x for x in self.store.index if x["id"] == sid), None)
            if s is not None:
                threading.Thread(target=self.notes.record, args=(s, turn), daemon=True).start()

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """For tests and shutdown: wait until every run has ended and said so (its run_end is stored)."""
        for t in list(self.threads):
            t.join(timeout)
        self.threads = [t for t in self.threads if t.is_alive()]
        return not self.runs and not self.threads
