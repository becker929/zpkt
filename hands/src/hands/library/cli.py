"""`hands library`: the library of WIP tracks, read-only.

    hands library inventory [--root DIR ...] [--exports DIR ...] [--records FILE] [--measure] [--json | --markdown]
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="The library of WIP tracks: where each one is in the seven steps (read-only).",
                  no_args_is_help=True)
console = Console()


@app.command("inventory")
def inventory_cmd(
    root: list[Path] = typer.Option(None, "--root", help="A folder of Live project folders (repeatable). "
                                    "Default: the rig's library_dir."),
    exports: list[Path] = typer.Option(None, "--exports", help="Another folder to look in for renders named after a "
                                       "track (repeatable). Default: the rig's renders_dir."),
    records_file: Path = typer.Option(None, "--records", help="Records file (default docs/inventory/records.toml)."),
    browser: Path = typer.Option(None, "--browser", help="audio-browser projects folder "
                                 "(default prototypes/audio-browser/projects)."),
    measure: bool = typer.Option(False, "--measure", help="Measure up to 3 master candidates per track with ears/mlab."),
    as_json: bool = typer.Option(False, "--json", help="Print the Inventory JSON (lib/contracts/inventory.schema.json)."),
    as_markdown: bool = typer.Option(False, "--markdown", help="Print a Markdown table and each track's evidence."),
) -> None:
    """Score every track's seven steps (collage, drums, arrange, kick, mix, master, release) from its sets and
    exports; records beat the heuristics. The headline is the lowest incomplete step."""
    from hands import config
    from hands.library import inventory as inv_mod
    from hands.library import workflow

    rig = config.rig()
    inv = inv_mod.inventory(
        root or [rig.library_dir], exports=exports if exports is not None else [rig.renders_dir],
        records_file=records_file or inv_mod.CENTRAL_RECORDS, browser=browser or inv_mod.BROWSER_PROJECTS,
        measure=inv_mod.measure_mlab if measure else None)
    if as_json:
        print(inv.model_dump_json(indent=2))
        return
    if as_markdown:
        print(inv_mod.markdown(inv), end="")
        return
    table = Table(title=f"{len(inv.tracks)} tracks", caption="* set by a record")
    table.add_column("Track")
    table.add_column("Lowest incomplete")
    for step in workflow.STEPS:
        table.add_column(step.numeral, justify="right")
    table.add_column("Set", style="dim")
    for t in inv.tracks:
        table.add_row(t.track, inv_mod.step_label(t.lowest_incomplete),
                      *[f"{x.percent}{'*' if x.record else ''}" for x in t.steps], t.set or "—")
    console.print(table)
    for line in inv.skipped:
        console.print(f"[dim]not scored: {line}[/dim]")
