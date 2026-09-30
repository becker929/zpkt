"""Typer CLI for the hands layer.

Commands:
    build    — render a ProjectConfig to Step list (dry-run by default)
    execute  — execute Steps against a running Ableton session
    record   — record and export audio via the resampling track
    vibe     — start the human feedback server
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="hands", help="DAW control layer for Ableton Live.")
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
    from hands.runner import ManualPolicy, StepRunner
    from hands.transport import DryRunTransport, LiveMcpTransport

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
    from hands.runner import ManualPolicy, StepRunner
    from hands.transport import LiveMcpTransport

    cfg = _load_config(config)
    builder = ProjectBuilder(cfg)
    steps = builder.build_steps()

    console.print(f"[bold]Executing {len(steps)} steps against Ableton @ {host}:{port}[/bold]")
    if resume > 0:
        console.print(f"[yellow]Resuming from step {resume}[/yellow]")

    transport = LiveMcpTransport(host=host, port=port)
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
    from hands.recorder import record_arrangement, record_via_resampling
    from hands.transport import LiveMcpTransport

    output_path = Path(output)
    transport = LiveMcpTransport(host=host, port=port)

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
def ableton_mcp(
    bridge_port: int = typer.Option(9010, "--bridge-port", help="Port for the MCP bridge HTTP server."),
    mcp_host: str = typer.Option("127.0.0.1", "--mcp-host", help="Ableton TCP host."),
    mcp_port: int = typer.Option(16619, "--mcp-port", help="Ableton TCP port."),
) -> None:
    """Start the Ableton MCP bridge server (Streamable HTTP for Letta).

    Exposes execute / api / search_api as a native MCP server so Letta can
    connect via StreamableHTTPServerConfig at http://host.docker.internal:<port>/mcp.
    """
    import os

    os.environ["ABLETON_MCP_BRIDGE_PORT"] = str(bridge_port)
    os.environ["ABLETON_MCP_HOST"] = mcp_host
    os.environ["ABLETON_TCP_PORT"] = str(mcp_port)

    from hands.mcp_server import serve

    console.print(f"[bold]Ableton MCP bridge → http://0.0.0.0:{bridge_port}/mcp[/bold]")
    console.print(f"[dim]Letta server_url: http://host.docker.internal:{bridge_port}/mcp[/dim]")
    serve()


@app.command()
def vibe(
    port: int = typer.Option(8080, "--port", help="Local vibe server port."),
    tunnel: bool = typer.Option(False, "--tunnel/--no-tunnel", help="Open ngrok tunnel."),
    mcp_host: str = typer.Option("127.0.0.1", "--mcp-host", help="Ableton MCP server host."),
    mcp_port: int = typer.Option(16619, "--mcp-port", help="Ableton MCP server port."),
) -> None:
    """Start the Letta-backed human feedback server."""
    import os as _os
    from hands.transport import LiveMcpTransport
    from hands.vibe.server import VibeServer

    output_dir = _os.environ.get("VIBE_OUTPUT_DIR", "/tmp/vibe")
    transport = LiveMcpTransport(host=mcp_host, port=mcp_port)
    server = VibeServer(transport=transport, output_dir=output_dir)

    if tunnel:
        from hands.vibe.tunnel import open_tunnel
        url = open_tunnel(port)
        console.print(f"[green]Tunnel open: {url}[/green]")

    console.print(f"[bold]Vibe server listening on http://0.0.0.0:{port}[/bold]")
    console.print(f"[dim]Output dir: {output_dir}[/dim]")
    console.print("POST /bounce — trigger a bounce")
    console.print("POST /feedback — submit feedback")
    console.print("GET  /session — session info")
    server.serve(port=port)


@app.command("self-improve")
def self_improve(
    description: str = typer.Argument(..., help="Short label for the improvement."),
    prompt: str = typer.Option(..., "--prompt", "-p", help="Full instructions for Claude Code."),
    restart: list[str] = typer.Option([], "--service", "-s", help="Service(s) to restart (repeat for multiple). Omit to auto-detect from changed files."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the prompt without running the agent."),
) -> None:
    """Apply a self-improvement to the agent harness using the Claude Agent SDK.

    Claude Code will make the requested code edits, then the affected services
    are restarted automatically.

    Example:
        hands self-improve "add /health endpoint" \\
          --prompt "Add a GET /health endpoint to hands/src/hands/vibe/server.py
                    that returns {status: ok, session_id: ...}. Follow the
                    existing _send_json pattern."
    """
    import asyncio

    if dry_run:
        console.print(f"[bold]Description:[/bold] {description}")
        console.print(f"[bold]Prompt:[/bold]\n{prompt}")
        if restart:
            console.print(f"[bold]Restart:[/bold] {', '.join(restart)}")
        else:
            console.print("[dim]Restart: auto-detect from changed files[/dim]")
        return

    try:
        from hands.self_modify import apply_improvement
    except ImportError as exc:
        console.print(f"[red]claude-agent-sdk not installed: {exc}[/red]")
        console.print("[dim]Install with: uv pip install 'hands[self-improve]'[/dim]")
        raise typer.Exit(1)

    console.print(f"[bold cyan]Self-improve:[/bold cyan] {description}")
    console.print("[dim]Running Claude Agent SDK session…[/dim]")

    result = asyncio.run(
        apply_improvement(
            description=description,
            prompt=prompt,
            restart=restart if restart else None,
        )
    )

    if result.get("changed_files"):
        console.print(f"\n[green]Changed files ({len(result['changed_files'])}):[/green]")
        for f in result["changed_files"]:
            console.print(f"  {f}")
    else:
        console.print("[yellow]No file changes detected.[/yellow]")

    if result.get("restarted_services"):
        console.print(f"\n[green]Restarted:[/green] {', '.join(result['restarted_services'])}")
    if result.get("setup_tools_run"):
        console.print("[green]Re-registered Letta tools (make setup-tools).[/green]")

    if result.get("agent_result"):
        console.print(f"\n[dim]Agent summary:[/dim] {result['agent_result'][:300]}")


def main() -> None:
    app()
