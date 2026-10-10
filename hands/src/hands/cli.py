"""Typer CLI for the hands layer.

Commands:
    build    — render a ProjectConfig to Step list (dry-run by default)
    execute  — execute Steps against a running Ableton session
    record   — record and export audio via the resampling track
    ab       — A/B the mix against reference tracks
    spectrum — show or hide the master Spectrum
    live     — one-shot LOM commands (ping, exec)
    als      — check a Live set file, list a device's parameters (offline)
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from hands.live.cli import app as live_app

app = typer.Typer(name="hands", help="DAW control layer for Ableton Live.")
app.add_typer(live_app, name="live")
als_app = typer.Typer(help="Check Live set files offline.", no_args_is_help=True)
app.add_typer(als_app, name="als")
console = Console()


def _load_config(config_path: str):
    """Load and validate a ProjectConfig from a JSON file."""
    from hands.models import ProjectConfig

    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        raise typer.Exit(1)

    try:
        return ProjectConfig.model_validate_json(path.read_text())
    except Exception as exc:
        console.print(f"[red]Invalid config: {exc}[/red]")
        raise typer.Exit(1)


@app.command()
def build(
    config: str = typer.Option(..., "--config", help="Path to ProjectConfig JSON."),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Print steps without executing."),
) -> None:
    """Render a ProjectConfig to Step list and print or execute."""
    from hands.builder import ProjectBuilder
    from hands.live.transport import DryRunTransport
    from hands.runner import ManualPolicy, StepRunner

    cfg = _load_config(config)
    builder = ProjectBuilder(cfg)
    steps = builder.build_steps()

    table = Table(title=f"Build: {cfg.name} ({len(steps)} steps)")
    table.add_column("#", style="dim", width=4)
    table.add_column("Label")
    table.add_column("Note", style="dim")
    for i, step in enumerate(steps):
        table.add_row(str(i), step.label, step.note or "")
    console.print(table)

    if dry_run:
        console.print("[yellow]Dry run — use --no-dry-run to execute against Ableton.[/yellow]")
        transport = DryRunTransport()
        runner = StepRunner(transport)
        runner.execute(steps, on_manual=ManualPolicy.SKIP)
    else:
        console.print("[red]Execute mode not available without --no-dry-run.[/red]")


@app.command()
def execute(
    config: str = typer.Option(..., "--config", help="Path to ProjectConfig JSON."),
    resume: int = typer.Option(0, "--resume", help="Resume from step index."),
    host: str = typer.Option("127.0.0.1", "--host", help="Ableton MCP server host."),
    port: int = typer.Option(16619, "--port", help="Ableton MCP server port."),
) -> None:
    """Execute Steps against a live Ableton session."""
    from hands.builder import ProjectBuilder
    from hands.live.transport import LiveClient
    from hands.runner import ManualPolicy, StepRunner

    cfg = _load_config(config)
    builder = ProjectBuilder(cfg)
    steps = builder.build_steps()

    console.print(f"[bold]Executing {len(steps)} steps against Ableton @ {host}:{port}[/bold]")
    if resume > 0:
        console.print(f"[yellow]Resuming from step {resume}[/yellow]")

    transport = LiveClient(host=host, port=port)
    runner = StepRunner(transport)
    results = runner.execute(steps, on_manual=ManualPolicy.PROMPT, resume_from=resume)

    failed = [r for r in results if r.status in ("error", "aborted")]
    if failed:
        console.print(f"[red]{len(failed)} step(s) failed. Run with --resume {failed[0].index} to retry.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Done — {len(results)} steps completed.[/green]")


@app.command()
def record(
    beats: int = typer.Option(64, "--beats", help="Number of beats to record."),
    output: str = typer.Option("render.mp3", "--output", help="Output file path (wav or mp3)."),
    arrangement: bool = typer.Option(
        False, "--arrangement",
        help="Render the set's existing arrangement from beat 0 instead of bouncing session slot-0 clips.",
    ),
    tail: float = typer.Option(4.0, "--tail", help="Extra beats recorded after --beats (arrangement mode)."),
    host: str = typer.Option("127.0.0.1", "--host", help="Ableton MCP server host."),
    port: int = typer.Option(16619, "--port", help="Ableton MCP server port."),
) -> None:
    """Record Ableton output via resampling track and export."""
    from hands.live.transport import LiveClient
    from hands.live.record import record_arrangement, record_via_resampling

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
        raise typer.Exit(1)

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
    port: int = typer.Option(16619, "--port", help="Ableton MCP server port."),
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
        raise typer.Exit(1)


@app.command("spectrum")
def spectrum_cmd(
    show: bool = typer.Option(False, "--show", help="Always show; never hide."),
    host: str = typer.Option("127.0.0.1", "--host", help="Ableton MCP server host."),
    port: int = typer.Option(16619, "--port", help="Ableton MCP server port."),
) -> None:
    """Toggle the master Spectrum analyzer in Live's detail view."""
    from hands import ab as ab_mod
    from hands.live.transport import LiveClient

    try:
        print(json.dumps(ab_mod.spectrum(LiveClient(host=host, port=port), toggle=not show)))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@als_app.command("check")
def als_check(
    file: Path = typer.Argument(..., help="The .als to check."),
    against: Path = typer.Option(None, "--against", help="The set it was made from: also show what changed."),
) -> None:
    """Run the self-checks a .als must pass before Live loads it. Exit 1 on a problem."""
    from hands import als

    report = als.check(file, against)
    print(report)
    if report.problems:
        raise typer.Exit(1)


@als_app.command("params")
def als_params(
    file: Path = typer.Argument(..., help="The .als to read."),
    track: str = typer.Argument(..., help="Track name."),
    device: str = typer.Argument(..., help="Device XML tag, e.g. Reverb or StereoGain."),
    index: int = typer.Option(0, "--index", help="Which device with that tag (-1: the last)."),
) -> None:
    """List a device's automatable parameters: tag, event kind, value and range."""
    from hands import als

    print("\n".join(als.list_params(file, track, device, index)))


def main() -> None:
    app()
