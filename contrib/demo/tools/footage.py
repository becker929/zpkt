"""Align the Live screen recordings to the reel, frame by frame.

out/footage/main.mp4 is Ableton Live playing HW002_121 from bar 1 to 182.
For every frame of a cut this picks the footage frame showing the same beat,
using the song-time fit in main.sync.json plus Live's measured display lag, and
crops Live's window (below the title bar, above the Dock).

  uv run python tools/footage.py        # the demo -> out/demo/frames/live/
  uv run python tools/footage.py long   # the 102-second cut -> out/frames/live/

Writes:
  <cut>/frames/live/fNNNN.jpg one per video frame (Live's window, 1920x925)
  out/frames/knob/kNNN.jpg    hands turning the kick sampler's Transp and Volume
  out/frames/cut/cNNN.jpg     engineer running Edit > Delete Time on bars 105-112
  out/frames/overview.jpg     the whole song, Optimize Arrangement Width
"""
import json
import pathlib
import subprocess
import sys

from edit import BAR, CUTS

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"
FOOT = OUT / "footage"
FRAMES = OUT / "frames"
FPS = 30
# Live's position display shows a beat about 0.385 s after Live reports it
# (97.1.1 first appears 0.385 s after the fit says beat 384; checked at bar 121 too)
LAG = 0.385
CROP = "crop=1920:925:0:55"  # Live's window minus its title bar


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def main_frames(edit: list, d: pathlib.Path) -> None:
    fit = json.loads((FOOT / "main.sync.json").read_text())["fit"]
    d.mkdir(parents=True, exist_ok=True)
    frame = 0
    for first, last, sid in edit:
        n = int(round((last - first + 1) * BAR * FPS))
        beat = (first - 1) * 4
        t = (beat - fit["beat_at_t0"]) / fit["beats_per_s"] + LAG
        ff("-ss", f"{t:.4f}", "-i", str(FOOT / "main.mp4"), "-frames:v", str(n), "-vf", CROP,
           "-q:v", "4", "-start_number", str(frame), str(d / "f%04d.jpg"))
        print(f"{sid:10s} bars {first}-{last}: footage {t:7.3f}s, reel frames {frame}-{frame + n - 1}")
        frame += n


def inserts() -> None:
    knob = json.loads((FOOT / "knob.sync.json").read_text())
    t0 = knob["footage_t0_wall"]
    moves = [(w - t0, tr) for w, tr, _ in knob["moves"]]
    rise = [t for t, tr in moves if tr > moves[0][1]]
    start, peak = rise[0] - 0.6, max(moves, key=lambda m: m[1])[0] + 0.5
    d = FRAMES / "knob"
    d.mkdir(parents=True, exist_ok=True)
    # 90 frames spanning the climb: the sampler panel with its Transp and Volume knobs
    speed = (peak - start) / 3.0
    ff("-ss", f"{start:.3f}", "-t", f"{peak - start:.3f}", "-i", str(FOOT / "knob.mp4"),
       "-vf", f"setpts=PTS/{speed:.4f},fps=30,crop=600:250:1080:690", "-frames:v", "90",
       "-q:v", "3", str(d / "k%03d.jpg"))
    cut = json.loads((FOOT / "cut.sync.json").read_text())
    tc = cut["cut_wall"] - cut["footage_t0_wall"]
    d = FRAMES / "cut"
    d.mkdir(parents=True, exist_ok=True)
    ff("-ss", f"{tc - 1.0:.3f}", "-i", str(FOOT / "cut.mp4"), "-frames:v", "90",
       "-vf", "crop=1220:580:380:100", "-q:v", "3", str(d / "c%03d.jpg"))
    ff("-i", str(FOOT / "overview.png"), "-vf", CROP, "-q:v", "3", str(FRAMES / "overview.jpg"))
    print(f"knob climb {start:.2f}-{peak:.2f}s (x{speed:.2f}), cut at {tc:.2f}s")


if __name__ == "__main__":
    edit, out = CUTS[sys.argv[1] if len(sys.argv) > 1 else "demo"]
    main_frames(edit, out / "frames/live")
    if not (FRAMES / "overview.jpg").exists():
        inserts()
