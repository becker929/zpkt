"""The mix state of the open set as data: take it, compare it, put it back. The one model of "the whole mix at a
moment" in zpkt: the mix desk's checkpoints are these files, and its history uses these keys.

    hands live state take NAME            # every mixer and device value -> sets_dir/state/<set>/NAME.json
    hands live state diff NAME [OTHER]    # NAME against Live now (or against OTHER); only what differs
    hands live state put NAME [--only T]  # NAME's raw values back into Live, read back, exit 1 on a mismatch
    hands live state ls                   # the states kept for the front set

A state (State) holds, for every track, return and Main: volume, pan, sends (by return name), mute and solo, and every
device's parameters (in chain order). Each value is a ShownRaw pair, as Live shows it and its raw value; `put` writes
the raw value, which round-trips exactly on the same Live version. Reading is one LOM call per 8 tracks (about 3 s for
a 33-track set); writing is one device and at most 16 parameters per call (zpkt.live.writes).

NAME may also be a path to a state file, or to a mix desk recipe: JSON whose "desk" key (or top level) is the desk
contract (zpkt.live.desk), read as a partial state.
"""

from __future__ import annotations

import ast
import json
import math
import time
from pathlib import Path
from typing import Any, TypedDict

from zpkt.live import config, writes
from zpkt.live import desk as desk_contract
from zpkt.live.inlive import keys
from zpkt.live.inlive import tracks as named_tracks
from zpkt.live.transport import McpTransport

READ_CHUNK = 8  # tracks per read call: one call per track cost about 0.4 s each in round trips
WRITE_CHUNK = writes.WRITE_CHUNK


class ShownRaw(list[Any]):
    """[what Live shows, the raw value], e.g. ["-6.0 dB", 0.7]. A list, so it is a JSON array and equals one."""

    @classmethod
    def of(cls, shown: str, raw: Any) -> ShownRaw:
        return cls([shown, raw])

    @property
    def shown(self) -> str:
        return str(self[0])

    @property
    def raw(self) -> Any:
        return self[1]


class MixerState(TypedDict, total=False):
    volume: ShownRaw
    pan: ShownRaw
    sends: dict[str, ShownRaw]  # by return name, with or without Live's letter
    mute: ShownRaw  # tracks and returns only
    solo: ShownRaw


DeviceState = TypedDict("DeviceState", {"name": str, "class": str | None, "params": dict[str, ShownRaw]})


class TrackState(TypedDict):
    mixer: MixerState
    devices: list[DeviceState]


class State(TypedDict, total=False):
    set: str  # the set it was taken from (written by save)
    at: str  # when, "YYYY-MM-DD HH:MM:SS"
    returns: list[str]  # the returns' names as Live shows them ("A-Space")
    tracks: dict[str, TrackState]  # by track name; returns by their Live name; "Main"
    partial: bool  # holds only some values (a desk recipe): compared on its own keys alone
    name: str  # what a person calls it ("before the glue"); the file's name says where it is, not this
    made_by: str  # who took it: you, minilab, agent or sys (zpkt.live.changes.Who)


Row = tuple[str, str | None, str | None]  # a difference: (key, shown in A, shown in B); None where absent

_READ_MANY = """rets = [r.name for r in song.return_tracks]
by = {{}}
for t in list(song.tracks) + list(song.return_tracks):
    by.setdefault(t.name, t)
def _one(t, is_track):
    m = t.mixer_device
    mix = {{'volume': [str(m.volume), m.volume.value], 'pan': [str(m.panning), m.panning.value],
           'sends': {{rets[k]: [str(s), s.value] for k, s in enumerate(m.sends)}}}}
    if is_track:
        mix['mute'] = [str(bool(t.mute)), bool(t.mute)]
        mix['solo'] = [str(bool(t.solo)), bool(t.solo)]
    devs = [{{'name': d.name, 'class': d.class_name,
             'params': {{p.name: [str(p), p.value] for p in d.parameters}}}} for d in t.devices]
    return {{'mixer': mix, 'devices': devs}}
result = {{n: _one(song.master_track if n == 'Main' else by[n], n != 'Main') for n in {names!r}}}"""


def track_expr(name: str) -> str:
    """The LOM expression for a track, return or Main by name (zpkt.live.inlive.tracks has the rule)."""
    return named_tracks.track_expr(name)


def short(name: str, returns: list[str]) -> str:
    """A return's name without the letter Live puts in front ("A-Space" -> "Space"); other names as they are."""
    return named_tracks.short_name(name, name in returns)


def take(client: McpTransport, only: list[str] | None = None) -> State:
    """Every mixer and device value of the open set (or of the tracks in `only`, by name or short name)."""
    names = client.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks)] + ['Main']")
    rets = client.run("result = [r.name for r in song.return_tracks]")
    if only:
        names = [n for n in names if n in only or short(n, rets) in only]
    tracks: dict[str, TrackState] = {}
    for i in range(0, len(names), READ_CHUNK):
        part = client.run(_READ_MANY.format(names=names[i : i + READ_CHUNK]))
        for n in names[i : i + READ_CHUNK]:
            tracks[n] = _track_state(part[n])
    return {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "returns": rets, "tracks": tracks}


# --- parsing: values from the bridge or a file become ShownRaw pairs --------------------------------------------


def _raw(v: Any) -> Any:
    """The bridge sends values deep in a reply as text ("1.0", "True"): back to numbers and booleans."""
    if isinstance(v, str):
        if v in ("True", "False"):
            return v == "True"
        try:
            return float(v)
        except ValueError:
            return v
    return v


def _pair(v: Any) -> ShownRaw:
    """[shown, raw] as the bridge may send it: a list, or (deep in a reply) the list's repr as text."""
    if isinstance(v, str) and v.startswith("["):
        v = ast.literal_eval(v)
    return ShownRaw.of(v[0], _raw(v[1]))


def _track_state(body: dict[str, Any]) -> TrackState:
    """A track's state with every value a ShownRaw pair (changes `body` in place and returns it)."""
    mix = body["mixer"]
    for k in keys.MIXER:
        if k in mix:
            mix[k] = _pair(mix[k])
    mix["sends"] = {r: _pair(v) for r, v in mix.get("sends", {}).items()}
    for d in body["devices"]:
        d["params"] = {p: _pair(v) for p, v in d["params"].items()}
    return body  # type: ignore[return-value]  # now in TrackState's shape


# --- comparing ---------------------------------------------------------------------------------------------------


def _num(v: Any) -> float:
    return float(v) if not isinstance(v, bool) else float(int(v))


def _same(a: list[Any] | None, b: list[Any] | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(_num(a[1]), _num(b[1]), abs_tol=tol)


def flatten(state: State) -> dict[str, ShownRaw]:
    """Every value under its state key (zpkt.live.inlive.keys): {"Kick bus/volume": [shown, raw],
    "Kick bus/send Space": [...], "Kick bus/desk EQ/1 Gain A": [...]}, for comparing."""
    out: dict[str, ShownRaw] = {}
    rets = state.get("returns", [])
    for name, body in state["tracks"].items():
        t = short(name, rets)
        mix = body["mixer"]
        for k in keys.MIXER:
            if k in mix:
                out[keys.mixer_key(t, k)] = mix[k]  # type: ignore[literal-required]
        for r, v in mix.get("sends", {}).items():
            out[keys.send_key(t, short(r, rets))] = v
        seen: dict[str, int] = {}
        for d in body["devices"]:
            seen[d["name"]] = seen.get(d["name"], 0) + 1
            label = keys.device_label(d["name"], seen[d["name"]])
            for p, v in d["params"].items():
                out[keys.device_key(t, label, p)] = v
    return out


def diff(a: State, b: State, ignore: tuple[str, ...] = ()) -> list[Row]:
    """(key, shown in a, shown in b) for every value that differs or exists on one side only. A state marked
    "partial" (a recipe holds only some devices) is compared on its own keys alone."""
    fa, fb = flatten(a), flatten(b)
    names = sorted(set(fa) if a.get("partial") else set(fa) | set(fb))
    return [
        (k, fa[k][0] if k in fa else None, fb[k][0] if k in fb else None)
        for k in names
        if not k.startswith(ignore) and not _same(fa.get(k), fb.get(k))
    ]


def summarize(rows: list[Row], limit: int = 60) -> str:
    """Short text: identical runs collapse ("mon C1/* only in A (5 values)") so a diff stays a few lines."""
    if not rows:
        return "same"
    lines: list[str] = []
    one_sided: dict[tuple[str, str], int] = {}
    for k, x, y in rows:
        if x is None or y is None:
            side = "A" if y is None else "B"
            key = (k.split("/")[0], side)
            one_sided[key] = one_sided.get(key, 0) + 1
        else:
            lines.append(f"{k}: {x} -> {y}")
    for (t, side), n in sorted(one_sided.items()):
        lines.append(f"{t}/* only in {side} ({n} values)")
    more = len(lines) - limit
    return "\n".join(lines[:limit] + ([f"... {more} more"] if more > 0 else []))


# --- putting back ------------------------------------------------------------------------------------------------


def _mixer_lines(t: str, mix: MixerState, live: dict[str, ShownRaw], rets: list[str], srets: list[str]) -> list[str]:
    """The LOM statements that set the mixer values of `mix` that differ from Live (`t` and `m` in scope)."""
    lines = []
    for key, attr in (("volume", "m.volume.value"), ("pan", "m.panning.value")):
        if key in mix and not _same(mix[key], live.get(keys.mixer_key(t, key))):  # type: ignore[literal-required]
            lines.append(f"{attr} = {mix[key][1]!r}")  # type: ignore[literal-required]
    sends = {short(r, srets): v for r, v in mix.get("sends", {}).items()}
    for k, r in enumerate(rets):
        v = sends.get(short(r, rets))
        if v is not None and not _same(v, live.get(keys.send_key(t, short(r, rets)))):
            lines.append(f"m.sends[{k}].value = {v[1]!r}")
    if t != "Main":
        for flag in ("mute", "solo"):
            if flag in mix and not _same(mix[flag], live.get(keys.mixer_key(t, flag))):
                lines.append(f"t.{flag} = {bool(mix[flag][1])!r}")
    return lines


def _put_track(
    client: McpTransport, t: str, body: TrackState, have: list[str], live: dict[str, ShownRaw], rets: list[str],
    srets: list[str],
) -> tuple[bool, list[Row]]:  # fmt: skip
    """Write one track's devices and mixer where they differ from Live; (wrote anything, what the set lacks)."""
    expr, missing, wrote = track_expr(t), [], False
    seen: dict[str, int] = {}
    for d in body["devices"]:
        seen[d["name"]] = seen.get(d["name"], 0) + 1
        k = seen[d["name"]]
        idxs = [i for i, x in enumerate(have) if x == d["name"]]
        if k > len(idxs):
            missing.append((f"{t}/{d['name']}", "device", None))
            continue
        label = keys.device_label(d["name"], k)
        items = [(p, v[1]) for p, v in d["params"].items() if not _same(v, live.get(keys.device_key(t, label, p)))]
        if items:
            writes.set_raw(client, f"{expr}.devices[{idxs[k - 1]}]", items)
            wrote = True
    lines = _mixer_lines(t, body["mixer"], live, rets, srets)
    if lines:
        client.run("\n".join([f"t = {expr}", "m = t.mixer_device", *lines, "result = 'ok'"]))
        wrote = True
    return wrote, missing  # type: ignore[return-value]


def put(client: McpTransport, state: State, only: list[str] | None = None) -> list[Row]:
    """Write `state` into Live (tracks in `only`, or all of them), then read back; return what still differs.
    Only values that differ from Live are written, so a near-identical state goes back in seconds. Tracks or
    devices the set lacks are reported, never created."""
    before = take(client)
    rets = before["returns"]
    by_short = {short(n, rets): n for n in before["tracks"]}
    live = flatten(before)
    srets = state.get("returns", [])
    missing: list[Row] = []
    names = [n for n in state["tracks"] if not only or n in only or short(n, srets) in only]
    touched: list[str] = []
    for n in names:
        t = short(n, srets)
        if t not in by_short:
            missing.append((f"{t}/*", "track", None))
            continue
        have = [d["name"] for d in before["tracks"][by_short[t]]["devices"]]
        wrote, lacks = _put_track(client, t, state["tracks"][n], have, live, rets, srets)
        missing += lacks
        if wrote:
            touched.append(by_short[t])
    now = before
    if touched:
        again = take(client, only=touched)
        now = {**before, "tracks": {**before["tracks"], **again["tracks"]}}
    want: State = {**state, "tracks": {n: state["tracks"][n] for n in names if short(n, srets) in by_short}}
    if not state.get("partial"):
        want["partial"] = True  # Live's tracks outside `names` are not ours to judge here
    return missing + diff(want, now)


# --- files -------------------------------------------------------------------------------------------------------


def folder(set_name: str) -> Path:
    return config.rig().sets_dir / "state" / set_name


def path_for(set_name: str, name: str) -> Path:
    p = Path(name).expanduser()
    if p.suffix == ".json" and (p.exists() or "/" in name):
        return p
    return folder(set_name) / (name if p.suffix == ".json" else f"{name}.json")


def save(state: State, path: Path, set_name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"set": set_name, **state}
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)
    return path


def _device(d: desk_contract.DeskDevice) -> DeviceState:
    return {"name": d.name, "class": d.class_, "params": {p: ShownRaw(v) for p, v in d.values.items()}}


def from_desk(data: Any) -> State:
    """A mix desk recipe's "desk" (returns, desk chains, mixer, owned switches) as a partial state. The desk is
    checked against its contract (zpkt.live.desk) first."""
    desk = desk_contract.parse(data)
    tracks: dict[str, TrackState] = {}

    def track(name: str) -> TrackState:
        return tracks.setdefault(name, {"mixer": {}, "devices": []})

    for name, m in desk.mixer.items():
        mix: MixerState = {
            "volume": ShownRaw(m.volume),
            "pan": ShownRaw(m.pan),
            "sends": {r: ShownRaw(v) for r, v in m.sends.items()},
        }
        if m.mute is not None:
            mix["mute"] = ShownRaw.of(str(m.mute), m.mute)
        tracks[name] = {"mixer": mix, "devices": []}
    for r in desk.returns:
        track(r.name)["devices"] = [_device(d) for d in r.devices]
    for name, chain in desk.chains.items():
        track(name)["devices"] += [_device(d) for d in chain]
    for o in desk.owned:
        track(o.track)["devices"].append(
            {"name": o.device, "class": None, "params": {p: ShownRaw(v) for p, v in o.values.items()}}
        )
    return {"tracks": tracks, "partial": True}


def load_dict(data: dict[str, Any]) -> State:
    """A state, or a dict holding a mix desk "desk" (the arrangement recipe, or the desk part alone), as a state."""
    if "tracks" in data:
        data["tracks"] = {n: _track_state(b) for n, b in data["tracks"].items()}
        return data  # type: ignore[return-value]  # now in State's shape
    desk = data.get("desk", data)
    if "mixer" in desk:
        return from_desk(desk)
    raise ValueError("neither a state nor a desk recipe")


def load(path: Path) -> State:
    if not path.exists():
        raise FileNotFoundError(f"no state {path}")
    try:
        return load_dict(json.loads(path.read_text()))
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None
