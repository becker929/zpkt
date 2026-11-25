"""Cut the bounced stems (bounce.py) into the arranger's loops and write loops.json.

    uv run --extra audio python contrib/arranger/mine.py   # numpy, soundfile and pyloudnorm: ears has them

Each stem is one part of the set, soloed, for the whole song. Bars are compared by a spectrogram feature; a stretch
whose bars repeat every p bars (p = 1, 2, 4 ... 32) becomes one loop of p bars, cut from its second pass so the
tail of the pass before is already in it and it loops as the set plays it. A stretch that does not repeat becomes a
one-shot with its tail. Loops that sound the same are kept once. The song's own arrangement comes out as a preset,
and that preset, summed, is checked against the bounced mix.

Cutting a render on the bar is all this does: no gain, no processing. Files are 16-bit FLAC, named by content.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time

import numpy as np
import pyloudnorm
import soundfile as sf

import hw002

DATA = hw002.DATA
STEMS = DATA / "raw" / "stems"
RATE, BAR = hw002.RATE, hw002.BAR_SAMPLES
PERIODS = (1, 2, 4, 8, 16, 32)
SILENT_DB = -62.0
SET = "HW002_121_full.als"

# lane id, title, group, colour, [(stem, title prefix, first bar of the stem in the song)]; a lane's first stem is the
# one the song preset uses
LANES = [
    (
        "kick",
        "Kick",
        "kick",
        "#ff6b5e",
        [("kick-rumble", "Kick + rumble", 0), ("kick", "Kick alone", 0), ("rumble", "Rumble alone", 0)],
    ),
    ("perc1", "Perc 1", "perc", "#ffd34d", [("perc1", "Perc 1", 0)]),
    ("perc2", "Perc 2", "perc", "#c7e65a", [("perc2", "Perc 2", 0)]),
    # single pads of the two hat racks, each alone through its track's devices: layers to stack by hand
    ("p1-oh", "P1 open", "hats", "#ffe27a", [("p1-oh", "P1 open hat", 0)]),
    ("p1-ch", "P1 closed", "hats", "#ffe27a", [("p1-ch", "P1 closed hat", 0)]),
    ("p1-rd", "P1 ride", "hats", "#ffe27a", [("p1-rd", "P1 ride", 0)]),
    ("p1-oh66", "P1 open 2", "hats", "#ffe27a", [("p1-oh66", "P1 open hat 2", 0)]),
    ("p2-rd2", "P2 ride 2", "hats", "#d5ec7e", [("p2-rd2", "P2 ride 2", 0)]),
    ("p2-rd1", "P2 ride 1", "hats", "#d5ec7e", [("p2-rd1", "P2 ride 1", 0)]),
    ("p2-oh", "P2 open", "hats", "#d5ec7e", [("p2-oh", "P2 open hat", 0)]),
    ("p2-ch27", "P2 closed 2", "hats", "#d5ec7e", [("p2-ch27", "P2 closed hat 2", 0)]),
    ("p2-ch1", "P2 closed 1", "hats", "#d5ec7e", [("p2-ch1", "P2 closed hat 1", 0)]),
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
SONG_ONLY_FIRST = {
    "break-horn",
    "break-stab",
    "break-chop",
    "break-beatbox",
    "break-hit",
    "p1-oh",
    "p1-ch",
    "p1-rd",
    "p1-oh66",
    "p2-rd2",
    "p2-rd1",
    "p2-oh",
    "p2-ch27",
    "p2-ch1",
}  # in the song via "Break, all"


def features(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per bar: a log band spectrogram (24 bands, 128 frames), flattened, and the level in dB."""
    mono = x.mean(1)
    n = len(mono) // BAR
    win = np.hanning(1024)
    edges = np.unique(np.geomspace(1, 512, 25).astype(int))
    F, db = [], []
    for b in range(n):
        seg = mono[b * BAR : (b + 1) * BAR]
        db.append(20 * np.log10(np.sqrt((seg**2).mean()) + 1e-9))
        S = np.abs(np.fft.rfft(np.lib.stride_tricks.sliding_window_view(seg, 1024)[::512] * win, axis=1))
        F.append(np.log1p(200 * np.stack([S[:, a:b_].sum(1) for a, b_ in itertools.pairwise(edges)], 1)).ravel())
    return np.array(F), np.array(db)


def dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(2 * np.linalg.norm(a - b) / (np.linalg.norm(a) + np.linalg.norm(b) + 1e-9))


def segments(F: np.ndarray, active: np.ndarray) -> tuple[list[tuple[int, int, int]], float]:
    """[(start bar, end bar, period)], period 0 for a stretch that does not repeat; and the threshold used."""
    n = len(F)
    D = {
        p: np.array([dist(F[k], F[k + p]) if active[k] and active[k + p] else 9.0 for k in range(n - p)])
        for p in PERIODS
        if p < n
    }
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
        best = (0, 0, 9.0)  # (extent, period, mean distance)
        soft = s == 0 or not active[s - 1]  # the first bar after silence has no tail from the bar before it
        for p, d in D.items():
            k = s
            while k < len(d) and (d[k] < thr or (soft and k == s and d[k] < 4 * thr)):
                k += 1
            reps = k - s
            if reps < (2 * p if thr >= 0.1 else p):  # under two passes (three where the match is loose): not a loop
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
    p = np.array([mono[a:b].max() if b > a else 0.0 for a, b in itertools.pairwise(cuts)])
    return [round(float(v), 3) for v in p / (p.max() + 1e-9)]


def write(x: np.ndarray) -> str:
    (DATA / "audio").mkdir(parents=True, exist_ok=True)
    tmp = DATA / "audio" / "tmp.flac"
    sf.write(tmp, x, RATE, subtype="PCM_16", format="FLAC")
    name = hashlib.sha256(tmp.read_bytes()).hexdigest()[:16] + ".flac"
    tmp.replace(DATA / "audio" / name)
    return name


def fade_out(x: np.ndarray, samples: int) -> np.ndarray:
    """A copy of `x` with a linear fade over its last `samples` (or all of it, if shorter)."""
    y = x.copy()
    n = min(len(y), samples)
    y[-n:] *= np.linspace(1, 0, n, dtype="float32")[:, None]
    return y


def ring_end(db: np.ndarray, active: np.ndarray, start: int, limit: int) -> int:
    """The bar after the quiet bars that follow `start` and still ring (above -80 dB), at most up to `limit`."""
    end = start
    while end < len(db) and end < limit and db[end] > -80 and not active[end]:
        end += 1
    return end


def cut_stem(lane: str, stem: str, prefix: str, first: int, clips: list[dict]) -> list[dict]:
    """Cut one stem into clips (appended to `clips`) and return the regions that play it as the song does."""
    x, sr = sf.read(STEMS / f"{stem}.wav", dtype="float32")
    assert sr == RATE, f"{stem}.wav is {sr} Hz; the stems are bounced at {RATE}"
    F, db = features(x)
    active = db > SILENT_DB
    segs, thr = segments(F, active)
    print(
        f"{stem}: threshold {thr:.3f}; "
        + ", ".join(f"{a + first + 1}-{b + first}" + (f"/{p}" if p else " once") for a, b, p in segs)
    )
    known: list[tuple[int, np.ndarray, str]] = []  # (period, feature, clip id); a one-shot's period is minus its bars
    regions = []
    prev = None  # (the loop clip of the stretch just before, where that stretch ends)

    def new_clip(kind: str, bars: int, file_bars: int, audio: np.ndarray, src_bar: int) -> str:
        letter = len(known)
        cid = f"{stem}-{chr(97 + letter)}"
        clips.append(
            {
                "id": cid,
                "lane": lane,
                "title": f"{prefix} {chr(65 + letter)}",
                "kind": kind,
                "bars": bars,
                "fileBars": file_bars,
                "file": write(audio),
                "peaks": peaks(audio, file_bars),
                "src": {"stem": stem, "bar": src_bar},
            }
        )
        return cid

    for a, b, p in segs:
        off = 0
        if not p and prev and prev[1] == a and db[a] < db[a - 1] - 8:
            # what rings on after a loop stops: kept as the loop's tail, not as a clip of its own
            end = ring_end(db, active, b, a + 4)
            if "tail" not in prev[0]:
                prev[0]["tail"], prev[0]["tailBars"] = write(fade_out(x[a * BAR : end * BAR], 2205)), end - a
            prev = None
            continue
        if p:
            src = a + p if b - a >= 3 * p else a  # a short stretch keeps its first pass, with its attack
            feat = F[src : src + p]
            match = None
            for kp, kf, kid in known:
                if kp != p:
                    continue
                for r in range(p):  # the same loop, entered r bars in
                    if dist(np.roll(kf, -r, axis=0), feat) < thr:
                        match, off = kid, r
                        break
                if match:
                    break
            if match is None:
                match = new_clip("loop", p, p, x[src * BAR : (src + p) * BAR], src + first)
                known.append((p, feat, match))
            regions.append({"lane": lane, "clip": match, "start": a + first, "len": b - a, "off": off})
            prev = (next(c for c in clips if c["id"] == match), b)
        else:
            end = ring_end(db, active, b, b + 4)  # the tail that rings into the silence after it
            cid = next((kid for kp, kf, kid in known if kp == -(b - a) and dist(kf, F[a:b]) < max(thr, 0.05)), None)
            if cid is None:  # the same one-shot again is kept once
                cid = new_clip("once", b - a, end - a, fade_out(x[a * BAR : end * BAR], 441), a + first)
                known.append((-(b - a), F[a:b], cid))
            regions.append({"lane": lane, "clip": cid, "start": a + first, "len": b - a, "off": 0})
            prev = None
    return regions


def sum_song(song: list[dict], by_id: dict[str, dict], length: int) -> np.ndarray:
    """The song preset summed as the page plays it: loops by the bar, one-shots whole, each loop's tail at its end."""
    total = np.zeros((length, 2), dtype="float32")
    cache: dict[str, np.ndarray] = {}

    def audio_of(name: str) -> np.ndarray:
        if name not in cache:
            cache[name] = sf.read(DATA / "audio" / name, dtype="float32")[0]
        return cache[name]

    def add(x: np.ndarray, at: int) -> None:
        n = min(len(x), len(total) - at)
        if n > 0:
            total[at : at + n] += x[:n]

    for r in song:
        c = by_id[r["clip"]]
        a = audio_of(c["file"])
        if c.get("tail"):
            add(audio_of(c["tail"]), (r["start"] + r["len"]) * BAR)
        at = r["start"] * BAR
        if c["kind"] == "once":
            add(a, at)
            continue
        for i in range(r["len"]):
            ph = (i + r["off"]) % c["bars"]
            add(a[ph * BAR : (ph + 1) * BAR], at + i * BAR)
    return total


def check(song: list[dict], by_id: dict[str, dict]) -> str:
    """The song preset, summed, against Live's bounce of the mix: loudness, level bar by bar, spectral distance."""
    mix, _ = sf.read(STEMS / "mix.wav", dtype="float32")
    total = sum_song(song, by_id, len(mix))
    meter = pyloudnorm.Meter(RATE)
    lu = meter.integrated_loudness(total) - meter.integrated_loudness(mix)
    Fm, dbm = features(mix)
    Ft, dbt = features(total)
    loud = dbm > SILENT_DB
    d = np.array([dist(Fm[k], Ft[k]) for k in range(len(Fm)) if loud[k]])
    lvl = np.array([dbt[k] - dbm[k] for k in range(len(Fm)) if loud[k]])
    text = (
        f"Check: the song preset, summed as this page plays it, is {lu:+.1f} LU from Live's own bounce of the mix; "
        f"bar by bar the level differs by {np.median(np.abs(lvl)):.1f} dB (median) and {np.abs(lvl).max():.1f} dB (worst bar)."
    )
    print(text)
    print(
        f"bar distance to the mix: median {np.median(d):.3f}, 90% {np.quantile(d, 0.9):.3f}, max {d.max():.3f}; "
        f"peak of the sum {np.abs(total).max():.3f}, of the mix {np.abs(mix).max():.3f}"
    )
    worst = np.argsort(-np.abs(dbt - dbm) * loud)[:8]
    print("worst bars:", [(int(k) + 1, round(float(dbt[k] - dbm[k]), 1)) for k in worst])
    return text


def first_drop(song: list[dict], by_id: dict[str, dict], bars: int = 32) -> list[dict]:
    """The song preset's first `bars` bars: the regions that start in them, a loop cut short at the end."""
    keep = [
        r for r in song if r["start"] < bars and (r["start"] + r["len"] <= bars or by_id[r["clip"]]["kind"] == "loop")
    ]
    return [{**r, "len": min(r["len"], bars - r["start"])} for r in keep]


def main() -> None:
    clips: list[dict] = []
    lanes, song = [], []
    for lane, title, group, colour, stems in LANES:
        lanes.append({"id": lane, "title": title, "group": group, "color": colour})
        for si, (stem, prefix, first) in enumerate(stems):
            regions = cut_stem(lane, stem, prefix, first, clips)
            if si == 0 and lane not in SONG_ONLY_FIRST:
                song += regions
    by_id = {c["id"]: c for c in clips}
    text = check(song, by_id)
    files = {c["file"] for c in clips} | {c["tail"] for c in clips if c.get("tail")}
    for f in (DATA / "audio").glob("*.flac"):
        if f.name not in files:
            f.unlink()
    size = sum((DATA / "audio" / f).stat().st_size for f in files)
    out = {
        "set": SET,
        "made": time.strftime("%-d %b %Y"),
        "bpm": int(hw002.TEMPO_BPM),
        "rate": RATE,
        "barSeconds": BAR / RATE,
        "lanes": lanes,
        "clips": clips,
        "check": text,
        "presets": [
            {"name": "The song", "bars": 180, "regions": song},
            {"name": "First drop", "bars": 32, "regions": first_drop(song, by_id)},
        ],
    }
    (DATA / "loops.json").write_text(json.dumps(out))
    print(
        f"{len(clips)} clips ({sum(c['kind'] == 'loop' for c in clips)} loops), {len(files)} files, {size / 1e6:.1f} MB; song preset {len(song)} regions"
    )


if __name__ == "__main__":
    main()
