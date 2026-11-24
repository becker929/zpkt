"""The desk's settings as structure in the arrangement (the recipe), and back into a set.

    uv run --project hands python contrib/mixdesk/recipe.py write    # Live -> "desk" in arrangements/short-8d2a2.json
    uv run --project hands python contrib/mixdesk/recipe.py show     # what the recipe's "desk" holds, in Live's units
    uv run --project hands python contrib/mixdesk/recipe.py apply [--set NAME]  # "desk" -> the set in front

Anthony (12 Nov 2026): every page stores structure, and it all accumulates into a recipe the mastering step runs in
Live. The desk's part of it is "desk": the two returns and their devices, every desk device on the buses and Main
(in chain order, every parameter), every track's mixer (volume, pan, sends by return name, mute), the switches
the desk owns on devices it did not add (the kick's KSMS match EQ), and the monitor tracks (monitor.py: the
original render and the references, as audio clips in the Arrangement, with their files and positions). Each value is kept twice, as Live shows it and as
its raw value; `apply` sets the raw value, which round-trips exactly on the same Live version.

`apply` works on the finishing set or on a mix set freshly built by contrib/arranger/mixset.py: it adds what is
missing (workspace.py's returns and desk devices), then puts the desk back with hands.live.state (only values that
differ, one device and at most 16 parameters per LOM call, ableton-guide Rule 2) and reads them back. `write` reads
the set with hands.live.state too; the "desk" it writes has the shape of lib/contracts/desk.schema.json.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import finishing as F
import match as M
import monitor as MON
import workspace as W

from hands.live import hold
from hands.live import state as S
from hands.live.ops import LiveOps

DATA = Path(os.environ.get("ARRANGER_DATA", "~/_agent_scratch/arranger")).expanduser()
ARR = DATA / "arrangements" / "short-8d2a2.json"
BACKUPS = F.OUT / "backups"
OWNED = [("kick", "EQ Eight", ["Device On"])]   # switches on devices the desk did not add
NOTE = (__doc__ or "").split("\n\n")[2].replace("\n", " ")
MONITOR_CLIPS = ("result = [[t.name, [[c.file_path, c.start_time, c.warping] for c in t.arrangement_clips]] "
                 "for t in song.tracks if t.name.startswith('mon ')]")


def _device(d: S.DeviceState) -> dict[str, Any]:
    return {"name": d["name"], "class": d["class"], "values": d["params"]}


def desk_from_state(state: S.State, clips: list[Any], set_name: str, made: float) -> dict[str, Any]:
    """The recipe's "desk" from a state just taken and the monitor tracks' clips ([[track, [[file, beat,
    warping], ...]], ...]): returns, desk chains, every mixer, the owned switches, the monitor tracks."""
    rets = state["returns"]
    desk: dict[str, Any] = {"made": made, "set": set_name, "note": NOTE, "returns": [], "chains": {}, "mixer": {},
                            "owned": []}
    for r in rets:
        desk["returns"].append({"name": S.short(r, rets), "devices": [_device(d) for d in state["tracks"][r]["devices"]]})
    for n, body in state["tracks"].items():
        name = S.short(n, rets)
        chain = [_device(d) for d in body["devices"] if d["name"].startswith("desk ")]
        if chain:
            desk["chains"][name] = chain
        m = body["mixer"]
        entry: dict[str, Any] = {"volume": m["volume"], "pan": m["pan"],
                                 "sends": {S.short(r, rets): v for r, v in m.get("sends", {}).items()}}
        if n != "Main":
            entry["mute"] = bool(m["mute"][1])
        desk["mixer"][name] = entry
    by_short = {S.short(n, rets): body for n, body in state["tracks"].items()}
    for track, dev, params in OWNED:
        found = next((d for d in by_short[track]["devices"] if d["name"] == dev), None) if track in by_short else None
        if found is not None:
            desk["owned"].append({"track": track, "device": dev, "values": {p: found["params"][p] for p in params}})
    desk["monitor"] = [{"track": n, "file": c[0][0], "beat": c[0][1], "warping": c[0][2]} for n, c in clips if c]
    return desk


def read_desk(live: LiveOps, set_name: str = M.SET) -> dict[str, Any]:
    return desk_from_state(S.take(live.client), live.run(MONITOR_CLIPS), set_name, time.time())


def write(live: LiveOps, set_name: str = M.SET) -> None:
    arr = json.loads(ARR.read_text())
    BACKUPS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARR, BACKUPS / f"{ARR.stem}.{time.strftime('%Y%m%d-%H%M%S')}.json")
    arr["desk"] = read_desk(live, set_name)
    tmp = ARR.with_name(f".{ARR.stem}.tmp")
    tmp.write_text(json.dumps(arr))
    tmp.replace(ARR)
    d = arr["desk"]
    print(f"{ARR}: desk with {len(d['returns'])} returns, {sum(len(c) for c in d['chains'].values())} desk devices on "
          f"{len(d['chains'])} tracks, {len(d['mixer'])} mixers, {len(d.get('monitor', []))} monitor tracks")


def show() -> None:
    d = json.loads(ARR.read_text()).get("desk")
    if not d:
        sys.exit(f"{ARR} has no desk yet: run `recipe.py write`")
    print(f"desk from {d['set']}, written {time.strftime('%Y-%m-%d %H:%M', time.localtime(d['made']))}")
    for r in d["returns"]:
        print(f"return {r['name']}: " + ", ".join(x["name"] for x in r["devices"]))
    for m in d.get("monitor", []):
        print(f"monitor {m['track']}: {Path(m['file']).name} at beat {m['beat']}, warping {m['warping']}")
    for track, chain in d["chains"].items():
        for dev in chain:
            moved = {k: v[0] for k, v in dev["values"].items() if k != "Device On"}
            print(f"{track:22s} {dev['name']:14s} on={dev['values'].get('Device On', ['?'])[0]:3s} {json.dumps(moved)[:160]}")
    for track, m in d["mixer"].items():
        sends = {k: v[0] for k, v in m["sends"].items() if not v[0].startswith("-inf")}
        print(f"{track:22s} vol {m['volume'][0]:>10s} pan {m['pan'][0]:>5s} mute {m.get('mute', False)!s:5s} sends {sends}")


def apply_desk(live: LiveOps, desk: dict[str, Any], log: Any = print) -> list[S.Row]:
    """Put `desk` into the set in front: workspace.py's returns and desk devices and the monitor tracks where
    missing, then every value (hands.live.state.put). Returns what still differs after the read-back."""
    W.devices(live)   # returns and desk devices, added where missing, at neutral values
    if desk.get("monitor"):   # the monitor tracks and their clips, added where missing (muted), before their mixers
        MON.ensure(live, log=log, want={m["track"]: (Path(m["file"]), float(m["beat"])) for m in desk["monitor"]})
    return S.put(live.client, S.from_desk(desk))


def apply(live: LiveOps, set_name: str = M.SET) -> None:
    d = json.loads(ARR.read_text()).get("desk")
    if not d:
        sys.exit(f"{ARR} has no desk yet")
    wrong = apply_desk(live, d, log=lambda *a: print(*a, flush=True))
    lines = [f"{k}: {have} != {want}" for k, want, have in wrong]
    print("recipe applied" if not wrong else "MISMATCH:\n  " + "\n  ".join(lines[:40]), flush=True)
    if wrong:
        sys.exit(1)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "show":
        return show()
    if cmd not in ("write", "apply"):
        sys.exit(__doc__)
    set_name = M.SET
    if cmd == "apply" and sys.argv[2:3] == ["--set"]:   # apply onto another HW002_121_pp_ set (a rebuild check)
        set_name = sys.argv[3]
    F.use_rig()
    live = F.ops()
    was = M.front_app()
    with hold.using_live(f"mixdesk recipe {cmd}"):
        try:
            M.front(live, set_name)
            {"write": write, "apply": apply}[cmd](live, set_name)
        finally:
            M.give_back(was)


if __name__ == "__main__":
    main()
