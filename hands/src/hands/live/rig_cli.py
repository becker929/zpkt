"""`hands rig check` and `hands rig reset`: is Live ready to render, and put it back when it is not."""

from __future__ import annotations

import json
import sys

import typer

from hands.live import rig

app = typer.Typer(help="Check the Live rig (Live, its audio, macOS audio) and reset it when its state gets weird.",
                  no_args_is_help=True)


@app.command()
def check(
    as_json: bool = typer.Option(False, "--json", help="Print the findings as JSON."),
    play: bool = typer.Option(True, help="Play for a second to see that Live's playhead moves."),
) -> None:
    """Report what is wrong with the rig, changing nothing. Exit 0 when it is ready to render."""
    h = rig.check(play=play)
    if as_json:
        print(json.dumps(h.as_dict()))
    elif h.problems:
        print("\n".join(f"- {p}" for p in h.problems))
        if h.needs != "wait":
            print(f"`hands rig reset` would do a {h.needs} reset.")
    else:
        print("ready: Live answers, plays and has an audio device")
    raise typer.Exit(0 if h.needs == "nothing" else 1)


@app.command()
def reset(
    set_path: str = typer.Option(None, "--set", help="The .als to open again (default: the set in front, else the last one)."),
    level: str = typer.Option("auto", help="auto (the mildest step that works), soft, or restart."),
    discard: bool = typer.Option(False, help="Throw away unsaved changes instead of saving them (after a backup)."),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON at the end."),
) -> None:
    """Put Live and macOS audio back into a working state. Exit 0 when the rig is ready again."""
    if level not in ("auto", "soft", "restart"):
        print("--level is auto, soft or restart", file=sys.stderr)
        raise typer.Exit(2)
    from pathlib import Path
    report = rig.reset(set_path=Path(set_path).expanduser() if set_path else None, level=level, keep=not discard)
    if as_json:
        print(json.dumps(report.__dict__))
    else:
        if report.needs_you:
            print("needs you:\n" + "\n".join(f"- {n}" for n in report.needs_you))
        problems = (report.health or {}).get("problems") or []
        print("ready" if report.ok else "still not ready:\n" + "\n".join(f"- {p}" for p in problems))
    raise typer.Exit(0 if report.ok else 1)
