"""Mix panels: faders and device knobs on tracks that are already in the set, heard on bars of the arrangement.

    hands panel make --spec '{"name": "buses", "bars": [17, 8], "faders": ["bus-kick", "bus-hats"],
        "devices": [{"track": "bus-kick", "device": "Saturator", "params": {"Drive": "6 dB"}, "controls": ["Drive"]}]}'

Where an instrument panel renders its own riff, a mix panel renders what the arrangement plays in those bars, in
Live, every time: nothing is mixed in the browser. Its values stay in the set (that is the mix); `drop` takes
out only the devices the panel added. The rest (apply, grid, pick, the blocks) is shared with hands.live.panel.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from hands.live import panel as P
from hands.live.agent import with_prelude
from hands.live.transport import McpTransport

BARS_MAX = 64
DEVICE_PREFIX = "mix "


def tr(name: str) -> str:
    """The Live expression for a track by name; Main (or Master) is the master track."""
    if name.strip().lower() in ("main", "master"):
        return "song.master_track"
    return f"next(x for x in list(song.tracks) + list(song.return_tracks) if x.name == {name!r})"


def _dev(track: str, device: str) -> str:
    return f"next(d for d in {tr(track)}.devices if d.name == {device!r})"


def _par(dev_expr: str, name: str) -> str:
    return f"next(p for p in {dev_expr}.parameters if p.name == {name!r})"


def read_params(client: McpTransport, exprs: list[str]) -> list[dict]:
    """Range, value and what Live shows across the range, for each parameter expression."""
    out: list[dict] = []
    for a in range(0, len(exprs), 8):
        rows = client.run(
            "result = [[p.name, p.min, p.max, p.value, bool(p.is_quantized), [str(i) for i in p.value_items] if p.is_quantized else [],\n"
            f"           [str(p.str_for_value(p.min + (p.max - p.min) * k / {P.SAMPLES - 1})) for k in range({P.SAMPLES})]]\n"
            f"          for p in [{', '.join(exprs[a:a + 8])}]]")
        out += [dict(zip(("name", "min", "max", "value", "quantized", "items", "table"), r)) for r in rows]
    return out


_ADD = '''
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
'''


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


def bars_of(spec: dict) -> tuple[int, int]:
    b = spec.get("bars")
    if not (isinstance(b, (list, tuple)) and len(b) == 2 and all(isinstance(x, (int, float)) for x in b)):
        raise P.PanelError('a mix panel needs "bars": [first bar, how many], for example [17, 8]')
    first, count = int(b[0]), int(b[1])
    if first < 1 or not 1 <= count <= BARS_MAX:
        raise P.PanelError(f"bars start at 1 and a render is 1 to {BARS_MAX} bars long (it renders in real time); got {b}")
    return first, count


def song_of(out_dir: Path, name: str) -> dict:
    f = out_dir / f"{name}.song.json"
    if not f.exists():
        raise P.PanelError(f"no song {name!r} in {out_dir}; make it with `hands song make`")
    return json.loads(f.read_text())


def render_bars(client: McpTransport, panel: dict, state: dict, out: Path, recorder: Callable[..., str | None],
                values: dict[str, float] | None = None) -> dict:
    """Set the values, record the panel's bars of the arrangement through Main, cut the take to those bars."""
    tempo = float(panel["tempo"])
    lead = P.lead_beats(tempo)
    start = float(panel.get("offset", 0.0)) + (panel["bars"][0] - 1) * 4.0
    if start < lead:
        raise P.PanelError(f"a render needs {lead:g} beats of run-up before it: start at bar {int(math.ceil(lead / 4)) + 1} or later")
    beats = panel["bars"][1] * 4.0
    out.parent.mkdir(parents=True, exist_ok=True)
    take = out.with_name(f".{out.stem}.take.wav")
    sel = state.get("selected")
    before = P.set_code(panel, values or {}) + (f"song.tempo = {tempo!r}\n" if abs(tempo - state["tempo"]) > 1e-6 else "")
    after = (f"song.tempo = {state['tempo']!r}\nsong.loop = {state['loop']!r}\nsong.start_time = {state['start_time']!r}\n"
             f"song.current_song_time = {state['pos']!r}\n"
             + (f"select_track(song.tracks[{sel}])\n" if sel is not None and sel < len(state["names"]) else ""))
    try:
        path = recorder(transport=client, filename=take.name, output_dir=str(out.parent), start_beat=start - lead,
                        duration_beats=lead + beats, tail_beats=float(panel.get("tail", 0.0)), tempo=tempo,
                        n_tracks=len(state["names"]), armed=state["armed"], before=before, after=after)
        if not path:
            raise P.PanelError("Live recorded nothing; check its audio output (`hands live check`)")
        return P.cut_take(path, out, start, beats + float(panel.get("tail", 0.0)), lead, fade_s=0.005)
    finally:
        for f in (take, Path(f"{take}.timing.json")):
            f.unlink(missing_ok=True)


def make(client: McpTransport, spec: dict, out_dir: Path, *, replace: bool = False, force: bool = False,
         recorder: Callable[..., str | None] | None = None) -> str:
    """Make a mix panel over tracks of the open set and render its bars; return the text to print."""
    name = P._name(spec)
    first, count = bars_of(spec)
    f = P._file(out_dir, name)
    if f.exists() and not replace:
        raise P.PanelError(f"a panel called {name!r} exists: change it with `hands panel apply {name}`, or pass --replace")
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    song = song_of(out_dir, str(spec["song"])) if spec.get("song") else None
    everything = client.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks)]") + ["Main", "Master"]
    faders = [str(t) for t in spec.get("faders") or []]
    pans = [str(t) for t in spec.get("pans") or []]
    devices = [d for d in spec.get("devices") or [] if isinstance(d, dict)]
    for t in [*faders, *pans, *[str(d.get("track")) for d in devices]]:
        if t not in everything:
            near = [n for n in everything if t.lower() in n.lower() or n.lower() in t.lower()][:6]
            raise P.PanelError(f"no track {t!r} in the open set; close names: {', '.join(near) or 'none'}. Tracks: {', '.join(everything[:40])}")
    if not faders and not pans and not devices:
        raise P.PanelError('a mix panel needs something to turn: "faders" (track names), "pans" or "devices"')
    if f.exists():
        drop(client, json.loads(f.read_text()), out_dir)
    added: list[dict] = []
    try:
        picks: list[tuple[str, str, str, str, str]] = []            # key, label, expr, kind, track
        picks += [(f"{t} volume", t, f"{tr(t)}.mixer_device.volume", "fader", t) for t in faders]
        picks += [(f"{t} pan", f"{t} pan", f"{tr(t)}.mixer_device.panning", "knob", t) for t in pans]
        values: dict[str, float] = {}
        exprs: dict[str, str] = {}
        warnings: list[str] = []
        for d in devices:
            track, device = str(d["track"]), str(d.get("device") or "").strip()
            if not device:
                raise P.PanelError('a device needs a "device": an audio effect from Live\'s browser ("Saturator", "EQ Eight", "Glue Compressor")')
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
            for c in d.get("controls") or list(got)[:4]:
                c = c if isinstance(c, dict) else {"param": c}
                pname = P._param(catalog, str(c.get("param") or ""))["name"]
                key = f"{track} {device} {pname}"
                exprs[key] = _par(where, pname)
                picks.append((key, str(c.get("label") or f"{track} {pname}")[:30], exprs[key], "knob", track))
        picks = picks[:P.MAX_CONTROLS]
        rows = read_params(client, [e for _, _, e, _, _ in picks])
        taken: set[str] = set()
        controls = []
        for slot, ((key, label, expr, kind, track), r) in enumerate(zip(picks, rows)):
            c = {"id": P._slug(key, taken), "param": key, "label": label, "track": track, "min": r["min"], "max": r["max"], "midiSlot": slot, "kind": kind}
            if r["quantized"] and r["max"] - r["min"] == 1:
                c["kind"] = "toggle"
            elif r["quantized"]:
                c["step"] = 1
                if r["items"] and len(r["items"]) <= 24:
                    c["display"] = r["items"]
            else:
                c["display"] = r["table"][::(P.SAMPLES - 1) // (P.ANCHORS - 1)]
            controls.append(c)
            exprs[key] = expr
            values.setdefault(key, r["value"])
        panel = {"kind": "mix", "name": name, "title": str(spec.get("title") or name), "track": "", "device": "mix",
                 "bars": [first, count], "offset": float(song["start"]) if song else 0.0, "song": song["name"] if song else None,
                 "tempo": float(song["tempo"] if song else state["tempo"]), "beats": count * 4.0, "tail": 0.0,
                 "controls": controls, "values": values, "exprs": exprs, "added": added, "version": 1, "renders": []}
        out = out_dir / f"{name}.wav"
        result = render_bars(client, panel, state, out, recorder or P._recorder(), values)
    except Exception:
        _remove(client, added)                   # leave nothing behind: the next try starts clean
        raise
    panel["renders"].append(P._shown_path(out))
    f.write_text(json.dumps(panel))
    return P.blocks(panel, result, warnings)


def apply(client: McpTransport, panel: dict, out_dir: Path, *, state_values: dict | None = None, spec: dict | None = None,
          force: bool = False, recorder: Callable[..., str | None] | None = None) -> str:
    """Set a mix panel's values from the page's Surface state, render the next version."""
    state = P._state(client)
    if state["playing"] and not force:
        raise P.PanelError("Live is playing (maybe the user): not rendering; pass --force to stop it")
    values = values_from(panel, state_values)
    if spec and spec.get("bars"):
        panel["bars"] = list(bars_of(spec))
        panel["beats"] = panel["bars"][1] * 4.0
    panel["values"].update(values)
    panel["version"] += 1
    out = out_dir / f"{panel['name']}-{panel['version']}.wav"
    result = render_bars(client, panel, state, out, recorder or P._recorder(), values)
    before = panel["renders"][-1]
    panel["renders"].append(P._shown_path(out))
    P._file(out_dir, panel["name"]).write_text(json.dumps(panel))
    return P.blocks(panel, result, [], ab=(before, panel["renders"][-1]))


def values_from(panel: dict, state_values: dict | None) -> dict[str, float]:
    """Raw values by parameter from the page's Surface state (by control id)."""
    by_id = {c["id"]: c for c in panel["controls"]}
    values: dict[str, float] = {}
    for cid, v in ((state_values or {}).get("values", state_values or {})).items():
        c = by_id.get(cid)
        if c is None or isinstance(v, str):      # a deck's side, or a control this panel does not have
            continue
        values[c["param"]] = (c["max"] if v else c["min"]) if isinstance(v, bool) else max(c["min"], min(c["max"], float(v)))
    return values


def _remove(client: McpTransport, added: list[dict]) -> None:
    for a in added:
        client.run(f"_t = {tr(a['track'])}\n_i = next((i for i, d in enumerate(_t.devices) if d.name == {a['device']!r}), None)\n"
                   "if _i is not None:\n    _t.delete_device(_i)\nresult = 'ok'")


def drop(client: McpTransport, panel: dict, out_dir: Path) -> str:
    """Take out the devices a mix panel added; fader and pan positions stay as they are."""
    _remove(client, panel.get("added") or [])
    P._file(out_dir, panel["name"]).unlink(missing_ok=True)
    n = len(panel.get("added") or [])
    return f"dropped the mix panel {panel['name']!r}" + (f" and the {n} device(s) it added" if n else "") + "; fader positions and renders stay"


def is_mix(spec: Any) -> bool:
    return isinstance(spec, dict) and "bars" in spec and not (spec.get("instrument") or spec.get("sound"))

