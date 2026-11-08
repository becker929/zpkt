"""`hands live ...`: one-shot commands against the running Live, for shells and skills."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NoReturn

import typer

from hands import config
from hands.live.transport import DEFAULT_HOST, DEFAULT_PORT, LiveClient, LiveError

app = typer.Typer(help="Drive the open Live set through the AbletonLiveMCP Remote Script.", no_args_is_help=True)

HOST = typer.Option(DEFAULT_HOST, "--host", help="Remote Script host.")
PORT = typer.Option(DEFAULT_PORT, "--port", help="Remote Script port.")


def _fail(message: str, code: int = 1) -> NoReturn:
    print(message, file=sys.stderr)
    raise typer.Exit(code)


@app.command()
def audition(
    track: str = typer.Argument(..., help="Track name."),
    notes: str = typer.Option("69,72", help="Comma-separated MIDI notes."),
    listen: float = typer.Option(2.0, help="Seconds to read the meters."),
    force: bool = typer.Option(False, help="Audition even if Live is playing."),
    host: str = HOST, port: int = PORT,
) -> None:
    """Play a chord on TRACK from a temporary arrangement clip, print meter peaks, clean up."""
    from hands.live.agent import audition as run_audition
    try:
        print(json.dumps(run_audition(LiveClient(host, port), track, [int(n) for n in notes.split(",")],
                                      listen_s=listen, force=force)))
    except LiveError as exc:
        _fail(str(exc))


@app.command()
def reload(
    set_path: Path = typer.Argument(..., help="The .als Live has open (after an offline edit)."),
    save_first: bool = typer.Option(False, "--save-first", help="Save Live before reopening (only if the file was NOT edited offline)."),
    seconds: int = typer.Option(10, help="Countdown length (the user can cancel)."),
) -> None:
    """Reopen SET_PATH in Live behind a cancellable countdown; wait for the bridge to answer."""
    import subprocess
    import time

    from hands.live import ui
    confirm = Path(__file__).resolve().parents[3] / "macros/hammerspoon/scripts/rig-confirm.sh"
    if save_first and not ui.menu("File", "Save Live Set"):
        _fail("could not save Live")
    if subprocess.run(["bash", str(confirm), f"Reloading the Live set {set_path.stem}", str(seconds)]).returncode != 0:
        _fail("cancelled (or no countdown)")
    subprocess.run(["open", "-a", "Ableton Live 12 Suite", str(set_path)], check=True)
    time.sleep(3)
    ui.reap_modals(reap=False)
    for _ in range(60):
        try:
            LiveClient(retries=0, timeout=3).run("1")
            print(f"reloaded: {ui.front_title()}")
            return
        except LiveError:
            time.sleep(2)
    _fail("Live did not answer after the reload")


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
    raw: bool = typer.Option(False, "--raw", help="Don't prepend the helpers (param, set_norm, set_clamped, select_track)."),
    timeout: float = typer.Option(15.0, "--timeout", help="Seconds to wait for the reply."),
    retries: int = typer.Option(2, "--retries", help="Connection retries (a sent request is never resent)."),
    host: str = HOST, port: int = PORT,
) -> None:
    """Run LOM code in Live and print its result. Exit 1 if Live raised or was not reachable."""
    source = file.read_text() if file else sys.stdin.read() if stdin else code
    if not source or not source.strip():
        _fail("give the code as an argument, --file or --stdin", 2)
    if not raw:
        from hands.live.agent import with_prelude
        source = with_prelude(source)
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
def export(
    out: Path = typer.Argument(..., help="File to write (.wav, .aif, .flac); a bare name goes to the rig's renders folder."),
    start: float = typer.Option(None, "--start", help="First beat to render; with --length, selected first."),
    length: float = typer.Option(None, "--length", help="Beats to render. Without a range, Live's own (loop brace or whole song)."),
    mode: str = typer.Option("Main", "--mode", help='"Main", a track name, "All Individual Tracks" or "Selected Tracks Only".'),
    bits: int = typer.Option(32, "--bits", help="16, 24 or 32."),
    sample_rate: int = typer.Option(44100, "--sample-rate"),
    host: str = HOST, port: int = PORT,
) -> None:
    """Render through Live's Export dialog and print the files written. Drives the GUI."""
    from hands.live import render, ui
    from hands.live.session import Guard

    if (start is None) != (length is None):
        _fail("give both --start and --length, or neither", 2)
    path = out if out.is_absolute() or len(out.parts) > 1 else config.rig().renders_dir / out
    try:
        written = render.export(LiveClient(host, port), path, start, length, mode=mode, bits=bits,
                                sample_rate=sample_rate)
    except (Guard, ui.UiError, LiveError, ValueError) as exc:
        _fail(f"export failed: {exc}")
    print("\n".join(str(f) for f in written))


@app.command()
def modals(reap: bool = typer.Option(False, "--reap", help="Press each safe button (Cancel, Don't Save, No, Close, OK).")) -> None:
    """List Live's modal dialogs (CLEAN if none, NO_LIVE if Live is not running); --reap dismisses
    the ones with a safe button and reports ABORT for any it will not touch."""
    from hands.live import ui

    try:
        print(ui.reap_modals(reap))
    except ui.UiError as exc:
        _fail(str(exc))
