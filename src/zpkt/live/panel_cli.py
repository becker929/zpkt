"""`hands panel ...`: an instrument, a riff, a render and its control panel, in one command each."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from zpkt.live import panel
from zpkt.live.cli_options import DIRECT, HOST, PORT, connect, fail
from zpkt.live.transport import LiveClient, LiveError, McpTransport

app = typer.Typer(
    no_args_is_help=True,
    help="""Control panels for Zpkt web: one instrument, a riff, a render, the knobs.

  hands panel make --spec - <<'JSON'
  {"name": "funk-bass", "instrument": "Operator", "tempo": 104,
   "params": {"Osc-A Wave": "Saw D", "Filter Freq": "600 Hz", "Filter Res": "40%"},
   "notes": [["A1", 0, 0.5, 110], ["C2", 0.75, 0.25, 90], ["E2", 1.5, 0.5, 100]], "beats": 16,
   "controls": ["Filter Freq", "Filter Res", "Ae Decay"]}
  JSON

It adds a track called "panel NAME" to the open set, renders the riff past the end of the arrangement and
prints the audio block and the control panel block to paste into the answer. `hands panel params Operator
--grep filter` lists parameter names, ranges and choices.

A mix panel is the same thing over tracks already in the set, heard on bars of the arrangement:

  hands panel make --spec '{"name": "buses", "bars": [17, 8], "faders": ["bus-kick", "bus-hats"],
    "devices": [{"track": "bus-kick", "device": "Saturator", "params": {"Drive": "6 dB"}, "controls": ["Drive"]}]}'

Several versions at once, for either kind: `hands panel grid NAME --axes '{"cutoff": {"steps": 4}}'` renders
each one in Live and prints one deck (A, B, C, ...); `hands panel pick NAME 1 C` keeps one.""",
)

OUT = typer.Option(Path("renders"), "--out", help="Folder for the renders and the panel's file.")
FORCE = typer.Option(False, "--force", help="Render even if Live is playing (stops it).")


def _json(arg: str | None, what: str) -> Any:
    """JSON from the argument itself, from @FILE, or from stdin (-)."""
    if arg is None:
        return None
    try:
        text = sys.stdin.read() if arg == "-" else Path(arg[1:]).read_text() if arg.startswith("@") else arg
        return json.loads(text)
    except OSError as exc:
        fail(f"{what}: cannot read {arg[1:]} ({exc.strerror or exc})", 2)
    except ValueError as exc:
        fail(f"{what} is not JSON: {exc}", 2)


def _run(fn: Callable[..., Any], client: McpTransport, *args: Any, what: str = "", **kwargs: Any) -> None:
    """Run one command with Live held for it (zpkt.live.hold): one command at a time, and what an interrupted
    one left is put back first."""
    from zpkt.live import hold

    what = what or f"hands {fn.__module__.rsplit('.', 1)[-1]} {fn.__name__}".replace(
        "hands versions", "hands panel"
    ).replace("hands mix", "hands panel")
    try:
        with hold.using_live(what, client=client) as put_back:
            for line in put_back:
                print(f"note: {line}", file=sys.stderr)
            print(fn(client, *args, **kwargs))
    except hold.Busy as exc:
        fail(f"ERROR: {exc}")
    except (panel.PanelError, LiveError) as exc:
        fail(f"ERROR: {plain(exc)}")
    except Exception as exc:
        fail(f"ERROR: {inside(exc)}")


_NOISE = re.compile(
    r" \(Multi-line code may have partially executed[^)]*\)| \[in '[^']*'\]|^(ValueError|RuntimeError|StopIteration): "
)


def plain(exc: BaseException) -> str:
    """An error from Live without the parts that are about hands' own code (which line of it, undo advice)."""
    text = _NOISE.sub("", str(exc)).strip()
    return text or f"Live could not do that ({type(exc).__name__}); check the names in the command against the set"


def inside(exc: BaseException) -> str:
    """One line for a failure hands did not expect: what, where, and the two things worth trying."""
    tb = exc.__traceback__
    while tb and tb.tb_next:
        tb = tb.tb_next
    where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}" if tb else "?"
    return (
        f"hands failed inside ({type(exc).__name__}: {str(exc)[:200]} at {where}). Either a value in the JSON has the "
        "wrong shape (compare it with the example in --help), or Live answered something odd: run `hands rig reset` "
        "and try once more."
    )


@app.command()
def make(
    spec: str = typer.Option(..., "--spec", help="The panel as JSON: the text itself, @FILE, or - for stdin."),
    replace: bool = typer.Option(False, "--replace", help="Replace the panel of the same name."),
    out: Path = OUT,
    force: bool = FORCE,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Load the instrument on a new track, set it, render the riff, print the audio and control panel blocks.

    The short form needs no parameter names: {"sound": "saw", "seq": "A B C D", "every": 4} is a saw playing
    one note on each downbeat. sound: saw, square, sine, triangle, noise, or pad / strings (layered saws that swell; chords are held) (an Operator with cutoff, resonance,
    decay and release knobs). seq: notes in order ("A B C D" climbs; "A1 C2" with octaves; "-" rests), one
    every `every` beats (1), each sounding `gate` (0.9) of its step. The name is made up if left out.

    Spec keys: name, instrument ("Operator", "Operator/Acid Bass", "Serum 2"), params ({name: value}; a number
    is the raw value, text is what Live shows: "800 Hz", "50%", "Saw D"), notes ([[pitch, start, length,
    velocity], ...] in beats, one pattern, repeated to fill beats; C3 is 60) or chords ("Dm9,Bbmaj9", one per
    bar) with rhythm (staccato-16ths, eighths, quarters, offbeats, whole, or beat offsets "0,0.75,1.5"), beats,
    tempo (only for the render), tail, controls (parameter names, or {param, label}), title.

    Only a device's parameters can be set: what `hands panel params NAME` lists. A sample or a wavetable is
    chosen by loading a preset as the instrument ("Wavetable/Basic Saw").
    """
    data = _json(spec, "--spec")
    if not isinstance(data, dict):
        fail("--spec must be a JSON object", 2)
    from zpkt.live import mix

    _run(
        mix.make if mix.is_mix(data) else panel.make,
        connect(LiveClient, host, port, direct=direct, keep=True),
        data,
        out,
        replace=replace,
        force=force,
    )


@app.command()
def apply(
    name: str = typer.Argument(..., help="The panel's name."),
    state: str = typer.Option(
        None, "--state", help="The Surface state from the page (or its values), as JSON, @FILE or -."
    ),
    spec: str = typer.Option(
        None, "--spec", help="Changes as JSON, @FILE or -: params, notes or chords, beats, tempo, controls."
    ),
    out: Path = OUT,
    force: bool = FORCE,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Set the panel's values, render the next version, print it with a before/after deck."""
    from zpkt.live import mix

    values, changes = _json(state, "--state"), _json(spec, "--spec")

    def apply(
        client: McpTransport,
    ) -> str:  # the panel's file is read once Live is held: another apply may be writing it
        made = _made(out, name)
        if made and made.get("kind") == "mix":
            return mix.apply(client, made, out, state_values=values, spec=changes, force=force)
        return panel.apply(client, name, out, state_values=values, spec=changes, force=force)

    _run(apply, connect(LiveClient, host, port, direct=direct, keep=True), what="hands panel apply")


def _made(out: Path, name: str) -> dict[str, Any] | None:
    """The panel's file, if it is there and whole (a cut-short or foreign file reads as no panel)."""
    try:
        made = json.loads(panel._file(out, name).read_text())
    except (OSError, ValueError):
        return None
    return made if isinstance(made, dict) else None


@app.command()
def grid(
    name: str = typer.Argument(..., help="The panel's name."),
    axes: str = typer.Option(
        ...,
        "--axes",
        help='What to vary, as JSON, @FILE or -: {"control id": {"from": "200 Hz", "to": "2 kHz", "steps": 4}} or {"control id": {"values": ["10 %", "60 %"]}}.',
    ),
    state: str = typer.Option(
        None, "--state", help="The Surface state from the page, so the other knobs are where the user has them."
    ),
    out: Path = OUT,
    force: bool = FORCE,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Render every combination (2 to 16 versions) and print them as one deck, A, B, C, ..., to hear side by side.

    One or two controls, by id, label or parameter name. A number is the raw value; text is what Live shows.
    Without from/to, the whole range. The panel's own values do not move until `hands panel pick`.
    """
    from zpkt.live import versions

    def note(k: int, n: int) -> None:
        print(f"rendering {k + 1} of {n}", file=sys.stderr, flush=True)

    _run(
        versions.grid,
        connect(LiveClient, host, port, direct=direct, keep=True),
        name,
        out,
        _json(axes, "--axes"),
        state_values=_json(state, "--state"),
        force=force,
        progress=note,
    )


@app.command()
def pick(
    name: str = typer.Argument(..., help="The panel's name."),
    grid_id: int = typer.Argument(..., help="Which grid (its number)."),
    letter: str = typer.Argument(..., help="Which version: A, B, C, ..."),
    out: Path = OUT,
    force: bool = FORCE,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Make one version of a grid the panel's values, in Live too. Nothing is rendered again."""
    from zpkt.live import versions

    _run(
        versions.pick,
        connect(LiveClient, host, port, direct=direct, keep=True),
        name,
        out,
        grid_id,
        letter,
        force=force,
    )


@app.command()
def params(
    instrument: str = typer.Argument(..., help="A name from Live's browser, as in a spec."),
    grep: str = typer.Option("", "--grep", help="Only names matching this (a regular expression, any case)."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """List a device's parameters: name | range | default = what Live shows | choices."""
    _run(panel.params, connect(LiveClient, host, port, changes=False, keep=True), instrument, grep)


@app.command()
def drop(
    name: str = typer.Argument(..., help="The panel's name."),
    out: Path = OUT,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Delete the panel's track from the open set. Its renders stay."""
    from zpkt.live import mix

    def drop(client: McpTransport) -> str:
        made = _made(out, name)
        return mix.drop(client, made, out) if made and made.get("kind") == "mix" else panel.drop(client, name, out)

    _run(drop, connect(LiveClient, host, port, direct=direct, keep=True), what="hands panel drop")


song_app = typer.Typer(
    no_args_is_help=True,
    help="""A song from panels: each panel's riff looped over the sections it plays in.

  hands song make --spec '{"name": "night-drive", "tempo": 124, "sections": [
    {"name": "intro", "bars": 8, "parts": ["nd-pad"]}, {"name": "drop", "bars": 16, "parts": ["nd-pad", "nd-bass"]}]}'

The clips go past the end of the arrangement and stay until `hands song drop`, so a mix panel can render bars
of the song ({"song": "night-drive", "bars": [9, 8], "faders": ["panel nd-pad", "panel nd-bass"]}).""",
)


@song_app.command("make")
def song_make(
    spec: str = typer.Option(
        ...,
        "--spec",
        help="The song as JSON, @FILE or -: name, tempo, sections [{name, bars, parts: [panel names]}], tail.",
    ),
    out: Path = OUT,
    force: bool = FORCE,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Lay the song out in the arrangement and render it (real time). Making it again replaces its clips."""
    from zpkt.live import song

    data = _json(spec, "--spec")
    if not isinstance(data, dict):
        fail("--spec must be a JSON object", 2)
    _run(song.make, connect(LiveClient, host, port, direct=direct, keep=True, timeout=30.0), data, out, force=force)


@song_app.command("render")
def song_render(
    name: str = typer.Argument(..., help="The song's name."),
    out: Path = OUT,
    force: bool = FORCE,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Render the song again as it now stands (after its panels or its mix changed)."""
    from zpkt.live import song

    _run(song.render, connect(LiveClient, host, port, direct=direct, keep=True), name, out, force=force)


@song_app.command("drop")
def song_drop(
    name: str = typer.Argument(..., help="The song's name."),
    out: Path = OUT,
    direct: bool = DIRECT,
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Delete the song's clips from the arrangement. Its panels' tracks and its renders stay."""
    from zpkt.live import song

    _run(song.drop, connect(LiveClient, host, port, direct=direct, keep=True), name, out)


def sweep_command(
    out: Path = OUT,
    project: list[Path] = typer.Option(
        [],
        "--project",
        help="A Live project to look for leftover takes in (repeat for more). The open set's project is looked at anyway.",
    ),
    days: float = typer.Option(7.0, "--days", help="Superseded renders go once they are this old."),
    apply: bool = typer.Option(False, "--apply", help="Delete. Without it, only say what would go."),
    pressure: bool = typer.Option(False, "--pressure", help="Do not wait --days: sweep everything superseded now."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    force: bool = typer.Option(False, "--force", help="Delete even when Live could not say which audio is in use."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Delete the files hands made that nothing can need again: leftover takes, old versions, old grids."""
    from zpkt.live import sweep

    projects, in_use = list(project), set()
    try:  # the open set: its project, and the audio it plays (which a set not saved yet would not show on disk)
        live = connect(LiveClient, host, port, changes=False, timeout=4.0, retries=0, keep=True)
        path, clips = live.run(
            "result = [str(getattr(song, 'file_path', '') or ''), sorted({str(c.file_path) for t in song.tracks "
            "for c in list(t.arrangement_clips) + [s.clip for s in t.clip_slots if s.has_clip] if c.is_audio_clip})]"
        )
        in_use = set(clips)
        if path:
            projects.append(Path(path).parent)
    except Exception as exc:
        if apply and not force:
            fail(
                f"ERROR: could not ask Live which audio is in use ({inside(exc)}); nothing deleted. Use --force to delete anyway."
            )
        print(f"warning: could not ask Live which audio is in use ({inside(exc)})", file=sys.stderr)
    try:
        result = sweep.sweep(out, projects, apply=apply, keep_days=days, pressure=pressure, in_use=in_use)
    except Exception as exc:
        fail(f"ERROR: {inside(exc)}")
    print(json.dumps(result) if as_json else sweep.report(result))
