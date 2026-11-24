"""`hands live ...`: one-shot commands against the running Live, for shells and skills.

This module parses arguments and prints; the work is in the library (session, render, ui, agent). The mix state's
commands are in state_cli, and the commands that build a set (reset, clip, device, surface) in edit_cli.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from hands import config
from hands.live.agent import AGENT_READ_ONLY, friendly, writes
from hands.live.cli_options import HOST, PORT, fail, front_set
from hands.live.transport import LiveClient, LiveError

app = typer.Typer(help="Drive the open Live set through the AbletonLiveMCP Remote Script.", no_args_is_help=True)


@app.command()
def audition(
    track: str = typer.Argument(..., help="Track name."),
    notes: str = typer.Option("69,72", help="Comma-separated MIDI notes."),
    listen: float = typer.Option(2.0, help="Seconds to read the meters."),
    force: bool = typer.Option(False, help="Audition even if Live is playing."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Play a chord on TRACK from a temporary arrangement clip, print meter peaks, clean up."""
    from hands.live.agent import audition as run_audition

    try:
        print(
            json.dumps(
                run_audition(
                    LiveClient(host, port), track, [int(n) for n in notes.split(",")], listen_s=listen, force=force
                )
            )
        )
    except LiveError as exc:
        fail(str(exc))


@app.command()
def reload(
    set_path: Path = typer.Argument(..., help="The .als Live has open (after an offline edit)."),
    save_first: bool = typer.Option(
        False, "--save-first", help="Save Live before reopening (only if the file was NOT edited offline)."
    ),
    seconds: int = typer.Option(10, help="Countdown length (the user can cancel)."),
) -> None:
    """Reopen SET_PATH in Live behind a cancellable countdown; wait for the bridge to answer."""
    from hands.live import session

    try:
        session.reload_set(set_path, save_first=save_first, seconds=seconds)
    except session.Guard as exc:
        fail(str(exc))
    print(f"reloaded: {set_path.stem}")


@app.command()
def ping(
    host: str = HOST,
    port: int | None = PORT,
    timeout: float = typer.Option(5.0, "--timeout", help="Seconds to wait for the pong."),
) -> None:
    """Check that the Remote Script is listening (it answers from its own thread, not Live's)."""
    try:
        seconds = LiveClient(host, port, timeout=timeout, retries=0).ping()
    except LiveError as exc:
        fail(str(exc))
    print(f"pong in {seconds * 1000:.0f} ms")


@app.command("exec")
def exec_(
    code: str = typer.Argument(None, help="Python to run in Live: an expression, or statements that set `result`."),
    file: Path = typer.Option(None, "--file", help="Read the code from a file."),
    stdin: bool = typer.Option(False, "--stdin", help="Read the code from stdin."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    raw: bool = typer.Option(
        False, "--raw", help="Don't prepend the helpers (param, set_norm, set_clamped, select_track)."
    ),
    timeout: float = typer.Option(15.0, "--timeout", help="Seconds to wait for the reply."),
    retries: int = typer.Option(2, "--retries", help="Connection retries (a sent request is never resent)."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Run LOM code in Live and print its result. Exit 1 if Live raised or was not reachable."""
    try:
        source = file.read_text() if file else sys.stdin.read() if stdin else code
    except (OSError, UnicodeDecodeError) as exc:
        fail(f"ERROR: cannot read the code ({exc})", 2)
    if not source or not source.strip():
        fail("give the code as an argument, --file or --stdin", 2)
    if os.environ.get("ZPKT_AGENT") and writes(source):
        fail(f"ERROR: {AGENT_READ_ONLY}")
    if not raw:
        from hands.live.agent import with_prelude

        source, notes = friendly(source)
        for note in notes:
            print(f"note: {note}", file=sys.stderr)
        source = with_prelude(source)
    res = LiveClient(host, port, timeout=timeout, retries=retries).execute(source)
    if res.warning:
        print(f"warning: {res.warning}", file=sys.stderr)
    if res.status != "ok":
        fail(f"ERROR: {res.error}" + (f"\n{res.traceback}" if res.traceback else ""))
    print(json.dumps(res.result) if as_json else res.result)


@app.command()
def check(
    expect: str = typer.Option(None, "--expect", help="The set that must be in front."),
    any_set: bool = typer.Option(False, "--any-set", help="Accept a set that is not one of ours (a desk session)."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Run the session guard: no dialog open, one of our sets in front, the LOM answering.
    Prints the front set; exit 1 with the reason if a check fails."""
    from hands.live import session

    try:
        print(session.check(LiveClient(host, port), "hands live check", expect_front=expect, ours=not any_set))
    except session.Guard as exc:
        fail(f"GUARD: {exc}")


@app.command()
def export(
    out: Path = typer.Argument(
        ..., help="File to write (.wav, .aif, .flac); a bare name goes to the rig's renders folder."
    ),
    start: float = typer.Option(None, "--start", help="First beat to render; with --length, selected first."),
    length: float = typer.Option(
        None, "--length", help="Beats to render. Without a range, Live's own (loop brace or whole song)."
    ),
    mode: str = typer.Option(
        "Main", "--mode", help='"Main", a track name, "All Individual Tracks" or "Selected Tracks Only".'
    ),
    bits: int = typer.Option(32, "--bits", help="16, 24 or 32."),
    sample_rate: int = typer.Option(44100, "--sample-rate"),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Render through Live's Export dialog and print the files written. Drives the GUI."""
    from hands.live import render, ui
    from hands.live.session import Guard

    if (start is None) != (length is None):
        fail("give both --start and --length, or neither", 2)
    path = out if out.is_absolute() or len(out.parts) > 1 else config.rig().renders_dir / out
    try:
        written = render.export(
            LiveClient(host, port), path, start, length, mode=mode, bits=bits, sample_rate=sample_rate
        )
    except (Guard, ui.UiError, LiveError, ValueError) as exc:
        fail(f"export failed: {exc}")
    print("\n".join(str(f) for f in written))


@app.command()
def modals(
    reap: bool = typer.Option(False, "--reap", help="Press each safe button (Cancel, Don't Save, No, Close, OK)."),
) -> None:
    """List Live's modal dialogs (CLEAN if none, NO_LIVE if Live is not running); --reap dismisses
    the ones with a safe button and reports ABORT for any it will not touch."""
    from hands.live import ui

    try:
        found = ui.reap_modals(reap)
        own = ui.dialogs() if found.strip() == "CLEAN" else 0
    except ui.UiError as exc:
        fail(str(exc))
    if own:  # Live draws its own prompts (Save changes?, Save As): no buttons to read or press from here
        found = f"OPEN | {own} dialog(s) Live draws itself; they cannot be read or pressed from here, look at Live"
    print(found)


@app.command("open")
def open_(
    name: str = typer.Argument(..., help="A set in the rig's sets folder, without .als."),
    no_save: bool = typer.Option(False, "--no-save", help="Do not save the set in front first."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Open a set and wait until it is in front and the LOM answers. The set in front is saved first."""
    from hands.live import session

    try:
        seconds = session.open_set(LiveClient(host, port), name.removesuffix(".als"), save_current=not no_save)
    except session.Guard as exc:
        fail(str(exc))
    print(f"opened {name} in {seconds:.1f} s")


@app.command()
def save(
    as_: str = typer.Option(None, "--as", help="Also keep a copy as sets_dir/<AS>.als (refuses to replace one)."),
    state: str = typer.Option(None, "--state", help="Also take the mix state as NAME (see `hands live state`)."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """File > Save Live Set on the front set and wait for its file; optionally keep a named copy and its state."""
    from hands.live import session
    from hands.live import state as S

    name = front_set()
    if as_ and config.rig().set_path(as_).exists():
        fail(f"{config.rig().set_path(as_)} exists; pick another name")
    wrote = session.save(name)
    print(f"{'saved' if wrote else 'nothing to save in'} {config.rig().set_path(name)}")
    if as_:
        print(f"copy {session.copy_set(name, as_)}")
    if state:
        p = S.save(S.take(LiveClient(host, port, keep=True)), S.path_for(name, state), name)
        print(f"state {p}")


from hands.live import edit_cli, state_cli  # noqa: E402  (they register their commands on app)

state_cli.register(app)
edit_cli.register(app)
