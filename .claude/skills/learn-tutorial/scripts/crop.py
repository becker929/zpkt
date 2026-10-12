"""Crop regions of video frames at source resolution and upscale them to read small DAW text.

    run crop.py src/<id>.mp4 --at 13.0 --box 0 0 640 40 --scale 3 --out frames/crops/c01_transport_t013.png
    run crop.py src/<id>.mp4 --spec 13.0 0 0 640 40 3 frames/crops/a.png --spec 105.5 0 690 1280 30 4 frames/crops/b.png

Coordinates are source-video pixels (check the size in meta.json). Lanczos upscale, lossless PNG.
The crop runs on RGB (format=rgb24 first): a yuv420 source refuses odd crop sizes. Truncated text
stays truncated; write '?' rather than a guess.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def crop(video: str, t: float, x: int, y: int, w: int, h: int, scale: float, out: str) -> None:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    vf = f"format=rgb24,crop={w}:{h}:{x}:{y},scale=iw*{scale}:ih*{scale}:flags=lanczos"
    subprocess.run(["nice", "-n", "10", "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t),
                    "-i", video, "-frames:v", "1", "-vf", vf, out], check=True)
    print(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--at", type=float, help="time, s")
    ap.add_argument("--box", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    ap.add_argument("--scale", type=float, default=3.0)
    ap.add_argument("--out")
    ap.add_argument("--spec", nargs=7, action="append", default=[], metavar=("T", "X", "Y", "W", "H", "SCALE", "OUT"),
                    help="one crop; repeatable")
    a = ap.parse_args()
    jobs = [(float(t), int(x), int(y), int(w), int(h), float(s), o) for t, x, y, w, h, s, o in a.spec]
    if a.at is not None:
        if not (a.box and a.out):
            ap.error("--at needs --box and --out")
        jobs.append((a.at, *a.box, a.scale, a.out))
    if not jobs:
        ap.error("give --at/--box/--out or --spec")
    for job in jobs:
        crop(a.video, *job)


if __name__ == "__main__":
    main()
