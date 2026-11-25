"""A Live transport that goes through the app: the same code strings, queued and logged by the zpkt app.

`LiveClient.via_app()` makes one. It is the one-line switch for a caller that used to open its own connection (the
`zpkt` command, music-bot's booth, zpkt-demo): the code runs in the app's one connection, under its lock, and the app
logs who asked. `via()` chooses by the ZPKT_LIVE_VIA setting. The HTTP is zpkt.app.client's; nothing here opens a
socket.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from typing import Literal

from zpkt.app.client import AppClient, AppDown
from zpkt.live.agent import only_reads
from zpkt.live.transport import McpResult, McpTransport, Transport

APP_DOWN = "Cannot reach the zpkt app"  # unlike "Cannot reach Ableton", it names the app


class AppTransport(Transport):
    """`execute` sends the code to the app's live.run and returns what Live said, as an McpResult."""

    def __init__(self, who: str = "cli", client: AppClient | None = None, group: str | None = None) -> None:
        """`group` ties this caller's changes together in the app's history; the default is one per transport."""
        self.client = client or AppClient(who)
        self.group = group or f"{self.client.who}-{uuid.uuid4().hex[:8]}"

    def execute(self, code: str) -> McpResult:
        """Code that certainly only reads goes as live.read, anything else as live.run. A read is not a move: an
        agent may ask it, and it is not held to a set, so a caller can wait for a set it has just opened."""
        kind = "live.read" if only_reads(code) else "live.run"
        try:
            status, reply = self.client.submit(kind, {"code": code}, group=self.group)
        except AppDown as exc:
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
        with contextlib.suppress(AppDown):
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
