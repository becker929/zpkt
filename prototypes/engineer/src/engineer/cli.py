"""engineer CLI: run the loop."""
from __future__ import annotations

import typer

app = typer.Typer(name="engineer", help="Run the hands → ears → taste loop.")


@app.callback()
def _engineer() -> None:
    """Keeps `loop` a subcommand: Typer runs a lone command as the app itself."""


@app.command()
def loop(
    config: str = typer.Option(..., "--config", help="Path to a ProjectConfig JSON."),
    cycles: int = typer.Option(1, "--cycles"),
    hands_bin: str = typer.Option("hands", "--hands-bin"),
    ears_bin: str = typer.Option("ears", "--ears-bin"),
) -> None:
    """Run N cycles: hands record → ears analyze → taste judge."""
    from engineer.loop import Loop
    orch = Loop(hands_bin=hands_bin, ears_bin=ears_bin)
    for i in range(cycles):
        typer.echo(f"Cycle {i + 1}/{cycles}…")
        verdict = orch.run_cycle(config)
        typer.echo(f"  score={verdict.score}/5  {verdict.rationale[:80]}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
