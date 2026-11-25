"""`hands live describe|selection|page ...`: what the one interface's pages are built from (zpkt.live.describe,
zpkt.live.page). All three only read Live."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from zpkt.live.cli_options import DIRECT, HOST, PORT, connect, fail
from zpkt.live.transport import LiveClient, LiveError

page_app = typer.Typer(help="Pages of controls for the one interface: check a spec against the open set.")


def register(app: typer.Typer) -> None:
    app.command("describe")(describe)
    app.command("selection")(selection)
    app.add_typer(page_app, name="page")


def describe(
    keys: list[str] = typer.Argument(..., help='State keys, e.g. "Kick bus/desk EQ/1 Gain A" "Kick bus/volume".'),
    as_json: bool = typer.Option(False, "--json", help="Print the descriptions as JSON."),
    brief: bool = typer.Option(False, "--brief", help="Leave out each value's stops (far fewer tokens)."),
    host: str = HOST,
    port: int | None = PORT,
    direct: bool = DIRECT,
) -> None:
    """Kind, range, unit, steps, default and shown stops of each value. Exit 1 if the open set lacks one."""
    from zpkt.live import describe as D

    try:
        found, missing = D.look(connect(LiveClient, host, port, changes=False, direct=direct, keep=True), keys)
    except LiveError as exc:
        fail(str(exc))
    if as_json:
        shown = {k: D.brief(d) for k, d in found.items()} if brief else found
        print(json.dumps({"found": shown, "missing": missing}, indent=1))
    else:
        for key, d in found.items():
            if d["kind"] == "continuous":
                span = (
                    f"{d['stops'][0].shown} to {d['stops'][-1].shown}"
                    if d["stops"] and not brief
                    else f"{d['min']} to {d['max']}"
                )
            else:
                span = " | ".join(d["items"])
            print(f"{key}: {d['now'].shown}  ({d['kind']}; {span})")
        for key, why in missing.items():
            print(f"{key}: MISSING: {why}")
    if missing:
        raise typer.Exit(1)


def selection(
    as_json: bool = typer.Option(False, "--json", help="Print it as JSON."),
    host: str = HOST,
    port: int | None = PORT,
    direct: bool = DIRECT,
) -> None:
    """The track, device and parameter selected in Live, as state keys spell them."""
    from zpkt.live import describe as D

    try:
        sel = D.selection(connect(LiveClient, host, port, changes=False, direct=direct, keep=True))
    except LiveError as exc:
        fail(str(exc))
    if as_json:
        print(json.dumps(sel))
    else:
        print(sel["key"] or "/".join(x for x in (sel["track"], sel["device"]) if x) or "nothing selected")


@page_app.command("lint")
def page_lint(
    file: Path = typer.Argument(..., help="A page spec (.json)."),
    as_json: bool = typer.Option(False, "--json", help="Print problems, labels, widgets and the MiniLab map as JSON."),
    host: str = HOST,
    port: int | None = PORT,
    direct: bool = DIRECT,
) -> None:
    """Check a page spec against the open set, and say how it maps to the MiniLab. Exit 1 if it may not be shown."""
    from zpkt.live import describe as D
    from zpkt.live import page as P

    try:
        page = P.load(file)
    except (OSError, ValueError) as exc:
        fail(f"ERROR: {exc}", 2)
    try:
        found, missing = D.look(
            connect(LiveClient, host, port, changes=False, direct=direct, keep=True), page.targets()
        )
    except LiveError as exc:
        fail(str(exc))
    problems = P.lint(page, found, missing)
    hardware = P.assign(page, found)
    names = P.labels(page, found)
    if as_json:
        widgets = {c.ref: P.widget(c, found.get(c.ref)) for c in page.controls()}
        print(json.dumps({"problems": problems, "labels": names, "widgets": widgets, "minilab": hardware}, indent=1))
    else:
        for p in problems:
            print(f"{p['level']}: {p['where']}: {p['text']}")
        for i, hw in enumerate(hardware, 1):
            print(f"MiniLab page {i} ({', '.join(hw['groups'])}):")
            print("  " + "  ".join(f"{s['slot']}={names[s['ref']]}" for s in hw["slots"]))
        print("ok" if not any(p["level"] == "error" for p in problems) else "not shown: fix the errors")
    if any(p["level"] == "error" for p in problems):
        raise typer.Exit(1)
