"""Several versions of a panel at once: a grid over its knobs and faders, heard side by side, and the pick.

    hands panel grid funk-bass --axes '{"cutoff": {"from": "200 Hz", "to": "2 kHz", "steps": 4}, "resonance": {"values": ["10 %", "60 %"]}}'
    hands panel pick funk-bass 1 C

Every option is rendered in Live (the same render as `apply`), so what is compared is what Live plays. The
options go into one deck (A, B, C, ...) that Zpkt web switches between on the bar. The panel's own values do
not move until an option is picked. Works for instrument panels and mix panels alike.
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hands.live import hold
from hands.live import mix as M
from hands.live import panel as P
from hands.live.transport import McpTransport

MAX_OPTIONS = 16
LETTERS = "ABCDEFGHIJKLMNOP"


def load(out_dir: Path, name: str) -> dict[str, Any]:
    f = P._file(out_dir, name)
    if not f.exists():
        raise P.PanelError(f"no panel {name!r} in {out_dir} (expected {f.name}); make it with `hands panel make`")
    return P.read_file(f, f"panel {name!r}")


def _control(panel: dict[str, Any], key: str) -> dict[str, Any]:
    k = str(key).strip().lower()
    for c in panel["controls"]:
        if k in (c["id"].lower(), c["label"].lower(), c["param"].lower()):
            return c
    near = [
        c for c in panel["controls"] if any(k in x for x in (c["id"].lower(), c["label"].lower(), c["param"].lower()))
    ]
    if len(near) == 1:  # "drive" for "bus-kick Drive", when only one control has it
        return near[0]
    raise P.PanelError(f"the panel has no control {key!r}; it has: {', '.join(c['id'] for c in panel['controls'])}")


def _where(panel: dict[str, Any], c: dict[str, Any]) -> str:
    """The Live expression for a control's parameter."""
    if panel.get("kind") == "mix":
        return panel["exprs"][c["param"]]
    return f"next(p for p in {P._device(panel['track'])}.parameters if p.name == {c['param']!r})"


def _raw(client: McpTransport, panel: dict[str, Any], c: dict[str, Any], want: Any) -> float:
    """A raw value for a number (already raw), "50%" of the range, or what Live shows ("800 Hz", "-6 dB")."""
    if isinstance(want, bool):
        return c["max"] if want else c["min"]
    if isinstance(want, (int, float)):
        return max(c["min"], min(c["max"], float(want)))
    r = P.reading(want)
    if r is None:
        raise P.PanelError(f"{c['label']}: cannot read {want!r}; give a number or text the way Live shows it")
    expr = _where(panel, c)
    lo, hi = c["min"], c["max"]
    for n in (P.SAMPLES, P.FINE):  # the whole range, then the stretch that reads as asked
        xs = P._grid(lo, hi, n)
        table = client.run(f"_p = {expr}\nresult = [str(_p.str_for_value(v)) for v in {xs!r}]")
        hits = P._between(r[0], xs, table, r[1])
        if not hits:
            raise P.PanelError(f"{c['label']}: nothing between {table[0]!r} and {table[-1]!r} reads {want!r}")
        lo, hi = hits[0][0], hits[-1][1]
    return (lo + hi) / 2


FADER_SPAN_DB = 6.0


def fader_span(
    client: McpTransport, panel: dict[str, Any], c: dict[str, Any], lo: float, hi: float
) -> tuple[float, float]:
    """A level grid with no range given spans the 6 dB below where the fader is (the question is nearly always
    "a bit louder or quieter?"), not silence to +6 dB. The whole travel if the level cannot be read."""
    current = (panel.get("values") or {}).get(c["param"])
    if current is None:
        return lo, hi
    try:
        shown = str(client.run(f"_p = {_where(panel, c)}\nresult = str(_p.str_for_value({float(current)!r}))"))
        m = re.match(r"\s*(-?[\d.]+)\s*dB", shown)
        if m is None:
            return lo, hi
        db = float(m.group(1))
    except (AttributeError, ValueError, TypeError, Exception):
        return lo, hi
    return _raw(client, panel, c, f"{db - FADER_SPAN_DB:g} dB"), float(current)


def axis_values(client: McpTransport, panel: dict[str, Any], c: dict[str, Any], ask: Any) -> list[float]:
    """The raw values one axis takes: {"values": [...]}, or {"from", "to", "steps"} (evenly, in the control's own travel)."""
    ask = ask if isinstance(ask, dict) else {"values": ask} if isinstance(ask, list) else {}
    if ask.get("values"):
        return [_raw(client, panel, c, v) for v in ask["values"]]
    if c["kind"] == "toggle":
        return [c["min"], c["max"]]
    steps = int(ask.get("steps") or 3)
    if not 2 <= steps <= 8:
        raise P.PanelError(f"{c['label']}: 2 to 8 steps; got {steps}")
    lo = _raw(client, panel, c, ask["from"]) if ask.get("from") is not None else c["min"]
    hi = _raw(client, panel, c, ask["to"]) if ask.get("to") is not None else c["max"]
    if c["kind"] == "fader" and ask.get("from") is None and ask.get("to") is None:
        lo, hi = fader_span(client, panel, c, lo, hi)
    vals = [lo + (hi - lo) * k / (steps - 1) for k in range(steps)]
    return [float(round(v)) for v in vals] if c.get("step") else vals


def _render(
    client: McpTransport,
    panel: dict[str, Any],
    state: dict[str, Any],
    out: Path,
    values: dict[str, float],
    recorder: Callable[..., str | None],
) -> dict[str, Any]:
    if panel.get("kind") == "mix":
        return M.render_bars(client, panel, state, out, recorder, values)
    notes = [tuple(n) for n in panel["notes"]]
    state = {**state, "names": state["names"]}
    return P._render(
        client, panel["track"], state, notes, panel["beats"], panel["tail"], panel["tempo"], out, recorder, values
    )


def _matched(files: list[Path], results: list[dict[str, Any]]) -> list[str | None]:
    """A copy of each render turned to the same RMS as the quietest (never up, so nothing clips): hands, not the page."""
    import numpy as np
    import soundfile as sf

    target = min(r["rms_dbfs"] for r in results)
    out: list[str | None] = []
    for f, r in zip(files, results):
        if r["rms_dbfs"] - target < 0.2:
            out.append(None)
            continue
        x, sr = sf.read(f, always_2d=True, dtype="float64")
        m = f.with_name(f"{f.stem}-m.wav")
        sf.write(m, x * 10 ** ((target - r["rms_dbfs"]) / 20), sr, subtype="PCM_24")
        out.append(P._shown_path(m))
        _ = np
    return out


def deck(panel: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    """The zpkt-surface control for a grid: every option as a source, switched on the bar."""
    bars = max(1, min(64, int(panel["beats"] // 4)))
    return {
        "kind": "deck",
        "id": f"grid{grid['id']}",
        "label": f"Grid {grid['id']}: {' × '.join(a['label'] for a in grid['axes'])}",
        "sources": [
            {
                "label": o["letter"],
                "note": o["label"],
                "src": o["file"],
                **({"matched": o["matched"]} if o.get("matched") else {}),
            }
            for o in grid["options"]
        ],
        "bpm": P._num(panel["tempo"]),
        "downbeatMs": 0,
        "loop": {"startBar": 1, "bars": bars},
        "quantize": "bar",
        "pick": grid["id"],
    }


def _print(panel: dict[str, Any], grid: dict[str, Any], lines: list[str]) -> str:
    spec = {
        "title": f"{panel.get('title') or panel['name']} · grid {grid['id']}",
        "note": f"{len(grid['options'])} versions rendered in Live",
        "panel": panel["name"],
        "controls": [deck(panel, grid)],
    }
    return "\n".join(
        [
            *lines,
            "Paste this block into your answer as it is:",
            "",
            "```zpkt-surface",
            json.dumps(spec, ensure_ascii=False),
            "```",
            "",
            f"To keep one: hands panel pick {panel['name']} {grid['id']} LETTER",
        ]
    )


def grid(
    client: McpTransport,
    name: str,
    out_dir: Path,
    axes: dict[str, Any],
    *,
    state_values: dict[str, Any] | None = None,
    force: bool = False,
    recorder: Callable[..., str | None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    """Render every combination of the axes' values; return the text to print (a deck of the options)."""
    from hands.live import shape

    panel = load(out_dir, name)
    axes = shape.clean(axes, shape.AXES, "--axes") if isinstance(axes, dict) else axes
    if not isinstance(axes, dict) or not axes:
        raise P.PanelError(
            'give --axes as {"control id": {"from": ..., "to": ..., "steps": 4}} or {"control id": {"values": [...]}}'
        )
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    track = panel["track"]
    if panel.get("kind") != "mix" and track not in state["names"]:
        raise P.PanelError(
            f"the track {track!r} is not in the open set; make the panel again (`hands panel make --replace`)"
        )
    current = dict(panel["values"])
    current.update(M.values_from(panel, state_values))  # what the knobs on the page say now
    cols = [(c, axis_values(client, panel, c, ask)) for c, ask in ((_control(panel, k), v) for k, v in axes.items())]
    combos = list(itertools.product(*[vals for _, vals in cols]))
    if not 2 <= len(combos) <= MAX_OPTIONS:
        raise P.PanelError(
            f"a grid is 2 to {MAX_OPTIONS} versions; this one is {len(combos)} ({' × '.join(str(len(v)) for _, v in cols)})"
        )
    shown = client.run(
        "result = ["
        + ", ".join(f"[str({_where(panel, c)}.str_for_value(v)) for v in {vals!r}]" for c, vals in cols)
        + "]"
    )
    text = [{v: s for v, s in zip(vals, row)} for (_, vals), row in zip(cols, shown)]
    gid = len(panel.get("grids") or []) + 1
    rec = recorder or P._recorder()
    options, files, results = [], [], []
    with hold.undo(
        client, f"the values of panel {name!r} from before its grid", P.set_code(panel, current) + "result = 'ok'"
    ):
        for k, combo in enumerate(combos):
            if progress:
                progress(k, len(combos))
            values = {**current, **{c["param"]: v for (c, _), v in zip(cols, combo)}}
            out = out_dir / f"{name}-g{gid}-{LETTERS[k].lower()}.wav"
            r = _render(client, panel, state, out, values, rec)
            files.append(out)
            results.append(r)
            options.append(
                {
                    "letter": LETTERS[k],
                    "values": {c["param"]: v for (c, _), v in zip(cols, combo)},
                    "label": " · ".join(f"{c['label']} {text[i][v]}" for i, ((c, _), v) in enumerate(zip(cols, combo))),
                    "file": P._shown_path(out),
                    **r,
                }
            )
    for o, m in zip(options, _matched(files, results)):
        if m:
            o["matched"] = m
    g = {"id": gid, "axes": [{"id": c["id"], "label": c["label"]} for c, _ in cols], "options": options}
    panel.setdefault("grids", []).append(g)
    panel["values"] = current
    hold.save_json(P._file(out_dir, name), panel)
    lines = [f"grid {gid} of panel {name}: {len(options)} versions"]
    lines += [
        f"  {o['letter']}  {o['label']}  (peak {o['peak_dbfs']:g} dBFS, RMS {o['rms_dbfs']:g} dBFS)" for o in options
    ]
    same = same_note(options, panel)
    if same and panel.get("kind") != "mix":
        lines += same  # an instrument's versions can measure alike and still sound different (a filter)
    elif same:
        hint = ""
        if panel.get("bars"):
            tracks = [str(c["track"]) for c, _ in cols if c.get("track")]
            bars = panel["bars"]
            quiet = M.quiet_tracks(client, tracks, float(panel.get("offset", 0.0)) + (bars[0] - 1) * 4.0, bars[1] * 4.0)
            later = re.search(r"first plays at bar (\d+)", " ".join(quiet))
            if later:
                hint = (
                    f" {quiet[0].split(':')[0]}. Move the panel there, then run this grid again: hands panel apply {name} --spec "
                    f"'{{\"bars\": [{later.group(1)}, {bars[1]}]}}'"
                )
        raise P.PanelError(
            same[0]
            .removeprefix("warning: ")
            .replace(" Do not offer them; choose bars where that track plays, or another control.", "")
            + hint
        )
    return _print(panel, g, lines)


def same_note(options: list[dict[str, Any]], panel: dict[str, Any]) -> list[str]:
    """A grid whose versions all measure the same changed nothing that plays: say so, rather than let the user
    listen for a difference that is not there."""
    measured = [o.get("rms_dbfs") for o in options]
    rms = [float(r) for r in measured if r is not None]
    if len(rms) < 2 or len(rms) < len(measured) or max(rms) - min(rms) > 0.1:
        return []
    where = f" in bars {panel['bars'][0]}-{panel['bars'][0] + panel['bars'][1] - 1}" if panel.get("bars") else ""
    return [
        f"warning: the versions measure the same (RMS {rms[0]:g} dBFS): the control changes nothing that plays{where}. "
        "Do not offer them; choose bars where that track plays, or another control."
    ]


def pick(client: McpTransport, name: str, out_dir: Path, grid_id: int, letter: str, *, force: bool = False) -> str:
    """Make one option of a grid the panel's values (in Live too); nothing is rendered again."""
    panel = load(out_dir, name)
    g = next((x for x in panel.get("grids") or [] if x["id"] == int(grid_id)), None)
    if g is None:
        raise P.PanelError(
            f"panel {name!r} has no grid {grid_id}; it has: {', '.join(str(x['id']) for x in panel.get('grids') or []) or 'none'}"
        )
    if g.get("swept"):
        raise P.PanelError(
            f"grid {grid_id} of {name!r} was swept (its renders were deleted to save space); make the grid again"
        )
    o = next((x for x in g["options"] if x["letter"] == str(letter).strip().upper()), None)
    if o is None:
        raise P.PanelError(
            f"grid {grid_id} has no option {letter!r}; it has {g['options'][0]['letter']} to {g['options'][-1]['letter']}"
        )
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not changing it; pass --force")
    client.run(P.set_code(panel, o["values"]) + "result = 'ok'")
    before = panel["renders"][-1]
    panel["values"].update(o["values"])
    panel["version"] += 1
    panel["renders"].append(o["file"])
    hold.save_json(P._file(out_dir, name), panel)
    result = {"peak_dbfs": o["peak_dbfs"], "rms_dbfs": o["rms_dbfs"], "seconds": o["seconds"]}
    return f"picked {o['letter']} ({o['label']}) from grid {grid_id}\n" + P.blocks(
        panel, result, [], ab=(before, o["file"])
    )
