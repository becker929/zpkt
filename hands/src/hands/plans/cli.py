"""`hands plan`: plans to renders to A/B files, for the voice loop (skills: render-plan, ab-1bar, plan-cache).

A PLAN argument is a JSON file or inline JSON: {"kit": "c8x4", "knobs": {"<track>|<device>|<param>": value},
"label": "..."}. Every command prints one JSON object.

    hands plan kit c8x4                          the kit: version, tempo, bar length, patterns
    hands plan knob c8x4 'rumble|plugin:Decapitator|Drive'     a knob's value and range in the kit
    hands plan lookup PLAN                       cached? else the nearest cached render, if close
    hands plan render PLAN [PLAN ...]            render what is not cached, in packs of P (one load, one export)
    hands plan ab A B                            A against B every bar, loudness-matched; renders what is missing
                                                 together with "more" and "the other end"
    hands plan ahead A B                         the write-ahead guesses only, as plans
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer

from .abfile import build
from .cache import Cache
from .model import Plan, write_ahead
from .render import FakeRenderer, LiveRenderer, Planner

app = typer.Typer(name="plan", help="Plans to renders to A/B files (the voice loop's music).", no_args_is_help=True)


def _plan(arg: str) -> Plan:
    text = Path(arg).read_text() if not arg.lstrip().startswith("{") and Path(arg).is_file() else arg
    try:
        return Plan.from_json(json.loads(text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise typer.BadParameter(f"not a plan ({exc}): {arg[:80]}") from None


def _planner(fake: bool) -> Planner:
    cache = Cache()
    renderer = FakeRenderer(cache.root / "fake") if fake else LiveRenderer()
    return Planner(cache=cache, renderer=renderer)


def _out(obj: Any) -> None:
    typer.echo(json.dumps(obj, indent=1))


FAKE = typer.Option(False, "--fake", help="Render with stand-in tones (no Live), for trying the flow.", hidden=True)


@app.command()
def kit(name: str) -> None:
    """The kit: version, tempo, bar length, patterns."""
    p = Planner(renderer=LiveRenderer())
    k = p.kit(name)
    _out({"kit": k.name, "set": k.set, "version": k.version(), "tempo": k.tempo(), "bar_seconds": k.bar_seconds(),
          "bars_per_pattern": k.bars_per_pattern(), "P": k.P})


@app.command()
def knob(kit_name: str, knobs: list[str]) -> None:
    """Knobs' values and ranges in the kit."""
    p = Planner(renderer=LiveRenderer())
    info = p.info(p.kit(kit_name), set(knobs))
    _out({k: {"value": i.base, "min": i.lo, "max": i.hi} for k, i in info.items()})


@app.command()
def lookup(plan: str) -> None:
    """Is this plan rendered? If not, the nearest cached render within reach."""
    _out(_planner(False).lookup(_plan(plan)))


@app.command()
def render(plans: list[str], fake: bool = FAKE) -> None:
    """Render the plans that are not cached yet (packed, one Live load and export per P plans)."""
    ps = [_plan(a) for a in plans]
    r = _planner(fake).ensure(ps)
    _out({"plans": [{"key": e.key, "label": p.describe(), "audio": str(e.audio), "cached": e.key in r.cached}
                    for p, e in zip(ps, r.entries)],
          "rendered": len(r.rendered), "seconds": round(sum(t.get("total_s", 0) for t in r.timings), 1)})


@app.command()
def ahead(a: str, b: str) -> None:
    """The write-ahead guesses after A against B: "more" and "the other end"."""
    pa, pb = _plan(a), _plan(b)
    planner = _planner(False)
    info = planner.info(planner.kit(pa.kit), set(pa.knobs) | set(pb.knobs))
    _out({"plans": [g.to_json() for g in write_ahead(pa, pb, info)]})


@app.command()
def ab(a: str, b: str, first: str = typer.Option("A", help="Which side plays first."),
       every: int = typer.Option(1, help="Bars per switch."),
       write_ahead_: bool = typer.Option(True, "--write-ahead/--no-write-ahead",
                                         help="Also render \"more\" and \"the other end\" in the same pass."),
       fake: bool = FAKE) -> None:
    """A against B, switching every bar, loudness-matched. Renders whatever is missing first."""
    pa, pb = _plan(a), _plan(b)
    planner = _planner(fake)
    r = planner.ensure([pa, pb], ahead_of=(pa, pb) if write_ahead_ else None)
    ea, eb = r.entries
    kit_ = planner.kit(pa.kit)
    bar_s = planner.renderer.bar_seconds if isinstance(planner.renderer, FakeRenderer) else kit_.bar_seconds()
    out = planner.cache.root / "ab" / f"{ea.key}-{eb.key}-{first}{every}.flac"
    f = build(ea.audio, eb.audio, out, bar_s, first=first.upper(), every=max(1, every))
    title = f"{pa.describe()} vs {pb.describe()}"
    _out({"path": str(f.path), "title": title[:120], "ab": f.present(pa.describe(), pb.describe()),
          "loudness_before_match": f.loudness, "keys": {"A": ea.key, "B": eb.key},
          "rendered": len(r.rendered), "cached": len(r.cached),
          "seconds": round(sum(t.get("total_s", 0) for t in r.timings), 1),
          "ahead": [{"label": e.plan.label, "key": e.key, "plan": e.plan.to_json()} for e in r.ahead]})


def main() -> None:          # `python -m hands.plans.cli`
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    app()


if __name__ == "__main__":
    main()
