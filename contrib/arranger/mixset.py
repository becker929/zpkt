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

    uv run python contrib/arranger/mixset.py build      # the mix set from the arrangement (HW002_121_pp_mix in front)
    uv run python contrib/arranger/mixset.py base       # render the mix as it stands (the reference)
    uv run python contrib/arranger/mixset.py worker     # render queued requests, one after another
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import hw002
from renderqueue import RenderQueue
from zpkt.live import recipe_build as rb

ROOT = Path(__file__).resolve().parents[2]
DATA = hw002.DATA
MIX2 = DATA / "mix2"
SET = hw002.MIX_SET
ARR_ID = hw002.CANONICAL
BAR = hw002.BEATS_PER_BAR
HEADROOM = (
    rb.HEADROOM_DB
)  # a Utility on the mix set's Main: the loops summed with mix 1 reach full scale, so renders leave room
FX_KINDS = rb.FX_KINDS
BUSES = rb.BUSES

# The devices the page offers, and the parameters a grid may move: (name in Live, unit, lo, hi) or (name, values).
DEVICES: dict[str, dict[str, Any]] = {
    "Saturator": {
        "what": "distortion",
        "params": [
            ("Drive", "dB", 0, 36),
            ("Type", ["Analog Clip", "Soft Sine", "Medium Curve", "Hard Curve", "Digital Clip"]),
            ("Dry/Wet", "%", 0, 100),
            ("Output", "dB", -36, 0),
        ],
    },
    "Drum Buss": {
        "what": "distortion and bus",
        "params": [
            ("Drive", "%", 0, 100),
            ("Crunch", "%", 0, 100),
            ("Boom Amt", "%", 0, 100),
            ("Transients", "", -1, 1),
            ("Drive Type", ["Soft", "Medium", "Hard"]),
            ("Dry/Wet", "%", 0, 100),
        ],
    },
    "EQ Eight": {
        "what": "EQ boost",
        "params": [("4 Frequency A", "Hz", 30, 16000), ("4 Gain A", "dB", 0, 15), ("4 Q A", "", 0.1, 4)],
        "fixed": {
            "4 Filter Type A": "Bell",
            "4 Filter On A": "On",
            **{f"{k} Filter On A": "Off" for k in (1, 2, 3, 5, 6, 7, 8)},
        },
    },
    "Compressor": {
        "what": "compression",
        "params": [
            ("Threshold", "dB", -40, 0),
            ("Ratio", ":1", 1, 20),
            ("Attack", "ms", 0.1, 100),
            ("Release", "ms", 10, 1000),
            ("Output", "dB", 0, 24),
            ("Dry/Wet", "%", 0, 100),
        ],
    },
    "Glue Compressor": {
        "what": "bus compression",
        "params": [
            ("Threshold", "dB", -40, 0),
            ("Ratio", ["2", "4", "10"]),
            ("Attack", [".01", ".1", ".3", "1", "3", "10", "30"]),
            ("Release", [".1", ".2", ".4", ".6", "1.2"]),
            ("Output", "dB", 0, 20),
            ("Dry/Wet", "%", 0, 100),
        ],
    },
}


def lo() -> Any:
    """hands' LiveOps for the mix set (hands' own data and renders under DATA/mix2)."""
    return hw002.live_ops(MIX2)


def load() -> tuple[dict, dict, dict]:
    """The loops index, the transition sounds and the canonical arrangement, from DATA."""
    loops = json.loads((DATA / "loops.json").read_text())
    fx = json.loads((DATA / "fx" / "fx.json").read_text())
    arr = json.loads((DATA / "arrangements" / f"{ARR_ID}.json").read_text())
    return loops, fx, arr


def channels(loops: dict, arr: dict) -> list[dict]:
    """The mix channels, as the mix pages make them: a lane of the arrangement, or a kind of transition laid over it."""
    return rb.channels(loops, arr)


def guard(L: Any) -> None:
    hw002.stop_unless_front(L, "mix set", SET)


def tracks(L: Any) -> dict[str, int]:
    """Track name -> index in the set."""
    return rb.tracks(L)


bell_eq_values = rb.bell_eq_values
cuts_eq_values = rb.cuts_eq_values


def _stopping(step: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """Run a recipe_build step; Live not being as it expects stops the script with the same "STOP:" line."""
    try:
        return step(*args, **kw)
    except rb.Stopped as e:
        sys.exit(f"STOP: {e}")


def swap_clips(L: Any, track: str, path: str, *, check: bool = False) -> None:
    """Point every arrangement clip of `track` at another audio file (zpkt.live.recipe_build.swap_clips)."""
    _stopping(rb.swap_clips, L, track, path, check=check)


def clip_placements(arr: dict, clips: dict, cands: dict) -> list[tuple[str, str, float, float | None]]:
    """Every audio clip the mix set holds (zpkt.live.recipe_build.clip_placements), from DATA."""
    return _stopping(rb.clip_placements, arr, clips, cands, DATA)


def build() -> None:
    """Empty the mix set in front and build it from the arrangement: tracks, routing, clips, mix 1 and the kept
    choices."""
    L = lo()
    guard(L)
    loops, fx, arr = load()
    built = _stopping(rb.build, L, loops, fx, arr, DATA, hw002.TEMPO_BPM)
    print(f"{built.channels} channels on {built.buses} buses, {built.clips} clips", flush=True)
    apply_mix(L, arr, channels(loops, arr))


def main_gain(L: Any, db: float) -> None:
    """The Utility at the end of Main: the renders' headroom, and the loudness match for comparing."""
    rb.main_gain(L, db)


def add_at_end(L: Any, track: str, device: str, values: dict[str, Any]) -> str:
    """Load `device` at the end of `track`'s chain and set its values; returns its LOM path."""
    return rb.add_at_end(L, track, device, values)


def apply_mix(L: Any, arr: dict, chans: list[dict]) -> None:
    """Mix 1 and the kept choices on the mix set (zpkt.live.recipe_build.apply_mix)."""
    _stopping(rb.apply_mix, L, arr, chans, DATA, DEVICES)
    print("mix applied", flush=True)


def target_track(idx: dict[str, int], target: str) -> str:
    """The LOM path of a channel ("kick") or a bus ("bus-kick")."""
    return _stopping(rb.target_track, idx, target)


def add_device(L: Any, idx: dict[str, int], target: str, device: str, values: dict[str, Any]) -> str:
    """A mix-2 device at the end of a channel's or bus's chain, with its fixed settings and `values`."""
    return _stopping(rb.add_device, L, idx, target, device, values, DEVICES[device].get("fixed", {}))


# ---- renders ------------------------------------------------------------------------------------------------------------


def to_flac(wav: Path, flac: Path, skip_beats: float = 0.0) -> None:
    """The render as 16-bit FLAC, its preroll cut off, in the repo's environment (audio extra). Only cut: no gain or processing."""
    code = (
        "import soundfile as sf, sys\nx, r = sf.read(sys.argv[1], always_2d=True)\n"
        f"n = round(float(sys.argv[3]) * r * 60 / {hw002.TEMPO_BPM:g})\n"
        "sf.write(sys.argv[2], x[n:], r, subtype='PCM_16')"
    )
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(ROOT),
            "--extra",
            "audio",
            "python",
            "-c",
            code,
            str(wav),
            str(flac),
            str(skip_beats),
        ],
        check=True,
    )
    wav.unlink()


def render(L: Any, out: Path, bars: tuple[int, int]) -> Path:
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
    """Integrated loudness of a file, measured in the repo's environment (audio extra)."""
    code = "import soundfile as sf, pyloudnorm as pl, sys\nx, r = sf.read(sys.argv[1])\nprint(pl.Meter(r).integrated_loudness(x))"
    out = subprocess.run(
        ["uv", "run", "--project", str(ROOT), "--extra", "audio", "python", "-c", code, str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return float(out.strip().splitlines()[-1])


def base() -> None:
    """Render the whole arrangement as the mix stands (the reference for mix 2)."""
    L = lo()
    guard(L)
    MIX2.mkdir(parents=True, exist_ok=True)
    print(render(L, MIX2 / "base-full.flac", hw002.SPAN))


def points(req: dict) -> list[dict]:
    """A batch's grid: every combination of its parameters' values, in the units Live shows (LiveOps.setp)."""
    axes = []
    for p in req["params"]:
        if p.get("values"):
            axes.append([(p["name"], v) for v in p["values"]])
            continue
        n = max(2, min(6, int(p["steps"])))
        lo_, hi_ = float(p["min"]), float(p["max"])
        if p.get("unit") == "Hz" or (p.get("log") and lo_ > 0):
            vals = [lo_ * (hi_ / lo_) ** (k / (n - 1)) for k in range(n)]
        else:
            vals = [lo_ + (hi_ - lo_) * k / (n - 1) for k in range(n)]
        unit = p.get("unit", "")
        axes.append([(p["name"], f"{round(v, 2)} {unit}" if unit and unit != ":1" else f"{round(v, 3)}") for v in vals])
    return [dict(c) for c in itertools.product(*axes)]


def run_request(L: Any, path: Path) -> None:
    """Render one batch: the mix as kept so far, then each grid point as it comes out and again with Main turned to
    the first render's loudness. The request file carries the progress the page shows."""
    req = json.loads(path.read_text())
    loops, _, arr = load()
    chans = channels(loops, arr)
    folder = MIX2 / req["id"]
    folder.mkdir(parents=True, exist_ok=True)
    bars = tuple(req.get("bars", (17, 32)))

    def status(**kw: Any) -> None:
        req.update(kw)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(req, indent=1))
        tmp.replace(path)

    pts = points(req)
    status(status="rendering", total=2 * len(pts) + 1, done=0, started=time.time())
    main_gain(L, HEADROOM)
    apply_mix(L, arr, chans)  # the mix as kept so far, without this request's device
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
        out.append(
            {
                "k": k,
                "values": values,
                "file": f,
                "matched": fm,
                "lufs": round(loud, 2),
                "matchDb": round(ref - loud, 2),
            }
        )
        status(done=2 * k + 3, points=out)
    L.run(f"t = {target_track(idx, req['target'])}\nt.delete_device(len(t.devices) - 1)\nresult = 'ok'")
    status(status="ready", finished=time.time())
    print(f"{req['id']}: {len(pts)} points", flush=True)


def render_queue() -> RenderQueue:
    return RenderQueue(MIX2 / "requests")


def queued_requests() -> list[Path]:
    """The batches waiting to render, oldest first (a request file that is not JSON stops the worker)."""
    return render_queue().queued(strict=True)


def worker() -> None:
    """Render queued requests oldest first, until none are left. Stops at the first surprise, and marks that batch
    failed with the reason for the page."""
    L = lo()
    guard(L)
    while True:
        queued = queued_requests()
        if not queued:
            print("queue empty", flush=True)
            return
        try:
            run_request(L, queued[0])
        except (Exception, SystemExit) as e:
            render_queue().fail(queued[0], str(e))
            raise


def catalog() -> dict:
    """What the page needs to offer: channels, buses and devices."""
    loops, _, arr = load()
    chans = channels(loops, arr)
    buses = [{"id": f"bus-{g}", "title": BUSES[g]} for g in BUSES if any(c["group"] == g for c in chans)]
    devices = {
        k: {
            "what": v["what"],
            "params": [
                {"name": p[0], "values": p[1]}
                if isinstance(p[1], list)
                else {"name": p[0], "unit": p[1], "min": p[2], "max": p[3]}
                for p in v["params"]
            ],
        }
        for k, v in DEVICES.items()
    }
    return {"channels": chans, "buses": buses, "devices": devices}


def write_catalog() -> None:
    MIX2.mkdir(parents=True, exist_ok=True)
    (MIX2 / "catalog.json").write_text(json.dumps(catalog(), indent=1))
    print(MIX2 / "catalog.json")


COMMANDS = {"build": build, "base": base, "worker": worker, "catalog": write_catalog}


def main(argv: list[str]) -> None:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        sys.exit(f"usage: mixset.py {{{'|'.join(COMMANDS)}}}")
    COMMANDS[argv[0]]()


if __name__ == "__main__":
    main(sys.argv[1:])
