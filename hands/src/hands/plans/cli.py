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
    hands plan slider KIT KNOB [--from --to]     one knob at N values, in one file the phone switches through
    hands plan line A B                          N steps from plan A to plan B, every knob moving together
    hands plan options PLAN PLAN [...]           any plans as buttons, in one file
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import typer

from .abfile import build
from .cache import Cache
from .model import KnobId, Plan, write_ahead
from .options import DEFAULT_BARS, fit_bars, knob_stops, line_stops, strip_path, values
from .options import build as build_strip
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


BARS = typer.Option(DEFAULT_BARS, help="Bars per option (fewer if the file would pass 135 s).")


def _stops(kit_P: int, stops: int) -> int:
    """The default: a whole Live pass, at least 8 stops and at most 16."""
    return stops if stops > 0 else min(16, max(kit_P, 8))


def _bake(planner: Planner, plans: list[Plan], labels: list[str], *, layout: str, name: str, now: int | None,
          bars: int) -> dict[str, Any]:
    """Render what is missing (packed into Live passes), cut the options into one file, and say how to present it."""
    kit_ = planner.kit(plans[0].kit)
    fake = isinstance(planner.renderer, FakeRenderer)
    bar_s = planner.renderer.bar_seconds if fake else kit_.bar_seconds()
    bars = fit_bars(len(plans), bar_s, bars, kit_.bars_per_pattern())
    r = planner.ensure(plans)
    keys = [e.key for e in r.entries]
    strip = build_strip([e.audio for e in r.entries], strip_path(planner.cache.root, keys, bars), bar_s, bars)
    return {"path": str(strip.path), "title": name[:120],
            "options": strip.present(labels, layout=layout, name=name, now=now),
            "plans": [{"label": lab, "key": k, "plan": p.to_json()} for lab, k, p in zip(labels, keys, plans)],
            "rendered": len(r.rendered), "cached": len(r.cached),
            "seconds": round(sum(t.get("total_s", 0) for t in r.timings), 1)}


@app.command()
def slider(kit_name: str = typer.Argument(..., metavar="KIT"), knob_id: str = typer.Argument(..., metavar="KNOB"),
           lo: float = typer.Option(None, "--from", help="The first stop (default: the knob's minimum)."),
           hi: float = typer.Option(None, "--to", help="The last stop (default: the knob's maximum)."),
           stops: int = typer.Option(0, help="How many values (default: one Live pass, 8 to 16)."),
           scale: str = typer.Option("lin", help="lin, or log (even ratios: frequencies, times)."),
           base: str = typer.Option(None, help="A plan on the kit whose other knobs hold at every stop."),
           bars: int = BARS, fake: bool = FAKE) -> None:
    """One knob at N values, baked in Live, as one file the phone's slider switches through without the Mac."""
    planner = _planner(fake)
    base_plan = _plan(base) if base else Plan(kit_name)
    if base_plan.kit != kit_name:
        raise typer.BadParameter(f"the base plan is on kit {base_plan.kit}, not {kit_name}")
    kit_ = planner.kit(kit_name)
    info = planner.info(kit_, {knob_id})[knob_id]
    vals = values(info.lo if lo is None else lo, info.hi if hi is None else hi, _stops(kit_.P, stops), scale)
    plans, labels, now = knob_stops(base_plan, knob_id, vals, info)
    kid = KnobId.parse(knob_id)
    name = f"{kid.track} {kid.param.split('/')[-1]}"
    _out(_bake(planner, plans, labels, layout="slider", name=name, now=now, bars=bars))


@app.command()
def line(a: str, b: str, stops: int = typer.Option(0, help="How many steps, A and B included (default 8 to 16)."),
         bars: int = BARS, fake: bool = FAKE) -> None:
    """N steps from plan A to plan B with every knob moving together, as one slider (A is where it starts)."""
    pa, pb = _plan(a), _plan(b)
    planner = _planner(fake)
    kit_ = planner.kit(pa.kit)
    info = planner.info(kit_, set(pa.knobs) | set(pb.knobs))
    plans, labels = line_stops(pa, pb, _stops(kit_.P, stops), info)
    name = f"{pa.describe()} to {pb.describe()}"
    _out(_bake(planner, plans, labels, layout="slider", name=name, now=0, bars=bars))


@app.command()
def options(plans: list[str], name: str = typer.Option("Options", help="What the choice is about, in a few words."),
            now: int = typer.Option(None, help="Which option is the sound as it is now (0-based)."),
            bars: int = BARS, fake: bool = FAKE) -> None:
    """Any plans on one kit as buttons: one file, and the phone switches between them without the Mac."""
    ps = [_plan(p) for p in plans]
    if now is not None and not 0 <= now < len(ps):
        raise typer.BadParameter(f"--now {now} is not one of the {len(ps)} options")
    _out(_bake(_planner(fake), ps, [p.describe() for p in ps], layout="buttons", name=name, now=now, bars=bars))


def main() -> None:          # `python -m hands.plans.cli`
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    app()


if __name__ == "__main__":
    main()
