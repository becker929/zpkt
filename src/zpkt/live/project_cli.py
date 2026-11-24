"""`hands build` and `hands execute`: the first design, a declarative ProjectConfig turned into LOM steps
(hands.models -> hands.builder -> hands.runner). Kept while Anthony decides whether it folds into something else."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def register(app: typer.Typer) -> None:
    app.command()(build)
    app.command()(execute)


def _load_config(config_path: str) -> Any:
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
        raise typer.Exit(1) from None


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


def execute(
    config: str = typer.Option(..., "--config", help="Path to ProjectConfig JSON."),
    resume: int = typer.Option(0, "--resume", help="Resume from step index."),
    host: str = typer.Option("127.0.0.1", "--host", help="Ableton MCP server host."),
    port: int | None = typer.Option(
        None, "--port", help="Ableton MCP server port (default: the rig's live_port, 16619)."
    ),
) -> None:
    """Execute Steps against a live Ableton session."""
    from hands.builder import ProjectBuilder
    from hands.live.transport import LiveClient
    from hands.runner import ManualPolicy, StepRunner

    cfg = _load_config(config)
    builder = ProjectBuilder(cfg)
    steps = builder.build_steps()

    transport = LiveClient(host=host, port=port)
    console.print(f"[bold]Executing {len(steps)} steps against Ableton @ {transport.host}:{transport.port}[/bold]")
    if resume > 0:
        console.print(f"[yellow]Resuming from step {resume}[/yellow]")

    runner = StepRunner(transport)
    results = runner.execute(steps, on_manual=ManualPolicy.PROMPT, resume_from=resume)

    failed = [r for r in results if r.status in ("error", "aborted")]
    if failed:
        console.print(f"[red]{len(failed)} step(s) failed. Run with --resume {failed[0].index} to retry.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Done — {len(results)} steps completed.[/green]")
