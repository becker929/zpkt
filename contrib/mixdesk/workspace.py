"""The HW002 finishing workspace in Live: a copy of the arranger's mix set with the devices the desk controls.

    uv run --project hands python contrib/mixdesk/workspace.py save     # HW002_121_pp_mix in front -> HW002_121_pp_finish
    uv run --project hands python contrib/mixdesk/workspace.py clean    # drop the stray panel tracks, tempo 160
    uv run --project hands python contrib/mixdesk/workspace.py devices  # add the desk's devices (once; skips what is there)

The mix set (contrib/arranger/mixset.py) holds the canonical arrangement 8d2a2 as one track per mix channel, routed to
a bus per group, with mix 1 and the kept kick on it. The desk adds, all at settings that change nothing until moved:
an EQ Eight, a Saturator and a Glue Compressor on the buses that need them (Saturator and Glue at 0 % wet), two
returns (Space, a Reverb; Echo, an Echo) with every send down, and on Main a Glue Compressor (0 % wet) and a Utility
for width and bass mono (off) before the mix set's -6 dB headroom Utility. Each step is one short LOM call, read back.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import finishing as F

from hands.live import hold, ui
from hands.live.inlive.tracks import track_expr
from hands.live.ops import LiveOps

SETS = F.SETS_DIR
SRC, SET = F.MIX_SET, F.SET
TEMPO = 160.0
DESK = Path(__file__).with_name("desk.json")


def front(live: LiveOps) -> str:
    return live.guard("mixdesk")


def save_as(live: LiveOps, name: str) -> Path:
    """File > Save Live Set As inside the HW002 project folder (it is a Live Project, so no new Project folder)."""
    target = SETS / f"{name}.als"
    if target.exists():
        sys.exit(f"STOP: {target} exists")
    # a Save panel left open (a macOS prompt held it) is reused; Save As opens in the set's own folder (HW002 links
    # to ~/Music/zpkt/sets), which the panel then need not leave
    return live.save_as(SETS, name, project=False)


def save(live: LiveOps) -> None:
    stamp = time.strftime("%Y-%m-%d")
    snap = f"{SRC}_unsaved_{stamp}"
    if ui.dialogs() == 0 and front(live) not in (SRC, snap):
        sys.exit(f"STOP: {SRC} is not in front")
    if not (SETS / f"{snap}.als").exists():
        print("snapshot:", save_as(live, snap))  # the mix set's unsaved state, kept as it was
    print("workspace:", save_as(live, SET))
    print("front:", front(live))


def names(live: LiveOps) -> list[str]:
    return live.run("result = [t.name for t in song.tracks]")


def require_front(live: LiveOps, set_name: str = SET) -> None:
    if front(live) != set_name:
        sys.exit(f"STOP: {set_name} is not in front")


def clean(live: LiveOps) -> None:
    require_front(live)
    while True:
        idx = [i for i, n in enumerate(names(live)) if n.startswith("panel ")]
        if not idx:
            break
        live.run(f"song.delete_track({idx[-1]})\nresult = 'ok'")
    live.run(f"song.tempo = {TEMPO}\nresult = 'ok'")
    print(live.run("result = [len(song.tracks), song.tempo]"))


# The desk's devices: name in the set -> (Live device, starting values in Live's own units). Neutral until moved.
EQ = {
    "1 Filter On A": "Off",
    "1 Filter Type A": "High Pass 12dB",
    "1 Frequency A": "30 Hz",
    "2 Filter On A": "On",
    "2 Filter Type A": "Low Shelf",
    "2 Frequency A": "120 Hz",
    "2 Gain A": "0.0 dB",
    "3 Filter On A": "Off",
    "5 Filter On A": "Off",
    "6 Filter On A": "Off",
    "8 Filter On A": "Off",
    "4 Filter On A": "On",
    "4 Filter Type A": "Bell",
    "4 Frequency A": "1600 Hz",
    "4 Gain A": "0.0 dB",
    "4 Q A": "1.00",
    "7 Filter On A": "On",
    "7 Filter Type A": "High Shelf",
    "7 Frequency A": "10000 Hz",
    "7 Gain A": "0.0 dB",
}
KICK_EQ = {**EQ, "2 Filter Type A": "Bell", "2 Frequency A": "45 Hz", "2 Q A": "1.00"}
SAT = {"Type": "Soft Sine", "Drive": "0.0 dB", "Dry/Wet": "0.0 %"}
GLUE = {"Dry/Wet": "0.0 %"}
DEVICES = {
    "Kick bus": [
        ("desk EQ", "EQ Eight", KICK_EQ),
        ("desk Sat", "Saturator", SAT),
        ("desk Glue", "Glue Compressor", GLUE),
    ],
    "Hats bus": [("desk EQ", "EQ Eight", EQ), ("desk Sat", "Saturator", SAT)],
    "Perc bus": [("desk EQ", "EQ Eight", EQ)],
    "Chord and splash bus": [("desk EQ", "EQ Eight", EQ), ("desk Sat", "Saturator", SAT)],
    "Break bus": [("desk EQ", "EQ Eight", EQ), ("desk Sat", "Saturator", SAT), ("desk Glue", "Glue Compressor", GLUE)],
    "Transitions bus": [("desk EQ", "EQ Eight", EQ)],
    "Main": [("desk Glue", "Glue Compressor", GLUE), ("desk Utility", "Utility", {"Bass Mono": "Off"})],
}
RETURNS = [("Space", "Reverb", "Dry/Wet"), ("Echo", "Echo", "Dry Wet")]


def devices(live: LiveOps) -> None:
    """The returns and desk devices, added where missing at neutral values (the caller has checked the set in
    front: `require_front`)."""
    have = live.run("result = [t.name for t in song.return_tracks]")
    for name, dev, wet in RETURNS:
        if not any(h[2:] == name or h == name for h in have):
            live.run(f"song.create_return_track()\nsong.return_tracks[-1].name = {name!r}\nresult = 'ok'")
        t = track_expr(name)
        if not live.run(f"result = len({t}.devices)"):
            live.load_item(t, "audio_effects", None, dev)
        live.setp(f"{t}.devices[0]", {wet: "100 %"})
    # the mix set's headroom Utility on Main gets a name the desk can find
    live.run(
        "d = song.master_track.devices[0]\nif d.class_name == 'StereoGain' and d.name == 'Utility':\n"
        "    d.name = 'desk headroom'\nresult = 'ok'"
    )
    for track, devs in DEVICES.items():
        for name, dev, values in devs:
            t = track_expr(track)
            if name in live.run(f"result = [d.name for d in {t}.devices]"):
                continue
            live.load_item(t, "audio_effects", None, dev)
            last = f"{t}.devices[len({t}.devices) - 1]"
            live.run(f"{last}.name = {name!r}\nresult = 'ok'")
            live.setp(last, values)
            print(track, "+", name, flush=True)
    print(
        json.dumps(
            live.run(
                "result = [[t.name, [d.name for d in t.devices]] for t in list(song.tracks)[:6] "
                "+ list(song.return_tracks) + [song.master_track]]"
            )
        )
    )


def checked_devices(live: LiveOps) -> None:
    require_front(live)
    devices(live)


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"save": save, "clean": clean, "devices": checked_devices}.get(step)
    if fn is None:
        sys.exit(__doc__)
    F.use_rig()
    live = F.ops()
    with hold.using_live(f"mixdesk workspace {step}"):
        fn(live)


if __name__ == "__main__":
    main()
