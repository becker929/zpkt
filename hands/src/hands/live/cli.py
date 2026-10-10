"""`hands live ...`: one-shot commands against the running Live, for shells and skills."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NoReturn

import typer

from hands.live.transport import DEFAULT_HOST, DEFAULT_PORT, LiveClient, LiveError

app = typer.Typer(help="Drive the open Live set through the AbletonLiveMCP Remote Script.", no_args_is_help=True)

HOST = typer.Option(DEFAULT_HOST, "--host", help="Remote Script host.")
PORT = typer.Option(DEFAULT_PORT, "--port", help="Remote Script port.")


def _fail(message: str, code: int = 1) -> NoReturn:
    print(message, file=sys.stderr)
    raise typer.Exit(code)


@app.command()
def ping(host: str = HOST, port: int = PORT,
         timeout: float = typer.Option(5.0, "--timeout", help="Seconds to wait for the pong.")) -> None:
    """Check that the Remote Script is listening (it answers from its own thread, not Live's)."""
    try:
        seconds = LiveClient(host, port, timeout=timeout, retries=0).ping()
    except LiveError as exc:
        _fail(str(exc))
    print(f"pong in {seconds * 1000:.0f} ms")


@app.command("exec")
def exec_(
    code: str = typer.Argument(None, help="Python to run in Live: an expression, or statements that set `result`."),
    file: Path = typer.Option(None, "--file", help="Read the code from a file."),
    stdin: bool = typer.Option(False, "--stdin", help="Read the code from stdin."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    timeout: float = typer.Option(15.0, "--timeout", help="Seconds to wait for the reply."),
    retries: int = typer.Option(2, "--retries", help="Connection retries (a sent request is never resent)."),
    host: str = HOST, port: int = PORT,
) -> None:
    """Run LOM code in Live and print its result. Exit 1 if Live raised or was not reachable."""
    source = file.read_text() if file else sys.stdin.read() if stdin else code
    if not source or not source.strip():
        _fail("give the code as an argument, --file or --stdin", 2)
    res = LiveClient(host, port, timeout=timeout, retries=retries).execute(source)
    if res.warning:
        print(f"warning: {res.warning}", file=sys.stderr)
    if res.status != "ok":
        _fail(f"ERROR: {res.error}" + (f"\n{res.traceback}" if res.traceback else ""))
    print(json.dumps(res.result) if as_json else res.result)


@app.command()
def check(
    expect: str = typer.Option(None, "--expect", help="The set that must be in front."),
    any_set: bool = typer.Option(False, "--any-set", help="Accept a set that is not one of ours (a desk session)."),
    host: str = HOST, port: int = PORT,
) -> None:
    """Run the session guard: no dialog open, one of our sets in front, the LOM answering.
    Prints the front set; exit 1 with the reason if a check fails."""
    from hands.live import session

    try:
        print(session.check(LiveClient(host, port), "hands live check", expect_front=expect, ours=not any_set))
    except session.Guard as exc:
        _fail(f"GUARD: {exc}")


@app.command()
def modals(reap: bool = typer.Option(False, "--reap", help="Press each safe button (Cancel, Don't Save, No, Close, OK).")) -> None:
    """List Live's modal dialogs (CLEAN if none, NO_LIVE if Live is not running); --reap dismisses
    the ones with a safe button and reports ABORT for any it will not touch."""
    from hands.live import ui

    try:
        print(ui.reap_modals(reap))
    except ui.UiError as exc:
        _fail(str(exc))
