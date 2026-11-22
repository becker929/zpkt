"""The desk's settings as structure in the arrangement (the recipe), and back into a set.

    uv run --project hands python contrib/mixdesk/recipe.py write    # Live -> "desk" in arrangements/short-8d2a2.json
    uv run --project hands python contrib/mixdesk/recipe.py show     # what the recipe's "desk" holds, in Live's units
    uv run --project hands python contrib/mixdesk/recipe.py apply [--set NAME]  # "desk" -> the set in front

Anthony (12 Nov 2026): every page stores structure, and it all accumulates into a recipe the mastering step runs in
Live. The desk's part of it is "desk": the two returns and their devices, every desk device on the buses and Main
(in chain order, every parameter), every track's mixer (volume, pan, sends by return name, mute), and the switches
the desk owns on devices it did not add (the kick's KSMS match EQ). Each value is kept twice, as Live shows it and as
its raw value; `apply` sets the raw value, which round-trips exactly on the same Live version.

`apply` works on the finishing set or on a mix set freshly built by contrib/arranger/mixset.py: it adds what is
missing (workspace.py's returns and desk devices), then sets every value, one device and at most 16 parameters per
LOM call (ableton-guide Rule 2), and reads them back.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import match as M  # noqa: E402  (sets the rig environment for liveops before hands is imported)
import workspace as W  # noqa: E402

L = M.L
DATA = Path(os.environ.get("ARRANGER_DATA", "~/_agent_scratch/arranger")).expanduser()
ARR = DATA / "arrangements" / "short-8d2a2.json"
BACKUPS = M.OUT / "backups"
OWNED = [("kick", "EQ Eight", ["Device On"])]   # switches on devices the desk did not add


def _track_names() -> list[str]:
    return L.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks)] + ['Main']")


def _short(name: str) -> str:
    """A return's name without Live's letter ("A-Space" -> "Space")."""
    return name[2:] if len(name) > 2 and name[1] == "-" and name[0].isalpha() and name[0].isupper() else name


def _params(t: str, k: int) -> dict:
    count = L.run(f"result = len({t}.devices[{k}].parameters)")
    out = {}
    for a in range(0, count, 20):
        for name, shown, raw in L.run(f"d = {t}.devices[{k}]\nresult = [[p.name, str(p), p.value] for p in list(d.parameters)[{a}:{a + 20}]]"):
            out[name] = [shown, raw]
    return out


def read_desk() -> dict:
    names = _track_names()
    rets = L.run("result = [t.name for t in song.return_tracks]")
    desk = {"made": time.time(), "set": M.SET, "note": __doc__.split("\n\n")[2].replace("\n", " "),
            "returns": [], "chains": {}, "mixer": {}, "owned": []}
    for r in rets:
        t = M.tr(_short(r))
        devs = L.run(f"result = [[d.name, d.class_name] for d in {t}.devices]")
        desk["returns"].append({"name": _short(r), "devices": [{"name": n, "class": c, "values": _params(t, k)}
                                                              for k, (n, c) in enumerate(devs)]})
    for n in names:
        t = M.tr(_short(n))
        devs = L.run(f"result = [[d.name, d.class_name] for d in {t}.devices]")
        chain = [{"name": dn, "class": c, "values": _params(t, k)} for k, (dn, c) in enumerate(devs) if dn.startswith("desk ")]
        if chain:
            desk["chains"][_short(n)] = chain
        mix = L.run(f"t = {t}\nm = t.mixer_device\nresult = [[str(m.volume), m.volume.value], [str(m.panning), m.panning.value], "
                    "[[str(s), s.value] for s in m.sends]]")
        entry = {"volume": mix[0], "pan": mix[1], "sends": {_short(r): s for r, s in zip(rets, mix[2])}}
        if n != "Main":
            entry["mute"] = L.run(f"result = bool({t}.mute)")
        desk["mixer"][_short(n)] = entry
    for track, dev, params in OWNED:
        t = M.tr(track)
        k = L.run(f"result = [d.name for d in {t}.devices].index({dev!r}) if {dev!r} in [d.name for d in {t}.devices] else -1")
        if k >= 0:
            vals = _params(t, k)
            desk["owned"].append({"track": track, "device": dev, "values": {p: vals[p] for p in params}})
    return desk


def write() -> None:
    arr = json.loads(ARR.read_text())
    BACKUPS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ARR, BACKUPS / f"{ARR.stem}.{time.strftime('%Y%m%d-%H%M%S')}.json")
    arr["desk"] = read_desk()
    tmp = ARR.with_name(f".{ARR.stem}.tmp")
    tmp.write_text(json.dumps(arr))
    tmp.replace(ARR)
    d = arr["desk"]
    print(f"{ARR}: desk with {len(d['returns'])} returns, {sum(len(c) for c in d['chains'].values())} desk devices on "
          f"{len(d['chains'])} tracks, {len(d['mixer'])} mixers")


def show() -> None:
    d = json.loads(ARR.read_text()).get("desk")
    if not d:
        sys.exit(f"{ARR} has no desk yet: run `recipe.py write`")
    print(f"desk from {d['set']}, written {time.strftime('%Y-%m-%d %H:%M', time.localtime(d['made']))}")
    for r in d["returns"]:
        print(f"return {r['name']}: " + ", ".join(x["name"] for x in r["devices"]))
    for track, chain in d["chains"].items():
        for dev in chain:
            moved = {k: v[0] for k, v in dev["values"].items() if k != "Device On"}
            print(f"{track:22s} {dev['name']:14s} on={dev['values'].get('Device On', ['?'])[0]:3s} {json.dumps(moved)[:160]}")
    for track, m in d["mixer"].items():
        sends = {k: v[0] for k, v in m["sends"].items() if not v[0].startswith("-inf")}
        print(f"{track:22s} vol {m['volume'][0]:>10s} pan {m['pan'][0]:>5s} mute {m.get('mute', False)!s:5s} sends {sends}")


def _set_raw(t: str, k: int, values: dict) -> None:
    items = [(n, v[1]) for n, v in values.items()]
    for a in range(0, len(items), 16):
        code = (f"d = {t}.devices[{k}]\nps = {{p.name: p for p in d.parameters}}\nbad = []\n"
                f"for n, v in {items[a:a + 16]!r}:\n"
                "    p = ps.get(n)\n"
                "    if p is None or not p.is_enabled:\n"
                "        bad.append(n)\n"
                "    else:\n"
                "        p.value = max(p.min, min(p.max, v))\n"
                "result = bad")
        bad = L.run(code)
        if bad:
            print(f"  note: {t}.devices[{k}]: not set {bad}", flush=True)


def apply() -> None:
    d = json.loads(ARR.read_text()).get("desk")
    if not d:
        sys.exit(f"{ARR} has no desk yet")
    W.devices()   # returns and desk devices, added where missing, at neutral values
    for r in d["returns"]:
        t = M.tr(r["name"])
        have = L.run(f"result = [d.name for d in {t}.devices]")
        for dev in r["devices"]:
            _set_raw(t, have.index(dev["name"]), dev["values"])
    for track, chain in d["chains"].items():
        t = M.tr(track)
        have = L.run(f"result = [d.name for d in {t}.devices]")
        for dev in chain:
            if dev["name"] not in have:
                sys.exit(f"STOP: {track} has no {dev['name']} after workspace.devices()")
            _set_raw(t, have.index(dev["name"]), dev["values"])
    for o in d.get("owned", []):
        t = M.tr(o["track"])
        have = L.run(f"result = [d.name for d in {t}.devices]")
        if o["device"] in have:
            _set_raw(t, have.index(o["device"]), o["values"])
    rets = L.run("result = [t.name for t in song.return_tracks]")
    for track, m in d["mixer"].items():
        t = M.tr(track)
        lines = [f"t = {t}", "m = t.mixer_device", f"m.volume.value = {m['volume'][1]!r}", f"m.panning.value = {m['pan'][1]!r}"]
        for k, r in enumerate(rets):
            if _short(r) in m["sends"]:
                lines.append(f"m.sends[{k}].value = {m['sends'][_short(r)][1]!r}")
        if "mute" in m and track != "Main":
            lines.append(f"t.mute = {bool(m['mute'])!r}")
        L.run("\n".join(lines) + "\nresult = 'ok'")
    # read back: every value the recipe holds, as Live now shows it
    now, wrong = read_desk(), []
    for track, chain in d["chains"].items():
        got = {x["name"]: x["values"] for x in now["chains"].get(track, [])}
        for dev in chain:
            for n, (shown, raw) in dev["values"].items():
                g = got.get(dev["name"], {}).get(n)
                if g is None or abs(g[1] - raw) > 1e-6:
                    wrong.append(f"{track}/{dev['name']}/{n}: {g and g[0]} != {shown}")
    for track, m in d["mixer"].items():
        g = now["mixer"].get(track)
        if g is None or abs(g["volume"][1] - m["volume"][1]) > 1e-6 or abs(g["pan"][1] - m["pan"][1]) > 1e-6:
            wrong.append(f"{track} mixer: {g and g['volume'][0]} != {m['volume'][0]}")
    print("recipe applied" if not wrong else "MISMATCH:\n  " + "\n  ".join(wrong[:40]), flush=True)
    if wrong:
        sys.exit(1)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "show":
        return show()
    if cmd not in ("write", "apply"):
        sys.exit(__doc__)
    if cmd == "apply" and sys.argv[2:3] == ["--set"]:   # apply onto another HW002_121_pp_ set (a rebuild check)
        M.SET = W.SET = sys.argv[3]
    was = M._front_app()
    with M.hold.using_live(f"mixdesk recipe {cmd}"):
        try:
            M.front()
            {"write": write, "apply": apply}[cmd]()
        finally:
            M.give_back(was)


if __name__ == "__main__":
    main()
