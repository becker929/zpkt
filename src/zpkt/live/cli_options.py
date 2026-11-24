"""What the `hands live` commands share: --host, --port, an exit with a message, and the name of the set in front."""

from __future__ import annotations

import sys
from typing import NoReturn

import typer

from zpkt.live.transport import DEFAULT_HOST

HOST = typer.Option(DEFAULT_HOST, "--host", help="Remote Script host.")
PORT = typer.Option(None, "--port", help="Remote Script port (default: the rig's live_port, 16619).")


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
