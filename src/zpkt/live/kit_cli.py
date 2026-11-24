"""`hands kit ...`: probe kits, the fast way to render many variants: P versions of a section in one load and one
export (zpkt.live.probe_kit)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Probe kits: P variants of a section in one load and one export.", no_args_is_help=True)
console = Console()


@app.command("template")
def kit_template(
    kit: str = typer.Argument(..., help="The kit's name, e.g. c8x4."),
    src: str = typer.Argument(..., help="The set to cut it from (in the rig's sets folder)."),
    keep_start: float = typer.Argument(..., help="First beat of the section."),
    keep_end: float = typer.Argument(..., help="Beat after its end."),
    patterns: int = typer.Argument(..., help="P, a power of two."),
    lead: float = typer.Option(8.0, "--lead", help="Beats of lead-in kept before the first pattern."),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int | None = typer.Option(
        None, "--port", help="Ableton MCP server port (default: the rig's live_port, 16619)."
    ),
) -> None:
    """Build a kit in Live (copy, Delete Time, Duplicate Time, save) and print its description."""
    from dataclasses import asdict

    from zpkt.live import probe_kit
    from zpkt.live.session import Guard
    from zpkt.live.transport import LiveClient

    try:
        made = probe_kit.template(LiveClient(host, port), kit, src, keep_start, keep_end, patterns, lead)
    except Guard as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    print(json.dumps(asdict(made)))


@app.command("render")
def kit_render(
    batch_set: str = typer.Argument(..., help="The batch set written by probe_kit.write_batch."),
    kit: str = typer.Argument(..., help="The kit it was made from."),
    out: Path = typer.Option(
        None, "--out", help="Folder for all.wav and pattern_XX.wav (default <data_dir>/kit_out/BATCH_SET)."
    ),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int | None = typer.Option(
        None, "--port", help="Ableton MCP server port (default: the rig's live_port, 16619)."
    ),
) -> None:
    """Load a batch set, export it once, check it and slice one WAV per pattern; print the manifest."""
    from zpkt.live import config, probe_kit
    from zpkt.live.audio import AudioError
    from zpkt.live.session import Guard
    from zpkt.live.transport import LiveClient

    try:
        manifest = probe_kit.render(
            LiveClient(host, port), batch_set, kit, out or config.rig().data_dir / "kit_out" / batch_set
        )
    except (Guard, AudioError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    print(json.dumps(manifest))
