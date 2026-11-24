"""The mix state of the open set as data: take it, compare it, put it back.

    hands live state take NAME            # every mixer and device value -> sets_dir/state/<set>/NAME.json
    hands live state diff NAME [OTHER]    # NAME against Live now (or against OTHER); only what differs
    hands live state put NAME [--only T]  # NAME's raw values back into Live, read back, exit 1 on a mismatch
    hands live state ls                   # the states kept for the front set

A state holds, for every track, return and Main: volume, pan, sends (by return name), mute and solo, and every
device's parameters (in chain order). Each value is kept as Live shows it and as its raw value; `put` writes the
raw value, which round-trips exactly on the same Live version. Reading is one LOM call per track; writing is one
device and at most 16 parameters per call (ableton-guide Rule 2).

NAME may also be a path to a state file, or to any JSON whose "desk" key or top level has this shape.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from hands import config
from hands.live.transport import Transport

WRITE_CHUNK = 16
Value = list  # [shown, raw]

_READ_TRACK = """t = {expr}
m = t.mixer_device
rets = [r.name for r in song.return_tracks]
mix = {{'volume': [str(m.volume), m.volume.value], 'pan': [str(m.panning), m.panning.value],
       'sends': {{rets[k]: [str(s), s.value] for k, s in enumerate(m.sends)}}}}
if {is_track}:
    mix['mute'] = [str(bool(t.mute)), bool(t.mute)]
    mix['solo'] = [str(bool(t.solo)), bool(t.solo)]
devs = [{{'name': d.name, 'class': d.class_name,
         'params': {{p.name: [str(p), p.value] for p in d.parameters}}}} for d in t.devices]
result = {{'mixer': mix, 'devices': devs}}"""


def track_expr(name: str) -> str:
    """The LOM expression for a track, return or Main by name."""
    if name.strip().lower() in ("main", "master"):
        return "song.master_track"
    return (f"next(t for t in list(song.tracks) + list(song.return_tracks) "
            f"if t.name == {name!r} or (t.name[1:2] == '-' and t.name[2:] == {name!r}))")


def short(name: str, returns: list[str]) -> str:
    """A return's name without the letter Live puts in front ("A-Space" -> "Space"); other names as they are."""
    return name[2:] if name in returns and len(name) > 2 and name[1] == "-" else name


def take(client: Transport, only: list[str] | None = None) -> dict:
    names = client.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks)] + ['Main']")
    rets = client.run("result = [r.name for r in song.return_tracks]")
    if only:
        names = [n for n in names if n in only or short(n, rets) in only]
    state: dict[str, Any] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "returns": rets, "tracks": {}}
    for n in names:
        body = client.run(_READ_TRACK.format(expr=track_expr(n), is_track=n != "Main"))
        state["tracks"][n] = _numbers(body)
    return state


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


def _numbers(body: dict) -> dict:
    mix = body["mixer"]
    for k in ("volume", "pan", "mute", "solo"):
        if k in mix:
            mix[k] = [mix[k][0], _raw(mix[k][1])]
    mix["sends"] = {r: [v[0], _raw(v[1])] for r, v in mix.get("sends", {}).items()}
    for d in body["devices"]:
        d["params"] = {p: [v[0], _raw(v[1])] for p, v in d["params"].items()}
    return body


def _num(v: Any) -> float:
    return float(v) if not isinstance(v, bool) else float(int(v))


def _same(a: Value | None, b: Value | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is b
    x, y = _num(a[1]), _num(b[1])
    return math.isclose(x, y, abs_tol=tol)


def flatten(state: dict) -> dict[str, Value]:
    """{"Track/mixer/volume": [shown, raw], "Track/Device#k/Param": [...]} for comparing. A device is keyed by
    name, with #2, #3 for repeats of a name on one track, so a reorder of unlike devices is not a difference."""
    out: dict[str, Value] = {}
    rets = state.get("returns", [])
    for name, body in state["tracks"].items():
        t = short(name, rets)
        mix = body["mixer"]
        for k in ("volume", "pan", "mute", "solo"):
            if k in mix:
                out[f"{t}/{k}"] = mix[k]
        for r, v in mix.get("sends", {}).items():
            out[f"{t}/send {short(r, rets)}"] = v
        seen: dict[str, int] = {}
        for d in body["devices"]:
            seen[d["name"]] = seen.get(d["name"], 0) + 1
            dn = d["name"] if seen[d["name"]] == 1 else f"{d['name']}#{seen[d['name']]}"
            for p, v in d["params"].items():
                out[f"{t}/{dn}/{p}"] = v
    return out


def diff(a: dict, b: dict, ignore: tuple[str, ...] = ()) -> list[tuple[str, str | None, str | None]]:
    """(key, shown in a, shown in b) for every value that differs or exists on one side only. A state marked
    "partial" (a recipe holds only some devices) is compared on its own keys alone."""
    fa, fb = flatten(a), flatten(b)
    keys = sorted(set(fa) if a.get("partial") else set(fa) | set(fb))
    return [(k, fa[k][0] if k in fa else None, fb[k][0] if k in fb else None)
            for k in keys if not k.startswith(ignore) and not _same(fa.get(k), fb.get(k))]


def summarize(rows: list[tuple[str, str | None, str | None]], limit: int = 60) -> str:
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


def _set_code(expr: str, values: list[tuple[str, Any]]) -> str:
    return (f"d = {expr}\nps = {{p.name: p for p in d.parameters}}\nbad = []\n"
            f"for n, v in {values!r}:\n"
            "    p = ps.get(n)\n"
            "    if p is None or not p.is_enabled:\n"
            "        bad.append(n)\n"
            "    else:\n"
            "        p.value = max(p.min, min(p.max, v))\n"
            "result = bad")


def put(client: Transport, state: dict, only: list[str] | None = None) -> list[tuple[str, str | None, str | None]]:
    """Write `state` into Live (tracks in `only`, or all of them), then read back; return what still differs.
    Only values that differ from Live are written, so a near-identical state goes back in seconds. Tracks or
    devices the set lacks are reported, never created."""
    before = take(client)
    rets = before["returns"]
    by_short = {short(n, rets): n for n in before["tracks"]}
    live = flatten(before)
    srets = state.get("returns", [])
    missing: list[tuple[str, str | None, str | None]] = []
    names = [n for n in state["tracks"] if not only or n in only or short(n, srets) in only]
    touched: list[str] = []
    for n in names:
        t = short(n, srets)
        if t not in by_short:
            missing.append((f"{t}/*", "track", None))
            continue
        body, expr = state["tracks"][n], track_expr(t)
        have = [d["name"] for d in before["tracks"][by_short[t]]["devices"]]
        seen: dict[str, int] = {}
        wrote = False
        for d in body["devices"]:
            seen[d["name"]] = seen.get(d["name"], 0) + 1
            k = seen[d["name"]]
            idxs = [i for i, x in enumerate(have) if x == d["name"]]
            if k > len(idxs):
                missing.append((f"{t}/{d['name']}", "device", None))
                continue
            dn = d["name"] if k == 1 else f"{d['name']}#{k}"
            items = [(p, v[1]) for p, v in d["params"].items() if not _same(v, live.get(f"{t}/{dn}/{p}"))]
            for a in range(0, len(items), WRITE_CHUNK):
                client.run(_set_code(f"{expr}.devices[{idxs[k - 1]}]", items[a:a + WRITE_CHUNK]))
                wrote = True
        mix = body["mixer"]
        lines = []
        for key, attr in (("volume", "m.volume.value"), ("pan", "m.panning.value")):
            if key in mix and not _same(mix[key], live.get(f"{t}/{key}")):
                lines.append(f"{attr} = {mix[key][1]!r}")
        sends = {short(r, srets): v for r, v in mix.get("sends", {}).items()}
        for k, r in enumerate(rets):
            v = sends.get(short(r, rets))
            if v is not None and not _same(v, live.get(f"{t}/send {short(r, rets)}")):
                lines.append(f"m.sends[{k}].value = {v[1]!r}")
        if t != "Main":
            for flag in ("mute", "solo"):
                if flag in mix and not _same(mix[flag], live.get(f"{t}/{flag}")):
                    lines.append(f"t.{flag} = {bool(mix[flag][1])!r}")
        if lines:
            client.run("\n".join([f"t = {expr}", "m = t.mixer_device", *lines, "result = 'ok'"]))
            wrote = True
        if wrote:
            touched.append(by_short[t])
    now = before
    if touched:
        again = take(client, only=touched)
        now = {**before, "tracks": {**before["tracks"], **again["tracks"]}}
    want = {**state, "tracks": {n: state["tracks"][n] for n in names if short(n, srets) in by_short}}
    if not state.get("partial"):
        want["partial"] = True   # Live's tracks outside `names` are not ours to judge here
    return missing + diff(want, now)


# --- files -------------------------------------------------------------------------------------------------------

def folder(set_name: str) -> Path:
    return config.rig().sets_dir / "state" / set_name


def path_for(set_name: str, name: str) -> Path:
    p = Path(name).expanduser()
    if p.suffix == ".json" and (p.exists() or "/" in name):
        return p
    return folder(set_name) / f"{name}.json"


def save(state: dict, path: Path, set_name: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {"set": set_name, **state}
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)
    return path


def from_desk(desk: dict) -> dict:
    """A mixdesk recipe's "desk" (returns, desk chains, mixer, owned switches) as a partial state."""
    tracks: dict[str, Any] = {}
    for name, m in desk.get("mixer", {}).items():
        mix = {"volume": m["volume"], "pan": m["pan"], "sends": m.get("sends", {})}
        if "mute" in m:
            mix["mute"] = [str(m["mute"]), m["mute"]]
        tracks[name] = {"mixer": mix, "devices": []}
    for r in desk.get("returns", []):
        tracks.setdefault(r["name"], {"mixer": {}, "devices": []})["devices"] = [
            {"name": d["name"], "class": d.get("class"), "params": d["values"]} for d in r["devices"]]
    for name, chain in desk.get("chains", {}).items():
        tracks.setdefault(name, {"mixer": {}, "devices": []})["devices"] += [
            {"name": d["name"], "class": d.get("class"), "params": d["values"]} for d in chain]
    for o in desk.get("owned", []):
        tracks.setdefault(o["track"], {"mixer": {}, "devices": []})["devices"].append(
            {"name": o["device"], "class": None, "params": o["values"]})
    return {"tracks": tracks, "partial": True}


def load_dict(data: dict) -> dict:
    """A state, or a dict holding a mixdesk "desk" (the arrangement recipe, or the desk part alone), as a state."""
    if "tracks" in data:
        data["tracks"] = {n: _numbers(b) for n, b in data["tracks"].items()}
        return data
    desk = data.get("desk", data)
    if "mixer" in desk:
        return from_desk(desk)
    raise ValueError("neither a state nor a desk recipe")


def load(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"no state {path}")
    try:
        return load_dict(json.loads(path.read_text()))
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None
