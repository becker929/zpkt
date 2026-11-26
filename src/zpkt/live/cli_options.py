"""What the `hands live` commands share: --host, --port, --direct, how a command reaches Live, an exit with a message,
and the name of the set in front.

A command that changes Live goes through the zpkt app (it queues, locks and records who asked). When the app is down
it refuses, unless given --direct: then it talks to Live itself and says the change is not recorded.
ZPKT_LIVE_VIA=direct makes every command direct without a warning (the old way); ZPKT_LIVE_VIA=app is the default.
In an agent's shell (ZPKT_AGENT is set) a command that changes Live stops before it does anything, by any route:
through the app, with --direct, with ZPKT_LIVE_VIA=direct (`agent_stop`). An agent changes Live through the app's
`change_live` tool only. Commands that only read still run. This guards against accidents; it is not a wall.

A command that only reads goes through the app too when it is running (so it waits its turn on the app's one
connection to Live) and falls back to a direct connection when the app is down, with --direct, with ZPKT_LIVE_VIA=direct,
or when --port names a Remote Script.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any, NoReturn, TypeVar

import typer

from zpkt.live.transport import DEFAULT_HOST, McpTransport

HOST = typer.Option(DEFAULT_HOST, "--host", help="Remote Script host.")
PORT = typer.Option(None, "--port", help="Remote Script port (default: the rig's live_port, 16619).")
DIRECT = typer.Option(
    False,
    "--direct",
    help="Talk to Live without the zpkt app (for repair). The change is not recorded. Without it, a change needs the app.",
)

_T = TypeVar("_T")
NOT_RECORDED = "warning: --direct talks to Live without the zpkt app, so this change is not recorded or undoable"
APP_NOT_RUNNING = (
    "the zpkt app is not running, and this command changes Live. Start it with `zpkt app`, or add --direct."
)


def agent_stop() -> None:
    """Stop here when an agent's shell runs a command that changes Live: say how an agent changes Live instead."""
    from zpkt.live.agent import AGENT_ENV, AGENT_NOT_FROM_SHELL

    if os.environ.get(AGENT_ENV):
        fail(f"ERROR: {AGENT_NOT_FROM_SHELL}")


def reach(factory: Callable[..., _T], host: str, port: int | None, **kwargs: Any) -> _T:
    """A direct connection, for the commands that look at the Remote Script itself (ping)."""
    return factory(host, port, **kwargs)


def connect(
    factory: Callable[..., McpTransport],
    host: str,
    port: int | None,
    *,
    changes: bool = True,
    direct: bool = False,
    **kwargs: Any,
) -> McpTransport:
    """The connection a command uses. `factory` is LiveClient (its module passes it, so a test can swap it).

    A change goes through the app; with the app down it stops, unless `direct`. A read goes through the app when it
    is running and otherwise straight to Live, silently. An explicit `port` means "that Remote Script": direct."""
    from zpkt.live.app_transport import AppTransport, configured_via, make_client

    if changes:
        agent_stop()
    forced_direct = direct or configured_via() == "direct"
    if not changes:
        if forced_direct or port is not None:
            return factory(host, port, **kwargs)
        client = make_client("cli")
        return AppTransport(client=client) if client.up() else factory(host, port, **kwargs)
    if direct:
        print(NOT_RECORDED, file=sys.stderr)
        return factory(host, port, **kwargs)
    if forced_direct:
        return factory(host, port, **kwargs)
    client = make_client("cli")
    if not client.up():
        fail(APP_NOT_RUNNING)
    return AppTransport(client=client)


def fail(message: str, code: int = 1) -> NoReturn:
    """Print `message` to stderr and exit with `code` (1: it did not work; 2: the command was given wrong)."""
    print(message, file=sys.stderr)
    raise typer.Exit(code)


def front_set() -> str:
    """The open set's name (zpkt.live.session.front_set), saying so on stderr when it is a guess."""
    from zpkt.live import session

    try:
        name, guessed = session.front_set()
    except session.Guard as exc:
        fail(str(exc))
    if guessed:
        print(f"(Live's window is not readable: using {name}, the set hands last saw open)", file=sys.stderr)
    return name
