"""`hands live state ...`: the mix state of the open set as data (zpkt.live.state): take it, compare it, put it back."""

from __future__ import annotations

import time

import typer

from zpkt.live.cli_options import HOST, PORT, front_set
from zpkt.live.transport import LiveClient

state_app = typer.Typer(
    help="The mix state of the open set as data: take it, compare it, put it back.", no_args_is_help=True
)


def register(app: typer.Typer) -> None:
    app.add_typer(state_app, name="state")


@state_app.command("take")
def state_take(
    name: str = typer.Argument(..., help="State name (or a .json path)."),
    only: list[str] = typer.Option(None, "--only", help="Only these tracks (repeatable)."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Every mixer and device value of the front set -> sets_dir/state/<set>/NAME.json."""
    from zpkt.live import state as S

    set_name = front_set()
    t0 = time.monotonic()
    st = S.take(LiveClient(host, port, keep=True), only)
    p = S.save(st, S.path_for(set_name, name), set_name)
    print(f"{p}  ({len(st['tracks'])} tracks, {len(S.flatten(st))} values, {time.monotonic() - t0:.1f} s)")


@state_app.command("diff")
def state_diff(
    a: str = typer.Argument(..., help='A state name, a state .json, or a recipe .json with a "desk".'),
    b: str = typer.Argument(None, help="Another one; default: Live now."),
    ignore: list[str] = typer.Option(None, "--ignore", help="Skip keys starting with this (e.g. 'mon '), repeatable."),
    full: bool = typer.Option(False, "--full", help="Every row, not the collapsed summary."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """What differs between A and B (or Live now). Only tracks A holds are read from Live. Exit 1 if anything does."""
    from zpkt.live import state as S

    set_name = front_set() if b is None or not b.endswith(".json") or not a.endswith(".json") else ""
    sa = S.load(S.path_for(set_name, a))
    if b is None:
        sb = S.take(LiveClient(host, port, keep=True), only=list(sa["tracks"]))
    else:
        sb = S.load(S.path_for(set_name, b))
    rows = S.diff(sa, sb, tuple(ignore or ()))
    n = len(S.flatten(sa))
    print(f"{n} values in A, {len(rows)} differ")
    print(S.summarize(rows, limit=10**6 if full else 60))
    if rows:
        raise typer.Exit(1)


@state_app.command("put")
def state_put(
    name: str = typer.Argument(..., help='A state name or .json (a recipe with a "desk" works too).'),
    only: list[str] = typer.Option(None, "--only", help="Only these tracks (repeatable)."),
    host: str = HOST,
    port: int | None = PORT,
) -> None:
    """Write a state's raw values into Live, read them back; exit 1 with what still differs."""
    from zpkt.live import hold
    from zpkt.live import state as S

    set_name = front_set()
    st = S.load(S.path_for(set_name, name))
    with hold.using_live(f"hands live state put {name}"):
        rows = S.put(LiveClient(host, port, keep=True), st, only)
    print("put, Live matches" if not rows else f"{len(rows)} differ after put:\n{S.summarize(rows)}")
    if rows:
        raise typer.Exit(1)


@state_app.command("ls")
def state_ls() -> None:
    """The states kept for the front set, newest first."""
    from zpkt.live import state as S

    d = S.folder(front_set())
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if d.exists() else []
    print(
        "\n".join(f"{p.stem:30s} {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}" for p in files)
        or f"none in {d}"
    )
