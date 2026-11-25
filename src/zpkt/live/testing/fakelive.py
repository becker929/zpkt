"""FakeLive: an offline Live that runs the same code strings the real Remote Script runs.

It loads its own copy of zpkt/live/remote_scripts/AbletonLiveMCP and runs that script's `_dispatch`, `_execute` and
`_build_scope` unchanged over a fake set (zpkt.live.testing.lom), so a call is evaluated, executed and serialized exactly
as in Live. FakeLive is an McpTransport; `serve()` puts the script's own TCP server on a free port, so a CLI or a
server in another process can be pointed at it (`--port`, or ZPKT_LIVE_PORT for the rig's live_port).

    with FakeLive(hw002_like()) as live:
        state.take(live)                  # in process
        port = live.serve()               # over TCP: hands live state take NAME --port PORT
        assert len(live.calls) == 6

Every call is kept (`calls`: code, seconds, status, readbacks). `fail_on`, `time_out_on` and `lose_reply_on` make
the Nth call go wrong the ways Live's can. The code runs in this process: modules it puts in sys.modules by hand
(pager.py does) are taken out again by close().
"""

from __future__ import annotations

import contextlib
import functools
import importlib.machinery
import importlib.util
import json
import socket
import sys
import threading
import time
import types
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from zpkt.live.testing import devices
from zpkt.live.testing.lom import MAIN_THREAD, Application, Browser, Song, live_module
from zpkt.live.transport import DEFAULT_PORT, LOST, McpResult, Transport

REMOTE_SCRIPT = Path(__file__).resolve().parents[1] / "remote_scripts" / "AbletonLiveMCP" / "__init__.py"
_ABSENT = object()


@dataclass(frozen=True)
class Fault:
    """How a call goes wrong: Live raises before the code runs, or the reply times out or is lost."""

    kind: Literal["fail", "time_out", "lose"]
    runs: bool = True  # for time_out and lose: the code still ran (it may have, in Live)
    error: BaseException | None = None  # for fail


@dataclass
class Call:
    """One code call as Live saw it."""

    number: int
    code: str
    seconds: float
    status: str
    error: str | None = None
    readbacks: list[str] = field(default_factory=list)  # values read after this call wrote them (ableton-guide rule 1)
    fault: str | None = None


@contextlib.contextmanager
def _modules(entries: dict[str, types.ModuleType]) -> Iterator[None]:
    """Put modules in sys.modules for a while, then put back what was there."""
    before = {name: sys.modules.get(name, _ABSENT) for name in entries}
    sys.modules.update(entries)
    try:
        yield
    finally:
        for name, old in before.items():
            if old is _ABSENT:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old  # type: ignore[assignment]


def load_remote_script() -> types.ModuleType:
    """A private copy of the Remote Script. Its import of Live's _Framework is stubbed while it loads; FakeLive never
    builds the script's control surface (its __init__ would listen on Live's own port)."""
    if not REMOTE_SCRIPT.exists():
        raise FileNotFoundError(
            f"FakeLive runs the Remote Script itself and needs {REMOTE_SCRIPT}; "
            "use hands from its checkout (an editable install)"
        )
    framework, surface = types.ModuleType("_Framework"), types.ModuleType("_Framework.ControlSurface")
    surface.ControlSurface = type("ControlSurface", (), {})  # type: ignore[attr-defined]
    framework.ControlSurface = surface  # type: ignore[attr-defined]
    spec = importlib.util.spec_from_file_location("zpkt_fakelive_remote_script", REMOTE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with MAIN_THREAD, _modules({"_Framework": framework, "_Framework.ControlSurface": surface}):
        spec.loader.exec_module(module)
    return module


def _raise(error: BaseException | None, *args: Any) -> Any:
    """The script's eval for a call told to fail: Live raises before the code runs."""
    raise error if error is not None else RuntimeError("Fake failure")


class _Done:
    """Stands in for the threading.Event the script waits on, so a call can time out without waiting 12 s."""

    def __init__(self, fake: FakeLive) -> None:
        self._fault, self._event = fake._fault, threading.Event()

    def set(self) -> None:
        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._fault is not None and (self._fault.kind == "time_out" or not self._fault.runs):
            return False
        return self._event.wait(timeout)


class _Bridge:
    """Stands in for the script's AbletonLiveMCP instance: the script's own methods run on it, unchanged."""

    def __init__(self, fake: FakeLive) -> None:
        self._fake = fake
        self._active_conn: socket.socket | None = None
        script = fake._script.AbletonLiveMCP
        self._log = types.MethodType(script._log, self)
        self._dispatch = types.MethodType(script._dispatch, self)
        self._build_scope = types.MethodType(script._build_scope, self)
        self._script_execute = types.MethodType(script._execute, self)

    def _execute(self, code: str) -> dict[str, Any]:
        return self._fake._call(code, lambda: self._script_execute(code))

    # what the script asks of its ControlSurface

    def song(self) -> Song:
        return self._fake.song

    def application(self) -> Application:
        return self._fake.application

    def log_message(self, *parts: Any) -> None:
        self._fake.log.append(" ".join(str(p) for p in parts))

    def show_message(self, message: str) -> None:
        self._fake.messages.append(str(message))

    def schedule_message(self, delay: int, callback: Callable[[], None]) -> None:
        """Run on Live's main thread now, unless the call's fault says the code never runs."""
        fault = self._fake._fault
        if fault is None or fault.runs:
            callback()


class FakeLive(Transport):
    """An McpTransport over a fake set; see the module docstring."""

    def __init__(self, song: Song | None = None, *, surfaces: Sequence[Any] = ()) -> None:
        self.song = song if song is not None else Song()
        self.browser = Browser(self.song, devices.browser_roots())
        self.application = Application(self.song, self.browser, surfaces)
        self.live = live_module(self.application)
        self.calls: list[Call] = []
        self.log: list[str] = []  # Live's Log.txt: the script's log_message lines
        self.messages: list[str] = []  # what the script showed in Live's status bar
        self._script = load_remote_script()
        # the script's threading (and, for a call told to fail, its eval) in this copy only: so a call can fail or
        # time out as in Live, with the script's own replies
        self._script.__dict__["threading"] = types.SimpleNamespace(Event=lambda: _Done(self), Thread=threading.Thread)
        self._bridge = _Bridge(self)
        self._faults: dict[int, Fault] = {}
        self._fault: Fault | None = None
        self._direct = False
        self._lost = False
        self._ids = 0
        self._count = 0  # code calls so far: what fail_on and the others count, whatever a test does to `calls`
        self._added_modules: set[str] = set()
        self._server: Any = None
        self._thread: threading.Thread | None = None

    # --- the transport

    def execute(self, code: str) -> McpResult:
        """What LiveClient.execute returns for this code from a Live that holds this set."""
        self._ids += 1
        line = json.dumps({"id": f"cmd-{self._ids}", "code": code}).encode()
        with MAIN_THREAD:
            self._direct, self._lost = True, False
            try:
                reply = self._bridge._dispatch(line)
            finally:
                self._direct = False
            lost = self._lost
        if lost:
            return McpResult(status="error", error=f"{LOST}: Live closed the connection without a reply")
        reply = json.loads(json.dumps(reply, default=str))  # what the wire carries: the handler dumps it this way
        ok = reply.get("status") == "ok"
        return McpResult(
            status="ok" if ok else "error",
            result=reply.get("result"),
            error=None if ok else str(reply.get("error") or reply),
            warning=reply.get("warning") or reply.get("hint"),
            elapsed=reply.get("elapsed"),
            traceback=reply.get("traceback"),
        )

    def _call(self, code: str, run: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """One call on Live's main thread, kept in `calls`; `run` is the script's own _execute."""
        with MAIN_THREAD:
            self._count += 1
            number = self._count
            self._fault = self._faults.pop(number, None)
            fault, events = self._fault, self.song._events()
            trace = events.begin_call()
            if fault is not None and fault.kind == "fail":
                self._script.__dict__["eval"] = functools.partial(_raise, fault.error)
            before = set(sys.modules)
            t0 = time.perf_counter()
            try:
                with _modules({"Live": self.live}):
                    reply = run()
            finally:
                events.end_call()
                self._fault = None
                self._script.__dict__.pop("eval", None)
                self._added_modules |= set(sys.modules) - before - {"Live"}
            self.calls.append(
                Call(
                    number,
                    code,
                    time.perf_counter() - t0,
                    str(reply.get("status")),
                    reply.get("error"),
                    list(trace.readbacks),
                    fault.kind if fault else None,
                )
            )
            if fault is not None and fault.kind == "lose":
                self._lose_reply()
            return reply

    def _lose_reply(self) -> None:
        conn = self._bridge._active_conn
        if self._direct or conn is None:
            self._lost = True
            return
        with contextlib.suppress(OSError):
            conn.shutdown(socket.SHUT_RDWR)  # the handler's write fails: the client sees the connection close

    # --- making calls go wrong

    def fail_on(self, n: int, error: BaseException | str = "Fake failure") -> None:
        """Call n (counting from 1 over this FakeLive's life) raises in Live before its code runs."""
        self._faults[n] = Fault("fail", error=RuntimeError(error) if isinstance(error, str) else error)

    def time_out_on(self, n: int, *, runs: bool = True) -> None:
        """Call n answers "Timed out after 12s" at once; with runs, its code still ran, as Live's main thread would."""
        self._faults[n] = Fault("time_out", runs=runs)

    def lose_reply_on(self, n: int, *, runs: bool = True) -> None:
        """Call n's reply never comes: over TCP the connection closes; in process, the error LiveClient gives."""
        self._faults[n] = Fault("lose", runs=runs)

    # --- Live's side, for tests

    @property
    def codes(self) -> list[str]:
        return [c.code for c in self.calls]

    @property
    def listener_errors(self) -> list[str]:
        """Tracebacks of listeners that raised (Live writes them to its log and goes on)."""
        return self.song._events().listener_errors

    def main_thread(self) -> contextlib.AbstractContextManager[Any]:
        """Hold Live's main thread: change the set directly inside it while a client may be calling."""
        return MAIN_THREAD

    def tick(self, ticks: int = 1) -> None:
        """Let Live's clock run: what control surfaces deferred with schedule_message runs."""
        with MAIN_THREAD:
            for _ in range(ticks):
                for surface in self.application._surfaces:
                    if hasattr(surface, "tick"):
                        surface.tick()

    def play_for(self, beats: float) -> None:
        """Move the playhead as playback would (if the song is playing), firing its listeners."""
        with MAIN_THREAD:
            self.song._advance(beats)

    # --- serving over TCP

    def serve(self, port: int = 0) -> int:
        """Listen on 127.0.0.1 with the script's own server (one client at a time); return the port."""
        if port == DEFAULT_PORT:
            raise ValueError(f"{DEFAULT_PORT} is the real Live's port: serve the fake on a free one (port 0)")
        if self._server is not None:
            raise RuntimeError(f"already serving on port {self.port}")
        server = self._script._Server(("127.0.0.1", port), self._script._Handler)
        server.controller = self._bridge
        self._server = server
        bound = int(server.server_address[1])
        self._thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}, name=f"FakeLive :{bound}", daemon=True
        )
        self._thread.start()
        return bound

    @property
    def port(self) -> int | None:
        return self._server.server_address[1] if self._server is not None else None

    def close(self) -> None:
        """Stop serving (dropping a kept connection, as the script's disconnect does) and take out the modules the
        code put in sys.modules by hand."""
        if self._server is not None:
            conn = self._bridge._active_conn
            if conn is not None:
                with contextlib.suppress(OSError):
                    conn.shutdown(socket.SHUT_RDWR)
            self._server.shutdown()
            self._server.server_close()
            if self._thread is not None:
                self._thread.join(timeout=2)
            self._server = self._thread = None
        for name in sorted(self._added_modules):
            if (
                "." not in name
                and name not in sys.builtin_module_names
                and importlib.machinery.PathFinder.find_spec(name) is None
            ):
                sys.modules.pop(name, None)
        self._added_modules = set()

    def __enter__(self) -> FakeLive:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
