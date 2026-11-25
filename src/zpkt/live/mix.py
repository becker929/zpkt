"""Mix panels: faders and device knobs on tracks that are already in the set, heard on bars of the arrangement.

    hands panel make --spec '{"name": "buses", "bars": [17, 8], "faders": ["bus-kick", "bus-hats"],
        "devices": [{"track": "bus-kick", "device": "Saturator", "params": {"Drive": "6 dB"}, "controls": ["Drive"]}]}'

Where an instrument panel renders its own riff, a mix panel renders what the arrangement plays in those bars, in
Live, every time: nothing is mixed in the browser. Its values stay in the set (that is the mix); `drop` takes
out only the devices the panel added. The rest (apply, grid, pick, the blocks) is shared with zpkt.live.panel.
"""

from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zpkt.live import hold
from zpkt.live import panel as P
from zpkt.live.agent import with_prelude
from zpkt.live.inlive import tracks as named_tracks
from zpkt.live.transport import McpTransport

BARS_MAX = 64
DEVICE_PREFIX = "mix "


def tr(name: str) -> str:
    """The Live expression for a track by name; Main (or Master) is the master track, and a return answers to its
    name without Live's letter (zpkt.live.inlive.tracks has the rule)."""
    return named_tracks.track_expr(name)


def _dev(track: str, device: str) -> str:
    return f"next(d for d in {tr(track)}.devices if d.name == {device!r})"


def _par(dev_expr: str, name: str) -> str:
    return f"next(p for p in {dev_expr}.parameters if p.name == {name!r})"


def read_params(client: McpTransport, exprs: list[str]) -> list[dict[str, Any]]:
    """Range, value and what Live shows across the range, for each parameter expression."""
    out: list[dict[str, Any]] = []
    for a in range(0, len(exprs), 8):
        rows = client.run(
            "result = [[p.name, p.min, p.max, p.value, bool(p.is_quantized), [str(i) for i in p.value_items] if p.is_quantized else [],\n"
            f"           [str(p.str_for_value(p.min + (p.max - p.min) * k / {P.SAMPLES - 1})) for k in range({P.SAMPLES})]]\n"
            f"          for p in [{', '.join(exprs[a : a + 8])}]]"
        )
        out += [
            dict(zip(("name", "min", "max", "value", "quantized", "items", "table"), r, strict=False)) for r in rows
        ]
    return out


_ADD = """
def _base(n):
    return n.rsplit(".", 1)[0].lower() if n.lower().endswith((".adv", ".adg")) else n.lower()
def _find(root, name, budget):
    queue = [root]
    while queue:
        node = queue.pop(0)
        for c in node.children:
            budget[0] -= 1
            if budget[0] < 0:
                return None
            if _base(c.name) == name and c.is_loadable:
                return c
            if c.is_folder:
                queue.append(c)
    return None
_t = {track}
_item = _find(browser.audio_effects, {device!r}.lower(), [4000])
if _item is None:
    raise ValueError("no audio effect %r in Live's browser" % {device!r})
_n = len(_t.devices)
select_track(_t)
browser.load_item(_item)
result = _n
"""


# A panel being replaced: its devices are renamed and switched off (parked) while the new one is made, deleted
# when it has rendered, and put back as they were if it fails. The name keeps whether the device was on.
PARKED = (" (parked, on)", " (parked, off)")
_EVERY = "for _t in list(song.tracks) + list(song.return_tracks) + [song.master_track]:\n"
_PARK = (
    _EVERY
    + """    for _d in _t.devices:
        if _d.name in {names!r}:
            _on = _d.parameters[0].value > 0.5
            _d.parameters[0].value = 0
            _d.name = _d.name + (" (parked, on)" if _on else " (parked, off)")
result = 'ok'
"""
)
_UNPARK = (
    _EVERY
    + """    for _d in _t.devices:
        for _k, _s in enumerate((" (parked, on)", " (parked, off)")):
            if _d.name.endswith(_s):
                _d.parameters[0].value = 1 - _k
                _d.name = _d.name[:-len(_s)]
result = 'ok'
"""
)
_DELETE = (
    _EVERY
    + """    for _i in reversed(range(len(_t.devices))):
        if _t.devices[_i].name in {names!r}:
            _t.delete_device(_i)
"""
)
_DELETE_PARKED = (
    _EVERY
    + """    for _i in reversed(range(len(_t.devices))):
        if _t.devices[_i].name.endswith((" (parked, on)", " (parked, off)")):
            _t.delete_device(_i)
result = 'ok'
"""
)


def _add_device(client: McpTransport, track: str, device: str, name: str) -> None:
    """Put an audio effect at the end of a track's chain and give it the panel's name for it."""
    n = client.run(with_prelude(_ADD.format(track=tr(track), device=device)))
    for k in range(12):
        if k:
            time.sleep(0.25)
        got = client.run(f"_d = list({tr(track)}.devices)\nresult = len(_d)")
        if got > n:
            break
    else:
        raise P.PanelError(f"Live did not load {device!r} on {track!r}")
    client.run(f"_d = list({tr(track)}.devices)[-1]\n_d.name = {name!r}\nresult = 'ok'")


def bars_of(spec: dict[str, Any]) -> tuple[int, int]:
    b = spec.get("bars")
    if not (isinstance(b, (list, tuple)) and len(b) == 2 and all(isinstance(x, (int, float)) for x in b)):
        raise P.PanelError('a mix panel needs "bars": [first bar, how many], for example [17, 8]')
    first, count = int(b[0]), int(b[1])
    if first < 1 or not 1 <= count <= BARS_MAX:
        raise P.PanelError(
            f"bars start at 1 and a render is 1 to {BARS_MAX} bars long (it renders in real time); got {b}"
        )
    return first, count


def song_of(out_dir: Path, name: str) -> dict[str, Any]:
    f = out_dir / f"{name}.song.json"
    if not f.exists():
        raise P.PanelError(f"no song {name!r} in {out_dir}; make it with `hands song make`")
    return P.read_file(f, f"song {name!r}")


_OPEN_BUSES = """_fed = set(str(t.output_routing_type.display_name) for t in song.tracks)
_opened = []
for _t in song.tracks:
    if _t.name in _fed and not _t.is_foldable and _t.has_audio_input and _t.current_monitoring_state == 2:
        _t.current_monitoring_state = 0
        _opened.append(_t.name)
result = _opened"""


def open_buses(client: McpTransport) -> list[str]:
    """Turn monitoring to In on audio tracks that other tracks play into (a bus made of an audio track).

    With monitoring Off such a bus passes nothing, so every render through it is silent; HW002's mix set
    was built that way (2026-11-20). Returns the tracks it changed; the change stays in the set."""
    try:
        return list(client.run(_OPEN_BUSES) or [])
    except Exception:  # an older Live API: render anyway, the silence check still speaks up
        return []


_QUIET = """_names = {names!r}
_lo, _hi = {lo!r}, {hi!r}
def _clips(name, seen):
    out = []
    for _t in song.tracks:
        if _t.is_foldable or _t.name in seen:
            continue
        if _t.name == name or str(_t.output_routing_type.display_name) == name:
            seen.add(_t.name)
            out += [(c.start_time, c.end_time) for c in _t.arrangement_clips if not c.muted]
            if _t.name != name:
                out += _clips(_t.name, seen)
    return out
result = {{}}
for _n in _names:
    _c = _clips(_n, set())
    if not any(a < _hi and b > _lo for a, b in _c):
        result[_n] = min([a for a, b in _c if a >= _hi] or [None] if _c else [None])
"""


def quiet_tracks(client: McpTransport, names: list[str], start: float, beats: float) -> list[str]:
    """Warn about the panel's tracks that play nothing in its bars (no clip on them or on what feeds them):
    their faders change nothing there, and a grid of them sounds the same."""
    names = [n for n in dict.fromkeys(names) if n not in ("Main", "Master")]
    try:
        quiet = client.run(_QUIET.format(names=names, lo=start, hi=start + beats)) or {}
    except Exception:
        return []
    out = []
    for n, nxt in quiet.items():
        later = f"; it first plays at bar {int(nxt // 4) + 1}" if isinstance(nxt, (int, float)) else ""
        out.append(f"{n} plays nothing in these bars{later}: its controls change nothing here")
    return out


def opened_note(names: list[str]) -> list[str]:
    return (
        [
            f"turned monitoring to In on {', '.join(names)}: other tracks play into them, and with monitoring Off "
            "they passed no sound"
        ]
        if names
        else []
    )


def render_bars(
    client: McpTransport,
    panel: dict[str, Any],
    state: dict[str, Any],
    out: Path,
    recorder: Callable[..., str | None],
    values: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Set the values, record the panel's bars of the arrangement through Main, cut the take to those bars."""
    tempo = float(panel["tempo"])
    lead = P.lead_beats(tempo)
    start = float(panel.get("offset", 0.0)) + (panel["bars"][0] - 1) * 4.0
    if start < lead:
        raise P.PanelError(
            f"a render needs {lead:g} beats of run-up before it: start at bar {math.ceil(lead / 4) + 1} or later"
        )
    beats = panel["bars"][1] * 4.0
    out.parent.mkdir(parents=True, exist_ok=True)
    take = out.with_name(f".{out.stem}.take.wav")
    sel = state.get("selected")
    opened = open_buses(client)
    before = P.set_code(panel, values or {}) + (
        f"song.tempo = {tempo!r}\n" if abs(tempo - state["tempo"]) > 1e-6 else ""
    )
    after = (
        f"song.tempo = {state['tempo']!r}\nsong.loop = {state['loop']!r}\nsong.start_time = {state['start_time']!r}\n"
        f"song.current_song_time = {state['pos']!r}\n"
        + (f"select_track(song.tracks[{sel}])\n" if sel is not None and sel < len(state["names"]) else "")
    )
    try:
        path = recorder(
            transport=client,
            filename=take.name,
            output_dir=str(out.parent),
            start_beat=start - lead,
            duration_beats=lead + beats,
            tail_beats=float(panel.get("tail", 0.0)),
            tempo=tempo,
            n_tracks=len(state["names"]),
            armed=state["armed"],
            before=before,
            after=after,
        )
        if not path:
            raise P.PanelError("Live recorded nothing; check its audio output (`hands live check`)")
        result = P.cut_take(path, out, start, beats + float(panel.get("tail", 0.0)), lead, fade_s=0.005)
        return {**result, "opened": opened}
    finally:
        for f in (take, Path(f"{take}.timing.json")):
            f.unlink(missing_ok=True)


def make(
    client: McpTransport,
    spec: dict[str, Any],
    out_dir: Path,
    *,
    replace: bool = False,
    force: bool = False,
    recorder: Callable[..., str | None] | None = None,
) -> str:
    """Make a mix panel over tracks of the open set and render its bars; return the text to print."""
    from zpkt.live import shape

    spec = shape.clean(spec, shape.MIX, "the spec")
    name = P._name(spec)
    first, count = bars_of(spec)
    f = P._file(out_dir, name)
    if f.exists() and not replace:
        raise P.PanelError(
            f"a panel called {name!r} exists: change it with `hands panel apply {name}`, or pass --replace"
        )
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    song = song_of(out_dir, str(spec["song"])) if spec.get("song") else None
    faders = [str(t) for t in spec.get("faders") or []]
    pans = [str(t) for t in spec.get("pans") or []]
    devices = [d for d in spec.get("devices") or [] if isinstance(d, dict)]
    tracks = [*faders, *pans, *[str(d.get("track")) for d in devices]]
    _check_tracks(client, tracks, bool(faders or pans or devices))
    start = (float(song["start"]) if song else 0.0) + (first - 1) * 4.0
    quiet = quiet_tracks(client, tracks, start, count * 4.0)
    ours = [f"{DEVICE_PREFIX}{name} {str(d.get('device') or '').strip()}" for d in devices]
    if len({(str(d.get("track")), n) for d, n in zip(devices, ours, strict=True)}) < len(devices):
        raise P.PanelError(
            "a mix panel takes one of each device per track; give each device once and all its params together"
        )
    old_devices = _devices_of_the_panel_replaced(f, name)
    unfinished = hold.note(
        f"the devices of a mix panel that was not finished ({name})", _DELETE.format(names=ours) + _UNPARK
    )
    if old_devices:
        client.run(_PARK.format(names=old_devices))
    try:
        picks: list[Pick] = [(f"{t} volume", t, f"{tr(t)}.mixer_device.volume", "fader", t) for t in faders]
        picks += [(f"{t} pan", f"{t} pan", f"{tr(t)}.mixer_device.panning", "knob", t) for t in pans]
        values: dict[str, float] = {}
        exprs: dict[str, str] = {}
        added, warnings = _add_devices(client, name, devices, picks, values, exprs)
        controls = _controls(client, picks[: P.MAX_CONTROLS], values, exprs)
        panel: dict[str, Any] = {
            "kind": "mix",
            "name": name,
            "title": str(spec.get("title") or name),
            "track": "",
            "device": "mix",
            "bars": [first, count],
            "offset": float(song["start"]) if song else 0.0,
            "song": song["name"] if song else None,
            "tempo": float(song["tempo"] if song else state["tempo"]),
            "beats": count * 4.0,
            "tail": 0.0,
            "controls": controls,
            "values": values,
            "exprs": exprs,
            "added": added,
            "version": 1,
            "renders": [],
        }
        out = out_dir / f"{name}.wav"
        result = render_bars(client, panel, state, out, recorder or P._recorder(), values)
    except BaseException:
        hold.settle(client, unfinished)  # leave nothing behind: the next try starts clean
        raise
    hold.forget(unfinished)
    if old_devices:
        # Best effort: the replaced panel's devices are already switched off, so one left behind changes no sound;
        # the next make or drop of this panel finds and deletes it.
        with contextlib.suppress(Exception):
            client.run(_DELETE_PARKED)
    panel["renders"].append(P._shown_path(out))
    hold.save_json(f, panel)
    return P.blocks(panel, result, warnings + opened_note(result.pop("opened", [])) + quiet)


Pick = tuple[str, str, str, str, str]  # key, label, LOM expression, kind, track


def _check_tracks(client: McpTransport, tracks: list[str], anything: bool) -> None:
    """Every track the spec names is in the open set, and it names something to turn; else PanelError."""
    everything = [
        *client.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks)]"),
        "Main",
        "Master",
    ]
    for t in tracks:
        if t not in everything:
            near = [n for n in everything if t.lower() in n.lower() or n.lower() in t.lower()][:6]
            raise P.PanelError(
                f"no track {t!r} in the open set; close names: {', '.join(near) or 'none'}. Tracks: {', '.join(everything[:40])}"
            )
    if not anything:
        raise P.PanelError('a mix panel needs something to turn: "faders" (track names), "pans" or "devices"')


def _devices_of_the_panel_replaced(f: Path, name: str) -> list[str]:
    """The devices the panel being replaced added. They stay, switched off, until the new one has rendered: a spec
    with a mistake must not cost them."""
    if not f.exists():
        return []
    try:
        return [str(a["device"]) for a in P.read_file(f, f"panel {name!r}").get("added") or []]
    except (P.PanelError, KeyError, TypeError):
        return []  # a damaged file: nothing in it to find in Live


def _add_devices(
    client: McpTransport, name: str, devices: list[dict[str, Any]], picks: list[Pick], values: dict[str, float],
    exprs: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:  # fmt: skip
    """Load each spec device onto its track as "mix NAME DEVICE", set its params, and add its knobs to `picks`.
    Returns the devices added and the warnings about values."""
    added: list[dict[str, Any]] = []
    warnings: list[str] = []
    for d in devices:
        track, device = str(d["track"]), str(d.get("device") or "").strip()
        if not device:
            raise P.PanelError(
                'a device needs a "device": an audio effect from Live\'s browser ("Saturator", "EQ Eight", "Glue Compressor")'
            )
        dname = f"{DEVICE_PREFIX}{name} {device}"
        _add_device(client, track, device, dname)
        added.append({"track": track, "device": dname})
        where = P.Loc(_dev(track, dname))
        catalog = P._catalog(client, where, device)
        got, warn = P.resolve(client, where, catalog, dict(d.get("params") or {}), device)
        warnings += warn
        for pname, v in got.items():
            key = f"{track} {device} {pname}"
            values[key], exprs[key] = v, _par(where, pname)
        for c in d["controls"] if "controls" in d else list(got)[:4]:  # "controls": [] means no knobs for it
            c = c if isinstance(c, dict) else {"param": c}
            pname = P._param(catalog, str(c.get("param") or ""))["name"]
            key = f"{track} {device} {pname}"
            exprs[key] = _par(where, pname)
            picks.append((key, str(c.get("label") or f"{track} {pname}")[:30], exprs[key], "knob", track))
    return added, warnings


def _controls(
    client: McpTransport, picks: list[Pick], values: dict[str, float], exprs: dict[str, str]
) -> list[dict[str, Any]]:
    """One control per pick, with its range and what Live shows across it; values not set yet are read."""
    rows = read_params(client, [e for _, _, e, _, _ in picks])
    taken: set[str] = set()
    controls = []
    for slot, ((key, label, expr, kind, track), r) in enumerate(zip(picks, rows, strict=False)):
        c = {
            "id": P._slug(key, taken),
            "param": key,
            "label": label,
            "track": track,
            "min": r["min"],
            "max": r["max"],
            "midiSlot": slot,
            "kind": kind,
        }
        if r["quantized"] and r["max"] - r["min"] == 1:
            c["kind"] = "toggle"
        elif r["quantized"]:
            c["step"] = 1
            if r["items"] and len(r["items"]) <= 24:
                c["display"] = r["items"]
        else:
            c["display"] = r["table"][:: (P.SAMPLES - 1) // (P.ANCHORS - 1)]
        controls.append(c)
        exprs[key] = expr
        values.setdefault(key, r["value"])
    return controls


def apply(
    client: McpTransport,
    panel: dict[str, Any],
    out_dir: Path,
    *,
    state_values: dict[str, Any] | None = None,
    spec: dict[str, Any] | None = None,
    force: bool = False,
    recorder: Callable[..., str | None] | None = None,
) -> str:
    """Set a mix panel's values from the page's Surface state, render the next version."""
    from zpkt.live import shape

    spec = shape.clean(spec or {}, shape.MIX_CHANGE, "--spec")
    state_values = shape.state(state_values)
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    values = values_from(panel, state_values)
    if spec and isinstance(spec.get("values"), dict):  # by control, as Live shows it: {"bus-kick": "-3 dB"}
        from zpkt.live import versions as V

        for key, want in spec["values"].items():
            c = V._control(panel, key)
            values[c["param"]] = V._raw(client, panel, c, want)
    if spec and spec.get("bars"):
        panel["bars"] = list(bars_of(spec))
        panel["beats"] = panel["bars"][1] * 4.0
    were = {k: panel["values"][k] for k in values if k in panel["values"]}
    panel["values"].update(values)
    panel["version"] += 1
    out = out_dir / f"{panel['name']}-{panel['version']}.wav"
    failed = hold.note(
        f"the values of panel {panel['name']!r} from before a render that failed",
        P.set_code(panel, were) + "result = 'ok'",
    )
    try:
        result = render_bars(client, panel, state, out, recorder or P._recorder(), values)
    except BaseException:
        hold.settle(client, failed)  # the page still shows the old values: Live must too
        raise
    hold.forget(failed)
    before = panel["renders"][-1]
    panel["renders"].append(P._shown_path(out))
    hold.save_json(P._file(out_dir, panel["name"]), panel)
    return P.blocks(panel, result, opened_note(result.pop("opened", [])), ab=(before, panel["renders"][-1]))


def values_from(panel: dict[str, Any], state_values: dict[str, Any] | None) -> dict[str, float]:
    """Raw values by parameter from the page's Surface state (by control id)."""
    from zpkt.live import shape

    by_id = {c["id"]: c for c in panel["controls"]}
    values: dict[str, float] = {}
    for cid, v in shape.state(state_values)["values"].items():
        c = by_id.get(cid)
        if c is None or isinstance(v, str):  # a deck's side, or a control this panel does not have
            continue
        values[c["param"]] = (
            (c["max"] if v else c["min"]) if isinstance(v, bool) else max(c["min"], min(c["max"], float(v)))
        )
    return values


def _remove(client: McpTransport, added: list[dict[str, Any]]) -> None:
    for a in added:
        client.run(
            f"_t = {tr(a['track'])}\n_i = next((i for i, d in enumerate(_t.devices) if d.name == {a['device']!r}), None)\n"
            "if _i is not None:\n    _t.delete_device(_i)\nresult = 'ok'"
        )


def drop(client: McpTransport, panel: dict[str, Any], out_dir: Path) -> str:
    """Take out the devices a mix panel added; fader and pan positions stay as they are."""
    _remove(client, panel.get("added") or [])
    P._file(out_dir, panel["name"]).unlink(missing_ok=True)
    n = len(panel.get("added") or [])
    return (
        f"dropped the mix panel {panel['name']!r}"
        + (f" and the {n} device(s) it added" if n else "")
        + "; fader positions and renders stay"
    )


def is_mix(spec: Any) -> bool:
    return isinstance(spec, dict) and "bars" in spec and not (spec.get("instrument") or spec.get("sound"))
