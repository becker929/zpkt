"""`hands als ...`: a saved Live set read offline: the self-checks, a device's parameters, the mix it holds."""

from __future__ import annotations

import json
from pathlib import Path

import typer

app = typer.Typer(help="Check Live set files offline.", no_args_is_help=True)


@app.command("check")
def als_check(
    file: Path = typer.Argument(..., help="The .als to check."),
    against: Path = typer.Option(None, "--against", help="The set it was made from: also show what changed."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
) -> None:
    """Run the self-checks a .als must pass before Live loads it. Exit 1 on a problem."""
    from zpkt.live import als

    report = als.check(file, against)
    print(
        json.dumps({"ok": not report.problems, "lines": report.lines, "problems": report.problems})
        if as_json
        else report
    )
    if report.problems:
        raise typer.Exit(1)


@app.command("params")
def als_params(
    file: Path = typer.Argument(..., help="The .als to read."),
    track: str = typer.Argument(..., help="Track name."),
    device: str = typer.Argument(..., help="Device XML tag, e.g. Reverb or StereoGain."),
    index: int = typer.Option(0, "--index", help="Which device with that tag (-1: the last)."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
) -> None:
    """List a device's automatable parameters: tag, event kind, value and range."""
    from zpkt.live import als

    rows = als.list_params(file, track, device, index)
    print(json.dumps(rows) if as_json else "\n".join(rows))


@app.command("mix")
def als_mix(
    file: Path = typer.Argument(..., help="A saved set (.als) or a name in the rig's sets folder."),
    against: Path = typer.Option(None, "--against", help="Another saved set: show only what differs (B = FILE)."),
    ignore: list[str] = typer.Option(None, "--ignore", help="Skip keys starting with this (e.g. 'mon '), repeatable."),
    full: bool = typer.Option(False, "--full", help="Every row, not the collapsed summary."),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
) -> None:
    """The mix a saved set holds (faders, sends, mutes, devices), offline; with --against, what differs.
    Live is not touched. Exit 1 if --against finds a difference."""
    from zpkt.live import als, config
    from zpkt.live import state as S

    def resolve(p: Path) -> Path:
        return p if p.exists() else config.rig().set_path(str(p).removesuffix(".als"))

    b: S.State = als.mix_state(resolve(file))  # type: ignore[assignment]  # the state's shape, in .als units
    if against is None:
        lines = als.mix_lines(b)
        print(json.dumps(lines) if as_json else "\n".join(lines))
        return
    a: S.State = als.mix_state(resolve(against))  # type: ignore[assignment]
    rows = S.diff(a, b, tuple(ignore or ()))
    if as_json:
        print(
            json.dumps({"values": len(S.flatten(a)), "differ": len(rows), "rows": [list(r) for r in rows]}, default=str)
        )
    else:
        print(
            f"{len(S.flatten(a))} values in A ({resolve(against).name}), {len(rows)} differ in B ({resolve(file).name})"
        )
        print(S.summarize(rows, limit=10**6 if full else 60))
    if rows:
        raise typer.Exit(1)
