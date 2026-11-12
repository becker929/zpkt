"""Cut the bounced stems (bounce.py) into the arranger's loops and write loops.json.

    uv run --project hands python contrib/arranger/mine.py

Each stem is one part of the set, soloed, for the whole song. Bars are compared by a spectrogram feature; a stretch
whose bars repeat every p bars (p = 1, 2, 4 ... 32) becomes one loop of p bars, cut from its second pass so the
tail of the pass before is already in it and it loops as the set plays it. A stretch that does not repeat becomes a
one-shot with its tail. Loops that sound the same are kept once. The song's own arrangement comes out as a preset,
and that preset, summed, is checked against the bounced mix.

Cutting a render on the bar is all this does: no gain, no processing. Files are 16-bit FLAC, named by content.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pyloudnorm
import soundfile as sf

DATA = Path("~/_agent_scratch/arranger").expanduser()
STEMS = DATA / "raw" / "stems"
RATE, BAR = 44100, 66150            # 160 BPM: a bar is 1.5 s
PERIODS = (1, 2, 4, 8, 16, 32)
SILENT_DB = -62.0
SET = "HW002_121_full.als"

# lane id, title, group, colour, [(stem, title prefix, first bar of the stem in the song)]; a lane's first stem is the
# one the song preset uses
LANES = [
    ("kick", "Kick", "kick", "#ff6b5e", [("kick-rumble", "Kick + rumble", 0), ("kick", "Kick alone", 0), ("rumble", "Rumble alone", 0)]),
    ("perc1", "Perc 1", "perc", "#ffd34d", [("perc1", "Perc 1", 0)]),
    ("perc2", "Perc 2", "perc", "#c7e65a", [("perc2", "Perc 2", 0)]),
    ("crash", "Crash", "perc", "#8fe0a0", [("crash", "Crash", 0)]),
    ("splash", "Splash", "sfx", "#62c8f2", [("splash", "Splash", 0)]),
    ("chord", "Chord", "sfx", "#8aa4ff", [("chord", "Chord", 0)]),
    ("break", "Break, all", "break", "#c58cff", [("break", "Break", 80)]),
    ("break-horn", "Brk horn", "break", "#d9a3ff", [("break-horn", "Horn", 80)]),
    ("break-stab", "Brk stab", "break", "#e7a0e0", [("break-stab", "Stab", 80)]),
    ("break-chop", "Brk chop", "break", "#f2a3c4", [("break-chop", "Chop", 80)]),
    ("break-beatbox", "Brk beatbox", "break", "#f5b3a8", [("break-beatbox", "Beatbox", 80)]),
    ("break-hit", "Brk hit", "break", "#f7c9a0", [("break-hit", "Hit", 80)]),
]
SONG_ONLY_FIRST = {"break-horn", "break-stab", "break-chop", "break-beatbox", "break-hit"}  # in the song via "Break, all"


def features(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per bar: a log band spectrogram (24 bands, 128 frames), flattened, and the level in dB."""
    mono = x.mean(1)
    n = len(mono) // BAR
    win = np.hanning(1024)
    edges = np.unique(np.geomspace(1, 512, 25).astype(int))
    F, db = [], []
    for b in range(n):
        seg = mono[b * BAR:(b + 1) * BAR]
        db.append(20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9))
        S = np.abs(np.fft.rfft(np.lib.stride_tricks.sliding_window_view(seg, 1024)[::512] * win, axis=1))
        F.append(np.log1p(200 * np.stack([S[:, a:b_].sum(1) for a, b_ in zip(edges[:-1], edges[1:])], 1)).ravel())
    return np.array(F), np.array(db)


def dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(2 * np.linalg.norm(a - b) / (np.linalg.norm(a) + np.linalg.norm(b) + 1e-9))


def segments(F: np.ndarray, active: np.ndarray) -> tuple[list[tuple[int, int, int]], float]:
    """[(start bar, end bar, period)], period 0 for a stretch that does not repeat; and the threshold used."""
    n = len(F)
    D = {p: np.array([dist(F[k], F[k + p]) if active[k] and active[k + p] else 9.0 for k in range(n - p)]) for p in PERIODS if p < n}
    floor = np.array([min(D[p][k] for p in D if k < len(D[p])) for k in range(n - 1) if active[k]])
    floor = floor[floor < 1.0]
    # identical bars sit at the low end; a part that never repeats has no low end, so the threshold is capped
    thr = min(0.13, max(0.02, 1.3 * float(np.quantile(floor, 0.25)))) if len(floor) else 0.02
    out: list[tuple[int, int, int]] = []
    s = 0
    while s < n:
        if not active[s]:
            s += 1
            continue
        best = (0, 0, 9.0)                     # (extent, period, mean distance)
        soft = s == 0 or not active[s - 1]     # the first bar after silence has no tail from the bar before it
        for p, d in D.items():
            k = s
            while k < len(d) and (d[k] < thr or (soft and k == s and d[k] < 4 * thr)):
                k += 1
            reps = k - s
            if reps < (2 * p if thr >= 0.1 else p):   # under two passes (three where the match is loose): not a loop
                continue
            extent, mean = reps + p, float(d[s:k].mean())
            if extent > best[0] + best[1] or (extent >= best[0] and mean < 0.5 * best[2]):
                best = (extent, p, mean)
        if best[1]:
            out.append((s, s + best[0], best[1]))
            s += best[0]
        elif out and out[-1][2] == 0 and out[-1][1] == s:
            out[-1] = (out[-1][0], s + 1, 0)
            s += 1
        else:
            out.append((s, s + 1, 0))
            s += 1
    return out, thr


def peaks(x: np.ndarray, bars: float) -> list[float]:
    n = int(min(480, max(24, round(bars * 24))))
    mono = np.abs(x).max(1)
    cuts = np.linspace(0, len(mono), n + 1).astype(int)
    p = np.array([mono[a:b].max() if b > a else 0.0 for a, b in zip(cuts[:-1], cuts[1:])])
    return [round(float(v), 3) for v in p / (p.max() + 1e-9)]


def write(x: np.ndarray) -> str:
    (DATA / "audio").mkdir(parents=True, exist_ok=True)
    tmp = DATA / "audio" / "tmp.flac"
    sf.write(tmp, x, RATE, subtype="PCM_16", format="FLAC")
    name = hashlib.sha256(tmp.read_bytes()).hexdigest()[:16] + ".flac"
    tmp.replace(DATA / "audio" / name)
    return name


def main() -> None:
    clips, lanes, song, used = [], [], [], set()
    render = {}                                   # lane -> the song preset's audio for that lane, for the check
    for lane, title, group, colour, stems in LANES:
        lanes.append({"id": lane, "title": title, "group": group, "color": colour})
        for si, (stem, prefix, first) in enumerate(stems):
            x, sr = sf.read(STEMS / f"{stem}.wav", dtype="float32")
            assert sr == RATE
            F, db = features(x)
            active = db > SILENT_DB
            segs, thr = segments(F, active)
            print(f"{stem}: threshold {thr:.3f}; " + ", ".join(f"{a + first + 1}-{b + first}" + (f"/{p}" if p else " once") for a, b, p in segs))
            known: list[tuple[int, np.ndarray, str]] = []       # (period, feature, clip id)
            letter = 0
            prev = None                                          # the loop clip of the stretch just before
            for a, b, p in segs:
                off = 0
                if not p and prev and prev[1] == a and db[a] < db[a - 1] - 8:
                    # what rings on after a loop stops: kept as the loop's tail, not as a clip of its own
                    end = b
                    while end < len(db) and end < a + 4 and db[end] > -80 and not active[end]:
                        end += 1
                    if "tail" not in prev[0]:
                        audio = x[a * BAR:end * BAR].copy()
                        fade = min(len(audio), 2205)
                        audio[-fade:] *= np.linspace(1, 0, fade, dtype="float32")[:, None]
                        prev[0]["tail"], prev[0]["tailBars"] = write(audio), end - a
                    prev = None
                    continue
                if p:
                    src = a + p if b - a >= 3 * p else a          # a short stretch keeps its first pass, with its attack
                    feat = F[src:src + p]
                    match = None
                    for kp, kf, kid in known:
                        if kp != p:
                            continue
                        for r in range(p):                       # the same loop, entered r bars in
                            if dist(np.roll(kf, -r, axis=0), feat) < thr:
                                match, off = kid, r
                                break
                        if match:
                            break
                    if match is None:
                        audio = x[src * BAR:(src + p) * BAR]
                        match = f"{stem}-{chr(97 + letter)}"
                        clips.append({"id": match, "lane": lane, "title": f"{prefix} {chr(65 + letter)}", "kind": "loop", "bars": p,
                                      "fileBars": p, "file": write(audio), "peaks": peaks(audio, p), "src": {"stem": stem, "bar": src + first}})
                        known.append((p, feat, match))
                        letter += 1
                    region = {"lane": lane, "clip": match, "start": a + first, "len": b - a, "off": off}
                    prev = (next(c for c in clips if c["id"] == match), b)
                else:
                    end = b
                    while end < len(db) and end < b + 4 and db[end] > -80 and not active[end]:
                        end += 1                                 # the tail that rings into the silence after it
                    audio = x[a * BAR:end * BAR].copy()
                    fade = min(len(audio), 441)
                    audio[-fade:] *= np.linspace(1, 0, fade, dtype="float32")[:, None]
                    cid = next((kid for kp, kf, kid in known if kp == -(b - a) and dist(kf, F[a:b]) < max(thr, 0.05)), None)
                    if cid is None:                              # the same one-shot again is kept once
                        cid = f"{stem}-{chr(97 + letter)}"
                        clips.append({"id": cid, "lane": lane, "title": f"{prefix} {chr(65 + letter)}", "kind": "once", "bars": b - a,
                                      "fileBars": end - a, "file": write(audio), "peaks": peaks(audio, end - a), "src": {"stem": stem, "bar": a + first}})
                        known.append((-(b - a), F[a:b], cid))
                        letter += 1
                    region = {"lane": lane, "clip": cid, "start": a + first, "len": b - a, "off": 0}
                    prev = None
                if si == 0 and lane not in SONG_ONLY_FIRST:
                    song.append(region)
                    used.add(region["clip"])
    by_id = {c["id"]: c for c in clips}

    # the check: the song preset, summed the way the page plays it, against the bounced mix
    mix, _ = sf.read(STEMS / "mix.wav", dtype="float32")
    total = np.zeros_like(mix)
    cache = {}

    def audio_of(name: str) -> np.ndarray:
        if name not in cache:
            cache[name] = sf.read(DATA / "audio" / name, dtype="float32")[0]
        return cache[name]

    for r in song:
        c = by_id[r["clip"]]
        a = audio_of(c["file"])
        if c.get("tail"):
            t, at_end = audio_of(c["tail"]), (r["start"] + r["len"]) * BAR
            n = min(len(t), len(total) - at_end)
            if n > 0:
                total[at_end:at_end + n] += t[:n]
        at = r["start"] * BAR
        if c["kind"] == "once":
            n = min(len(a), len(total) - at)
            total[at:at + n] += a[:n]
        else:
            for i in range(r["len"]):
                ph = (i + r["off"]) % c["bars"]
                bar = a[ph * BAR:(ph + 1) * BAR]
                n = min(BAR, len(total) - (at + i * BAR))
                total[at + i * BAR:at + i * BAR + n] += bar[:n]
    meter = pyloudnorm.Meter(RATE)
    lu = meter.integrated_loudness(total) - meter.integrated_loudness(mix)
    Fm, dbm = features(mix)
    Ft, dbt = features(total)
    d = np.array([dist(Fm[k], Ft[k]) for k in range(len(Fm)) if dbm[k] > SILENT_DB])
    lvl = np.array([dbt[k] - dbm[k] for k in range(len(Fm)) if dbm[k] > SILENT_DB])
    check = (f"Check: the song preset, summed as this page plays it, is {lu:+.1f} LU from Live's own bounce of the mix; "
             f"bar by bar the level differs by {np.median(np.abs(lvl)):.1f} dB (median) and {np.abs(lvl).max():.1f} dB (worst bar).")
    print(check)
    print(f"bar distance to the mix: median {np.median(d):.3f}, 90% {np.quantile(d, .9):.3f}, max {d.max():.3f}; peak of the sum {np.abs(total).max():.3f}, of the mix {np.abs(mix).max():.3f}")
    worst = np.argsort(-np.abs(dbt - dbm) * (dbm > SILENT_DB))[:8]
    print("worst bars:", [(int(k) + 1, round(float(dbt[k] - dbm[k]), 1)) for k in worst])

    files = {c["file"] for c in clips} | {c["tail"] for c in clips if c.get("tail")}
    for f in (DATA / "audio").glob("*.flac"):
        if f.name not in files:
            f.unlink()
    size = sum((DATA / "audio" / f).stat().st_size for f in files)
    out = {"set": SET, "made": time.strftime("%-d %b %Y"), "bpm": 160, "rate": RATE, "barSeconds": BAR / RATE, "lanes": lanes,
           "clips": clips, "check": check,
           "presets": [{"name": "The song", "bars": 180, "regions": song},
                       {"name": "First drop", "bars": 32, "regions": [r for r in song if r["start"] < 32 and (r["start"] + r["len"] <= 32 or by_id[r["clip"]]["kind"] == "loop")]}]}
    for r in out["presets"][1]["regions"]:
        r2 = dict(r)
        r2["len"] = min(r["len"], 32 - r["start"])
        out["presets"][1]["regions"][out["presets"][1]["regions"].index(r)] = r2
    (DATA / "loops.json").write_text(json.dumps(out))
    print(f"{len(clips)} clips ({sum(c['kind'] == 'loop' for c in clips)} loops), {len(files)} files, {size / 1e6:.1f} MB; song preset {len(song)} regions")


if __name__ == "__main__":
    main()
