"""The `hands` command: drive Ableton Live from a shell.

    live     — one-shot commands against the open set: exec, check, save, export, the mix state (hands.live.cli)
    panel    — an instrument, a riff, a render and its control panel for Zpkt web; song, sweep (hands.live.panel_cli)
    rig      — check the Live rig, and reset it when its state gets weird (hands.live.rig_cli)
    record   — record the output through a resampling track and export it
    ab       — A/B the mix against reference tracks; spectrum — show or hide the master Spectrum
    kit      — probe kits: many variants of a section in one export (hands.kit_cli)
    als      — a saved set offline: its checks, a device's parameters, its mix (hands.als_cli)
    library  — the WIP library: each track's place in the seven steps (hands.library, read-only)
    serum2   — Serum 2 presets: list, render offline, apply into a saved set (hands.serum2)
    build, execute — the first design: a ProjectConfig into LOM steps (hands.project_cli)

Each module named here parses its arguments and prints; the work is in the library.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from hands import als_cli, kit_cli, project_cli
from hands.library.cli import app as library_app
from hands.live.cli import app as live_app
from hands.live.panel_cli import app as panel_app
from hands.live.panel_cli import song_app, sweep_command
from hands.live.rig_cli import app as rig_app
from hands.serum2.cli import app as serum2_app

app = typer.Typer(name="hands", help="DAW control layer for Ableton Live.")
project_cli.register(app)
app.add_typer(live_app, name="live")
app.add_typer(library_app, name="library")
app.add_typer(serum2_app, name="serum2")
app.add_typer(als_cli.app, name="als")
app.add_typer(kit_cli.app, name="kit")
app.add_typer(panel_app, name="panel")
app.add_typer(song_app, name="song")
app.command("sweep")(sweep_command)
app.add_typer(rig_app, name="rig")
console = Console()


@app.command()
def record(
    beats: int = typer.Option(64, "--beats", help="Number of beats to record."),
    output: str = typer.Option("render.mp3", "--output", help="Output file path (wav or mp3)."),
    arrangement: bool = typer.Option(
        False,
        "--arrangement",
        help="Render the set's existing arrangement from beat 0 instead of bouncing session slot-0 clips.",
    ),
    tail: float = typer.Option(4.0, "--tail", help="Extra beats recorded after --beats (arrangement mode)."),
    host: str = typer.Option("127.0.0.1", "--host", help="Ableton MCP server host."),
    port: int | None = typer.Option(
        None, "--port", help="Ableton MCP server port (default: the rig's live_port, 16619)."
    ),
) -> None:
    """Record Ableton output via resampling track and export."""
    from hands.live.record import record_arrangement, record_via_resampling
    from hands.live.transport import LiveClient

    output_path = Path(output)
    transport = LiveClient(host=host, port=port)

    console.print(f"[bold]Recording {beats} beats → {output}[/bold]")
    # Pass the full name: the recorder picks WAV vs MP3 from the extension.
    try:
        if arrangement:
            result = record_arrangement(
                transport=transport,
                filename=output_path.name,
                duration_beats=float(beats),
                output_dir=str(output_path.parent),
                tail_beats=tail,
            )
        else:
            result = record_via_resampling(
                transport=transport,
                filename=output_path.name,
                duration_beats=float(beats),
                output_dir=str(output_path.parent),
            )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None

    if result:
        console.print(f"[green]Exported: {result}[/green]")
    else:
        console.print("[red]Recording failed — check Ableton is running.[/red]")
        raise typer.Exit(1)


@app.command()
def ab(
    action: str = typer.Argument("toggle", help="toggle | next | status"),
    spectrum: bool = typer.Option(False, "--spectrum", help="Also show the master Spectrum."),
    host: str = typer.Option("127.0.0.1", "--host", help="Ableton MCP server host."),
    port: int | None = typer.Option(
        None, "--port", help="Ableton MCP server port (default: the rig's live_port, 16619)."
    ),
) -> None:
    """A/B the mix against the current reference track (tracks named "REF ...")."""
    from hands import ab as ab_mod
    from hands.live.transport import LiveClient

    transport = LiveClient(host=host, port=port)
    actions = {
        "toggle": lambda: ab_mod.toggle(transport, spectrum=spectrum),
        "next": lambda: ab_mod.next_ref(transport),
        "status": lambda: ab_mod.status(transport),
    }
    if action not in actions:
        console.print(f"[red]unknown action {action!r}: use toggle, next or status[/red]")
        raise typer.Exit(2)
    try:
        print(json.dumps(actions[action]()))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None


@app.command("spectrum")
def spectrum_cmd(
    show: bool = typer.Option(False, "--show", help="Always show; never hide."),
    host: str = typer.Option("127.0.0.1", "--host", help="Ableton MCP server host."),
    port: int | None = typer.Option(
        None, "--port", help="Ableton MCP server port (default: the rig's live_port, 16619)."
    ),
) -> None:
    """Toggle the master Spectrum analyzer in Live's detail view."""
    from hands import ab as ab_mod
    from hands.live.transport import LiveClient

    try:
        print(json.dumps(ab_mod.spectrum(LiveClient(host=host, port=port), toggle=not show)))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None


def main() -> None:
    """The `hands` command. A failure nobody planned for ends in one line an agent can act on, not a traceback
    (set HANDS_TRACEBACK=1 to see it)."""
    import os
    import sys

    try:
        app()
    except Exception as exc:
        if os.environ.get("HANDS_TRACEBACK"):
            raise
        from hands.live.panel_cli import inside

        print(f"ERROR: {inside(exc)}", file=sys.stderr)
        sys.exit(1)
