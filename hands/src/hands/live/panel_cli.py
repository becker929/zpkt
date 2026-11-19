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
--grep filter` lists parameter names, ranges and choices.

A mix panel is the same thing over tracks already in the set, heard on bars of the arrangement:

  hands panel make --spec '{"name": "buses", "bars": [17, 8], "faders": ["bus-kick", "bus-hats"],
    "devices": [{"track": "bus-kick", "device": "Saturator", "params": {"Drive": "6 dB"}, "controls": ["Drive"]}]}'

Several versions at once, for either kind: `hands panel grid NAME --axes '{"cutoff": {"steps": 4}}'` renders
each one in Live and prints one deck (A, B, C, ...); `hands panel pick NAME 1 C` keeps one.""")

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
        _fail("--spec must be a JSON object", 2)
    from hands.live import mix
    _run(mix.make if mix.is_mix(data) else panel.make, LiveClient(host, port, keep=True), data, out, replace=replace, force=force)


@app.command()
def apply(
    name: str = typer.Argument(..., help="The panel's name."),
    state: str = typer.Option(None, "--state", help="The Surface state from the page (or its values), as JSON, @FILE or -."),
    spec: str = typer.Option(None, "--spec", help="Changes as JSON, @FILE or -: params, notes or chords, beats, tempo, controls."),
    out: Path = OUT, force: bool = FORCE, host: str = HOST, port: int = PORT,
) -> None:
    """Set the panel's values, render the next version, print it with a before/after deck."""
    from hands.live import mix
    made = _made(out, name)
    if made and made.get("kind") == "mix":
        _run(mix.apply, LiveClient(host, port, keep=True), made, out, state_values=_json(state, "--state"), spec=_json(spec, "--spec"), force=force)
        return
    _run(panel.apply, LiveClient(host, port, keep=True), name, out, state_values=_json(state, "--state"), spec=_json(spec, "--spec"), force=force)


def _made(out: Path, name: str) -> dict | None:
    f = panel._file(out, name)
    return json.loads(f.read_text()) if f.exists() else None


@app.command()
def grid(
    name: str = typer.Argument(..., help="The panel's name."),
    axes: str = typer.Option(..., "--axes", help='What to vary, as JSON, @FILE or -: {"control id": {"from": "200 Hz", "to": "2 kHz", "steps": 4}} or {"control id": {"values": ["10 %", "60 %"]}}.'),
    state: str = typer.Option(None, "--state", help="The Surface state from the page, so the other knobs are where the user has them."),
    out: Path = OUT, force: bool = FORCE, host: str = HOST, port: int = PORT,
) -> None:
    """Render every combination (2 to 16 versions) and print them as one deck, A, B, C, ..., to hear side by side.

    One or two controls, by id, label or parameter name. A number is the raw value; text is what Live shows.
    Without from/to, the whole range. The panel's own values do not move until `hands panel pick`.
    """
    from hands.live import versions
    note = lambda k, n: print(f"rendering {k + 1} of {n}", file=sys.stderr, flush=True)  # noqa: E731
    _run(versions.grid, LiveClient(host, port, keep=True), name, out, _json(axes, "--axes"), state_values=_json(state, "--state"), force=force, progress=note)


@app.command()
def pick(
    name: str = typer.Argument(..., help="The panel's name."),
    grid_id: int = typer.Argument(..., help="Which grid (its number)."),
    letter: str = typer.Argument(..., help="Which version: A, B, C, ..."),
    out: Path = OUT, force: bool = FORCE, host: str = HOST, port: int = PORT,
) -> None:
    """Make one version of a grid the panel's values, in Live too. Nothing is rendered again."""
    from hands.live import versions
    _run(versions.pick, LiveClient(host, port, keep=True), name, out, grid_id, letter, force=force)


@app.command()
def params(
    instrument: str = typer.Argument(..., help="A name from Live's browser, as in a spec."),
    grep: str = typer.Option("", "--grep", help="Only names matching this (a regular expression, any case)."),
    host: str = HOST, port: int = PORT,
) -> None:
    """List a device's parameters: name | range | default = what Live shows | choices."""
    _run(panel.params, LiveClient(host, port, keep=True), instrument, grep)


@app.command()
def drop(name: str = typer.Argument(..., help="The panel's name."), out: Path = OUT, host: str = HOST, port: int = PORT) -> None:
    """Delete the panel's track from the open set. Its renders stay."""
    from hands.live import mix
    made = _made(out, name)
    if made and made.get("kind") == "mix":
        _run(mix.drop, LiveClient(host, port, keep=True), made, out)
        return
    _run(panel.drop, LiveClient(host, port, keep=True), name, out)


song_app = typer.Typer(no_args_is_help=True, help="""A song from panels: each panel's riff looped over the sections it plays in.

  hands song make --spec '{"name": "night-drive", "tempo": 124, "sections": [
    {"name": "intro", "bars": 8, "parts": ["nd-pad"]}, {"name": "drop", "bars": 16, "parts": ["nd-pad", "nd-bass"]}]}'

The clips go past the end of the arrangement and stay until `hands song drop`, so a mix panel can render bars
of the song ({"song": "night-drive", "bars": [9, 8], "faders": ["panel nd-pad", "panel nd-bass"]}).""")


@song_app.command("make")
def song_make(
    spec: str = typer.Option(..., "--spec", help="The song as JSON, @FILE or -: name, tempo, sections [{name, bars, parts: [panel names]}], tail."),
    out: Path = OUT, force: bool = FORCE, host: str = HOST, port: int = PORT,
) -> None:
    """Lay the song out in the arrangement and render it (real time). Making it again replaces its clips."""
    from hands.live import song
    data = _json(spec, "--spec")
    if not isinstance(data, dict):
        _fail("--spec must be a JSON object", 2)
    _run(song.make, LiveClient(host, port, keep=True, timeout=30.0), data, out, force=force)


@song_app.command("render")
def song_render(name: str = typer.Argument(..., help="The song's name."), out: Path = OUT, force: bool = FORCE, host: str = HOST, port: int = PORT) -> None:
    """Render the song again as it now stands (after its panels or its mix changed)."""
    from hands.live import song
    _run(song.render, LiveClient(host, port, keep=True), name, out, force=force)


@song_app.command("drop")
def song_drop(name: str = typer.Argument(..., help="The song's name."), out: Path = OUT, host: str = HOST, port: int = PORT) -> None:
    """Delete the song's clips from the arrangement. Its panels' tracks and its renders stay."""
    from hands.live import song
    _run(song.drop, LiveClient(host, port, keep=True), name, out)


def sweep_command(
    out: Path = OUT,
    project: list[Path] = typer.Option([], "--project", help="A Live project to look for leftover takes in (repeat for more). The open set's project is looked at anyway."),
    days: float = typer.Option(7.0, "--days", help="Superseded renders go once they are this old."),
    apply: bool = typer.Option(False, "--apply", help="Delete. Without it, only say what would go."),
    pressure: bool = typer.Option(False, "--pressure", help="Do not wait --days: sweep everything superseded now."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    host: str = HOST, port: int = PORT,
) -> None:
    """Delete the files hands made that nothing can need again: leftover takes, old versions, old grids."""
    from hands.live import sweep

    projects, in_use = list(project), set()
    try:   # the open set: its project, and the audio it plays (which a set not saved yet would not show on disk)
        live = LiveClient(host, port, timeout=4.0, retries=0, keep=True)
        path, clips = live.run("result = [str(getattr(song, 'file_path', '') or ''), sorted({str(c.file_path) for t in song.tracks "
                               "for c in list(t.arrangement_clips) + [s.clip for s in t.clip_slots if s.has_clip] if c.is_audio_clip})]")
        in_use = set(clips)
        if path:
            projects.append(Path(path).parent)
    except (LiveError, OSError, ValueError, TypeError):
        pass
    result = sweep.sweep(out, projects, apply=apply, keep_days=days, pressure=pressure, in_use=in_use)
    print(json.dumps(result) if as_json else sweep.report(result))
