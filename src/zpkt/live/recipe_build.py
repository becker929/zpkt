"""The recipe built in Live: the mix set made from an arrangement, and mix 1 and the kept choices put on it.

An arrangement (contrib/arranger/arrangement.py) says which loops play where and how they are mixed. This module turns
that into Live: one audio track per mix channel holding its loops and picked transitions, each channel routed to a
bus per group, then each channel's gain, pan, cuts and kept devices. The planning (channels, clip places, EQ values)
is pure. The steps take `live`, anything with `run(code)` and the LiveOps helpers (`mixer`, `load_item`, `setp`,
`devices`): the app hands in its own connection, and the arranger's scripts hand in theirs.

A step that finds Live in a state it does not expect raises `Stopped`; the message says what was found.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BEATS_PER_BAR = 4.0
HEADROOM_DB = -6.0  # a Utility on Main: the loops summed with mix 1 reach full scale, so renders leave room
FX_KINDS = {"riser": "Risers", "reverse": "Reverse reverbs", "fill": "Fills", "downlifter": "Downlifters"}
BUSES = {
    "kick": "Kick bus",
    "hats": "Hats bus",
    "perc": "Perc bus",
    "sfx": "Chord and splash bus",
    "break": "Break bus",
    "fx": "Transitions bus",
}
CLIPS_PER_CALL = 12  # audio clips made in one LOM call, well under the Remote Script's 12 s


class Stopped(RuntimeError):
    """Live is not as the build expects; the run stops with this message."""


@dataclass(frozen=True)
class Built:
    """What `build` made."""

    channels: int
    buses: int
    clips: int


# ---- pure: what to build -------------------------------------------------------------------------------------------


def channels(loops: dict[str, Any], arr: dict[str, Any]) -> list[dict[str, Any]]:
    """The mix channels, as the mix pages make them: a lane of the arrangement, or a kind of transition laid over it."""
    used = {r["lane"] for r in arr["regions"]} | {
        t["lane"] for t in arr.get("transitions", []) if t.get("mode") == "replace"
    }
    out = [
        {"id": lane["id"], "title": lane["title"], "group": lane["group"]}
        for lane in loops["lanes"]
        if lane["id"] in used
    ]
    kinds = {t["kind"] for t in arr.get("transitions", []) if t.get("mode") != "replace"}
    out += [{"id": f"fx-{k}", "title": v, "group": "fx"} for k, v in FX_KINDS.items() if k in kinds]
    return out


def used_buses(chans: list[dict[str, Any]]) -> list[str]:
    """The bus groups some channel plays into, in the buses' order."""
    return [g for g in BUSES if any(c["group"] == g for c in chans)]


def clip_placements(
    arr: dict[str, Any], clips: dict[str, Any], cands: dict[str, Any], data: Path
) -> list[tuple[str, str, float, float | None]]:
    """Every audio clip the mix set holds: (channel, file, start beat, clip gain in dB or None). The loops in whole
    passes where the arrangement puts them (a scoop or kick fill takes the kick's pass instead), a loop's tail where
    nothing follows it, and each picked transition with its level from the transitions page."""
    replaced = [
        (t["lane"], t["startBeat"], t["startBeat"] + t["beats"])
        for t in arr.get("transitions", [])
        if t.get("mode") == "replace"
    ]
    calls: list[tuple[str, str, float, float | None]] = []
    for r in arr["regions"]:
        c = clips[r["clip"]]
        path = str(data / "audio" / c["file"])
        if c["kind"] == "once":
            calls.append((r["lane"], path, r["start"] * BEATS_PER_BAR, None))
            continue
        for p in range(math.ceil(r["len"] / c["bars"])):
            at = (r["start"] + p * c["bars"]) * BEATS_PER_BAR
            if any(lane == r["lane"] and a <= at < b for lane, a, b in replaced):
                continue
            if (p + 1) * c["bars"] > r["len"]:
                raise Stopped(f"{r['clip']} does not fill whole passes in {r}")
            calls.append((r["lane"], path, at, None))
        end = r["start"] + r["len"]
        follows = any(o["lane"] == r["lane"] and o["start"] == end for o in arr["regions"])
        if c.get("tail") and not follows and end < arr["bars"]:
            calls.append((r["lane"], str(data / "audio" / c["tail"]), end * BEATS_PER_BAR, None))
    for t in arr.get("transitions", []):
        lane = t["lane"] if t.get("mode") == "replace" else f"fx-{t['kind']}"
        path = str(data / "fx" / "audio" / cands[t["id"]]["file"])
        calls.append((lane, path, float(t["startBeat"]), t.get("gainDb", 0.0)))
    return calls


def bell_eq_values(bells: list[Any]) -> dict[str, Any]:
    """EQ Eight's values for up to six bells [(Hz, dB, Q)] on bands 2-7, every other band off."""
    v: dict[str, Any] = {f"{k} Filter On A": "Off" for k in range(1, 9)}
    for k, (f, g, q) in enumerate(bells, start=2):
        v.update(
            {
                f"{k} Filter On A": "On",
                f"{k} Filter Type A": "Bell",
                f"{k} Frequency A": f"{f} Hz",
                f"{k} Gain A": f"{g} dB",
                f"{k} Q A": float(q),
            }
        )
    return v


def cuts_eq_values(eq: dict[str, Any]) -> dict[str, Any] | None:
    """Mix 1's cuts on one channel as EQ Eight's values (a high-pass on band 1, up to three bell cuts, never a boost,
    a low-pass on band 8), or None when nothing is on."""
    hp, lp = eq.get("hp") or {}, eq.get("lp") or {}
    cuts = [x for x in eq.get("cuts", []) if x.get("on")]
    if not (cuts or hp.get("on") or lp.get("on")):
        return None
    p: dict[str, Any] = {f"{k} Filter On A": "Off" for k in range(1, 9)}
    if hp.get("on"):
        p.update({"1 Filter On A": "On", "1 Filter Type A": "High Pass 12dB", "1 Frequency A": f"{hp['freq']} Hz"})
    for k, x in enumerate(cuts[:3], start=2):
        p.update(
            {
                f"{k} Filter On A": "On",
                f"{k} Filter Type A": "Bell",
                f"{k} Frequency A": f"{x['freq']} Hz",
                f"{k} Gain A": f"{min(0.0, x['gainDb'])} dB",
                f"{k} Q A": float(x["q"]),
            }
        )
    if lp.get("on"):
        p.update({"8 Filter On A": "On", "8 Filter Type A": "Low Pass 12dB", "8 Frequency A": f"{lp['freq']} Hz"})
    return p


# ---- steps in Live ---------------------------------------------------------------------------------------------------


def tracks(live: Any) -> dict[str, int]:
    """Track name -> index in the set."""
    return {n: i for i, n in enumerate(live.run("result = [t.name for t in song.tracks]"))}


def target_track(idx: dict[str, int], target: str) -> str:
    """The LOM path of a channel ("kick") or a bus ("bus-kick")."""
    name = BUSES.get(target.removeprefix("bus-"), target) if target.startswith("bus-") else target
    if name not in idx:
        raise Stopped(f"no track for {target!r}")
    return f"song.tracks[{idx[name]}]"


def swap_clips(live: Any, track: str, path: str, *, check: bool = False) -> None:
    """Point every arrangement clip of `track` at another audio file: the same places, warping off. With `check`,
    read the clips back (a separate call) and stop if any differs."""
    starts = live.run(f"result = [c.start_time for c in {track}.arrangement_clips]")
    live.run(f"t = {track}\nfor c in list(t.arrangement_clips):\n    t.delete_clip(c)\nresult = 'ok'")
    for k in range(0, len(starts), CLIPS_PER_CALL):
        live.run(
            "".join(
                f"c = {track}.create_audio_clip({path!r}, {s})\nc.warping = False\n"
                for s in starts[k : k + CLIPS_PER_CALL]
            )
            + "result = 'ok'"
        )
    if check:
        got = live.run(f"result = [(c.start_time, c.file_path) for c in {track}.arrangement_clips]")
        if [g[0] for g in got] != starts or any(g[1] != path for g in got):
            raise Stopped(f"kick clips are {got}")


def empty_set(live: Any, names: list[str]) -> None:
    """New audio tracks named `names` first (a set keeps at least one track), then every old track and return goes."""
    old = len(live.run("result = [t.name for t in song.tracks]"))
    for name in names:
        live.run(f"t = song.create_audio_track(-1)\nt.name = {name!r}\nresult = 'ok'")
    live.run(f"for _ in range({old}):\n    song.delete_track(0)\nresult = 'ok'")
    live.run("while len(song.return_tracks):\n    song.delete_return_track(0)\nresult = 'ok'")


def route(live: Any, idx: dict[str, int], groups: list[str], chans: list[dict[str, Any]]) -> None:
    """Each channel into its bus; buses into Main. A bus monitors In with no input of its own: it hears only the
    channels routed to it."""
    for g in groups:
        got = live.run(f"""t = song.tracks[{idx[BUSES[g]]}]
r = [x for x in t.available_input_routing_types if x.display_name == 'No Input']
t.input_routing_type = r[0]
t.current_monitoring_state = 0
result = [t.input_routing_type.display_name, t.current_monitoring_state]""")
        if got != ["No Input", 0]:
            raise Stopped(f"bus {g}: {got}")
    for c in chans:
        bus = BUSES[c["group"]]
        got = live.run(f"""t = song.tracks[{idx[c["id"]]}]
r = [x for x in t.available_output_routing_types if x.display_name == {bus!r}]
if r:
    t.output_routing_type = r[0]
result = t.output_routing_type.display_name""")
        if got != bus:
            raise Stopped(f"{c['id']} routes to {got!r}, wanted {bus!r}")


def clip_gain(live: Any, track: int, path: str, at: float, gain_db: float) -> None:
    """Set one clip's gain to `gain_db` by bisection on its display text: Live does not publish the gain law."""
    live.run(f"""t = song.tracks[{track}]
c = [c for c in t.arrangement_clips if abs(c.start_time - {float(at)}) < 1e-6 and c.file_path == {path!r}][0]
want = {float(gain_db)}
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


def main_gain(live: Any, db: float) -> None:
    """The Utility at the end of Main: the renders' headroom, and the loudness match for comparing."""
    if live.run("result = [d.class_name for d in song.master_track.devices][-1:]") != ["StereoGain"]:
        live.load_item("song.master_track", "audio_effects", None, "Utility")
    live.setp("song.master_track.devices[-1]", {"Output": f"{round(db, 2)} dB"})


def add_at_end(live: Any, track: str, device: str, values: dict[str, Any]) -> str:
    """Load `device` at the end of `track`'s chain and set its values; returns its LOM path."""
    live.load_item(track, "audio_effects", None, device)
    dev = f"{track}.devices[{len(live.devices(track)) - 1}]"
    live.setp(dev, values)
    return dev


def add_device(
    live: Any, idx: dict[str, int], target: str, device: str, values: dict[str, Any], fixed: Mapping[str, Any]
) -> str:
    """A mix-2 device at the end of a channel's or bus's chain, with its `fixed` settings and `values`."""
    return add_at_end(live, target_track(idx, target), device, {**fixed, **values})


def build(
    live: Any, loops: dict[str, Any], fx: dict[str, Any], arr: dict[str, Any], data: Path, tempo_bpm: float
) -> Built:
    """Empty the set in front and build it from the arrangement: tracks, routing and clips. The headroom goes on Main;
    mix 1 and the kept choices follow with `apply_mix`."""
    chans = channels(loops, arr)
    clips = {c["id"]: c for c in loops["clips"]}
    cands = {c["id"]: c for c in fx["candidates"]}
    live.run(f"song.tempo = {tempo_bpm}\nresult = 'ok'")
    groups = used_buses(chans)
    empty_set(live, [BUSES[g] for g in groups] + [c["id"] for c in chans])
    idx = tracks(live)
    route(live, idx, groups, chans)
    calls = clip_placements(arr, clips, cands, data)
    for k in range(0, len(calls), CLIPS_PER_CALL):
        code = "out = []\n"
        for lane, path, at, _ in calls[k : k + CLIPS_PER_CALL]:
            code += (
                f"t = song.tracks[{idx[lane]}]\nc = t.create_audio_clip({path!r}, {float(at)})\nc.warping = False\n"
                "out.append(c.end_time - c.start_time)\n"
            )
        live.run(code + "result = out")
    for lane, path, at, gain in calls:
        if gain:
            clip_gain(live, idx[lane], path, at, gain)
    main_gain(live, HEADROOM_DB)
    return Built(len(chans), len(groups), len(calls))


def apply_mix(
    live: Any, arr: dict[str, Any], chans: list[dict[str, Any]], data: Path, devices: Mapping[str, Mapping[str, Any]]
) -> None:
    """Mix 1 (gain, pan and cuts) on each channel: the mixer, and an EQ Eight for the cuts. Then the kept kick
    option, the kept mix-2 devices in the order they were kept (`devices` has each one's fixed settings), and
    the kept spectral fixes. Everything after the mixer is rebuilt from the structure each time."""
    idx = tracks(live)
    mix = (arr.get("mix") or {}).get("channels", {})
    for name in [c["id"] for c in chans] + list(BUSES.values()):
        if name in idx:
            live.run(f"t = song.tracks[{idx[name]}]\nwhile len(t.devices):\n    t.delete_device(0)\nresult = 'ok'")
    kick_option = arr.get("kickFuzz")  # kept on the kick or spectral page (kickfuzz.py): its loop, the kick turned
    if kick_option and "kick" in idx:
        swap_clips(live, f"song.tracks[{idx['kick']}]", str(data / "kickfuzz" / kick_option["loop"]))
    for c in chans:
        m = mix.get(c["id"], {})
        t = f"song.tracks[{idx[c['id']]}]"
        turned = float(kick_option["kickTurnedDb"]) if kick_option and c["id"] == "kick" else 0.0
        live.mixer(t, float(m.get("gainDb", 0.0)) + turned, (), float(m.get("pan", 0.0)))
        cut = cuts_eq_values(m.get("eq") or {})
        if cut is not None:
            live.load_item(t, "audio_effects", None, "EQ Eight")
            live.setp(f"{t}.devices[0]", cut)
    if kick_option and kick_option.get("bells"):  # the kept kick's match EQ (kickiso.py), after mix 1's cuts
        add_at_end(live, f"song.tracks[{idx['kick']}]", "EQ Eight", bell_eq_values(kick_option["bells"]))
    for k in arr.get("mix2") or []:
        add_device(live, idx, k["target"], k["device"], k["values"], devices[k["device"]].get("fixed", {}))
    for f in arr.get("spectral") or []:  # the spectral fixes kept (spectral.py): a gain move or a device
        for p in f["parts"]:
            if p["device"] == "gain":
                c = next(c for c in chans if c["id"] == p["target"])
                m = mix.get(c["id"], {})
                gain = float(m.get("gainDb", 0.0)) + p["values"]["dB"]
                live.mixer(f"song.tracks[{idx[c['id']]}]", gain, (), float(m.get("pan", 0.0)))
            else:
                t = "song.master_track" if p["target"] == "main" else target_track(idx, p["target"])
                add_at_end(live, t, p["device"], p["values"])
