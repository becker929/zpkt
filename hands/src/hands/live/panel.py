"""Control panels: one instrument on its own track, a riff, a render, and the knobs to play it with.

`make` does in one command what otherwise takes an agent dozens of `hands live exec` calls: add a MIDI
track at the end of the open set, load the instrument, set parameters (by raw value, by "50%", or by the
text Live shows, "800 Hz"), write the riff past the end of the arrangement, render it and print the two
blocks Zpkt web draws (the audio and the control panel). `apply` takes the panel's values as they come
back from the page, sets them and renders the next version with a before/after deck.

The open set is left as it was apart from the panel's own track: the riff's clip, the render track, the
tempo, the loop, the start marker, the position, the selection and the arm states are all put back.
Everything a later `apply` needs is in <out>/<name>.panel.json.
"""

from __future__ import annotations

import contextlib
import difflib
import json
import math
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hands import config
from hands.live import hold
from hands.live.agent import with_prelude
from hands.live.panel_base import (  # noqa: F401  (part of panel's API: mix, versions and song use them as P.*)
    ANCHORS,
    CHUNK,
    FINE,
    LEAD_SECONDS,
    MAX_BEATS,
    MAX_CONTROLS,
    ROUNDS,
    SAMPLES,
    TRACK_PREFIX,
    Loc,
    Note,
    PanelError,
    _device,
    _track,
)
from hands.live.panel_blocks import _num, _shown_path, _slug, blocks, surface  # noqa: F401
from hands.live.panel_render import _render, cut_take, lead_beats, levels, record_span, set_code  # noqa: F401
from hands.live.riff import (  # noqa: F401
    PRESET_CONTROLS,
    PRESETS,
    SOUND_CONTROLS,
    SOUNDS,
    _check_beats,
    expand,
    pitch,
    riff,
    sequence,
)
from hands.live.transport import McpTransport

# ---------------------------------------------------------------------------------------------
# What Live shows for a value, and the value for what it shows

_READING = re.compile(r"^\s*([-+]?(?:inf|\d+(?:\.\d+)?))\s*(.*?)\s*$", re.I)
_SCALE = {"khz": ("hz", 1000.0), "hz": ("hz", 1.0), "s": ("ms", 1000.0), "ms": ("ms", 1.0)}


def reading(text: Any) -> tuple[float, str] | None:
    """A displayed value as a number in its base unit: "1.2 kHz" is (1200.0, "hz"), "250 ms" (250.0, "ms")."""
    m = _READING.match(str(text))
    if not m:
        return None
    base, k = _SCALE.get(m[2].lower(), (m[2].lower(), 1.0))
    return float(m[1]) * k, base


def _between(target: float, xs: list[float], shown: list[str], unit: str) -> list[tuple[float, float, float, float]]:
    """Every pair of neighbouring samples whose readings enclose target: (x0, x1, reading0, reading1).
    Live rounds what it shows, so a reading holds over a stretch of values: the first and last pair bound it."""
    reads = [reading(s) for s in shown]
    out = []
    for (x0, r0), (x1, r1) in zip(zip(xs, reads), zip(xs[1:], reads[1:])):
        if r0 is None or r1 is None or not (math.isfinite(r0[0]) and math.isfinite(r1[0])):
            continue
        if unit and (r0[1] != unit or r1[1] != unit):
            continue
        if min(r0[0], r1[0]) <= target <= max(r0[0], r1[0]):
            out.append((x0, x1, r0[0], r1[0]))
    return out


def _grid(lo: float, hi: float, n: int = SAMPLES) -> list[float]:
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


def _match(want: str, names: list[str]) -> str | None:
    w = want.strip().lower()
    for test in (lambda n: n.lower() == w, lambda n: n.lower().startswith(w), lambda n: w in n.lower()):
        hits = [n for n in names if test(n)]
        if hits:
            return hits[0]
    return None


def _param(catalog: list[dict[str, Any]], name: str) -> dict[str, Any]:
    by = {p["name"]: p for p in catalog}
    hit = by.get(name) or next((p for p in catalog if p["name"].lower() == str(name).strip().lower()), None)
    if hit is None:
        near = difflib.get_close_matches(str(name), list(by), n=6, cutoff=0.4) or _contains(str(name), list(by))
        raise PanelError(
            f"no parameter {name!r}; close names: {', '.join(near) or 'none'} "
            "(`hands panel params NAME --grep WORD` lists them)"
        )
    return hit


def _contains(name: str, names: list[str]) -> list[str]:
    words = [w for w in re.split(r"\W+", name.lower()) if len(w) > 2]
    return [n for n in names if any(w in n.lower() for w in words)][:6]


# ---------------------------------------------------------------------------------------------
# Talking to Live


def read_catalog(client: McpTransport, track: str) -> list[dict[str, Any]]:
    """Every parameter of the panel's instrument: name, range, value, what Live shows, and its choices."""
    count = client.run(f"result = len({_device(track)}.parameters)")
    out: list[dict[str, Any]] = []
    for a in range(0, int(count), CHUNK):
        rows = client.run(
            f"_d = {_device(track)}\n"
            "result = [[p.name, p.min, p.max, p.value, bool(p.is_quantized), p.str_for_value(p.value), "
            f"list(p.value_items) if p.is_quantized else None] for p in list(_d.parameters)[{a}:{a + CHUNK}]]"
        )
        for name, lo, hi, value, quantized, shown, items in rows:
            out.append(
                {
                    "name": name,
                    "min": lo,
                    "max": hi,
                    "value": value,
                    "quantized": quantized,
                    "shown": str(shown),
                    "items": [str(i) for i in items] if items else None,
                }
            )
    return out


def sample(
    client: McpTransport, track: str, asks: list[tuple[str, float, float]], n: int = SAMPLES
) -> dict[str, list[str]]:
    """What Live shows at n even points between lo and hi, for each (parameter, lo, hi)."""
    out: dict[str, list[str]] = {}
    for a in range(0, len(asks), 8):
        part = asks[a : a + 8]
        rows = client.run(
            f"_by = {{p.name: p for p in {_device(track)}.parameters}}\n"
            f"result = [[str(_by[n].str_for_value(lo + (hi - lo) * k / {n - 1})) for k in range({n})] for n, lo, hi in {part!r}]"
        )
        out.update({ask[0]: row for ask, row in zip(part, rows)})
    return out


def resolve(
    client: McpTransport, track: str, catalog: list[dict[str, Any]], wants: dict[str, Any], device: str = ""
) -> tuple[dict[str, float], list[str]]:
    """Raw values for what a spec asks: a number is the raw value, "50%" a point in the range, any other
    text what Live shows ("800 Hz", "Saw D", "On")."""
    values: dict[str, float] = {}
    warnings: list[str] = []
    shown: dict[str, tuple[float, str]] = {}  # continuous parameters asked for by what Live shows
    for key, want in wants.items():
        p = _param(catalog, key)
        lo, hi = p["min"], p["max"]
        if isinstance(want, bool):
            values[p["name"]] = hi if want else lo
        elif isinstance(want, (int, float)):
            values[p["name"]] = max(lo, min(hi, float(want)))
            if not lo <= want <= hi:
                warnings.append(f"{p['name']}: {want:g} is outside {lo:g}..{hi:g}; used {values[p['name']]:g}")
        elif re.fullmatch(r"\s*-?\d+(\.\d+)?\s*%\s*", str(want)) and not (p["shown"] or "").strip().endswith("%"):
            values[p["name"]] = lo + max(0.0, min(1.0, float(str(want).strip().rstrip("% ")) / 100)) * (hi - lo)
        elif p["items"]:
            hit = _match(str(want), p["items"])
            if hit is None:
                raise PanelError(f"{p['name']} has no choice {want!r}; it has: {', '.join(p['items'])}")
            values[p["name"]] = lo + p["items"].index(hit)
        else:
            r = reading(want)
            if r is None:
                raise PanelError(
                    f'{p["name"]}: cannot read {want!r}; give a number, "50%", or text like {p["shown"]!r}'
                )
            shown[p["name"]] = r
    spans = {n: (_param(catalog, n)["min"], _param(catalog, n)["max"]) for n in shown}
    for depth in range(ROUNDS):
        todo = [n for n in shown if n not in values]
        if not todo:
            break
        tables = (
            _tables(client, track, device, todo, catalog)
            if device and not depth
            else sample(client, track, [(n, *spans[n]) for n in todo], SAMPLES if not depth else FINE)
        )
        for n in todo:
            target, unit = shown[n]
            xs, table = _grid(*spans[n], len(tables[n])), tables[n]
            hits = _between(target, xs, table, unit)
            if not hits:
                lo_end, hi_end = reading(table[0]), reading(table[-1])
                asked = f"{target:g} {unit}".strip()
                if (
                    depth
                    or lo_end is None
                    or hi_end is None
                    or (unit and unit not in (lo_end[1], hi_end[1]))
                    or min(lo_end[0], hi_end[0]) <= target <= max(lo_end[0], hi_end[0])
                ):
                    raise PanelError(f"{n}: nothing between {table[0]!r} and {table[-1]!r} reads {asked}")
                first = (target < lo_end[0]) == (lo_end[0] <= hi_end[0])  # which end is the nearer one
                values[n] = xs[0] if first else xs[-1]
                warnings.append(f"{n}: {asked} is outside its range; used {table[0] if first else table[-1]}")
            elif depth == ROUNDS - 1:  # the middle of the stretch that reads as asked
                at = [
                    x0 if r1 == r0 else x0 + (x1 - x0) * (target - r0) / (r1 - r0)
                    for x0, x1, r0, r1 in (hits[0], hits[-1])
                ]
                if hits[0][2] == hits[0][3]:
                    at[0] = hits[0][0]
                if hits[-1][2] == hits[-1][3]:
                    at[1] = hits[-1][1]
                values[n] = (at[0] + at[1]) / 2
            else:
                spans[n] = (hits[0][0], hits[-1][1])
    return values, warnings


def _state(client: McpTransport) -> dict[str, Any]:
    state = client.run(
        "_sel = song.view.selected_track\n"
        "_leaf = [t for t in song.tracks if not t.is_foldable]\n"
        "result = {'playing': bool(song.is_playing), 'names': [t.name for t in song.tracks], 'tempo': song.tempo,\n"
        "          'end': max([c.end_time for t in _leaf for c in t.arrangement_clips] + [0.0]),\n"
        "          'armed': [i for i, t in enumerate(song.tracks) if t.can_be_armed and t.arm],\n"
        "          'selected': next((i for i, t in enumerate(song.tracks) if t == _sel), None),\n"
        "          'loop': bool(song.loop), 'start_time': song.start_time, 'pos': song.current_song_time,\n"
        "          'set': str(getattr(song, 'file_path', '') or '')}"
    )
    if not isinstance(state, dict) or not isinstance(state.get("names"), list):
        from hands.live.transport import LiveError

        raise LiveError(
            f"Live answered something that is not the set's state ({str(state)[:80]}); run `hands rig reset`"
        )
    hold.on_set(state.get("set"))
    return state


_LOAD = """
_t = song.tracks[{idx}]
_t.name = {track!r}
def _base(n):
    return n.rsplit(".", 1)[0].lower() if n.lower().endswith((".adv", ".adg", ".aupreset", ".vstpreset")) else n.lower()
def _find(root, name, budget):
    queue = [root]
    while queue:
        node = queue.pop(0)
        for c in node.children:
            budget[0] -= 1
            if budget[0] < 0:
                return None
            if _base(c.name) == name:
                return c
            if c.is_folder:
                queue.append(c)
    return None
_item = None
for _root in (browser.instruments, browser.plugins, browser.sounds, browser.drums):
    _node = _root
    for _part in {parts!r}:
        _node = _find(_node, _part, [3000])
        if _node is None:
            break
    if _node is not None and _node.is_loadable:
        _item = _node
        break
if _item is None:
    raise ValueError("no loadable %r in Live's browser (instruments, plug-ins, sounds, drums)" % {instrument!r})
select_track(_t)
browser.load_item(_item)
for _i, _x in enumerate(song.tracks):
    if _x.can_be_armed and _x.arm != (_i in {armed!r}):
        _x.arm = _i in {armed!r}
result = _item.name
"""


def _load(client: McpTransport, track: str, instrument: str, state: dict[str, Any]) -> str:
    """Add the panel's track at the end and load the instrument on it; return the device's name."""
    idx = len(state["names"])
    parts = [p.strip().lower() for p in instrument.split("/") if p.strip()]
    # One call: every round trip to Live waits for its next tick, close to a second when Live is in the background.
    client.run(
        with_prelude(
            "song.create_midi_track(-1)\n"
            + _LOAD.format(idx=idx, track=track, parts=parts, instrument=instrument, armed=state["armed"])
        )
    )
    for _ in range(12):  # a plug-in can take a few seconds to appear
        time.sleep(0.2)
        devices = client.run(f"result = [d.name for d in {_track(track)}.devices]")
        if devices:
            return devices[0]
    raise PanelError(f"{instrument!r} did not load onto the track")


def _drop_code(track: str) -> str:
    return (
        f"_i = next((i for i, t in enumerate(song.tracks) if t.name == {track!r}), None)\n"
        "if _i is not None:\n    song.delete_track(_i)\nresult = 'ok'"
    )


ASIDE = " (being replaced)"


def _rename_code(old: str, new: str) -> str:
    return (
        f"_t = next((t for t in song.tracks if t.name == {old!r}), None)\n"
        f"if _t is not None:\n    _t.name = {new!r}\nresult = 'ok'"
    )


def _drop(client: McpTransport, track: str) -> None:
    client.run(_drop_code(track))


def read_file(f: Path, what: str) -> dict[str, Any]:
    """A panel's or a song's file as hands wrote it. A file that is cut short or is not one of ours is an error
    the caller can act on, not a crash."""
    try:
        made = json.loads(f.read_text())
    except (OSError, ValueError) as exc:
        raise PanelError(
            f"the file of {what} cannot be read ({f.name}: {str(exc)[:80]}); make it again (--replace)"
        ) from exc
    if not isinstance(made, dict):
        raise PanelError(f"the file of {what} is not one hands wrote ({f.name}); make it again (--replace)")
    return made


# ---------------------------------------------------------------------------------------------
# The control panel's knobs, read from Live


def controls_for(
    client: McpTransport, track: str, catalog: list[dict[str, Any]], wanted: list[Any], device: str = ""
) -> list[dict[str, Any]]:
    """One control per wanted parameter (a name, or {"param", "label"}), with what Live shows across its range."""
    picks = []
    for w in wanted[:MAX_CONTROLS]:
        w = w if isinstance(w, dict) else {"param": w}
        p = _param(catalog, str(w.get("param") or ""))
        picks.append((p, str(w.get("label") or p["name"])[:30]))
    smooth = [p for p, _ in picks if not p["quantized"]]
    names = [p["name"] for p in smooth]
    tables = (
        {}
        if not names
        else _tables(client, track, device, names, catalog)
        if device
        else sample(client, track, [(p["name"], p["min"], p["max"]) for p in smooth])
    )
    taken: set[str] = set()
    out = []
    for slot, (p, label) in enumerate(picks):
        c = {
            "id": _slug(p["name"], taken),
            "param": p["name"],
            "label": label,
            "min": p["min"],
            "max": p["max"],
            "midiSlot": slot,
        }
        if p["quantized"] and p["max"] - p["min"] == 1:
            c["kind"] = "toggle"
        else:
            c["kind"] = "knob"
            if p["quantized"]:
                c["step"] = 1
                if p["items"] and len(p["items"]) <= 24:
                    c["display"] = p["items"]
            else:
                c["display"] = tables[p["name"]][:: (SAMPLES - 1) // (ANCHORS - 1)]
        out.append(c)
    return out


# ---------------------------------------------------------------------------------------------
# The commands


def _cache_file(device: str) -> Path:
    return config.rig().data_dir / "panel-params" / (re.sub(r"[^\w.-]+", "_", device) + ".json")


def _remember(device: str, catalog: list[dict[str, Any]]) -> None:
    f = _cache_file(device)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(catalog))


def _file(out_dir: Path, name: str) -> Path:
    return out_dir / f"{name}.panel.json"


def _name(spec: dict[str, Any]) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", str(spec.get("name") or "").lower()).strip("-")[:40]
    if not name:
        raise PanelError('the spec needs a "name" (letters, digits, dashes)')
    return name


def _recorder() -> Callable[..., str | None]:
    return record_span


def _catalog(client: McpTransport, track: str, device: str) -> list[dict[str, Any]]:
    """The device's parameters, from the cache when it has been read before (a read is six round trips)."""
    cache = _cache_file(device)
    if cache.exists():
        try:
            kept = json.loads(cache.read_text())
            if isinstance(kept, list) and kept and all(isinstance(p, dict) and "name" in p for p in kept):
                return kept
        except (OSError, ValueError):
            pass  # a damaged copy: read the device again
    catalog = read_catalog(client, track)
    _remember(device, catalog)
    return catalog


def _tables(
    client: McpTransport, track: str, device: str, names: list[str], catalog: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """What Live shows across each parameter's whole range; read once per device and parameter, then kept."""
    f = _cache_file(device).with_suffix(".shown.json")
    have = json.loads(f.read_text()) if f.exists() else {}
    missing = [n for n in names if n not in have]
    if missing:
        have.update(sample(client, track, [(n, _param(catalog, n)["min"], _param(catalog, n)["max"]) for n in missing]))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(have))
    return {n: have[n] for n in names}


def make(
    client: McpTransport,
    spec: dict[str, Any],
    out_dir: Path,
    *,
    replace: bool = False,
    force: bool = False,
    recorder: Callable[..., str | None] | None = None,
) -> str:
    """Make a panel from a spec and render it; return the text to print."""
    from hands.live import shape

    spec = expand(shape.clean(spec, shape.INSTRUMENT, "the spec"), new=True)
    state = _state(client)
    if not spec.get("name"):  # named after what it is; a second one of the same gets a number
        base = re.sub(
            r"[^a-z0-9]+",
            "-",
            f"{spec.get('sound') or spec.get('instrument') or 'panel'} {spec.get('seq') or spec.get('chords') or ''}".lower(),
        ).strip("-")[:32]
        name, k = base, 2
        while TRACK_PREFIX + name in state["names"] or _file(out_dir, name).exists():
            name, k = f"{base}-{k}", k + 1
        spec = {**spec, "name": name}
    name = _name(spec)
    instrument = str(spec.get("instrument") or "").strip()
    if not instrument:
        raise PanelError(
            'the spec needs an "instrument": a name from Live\'s browser ("Operator", "Operator/Acid Bass", "Serum 2")'
        )
    notes, beats = riff(spec)
    track = TRACK_PREFIX + name
    if state["playing"] and not force:
        raise PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    aside = None
    if track in state["names"]:
        if not replace:
            raise PanelError(
                f"a panel called {name!r} exists: change it with `hands panel apply {name}`, or pass --replace"
            )
        aside = track + ASIDE  # the old one stays until the new one has rendered: a spec with a
        client.run(_rename_code(track, aside))  # mistake in it must not cost the panel it was to replace
        state = _state(client)
    unfinished = hold.note(
        f"the track {track!r} of a panel that was not finished",
        _drop_code(track) + ("\n" + _rename_code(aside, track) if aside else ""),
    )
    device = instrument
    try:
        device = _load(client, track, instrument, state)
        catalog = _catalog(client, track, device)
        wants = spec.get("params") or {}
        if not isinstance(wants, dict):
            raise PanelError('"params" is {name: value}, for example {"Filter Freq": "600 Hz"}')
        values, warnings = resolve(client, track, catalog, wants, device)
        wanted = spec.get("controls") or list(values)[:8] or [p["name"] for p in catalog[1:9]]
        controls = controls_for(client, track, catalog, wanted, device)
        panel: dict[str, Any] = {
            "name": name,
            "title": str(spec.get("title") or name),
            "track": track,
            "instrument": instrument,
            "device": device,
            "tempo": float(spec.get("tempo") or state["tempo"]),
            "beats": beats,
            "tail": float(spec.get("tail", 2.0)),
            "notes": notes,
            "controls": controls,
            "version": 1,
            "renders": [],
            "values": {**{c["param"]: _param(catalog, c["param"])["value"] for c in controls}, **values},
        }
        out = out_dir / f"{name}.wav"
        state = {**state, "names": [*state["names"], track]}
        result = _render(
            client, track, state, notes, beats, panel["tail"], panel["tempo"], out, recorder or _recorder(), values
        )
    except BaseException as exc:
        hold.settle(client, unfinished)  # leave nothing behind: the next try starts clean
        if "KeyError" in str(exc):  # the kept parameter list no longer fits the device: read it afresh next time
            for stale in (_cache_file(device), _cache_file(device).with_suffix(".shown.json")):
                stale.unlink(missing_ok=True)
        raise
    hold.forget(unfinished)
    if aside:
        with contextlib.suppress(Exception):  # the new panel is made; a leftover old track is only clutter
            _drop(client, aside)
    panel["renders"].append(_shown_path(out))
    hold.save_json(_file(out_dir, name), panel)
    return blocks(panel, result, warnings)


def apply(
    client: McpTransport,
    name: str,
    out_dir: Path,
    *,
    state_values: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
    force: bool = False,
    recorder: Callable[..., str | None] | None = None,
) -> str:
    """Set a panel's values (from the page's Surface state, and/or a spec's changes) and render the next version."""
    f = _file(out_dir, name)
    if not f.exists():
        raise PanelError(f"no panel {name!r} in {out_dir} (expected {f.name}); make it with `hands panel make`")
    from hands.live import shape

    panel = read_file(f, f"panel {name!r}")
    spec = expand(shape.clean(spec or {}, shape.INSTRUMENT_CHANGE, "--spec"), new=False)
    state_values = shape.state(state_values)
    track = panel["track"]
    state = _state(client)
    if state["playing"] and not force:
        raise PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    if track not in state["names"]:
        raise PanelError(
            f"the track {track!r} is not in the open set; make the panel again (`hands panel make --replace`)"
        )
    device = panel["device"]
    catalog = _catalog(client, track, device)
    by_id = {c["id"]: c for c in panel["controls"]}
    values: dict[str, float] = {}
    for cid, v in ((state_values or {}).get("values", state_values or {})).items():
        c = by_id.get(cid)
        if c is None or isinstance(v, str):  # the deck's side, or a control this panel does not have
            continue
        values[c["param"]] = (
            (c["max"] if v else c["min"]) if isinstance(v, bool) else max(c["min"], min(c["max"], float(v)))
        )
    asked, warnings = resolve(client, track, catalog, dict(spec.get("params") or {}), device)
    values.update(asked)
    if spec.get("controls"):
        panel["controls"] = controls_for(client, track, catalog, spec["controls"], device)
        for c in panel["controls"]:
            panel["values"].setdefault(c["param"], _param(catalog, c["param"])["value"])
    if spec.get("notes") or spec.get("chords") or spec.get("seq"):
        panel["notes"], panel["beats"] = riff(spec)
    elif spec.get("beats"):
        raise PanelError("to change the length, give the notes again (seq, notes or chords) with beats")
    for key in ("tempo", "tail"):
        if spec.get(key) is not None:
            panel[key] = float(spec[key])
    if spec.get("title"):
        panel["title"] = str(spec["title"])
    were = {k: panel["values"][k] for k in values if k in panel["values"]}
    panel["values"].update(values)
    panel["version"] += 1
    out = out_dir / f"{name}-{panel['version']}.wav"
    notes = [tuple(n) for n in panel["notes"]]
    failed = hold.note(
        f"the values of panel {name!r} from before a render that failed", set_code(panel, were) + "result = 'ok'"
    )
    try:
        result = _render(
            client,
            track,
            state,
            notes,
            panel["beats"],
            panel["tail"],
            panel["tempo"],
            out,
            recorder or _recorder(),
            values,
        )
    except BaseException:
        hold.settle(client, failed)  # the page still shows the old values: Live must too
        raise
    hold.forget(failed)
    before = panel["renders"][-1]
    panel["renders"].append(_shown_path(out))
    hold.save_json(f, panel)
    return blocks(panel, result, warnings, ab=(before, panel["renders"][-1]))


def drop(client: McpTransport, name: str, out_dir: Path) -> str:
    """Delete a panel's track from the open set; its renders stay."""
    track = TRACK_PREFIX + name
    names = client.run("result = [t.name for t in song.tracks]")
    if track not in names:
        return f"no track {track!r} in the open set"
    _drop(client, track)
    _file(out_dir, name).unlink(missing_ok=True)
    return f"deleted the track {track!r}; the renders stay"


def params(client: McpTransport | None, instrument: str, grep: str = "") -> str:
    """A device's parameters, one per line: name | range | value = what Live shows | choices. Read from the
    cache when the device has been loaded before; otherwise loaded on a temporary track, read, and removed."""
    cache = _cache_file(instrument)
    catalog = None
    if cache.exists():
        try:
            catalog = json.loads(cache.read_text())
        except (OSError, ValueError):
            catalog = None
    if not (isinstance(catalog, list) and catalog and all(isinstance(p, dict) and "name" in p for p in catalog)):
        if client is None:
            raise PanelError(f"{instrument!r} has not been read yet and Live is not reachable")
        state = _state(client)
        track = TRACK_PREFIX + "params (temporary)"
        with hold.undo(client, "the temporary track that reads a device's parameters", _drop_code(track)):
            try:
                device = _load(client, track, instrument, state)
            except Exception as exc:
                if "no loadable" not in str(exc):
                    raise
                from hands.live import (
                    mix,
                )  # not an instrument: an audio effect ("EQ Eight", "Saturator"), for a mix panel's devices

                try:
                    mix._add_device(client, track, instrument, instrument)
                except Exception:
                    raise PanelError(
                        f"no instrument or audio effect called {instrument!r} in Live's browser; give the name as the "
                        'browser shows it ("Operator", "EQ Eight", "Saturator", "Glue Compressor", "Compressor", "Reverb")'
                    ) from None
                device = instrument
            catalog = read_catalog(client, track)
        _remember(device, catalog)
        if device != instrument:
            _remember(instrument, catalog)
    try:
        rx = re.compile(grep, re.I) if grep else None
    except re.error as exc:
        raise PanelError(f"--grep is not a regular expression: {exc}") from exc
    rows = []
    for p in catalog:
        if rx and not rx.search(p["name"]):
            continue
        row = f"{p['name']} | {p['min']:g}..{p['max']:g} | {p['value']:.4g} = {p['shown']}"
        if p["items"]:
            row += " | " + ", ".join(p["items"][:32])
        rows.append(row)
    head = (
        f"{instrument}: {len(rows)} of {len(catalog)} parameters (name | range | default = shown | choices). "
        'In a spec, a number is the raw value; text is what Live shows ("800 Hz", "50%", a choice).'
    )
    return "\n".join([head, *rows])
