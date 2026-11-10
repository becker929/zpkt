"""Read positions off a DAW screencast's pixels, calibrated by two ruler ticks.

    run pixels.py rowscan    src/<id>.mp4 --at 13.0 --y 412 --x 160 1250 --ref 161 0 547.2 4
    run pixels.py colprofile src/<id>.mp4 --at 13.0 --rect 160 380 1250 405 --ref 161 0 547.2 4

--ref XA BEAT_A XB BEAT_B: two ruler ticks read from a crop (x pixel and its beat). Calibrate on
two ticks far apart; two zoom levels should agree within about 0.02 beat.

rowscan: runs of clip-header colour along one pixel row (Live's light-blue headers: blue exceeds
red by --min-blue) -> each clip's start beat and length. A selected clip's header is grey and is
missed: check by eye.
colprofile: per-column count of dark 'ink' pixels in a waveform lane -> transient columns as
beats, with their height (a rough loudness). Timing is good; loudness is only relative.
"""

from __future__ import annotations

import argparse
import subprocess


def grab(video: str, t: float, x: int, y: int, w: int, h: int, fmt: str) -> bytes:
    return subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", str(t), "-i", video,
                           "-frames:v", "1", "-vf", f"format={fmt},crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-"],
                          capture_output=True, check=True).stdout


def rowscan(a) -> None:
    x0, x1 = a.x
    raw = grab(a.video, a.at, x0, a.y, x1 - x0, 1, "rgb24")
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    mask = [(b - r) >= a.min_blue for r, g, b in px]
    xa, ba, xb, bb = a.ref
    ppb = (xb - xa) / (bb - ba)
    runs, start = [], None
    for i, m in enumerate(mask + [False]):
        if m and start is None:
            start = i
        elif not m and start is not None:
            runs.append((start + x0, i - 1 + x0))
            start = None
    print(f"t={a.at} y={a.y} {ppb:.2f} px/beat")
    for s, e in runs:
        if e - s >= 3:
            print(f"x {s:4d}-{e:4d}  start beat {ba + (s - xa) / ppb:7.3f}  length {(e - s + 1) / ppb:6.3f} beats")


def colprofile(a) -> None:
    x0, y0, x1, y1 = a.rect
    w, h = x1 - x0, y1 - y0
    raw = grab(a.video, a.at, x0, y0, w, h, "gray")
    prof = [sum(1 for y in range(h) if raw[y * w + x] < a.dark) for x in range(w)]
    top = max(prof) or 1
    xa, ba, xb, bb = a.ref
    ppb = (xb - xa) / (bb - ba)
    print(f"t={a.at} lane x{x0}-{x1} y{y0}-{y1}, {ppb:.2f} px/beat, max ink {top}")
    i = 0
    while i < w:
        if prof[i] >= a.min * top:
            j = i
            while j + 1 < w and prof[j + 1] >= a.min * top * 0.5:
                j += 1
            pk = max(range(i, j + 1), key=lambda k: prof[k])
            s = i
            while s > 0 and prof[s - 1] > 0.15 * top:  # back to where the ink starts rising
                s -= 1
            print(f"onset x {s + x0:4d}  beat {ba + (s + x0 - xa) / ppb:7.3f}   peak x {pk + x0:4d} ink {prof[pk]:3d}")
            i = j + 1
        else:
            i += 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("rowscan", "colprofile"):
        p = sub.add_parser(name)
        p.add_argument("video")
        p.add_argument("--at", type=float, required=True, help="time, s")
        p.add_argument("--ref", type=float, nargs=4, required=True, metavar=("XA", "BEAT_A", "XB", "BEAT_B"))
        if name == "rowscan":
            p.add_argument("--y", type=int, required=True)
            p.add_argument("--x", type=int, nargs=2, required=True, metavar=("X0", "X1"))
            p.add_argument("--min-blue", type=int, default=25)
        else:
            p.add_argument("--rect", type=int, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"),
                           help="corners (crop.py --box takes X Y W H instead)")
            p.add_argument("--dark", type=int, default=60, help="grey level counted as ink")
            p.add_argument("--min", type=float, default=0.35, help="onset threshold, fraction of max ink")
    a = ap.parse_args()
    rowscan(a) if a.cmd == "rowscan" else colprofile(a)


if __name__ == "__main__":
    main()
