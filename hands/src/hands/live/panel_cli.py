"""`hands panel ...`: an instrument, a riff, a render and its control panel, in one command each."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, NoReturn

import typer

from hands.live import panel
from hands.live.transport import DEFAULT_HOST, DEFAULT_PORT, LiveClient, LiveError

app = typer.Typer(no_args_is_help=True, help="""Control panels for Zpkt web: one instrument, a riff, a render, the knobs.

  hands panel make --spec - <<'JSON'
  {"name": "funk-bass", "instrument": "Operator", "tempo": 104,
   "params": {"Osc-A Wave": "Saw D", "Filter Freq": "600 Hz", "Filter Res": "40%"},
   "notes": [["A1", 0, 0.5, 110], ["C2", 0.75, 0.25, 90], ["E2", 1.5, 0.5, 100]], "beats": 16,
   "controls": ["Filter Freq", "Filter Res", "Ae Decay"]}
  JSON

It adds a track called "panel NAME" to the open set, renders the riff past the end of the arrangement and
prints the audio block and the control panel block to paste into the answer. `hands panel params Operator
--grep filter` lists parameter names, ranges and choices.""")

OUT = typer.Option(Path("renders"), "--out", help="Folder for the renders and the panel's file.")
HOST = typer.Option(DEFAULT_HOST, "--host", help="Remote Script host.")
PORT = typer.Option(DEFAULT_PORT, "--port", help="Remote Script port.")
FORCE = typer.Option(False, "--force", help="Render even if Live is playing (stops it).")


def _fail(message: str, code: int = 1) -> NoReturn:
    print(message, file=sys.stderr)
    raise typer.Exit(code)


def _json(arg: str | None, what: str) -> Any:
    """JSON from the argument itself, from @FILE, or from stdin (-)."""
    if arg is None:
        return None
    text = sys.stdin.read() if arg == "-" else Path(arg[1:]).read_text() if arg.startswith("@") else arg
    try:
        return json.loads(text)
    except ValueError as exc:
        _fail(f"{what} is not JSON: {exc}", 2)


def _run(fn, *args, **kwargs) -> None:
    try:
        print(fn(*args, **kwargs))
    except (panel.PanelError, LiveError) as exc:
        _fail(f"ERROR: {exc}")


@app.command()
def make(
    spec: str = typer.Option(..., "--spec", help="The panel as JSON: the text itself, @FILE, or - for stdin."),
    replace: bool = typer.Option(False, "--replace", help="Replace the panel of the same name."),
    out: Path = OUT, force: bool = FORCE, host: str = HOST, port: int = PORT,
) -> None:
    """Load the instrument on a new track, set it, render the riff, print the audio and control panel blocks.

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
        _fail("--spec must be a JSON object", 2)
    _run(panel.make, LiveClient(host, port), data, out, replace=replace, force=force)


@app.command()
def apply(
    name: str = typer.Argument(..., help="The panel's name."),
    state: str = typer.Option(None, "--state", help="The Surface state from the page (or its values), as JSON, @FILE or -."),
    spec: str = typer.Option(None, "--spec", help="Changes as JSON, @FILE or -: params, notes or chords, beats, tempo, controls."),
    out: Path = OUT, force: bool = FORCE, host: str = HOST, port: int = PORT,
) -> None:
    """Set the panel's values, render the next version, print it with a before/after deck."""
    _run(panel.apply, LiveClient(host, port), name, out, state_values=_json(state, "--state"), spec=_json(spec, "--spec"), force=force)


@app.command()
def params(
    instrument: str = typer.Argument(..., help="A name from Live's browser, as in a spec."),
    grep: str = typer.Option("", "--grep", help="Only names matching this (a regular expression, any case)."),
    host: str = HOST, port: int = PORT,
) -> None:
    """List a device's parameters: name | range | default = what Live shows | choices."""
    _run(panel.params, LiveClient(host, port), instrument, grep)


@app.command()
def drop(name: str = typer.Argument(..., help="The panel's name."), out: Path = OUT, host: str = HOST, port: int = PORT) -> None:
    """Delete the panel's track from the open set. Its renders stay."""
    _run(panel.drop, LiveClient(host, port), name, out)
