"""A Live transport that goes through the app: the same code strings, queued and logged by the zpkt app.

`LiveClient.via_app()` makes one. It is the one-line switch for a caller that used to open its own connection (the
`zpkt` command, music-bot's booth, zpkt-demo): the code runs in the app's one connection, under its lock, and the app
logs who asked. `via()` chooses by the ZPKT_LIVE_VIA setting. The HTTP is the app client's (zpkt.app.client); this
library never imports zpkt.app: it asks for a client through `AppClientLike`, and `make_client` finds the app's.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import uuid
from collections.abc import Callable
from typing import Any, Literal, Protocol

from zpkt.live.agent import only_reads
from zpkt.live.transport import McpResult, McpTransport, Transport

APP_DOWN = "Cannot reach the zpkt app"  # unlike "Cannot reach Ableton", it names the app


class AppClientLike(Protocol):
    """What the transport needs of the app's client (zpkt.app.client.AppClient is one)."""

    who: str

    def submit(self, kind: str, args: dict[str, Any], group: str | None = None) -> tuple[int, dict[str, Any]]: ...

    def up(self) -> bool: ...


ClientFactory = Callable[[str], AppClientLike]
_factory: ClientFactory | None = None


def set_client_factory(factory: ClientFactory | None) -> None:
    """Hand in the function that builds the app's client, instead of the default (None goes back to the default)."""
    global _factory
    _factory = factory


def make_client(who: str = "cli") -> AppClientLike:
    """The app's client for `who`: the one handed in, else zpkt.app.client's AppClient, found by name so that this
    library has no import of the app."""
    if _factory is not None:
        return _factory(who)
    client_class: ClientFactory = importlib.import_module("zpkt.app.client").AppClient
    return client_class(who)


class AppTransport(Transport):
    """`execute` sends the code to the app's live.run and returns what Live said, as an McpResult."""

    def __init__(self, who: str = "cli", client: AppClientLike | None = None, group: str | None = None) -> None:
        """`group` ties this caller's changes together in the app's history; the default is one per transport."""
        self.client = client or make_client(who)
        self.group = group or f"{self.client.who}-{uuid.uuid4().hex[:8]}"

    def execute(self, code: str) -> McpResult:
        """Code that certainly only reads goes as live.read, anything else as live.run. A read is not a move: an
        agent may ask it, and it is not held to a set, so a caller can wait for a set it has just opened."""
        kind = "live.read" if only_reads(code) else "live.run"
        try:
            status, reply = self.client.submit(kind, {"code": code}, group=self.group)
        except OSError as exc:  # zpkt.app.client.AppDown is an OSError
            return McpResult(status="error", error=f"{APP_DOWN}: {exc}")
        if status == 200 and isinstance(reply.get("reply"), dict):
            r = reply["reply"]
            return McpResult(
                status="ok" if r.get("status") == "ok" else "error",
                result=r.get("result"),
                error=r.get("error"),
                warning=r.get("warning"),
                elapsed=r.get("elapsed"),
                traceback=r.get("traceback"),
            )
        return McpResult(status="error", error=f"the zpkt app said {status}: {reply.get('error', reply)}")

    def close(self) -> None:
        """Nothing is held open."""

    def set_opened(self, name: str) -> None:
        """Tell the app which set this caller has just opened in Live (zpkt.live.session.tell_opened): a read that
        names it. When Live has that set, the app holds the calls that name no set to it from now on."""
        with contextlib.suppress(OSError):  # AppDown
            self.client.submit("live.read", {"code": "result = 1", "expect_set": name}, group=self.group)

    def ping(self) -> float:
        """The app answers; Live's own answer comes with the next call."""
        import time

        t0 = time.monotonic()
        if not self.client.up():
            from zpkt.live.transport import LiveError

            raise LiveError(f"{APP_DOWN}: start it with `zpkt app`")
        return time.monotonic() - t0


Via = Literal["app", "direct"]


def configured_via() -> Via | None:
    """ZPKT_LIVE_VIA: "app", "direct", or unset (None)."""
    value = os.environ.get("ZPKT_LIVE_VIA", "").strip().lower()
    if value in ("app", "direct"):
        return value  # type: ignore[return-value]
    if value:
        raise ValueError(f"ZPKT_LIVE_VIA is 'app' or 'direct', not {value!r}")
    return None


def via_app(who: str = "cli") -> McpTransport:
    return AppTransport(who)


def __getattr__(name: str) -> Any:
    """Old callers imported AppClient and AppDown from here; they live in zpkt.app.client, found when asked for."""
    if name in ("AppClient", "AppDown"):
        return getattr(importlib.import_module("zpkt.app.client"), name)
    raise AttributeError(name)
