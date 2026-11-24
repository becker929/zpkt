"""HW002 against its references, by spectrum: where the mix differs, and fixes for the biggest differences, made in Live.

Anthony (12 Nov 2026): "analyze the spectra of the references and the track, note the top 5 differences, explain them,
and then propose and execute fixes, and give me an A/B listening interface". The fixes are structure (a device and its
values on a channel or bus of the mix set), applied by Live and heard only as Live's renders, like mix 2.

    uv run --project hands python contrib/arranger/spectral.py before    # render the mix as the recipe stands (mix set in front)
    uv run --project ears  python contrib/arranger/spectral.py analyze   # spectra: the mix against the four HW002 references
    uv run --project hands python contrib/arranger/spectral.py after     # render each fix alone, then all of them together
    uv run --project ears  python contrib/arranger/spectral.py measure   # loudness and spectra of the renders, for the page
    uv run --project ears  python contrib/arranger/spectral.py compare [file.wav ...]  # fast read-only report against cached refs

Files in DATA/spectral: before.flac, fix-<id>.flac, after.flac, analysis.json (the comparison), fixes.json (the
proposed fixes, written by hand from the analysis), renders.json (what the page plays).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import hw002
import mixset

OUT = hw002.DATA / "spectral"
BARS = hw002.SPAN
REFS = hw002.DATA / "refs"
TEXTURE = hw002.DATA / "kickdesign" / "texture.json"  # kicktexture.py's measures, shown by compare
KSMS = "ksms-roses-of-flesh-and-blood"  # the canonical reference (Anthony, 13 Nov 2026)


# ---- in Live --------------------------------------------------------------------------------------------------------


def parts(fixes: list[dict]) -> list[dict]:
    return [p for f in fixes for p in f.get("parts", [f])]


def state(L: Any, arr: dict, chans: list[dict], fixes: list[dict]) -> None:
    """The mix set as the recipe stands, plus these fixes. A gain fix moves a channel's mix-1 gain; any other fix is a
    device with its values at the end of a channel's, bus's or Main's chain (on Main after the headroom Utility: a
    Utility and an EQ are both linear, so the order does not change the sound)."""
    arr = json.loads(json.dumps(arr))
    arr.pop(
        "spectral", None
    )  # the fixes already kept are not part of "before": every render starts from the recipe without them
    chs = arr.setdefault("mix", {}).setdefault("channels", {})
    for p in parts(fixes):
        if p["device"] == "gain":
            ch = chs.setdefault(p["target"], {"gainDb": 0.0, "pan": 0.0})
            ch["gainDb"] = float(ch.get("gainDb", 0.0)) + p["values"]["dB"]
    L.run("t = song.master_track\nwhile len(t.devices):\n    t.delete_device(0)\nresult = 'ok'")
    mixset.main_gain(L, mixset.HEADROOM)
    mixset.apply_mix(L, arr, chans)
    idx = mixset.tracks(L)
    for p in parts(fixes):
        if p["device"] == "gain":
            continue
        t = "song.master_track" if p["target"] == "main" else mixset.target_track(idx, p["target"])
        L.load_item(t, "audio_effects", None, p["device"])
        L.setp(f"{t}.devices[{len(L.devices(t)) - 1}]", p["values"])


def before() -> None:
    L = mixset.lo()
    mixset.guard(L)
    loops, _, arr = mixset.load()
    chans = mixset.channels(loops, arr)
    OUT.mkdir(parents=True, exist_ok=True)
    state(L, arr, chans, [])
    print(mixset.render(L, OUT / "before.flac", BARS), flush=True)


def after() -> None:
    L = mixset.lo()
    mixset.guard(L)
    loops, _, arr = mixset.load()
    chans = mixset.channels(loops, arr)
    fixes = json.loads((OUT / "fixes.json").read_text())["fixes"]
    only = set(sys.argv[2:])
    for fx in fixes:
        if not only or fx["id"] in only:
            state(L, arr, chans, [fx])
            print(mixset.render(L, OUT / f"fix-{fx['id']}.flac", BARS), flush=True)
    if not only or "all" in only:
        state(L, arr, chans, fixes)
        print(mixset.render(L, OUT / "after.flac", BARS), flush=True)
    state(L, arr, chans, [])  # leave the set as the recipe stands


# ---- measuring (ears) -----------------------------------------------------------------------------------------------

NB = 48  # log bands, 20 Hz to 20 kHz (a third of an octave is about 1/1.44 of these)
F0, F1 = 20.0, 20000.0
EDGES = [F0 * (F1 / F0) ** (k / NB) for k in range(NB + 1)]
CENTRES = [(EDGES[k] * EDGES[k + 1]) ** 0.5 for k in range(NB)]
REGIONS = [
    ("sub", 20, 60),
    ("bass", 60, 120),
    ("low mids", 120, 300),
    ("mud", 300, 600),
    ("mids", 600, 1500),
    ("upper mids", 1500, 4000),
    ("presence", 4000, 8000),
    ("air", 8000, 20000),
]


def spectrum(x, r, a: float, b: float):
    """The long-term average spectrum of seconds a..b (mono sum), in dB per log band, as power per band (so a band's
    level is what the ear sums there), with the loudness taken out: every curve is relative to its own LUFS over the
    same stretch, so the comparison is shape, not level."""
    import numpy as np
    import pyloudnorm as pl

    seg = x[int(a * r) : int(b * r)]
    lufs = pl.Meter(r).integrated_loudness(seg)
    m = seg.mean(axis=1)
    n = 8192
    win = np.hanning(n)
    acc = np.zeros(n // 2 + 1)
    hops = range(0, len(m) - n, n // 2)
    for i in hops:
        acc += np.abs(np.fft.rfft(m[i : i + n] * win)) ** 2
    acc /= max(1, len(hops))
    f = np.fft.rfftfreq(n, 1 / r)
    bands = []
    for k in range(NB):
        sel = (f >= EDGES[k]) & (f < EDGES[k + 1])
        p = acc[sel].sum() if sel.any() else acc[np.argmin(abs(f - CENTRES[k]))]
        bands.append(10 * np.log10(p + 1e-20))
    levels = np.array(bands)
    return levels - lufs, lufs


def side_ratio(x, r, a: float, b: float):
    """Per region: side energy against mid energy in dB (how wide each range is). -inf-ish = mono."""
    import numpy as np

    seg = x[int(a * r) : int(b * r)]
    mid, side = (seg[:, 0] + seg[:, 1]) / 2, (seg[:, 0] - seg[:, 1]) / 2
    M, S = np.abs(np.fft.rfft(mid)) ** 2, np.abs(np.fft.rfft(side)) ** 2
    f = np.fft.rfftfreq(len(mid), 1 / r)
    out = {}
    for name, lo_, hi_ in REGIONS:
        sel = (f >= lo_) & (f < hi_)
        out[name] = round(float(10 * np.log10((S[sel].sum() + 1e-12) / (M[sel].sum() + 1e-12))), 1)
    return out


def crest(x, r, a: float, b: float):
    """Peak to loudness (PLR): how much the peaks stand above the loudness."""
    import numpy as np
    import pyloudnorm as pl

    seg = x[int(a * r) : int(b * r)]
    return round(float(20 * np.log10(np.abs(seg).max() + 1e-12) - pl.Meter(r).integrated_loudness(seg)), 1)


def windows(drop: float, bar: float) -> dict:
    """Seconds into a file for each part, by bars around the drop (the track's bar 17 = a reference's drop)."""
    return {
        "build": (drop - 16 * bar, drop),
        "drop": (drop, drop + 16 * bar),
        "drop2": (drop + 16 * bar, drop + 24 * bar),
    }


def band_db(spec: list[float], lo_: float, hi_: float) -> float:
    """The power sum, in dB, of a spectrum's bands whose centres lie in lo_..hi_ Hz."""
    import numpy as np

    c = np.array(CENTRES)
    sel = (c >= lo_) & (c < hi_)
    return float(10 * np.log10((10 ** (np.array(spec)[sel] / 10)).sum()))


def region_of(f: float) -> str:
    return next(n for n, a, b in REGIONS if a <= f < b)


def measure_file(path: Path, drop: float, bar: float) -> dict:
    import soundfile as sf

    x, r = sf.read(path, always_2d=True)
    dur = len(x) / r
    out = {}
    for part, (a, b) in windows(drop, bar).items():
        a, b = max(0.0, a), min(dur, b)
        if b - a < 4 * bar:
            continue
        s, lufs = spectrum(x, r, a, b)
        out[part] = {
            "spectrum": [round(float(v), 2) for v in s],
            "lufs": round(float(lufs), 2),
            "side": side_ratio(x, r, a, b),
            "plr": crest(x, r, a, b),
        }
    return out


def analyze() -> None:
    import numpy as np

    refs = [r for r in json.loads((REFS / "refs.json").read_text())["refs"] if r["set"] == "hw002"]
    mine = measure_file(OUT / "before.flac", hw002.DROP_SECONDS, hw002.BAR_SECONDS)
    theirs = {r["id"]: measure_file(REFS / r["file"], r["drop"], r["barSeconds"]) for r in refs}
    res: dict[str, Any] = {
        "bands": {"n": NB, "centres": [round(c, 1) for c in CENTRES]},
        "regions": REGIONS,
        "mix": mine,
        "refs": theirs,
        "titles": {r["id"]: r["title"] for r in refs},
    }
    for part in ("drop", "build"):
        ref = np.array([theirs[k][part]["spectrum"] for k in theirs if part in theirs[k]])
        mean, lo_, hi_ = ref.mean(0), ref.min(0), ref.max(0)
        d = np.array(mine[part]["spectrum"]) - mean
        res[part] = {
            "refMean": [round(float(v), 2) for v in mean],
            "refMin": [round(float(v), 2) for v in lo_],
            "refMax": [round(float(v), 2) for v in hi_],
            "diff": [round(float(v), 2) for v in d],
            # outside the references' own spread: how far past the nearest reference
            "outside": [
                round(float(v - hi_[k]) if v > hi_[k] else float(v - lo_[k]) if v < lo_[k] else 0.0, 2)
                for k, v in enumerate(mine[part]["spectrum"])
            ],
        }
        print(
            f"\n{part}: mix {mine[part]['lufs']} LUFS, PLR {mine[part]['plr']}; refs "
            + ", ".join(f"{theirs[k][part]['lufs']}/{theirs[k][part]['plr']}" for k in theirs if part in theirs[k])
        )
        for k, c in enumerate(CENTRES):
            print(
                f"  {c:8.0f} Hz  mix {mine[part]['spectrum'][k]:6.1f}  refs {mean[k]:6.1f} [{lo_[k]:6.1f} .. {hi_[k]:6.1f}]"
                f"  diff {d[k]:+5.1f}  outside {res[part]['outside'][k]:+5.1f}"
            )
        print("  side/mid dB: mix", mine[part]["side"])
        for k in theirs:
            if part in theirs[k]:
                print("              ", k[:12], theirs[k][part]["side"])
    (OUT / "analysis.json").write_text(json.dumps(res))
    print(OUT / "analysis.json")


def measure() -> None:
    """Every render the page plays, measured the same way: loudness over the drop (the page's loudness match) and the
    drop's spectrum (its curve)."""
    import pyloudnorm as pl
    import soundfile as sf

    fixes = json.loads((OUT / "fixes.json").read_text())["fixes"]
    an = json.loads((OUT / "analysis.json").read_text())
    items: list[dict[str, Any]] = [{"id": "before", "title": "Before", "file": "before.flac"}]
    items += [
        {"id": f"fix-{f['id']}", "title": f["title"], "file": f"fix-{f['id']}.flac", "fix": f["id"]}
        for f in fixes
        if (OUT / f"fix-{f['id']}.flac").exists()
    ]
    if (OUT / "after.flac").exists():
        items.append({"id": "after", "title": "All fixes", "file": "after.flac"})
    for it in items:
        m = measure_file(OUT / it["file"], hw002.DROP_SECONDS, hw002.BAR_SECONDS)
        it.update(drop=m["drop"], build=m.get("build"))
        x, r = sf.read(OUT / it["file"], always_2d=True)
        it["lufsWhole"] = round(float(pl.Meter(r).integrated_loudness(x)), 2)
    refs = []
    for k, t in an["titles"].items():
        meta = next(r for r in json.loads((REFS / "refs.json").read_text())["refs"] if r["id"] == k)
        refs.append(
            {
                "id": k,
                "title": t,
                "file": meta["file"],
                "drop": meta["drop"],
                "bpm": meta["bpm"],
                "barSeconds": meta["barSeconds"],
                "lufsDrop": an["refs"][k]["drop"]["lufs"],
                "dropSpectrum": an["refs"][k]["drop"]["spectrum"],
            }
        )
    # each fix's result, measured: the gap to the references' average in its band, before and with the fix alone
    before_m = next(it for it in items if it["id"] == "before")
    after_m: dict[str, Any] | None = next((it for it in items if it["id"] == "after"), None)
    for f in fixes:
        fixed = next((x for x in items if x.get("fix") == f["id"]), None)
        if not fixed or "band" not in f:
            continue
        part = f.get("part", "drop")
        if f.get("measureBy") == "side":
            got = [m[part]["side"][f["region"]] for m in (before_m, fixed, after_m) if m]
            refs_side = [an["refs"][k][part]["side"][f["region"]] for k in an["refs"]]
            f["result"] = (
                f"side/mid in the {f['region']}: {got[0]:+.1f} dB before, {got[1]:+.1f} with this fix"
                + (f", {got[2]:+.1f} with all fixes" if len(got) > 2 else "")
                + f"; the references {min(refs_side):+.1f} to {max(refs_side):+.1f}"
            )
            continue
        ref = band_db(an[part]["refMean"], *f["band"])
        got = [band_db(m[part]["spectrum"], *f["band"]) - ref for m in (before_m, fixed, after_m) if m]
        f["result"] = (
            f"{part}, {f['band'][0]:g}–{f['band'][1]:g} Hz against the references' average: {got[0]:+.1f} dB before, "
            f"{got[1]:+.1f} with this fix" + (f", {got[2]:+.1f} with all fixes" if len(got) > 2 else "")
        )
    out = {
        "bands": an["bands"],
        "regions": an["regions"],
        "refMean": an["drop"]["refMean"],
        "refMin": an["drop"]["refMin"],
        "refMax": an["drop"]["refMax"],
        "renders": items,
        "refs": refs,
        "fixes": fixes,
        "note": json.loads((OUT / "fixes.json").read_text()).get("note", ""),
    }
    (OUT / "renders.json").write_text(json.dumps(out))
    for it in items:
        print(f"{it['id']:14s} drop {it['drop']['lufs']:6.2f} LUFS  PLR {it['drop']['plr']}")
    print(OUT / "renders.json")


def compare() -> None:
    """Fast read-only spectral comparison of given audio files (or before.flac) against cached analysis.json & texture.json."""
    an = json.loads((OUT / "analysis.json").read_text())
    paths = [Path(p).expanduser() for p in sys.argv[2:]] or [OUT / "before.flac"]
    measured = {p.stem: measure_file(p, hw002.DROP_SECONDS, hw002.BAR_SECONDS) for p in paths if p.exists()}
    if not measured:
        measured = {"before": an["mix"]}
    ksms_key = KSMS
    bands = [
        *REGIONS,
        ("deep sub", 20, 48),
        ("kick/bass body", 55, 120),
        ("1-4 kHz bite", 1000, 4000),
        ("8-14 kHz air", 8000, 14000),
    ]
    for part in ("drop", "build"):
        print(f"=== {part.upper()} DYNAMICS & STEREO ===")
        for name, m in measured.items():
            if part in m:
                print(
                    f"  {name:20s}: {m[part]['lufs']:6.2f} LUFS | PLR {m[part]['plr']:4.1f} dB | side/mid {m[part]['side']}"
                )
        for k, v in an["refs"].items():
            if part in v:
                print(
                    f"  {k[:20]:20s}: {v[part]['lufs']:6.2f} LUFS | PLR {v[part]['plr']:4.1f} dB | side/mid {v[part]['side']}"
                )
        print(f"\n=== {part.upper()} SPECTRAL BANDS (dB rel to LUFS) ===")
        for bname, lo_, hi_ in bands:
            r_vals = {k: band_db(v[part]["spectrum"], lo_, hi_) for k, v in an["refs"].items() if part in v}
            r_mean = band_db(an[part]["refMean"], lo_, hi_)
            ksms = r_vals.get(ksms_key, float("nan"))
            cols = " | ".join(
                f"{n}={band_db(m[part]['spectrum'], lo_, hi_):5.1f} (vs mean {band_db(m[part]['spectrum'], lo_, hi_) - r_mean:+5.1f}, vs KSMS {band_db(m[part]['spectrum'], lo_, hi_) - ksms:+5.1f})"
                for n, m in measured.items()
                if part in m
            )
            print(
                f"  {bname:16s} ({lo_:5g}-{hi_:5g} Hz): {cols} | refMean={r_mean:5.1f} [{min(r_vals.values()):5.1f}..{max(r_vals.values()):5.1f}] | KSMS={ksms:5.1f}"
            )
        print()
    fixes_p = OUT / "fixes.json"
    if fixes_p.exists():
        print("=== TOP SPECTRAL FIXES (fixes.json) ===")
        for f in json.loads(fixes_p.read_text()).get("fixes", []):
            print(
                f"  [{f['id']}] {f['title']} ({f.get('short', f.get('region', ''))}: {f.get('measure', '')}) -> {f.get('how', '')}"
            )
    tex_p = TEXTURE
    if tex_p.exists():
        print("\n=== KICK TEXTURE (1-6 kHz) ===")
        for k, v in json.loads(tex_p.read_text()).items():
            print(
                f"  {k:22s}: holdMh={v.get('holdMh')} ms | flatness={v.get('flatness')} | crest={v.get('crest')} dB | toKsms={v.get('toKsms')}"
            )


COMMANDS = {"before": before, "after": after, "analyze": analyze, "measure": measure, "compare": compare}


def main(argv: list[str]) -> None:
    """`after` and `compare` read further arguments from sys.argv[2:] (fix ids, files)."""
    if not argv or argv[0] not in COMMANDS:
        sys.exit(f"usage: spectral.py {{{'|'.join(COMMANDS)}}} [...]")
    COMMANDS[argv[0]]()


if __name__ == "__main__":
    main(sys.argv[1:])
