"""The second mixing step, in Live: distortion, EQ boosts, compression and bus processing, heard as small batches.

Anthony (12 Nov 2026): "I'll choose a range of parameters I want to hear and then you'll do a large-grained grid
search of those parameters and render them for me to play with in the app." The mix 2 page (static/mix2.html) writes
a request: a channel or bus, a Live device, one or two of its parameters with a range and a number of steps, and a
stretch of bars. This script renders each point of that grid in Live, and the page plays the renders.

The renders come from a mix set built in Live from the arrangement's own structure (HW002_121_pp_mix.als): one audio
track per mix channel holding the arranger's loops and the picked transitions where the arrangement puts them, each
channel routed to a bus track per group (kick, hats, perc, chord and splash, break, transitions), every channel's
mix-1 gain and pan on its mixer and its cuts on an EQ Eight, and the mix-2 choices already kept on their tracks.
The loops are Live's bounces of each part through its own track, group and Main, so a device on a bus here works on
the parts summed after their own groups: close to, not the same as, the same device in HW002's own group.

    uv run --project hands python contrib/arranger/mixset.py build      # the mix set from the arrangement (HW002_121_pp_mix in front)
    uv run --project hands python contrib/arranger/mixset.py base       # render the mix as it stands (the reference)
    uv run --project hands python contrib/arranger/mixset.py worker     # render queued requests, one after another
"""
from __future__ import annotations

import itertools
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("ARRANGER_DATA", "~/_agent_scratch/arranger")).expanduser()
MIX2 = DATA / "mix2"
SETS = Path("~/_agent_scratch/HW002").expanduser()
SET = "HW002_121_pp_mix"
ARR_ID = "short-8d2a2"
BAR = 4.0
HEADROOM = -6.0   # a Utility on the mix set's Main: the loops summed with mix 1 reach full scale, so renders leave room
FX_KINDS = {"riser": "Risers", "reverse": "Reverse reverbs", "fill": "Fills", "downlifter": "Downlifters"}
BUSES = {"kick": "Kick bus", "hats": "Hats bus", "perc": "Perc bus", "sfx": "Chord and splash bus", "break": "Break bus",
         "fx": "Transitions bus"}

# The devices the page offers, and the parameters a grid may move: (name in Live, unit, lo, hi) or (name, values).
DEVICES = {
    "Saturator": {"what": "distortion", "params": [("Drive", "dB", 0, 36), ("Type", ["Analog Clip", "Soft Sine", "Medium Curve", "Hard Curve", "Digital Clip"]),
                                                    ("Dry/Wet", "%", 0, 100), ("Output", "dB", -36, 0)]},
    "Drum Buss": {"what": "distortion and bus", "params": [("Drive", "%", 0, 100), ("Crunch", "%", 0, 100), ("Boom Amt", "%", 0, 100),
                                                            ("Transients", "", -1, 1), ("Drive Type", ["Soft", "Medium", "Hard"]), ("Dry/Wet", "%", 0, 100)]},
    "EQ Eight": {"what": "EQ boost", "params": [("4 Frequency A", "Hz", 30, 16000), ("4 Gain A", "dB", 0, 15), ("4 Q A", "", 0.1, 4)],
                 "fixed": {"4 Filter Type A": "Bell", "4 Filter On A": "On", "1 Filter On A": "Off", "2 Filter On A": "Off",
                           "3 Filter On A": "Off", "5 Filter On A": "Off", "6 Filter On A": "Off", "7 Filter On A": "Off", "8 Filter On A": "Off"}},
    "Compressor": {"what": "compression", "params": [("Threshold", "dB", -40, 0), ("Ratio", ":1", 1, 20), ("Attack", "ms", 0.1, 100),
                                                      ("Release", "ms", 10, 1000), ("Output", "dB", 0, 24), ("Dry/Wet", "%", 0, 100)]},
    "Glue Compressor": {"what": "bus compression", "params": [("Threshold", "dB", -40, 0), ("Ratio", ["2", "4", "10"]),
                                                               ("Attack", [".01", ".1", ".3", "1", "3", "10", "30"]),
                                                               ("Release", [".1", ".2", ".4", ".6", "1.2"]), ("Output", "dB", 0, 20),
                                                               ("Dry/Wet", "%", 0, 100)]},
}


def lo():
    os.environ["ZPKT_SETS_DIR"] = str(SETS)
    os.environ["ZPKT_SET_PREFIXES"] = "HW002_121_pp_"
    os.environ["ZPKT_DATA_DIR"] = str(MIX2 / "data")
    os.environ["ZPKT_RENDERS_DIR"] = str(MIX2 / "raw")
    sys.path.insert(0, str(ROOT / "hands" / "scripts" / "rummage"))
    import liveops
    # a folder the Save panel already knows (export() moves the file to its target), whatever ARRANGER_DATA says
    liveops.EXPORT_DIR = Path("~/_agent_scratch/arranger/raw").expanduser()
    return liveops


def load() -> tuple[dict, dict, dict]:
    loops = json.loads((DATA / "loops.json").read_text())
    fx = json.loads((DATA / "fx" / "fx.json").read_text())
    arr = json.loads((DATA / "arrangements" / f"{ARR_ID}.json").read_text())
    return loops, fx, arr


def channels(loops: dict, arr: dict) -> list[dict]:
    """The mix channels, as the mix pages make them: a lane of the arrangement, or a kind of transition laid over it."""
    used = {r["lane"] for r in arr["regions"]} | {t["lane"] for t in arr.get("transitions", []) if t.get("mode") == "replace"}
    out = [{"id": l["id"], "title": l["title"], "group": l["group"]} for l in loops["lanes"] if l["id"] in used]
    kinds = {t["kind"] for t in arr.get("transitions", []) if t.get("mode") != "replace"}
    out += [{"id": f"fx-{k}", "title": v, "group": "fx"} for k, v in FX_KINDS.items() if k in kinds]
    return out


def guard(L) -> None:
    if L.guard("mix set") != SET:
        sys.exit(f"STOP: {SET} is not in front")


def tracks(L) -> dict:
    return {n: i for i, n in enumerate(L.run("result = [t.name for t in song.tracks]"))}


# ---- build: the mix set from the arrangement -------------------------------------------------------------------------

def build() -> None:
    L = lo()
    guard(L)
    loops, fx, arr = load()
    chans = channels(loops, arr)
    clips = {c["id"]: c for c in loops["clips"]}
    cands = {c["id"]: c for c in fx["candidates"]}
    L.run("song.tempo = 160.0\nresult = 'ok'")
    # empty the set: new tracks first (a set keeps at least one), then the old ones go
    old = len(L.run("result = [t.name for t in song.tracks]"))
    groups = [g for g in BUSES if any(c["group"] == g for c in chans)]
    for name in [BUSES[g] for g in groups] + [c["id"] for c in chans]:
        L.run(f"t = song.create_audio_track(-1)\nt.name = {name!r}\nresult = 'ok'")
    L.run(f"for _ in range({old}):\n    song.delete_track(0)\nresult = 'ok'")
    L.run("while len(song.return_tracks):\n    song.delete_return_track(0)\nresult = 'ok'")
    idx = tracks(L)
    # each channel into its bus; buses into Main. A bus monitors In with no input of its own: it hears only the
    # channels routed to it.
    for g in groups:
        got = L.run(f"""t = song.tracks[{idx[BUSES[g]]}]
r = [x for x in t.available_input_routing_types if x.display_name == 'No Input']
t.input_routing_type = r[0]
t.current_monitoring_state = 0
result = [t.input_routing_type.display_name, t.current_monitoring_state]""")
        if got != ["No Input", 0]:
            sys.exit(f"STOP: bus {g}: {got}")
    for c in chans:
        bus = BUSES[c["group"]]
        got = L.run(f"""t = song.tracks[{idx[c['id']]}]
r = [x for x in t.available_output_routing_types if x.display_name == {bus!r}]
if r:
    t.output_routing_type = r[0]
result = t.output_routing_type.display_name""")
        if got != bus:
            sys.exit(f"STOP: {c['id']} routes to {got!r}, wanted {bus!r}")
    # the loops where the arrangement puts them (whole passes; a scoop or kick fill takes the kick's pass instead)
    replaced = [(t["lane"], t["startBeat"], t["startBeat"] + t["beats"]) for t in arr.get("transitions", []) if t.get("mode") == "replace"]
    calls = []
    for r in arr["regions"]:
        c = clips[r["clip"]]
        path = str(DATA / "audio" / c["file"])
        if c["kind"] == "once":
            calls.append((r["lane"], path, r["start"] * BAR, None))
            continue
        for p in range(math.ceil(r["len"] / c["bars"])):
            at = (r["start"] + p * c["bars"]) * BAR
            if any(lane == r["lane"] and a <= at < b for lane, a, b in replaced):
                continue
            if (p + 1) * c["bars"] > r["len"]:
                sys.exit(f"STOP: {r['clip']} does not fill whole passes in {r}")
            calls.append((r["lane"], path, at, None))
        end = r["start"] + r["len"]
        if c.get("tail") and not any(o["lane"] == r["lane"] and o["start"] == end for o in arr["regions"]) and end < arr["bars"]:
            calls.append((r["lane"], str(DATA / "audio" / c["tail"]), end * BAR, None))
    for t in arr.get("transitions", []):
        lane = t["lane"] if t.get("mode") == "replace" else f"fx-{t['kind']}"
        calls.append((lane, str(DATA / "fx" / "audio" / cands[t["id"]]["file"]), float(t["startBeat"]), t.get("gainDb", 0.0)))
    for k in range(0, len(calls), 12):
        code = "out = []\n"
        for lane, path, at, gain in calls[k:k + 12]:
            code += (f"t = song.tracks[{idx[lane]}]\nc = t.create_audio_clip({path!r}, {float(at)})\nc.warping = False\n"
                     f"out.append(c.end_time - c.start_time)\n")
        L.run(code + "result = out")
    for lane, path, at, gain in calls:   # a transition's level from its page, as the clip's gain
        if gain:
            L.run(f"""t = song.tracks[{idx[lane]}]
c = [c for c in t.arrangement_clips if abs(c.start_time - {float(at)}) < 1e-6 and c.file_path == {path!r}][0]
want = {float(gain)}
lo_, hi_ = 0.0, 1.0
for _ in range(40):
    mid = (lo_ + hi_) / 2
    c.gain = mid
    s = c.gain_display_string.replace(' dB', '')
    v = -999.0 if 'inf' in s else float(s)
    if v < want: lo_ = mid
    else: hi_ = mid
c.gain = hi_
result = c.gain_display_string""")
    print(f"{len(chans)} channels on {len(groups)} buses, {len(calls)} clips", flush=True)
    main_gain(L, HEADROOM)
    apply_mix(L, arr, chans)


def main_gain(L, db: float) -> None:
    """The Utility at the end of Main: the renders' headroom, and the loudness match for comparing."""
    if L.run("result = [d.class_name for d in song.master_track.devices][-1:]") != ["StereoGain"]:
        L.load_item("song.master_track", "audio_effects", None, "Utility")
    L.setp("song.master_track.devices[-1]", {"Output": f"{round(db, 2)} dB"})


def apply_mix(L, arr: dict, chans: list[dict]) -> None:
    """Mix 1 (gain, pan and cuts) on each channel: the mixer, and an EQ Eight for the cuts. Then the kept mix-2
    devices, in the order they were kept. Everything after the mixer is rebuilt from the structure each time."""
    idx = tracks(L)
    mix = (arr.get("mix") or {}).get("channels", {})
    for name in [c["id"] for c in chans] + list(BUSES.values()):
        if name in idx:
            L.run(f"t = song.tracks[{idx[name]}]\nwhile len(t.devices):\n    t.delete_device(0)\nresult = 'ok'")
    for c in chans:
        m = mix.get(c["id"], {})
        t = f"song.tracks[{idx[c['id']]}]"
        L.mixer(t, float(m.get("gainDb", 0.0)), (), float(m.get("pan", 0.0)))
        eq = m.get("eq") or {}
        cuts = [x for x in eq.get("cuts", []) if x.get("on")]
        if not (cuts or (eq.get("hp") or {}).get("on") or (eq.get("lp") or {}).get("on")):
            continue
        L.load_item(t, "audio_effects", None, "EQ Eight")
        p = {f"{k} Filter On A": "Off" for k in range(1, 9)}
        if (eq.get("hp") or {}).get("on"):
            p.update({"1 Filter On A": "On", "1 Filter Type A": "High Pass 12dB", "1 Frequency A": f"{eq['hp']['freq']} Hz"})
        for k, x in enumerate(cuts[:3], start=2):
            p.update({f"{k} Filter On A": "On", f"{k} Filter Type A": "Bell", f"{k} Frequency A": f"{x['freq']} Hz",
                      f"{k} Gain A": f"{min(0.0, x['gainDb'])} dB", f"{k} Q A": float(x["q"])})
        if (eq.get("lp") or {}).get("on"):
            p.update({"8 Filter On A": "On", "8 Filter Type A": "Low Pass 12dB", "8 Frequency A": f"{eq['lp']['freq']} Hz"})
        L.setp(f"{t}.devices[0]", p)
    for k in arr.get("mix2", []):
        add_device(L, idx, k["target"], k["device"], k["values"])
    print("mix applied", flush=True)


def target_track(idx: dict, target: str) -> str:
    name = BUSES.get(target.removeprefix("bus-"), target) if target.startswith("bus-") else target
    if name not in idx:
        sys.exit(f"STOP: no track for {target!r}")
    return f"song.tracks[{idx[name]}]"


def add_device(L, idx: dict, target: str, device: str, values: dict) -> str:
    t = target_track(idx, target)
    L.load_item(t, "audio_effects", None, device)
    dev = f"{t}.devices[{len(L.devices(t)) - 1}]"
    L.setp(dev, {**DEVICES[device].get("fixed", {}), **values})
    return dev


# ---- renders ------------------------------------------------------------------------------------------------------------

def to_flac(wav: Path, flac: Path, skip_beats: float = 0.0) -> None:
    """The render as 16-bit FLAC, its preroll bar cut off. Only cut: no gain or processing."""
    code = ("import soundfile as sf, sys\nx, r = sf.read(sys.argv[1], always_2d=True)\nn = round(float(sys.argv[3]) * r * 60 / 160)\n"
            "sf.write(sys.argv[2], x[n:], r, subtype='PCM_16')")
    subprocess.run(["uv", "run", "--project", str(ROOT / "ears"), "python", "-c", code, str(wav), str(flac), str(skip_beats)], check=True)
    wav.unlink()


def render(L, out: Path, bars: tuple[int, int]) -> Path:
    """Bars (1-based, inclusive) of the mix set, with a bar of preroll before them (cut off) so devices with memory
    (compressors) are settled when the stretch starts."""
    a, b = bars
    pre = 1.0 if a > 1 else 0.0
    start = (a - 1 - pre) * BAR
    wav = out.with_suffix(".wav")
    if wav.exists():
        wav.unlink()
    L.export(wav, start, (b - a + 1 + pre) * BAR, bits=24, timeout_s=600)
    to_flac(wav, out, pre * BAR)
    return out


def lufs(path: Path) -> float:
    code = "import soundfile as sf, pyloudnorm as pl, sys\nx, r = sf.read(sys.argv[1])\nprint(pl.Meter(r).integrated_loudness(x))"
    out = subprocess.run(["uv", "run", "--project", str(ROOT / "ears"), "python", "-c", code, str(path)], check=True,
                         capture_output=True, text=True).stdout
    return float(out.strip().splitlines()[-1])


def base() -> None:
    L = lo()
    guard(L)
    MIX2.mkdir(parents=True, exist_ok=True)
    out = render(L, MIX2 / "base-full.flac", (1, 40))
    print(out)


def points(req: dict) -> list[dict]:
    axes = []
    for p in req["params"]:
        if p.get("values"):
            axes.append([(p["name"], v) for v in p["values"]])
        else:
            n = max(2, min(6, int(p["steps"])))
            lo_, hi_ = float(p["min"]), float(p["max"])
            if p.get("unit") == "Hz" or (p.get("log") and lo_ > 0):
                vals = [lo_ * (hi_ / lo_) ** (k / (n - 1)) for k in range(n)]
            else:
                vals = [lo_ + (hi_ - lo_) * k / (n - 1) for k in range(n)]
            unit = p.get("unit", "")   # in the parameter's display units, as liveops.setp takes them
            axes.append([(p["name"], f"{round(v, 2)} {unit}" if unit and unit != ":1" else f"{round(v, 3)}") for v in vals])
    return [dict(c) for c in itertools.product(*axes)]


def run_request(L, path: Path) -> None:
    req = json.loads(path.read_text())
    loops, fx, arr = load()
    chans = channels(loops, arr)
    folder = MIX2 / req["id"]
    folder.mkdir(parents=True, exist_ok=True)
    bars = tuple(req.get("bars", (17, 32)))

    def status(**kw):
        req.update(kw)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(req, indent=1))
        tmp.replace(path)

    pts = points(req)
    status(status="rendering", total=2 * len(pts) + 1, done=0, started=time.time())
    main_gain(L, HEADROOM)
    apply_mix(L, arr, chans)                     # the mix as kept so far, without this request's device
    render(L, folder / "base.flac", bars)
    ref = lufs(folder / "base.flac")
    status(done=1, base="base.flac", baseLufs=round(ref, 2))
    idx = tracks(L)
    dev = add_device(L, idx, req["target"], req["device"], pts[0])
    out = []
    for k, values in enumerate(pts):
        L.setp(dev, values)
        f, fm = f"p{k:02d}.flac", f"p{k:02d}-m.flac"
        render(L, folder / f, bars)
        loud = lufs(folder / f)
        # the same render again with Main turned to the base's loudness: a listening aid, made in Live
        main_gain(L, HEADROOM + ref - loud)
        render(L, folder / fm, bars)
        main_gain(L, HEADROOM)
        out.append({"k": k, "values": values, "file": f, "matched": fm, "lufs": round(loud, 2), "matchDb": round(ref - loud, 2)})
        status(done=2 * k + 3, points=out)
    L.run(f"t = {target_track(idx, req['target'])}\nt.delete_device(len(t.devices) - 1)\nresult = 'ok'")
    status(status="ready", finished=time.time())
    print(f"{req['id']}: {len(pts)} points", flush=True)


def worker() -> None:
    """Render queued requests oldest first, until none are left. Stops at the first surprise."""
    L = lo()
    guard(L)
    while True:
        queued = sorted((p for p in (MIX2 / "requests").glob("*.json") if json.loads(p.read_text()).get("status") == "queued"),
                        key=lambda p: json.loads(p.read_text()).get("made", 0))
        if not queued:
            print("queue empty", flush=True)
            return
        try:
            run_request(L, queued[0])
        except (Exception, SystemExit) as e:
            req = json.loads(queued[0].read_text())
            req.update(status="failed", error=str(e))
            queued[0].write_text(json.dumps(req, indent=1))
            raise


def catalog() -> dict:
    """What the page needs to offer: channels, buses and devices."""
    loops, _, arr = load()
    chans = channels(loops, arr)
    buses = [{"id": f"bus-{g}", "title": BUSES[g]} for g in BUSES if any(c["group"] == g for c in chans)]
    return {"channels": chans, "buses": buses,
            "devices": {k: {"what": v["what"], "params": [{"name": p[0], "values": p[1]} if isinstance(p[1], list)
                                                          else {"name": p[0], "unit": p[1], "min": p[2], "max": p[3]} for p in v["params"]]}
                        for k, v in DEVICES.items()}}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "catalog":
        MIX2.mkdir(parents=True, exist_ok=True)
        (MIX2 / "catalog.json").write_text(json.dumps(catalog(), indent=1))
        print(MIX2 / "catalog.json")
    else:
        {"build": build, "base": base, "worker": worker}[cmd]()
