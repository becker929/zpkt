"""engineer CLI: run the loop, or run a mastering hypothesis."""
from __future__ import annotations

import typer

app = typer.Typer(name="engineer", help="Run the hands → ears → taste loop, or a hypothesis.")
hyp_app = typer.Typer(help="Claim → variants → measured verdict.")
app.add_typer(hyp_app, name="hyp")


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


@hyp_app.command("run")
def hyp_run(
    file: str = typer.Argument(..., help="Hypothesis YAML (see engineer/hypotheses/TEMPLATE.yaml)."),
    codecs: bool = typer.Option(None, "--codecs/--no-codecs", help="Also measure after codec round trips."),
) -> None:
    """Build the variants, measure each with ears' meters, and write a verdict."""
    from engineer import hypothesis
    outdir, verdict = hypothesis.run(file, codecs=codecs)
    typer.echo(f"{verdict}  →  {outdir}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
