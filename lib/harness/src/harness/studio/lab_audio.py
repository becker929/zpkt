"""`harness lab-audio`: HW002's audio for the lab (/studio/lab/), as MP3s iPhone Safari decodes, and a manifest.

What it gathers, all outside the repo (Anthony's set, his stems and his samples):

- the stems of the canonical shape's 36 s version (kick, perc and SFX groups, and the mix; beat 0 at sample 0;
  a group that is silent in it, like the break, is left out),
- the canonical Short's own stems (batch 4.3 track 1, 30 s: real A, AB, ABC and ABCD hat bars and its splashes),
- the whole song's mix (beat 0 at sample 0), for the arrangement map,
- every audio file the set's clips play, from unmuted tracks (the collage's sources), cut to the part the set plays
  (with a margin), and where the set uses them: `uses` = [start bar, end bar, start s, end s in the file as served],
- a few kick hits cut from the kick stem, on the beat,
- the set's arrangement: every clip on every track, in bars.

Files are named by their content, so the phone caches them for good; the manifest names the current ones. Each entry
carries a few thousand samples of its start (`head`): MP3 decoders differ in how much of the encoder's delay they
trim, and the page lines the decoded audio up against `head` so the stems stay on the bar grid.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

SCRATCH = Path.home() / "_agent_scratch"
SET = SCRATCH / "HW002" / "HW002_121_full.als"
STEMS = SCRATCH / "mixclimb" / "stems-fullsong"
SHAPE = SCRATCH / "mixclimb" / "stems"         # the canonical Short (b43-01), 30 s
FULL = SCRATCH / "renders" / "hw002_121_full_aligned.wav"
RATE = 44100
HEAD = 2048                  # samples of each file's start kept for lining it up
MAX_CLIP_S = 60.0            # at most this much of a source (decoded on the phone: 60 s of stereo is 21 MB)
MARGIN_S = 10.0              # kept either side of the part of a source the set plays: room to explore
STEM_TITLES = {"kick": "Kick group", "perc": "Perc group", "sfx": "SFX group", "brk": "Break group", "mix": "Mix"}


@dataclass
class Clip:
    track: str
    group: str | None
    start: float            # beats in the arrangement
    end: float
    file: str
    file_s: tuple[float, float]   # the part of the file it plays, in seconds (through the warp markers when warped)


def arrangement(als: Path) -> tuple[float, list[dict], list[Clip]]:
    """The set's tempo, its tracks (name, group, kind, muted) and the audio and MIDI clips on its unmuted tracks."""
    live = ET.fromstring(gzip.open(als).read()).find("LiveSet")

    def v(el, path):
        x = el.find(path)
        return x.get("Value") if x is not None else None

    tracks, clips = [], []
    names = {t.get("Id"): v(t, "Name/EffectiveName") for t in live.find("Tracks")}
    for t in live.find("Tracks"):
        name = v(t, "Name/EffectiveName")
        gid = v(t, "TrackGroupId")
        group = names.get(gid) if gid and gid != "-1" else None
        muted = v(t, "DeviceChain/Mixer/Speaker/Manual") == "false"
        row = {"name": name, "group": group, "kind": t.tag.replace("Track", "").lower(), "muted": muted, "clips": []}
        tracks.append(row)
        if muted:
            continue
        for c in t.iter("AudioClip"):
            path = v(c, "SampleRef/FileRef/Path")
            start, end = float(v(c, "CurrentStart") or 0), float(v(c, "CurrentEnd") or 0)
            if path:
                clips.append(Clip(name, group, start, end, path, _file_span(c, start, end, v)))
                row["clips"].append([round(start / 4, 3), round(end / 4, 3), path])
        for c in t.iter("MidiClip"):
            start, end = float(v(c, "CurrentStart") or 0), float(v(c, "CurrentEnd") or 0)
            row["clips"].append([round(start / 4, 3), round(end / 4, 3), None])
    tempo = float(v(live, ".//Tempo/Manual") or 160)
    return tempo, tracks, clips


def _file_span(c: ET.Element, start: float, end: float, v) -> tuple[float, float]:
    """Where in its file a clip plays, in seconds. A warped clip's loop is in its own beats, mapped to the file by its
    warp markers (piecewise linear, the last segment extended); an unwarped clip's loop is in seconds and it plays at
    the file's speed (its arrangement length in beats at the set's tempo, 160 BPM)."""
    loop_start = float(v(c, "Loop/LoopStart") or 0)
    loop_end = float(v(c, "Loop/LoopEnd") or loop_start)
    looped = v(c, "Loop/LoopOn") == "true"
    if v(c, "IsWarped") != "true":
        a = loop_start
        b = loop_end if looped else a + (end - start) * 60 / 160
        return round(a, 3), round(max(b, a), 3)
    marks = sorted((float(w.get("BeatTime")), float(w.get("SecTime"))) for w in c.findall("WarpMarkers/WarpMarker"))
    if len(marks) < 2:
        marks = [(0.0, 0.0), (1.0, 60 / 160)]

    def sec(beat: float) -> float:
        for (b0, s0), (b1, s1) in zip(marks, marks[1:]):
            if beat <= b1 or (b1, s1) == marks[-1]:
                return s0 + (beat - b0) * (s1 - s0) / (b1 - b0 or 1)
        return marks[-1][1]

    a = sec(loop_start)
    b = sec(loop_end if looped else loop_start + (end - start))
    return round(max(0.0, a), 3), round(max(b, a), 3)


def decode(path: Path, seconds: float | None = None) -> np.ndarray:
    """Any audio file as float32 stereo at RATE (ffmpeg)."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path)] + (["-t", str(seconds)] if seconds else []) + \
          ["-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def mp3(x: np.ndarray, out: Path, kbps: int = 192) -> tuple[str, float]:
    """`x` as an MP3 in `out`, named by its content; returns (file name, seconds)."""
    pcm = np.clip(x, -1, 1).astype(np.float32).tobytes()
    data = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-i", "-",
                           "-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-f", "mp3", "-"],
                          input=pcm, capture_output=True, check=True).stdout
    name = hashlib.sha256(data).hexdigest()[:16] + ".mp3"
    (out / name).write_bytes(data)
    return name, round(len(x) / RATE, 3)


def head(x: np.ndarray) -> dict:
    """HEAD samples of the mono sum from the first sound, as int16 (base64), and where they start."""
    mono = x.mean(axis=1)
    loud = np.flatnonzero(np.abs(mono) > 0.01)
    at = int(loud[0]) if len(loud) else 0
    piece = mono[at:at + HEAD]
    return {"at": at, "pcm": base64.b64encode((np.clip(piece, -1, 1) * 32767).astype("<i2").tobytes()).decode()}


def kick_hits(kick: np.ndarray, bpm: float, n: int = 6) -> list[tuple[int, np.ndarray]]:
    """`n` single beats of the kick stem, the loudest on-beat hits from different bars, each faded out."""
    beat = int(round(RATE * 60 / bpm))
    mono = np.abs(kick.mean(axis=1))
    starts = range(0, len(kick) - beat, beat)
    peaks = sorted(((float(mono[s:s + 400].max()), s) for s in starts), reverse=True)
    chosen, bars = [], set()
    for level, s in peaks:
        bar = s // (beat * 4)
        if level < 0.05 or bar in bars:
            continue
        bars.add(bar)
        hit = kick[s:s + beat].copy()
        hit[-220:] *= np.linspace(1, 0, 220)[:, None]                 # 5 ms fade
        chosen.append((s // beat, hit))
        if len(chosen) == n:
            break
    return sorted(chosen, key=lambda c: c[0])


def build(out: Path, als: Path = SET, stems: Path = STEMS, full: Path = FULL, shape: Path = SHAPE) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tempo, tracks, clips = arrangement(als)
    bar_s = 4 * 60 / tempo
    manifest: dict = {"made": time.strftime("%Y-%m-%d %H:%M:%S"), "set": als.name, "bpm": tempo, "rate": RATE,
                      "bar_seconds": bar_s, "stems": [], "shape": [], "full": None, "clips": [], "kicks": [], "tracks": []}

    for key, title in STEM_TITLES.items():
        path = stems / f"{key}.wav"
        if not path.exists():
            log.warning("no stem %s", path)
            continue
        x = decode(path)
        if float(np.abs(x).max()) < 1e-4:
            log.info("stem %s is silent: left out", key)
            continue
        name, seconds = mp3(x, out)
        manifest["stems"].append({"id": key, "title": title, "file": name, "seconds": seconds,
                                  "bars": round(seconds / bar_s, 3), "head": head(x)})
        if key == "kick":
            for beat_no, hit in kick_hits(x, tempo):
                hname, hs = mp3(hit, out, 256)
                manifest["kicks"].append({"id": f"kick-{beat_no}", "title": f"Kick, beat {beat_no + 1}",
                                          "file": hname, "seconds": hs})
    for key, title in STEM_TITLES.items():
        path = shape / f"{key}.wav"
        if not path.exists():
            continue
        x = decode(path)
        if float(np.abs(x).max()) < 1e-4:
            continue
        name, seconds = mp3(x, out)
        manifest["shape"].append({"id": f"shape-{key}", "title": f"{title} (the canonical Short)", "file": name,
                                  "seconds": seconds, "bars": round(seconds / bar_s, 3), "head": head(x)})
    if full.exists():
        x = decode(full)
        name, seconds = mp3(x, out, 160)
        manifest["full"] = {"id": "full", "title": "HW002, whole song", "file": name, "seconds": seconds,
                            "bars": round(seconds / bar_s, 3), "head": head(x)}

    ids: dict[str, str] = {}
    for c in clips:
        if c.file in ids or not Path(c.file).exists():
            continue
        mine = [o for o in clips if o.file == c.file]
        x = decode(Path(c.file))
        whole = len(x) / RATE
        lo = max(0.0, min(o.file_s[0] for o in mine) - MARGIN_S)
        hi = min(whole, max(o.file_s[1] for o in mine) + MARGIN_S, lo + MAX_CLIP_S)
        if hi - lo < 1.0:                              # nothing usable found: keep the start of the file
            lo, hi = 0.0, min(whole, MAX_CLIP_S)
        x = x[int(lo * RATE):int(hi * RATE)]
        name, seconds = mp3(x, out)
        sid = f"src-{len(ids) + 1}"
        ids[c.file] = sid
        uses = [[round(o.start / 4, 2), round(o.end / 4, 2), round(max(0.0, o.file_s[0] - lo), 3),
                 round(min(hi, o.file_s[1]) - lo, 3)] for o in mine]
        manifest["clips"].append({"id": sid, "title": Path(c.file).stem, "track": c.track, "group": c.group,
                                  "file": name, "seconds": seconds, "from_s": round(lo, 3), "file_seconds": round(whole, 3),
                                  "uses": uses, "head": head(x)})
    for t in tracks:
        t["clips"] = [[a, b, ids.get(f) if f else "midi"] for a, b, f in t["clips"]]
    manifest["tracks"] = tracks

    names = {e["file"] for group in ("stems", "shape", "clips", "kicks") for e in manifest[group]}
    if manifest["full"]:
        names.add(manifest["full"]["file"])
    for old in out.glob("*.mp3"):
        if old.name not in names:
            old.unlink()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def summary(m: dict) -> str:
    lines = [f"{m['set']}: {m['bpm']:g} BPM"]
    lines += [f"  stem {s['id']:5} {s['seconds']:6.1f} s  {s['file']}" for s in m["stems"]]
    lines += [f"  {s['id']:10} {s['seconds']:6.1f} s  {s['file']}" for s in m.get("shape", [])]
    if m["full"]:
        lines.append(f"  full       {m['full']['seconds']:6.1f} s  {m['full']['file']}")
    lines += [f"  clip {c['id']:6} {c['seconds']:6.1f} s of {c['file_seconds']:6.1f} (from {c['from_s']:.1f})  "
              f"{c['title'][:40]} ({len(c['uses'])} uses)" for c in m["clips"]]
    lines.append(f"  {len(m['kicks'])} kick hits; {sum(len(t['clips']) for t in m['tracks'])} clips on "
                 f"{len(m['tracks'])} tracks")
    return "\n".join(lines)


def default_out() -> Path:
    return Path(os.environ.get("HARNESS_LAB_AUDIO", SCRATCH / "lab" / "audio"))
