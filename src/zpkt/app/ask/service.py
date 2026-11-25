"""The Ask service: sessions, engines, the failure budget, notes and the permission desk, tied together.

`send` starts one turn of one engine in a session and returns at once; the run goes on in its own thread and every
event is stored and streamed (so it survives the page closing). A session may change engine between turns: the
other engine gets the turns it missed. The service holds no Live connection. Agents get the app's tools through the
MCP server (mcp.py); `tools.ToolGate` runs their calls on the bus as `agent`.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zpkt.app.ask import notes as notes_module
from zpkt.app.ask.engines import MODEL_NAME, MODES, ToolServer
from zpkt.app.ask.events import ENGINE_NAME, ENGINES, Budget, Event, handoff_context
from zpkt.app.ask.library import Library
from zpkt.app.ask.permissions import Permissions
from zpkt.app.ask.provider import Outcome, Provider, Turn
from zpkt.app.ask.store import Refused, SessionStore
from zpkt.app.ask.tools import ToolGate
from zpkt.app.ask.workspaces import Workspaces

MAX_LIVE = 4
MAX_TITLE = 80


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
    ) -> None:
        self.dir = Path(data_dir)
        self.store = SessionStore(self.dir)
        self.providers, self.gate, self.guide = providers, gate, guide
        self.attach_dir = attach_dir or self.dir / "attachments"
        self.workspaces = Workspaces(self.dir, home)
        self.library = Library(self.dir)
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
        mode: str = "plan",
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
        try:
            context = self.notes.context(s, prompt)
            turn = self._turn(s, prompt, mode, engine, model, extra, context.text if context else "")
        except Exception:
            self.runs.pop(s["id"], None)
            raise
        self.store.emit(
            s["id"],
            {"type": "prompt", "text": prompt, "mode": mode, "model": model or "auto", "engine": engine, "auto": False}
            | ({"attachments": attachments} if attachments else {})
            | ({"extra": True} if extra else {}),
        )
        s["engine"] = engine
        self.store.touch(s)
        self.notes.seen(s, context)
        run.thread = threading.Thread(
            target=self._run, args=(s, turn, engine, run), daemon=True, name=f"ask-{s['id'][:8]}"
        )
        self.threads.append(run.thread)
        run.thread.start()

    def _turn(
        self, s: dict[str, Any], prompt: str, mode: str, engine: str, model: str, extra: str, context: str
    ) -> Turn:
        engines = self.store.engine_state(s)
        resume = bool(engines.get(engine, {}).get("started"))
        text = prompt + (f"\n\n{context}" if context else "") + (f"\n\n{extra}" if extra else "")
        events = self.store.replay(s["id"])
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
            if any(engines.get(o, {}).get("started") for o in ENGINES if o != engine):
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
        )

    def _tool_server(self, sid: str) -> ToolServer | None:
        if not self.app_url:
            return None
        env = {"ZPKT_APP_URL": self.app_url, "ZPKT_APP_SESSION": sid, "ZPKT_APP_TOKEN": self.gate.token(sid)}
        return ToolServer(self.tool_python, ("-m", "zpkt.app.ask.mcp"), env)

    def _run(self, s: dict[str, Any], turn: Turn, engine: str, run: Run) -> None:
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

        turn.mark_started = mark_started
        turn.ask_permission = lambda tool, options: self.permissions.ask(sid, tool, options, run.cancel)
        outcome = Outcome(None, None, "the engine did not run")
        try:
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
