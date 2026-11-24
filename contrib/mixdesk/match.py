"""Matching the finishing set to the HW002 references, in Live: renders, bus solo renders, snapshots, and plans.

    uv run --project hands python contrib/mixdesk/match.py render NAME            # bars 1-40 of HW002_121_pp_finish
    uv run --project hands python contrib/mixdesk/match.py stems [--as P] [BUS..] # each bus soloed, same bars -> P-<bus>.flac
    uv run --project hands python contrib/mixdesk/match.py snapshot NAME          # every value the desk could touch
    uv run --project hands python contrib/mixdesk/match.py apply PLAN.json        # set a plan's values, read them back
    uv run --project hands python contrib/mixdesk/match.py eqfit-moves OUT.json   # fit.json as an mlab eqfit moves spec
    uv run --project hands python contrib/mixdesk/match.py plan-from-fit FIT_OUT.json PLAN.json   # eqfit result -> plan

Renders land in ~/_agent_scratch/mixdesk/renders as FLAC; measure.py (ears) reads them. A plan is a list of moves,
each a track and either a device parameter or a mixer value, in Live's own units:

    {"moves": [{"track": "Hats bus", "device": "desk EQ", "param": "7 Gain A", "value": "-6.0 dB"},
               {"track": "fx-downlifter", "param": "volume", "value": "-5.0 dB"}]}

Everything here happens in Live with the set's own devices (contrib/docs/sound.md); nothing is processed offline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = Path("~/_agent_scratch/mixdesk").expanduser()
RENDERS, SNAPS = OUT / "renders", OUT / "snapshots"
os.environ["ZPKT_SETS_DIR"] = str(Path("~/_agent_scratch/HW002").expanduser())
os.environ["ZPKT_SET_PREFIXES"] = "HW002_121_pp_"
os.environ.setdefault("ZPKT_DATA_DIR", str(OUT / "data"))
os.environ.setdefault("ZPKT_RENDERS_DIR", str(RENDERS))
from hands.live import hold, ui  # noqa: E402
from hands.live.export import SavePanel  # noqa: E402
from hands.live.inlive import with_source  # noqa: E402
from hands.live.ops import LiveOps  # noqa: E402
from hands.live.transport import LiveClient  # noqa: E402

SET = "HW002_121_pp_finish"
BAR = 4.0
BARS = (1, 40)          # the whole 8d2a2 arrangement: build 1-16, drop 17-32, horn's return 33-40
BUSES = ["Kick bus", "Hats bus", "Perc bus", "Chord and splash bus", "Break bus", "Transitions bus"]
# the Save panel opens where the last export went; this folder is one it has reached before. It is reached by the Go
# to Folder sheet when it is not already there: the Where popup's menu does not open by accessibility on this Mac
# (2026-11-22).
L = LiveOps(
    LiveClient(), staging=Path("~/_agent_scratch/arranger/raw").expanduser(), save_panel=SavePanel(reach="go_to_folder")
)


def tr(name: str) -> str:
    if name.lower() in ("main", "master"):
        return "song.master_track"
    return (f"next(x for x in list(song.tracks) + list(song.return_tracks) "
            f"if x.name == {name!r} or x.name[1:] == {'-' + name!r})")


def front() -> None:
    got = L.guard("mixdesk match")
    if got != SET:
        sys.exit(f"STOP: {got} is in front, not {SET}")


def _front_app() -> str:
    return ui.osa('tell application "System Events" to get name of first application process whose frontmost is true')


def give_back(was: str) -> None:
    """Anthony uses this Mac while Live renders: hand the front back to whatever had it."""
    if was and was != "Live" and _front_app() == "Live":
        ui.osa(f'tell application "System Events" to set frontmost of process {json.dumps(was)} to true')


def to_flac(wav: Path, flac: Path) -> None:
    code = ("import soundfile as sf, sys\nx, r = sf.read(sys.argv[1], always_2d=True)\n"
            "sf.write(sys.argv[2], x, r, subtype='PCM_24')")
    subprocess.run([str(Path("~/.local/bin/uv").expanduser()), "run", "--project", str(ROOT / "ears"), "python", "-c",
                    code, str(wav), str(flac)], check=True, capture_output=True)
    wav.unlink()


def solo(names: list[str]) -> None:
    want = sorted(names)
    L.run("for t in list(song.tracks) + list(song.return_tracks):\n"
          f"    t.solo = t.name in {set(names)!r}\nresult = 'ok'")
    got = sorted(L.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks) if t.solo]"))
    if got != want:
        sys.exit(f"STOP: soloed {got}, wanted {want}")


def render(name: str, solo_names: list[str] | None = None) -> Path:
    RENDERS.mkdir(parents=True, exist_ok=True)
    out = RENDERS / f"{name}.flac"
    wav = RENDERS / f"{name}.wav"
    for p in (out, wav, L.staging / wav.name):
        if p.exists():
            p.unlink()
    a, b = BARS
    t0 = time.time()
    try:
        solo(solo_names or [])
        L.export(wav, (a - 1) * BAR, (b - a + 1) * BAR, bits=24, timeout_s=600)
    finally:
        if solo_names:
            solo([])
    to_flac(wav, out)
    print(f"{out}  ({time.time() - t0:.0f} s)", flush=True)
    return out


def snapshot(name: str) -> Path:
    """Every track's mixer (volume, pan, sends, mute, solo) and every device's parameters, as Live shows them. One
    device and at most 20 parameters per call (ableton-guide Rule 2)."""
    SNAPS.mkdir(parents=True, exist_ok=True)
    rows = L.run("result = [t.name for t in list(song.tracks) + list(song.return_tracks)] + ['Main']")
    snap = {"set": SET, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "tracks": {}}
    for n in rows:
        t = tr(n)
        mix = L.run(f"t = {t}\nm = t.mixer_device\n"
                    "result = {'volume': str(m.volume), 'volumeRaw': m.volume.value, 'pan': str(m.panning), "
                    "'sends': [str(s) for s in m.sends], 'sendsRaw': [s.value for s in m.sends], "
                    + ("'mute': False, 'solo': False}" if n == "Main" else "'mute': bool(t.mute), 'solo': bool(t.solo)}"))
        devs = []
        for k, (dname, cls, count) in enumerate(L.run(f"result = [[d.name, d.class_name, len(d.parameters)] for d in {t}.devices]")):
            params = []
            for a in range(0, count, 20):
                params += L.run(f"d = {t}.devices[{k}]\nresult = [[p.name, str(p), p.value] for p in list(d.parameters)[{a}:{a + 20}]]")
            devs.append({"name": dname, "class": cls, "params": params})
        snap["tracks"][n] = {"mixer": mix, "devices": devs}
    path = SNAPS / f"{name}.json"
    path.write_text(json.dumps(snap, indent=1))
    print(path)
    return path


def apply(plan_path: str) -> None:
    plan = json.loads(Path(plan_path).read_text())
    for m in plan["moves"]:
        t = tr(m["track"])
        if m.get("device"):
            dev = f"next(d for d in {t}.devices if d.name == {m['device']!r})"
            L.setp(dev, {m["param"]: m["value"]})
            got = L.run(f"result = str(next(p for p in {dev}.parameters if p.name == {m['param']!r}))")
        elif m["param"] == "volume":
            L.mixer(t, float(str(m["value"]).split()[0]))
            got = L.run(f"result = str({t}.mixer_device.volume)")
        elif m["param"].startswith("send:"):
            ret = m["param"][5:]
            i = L.run(f"result = next(k for k, r in enumerate(song.return_tracks) if r.name == {ret!r} or r.name[1:] == {'-' + ret!r})")
            bad = L.run(with_source(f"result = set_shown({t}.mixer_device.sends[{i}], {str(m['value'])!r}, 'send')", "shown"))
            if bad:
                sys.exit(f"STOP: {m}: {bad}")
            got = L.run(f"result = str({t}.mixer_device.sends[{i}])")
        elif m["param"] in ("mute", "solo"):
            L.run(f"{t}.{m['param']} = {bool(m['value'])!r}\nresult = 'ok'")
            got = L.run(f"result = {t}.{m['param']}")
        else:
            sys.exit(f"STOP: unknown move {m}")
        print(f"{m['track']:22s} {m.get('device', ''):14s} {m['param']:16s} -> {got}", flush=True)


FIT = HERE / "fit.json"
MIN_GAIN_DB = 0.1      # a fitted band or trim smaller than this is left where it is


def _hz(f: float) -> str:
    return f"{f:.3g} Hz" if f < 1000 else f"{f:.0f} Hz"


def eqfit_moves() -> dict:
    """fit.json's controls as an mlab eqfit moves spec (stems in the same order, bands in the same order)."""
    spec = json.loads(FIT.read_text())
    out = {}
    for stem, c in spec["controls"].items():
        eq = [{k: b[k] for k in ("kind", "f", "gain_db", "q") if k in b} for b in c["bands"]]
        out[stem] = {"eq": eq, "gain_db": c.get("fader", 0.0)}
    return out


def plan_from_fit(fit_out: dict) -> dict:
    """An mlab eqfit result -> a plan for `apply`: each fitted band that moves more than MIN_GAIN_DB becomes its desk
    EQ band (on, type, frequency, gain, Q); each fader trim a bus volume; then fit.json's moves on Main."""
    spec = json.loads(FIT.read_text())
    moves, kept = [], []
    for stem, c in spec["controls"].items():
        got = fit_out["plan"].get(stem)
        if not got:
            continue
        for b, g in zip(c["bands"], got["eq"]):
            if abs(g["gain_db"]) < MIN_GAIN_DB:
                continue
            n = b["band"]
            dev = {"track": stem, "device": "desk EQ"}
            moves += [{**dev, "param": f"{n} Filter On A", "value": "On"},
                      {**dev, "param": f"{n} Filter Type A", "value": b["type"]},
                      {**dev, "param": f"{n} Frequency A", "value": _hz(g["f"])},
                      {**dev, "param": f"{n} Gain A", "value": f"{g['gain_db']:.1f} dB"},
                      {**dev, "param": f"{n} Q A", "value": f"{g['q']:.2f}"}]
            kept.append(f"{stem} {b['label']}: {g['gain_db']:+.1f} dB at {_hz(g['f'])}, Q {g['q']:.2f}")
        if abs(got.get("gain_db", 0.0)) >= MIN_GAIN_DB:
            moves.append({"track": stem, "param": "volume", "value": f"{got['gain_db']:.1f} dB"})
            kept.append(f"{stem} fader {got['gain_db']:+.1f} dB")
    moves += spec.get("main", [])
    return {"note": "the reference match, from mlab eqfit (fit.json)", "kept": kept, "moves": moves}


def main() -> None:
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "plan-from-fit":   # FIT_OUT.json PLAN.json: no Live needed
        plan = plan_from_fit(json.loads(Path(args[0]).read_text()))
        Path(args[1]).write_text(json.dumps(plan, indent=1))
        print("\n".join(plan["kept"]) + f"\n{len(plan['moves'])} moves -> {args[1]}")
        return
    if cmd == "eqfit-moves":     # OUT.json: fit.json as mlab eqfit's moves spec
        Path(args[0]).write_text(json.dumps(eqfit_moves(), indent=1))
        return
    if cmd not in ("render", "stems", "snapshot", "apply"):
        sys.exit(__doc__)
    was = _front_app()
    with hold.using_live(f"mixdesk match {cmd}"):
        try:
            front()
            if cmd == "render":
                render(args[0])
            elif cmd == "stems":   # stems [--as PREFIX] [BUS ...]: PREFIX defaults to "stem"
                prefix = "stem"
                if args[:1] == ["--as"]:
                    prefix, args = args[1], args[2:]
                for b in (args or BUSES):
                    render(prefix + "-" + b.lower().replace(" ", "-"), [b])
            elif cmd == "snapshot":
                snapshot(args[0])
            elif cmd == "apply":
                apply(args[0])
        finally:
            give_back(was)


if __name__ == "__main__":
    main()
